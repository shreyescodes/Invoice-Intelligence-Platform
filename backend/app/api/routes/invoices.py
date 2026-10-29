from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, File, Query, Response, UploadFile, status
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import raiseload

from app.api.deps import Approver, AppSettings, CurrentUser, DbSession, Store, Uploader
from app.errors import DomainError
from app.models import AuditEvent, Invoice, InvoiceStatus, User, UserRole, Vendor
from app.schemas import (
    ApproveIn,
    AuditEventOut,
    InvoiceDetail,
    InvoiceListItem,
    InvoicePage,
    Problem,
    RejectIn,
)
from app.services.invoices import InvoiceService
from app.services.preview import get_preview

router = APIRouter(prefix="/invoices", tags=["invoices"])

SORTABLE: dict[str, Any] = {
    "created_at": Invoice.created_at,
    "invoice_date": Invoice.invoice_date,
    "total_amount": Invoice.total_amount,
    "anomaly_score": Invoice.anomaly_score,
    "vendor_name": Invoice.vendor_name,
    "updated_at": Invoice.updated_at,
}
ERRORS: dict[int | str, dict[str, Any]] = {
    403: {"model": Problem},
    404: {"model": Problem},
    409: {"model": Problem},
}


def allowed_actions(invoice: Invoice, user: User) -> list[str]:
    actions: list[str] = []
    if (
        invoice.status is InvoiceStatus.NEEDS_REVIEW
        and user.role in (UserRole.APPROVER, UserRole.ADMIN)
        and invoice.uploaded_by_id != user.id
    ):
        actions += ["approve", "reject"]
    if invoice.status is InvoiceStatus.FAILED and user.role is UserRole.ADMIN:
        actions.append("retry")
    return actions


def to_detail(session: DbSession, invoice: Invoice, user: User) -> InvoiceDetail:
    events = session.scalars(
        select(AuditEvent).where(AuditEvent.invoice_id == invoice.id).order_by(AuditEvent.created_at, AuditEvent.id)
    ).all()
    detail = InvoiceDetail.model_validate(invoice)
    detail.events = [AuditEventOut.model_validate(e) for e in events]
    detail.allowed_actions = allowed_actions(invoice, user)  # type: ignore[assignment]
    return detail


def _filtered(
    statuses: list[InvoiceStatus],
    vendor_id: uuid.UUID | None,
    q: str | None,
    date_from: date | None,
    date_to: date | None,
) -> Select[Invoice]:
    stmt = select(Invoice)
    if statuses:
        stmt = stmt.where(Invoice.status.in_(statuses))
    if vendor_id:
        stmt = stmt.where(Invoice.vendor_id == vendor_id)
    if date_from:
        stmt = stmt.where(Invoice.invoice_date >= date_from)
    if date_to:
        stmt = stmt.where(Invoice.invoice_date <= date_to)
    if q:
        needle = q.strip().lower()
        stmt = stmt.outerjoin(Vendor, Vendor.id == Invoice.vendor_id).where(
            or_(
                func.lower(Invoice.invoice_number).contains(needle, autoescape=True),
                func.lower(Invoice.vendor_name).contains(needle, autoescape=True),
                func.lower(Vendor.name).contains(needle, autoescape=True),
                func.lower(Invoice.po_number).contains(needle, autoescape=True),
                func.lower(Invoice.file_name).contains(needle, autoescape=True),
            )
        )
    return stmt


