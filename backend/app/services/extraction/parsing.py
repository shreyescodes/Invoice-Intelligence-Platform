"""Rule-based field extraction from invoice text.

Works on the text layer of digitally generated PDFs, which covers most invoices that come out of
billing systems. Every field gets a confidence: high for values found next to an explicit label,
lower for positional guesses, and a boost when independent fields agree (line items sum to the
subtotal, subtotal + tax equals the total).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.services.extraction.base import ExtractedLine, ExtractionResult

LABELLED = 0.95
CROSS_CHECKED = 0.99
GUESSED = 0.65

_CURRENCY = r"(?:INR|Rs\.?|₹|USD|US\$|\$|EUR|€|GBP|£)"
_AMOUNT = r"-?\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?|-?\d+(?:\.\d{1,2})?"
_AMOUNT_RE = re.compile(rf"{_CURRENCY}?\s*({_AMOUNT})")
_TRAILING_AMOUNT_RE = re.compile(rf"(?:{_CURRENCY}\s*)?({_AMOUNT})\s*(?:{_CURRENCY})?\s*$")

_DATE = (
    r"\d{4}-\d{1,2}-\d{1,2}"
    r"|\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}"
    r"|\d{1,2}(?:st|nd|rd|th)?[\s\-]+[A-Za-z]{3,9}\.?[\s\-,]+\d{4}"
    r"|[A-Za-z]{3,9}\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}"
)
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%d/%m/%y",
    "%d-%m-%y",
    "%d %b %Y",
    "%d %B %Y",
    "%d-%b-%Y",
    "%d-%B-%Y",
    "%b %d %Y",
    "%B %d %Y",
)

_GSTIN_RE = re.compile(r"\b(\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z])\b")
_TAX_ID_LABEL_RE = re.compile(
    r"(?:GSTIN|GST\s*(?:No|Number|IN)|VAT\s*(?:No|Number|ID|Reg)|Tax\s*(?:ID|No|Number)|TIN)\.?\s*[:#\-]?\s*"
    r"([A-Z0-9][A-Z0-9\-]{6,20})",
    re.IGNORECASE,
)
_INVOICE_NO_RE = re.compile(
    r"\b(?:tax\s+)?(?:invoice|inv|bill)\s*(?:no\.?|number|num\.?|#|ref(?:erence)?)\s*[:#.\-]?\s*"
    r"([A-Z0-9][A-Z0-9/\-_.]{1,40})",
    re.IGNORECASE,
)
_PO_RE = re.compile(
    r"\b(?:p\.?\s?o\.?(?![a-z])|purchase\s+order|order\s+ref(?:erence)?)\s*(?:no\.?|number|#|ref\.?)?\s*[:#.\-]?\s*"
    r"([A-Z0-9][A-Z0-9/\-]{3,30})",
    re.IGNORECASE,
)
_DATED_LABEL_RE = re.compile(
    rf"\b((?:invoice|inv\.?|bill|issue|due|payment\s+due|pay\s+by|document)?\s*date(?:\s+of\s+issue)?"
    rf"|dated|due\s+on|payment\s+due|pay\s+by)\s*[:\-]?\s*({_DATE})",
    re.IGNORECASE,
)
_BILL_TO_RE = re.compile(r"\b(?:bill(?:ed)?\s+to|buyer|customer|sold\s+to|ship(?:ped)?\s+to)\b", re.IGNORECASE)
_VENDOR_LABEL_RE = re.compile(r"^\s*(?:from|supplier|vendor|seller)\s*[:\-]\s*(.{3,120})$", re.IGNORECASE)
_NOT_A_NAME_RE = re.compile(
    r"^(?:tax\s+invoice|invoice|bill|receipt|original|duplicate|page\s+\d|gstin|pan|cin|phone|tel|email|"
    r"www\.|http|\d)",
    re.IGNORECASE,
)

_SUBTOTAL_RE = re.compile(
    r"\b(?:sub[\s\-]?total|taxable\s+(?:value|amount)|net\s+(?:amount|total)|total\s+before\s+tax|"
    r"amount\s+before\s+tax)\b",
    re.IGNORECASE,
)
_TAX_LINE_RE = re.compile(r"\b(?:cgst|sgst|igst|utgst|gst|vat|sales\s+tax|tax)\b", re.IGNORECASE)
_TOTAL_TAX_RE = re.compile(r"\btotal\s+(?:tax|gst|vat)\b|\btax\s+(?:amount|total)\b", re.IGNORECASE)
_GRAND_TOTAL_RE = re.compile(
    r"\b(?:grand\s+total|total\s+amount\s+(?:due|payable)|amount\s+(?:due|payable)|invoice\s+total|"
    r"total\s+payable|balance\s+due|total\s+due|total\s+\(?(?:incl|inc)\.?)",
    re.IGNORECASE,
)
_PLAIN_TOTAL_RE = re.compile(r"^\s*total\b(?!\s+(?:tax|gst|vat|qty|quantity|items?))", re.IGNORECASE)
_RATE_RE = re.compile(r"@?\s*\d{1,2}(?:\.\d{1,2})?\s*%")
# Labels that often share a visual line with the vendor name in two-column headers.
_HEADER_LABEL_SPLIT_RE = re.compile(
    r"\s+(?:tax\s+invoice|invoice|inv\.?\s*(?:no|#)|bill\s+(?:no|date)|date|gstin|p\.?o\.?\s|original)\b.*$",
    re.IGNORECASE,
)

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
_TOLERANCE = Decimal("1.00")


def parse_amount(text: str) -> Decimal | None:
    match = _AMOUNT_RE.search(text)
    if not match:
        return None
    try:
        return Decimal(match.group(1).replace(",", ""))
    except InvalidOperation:
        return None


def parse_date(text: str) -> date | None:
    cleaned = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", text.strip())
    cleaned = re.sub(r"[,.]", " ", cleaned) if re.search(r"[A-Za-z]", cleaned) else cleaned
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    for fmt in _DATE_FORMATS:
        candidate = cleaned.replace("-", " ") if "%b" in fmt or "%B" in fmt else cleaned
        candidate_fmt = fmt.replace("-", " ") if "%b" in fmt or "%B" in fmt else fmt
        try:
            return datetime.strptime(candidate, candidate_fmt).date()  # noqa: DTZ007 - dates only
        except ValueError:
            continue
    return None


def detect_currency(text: str, default: str) -> str:
    counts = {
        "INR": len(re.findall(r"\bINR\b|\bRs\.?(?=\s|\d)|₹", text)),
        "USD": len(re.findall(r"\bUSD\b|US\$|(?<![A-Z])\$", text)),
        "EUR": len(re.findall(r"\bEUR\b|€", text)),
        "GBP": len(re.findall(r"\bGBP\b|£", text)),
    }
    best, hits = max(counts.items(), key=lambda kv: kv[1])
    return best if hits else default


def _lines(text: str) -> list[str]:
    return [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines() if line.strip()]


def _trailing_amount(line: str) -> Decimal | None:
    match = _TRAILING_AMOUNT_RE.search(line)
    if not match:
        return None
    try:
        return Decimal(match.group(1).replace(",", ""))
    except InvalidOperation:
        return None


def _vendor_section(lines: Sequence[str]) -> list[str]:
    for i, line in enumerate(lines):
        if _BILL_TO_RE.search(line):
            return list(lines[:i])
    return list(lines[: max(8, len(lines) // 3)])


def _extract_vendor(lines: Sequence[str], result: ExtractionResult) -> None:
    header = _vendor_section(lines)
    for line in header:
        match = _VENDOR_LABEL_RE.match(line)
        if match:
            result.vendor_name = match.group(1).strip()
            result.field_confidence["vendor_name"] = LABELLED
            break
    else:
        for line in header:
            name = _HEADER_LABEL_SPLIT_RE.sub("", line).strip(" ,:-")
            if 3 <= len(name) <= 120 and not _NOT_A_NAME_RE.match(name) and re.search(r"[A-Za-z]{3}", name):
                result.vendor_name = name
                result.field_confidence["vendor_name"] = GUESSED
                break

    for haystack in (header, lines):
        gstin = next(_matches(_GSTIN_RE, haystack), None)
        if gstin:
            result.vendor_tax_id = gstin.group(1)
            return
        labelled = next(_matches(_TAX_ID_LABEL_RE, haystack), None)
        if labelled and re.search(r"\d", labelled.group(1)):
            result.vendor_tax_id = labelled.group(1).upper()
            return


def _matches(pattern: re.Pattern[str], lines: Sequence[str]) -> Iterator[re.Match[str]]:
    """Labels and their values are matched within a single line, never across a line break."""
    for line in lines:
        yield from pattern.finditer(line)


def _extract_identifiers(lines: Sequence[str], result: ExtractionResult) -> None:
    for match in _matches(_INVOICE_NO_RE, lines):
        value = match.group(1).strip(".-/")
        if re.search(r"\d", value) and value.lower() not in {"date", "dated"}:
            result.invoice_number = value
            result.field_confidence["invoice_number"] = LABELLED
            break
    for match in _matches(_PO_RE, lines):
        value = match.group(1).strip(".-/")
        if len(re.sub(r"\D", "", value)) >= 4 and not re.match(r"box\b", value, re.IGNORECASE):
            result.po_number = value
            result.field_confidence["po_number"] = LABELLED
            break


def _extract_dates(lines: Sequence[str], result: ExtractionResult) -> None:
    generic: date | None = None
    for match in _matches(_DATED_LABEL_RE, lines):
        label = match.group(1).lower()
        parsed = parse_date(match.group(2))
        if parsed is None:
            continue
        if "due" in label or "pay" in label:
            if result.due_date is None:
                result.due_date = parsed
        elif any(word in label for word in ("invoice", "inv", "bill", "issue", "document", "dated")):
            if result.invoice_date is None:
                result.invoice_date = parsed
                result.field_confidence["invoice_date"] = LABELLED
        elif generic is None:
            generic = parsed
    if result.invoice_date is None and generic is not None:
        result.invoice_date = generic
        result.field_confidence["invoice_date"] = GUESSED + 0.15


def _extract_totals(lines: Sequence[str], result: ExtractionResult) -> None:
    tax_parts: list[Decimal] = []
    explicit_tax: Decimal | None = None
    grand_total: Decimal | None = None
    plain_totals: list[Decimal] = []

    # Tax and plain "Total" lines only count in the summary block, so a line item such as
    # "Tax advisory services" is never mistaken for a tax amount.
    summary_start = next(
        (i for i, line in enumerate(lines) if _SUBTOTAL_RE.search(line) and _trailing_amount(line) is not None),
        int(len(lines) * 0.6),
    )
    for index, line in enumerate(lines):
        if _GSTIN_RE.search(line) or re.search(r"\btax\s+invoice\b", line, re.IGNORECASE):
            continue
        amount = _trailing_amount(line)
        if amount is None:
            continue
        in_summary = index >= summary_start
        if _SUBTOTAL_RE.search(line):
            if result.subtotal is None:
                result.subtotal = amount
                result.field_confidence["subtotal"] = LABELLED
        elif _TOTAL_TAX_RE.search(line) and in_summary:
            explicit_tax = amount
        elif _GRAND_TOTAL_RE.search(line):
            grand_total = amount
        elif _TAX_LINE_RE.search(line) and in_summary:
            # "CGST @ 9% 2,610.00": make sure the trailing number is an amount, not the rate.
            if _trailing_amount(_RATE_RE.sub(" ", line)) is not None:
                tax_parts.append(amount)
        elif _PLAIN_TOTAL_RE.search(line) and in_summary:
            plain_totals.append(amount)

    if explicit_tax is not None:
        result.tax_amount = explicit_tax
        result.field_confidence["tax_amount"] = LABELLED
    elif tax_parts:
        result.tax_amount = sum(tax_parts, Decimal("0"))
        result.field_confidence["tax_amount"] = LABELLED - 0.1

    if grand_total is not None:
        result.total_amount = grand_total
        result.field_confidence["total_amount"] = LABELLED
    elif plain_totals:
        result.total_amount = max(plain_totals)
        result.field_confidence["total_amount"] = LABELLED - 0.15


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
) -> ExtractionResult:
    result = ExtractionResult(method=method, raw_text=text)
    lines = _lines(text)
    if not lines:
        result.warnings.append("Document has no text layer (scanned image?)")
        return result

    result.currency = detect_currency(text, default_currency)
    _extract_vendor(lines, result)
    _extract_identifiers(lines, result)
    _extract_dates(lines, result)
    _extract_totals(lines, result)

    for table in table_rows:
        items = line_items_from_table(table)
        if items:
            result.line_items = items
            break
    if not result.line_items:
        result.line_items = parse_line_items_from_text(lines)

    cross_check(result)
    return result
