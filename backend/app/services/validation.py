"""Validation rules run on every extracted invoice.

Each rule returns pass / warn / fail with a human-readable message that is shown to reviewers.
The purchase-order rules implement the standard AP 3-way match: invoice vs PO price (2-way) and
invoice vs goods received but not yet invoiced (3-way).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from rapidfuzz import fuzz

from app.models import CheckStatus
from app.services.erp import PurchaseOrder, PurchaseOrderItem
from app.services.extraction import ExtractedLine, ExtractionResult
from app.services.vendors import VendorMatch

GST_SLABS = (Decimal("0"), Decimal("5"), Decimal("12"), Decimal("18"), Decimal("28"))
TAX_RATE_TOLERANCE_PP = Decimal("0.25")
DESCRIPTION_MATCH_THRESHOLD = 70
STALE_AFTER_DAYS = 180


@dataclass(frozen=True, slots=True)
class CheckOutcome:
    code: str
    status: CheckStatus
    message: str
    details: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class DuplicateCandidate:
    invoice_id: str
    invoice_number: str | None
    total_amount: Decimal | None
    invoice_date: date | None
    status: str
    exact: bool


@dataclass(slots=True)
class ValidationReport:
    checks: list[CheckOutcome] = field(default_factory=list)
    line_po_items: dict[int, str] = field(default_factory=dict)  # invoice line index -> PO item

    def add(self, code: str, status: CheckStatus, message: str, **details: Any) -> None:
        self.checks.append(CheckOutcome(code, status, message, details or None))

    @property
    def passed(self) -> bool:
        return all(c.status is CheckStatus.PASS for c in self.checks)

    def by_status(self, status: CheckStatus) -> list[CheckOutcome]:
        return [c for c in self.checks if c.status is status]


@dataclass(frozen=True, slots=True)
class ValidationContext:
    extraction: ExtractionResult
    vendor: VendorMatch
    purchase_order: PurchaseOrder | None
    duplicates: list[DuplicateCandidate]
    today: date
    price_tolerance_pct: Decimal
    amount_tolerance: Decimal


def _money(value: Decimal | None) -> str:
    return "n/a" if value is None else f"{value:,.2f}"


def validate(ctx: ValidationContext) -> ValidationReport:
    report = ValidationReport()
    _required_fields(ctx, report)
    _vendor(ctx, report)
    _duplicates(ctx, report)
    _arithmetic(ctx, report)
    _tax_rate(ctx, report)
    _dates(ctx, report)
    _purchase_order(ctx, report)
    return report


def _required_fields(ctx: ValidationContext, report: ValidationReport) -> None:
    ex = ctx.extraction
    missing = [
        label
        for label, value in (
            ("invoice number", ex.invoice_number),
            ("invoice date", ex.invoice_date),
            ("total amount", ex.total_amount),
            ("vendor", ex.vendor_name or ex.vendor_tax_id),
        )
        if not value
    ]
    if missing:
        report.add(
            "REQUIRED_FIELDS",
            CheckStatus.FAIL,
            f"Could not read {', '.join(missing)} from the document",
            missing=missing,
        )
    else:
        report.add("REQUIRED_FIELDS", CheckStatus.PASS, "All mandatory header fields were extracted")


def _vendor(ctx: ValidationContext, report: ValidationReport) -> None:
    ex = ctx.extraction
    match = ctx.vendor
    if match.vendor is None:
        label = ex.vendor_name or "Unknown vendor"
        suffix = f" (tax ID {ex.vendor_tax_id})" if ex.vendor_tax_id else ""
        report.add("VENDOR_MATCH", CheckStatus.FAIL, f"{label}{suffix} is not in the vendor master")
    elif match.method == "name":
        report.add(
            "VENDOR_MATCH",
            CheckStatus.WARN,
            f"Matched to {match.vendor.name} by name only ({match.score:.0f}% similar); tax ID not confirmed",
            vendor_erp_id=match.vendor.erp_id,
        )
    else:
        report.add(
            "VENDOR_MATCH",
            CheckStatus.PASS,
            f"Matched to vendor {match.vendor.erp_id} by tax ID",
            vendor_erp_id=match.vendor.erp_id,
        )


def _duplicates(ctx: ValidationContext, report: ValidationReport) -> None:
    exact = [d for d in ctx.duplicates if d.exact]
    similar = [d for d in ctx.duplicates if not d.exact]
    if exact:
        report.add(
            "DUPLICATE",
            CheckStatus.FAIL,
            f"Invoice number {exact[0].invoice_number} was already received from this vendor",
            duplicate_of=exact[0].invoice_id,
        )
    elif similar:
        report.add(
            "DUPLICATE",
            CheckStatus.WARN,
            f"Possible duplicate: same amount and date range as invoice {similar[0].invoice_number}",
            duplicate_of=similar[0].invoice_id,
        )
    else:
        report.add("DUPLICATE", CheckStatus.PASS, "No duplicate found for this vendor")


def _arithmetic(ctx: ValidationContext, report: ValidationReport) -> None:
    ex, tol = ctx.extraction, ctx.amount_tolerance
    if ex.line_items and ex.subtotal is not None:
        line_sum = sum((li.amount for li in ex.line_items), Decimal("0"))
        if abs(line_sum - ex.subtotal) > tol:
            report.add(
                "LINE_TOTALS",
                CheckStatus.FAIL,
                f"Line items add up to {_money(line_sum)} but the subtotal is {_money(ex.subtotal)}",
                line_sum=str(line_sum),
                subtotal=str(ex.subtotal),
            )
        else:
            bad_lines = [
                i + 1 for i, li in enumerate(ex.line_items) if abs(li.quantity * li.unit_price - li.amount) > tol
            ]
            if bad_lines:
                report.add(
                    "LINE_TOTALS",
                    CheckStatus.FAIL,
                    f"Quantity x price does not equal the amount on line(s) {bad_lines}",
                    lines=bad_lines,
                )
            else:
                report.add("LINE_TOTALS", CheckStatus.PASS, f"{len(ex.line_items)} line items add up to the subtotal")
    elif not ex.line_items:
        report.add("LINE_TOTALS", CheckStatus.WARN, "No line items could be extracted")

    if ex.subtotal is not None and ex.tax_amount is not None and ex.total_amount is not None:
        expected = ex.subtotal + ex.tax_amount
        if abs(expected - ex.total_amount) > tol:
            report.add(
                "INVOICE_TOTAL",
                CheckStatus.FAIL,
                f"Subtotal + tax = {_money(expected)}, but the invoice total is {_money(ex.total_amount)}",
            )
        else:
            report.add("INVOICE_TOTAL", CheckStatus.PASS, "Subtotal plus tax equals the invoice total")


def _tax_rate(ctx: ValidationContext, report: ValidationReport) -> None:
    ex = ctx.extraction
    if not ex.subtotal or ex.tax_amount is None:
        return
    rate = (ex.tax_amount / ex.subtotal * 100).quantize(Decimal("0.01"))
    nearest = min(GST_SLABS, key=lambda slab: abs(slab - rate))
    if abs(nearest - rate) <= TAX_RATE_TOLERANCE_PP:
        report.add("TAX_RATE", CheckStatus.PASS, f"Tax rate {nearest}% matches a GST slab", rate=str(rate))
    else:
        report.add(
            "TAX_RATE", CheckStatus.WARN, f"Effective tax rate {rate}% does not match any GST slab", rate=str(rate)
        )


def _dates(ctx: ValidationContext, report: ValidationReport) -> None:
    ex = ctx.extraction
    if ex.invoice_date is None:
        return
    problems: list[str] = []
    if ex.invoice_date > ctx.today:
        problems.append(f"invoice is dated in the future ({ex.invoice_date:%d %b %Y})")
    if ex.invoice_date < ctx.today - timedelta(days=STALE_AFTER_DAYS):
        problems.append(f"invoice is more than {STALE_AFTER_DAYS} days old")
    if ex.due_date is not None and ex.due_date < ex.invoice_date:
        problems.append("due date is before the invoice date")
    if problems:
        message = "; ".join(problems)
        report.add("DATES", CheckStatus.WARN, message[0].upper() + message[1:])
    else:
        report.add("DATES", CheckStatus.PASS, "Invoice and due dates are plausible")


def _match_lines(lines: list[ExtractedLine], items: tuple[PurchaseOrderItem, ...]) -> dict[int, PurchaseOrderItem]:
    matches: dict[int, PurchaseOrderItem] = {}
    for index, line in enumerate(lines):
        best: tuple[float, PurchaseOrderItem] | None = None
        for item in items:
            score = fuzz.token_set_ratio(line.description.lower(), item.description.lower())
            if item.net_price and abs(line.unit_price - item.net_price) / item.net_price < Decimal("0.001"):
                score += 10  # identical price is strong evidence
            if best is None or score > best[0]:
                best = (score, item)
        if best is not None and best[0] >= DESCRIPTION_MATCH_THRESHOLD:
            matches[index] = best[1]
    return matches


def _purchase_order(ctx: ValidationContext, report: ValidationReport) -> None:
    ex = ctx.extraction
    if not ex.po_number:
        report.add("PO_MATCH", CheckStatus.FAIL, "No purchase order number on the invoice; needs manual coding")
        return
    po = ctx.purchase_order
    if po is None:
        report.add("PO_MATCH", CheckStatus.FAIL, f"Purchase order {ex.po_number} does not exist in the ERP")
        return

    vendor = ctx.vendor.vendor
    problems: list[str] = []
    if vendor is not None and po.supplier_id != vendor.erp_id:
        problems.append(f"PO {po.number} belongs to supplier {po.supplier_id}, not {vendor.erp_id}")
    if po.currency != ex.currency:
        problems.append(f"PO currency is {po.currency} but the invoice is in {ex.currency}")
    if problems:
        report.add("PO_MATCH", CheckStatus.FAIL, "; ".join(problems), po_number=po.number)
        return

    matches = _match_lines(ex.line_items, po.items)
    report.line_po_items = {i: item.item for i, item in matches.items()}
    unmatched = [i + 1 for i in range(len(ex.line_items)) if i not in matches]
    if unmatched:
        report.add(
            "PO_MATCH",
            CheckStatus.WARN,
            f"Line(s) {unmatched} could not be matched to a PO {po.number} item",
            po_number=po.number,
        )
    else:
        report.add("PO_MATCH", CheckStatus.PASS, f"All lines matched to PO {po.number}", po_number=po.number)

    price_issues: list[dict[str, str]] = []
    for index, item in matches.items():
        line = ex.line_items[index]
        variance = (line.unit_price - item.net_price) / item.net_price * 100 if item.net_price else Decimal("0")
        if abs(variance) > ctx.price_tolerance_pct:
            price_issues.append(
                {
                    "line": str(index + 1),
                    "po_item": item.item,
                    "invoice_price": str(line.unit_price),
                    "po_price": str(item.net_price),
                    "variance_pct": f"{variance:.1f}",
                }
            )
    if price_issues:
        first = price_issues[0]
        report.add(
            "PRICE_MATCH",
            CheckStatus.FAIL,
            f"Line {first['line']} is billed at {_money(Decimal(first['invoice_price']))} vs PO price "
            f"{_money(Decimal(first['po_price']))} ({float(first['variance_pct']):+.1f}%)",
            lines=price_issues,
        )
    elif matches:
        report.add("PRICE_MATCH", CheckStatus.PASS, f"Unit prices are within {ctx.price_tolerance_pct}% of the PO")

    billed: dict[str, Decimal] = defaultdict(Decimal)
    for index, item in matches.items():
        billed[item.item] += ex.line_items[index].quantity
    by_item = {i.item: i for i in po.items}
    receipt_issues = [
        {"po_item": item_no, "billed": str(qty), "open": str(by_item[item_no].open_quantity)}
        for item_no, qty in billed.items()
        if qty > by_item[item_no].open_quantity
    ]
    if receipt_issues:
        first_issue = receipt_issues[0]
        item = by_item[first_issue["po_item"]]
        report.add(
            "GOODS_RECEIPT",
            CheckStatus.FAIL,
            f"Billed {Decimal(first_issue['billed']).normalize()} {item.unit} of '{item.description}' but only "
            f"{item.open_quantity.normalize()} received and not yet invoiced",
            items=receipt_issues,
        )
    elif matches:
        report.add("GOODS_RECEIPT", CheckStatus.PASS, "Billed quantities are covered by goods receipts")
