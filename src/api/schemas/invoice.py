"""Pydantic schemas for the invoice pipeline.

This is the contract between every stage: what Document Intelligence
extraction gets normalized into, what's stored in Cosmos DB, and what
the API returns. Keep it the single source of truth — don't let
Functions and the API drift into separate ad hoc dict shapes.

TODO(phase 2): flesh out LineItem and add whatever fields your chosen
Document Intelligence model actually returns (prebuilt-invoice gives
you VendorName, InvoiceId, InvoiceDate, DueDate, InvoiceTotal,
Items[], etc. — check the response shape and map it here rather than
guessing).
"""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


class InvoiceStatus(StrEnum):
    RECEIVED = "received"
    EXTRACTING = "extracting"
    VALIDATING = "validating"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    POSTED = "posted"
    FAILED = "failed"


class LineItem(BaseModel):
    description: str
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    amount: Decimal = Field(ge=0)

    @field_validator("amount")
    @classmethod
    def amount_matches_qty_times_price(cls, v: Decimal, info: object) -> Decimal:
        # TODO: cross-check quantity * unit_price ~= amount within a
        # rounding tolerance; flag a mismatch as an extraction error
        # rather than silently accepting it.
        return v


class ExtractedInvoice(BaseModel):
    """What comes out of Document Intelligence + LLM cleanup, before
    SAP validation or anomaly scoring have run."""

    vendor_name: str
    vendor_tax_id: str | None = None
    invoice_number: str
    po_number: str | None = None
    invoice_date: date
    due_date: date | None = None
    currency: str = Field(default="INR", min_length=3, max_length=3)
    line_items: list[LineItem] = Field(default_factory=list)
    subtotal: Decimal
    tax_amount: Decimal = Decimal("0")
    total_amount: Decimal
    extraction_confidence: float = Field(ge=0, le=1)


class InvoiceRecord(BaseModel):
    """The Cosmos DB document shape. id is the partition-friendly key —
    see the README's data-modeling note on why vendor_id is the
    partition key, not id."""

    id: UUID = Field(default_factory=uuid4)
    vendor_id: str
    status: InvoiceStatus = InvoiceStatus.RECEIVED
    blob_path: str
    extracted: ExtractedInvoice | None = None
    sap_match: dict | None = None  # TODO: type this once validate_po_sap.py exists
    anomaly_score: float | None = None
    approved_by: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class InvoiceUploadResponse(BaseModel):
    invoice_id: UUID
    status: InvoiceStatus
    orchestration_id: str


class ApprovalDecision(BaseModel):
    approve: bool
    reason: str | None = None
