"""SQLAlchemy ORM models.

State changes to an invoice always go through `app.services.invoices` so that the audit trail and the
job queue are written in the same transaction as the invoice itself.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, UTCDateTime, utcnow

# SQLite only auto-increments INTEGER PRIMARY KEY columns.
BigIntPK = BigInteger().with_variant(Integer, "sqlite")
Money = Numeric(14, 2)
Quantity = Numeric(14, 3)


def _enum(cls: type[StrEnum], length: int = 20) -> Enum:
    return Enum(cls, native_enum=False, length=length, values_callable=lambda e: [m.value for m in e])


class UserRole(StrEnum):
    ADMIN = "admin"
    APPROVER = "approver"
    CLERK = "clerk"
    VIEWER = "viewer"


class InvoiceStatus(StrEnum):
    RECEIVED = "received"
    PROCESSING = "processing"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    POSTED = "posted"
    REJECTED = "rejected"
    FAILED = "failed"


class CheckStatus(StrEnum):
    PASS = "pass"  # noqa: S105 - not a password
    WARN = "warn"
    FAIL = "fail"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    DEAD = "dead"


class JobKind(StrEnum):
    PROCESS_INVOICE = "process_invoice"
    POST_TO_ERP = "post_to_erp"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(_enum(UserRole))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Vendor(Base):
    """Local replica of the ERP supplier master, refreshed by the worker."""

    __tablename__ = "vendors"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    erp_id: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    tax_id: Mapped[str | None] = mapped_column(String(32), unique=True)
    city: Mapped[str | None] = mapped_column(String(100))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    payment_terms_days: Mapped[int] = mapped_column(Integer, default=30)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    synced_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        Index("ix_invoices_vendor_number_key", "vendor_id", "invoice_number_key"),
        Index("ix_invoices_status_created", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    status: Mapped[InvoiceStatus] = mapped_column(_enum(InvoiceStatus), default=InvoiceStatus.RECEIVED)
    version: Mapped[int] = mapped_column(Integer, default=1)

    # Source document
    file_name: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    file_size: Mapped[int] = mapped_column(Integer)
    file_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    storage_key: Mapped[str] = mapped_column(String(500))
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))

    # Extracted header fields
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vendors.id"), index=True)
    vendor_name: Mapped[str | None] = mapped_column(String(200))
    vendor_tax_id: Mapped[str | None] = mapped_column(String(32))
    invoice_number: Mapped[str | None] = mapped_column(String(64))
    # Upper-cased, punctuation-free form used for duplicate detection ("INV-001" == "inv 001").
    invoice_number_key: Mapped[str | None] = mapped_column(String(64))
    po_number: Mapped[str | None] = mapped_column(String(32), index=True)
    invoice_date: Mapped[date | None] = mapped_column(Date, index=True)
    due_date: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    subtotal: Mapped[Decimal | None] = mapped_column(Money)
    tax_amount: Mapped[Decimal | None] = mapped_column(Money)
    total_amount: Mapped[Decimal | None] = mapped_column(Money)
    extraction_method: Mapped[str | None] = mapped_column(String(40))
    extraction_confidence: Mapped[float | None] = mapped_column(Float)
    field_confidence: Mapped[dict[str, float] | None] = mapped_column(JSON)
    raw_text: Mapped[str | None] = mapped_column(Text, deferred=True)

    # Risk assessment
    anomaly_score: Mapped[float | None] = mapped_column(Float)
    anomaly_reasons: Mapped[list[str] | None] = mapped_column(JSON)
    review_reasons: Mapped[list[str] | None] = mapped_column(JSON)
    model_version: Mapped[str | None] = mapped_column(String(40))

    # Decision
    auto_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    decision_comment: Mapped[str | None] = mapped_column(Text)

    # ERP posting
    erp_document_number: Mapped[str | None] = mapped_column(String(32))
    posted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    # Operations
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    failure_stage: Mapped[str | None] = mapped_column(String(20))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    vendor: Mapped[Vendor | None] = relationship(lazy="joined")
    uploaded_by: Mapped[User | None] = relationship(foreign_keys=[uploaded_by_id], lazy="joined")
    decided_by: Mapped[User | None] = relationship(foreign_keys=[decided_by_id], lazy="joined")
    line_items: Mapped[list[InvoiceLineItem]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", order_by="InvoiceLineItem.line_no"
    )
    checks: Mapped[list[InvoiceCheck]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", order_by="InvoiceCheck.id"
    )

    # Optimistic locking: concurrent approve/reject requests cannot both win.
    __mapper_args__ = {"version_id_col": version}


class InvoiceLineItem(Base):
    __tablename__ = "invoice_line_items"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(500))
    quantity: Mapped[Decimal] = mapped_column(Quantity)
    unit_price: Mapped[Decimal] = mapped_column(Money)
    amount: Mapped[Decimal] = mapped_column(Money)
    po_item: Mapped[str | None] = mapped_column(String(10))

    invoice: Mapped[Invoice] = relationship(back_populates="line_items")


class InvoiceCheck(Base):
    """Outcome of one validation rule for an invoice."""

    __tablename__ = "invoice_checks"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(40))
    status: Mapped[CheckStatus] = mapped_column(_enum(CheckStatus, 10))
    message: Mapped[str] = mapped_column(String(500))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    invoice: Mapped[Invoice] = relationship(back_populates="checks")


class AuditEvent(Base):
    """Append-only history of everything that happened to an invoice."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(50))
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str | None] = mapped_column(String(20))
    comment: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)

    actor: Mapped[User | None] = relationship(lazy="joined")
    # Declared so the unit of work inserts the invoice before its events.
    invoice: Mapped[Invoice | None] = relationship(lazy="raise")


class Job(Base):
    """Durable work queue backed by the primary database (see docs/adr/0002-database-job-queue.md)."""

    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_status_run_after", "status", "run_after"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    kind: Mapped[JobKind] = mapped_column(_enum(JobKind, 40))
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    status: Mapped[JobStatus] = mapped_column(_enum(JobStatus), default=JobStatus.QUEUED)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    run_after: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    locked_by: Mapped[str | None] = mapped_column(String(100))
    locked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    invoice: Mapped[Invoice] = relationship(lazy="raise")
