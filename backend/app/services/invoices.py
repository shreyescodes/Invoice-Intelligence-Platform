"""Invoice lifecycle commands: ingest, approve, reject, reprocess.

Every state change writes an audit event and, where follow-up work is needed, a job - in the same
transaction as the change itself.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import utcnow
from app.errors import (
    ConflictError,
    DocumentTooLargeError,
    InvalidStateError,
    NotFoundError,
    PermissionDeniedError,
    UnsupportedDocumentError,
)
from app.models import AuditEvent, Invoice, InvoiceStatus, JobKind, User, UserRole
from app.observability import DECISIONS, INVOICES_UPLOADED, get_logger
from app.services import jobs
from app.services.policy import approval_limit
from app.services.storage import DocumentStore

log = get_logger(__name__)

_SIGNATURES: tuple[tuple[bytes, str, str], ...] = (
    (b"%PDF-", "application/pdf", "pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
)


def sniff_content_type(data: bytes) -> tuple[str, str]:
    """Trust the bytes, not the client's Content-Type header."""
    head = data[:1024].lstrip()
    for signature, content_type, extension in _SIGNATURES:
        if head.startswith(signature):
            return content_type, extension
    raise UnsupportedDocumentError("Only PDF, PNG and JPEG invoices are supported")


def clean_filename(name: str | None) -> str:
    name = unicodedata.normalize("NFKC", (name or "invoice").replace("\\", "/").rsplit("/", 1)[-1])
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip() or "invoice"
    return name[-200:]


def invoice_number_key(value: str | None) -> str | None:
    if not value:
        return None
    return re.sub(r"[^A-Z0-9]", "", value.upper()) or None


def record_event(
    session: Session,
    invoice: Invoice,
    action: str,
    *,
    actor: User | None = None,
    from_status: InvoiceStatus | None = None,
    to_status: InvoiceStatus | None = None,
    comment: str | None = None,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        invoice_id=invoice.id,
        actor_id=actor.id if actor else None,
        action=action,
        from_status=from_status.value if from_status else None,
        to_status=to_status.value if to_status else None,
        comment=comment,
        details=details,
    )
    session.add(event)
    return event


