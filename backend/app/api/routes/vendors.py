from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter
from sqlalchemy import case, func, select

from app.api.deps import CurrentUser, DbSession
from app.models import Invoice, InvoiceStatus, Vendor
from app.schemas import VendorOut

router = APIRouter(prefix="/vendors", tags=["vendors"])

_OPEN = (InvoiceStatus.RECEIVED, InvoiceStatus.PROCESSING, InvoiceStatus.NEEDS_REVIEW, InvoiceStatus.APPROVED)
_SPEND = (InvoiceStatus.APPROVED, InvoiceStatus.POSTED)


@router.get("", response_model=list[VendorOut], summary="Vendor master with invoice statistics")
def list_vendors(session: DbSession, _: CurrentUser) -> list[VendorOut]:
    stats = (
        select(
            Invoice.vendor_id.label("vendor_id"),
            func.count().label("invoice_count"),
            func.sum(case((Invoice.status.in_(_OPEN), 1), else_=0)).label("open_count"),
            func.sum(case((Invoice.status.in_(_SPEND), Invoice.total_amount), else_=0)).label("total_spend"),
            func.max(Invoice.invoice_date).label("last_invoice_date"),
        )
        .where(Invoice.vendor_id.is_not(None))
        .group_by(Invoice.vendor_id)
        .subquery()
    )
    rows = session.execute(
        select(Vendor, stats.c.invoice_count, stats.c.open_count, stats.c.total_spend, stats.c.last_invoice_date)
        .outerjoin(stats, stats.c.vendor_id == Vendor.id)
        .order_by(func.coalesce(stats.c.total_spend, 0).desc(), Vendor.name)
    ).all()
    result: list[VendorOut] = []
    for vendor, count, open_count, spend, last_date in rows:
        out = VendorOut.model_validate(vendor)
        out.invoice_count = int(count or 0)
        out.open_count = int(open_count or 0)
        out.total_spend = Decimal(str(spend or 0))
        out.last_invoice_date = last_date
        result.append(out)
    return result
