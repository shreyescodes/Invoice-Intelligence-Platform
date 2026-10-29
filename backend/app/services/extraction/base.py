from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Protocol

# How much each header field contributes to the overall extraction confidence.
FIELD_WEIGHTS: dict[str, float] = {
    "vendor_name": 1.0,
    "invoice_number": 1.0,
    "invoice_date": 1.0,
    "total_amount": 1.5,
    "subtotal": 0.5,
    "tax_amount": 0.5,
}


@dataclass(slots=True)
class ExtractedLine:
    description: str
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal


@dataclass(slots=True)
class ExtractionResult:
    method: str
    raw_text: str = ""
    vendor_name: str | None = None
    vendor_tax_id: str | None = None
    invoice_number: str | None = None
    po_number: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    currency: str = "INR"
    subtotal: Decimal | None = None
    tax_amount: Decimal | None = None
    total_amount: Decimal | None = None
    line_items: list[ExtractedLine] = field(default_factory=list)
    field_confidence: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def confidence(self) -> float:
        total_weight = sum(FIELD_WEIGHTS.values())
        score = sum(w * self.field_confidence.get(name, 0.0) for name, w in FIELD_WEIGHTS.items())
        return round(score / total_weight, 3)

    def missing_fields(self) -> list[str]:
        return [name for name in FIELD_WEIGHTS if getattr(self, name) is None]


class ExtractionError(Exception):
    """The document could not be read at all (corrupt, encrypted, unsupported)."""


class Extractor(Protocol):
    name: str

    def extract(self, data: bytes, content_type: str) -> ExtractionResult: ...
