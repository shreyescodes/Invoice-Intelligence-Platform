"""Background job handlers: invoice processing and ERP posting."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import utcnow
from app.models import (
    Invoice,
    InvoiceCheck,
    InvoiceLineItem,
    InvoiceStatus,
    Job,
    JobKind,
    Vendor,
)
from app.observability import PIPELINE_DURATION, PIPELINE_OUTCOMES, get_logger
from app.services import jobs
from app.services.anomaly import AnomalyModel, HistoricalInvoice, build_features, explain
from app.services.erp import Erp, ErpRejectedError
from app.services.extraction import ExtractionError, ExtractionResult, InvoiceExtractor
from app.services.invoices import invoice_number_key, record_event, transition
from app.services.policy import evaluate_policy
from app.services.storage import DocumentNotFoundError, DocumentStore
from app.services.validation import DuplicateCandidate, ValidationContext, validate
from app.services.vendors import VendorMatch, match_vendor, sync_vendors

log = get_logger(__name__)

VENDOR_RESYNC_AFTER = timedelta(minutes=1)


class PermanentJobError(Exception):
    """Retrying will not help (unreadable document, ERP business rejection)."""


@dataclass(slots=True)
class PipelineServices:
    settings: Settings
    store: DocumentStore
    extractor: InvoiceExtractor
    erp: Erp
    anomaly_model: AnomalyModel


# --- Processing ----------------------------------------------------------------------------------


def _match_vendor_with_refresh(session: Session, services: PipelineServices, ex: ExtractionResult) -> VendorMatch:
    match = match_vendor(session, ex.vendor_name, ex.vendor_tax_id)
    if match.vendor is not None or not (ex.vendor_tax_id or ex.vendor_name):
        return match
    # The vendor may have been created in the ERP since the last replication run.
    last_sync = session.scalar(select(func.max(Vendor.synced_at)))
    if last_sync is None or utcnow() - last_sync > VENDOR_RESYNC_AFTER:
        sync_vendors(session, services.erp)
        match = match_vendor(session, ex.vendor_name, ex.vendor_tax_id)
    return match


def _find_duplicates(session: Session, invoice: Invoice, vendor: Vendor | None) -> list[DuplicateCandidate]:
    if vendor is None:
        return []
    open_or_done = Invoice.status.not_in([InvoiceStatus.REJECTED, InvoiceStatus.FAILED])
    base = select(Invoice).where(Invoice.vendor_id == vendor.id, Invoice.id != invoice.id, open_or_done)
    candidates: list[DuplicateCandidate] = []
    if invoice.invoice_number_key:
        for other in session.scalars(base.where(Invoice.invoice_number_key == invoice.invoice_number_key).limit(3)):
            candidates.append(
                DuplicateCandidate(
                    str(other.id),
                    other.invoice_number,
                    other.total_amount,
                    other.invoice_date,
                    other.status.value,
                    exact=True,
                )
            )
    if invoice.total_amount is not None and invoice.invoice_date is not None:
        window = (invoice.invoice_date - timedelta(days=7), invoice.invoice_date + timedelta(days=7))
        similar = base.where(
            Invoice.total_amount == invoice.total_amount,
            Invoice.invoice_date.between(*window),
            Invoice.invoice_number_key != invoice.invoice_number_key,
        ).limit(3)
        for other in session.scalars(similar):
            candidates.append(
                DuplicateCandidate(
                    str(other.id),
                    other.invoice_number,
                    other.total_amount,
                    other.invoice_date,
                    other.status.value,
                    exact=False,
                )
            )
    return candidates


def _vendor_history(session: Session, invoice: Invoice) -> list[HistoricalInvoice]:
    if invoice.vendor_id is None or invoice.invoice_date is None:
        return []
    rows = session.execute(
        select(Invoice.invoice_date, Invoice.total_amount, Invoice.subtotal, Invoice.tax_amount)
        .where(
            Invoice.vendor_id == invoice.vendor_id,
            Invoice.id != invoice.id,
            Invoice.status.in_([InvoiceStatus.APPROVED, InvoiceStatus.POSTED]),
            Invoice.invoice_date.is_not(None),
            Invoice.total_amount.is_not(None),
            Invoice.invoice_date <= invoice.invoice_date,
        )
        .order_by(Invoice.invoice_date.desc())
        .limit(24)
    ).all()
    return [
        HistoricalInvoice(
            invoice_date=row.invoice_date,
            total=float(row.total_amount),
            tax_rate=float(row.tax_amount or 0) / float(row.subtotal) if row.subtotal else 0.0,
        )
        for row in rows
    ]


def _apply_extraction(session: Session, invoice: Invoice, ex: ExtractionResult, match: VendorMatch) -> None:
    invoice.vendor_id = match.vendor.id if match.vendor else None
    invoice.vendor_name = ex.vendor_name or (match.vendor.name if match.vendor else None)
    invoice.vendor_tax_id = ex.vendor_tax_id
    invoice.invoice_number = ex.invoice_number
    invoice.invoice_number_key = invoice_number_key(ex.invoice_number)
    invoice.po_number = ex.po_number
    invoice.invoice_date = ex.invoice_date
    invoice.due_date = ex.due_date
    invoice.currency = ex.currency
    invoice.subtotal = ex.subtotal
    invoice.tax_amount = ex.tax_amount
    invoice.total_amount = ex.total_amount
    invoice.extraction_method = ex.method
    invoice.raw_text = ex.raw_text[:100_000] or None
    confidence = dict(ex.field_confidence)
    if match.method == "tax_id":
        confidence["vendor_name"] = 1.0  # confirmed against the vendor master
        ex.field_confidence["vendor_name"] = 1.0
    invoice.field_confidence = {k: round(v, 3) for k, v in confidence.items()}
    invoice.extraction_confidence = ex.confidence
    invoice.line_items = [
        InvoiceLineItem(
            line_no=i + 1,
            description=li.description[:500],
            quantity=li.quantity,
            unit_price=li.unit_price,
            amount=li.amount,
        )
        for i, li in enumerate(ex.line_items)
    ]
    session.flush()


def process_invoice(session: Session, services: PipelineServices, invoice_id: uuid.UUID) -> None:
    invoice = session.get(Invoice, invoice_id)
    if invoice is None:
        raise PermanentJobError(f"invoice {invoice_id} no longer exists")
    if invoice.status not in (InvoiceStatus.RECEIVED, InvoiceStatus.PROCESSING):
        log.info("process_skipped", invoice_id=str(invoice_id), status=invoice.status.value)
        return
    if invoice.status is InvoiceStatus.RECEIVED:
        transition(session, invoice, InvoiceStatus.PROCESSING, "processing_started")

    started = time.perf_counter()
    settings = services.settings
    try:
        document = services.store.get(invoice.storage_key)
        extraction = services.extractor.extract(document, invoice.content_type)
    except (ExtractionError, DocumentNotFoundError) as exc:
        raise PermanentJobError(str(exc)) from exc

    match = _match_vendor_with_refresh(session, services, extraction)
    _apply_extraction(session, invoice, extraction, match)
    purchase_order = services.erp.get_purchase_order(extraction.po_number) if extraction.po_number else None

    report = validate(
        ValidationContext(
            extraction=extraction,
            vendor=match,
            purchase_order=purchase_order,
            duplicates=_find_duplicates(session, invoice, match.vendor),
            today=utcnow().date(),
            price_tolerance_pct=settings.price_tolerance_pct,
            amount_tolerance=settings.amount_tolerance,
        )
    )
    for index, po_item in report.line_po_items.items():
        invoice.line_items[index].po_item = po_item
    invoice.checks = [
        InvoiceCheck(code=c.code, status=c.status, message=c.message[:500], details=c.details) for c in report.checks
    ]

    if invoice.total_amount is not None and invoice.invoice_date is not None:
        features = build_features(
            invoice.total_amount,
            invoice.subtotal,
            invoice.tax_amount,
            invoice.invoice_date,
            len(invoice.line_items),
            _vendor_history(session, invoice),
        )
        invoice.anomaly_score = services.anomaly_model.score(features)
        invoice.anomaly_reasons = explain(features, invoice.anomaly_score, settings.anomaly_review_threshold)
        invoice.model_version = services.anomaly_model.version
    else:
        invoice.anomaly_score, invoice.anomaly_reasons = None, []

    decision = evaluate_policy(
        report.checks, invoice.anomaly_score, invoice.total_amount, extraction.confidence, settings
    )
    now = utcnow()
    invoice.processed_at = now
    invoice.review_reasons = decision.reasons
    summary: dict[str, Any] = {
        "confidence": extraction.confidence,
        "anomaly_score": invoice.anomaly_score,
        "failed_checks": [c.code for c in report.checks if c.status.value == "fail"],
        "warnings": [c.code for c in report.checks if c.status.value == "warn"],
    }
    if decision.auto_approve:
        invoice.auto_approved = True
        invoice.decided_at = now
        transition(session, invoice, InvoiceStatus.APPROVED, "auto_approved", details=summary)
        jobs.enqueue(session, JobKind.POST_TO_ERP, invoice.id, settings.worker_max_attempts)
        outcome = "auto_approved"
    else:
        transition(
            session,
            invoice,
            InvoiceStatus.NEEDS_REVIEW,
            "routed_to_review",
            details={**summary, "reasons": decision.reasons},
        )
        outcome = "needs_review"
    PIPELINE_OUTCOMES.labels(outcome).inc()
    PIPELINE_DURATION.observe(time.perf_counter() - started)
    log.info(
        "invoice_processed",
        invoice_id=str(invoice.id),
        outcome=outcome,
        confidence=extraction.confidence,
        anomaly_score=invoice.anomaly_score,
        checks_failed=summary["failed_checks"],
    )


# --- ERP posting ---------------------------------------------------------------------------------


def _posting_payload(invoice: Invoice, supplier_id: str) -> dict[str, Any]:
    return {
        "SupplierInvoiceIDByInvcgParty": invoice.invoice_number,
        "Supplier": supplier_id,
        "PurchaseOrder": invoice.po_number,
        "DocumentDate": invoice.invoice_date.isoformat() if invoice.invoice_date else None,
        "InvoiceGrossAmount": str(invoice.total_amount or Decimal("0")),
        "DocumentCurrency": invoice.currency,
        "Items": [
            {
                "PurchaseOrderItem": li.po_item,
                "Quantity": format(li.quantity.normalize(), "f"),
                "Amount": str(li.amount),
            }
            for li in invoice.line_items
            if li.po_item
        ],
    }


def post_invoice(session: Session, services: PipelineServices, invoice_id: uuid.UUID) -> None:
    invoice = session.get(Invoice, invoice_id)
    if invoice is None:
        raise PermanentJobError(f"invoice {invoice_id} no longer exists")
    if invoice.status is not InvoiceStatus.APPROVED:
        log.info("posting_skipped", invoice_id=str(invoice_id), status=invoice.status.value)
        return
    if invoice.vendor is None:
        raise PermanentJobError("approved invoice has no vendor")
    try:
        result = services.erp.post_supplier_invoice(str(invoice.id), _posting_payload(invoice, invoice.vendor.erp_id))
    except ErpRejectedError as exc:
        raise PermanentJobError(exc.detail) from exc
    invoice.erp_document_number = result.document_number
    invoice.posted_at = utcnow()
    transition(
        session,
        invoice,
        InvoiceStatus.POSTED,
        "posted_to_erp",
        details={"document_number": result.document_number, "fiscal_year": result.fiscal_year},
    )


HANDLERS = {JobKind.PROCESS_INVOICE: process_invoice, JobKind.POST_TO_ERP: post_invoice}


def on_job_dead(session: Session, job: Job, error: str) -> None:
    """A job ran out of attempts: park the invoice in FAILED so an operator sees it."""
    invoice = session.get(Invoice, job.invoice_id)
    if invoice is None or invoice.status in (InvoiceStatus.POSTED, InvoiceStatus.REJECTED):
        return
    invoice.failure_stage = "posting" if job.kind is JobKind.POST_TO_ERP else "processing"
    invoice.last_error = error[:2000]
    transition(
        session,
        invoice,
        InvoiceStatus.FAILED,
        "failed",
        comment=error[:500],
        details={"stage": invoice.failure_stage, "attempts": job.attempts},
    )


def record_retry(session: Session, job: Job, error: str) -> None:
    invoice = session.get(Invoice, job.invoice_id)
    if invoice is not None:
        record_event(
            session,
            invoice,
            "retry_scheduled",
            comment=error[:500],
            details={"job": job.kind.value, "attempt": job.attempts, "run_after": job.run_after.isoformat()},
        )
