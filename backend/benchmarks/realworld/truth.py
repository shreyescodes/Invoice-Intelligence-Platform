"""Ground truth for benchmark documents, mapped onto ExtractionResult field names."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.services.extraction.einvoice import embedded_xml, parse_cii
from benchmarks.realworld.datasets import Document


@dataclass(slots=True)
class Truth:
    values: dict[str, object] = field(default_factory=dict)
    # Accepted alternatives, e.g. a subtotal printed before or after document-level allowances.
    alternatives: dict[str, list[object]] = field(default_factory=dict)


def _decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value)).quantize(Decimal("0.01"))


def from_invoice2data(document: Document) -> Truth:
    raw = json.loads(document.truth_path.read_text(encoding="utf-8"))[0]
    truth = Truth()
    mapping = {
        "vendor_name": raw.get("issuer"),
        "invoice_number": raw.get("invoice_number"),
        "invoice_date": date.fromisoformat(raw["date"]) if raw.get("date") else None,
        "total_amount": _decimal(raw.get("amount")),
        "subtotal": _decimal(raw.get("amount_untaxed")),
        "tax_amount": _decimal(raw.get("amount_tax")),
        "currency": raw.get("currency"),
        "vendor_tax_id": raw.get("vat"),
    }
    truth.values = {k: v for k, v in mapping.items() if v is not None}
    if raw.get("partner_name"):
        truth.alternatives["vendor_name"] = [raw["partner_name"]]
    return truth


def from_embedded_cii(document: Document) -> Truth | None:
    xml = embedded_xml(document.path.read_bytes())
    parsed = parse_cii(xml) if xml else None
    if parsed is None:
        return None
    truth = Truth()
    for name in (
        "vendor_name",
        "vendor_tax_id",
        "invoice_number",
        "po_number",
        "invoice_date",
        "due_date",
        "currency",
        "subtotal",
        "tax_amount",
        "total_amount",
    ):
        value = getattr(parsed, name)
        if value is not None:
            truth.values[name] = value
    # Line total before document-level allowances is an equally valid "subtotal".
    line_total = re.search(
        rb"<ram:LineTotalAmount>([\d.]+)</ram:LineTotalAmount>\s*(?:<ram:ChargeTotal|<ram:Allow|<ram:TaxBasis)",
        xml or b"",
    )
    if line_total:
        truth.alternatives["subtotal"] = [Decimal(line_total.group(1).decode()).quantize(Decimal("0.01"))]
    return truth


def load_truth(document: Document) -> Truth | None:
    return from_invoice2data(document) if document.corpus == "invoice2data" else from_embedded_cii(document)
