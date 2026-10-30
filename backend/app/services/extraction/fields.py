"""Header-field extraction that generalises across invoice layouts and languages.

The approach, in order:

1. **Label/value pairs.** Every line is scanned for known labels (English, German, French, Dutch,
   Spanish, Italian). Several pairs may share a line ("Net 100,00   VAT 19,00   Total 119,00"); each
   label owns the text up to the next label. If a label has no value beside it, the value is looked
   up *below* it in the column-preserving layout text (header row / value row tables).
2. **Totals by consistency.** Among the candidate subtotals, taxes and totals, the combination that
   satisfies subtotal + tax = total wins; otherwise the strongest label wins.
3. **Vendor by evidence.** Explicit seller labels, then the sender line of a business letter, then
   names carrying a legal form (GmbH, B.V., Ltd, SAS, ...), never from the buyer's address block.
4. **Tax IDs by format.** GSTIN and EU VAT number patterns, preferring the seller's side.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import product
from typing import Literal

from app.services.extraction.base import ExtractionResult
from app.services.extraction.locale_formats import find_amounts, find_dates

Kind = Literal["id", "date", "money"]
LABELLED = 0.95
GUESSED = 0.65

_MONEY_SUFFIX = (
    r"(?:\s*\(?(?:inkl|incl|including|exkl|excl|excluding|zzgl|hors|ohne|met|zonder)\.?\s*"
    r"(?:mwst\.?|ust\.?|vat|btw|tva|tax(?:es)?|gst|iva)?\)?)?"
    r"(?:\s*\(?(?:in\s+)?(?:eur|usd|inr|gbp|chf|€|\$|₹)\)?)?"
)

# (field, kind, strength, pattern). Higher strength = more specific label.
_LABEL_SPECS: list[tuple[str, Kind, int, str]] = [
    # Invoice number
    ("invoice_number", "id", 3, r"(?:tax\s+)?invoice\s*(?:no|number|num|nr|#|id|ref(?:erence)?)\.?"),
    ("invoice_number", "id", 3, r"inv\.?\s*(?:no|#)\.?"),
    ("invoice_number", "id", 3, r"bill\s*(?:no|number|#)\.?"),
    ("invoice_number", "id", 3, r"rechnungs?[\s-]*(?:nummer|nr|no)\.?"),
    (
        "invoice_number",
        "id",
        3,
        r"(?:\w*rechnung\w*|gutschrift|invoice|credit\s+note|facture|avoir|factuur|creditnota)"
        r"(?:\s*\([^)\n]{0,40}\))*\s*(?:nr|nummer|no|n[°º])\.?",
    ),
    ("invoice_number", "id", 3, r"\w*rechnung\w*(?:\s+\w+){1,3}\s*\(\d{3}\)\s*(?:nr|nummer|no)\.?"),
    ("invoice_number", "id", 3, r"(?:num[ée]ro|n[°º]|no)\.?\s*(?:de\s+)?(?:la\s+)?facture"),
    ("invoice_number", "id", 3, r"facture\s*(?:n[°º]|no|num[ée]ro|#)\.?"),
    ("invoice_number", "id", 3, r"factuur[\s-]*(?:nummer|nr|no)\.?"),
    ("invoice_number", "id", 3, r"(?:n[°º]|n[úu]mero)\s*(?:de\s+)?factura|factura\s*(?:n[°º]|no|n[úu]mero)\.?"),
    ("invoice_number", "id", 3, r"(?:numero|n\.)\s*(?:della\s+)?fattura|fattura\s*(?:n[°º.]|numero)"),
    ("invoice_number", "id", 2, r"(?:document|receipt|beleg)[\s-]*(?:no|number|nr|nummer|#)\.?"),
    ("invoice_number", "id", 1, r"invoice|rechnung|facture|factuur|factura|fattura"),
    # Dates
    ("invoice_date", "date", 3, r"(?:invoice|inv\.?|bill|issue|document)\s*date"),
    ("invoice_date", "date", 3, r"date\s+of\s+(?:issue|invoice)|dated"),
    ("invoice_date", "date", 3, r"rechnungs?datum|belegdatum|ausstellungsdatum"),
    ("invoice_date", "date", 3, r"date\s+(?:de\s+)?(?:la\s+)?facture|date\s+d['’]?\s?[ée]mission|factur[ée]e?\s+le"),
    (
        "invoice_date",
        "date",
        3,
        r"factuur\s*datum|fecha\s+(?:de\s+)?(?:la\s+)?(?:factura|emisi[óo]n)|data\s+(?:della\s+)?fattura",
    ),
    ("invoice_date", "date", 1, r"date|datum|fecha"),
    ("due_date", "date", 3, r"(?:payment\s+)?due\s*(?:date|on|by)|payment\s+due|pay(?:able)?\s+by"),
    ("due_date", "date", 3, r"f[äa]llig(?:keitsdatum|keit|\s+am|\s+bis)?|zahlbar\s+bis|zahlungsziel"),
    ("due_date", "date", 3, r"(?:date\s+d['’]?\s?)?[ée]ch[ée]ance|vervaldatum|uiterste\s+betaaldatum"),
    ("due_date", "date", 3, r"(?:fecha\s+de\s+)?vencimiento|scadenza"),
    # Payment-terms sentences: "Zahlbar innerhalb 30 Tagen netto bis 04.04.2018", "payable by 1 May 2026".
    (
        "due_date",
        "date",
        2,
        r"(?:zahlbar|zahlen|[üu]berweisen|payable|pay|payment|payer|r[ée]gler|betalen|voldoen)"
        r"[^\n\d]{0,45}?(?:bis(?:\s+zum)?|by|until|before|avant\s+le|uiterlijk|voor)",
    ),
    # Dates that must not be mistaken for the invoice date.
    (
        "_other",
        "date",
        3,
        r"(?:order|delivery|service|shipping|ship|supply|period|leistungs|liefer|bestell|order)\s*-?datum",
    ),
    ("_other", "date", 3, r"(?:order|delivery|service|shipping|supply)\s+date|date\s+(?:de\s+)?(?:commande|livraison)"),
    ("_other", "date", 3, r"orderdatum|leverdatum|liefer-\s*und\s*leistungsdatum|leistungszeitraum"),
    # Purchase order
    ("po_number", "id", 3, r"(?:p\.?\s?o\.?(?![a-z])|purchase\s+order)\s*(?:no|number|#|ref)?\.?"),
    ("po_number", "id", 3, r"(?:your|customer)\s+(?:order|po)\s*(?:no|number|ref)?\.?|order\s+ref(?:erence)?"),
    (
        "po_number",
        "id",
        3,
        r"bestell(?:nummer|nr|ung)\.?(?:\s*(?:nr|nummer)\.?)?|ihre\s+bestellung|auftrags?(?:nummer|nr)\.?",
    ),
    ("po_number", "id", 3, r"(?:bon|num[ée]ro|n[°º])\s*de\s+commande|bestelnummer|inkoopordernummer"),
    ("po_number", "id", 2, r"(?:orden|pedido)\s+de\s+compra|ordine\s+n\.?"),
    # Amounts
    ("subtotal", "money", 3, r"sub[\s-]?total|net\s+(?:amount|total|value)|taxable\s+(?:value|amount)"),
    ("subtotal", "money", 3, r"total\s+(?:excl\.?|excluding|before|net|w/o)\b[^\d\n]{0,14}|amount\s+before\s+tax"),
    (
        "subtotal",
        "money",
        3,
        r"zwischensumme|netto(?:betrag|summe|wert)?|summe\s+netto|gesamt(?:betrag)?\s+netto|warenwert",
    ),
    ("subtotal", "money", 3, r"summe\s+(?:der\s+)?positionen|(?:steuerbasis|basis)betrag"),
    ("subtotal", "money", 2, r"positionssumme|grondslag|warenwert\s+gesamt"),
    ("subtotal", "money", 3, r"total\s+h\.?t\.?|montant\s+h\.?t\.?|sous[\s-]total|total\s+hors\s+taxes?"),
    (
        "subtotal",
        "money",
        3,
        r"subtotaal|(?:totaal\s+)?excl(?:\.|usief)?\s+btw|netto\s+bedrag|base\s+imponible|imponibile",
    ),
    ("tax_amount", "money", 3, r"total\s+(?:tax|vat|gst)|(?:tax|vat|gst)\s+(?:amount|total)"),
    (
        "tax_amount",
        "money",
        3,
        r"(?:summe|gesamt)\s+(?:mwst|ust|umsatzsteuer)|steuerbetrag|umsatzsteuerbetrag|mehrwertsteuerbetrag",
    ),
    ("tax_amount", "money", 3, r"(?:total|montant)\s+t\.?v\.?a\.?|totaal\s+btw|btw[\s-]?bedrag|total\s+iva"),
    ("tax_amount", "money", 1, r"cgst|sgst|igst|utgst|gst|vat|tax|mwst|ust|tva|btw|iva|umsatzsteuer|mehrwertsteuer"),
    ("total_amount", "money", 3, r"grand\s+total|total\s+(?:amount\s+)?(?:due|payable)|amount\s+(?:due|payable)"),
    (
        "total_amount",
        "money",
        3,
        r"invoice\s+(?:total|amount)|balance\s+due|total\s+(?:incl\.?|including)\b[^\d\n]{0,14}",
    ),
    (
        "total_amount",
        "money",
        3,
        r"gesamtbetrag|rechnungs(?:betrag|summe)|brutto(?:betrag|summe)|(?:gesamt|summe)\s+brutto",
    ),
    (
        "total_amount",
        "money",
        3,
        r"end(?:betrag|summe)|gesamtsumme",
    ),
    (
        "total_amount",
        "money",
        2,
        r"zahlbetrag|zu\s+zahlen(?:der\s+betrag)?|f[äa]lliger\s+betrag",
    ),
    (
        "total_amount",
        "money",
        3,
        r"total\s+t\.?t\.?c\.?|montant\s+t\.?t\.?c\.?|net\s+[àa]\s+payer|total\s+[àa]\s+payer",
    ),
    (
        "total_amount",
        "money",
        3,
        r"montant\s+total|montant\s+d[uû]|te\s+betalen|totaal(?:bedrag)?\s+incl(?:\.|usief)?(?:\s+btw)?",
    ),
    (
        "total_amount",
        "money",
        3,
        r"totaalbedrag|factuurbedrag|total\s+(?:a\s+pagar|factura)|importe\s+total|totale\s+(?:fattura|documento)",
    ),
    ("total_amount", "money", 1, r"total|totaal|summe|gesamt|totale"),
    # Totals that are not the invoice total.
    ("_other", "money", 2, r"total\s+(?:qty|quantity|items?|weight|pages?|hours|units)|anzahl|menge|gewicht"),
    (
        "_other",
        "money",
        2,
        r"(?:already\s+)?paid|bezahlt|pay[ée]|betaald|(?:erhaltene\s+)?anzahlungen?|vorauszahlungen?|deposits?|acompte|rabatt|discount|remise",
    ),
    (
        "_other",
        "money",
        3,
        r"gesamtbetrag\s+der\s+(?:zu|ab)schl[äa]ge|(?:zu|ab)schl[äa]ge|allowances?|charges|grundgeb[üu]hr",
    ),
]


@dataclass(frozen=True, slots=True)
class _Label:
    field: str
    kind: Kind
    strength: int
    regex: re.Pattern[str]


LABELS = [
    _Label(
        field,
        kind,
        strength,
        re.compile(rf"(?<![\w-])(?:{pattern}){_MONEY_SUFFIX if kind == 'money' else ''}(?![\w])", re.IGNORECASE),
    )
    for field, kind, strength, pattern in _LABEL_SPECS
]


@dataclass(frozen=True, slots=True)
class Candidate:
    field: str
    value: object
    strength: int
    line: int
    position: int


def _label_matches(line: str) -> list[tuple[int, int, _Label]]:
    found = [(m.start(), m.end(), label) for label in LABELS for m in label.regex.finditer(line)]
    found.sort(key=lambda f: (f[0], -(f[1] - f[0]), -f[2].strength))
    chosen: list[tuple[int, int, _Label]] = []
    for start, end, label in found:
        if chosen and start < chosen[-1][1]:
            continue
        chosen.append((start, end, label))
    return chosen


_ID_RE = re.compile(r"#?[A-Za-z0-9][A-Za-z0-9/_.#\-]{1,40}")
_NOT_AN_ID = re.compile(r"^(?:no|nr|nummer|number|date|datum|page|seite|of|von)$", re.IGNORECASE)


def _id_value(segment: str) -> tuple[str, int] | None:
    stripped = segment.lstrip(" \t:#.-–=")
    offset = len(segment) - len(stripped)
    match = _ID_RE.match(stripped)
    if not match:
        return None
    token = re.sub(r"(?<=[A-Z0-9])(?:vom|van|du|del|dated)$", "", match.group(0)).rstrip(".,:;-/")
    if not re.search(r"\d", token) or _NOT_AN_ID.match(token) or len(token.lstrip("#")) < 2:
        return None
    if next(find_dates(token), None) is not None and len(re.sub(r"\D", "", token)) <= 8:
        return None
    if re.fullmatch(r"-?\d{1,3}(?:[.,]\d{3})*[.,]\d{2}", token):
        return None  # an amount, not a document number
    return token.lstrip("#"), offset + match.end()


def _value(kind: Kind, segment: str, field: str, month_first: bool) -> tuple[object, int] | None:
    window = segment[:70]
    if kind == "id":
        return _id_value(window)
    if kind == "date":
        found = next(find_dates(window, month_first), None)
        return (found[0], found[2]) if found else None
    # Dates inside the segment ("TOTAL DUE ON August 3, 2014  $4.11") must not yield amounts.
    for _, date_start, date_end in find_dates(window, month_first):
        window = window[:date_start] + " " * (date_end - date_start) + window[date_end:]
    amounts = [a for a in find_amounts(window) if abs(a[0]) < Decimal("1e11")]
    if not amounts:
        return None
    # "VAT 19% on 445.27 = 84.60": for tax lines the amount is the last one, otherwise the first.
    pick = amounts[-1] if field == "tax_amount" else amounts[0]
    return pick[0], pick[2]


def _below(
    kind: Kind, lines: Sequence[str], index: int, start: int, end: int, field: str, month_first: bool
) -> object | None:
    """Value printed under its label (a header row followed by a value row)."""
    looked = 0
    for following in lines[index + 1 : index + 6]:
        if not following.strip():
            continue
        looked += 1
        if looked > 2:
            break
        column = following[max(0, start - 3) : end + 22]
        if not column.strip():
            continue
        found = _value(kind, column.lstrip(), field, month_first)
        if found is not None:
            return found[0]
    return None


_LETTER_SPACED = re.compile(r"\b([A-Z]) (?=[a-z]{3,})")
_EXCLUDING = re.compile(r"\b(?:ohne|exkl|excl|excluding|exclusief|zonder|hors|before|w/o|net\s+of|zzgl)\b", re.I)
_INCLUDING = re.compile(r"\b(?:inkl|incl|including|inclusief|mit|met|ttc|brutto)\b", re.I)


def _field_for(label: _Label, text: str) -> str:
    """ "Rechnungssumme ohne USt." is a subtotal; "Totaal incl. BTW" is the total."""
    if label.field == "total_amount" and _EXCLUDING.search(text):
        return "subtotal"
    if label.field == "subtotal" and _INCLUDING.search(text) and not _EXCLUDING.search(text):
        return "total_amount"
    return label.field


def label_candidates(lines: Sequence[str], month_first: bool) -> list[Candidate]:
    candidates: list[Candidate] = []
    # Kerned PDFs split words ("F actuurnummer"); rejoin them so labels match.
    lines = [_LETTER_SPACED.sub(r"\1", line) for line in lines]
    for index, line in enumerate(lines):
        matches = _label_matches(line)
        for i, (start, end, label) in enumerate(matches):
            limit = matches[i + 1][0] if i + 1 < len(matches) else len(line)
            segment = line[end:limit]
            if label.field == "_other":
                continue
            found = _value(label.kind, segment, label.field, month_first)
            value: object | None = found[0] if found else None
            # Only specific labels (and a bare "Invoice" column header) may take a value from the row below.
            may_look_below = label.strength >= 2 or label.kind == "id"
            # A header row holds words, its value row holds digits: if nothing beside the label has a digit,
            # the label is a column heading and its value is underneath.
            heading_only = not re.search(r"\d", segment[:60])
            if value is None and may_look_below and heading_only:
                value = _below(label.kind, lines, index, start, end, label.field, month_first)
            if value is None:
                continue
            field = _field_for(label, line[start:end]) if label.kind == "money" else label.field
            candidates.append(Candidate(field, value, label.strength, index, start))
            # "Rechnung Nr. 471102 vom 05.06.2018": a date right after the number is the issue date.
            if label.field == "invoice_number" and found:
                rest = segment[found[1] : found[1] + 30]
                issued = next(find_dates(rest, month_first), None)
                if issued is not None and re.match(r"\s*(?:vom|du|dated|del|van|of|from|,)?\s*\d", rest, re.I):
                    candidates.append(Candidate("invoice_date", issued[0], 2, index, start))
    return candidates


def _best(candidates: list[Candidate], field: str) -> Candidate | None:
    pool = [c for c in candidates if c.field == field]
    if not pool:
        return None
    return max(pool, key=lambda c: (c.strength, -c.line, -c.position))


def _money(candidate: Candidate) -> Decimal:
    if not isinstance(candidate.value, Decimal):
        raise TypeError("not an amount")
    return candidate.value


def _choose_amounts(candidates: list[Candidate]) -> tuple[Candidate | None, Candidate | None, Candidate | None]:
    def pool(field: str) -> list[Candidate]:
        best: dict[Decimal, Candidate] = {}
        for c in candidates:
            if c.field != field or not isinstance(c.value, Decimal):
                continue
            current = best.get(c.value)
            if current is None or c.strength > current.strength:
                best[c.value] = c
        return sorted(best.values(), key=lambda c: -c.strength)[:8]

    subtotals, totals, taxes = pool("subtotal"), pool("total_amount"), pool("tax_amount")
    # CGST + SGST, or several VAT rates: one component per line, even when the amounts are equal.
    components = list(
        {
            c.line: c
            for c in candidates
            if c.field == "tax_amount" and c.strength == 1 and isinstance(c.value, Decimal)
        }.values()
    )
    if len(components) > 1:
        summed = sum((_money(c) for c in components), Decimal(0))
        taxes.append(Candidate("tax_amount", summed, 2, components[-1].line, components[-1].position))

    best_combo: tuple[int, Candidate, Candidate | None, Candidate] | None = None
    for total in totals:
        for subtotal, tax in product(subtotals, [*taxes, None]):
            tax_value = _money(tax) if tax else Decimal(0)
            if abs(_money(subtotal) + tax_value - _money(total)) <= Decimal("0.02"):
                score = total.strength + subtotal.strength + (tax.strength if tax else 0)
                if best_combo is None or score > best_combo[0]:
                    best_combo = (score, subtotal, tax, total)
    if best_combo is not None:
        _, subtotal, tax, total = best_combo
        return subtotal, tax, total

    def strongest(items: list[Candidate], largest: bool = False) -> Candidate | None:
        if not items:
            return None
        top = max(c.strength for c in items)
        tied = [c for c in items if c.strength == top]
        if largest:
            return max(tied, key=_money)
        return min(tied, key=lambda c: (c.line, c.position))

    explicit_taxes = [c for c in taxes if c.strength >= 2]
    return strongest(subtotals), strongest(explicit_taxes or taxes), strongest(totals, largest=True)


# --- Vendor ----------------------------------------------------------------------------------------

_BUYER_RE = re.compile(
    r"\b(?:bill(?:ed)?\s+to|invoice\s+to|sold\s+to|ship(?:ped)?\s+to|deliver(?:y|ed)?\s+to|customer|buyer|client|"
    r"recipient|k[äa]ufer|kunde|rechnungs(?:empf[äa]nger|adresse|anschrift)|leistungsempf[äa]nger|lieferadresse|"
    r"lieferanschrift|adresse\s+de\s+(?:facturation|livraison)|factur[ée]\s+[àa]|livr[ée]\s+[àa]|factuuradres|"
    r"afleveradres|klant|destinatario|cliente)\b",
    re.IGNORECASE,
)
_SELLER_HEADER_RE = re.compile(
    r"^\W*(?:from|seller|supplier|vendor|issued\s+by|verk[äa]ufer|lieferant|leistungserbringer|rechnungssteller|"
    r"vendeur|fournisseur|[ée]metteur|leverancier|verkoper|proveedor|emisor|fornitore)\b\W*(.*)$",
    re.IGNORECASE,
)
_LEGAL_RE = re.compile(
    r"(?<![\w&])(?:GmbH(?:\s*&\s*Co\.?\s*KG)?|AG|KG|OHG|UG|e\.\s?K\.|B\.\s?V\.|BV|N\.\s?V\.|S\.?A\.?S\.?|SARL|S\.A\.|SA|"
    r"S\.L\.|S\.r\.l\.|S\.p\.A\.|Ltd\.?|Limited|LLP|LLC|Inc\.?|Corp(?:oration)?\.?|Pvt\.?\s+Ltd\.?|PLC|plc|Oy|AB|ApS|"
    r"A/S|SE|L\.L\.C\.)(?=$|[\s,.)·|–-])"
)
_POSTCODE_RE = re.compile(r"\b(?:[A-Z]{1,2}-?)?\d{4,6}\b|\b[A-Z]\d[A-Z]\s?\d[A-Z]\d\b|\b\d{4}\s?[A-Z]{2}\b")
_SEPARATORS_RE = re.compile(r"\s+[·•|–-]\s+|\s*·\s*|\s+\|\s+")
_NOT_A_NAME_RE = re.compile(
    r"^(?:tax\s+invoice|invoice|factuur|facture|rechnung|bill|receipt|original|duplicate|page|seite|gstin|pan|"
    r"cin|phone|tel|fax|e-?mail|www\.|http|iban|bic|swift|vat|btw|tva|ust|steuer|nummer|number|name|anschrift|"
    r"address|adresse|warehouse|datum|date|kopie|copy|seite|\d)",
    re.IGNORECASE,
)
_PREFIX_NOISE_RE = re.compile(r"^(?:factuur|invoice|facture|rechnung|tax\s+invoice)\W+", re.IGNORECASE)


def _clean_name(text: str) -> str:
    text = _PREFIX_NOISE_RE.sub("", text.strip())
    text = re.split(r"\s{3,}|\t", text)[0]
    return text.strip(" ,:;-–·|")


def _buyer_lines(lines: Sequence[str]) -> set[int]:
    blocked: set[int] = set()
    for i, line in enumerate(lines):
        if _BUYER_RE.search(line) and not _SELLER_HEADER_RE.match(line):
            for j in range(i, min(i + 6, len(lines))):
                if j > i and _SELLER_HEADER_RE.match(lines[j]):
                    break
                blocked.add(j)
    return blocked


def find_vendor(lines: Sequence[str]) -> tuple[str, float] | None:
    blocked = _buyer_lines(lines)
    # 1. Explicit seller label or seller section.
    for i, line in enumerate(lines):
        match = _SELLER_HEADER_RE.match(line)
        if not match:
            continue
        inline = _clean_name(match.group(1).split(":", 1)[-1]) if match.group(1) else ""
        if len(inline) >= 3 and not _NOT_A_NAME_RE.match(inline):
            return inline, LABELLED
        for following in lines[i + 1 : i + 6]:
            named = re.match(r"^\s*(?:name|firma|company|raison\s+sociale|naam)\s*[:\-]\s*(.+)$", following, re.I)
            if named:
                return _clean_name(named.group(1)), LABELLED
            candidate = _clean_name(following)
            plausible = len(candidate) >= 3 and not _NOT_A_NAME_RE.match(candidate)
            if (
                plausible
                and not _POSTCODE_RE.search(candidate)
                and (_LEGAL_RE.search(candidate) or not re.search(r"\d", candidate))
            ):
                return candidate, LABELLED - 0.1
    # 2. Sender line of a business letter: "Company GmbH · Street 1 · 12345 City".
    for i, line in enumerate(lines[: max(12, len(lines) // 3)]):
        parts = [p for p in _SEPARATORS_RE.split(line) if p.strip()]
        if len(parts) >= 2 and any(_POSTCODE_RE.search(p) for p in parts[1:]) and i not in blocked:
            name = _clean_name(parts[0])
            if len(name) >= 3 and re.search(r"[A-Za-z]{3}", name) and not _NOT_A_NAME_RE.match(name):
                return name, LABELLED - 0.1
    # 3. Names with a legal form, preferring ones repeated in the footer and outside the buyer block.
    counts: Counter[str] = Counter()
    first_line: dict[str, int] = {}
    display: dict[str, str] = {}
    for i, line in enumerate(lines):
        if i in blocked:
            continue
        for match in _LEGAL_RE.finditer(line):
            head = re.split(r"[:|·•]|\s{3,}|\s[-–]\s", line[: match.end()])[-1]
            name = _clean_name(head)
            if 2 <= len(name) <= 70 and 1 <= len(name.split()) <= 8 and not _NOT_A_NAME_RE.match(name):
                key = name.lower()
                counts[key] += 1
                first_line.setdefault(key, i)
                display.setdefault(key, name)
    if counts:
        key = max(counts, key=lambda k: (counts[k], -first_line[k]))
        return display[key], LABELLED - 0.2
    # 4. First plausible line of the document.
    for i, line in enumerate(lines[:8]):
        name = _clean_name(line)
        if (
            i not in blocked
            and 3 <= len(name) <= 80
            and not _NOT_A_NAME_RE.match(name)
            and re.search(r"[A-Za-z]{3}", name)
        ):
            return name, GUESSED
    return None


# --- Tax IDs ---------------------------------------------------------------------------------------

_GSTIN_RE = re.compile(r"\b(\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z])\b")
_EU_VAT_RE = re.compile(
    r"\b(ATU\d{8}|BE\s?0?\d{3}[.\s]?\d{3}[.\s]?\d{3}|DE\s?\d{3}\s?\d{3}\s?\d{3}|FR\s?[A-Z0-9]{2}\s?\d{3}\s?\d{3}\s?\d{3}|"
    r"NL\s?\d{9}\s?B\s?\d{2}|IT\s?\d{11}|ES\s?[A-Z0-9]\d{7}[A-Z0-9]|LU\s?\d{8}|PL\s?\d{10}|PT\s?\d{9}|SE\s?\d{12}|"
    r"DK\s?\d{8}|FI\s?\d{8}|IE\s?\d[A-Z0-9]\d{5}[A-Z]{1,2}|CHE[-\s]?\d{3}\.?\d{3}\.?\d{3}|"
    r"GB\s?\d{3}\s?\d{4}\s?\d{2}(?:\s?\d{3})?|CZ\d{8,10}|SK\d{10}|HU\d{8}|RO\d{2,10}|EL\d{9})\b"
)


def find_tax_id(lines: Sequence[str]) -> str | None:
    blocked = _buyer_lines(lines)
    for pattern in (_GSTIN_RE, _EU_VAT_RE):
        outside = [(i, m.group(1)) for i, line in enumerate(lines) if i not in blocked for m in pattern.finditer(line)]
        inside = [(i, m.group(1)) for i, line in enumerate(lines) if i in blocked for m in pattern.finditer(line)]
        if outside or inside:
            return re.sub(r"[\s.]", "", (outside or inside)[0][1])
    return None


# --- Entry point -----------------------------------------------------------------------------------


def extract_header(lines: Sequence[str], layout_lines: Sequence[str], result: ExtractionResult) -> None:
    month_first = result.currency == "USD"
    candidates = label_candidates(layout_lines or lines, month_first)

    for field in ("invoice_number", "po_number", "invoice_date", "due_date"):
        best = _best(candidates, field)
        if best is not None:
            setattr(result, field, best.value)
            if field != "due_date":
                result.field_confidence[field] = LABELLED if best.strength >= 2 else GUESSED + 0.15

    subtotal, tax, total = _choose_amounts(candidates)
    for field, candidate in (("subtotal", subtotal), ("tax_amount", tax), ("total_amount", total)):
        if candidate is not None:
            setattr(result, field, candidate.value)
            result.field_confidence[field] = LABELLED if candidate.strength >= 2 else LABELLED - 0.15

    vendor = find_vendor(lines)
    if vendor is not None:
        result.vendor_name, result.field_confidence["vendor_name"] = vendor
    result.vendor_tax_id = find_tax_id(lines)
    if (
        isinstance(result.invoice_date, date)
        and isinstance(result.due_date, date)
        and result.due_date < result.invoice_date
    ):
        result.due_date = None
