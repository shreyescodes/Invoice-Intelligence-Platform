"""API request and response models."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator

from app.models import CheckStatus, InvoiceStatus, UserRole

# Money travels as a fixed-point string ("1234.50") so no client ever sees float rounding.
Money = Annotated[
    Decimal, PlainSerializer(lambda v: f"{v:.2f}", return_type=str, when_used="json"), Field(examples=["118000.00"])
]
Quantity = Annotated[Decimal, PlainSerializer(lambda v: format(v.normalize(), "f"), return_type=str, when_used="json")]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Problem(BaseModel):
    """RFC 9457 problem details."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str
    code: str
    extra: dict[str, Any] | None = None


# --- Auth ---------------------------------------------------------------------------------------


class UserOut(ORMModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: UserRole


class UserRef(ORMModel):
    id: uuid.UUID
    full_name: str
    role: UserRole


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - OAuth2 token type, not a secret
    expires_in: int
    user: UserOut


class MetaOut(BaseModel):
    version: str
    environment: str
    demo_mode: bool
    demo_accounts: list[dict[str, str]] = []
    llm_enabled: bool
    llm_model: str | None
    extractor: str
    currency: str = "INR"
    auto_approve_limit: Money
    approver_limit: Money
    anomaly_review_threshold: float
    anomaly_model: dict[str, Any] | None = None


# --- Vendors ------------------------------------------------------------------------------------


class VendorRef(ORMModel):
    id: uuid.UUID
    erp_id: str
    name: str
    tax_id: str | None


class VendorOut(VendorRef):
    city: str | None
    currency: str
    payment_terms_days: int
    is_active: bool
    synced_at: datetime
    invoice_count: int = 0
    open_count: int = 0
    total_spend: Money = Decimal("0")
    last_invoice_date: date | None = None


# --- Invoices -----------------------------------------------------------------------------------


class InvoiceListItem(ORMModel):
    id: uuid.UUID
    status: InvoiceStatus
    file_name: str
    vendor: VendorRef | None
    vendor_name: str | None
    invoice_number: str | None
    po_number: str | None
    invoice_date: date | None
    due_date: date | None
    currency: str
    total_amount: Money | None
    anomaly_score: float | None
    extraction_confidence: float | None
    auto_approved: bool
    review_reasons: list[str] | None
    created_at: datetime
    updated_at: datetime


class LineItemOut(ORMModel):
    line_no: int
    description: str
    quantity: Quantity
    unit_price: Money
    amount: Money
    po_item: str | None


class CheckOut(ORMModel):
    code: str
    status: CheckStatus
    message: str
    details: dict[str, Any] | None


class AuditEventOut(ORMModel):
    id: int
    action: str
    from_status: str | None
    to_status: str | None
    comment: str | None
    details: dict[str, Any] | None
    actor: UserRef | None
    created_at: datetime


class InvoiceDetail(InvoiceListItem):
    content_type: str
    file_size: int
    vendor_tax_id: str | None
    subtotal: Money | None
    tax_amount: Money | None
    extraction_method: str | None
    field_confidence: dict[str, float] | None
    anomaly_reasons: list[str] | None
    model_version: str | None
    uploaded_by: UserRef | None
    decided_by: UserRef | None
    decided_at: datetime | None
    decision_comment: str | None
    erp_document_number: str | None
    posted_at: datetime | None
    processed_at: datetime | None
    failure_stage: str | None
    last_error: str | None
    line_items: list[LineItemOut]
    checks: list[CheckOut]
    events: list[AuditEventOut] = []
    allowed_actions: list[Literal["approve", "reject", "retry"]] = []


class InvoicePage(BaseModel):
    items: list[InvoiceListItem]
    total: int
    page: int
    page_size: int


class ApproveIn(BaseModel):
    comment: str | None = Field(default=None, max_length=2000)


class RejectIn(BaseModel):
    comment: str = Field(min_length=3, max_length=2000, description="Reason shared with the AP team")

    @field_validator("comment")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("A rejection reason is required")
        return value


# --- Analytics ----------------------------------------------------------------------------------


class Kpis(BaseModel):
    invoices_received: int
    invoices_processed: int
    spend_approved: float
    straight_through_rate: float | None
    avg_cycle_hours: float | None
    review_queue_count: int
    review_queue_value: float
    oldest_review_hours: float | None
    failed_count: int


class SeriesPoint(BaseModel):
    period: str
    spend: float
    invoices: int


class NamedValue(BaseModel):
    name: str
    value: float
    count: int = 0


class SummaryOut(BaseModel):
    period_days: int
    kpis: Kpis
    status_counts: dict[str, int]
    monthly_spend: list[SeriesPoint]
    top_vendors: list[NamedValue]
    exceptions: list[NamedValue]


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)


class AskOut(BaseModel):
    question: str
    answer: str
    sql: str
    columns: list[str]
    rows: list[list[Any]]
    source: Literal["catalog", "llm"]
    chart: Literal["bar", "line", "table"]
    model: str | None
    truncated: bool


class Suggestions(BaseModel):
    questions: list[str]
    llm_enabled: bool