@router.get("", response_model=InvoicePage, summary="Search and page through invoices")
def list_invoices(
    session: DbSession,
    _: CurrentUser,
    status_: Annotated[list[InvoiceStatus], Query(alias="status")] = [],  # noqa: B006 - FastAPI query list
    vendor_id: uuid.UUID | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    sort: Annotated[str, Query(pattern=r"^-?[a-z_]+$")] = "-created_at",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> InvoicePage:
    stmt = _filtered(status_, vendor_id, q, date_from, date_to)
    total = session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0

    column = SORTABLE.get(sort.lstrip("-"))
    if column is None:
        raise DomainError(f"Cannot sort by '{sort}'. Use one of: {', '.join(SORTABLE)}")
    order = column.desc().nulls_last() if sort.startswith("-") else column.asc().nulls_last()
    rows = session.scalars(
        stmt.options(raiseload(Invoice.uploaded_by), raiseload(Invoice.decided_by))
        .order_by(order, Invoice.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).unique()
    return InvoicePage(
        items=[InvoiceListItem.model_validate(r) for r in rows], total=total, page=page, page_size=page_size
    )


@router.post(
    "",
    response_model=InvoiceListItem,
    status_code=status.HTTP_202_ACCEPTED,
    responses={409: {"model": Problem}, 413: {"model": Problem}, 415: {"model": Problem}},
    summary="Upload an invoice document (PDF, PNG or JPEG) for processing",
)
def upload_invoice(
    response: Response,
    session: DbSession,
    settings: AppSettings,
    store: Store,
    user: Uploader,
    file: Annotated[UploadFile, File(description="Invoice document")],
) -> Invoice:
    data = file.file.read(settings.max_upload_bytes + 1)
    invoice = InvoiceService(session, settings, store).ingest(data, file.filename, user)
    response.headers["Location"] = f"/api/v1/invoices/{invoice.id}"
    return invoice


@router.get("/{invoice_id}", response_model=InvoiceDetail, responses=ERRORS)
def get_invoice(
    invoice_id: uuid.UUID, session: DbSession, settings: AppSettings, store: Store, user: CurrentUser
) -> InvoiceDetail:
    invoice = InvoiceService(session, settings, store).get(invoice_id)
    return to_detail(session, invoice, user)


@router.get(
    "/{invoice_id}/document",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}, "image/png": {}, "image/jpeg": {}}}, 404: {"model": Problem}},
    summary="Download the original document",
)
def get_document(
    invoice_id: uuid.UUID, session: DbSession, settings: AppSettings, store: Store, _: CurrentUser
) -> Response:
    invoice = InvoiceService(session, settings, store).get(invoice_id)
    data = store.get(invoice.storage_key)
    return Response(
        content=data,
        media_type=invoice.content_type,
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(invoice.file_name)}",
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(
    "/{invoice_id}/preview",
    response_class=Response,
    responses={200: {"content": {"image/png": {}, "image/jpeg": {}}}, 404: {"model": Problem}},
    summary="Rendered page image for previews (PDF pages are rasterised and cached)",
)
def get_preview_image(
    invoice_id: uuid.UUID,
    session: DbSession,
    settings: AppSettings,
    store: Store,
    _: CurrentUser,
    page: Annotated[int, Query(ge=1, le=50)] = 1,
) -> Response:
    invoice = InvoiceService(session, settings, store).get(invoice_id)
    data, media_type, pages = get_preview(store, invoice, page)
    return Response(
        content=data,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=3600", "X-Page-Count": str(pages)},
    )


@router.post("/{invoice_id}/approve", response_model=InvoiceDetail, responses=ERRORS)
def approve_invoice(
    invoice_id: uuid.UUID, body: ApproveIn, session: DbSession, settings: AppSettings, store: Store, user: Approver
) -> InvoiceDetail:
    invoice = InvoiceService(session, settings, store).approve(invoice_id, user, body.comment)
    return to_detail(session, invoice, user)


@router.post("/{invoice_id}/reject", response_model=InvoiceDetail, responses=ERRORS)
def reject_invoice(
    invoice_id: uuid.UUID, body: RejectIn, session: DbSession, settings: AppSettings, store: Store, user: Approver
) -> InvoiceDetail:
    invoice = InvoiceService(session, settings, store).reject(invoice_id, user, body.comment)
    return to_detail(session, invoice, user)


@router.post(
    "/{invoice_id}/retry",
    response_model=InvoiceDetail,
    responses=ERRORS,
    summary="Re-run a failed processing or posting step (administrators)",
)
def retry_invoice(
    invoice_id: uuid.UUID, session: DbSession, settings: AppSettings, store: Store, user: CurrentUser
) -> InvoiceDetail:
    invoice = InvoiceService(session, settings, store).retry(invoice_id, user)
    return to_detail(session, invoice, user)