def transition(
    session: Session,
    invoice: Invoice,
    to_status: InvoiceStatus,
    action: str,
    *,
    actor: User | None = None,
    comment: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    from_status = invoice.status
    invoice.status = to_status
    invoice.updated_at = utcnow()
    record_event(
        session,
        invoice,
        action,
        actor=actor,
        from_status=from_status,
        to_status=to_status,
        comment=comment,
        details=details,
    )


class InvoiceService:
    def __init__(self, session: Session, settings: Settings, store: DocumentStore) -> None:
        self.session = session
        self.settings = settings
        self.store = store

    def get(self, invoice_id: uuid.UUID) -> Invoice:
        invoice = self.session.get(Invoice, invoice_id)
        if invoice is None:
            raise NotFoundError("Invoice not found")
        return invoice

    def ingest(self, data: bytes, filename: str | None, uploader: User | None) -> Invoice:
        if not data:
            raise UnsupportedDocumentError("The uploaded file is empty")
        if len(data) > self.settings.max_upload_bytes:
            raise DocumentTooLargeError(
                f"Files larger than {self.settings.max_upload_bytes // (1024 * 1024)} MB are not accepted"
            )
        content_type, extension = sniff_content_type(data)
        digest = hashlib.sha256(data).hexdigest()

        existing = self.session.scalar(select(Invoice).where(Invoice.file_sha256 == digest))
        if existing is not None:
            raise ConflictError("This document has already been uploaded", invoice_id=str(existing.id))

        invoice_id = uuid.uuid4()
        now = utcnow()
        key = f"invoices/{now:%Y/%m}/{invoice_id}.{extension}"
        self.store.put(key, data, content_type)

        invoice = Invoice(
            id=invoice_id,
            status=InvoiceStatus.RECEIVED,
            file_name=clean_filename(filename),
            content_type=content_type,
            file_size=len(data),
            file_sha256=digest,
            storage_key=key,
            uploaded_by_id=uploader.id if uploader else None,
            created_at=now,
            updated_at=now,
        )
        self.session.add(invoice)
        record_event(
            self.session,
            invoice,
            "uploaded",
            actor=uploader,
            to_status=InvoiceStatus.RECEIVED,
            details={"file_name": invoice.file_name, "size": len(data)},
        )
        jobs.enqueue(self.session, JobKind.PROCESS_INVOICE, invoice_id, self.settings.worker_max_attempts)
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            self.store.delete(key)  # don't leave orphaned documents behind
            raise
        INVOICES_UPLOADED.inc()
        log.info("invoice_uploaded", invoice_id=str(invoice_id), size=len(data), content_type=content_type)
        return invoice

    def _check_can_decide(self, invoice: Invoice, user: User) -> None:
        if user.role not in (UserRole.APPROVER, UserRole.ADMIN):
            raise PermissionDeniedError("Only approvers can approve or reject invoices")
        if invoice.status is not InvoiceStatus.NEEDS_REVIEW:
            raise InvalidStateError(f"Invoice is {invoice.status.value.replace('_', ' ')}, not awaiting review")
        if invoice.uploaded_by_id == user.id:
            raise PermissionDeniedError("Segregation of duties: you cannot approve an invoice you uploaded")

    def approve(self, invoice_id: uuid.UUID, user: User, comment: str | None) -> Invoice:
        invoice = self.get(invoice_id)
        self._check_can_decide(invoice, user)
        limit = approval_limit(user.role, self.settings)
        if limit is not None and (invoice.total_amount or Decimal("0")) > limit:
            raise PermissionDeniedError(f"Invoices above {limit:,.0f} need an administrator's approval")
        if invoice.vendor_id is None:
            raise InvalidStateError("Assign a vendor from the vendor master before approving")

        invoice.decided_by_id = user.id
        invoice.decided_at = utcnow()
        invoice.decision_comment = comment
        invoice.auto_approved = False
        transition(self.session, invoice, InvoiceStatus.APPROVED, "approved", actor=user, comment=comment)
        jobs.enqueue(self.session, JobKind.POST_TO_ERP, invoice.id, self.settings.worker_max_attempts)
        self.session.commit()
        DECISIONS.labels("approved").inc()
        log.info("invoice_approved", invoice_id=str(invoice.id), user_id=str(user.id))
        return invoice

    def reject(self, invoice_id: uuid.UUID, user: User, comment: str) -> Invoice:
        invoice = self.get(invoice_id)
        self._check_can_decide(invoice, user)
        invoice.decided_by_id = user.id
        invoice.decided_at = utcnow()
        invoice.decision_comment = comment
        transition(self.session, invoice, InvoiceStatus.REJECTED, "rejected", actor=user, comment=comment)
        self.session.commit()
        DECISIONS.labels("rejected").inc()
        log.info("invoice_rejected", invoice_id=str(invoice.id), user_id=str(user.id))
        return invoice

    def retry(self, invoice_id: uuid.UUID, user: User) -> Invoice:
        """Re-run a failed stage (extraction or ERP posting) after the cause has been fixed."""
        if user.role is not UserRole.ADMIN:
            raise PermissionDeniedError("Only administrators can retry failed invoices")
        invoice = self.get(invoice_id)
        if invoice.status is not InvoiceStatus.FAILED:
            raise InvalidStateError("Only failed invoices can be retried")
        if invoice.failure_stage == "posting":
            target, kind = InvoiceStatus.APPROVED, JobKind.POST_TO_ERP
        else:
            target, kind = InvoiceStatus.RECEIVED, JobKind.PROCESS_INVOICE
        invoice.last_error = None
        invoice.failure_stage = None
        transition(self.session, invoice, target, "retried", actor=user)
        jobs.enqueue(self.session, kind, invoice.id, self.settings.worker_max_attempts)
        self.session.commit()
        return invoice
