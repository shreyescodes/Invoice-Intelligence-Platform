from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from app.models import CheckStatus, Vendor
from app.services.erp import PurchaseOrder, PurchaseOrderItem
from app.services.extraction import ExtractedLine, ExtractionResult
from app.services.validation import DuplicateCandidate, ValidationContext, validate
from app.services.vendors import VendorMatch, normalize_name, normalize_tax_id

TODAY = date(2026, 10, 29)
VENDOR = Vendor(id=uuid.uuid4(), erp_id="100010", name="Kaveri Industrial Components Ltd", tax_id="29AABCK4321P1Z9")
PO = PurchaseOrder(
    number="4500012101",
    supplier_id="100010",
    currency="INR",
    order_date=date(2026, 9, 22),
    items=(
        PurchaseOrderItem(
            "10", "Hydraulic hose assembly 3/4 in", Decimal(40), "EA", Decimal("1450.00"), Decimal(40), Decimal(0)
        ),
        PurchaseOrderItem(
            "20", "Inductive proximity sensor M18", Decimal(10), "EA", Decimal("2350.00"), Decimal(10), Decimal(4)
        ),
    ),
)


def extraction(**overrides: object) -> ExtractionResult:
    result = ExtractionResult(
        method="test",
        vendor_name="Kaveri Industrial Components Ltd",
        vendor_tax_id="29AABCK4321P1Z9",
        invoice_number="KIC/26-27/0412",
        po_number="4500012101",
        invoice_date=TODAY - timedelta(days=3),
        due_date=TODAY + timedelta(days=42),
        subtotal=Decimal("72100.00"),
        tax_amount=Decimal("12978.00"),
        total_amount=Decimal("85078.00"),
        line_items=[
            ExtractedLine("Hydraulic hose assembly 3/4 in", Decimal(40), Decimal("1450.00"), Decimal("58000.00")),
            ExtractedLine("Proximity sensor M18 (inductive)", Decimal(6), Decimal("2350.00"), Decimal("14100.00")),
        ],
    )
    for key, value in overrides.items():
        setattr(result, key, value)
    return result


def run(
    ex: ExtractionResult | None = None,
    *,
    vendor: VendorMatch | None = None,
    po: PurchaseOrder | None = PO,
    duplicates: list[DuplicateCandidate] | None = None,
) -> dict[str, tuple[CheckStatus, str]]:
    report = validate(
        ValidationContext(
            extraction=ex or extraction(),
            vendor=vendor or VendorMatch(VENDOR, "tax_id", 100),
            purchase_order=po,
            duplicates=duplicates or [],
            today=TODAY,
            price_tolerance_pct=Decimal("2.0"),
            amount_tolerance=Decimal("1.00"),
        )
    )
    return {c.code: (c.status, c.message) for c in report.checks}


def test_clean_invoice_passes_every_check() -> None:
    checks = run()
    assert {status for status, _ in checks.values()} == {CheckStatus.PASS}
    assert set(checks) >= {
        "REQUIRED_FIELDS",
        "VENDOR_MATCH",
        "DUPLICATE",
        "LINE_TOTALS",
        "INVOICE_TOTAL",
        "TAX_RATE",
        "DATES",
        "PO_MATCH",
        "PRICE_MATCH",
        "GOODS_RECEIPT",
    }


def test_price_variance_beyond_tolerance_fails() -> None:
    ex = extraction(
        line_items=[
            ExtractedLine("Hydraulic hose assembly 3/4 in", Decimal(40), Decimal("1595.00"), Decimal("63800.00")),
        ],
        subtotal=Decimal("63800.00"),
        tax_amount=Decimal("11484.00"),
        total_amount=Decimal("75284.00"),
    )
    status, message = run(ex)["PRICE_MATCH"]
    assert status is CheckStatus.FAIL
    assert "+10.0%" in message


def test_goods_receipt_counts_previously_invoiced_quantity() -> None:
    ex = extraction(
        line_items=[
            ExtractedLine("Inductive proximity sensor M18", Decimal(7), Decimal("2350.00"), Decimal("16450.00")),
        ],
        subtotal=Decimal("16450.00"),
        tax_amount=Decimal("2961.00"),
        total_amount=Decimal("19411.00"),
    )
    status, message = run(ex)["GOODS_RECEIPT"]
    assert status is CheckStatus.FAIL
    assert "only 6 received and not yet invoiced" in message


def test_line_totals_mismatch_fails() -> None:
    status, message = run(
        extraction(subtotal=Decimal("72300.00"), tax_amount=Decimal("13014.00"), total_amount=Decimal("85314.00"))
    )["LINE_TOTALS"]
    assert status is CheckStatus.FAIL
    assert "72,100.00" in message


def test_invoice_total_mismatch_fails() -> None:
    assert run(extraction(total_amount=Decimal("90000.00")))["INVOICE_TOTAL"][0] is CheckStatus.FAIL


def test_unusual_tax_rate_warns() -> None:
    status, _ = run(extraction(tax_amount=Decimal("10000.00"), total_amount=Decimal("82100.00")))["TAX_RATE"]
    assert status is CheckStatus.WARN


def test_missing_and_unknown_po() -> None:
    assert run(extraction(po_number=None), po=None)["PO_MATCH"][0] is CheckStatus.FAIL
    status, message = run(po=None)["PO_MATCH"]
    assert status is CheckStatus.FAIL and "does not exist" in message


def test_po_of_another_supplier_fails() -> None:
    other = PurchaseOrder("4500012101", "100099", "INR", None, PO.items)
    status, message = run(po=other)["PO_MATCH"]
    assert status is CheckStatus.FAIL and "belongs to supplier 100099" in message


def test_unknown_vendor_fails_and_name_match_warns() -> None:
    assert run(vendor=VendorMatch(None, None))["VENDOR_MATCH"][0] is CheckStatus.FAIL
    assert run(vendor=VendorMatch(VENDOR, "name", 93))["VENDOR_MATCH"][0] is CheckStatus.WARN


def test_duplicates() -> None:
    exact = DuplicateCandidate("x", "KIC/26-27/0412", Decimal("1"), TODAY, "posted", exact=True)
    similar = DuplicateCandidate("y", "KIC/26-27/0400", Decimal("1"), TODAY, "posted", exact=False)
    assert run(duplicates=[exact])["DUPLICATE"][0] is CheckStatus.FAIL
    assert run(duplicates=[similar])["DUPLICATE"][0] is CheckStatus.WARN


def test_dates() -> None:
    status, message = run(extraction(invoice_date=TODAY + timedelta(days=3), due_date=TODAY))["DATES"]
    assert status is CheckStatus.WARN
    assert "future" in message and "before the invoice date" in message


def test_required_fields() -> None:
    status, message = run(extraction(invoice_number=None, total_amount=None))["REQUIRED_FIELDS"]
    assert status is CheckStatus.FAIL
    assert "invoice number" in message and "total amount" in message


def test_normalisation_helpers() -> None:
    assert normalize_tax_id(" 29aabck4321p1z9 ") == "29AABCK4321P1Z9"
    assert normalize_tax_id("") is None
    assert normalize_name("Ganesh Freight & Logistics LLP") == "ganesh freight and logistics"
