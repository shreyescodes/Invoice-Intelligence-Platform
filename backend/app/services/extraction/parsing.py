"""Field extraction from invoice text.

Works on the text layer of digitally generated PDFs, which covers most invoices that come out of
billing systems. Header fields come from `fields.extract_header` (multilingual labels, values beside
or below their label, totals chosen by consistency). Line items come from ruled tables or text rows.
Every field gets a confidence; fields that agree with each other (lines sum to the subtotal, subtotal
plus tax equals the total) are boosted.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from datetime import date
from decimal import Decimal, InvalidOperation

from app.services.extraction.base import ExtractedLine, ExtractionResult
from app.services.extraction.fields import extract_header
from app.services.extraction.locale_formats import find_amounts, find_dates, normalize_text

LABELLED = 0.95
CROSS_CHECKED = 0.99
GUESSED = 0.65
_TOLERANCE = Decimal("1.00")

# Rows that end the line-item table.
_SUBTOTAL_RE = re.compile(
    r"\b(?:sub[\s-]?total|taxable\s+(?:value|amount)|net\s+(?:amount|total)|total\s+before\s+tax|zwischensumme|"
    r"nettobetrag|summe\s+netto|total\s+h\.?t\.?|sous[\s-]total|subtotaal)\b",
    re.IGNORECASE,
)
_PLAIN_TOTAL_RE = re.compile(r"^\s*(?:total|totaal|summe|gesamt)\b(?!\s+(?:tax|gst|vat|qty|quantity|items?))", re.I)
_GRAND_TOTAL_RE = re.compile(
    r"\b(?:grand\s+total|amount\s+(?:due|payable)|gesamtbetrag|total\s+ttc|te\s+betalen)\b", re.I
)


def parse_amount(text: str) -> Decimal | None:
    found = next(find_amounts(text), None)
    return found[0] if found else None


def parse_date(text: str) -> date | None:
    found = next(find_dates(text), None)
    return found[0] if found else None


def detect_currency(text: str, default: str) -> str:
    counts = {
        "INR": len(re.findall(r"\bINR\b|\bRs\.?(?=\s|\d)|₹", text)),
        "USD": len(re.findall(r"\bUSD\b|US\$|(?<![A-Z])\$", text)),
        "EUR": len(re.findall(r"\bEUR\b|€", text)),
        "GBP": len(re.findall(r"\bGBP\b|£", text)),
        "CHF": len(re.findall(r"\bCHF\b", text)),
    }
    best, hits = max(counts.items(), key=lambda kv: kv[1])
    return best if hits else default


def _lines(text: str) -> list[str]:
    return [re.sub(r"[ 	]+", " ", line).strip() for line in text.splitlines() if line.strip()]


_ITEM_HEADER_RE = re.compile(r"\b(?:description|particulars|item|product|service)s?\b", re.IGNORECASE)
_ITEM_NUMBERS = (
    r"(?P<qty>\d+(?:\.\d+)?)\s+(?:[A-Za-z]{2,6}\.?\s+)?"
    r"(?P<price>\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)\s+"
    r"(?P<amount>\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)$"
)
# With an HSN/SAC column the code sits between description and quantity; without one, a trailing
# number in the description ("Hosting - Oct 2026") must stay part of the description.
_ITEM_LINE_WITH_HSN_RE = re.compile(r"^(?:\d{1,3}[.)]?\s+)?(?P<desc>[A-Za-z].*?)\s+(?P<hsn>\d{4,8})\s+" + _ITEM_NUMBERS)
_ITEM_LINE_RE = re.compile(r"^(?:\d{1,3}[.)]?\s+)?(?P<desc>[A-Za-z].*?)\s+" + _ITEM_NUMBERS)
_HSN_HEADER_RE = re.compile(r"\b(?:hsn|sac)\b", re.IGNORECASE)


def parse_line_items_from_text(lines: Sequence[str]) -> list[ExtractedLine]:
    items: list[ExtractedLine] = []
    in_table = False
    has_hsn = False
    for line in lines:
        if not in_table:
            in_table = bool(_ITEM_HEADER_RE.search(line) and re.search(r"amount|total|value", line, re.I))
            has_hsn = bool(in_table and _HSN_HEADER_RE.search(line))
            continue
        if _SUBTOTAL_RE.search(line) or _PLAIN_TOTAL_RE.search(line) or _GRAND_TOTAL_RE.search(line):
            break
        parsed = _parse_item_line(line, has_hsn)
        if parsed:
            items.append(parsed)
    return items


def _parse_item_line(line: str, has_hsn: bool = False) -> ExtractedLine | None:
    match = (_ITEM_LINE_WITH_HSN_RE if has_hsn else _ITEM_LINE_RE).match(line)
    if not match and has_hsn:
        match = _ITEM_LINE_RE.match(line)
    if not match:
        return None
    try:
        qty = Decimal(match.group("qty"))
        price = Decimal(match.group("price").replace(",", ""))
        amount = Decimal(match.group("amount").replace(",", ""))
    except InvalidOperation:
        return None
    if qty <= 0 or abs(qty * price - amount) > _TOLERANCE:
        return None
    return ExtractedLine(match.group("desc").strip(" -"), qty, price, amount)


def line_items_from_table(rows: Iterable[Sequence[str | None]]) -> list[ExtractedLine]:
    """Map a table (first row = header) to line items by recognising column headings."""
    table: list[list[str]] = [[(cell or "").strip() for cell in row] for row in rows]
    header_index = next((i for i, row in enumerate(table) if any(_ITEM_HEADER_RE.search(c) for c in row)), None)
    if header_index is None:
        return []
    header = [c.lower() for c in table[header_index]]

    def column(*patterns: str) -> int | None:
        for pattern in patterns:
            for idx, name in enumerate(header):
                if re.search(pattern, name):
                    return idx
        return None

    desc_col = column(r"desc|particular|item|product|service")
    qty_col = column(r"\bqty\b|quantity|units?\b|hours")
    price_col = column(r"unit\s*price|rate|price|unit\s*cost")
    amount_col = column(r"amount|line\s*total|total|value")
    if None in (desc_col, qty_col, price_col, amount_col):
        return []

    items: list[ExtractedLine] = []
    for row in table[header_index + 1 :]:
        if len(row) <= max(c for c in (desc_col, qty_col, price_col, amount_col) if c is not None):
            continue
        description = row[desc_col or 0].replace("\n", " ").strip()
        qty = parse_amount(row[qty_col or 0])
        price = parse_amount(row[price_col or 0])
        amount = parse_amount(row[amount_col or 0])
        if not description or qty is None or price is None or amount is None or qty <= 0:
            continue
        items.append(ExtractedLine(description, qty, price, amount))
    return items


def cross_check(result: ExtractionResult) -> None:
    sub, tax, total = result.subtotal, result.tax_amount, result.total_amount
    if result.line_items:
        line_sum = sum((i.amount for i in result.line_items), Decimal("0"))
        if sub is None:
            result.subtotal = sub = line_sum
            result.field_confidence["subtotal"] = GUESSED + 0.15
        elif abs(line_sum - sub) <= _TOLERANCE:
            result.field_confidence["subtotal"] = CROSS_CHECKED
    if sub is not None and total is not None:
        if tax is None and total >= sub:
            result.tax_amount = tax = total - sub
            result.field_confidence["tax_amount"] = GUESSED + 0.15
        if tax is not None and abs(sub + tax - total) <= _TOLERANCE:
            for name in ("subtotal", "tax_amount", "total_amount"):
                result.field_confidence[name] = max(result.field_confidence.get(name, 0.0), CROSS_CHECKED)
    elif sub is not None and tax is not None and total is None:
        result.total_amount = sub + tax
        result.field_confidence["total_amount"] = GUESSED


def parse_invoice_text(
    text: str,
    *,
    method: str,
    default_currency: str = "INR",
    table_rows: Sequence[Sequence[Sequence[str | None]]] = (),
    layout_text: str | None = None,
) -> ExtractionResult:
    text = normalize_text(text)
    result = ExtractionResult(method=method, raw_text=text)
    lines = _lines(text)
    if not lines:
        result.warnings.append("Document has no text layer (scanned image?)")
        return result

    result.currency = detect_currency(text, default_currency)
    layout_lines = normalize_text(layout_text).splitlines() if layout_text else []
    extract_header(lines, layout_lines, result)

    for table in table_rows:
        items = line_items_from_table(table)
        if items:
            result.line_items = items
            break
    if not result.line_items:
        result.line_items = parse_line_items_from_text(lines)

    cross_check(result)
    return result
