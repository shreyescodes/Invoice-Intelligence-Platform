"""Locale-aware parsing of amounts and dates as they are printed on invoices.

Amounts: decides per token whether "," or "." is the decimal separator ("1.234,56", "1,234.56",
"1 234,56", "12,50", Indian "1,23,456.00"), and ignores percentages.
Dates: numeric (day-first, or month-first for US documents), ISO, and month names in English, German,
French, Dutch, Spanish and Italian.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator
from datetime import date
from decimal import Decimal, InvalidOperation

CURRENCY_SYMBOL = r"(?:INR|Rs\.?|₹|USD|US\$|\$|EUR|€|GBP|£|CHF)"

# A number with optional thousands separators ("," "." " " "'" or a thin space) and decimals.
# A space (or apostrophe) only separates thousands before exactly three digits, so "1 100,00" from a
# quantity column followed by a price is not read as 1,100.
_NUMBER = r"[-−]?\d{1,3}(?:[.,]\d{2,3}|[ '’  ]\d{3}(?=[.,\s]|$))+(?:[.,]\d{1,2})?|[-−]?\d+(?:[.,]\d{1,2})?"
AMOUNT_RE = re.compile(rf"(?<![\d.,])(?:{CURRENCY_SYMBOL}\s?)?({_NUMBER})(?![\d])(?!\s?%)(?![.,]\d)")


def normalize_text(text: str) -> str:
    """NFKC plus a few typographic fixes that break regexes (non-breaking spaces, unicode minus)."""
    text = unicodedata.normalize("NFKC", text)
    return text.replace(" ", " ").replace(" ", " ").replace("−", "-")


def to_decimal(token: str) -> Decimal | None:
    raw = token.strip().replace("−", "-").replace("'", "").replace("’", "")
    raw = re.sub(r"[\s  ]", "", raw)
    if not raw or not re.search(r"\d", raw):
        return None
    last_dot, last_comma = raw.rfind("."), raw.rfind(",")
    if last_dot >= 0 and last_comma >= 0:
        decimal_sep = "." if last_dot > last_comma else ","
    elif last_comma >= 0 or last_dot >= 0:
        sep = "," if last_comma >= 0 else "."
        tail = raw.rsplit(sep, 1)[1]
        decimal_sep = sep if (raw.count(sep) == 1 and len(tail) != 3) else ""
        if raw.count(sep) == 1 and len(tail) == 3 and raw.lstrip("-").split(sep)[0] == "0":
            decimal_sep = sep  # "0,125" is a decimal, not thousands
    else:
        decimal_sep = ""
    thousands = {",", "."} - {decimal_sep}
    for sep in thousands:
        raw = raw.replace(sep, "")
    if decimal_sep:
        raw = raw.replace(decimal_sep, ".")
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def find_amounts(text: str) -> Iterator[tuple[Decimal, int, int]]:
    """Yield (value, start, end) for each monetary-looking number that is not a percentage."""
    for match in AMOUNT_RE.finditer(text):
        token = match.group(1)
        if re.fullmatch(r"-?\d{7,}", token):
            continue  # account, phone or reference numbers, not money
        value = to_decimal(token)
        if value is not None:
            yield value, match.start(1), match.end(1)


MONTHS: dict[str, int] = {}
for _number, _names in enumerate(
    [
        ["january", "jan", "januar", "jänner", "janvier", "janv", "januari", "enero", "gennaio"],
        ["february", "feb", "februar", "février", "fevrier", "févr", "fevr", "februari", "febrero", "febbraio"],
        ["march", "mar", "märz", "maerz", "mär", "mars", "maart", "mrt", "marzo"],
        ["april", "apr", "avril", "avr", "abril", "aprile"],
        ["may", "mai", "mei", "mayo", "maggio"],
        ["june", "jun", "juni", "juin", "junio", "giugno"],
        ["july", "jul", "juli", "juillet", "juil", "julio", "luglio"],
        ["august", "aug", "août", "aout", "augustus", "agosto"],
        ["september", "sep", "sept", "septembre", "septiembre", "setiembre", "settembre"],
        ["october", "oct", "oktober", "okt", "octobre", "octubre", "ottobre"],
        ["november", "nov", "novembre", "noviembre"],
        ["december", "dec", "dezember", "dez", "décembre", "decembre", "déc", "diciembre", "dicembre"],
    ],
    start=1,
):
    for _name in _names:
        MONTHS[_name] = _number

_MONTH = "|".join(sorted((re.escape(m) for m in MONTHS), key=len, reverse=True))
DATE_RE = re.compile(
    rf"(?<!\d)(\d{{4}}-\d{{1,2}}-\d{{1,2}}"
    rf"|\d{{1,2}}[./-]\d{{1,2}}[./-](?:\d{{4}}|\d{{2}})"
    rf"|\d{{1,2}}(?:st|nd|rd|th|er)?\.?[\s-]*(?:de\s+)?(?:{_MONTH})\.?,?[\s-]*(?:de\s+)?\d{{4}}"
    rf"|(?:{_MONTH})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?\s*,?\s+\d{{4}})(?!\d)",
    re.IGNORECASE,
)


def _valid(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_date(text: str, month_first: bool = False) -> date | None:
    value = text.strip().lower().rstrip(".,")
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", value):
        return _valid(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if m := re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{2}|\d{4})", value):
        a, b, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        year += 2000 if year < 100 else 0
        first, second = (b, a) if month_first else (a, b)  # (day, month)
        return _valid(year, second, first) or _valid(year, first, second)
    words = re.findall(r"[a-zäöüéèûôàç]+|\d+", value)
    numbers = [int(w) for w in words if w.isdigit()]
    month = next((MONTHS[w] for w in words if w in MONTHS), None)
    if month is None or len(numbers) < 2:
        return None
    day, year = (numbers[0], numbers[-1]) if numbers[-1] > 31 else (numbers[-1], numbers[0])
    return _valid(year, month, day)


def find_dates(text: str, month_first: bool = False) -> Iterator[tuple[date, int, int]]:
    for match in DATE_RE.finditer(text):
        parsed = parse_date(match.group(1), month_first)
        if parsed is not None and 1990 <= parsed.year <= 2100:
            yield parsed, match.start(1), match.end(1)
