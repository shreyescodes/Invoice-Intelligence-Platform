"""Operational KPIs for the dashboard."""

from __future__ import annotations

from datetime import date, timedelta
from statistics import fmean
from typing import Any

from sqlalchemy import case, func, literal_column, select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import CheckStatus, Invoice, InvoiceCheck, InvoiceStatus, Vendor
from app.schemas import Kpis, NamedValue, SeriesPoint, SummaryOut

SPEND_STATUSES = (InvoiceStatus.APPROVED, InvoiceStatus.POSTED)


def _month_bucket(session: Session, column: Any) -> Any:
    if session.get_bind().dialect.name == "postgresql":
        # Literals, not bound parameters: PostgreSQL only matches GROUP BY expressions textually.
        return func.to_char(func.date_trunc(literal_column("'month'"), column), literal_column("'YYYY-MM'"))
    return func.strftime(literal_column("'%Y-%m'"), column)


def _month_starts(months: int, today: date) -> list[str]:
    year, month = today.year, today.month
    labels: list[str] = []
    for _ in range(months):
        labels.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return list(reversed(labels))


def dashboard_summary(session: Session, days: int = 90) -> SummaryOut:
    now = utcnow()
    since = now - timedelta(days=days)
    since_date = since.date()

    status_counts = {s.value: 0 for s in InvoiceStatus}
    for status, count in session.execute(select(Invoice.status, func.count()).group_by(Invoice.status)):
        status_counts[status.value] = int(count)

    received = session.scalar(select(func.count()).where(Invoice.created_at >= since)) or 0
    processed = session.scalar(select(func.count()).where(Invoice.processed_at >= since)) or 0
    spend = session.scalar(
        select(func.coalesce(func.sum(Invoice.total_amount), 0)).where(
            Invoice.status.in_(SPEND_STATUSES), Invoice.invoice_date >= since_date
        )
    )

    decided = session.execute(
        select(
            func.count(),
            func.sum(case((Invoice.auto_approved.is_(True), 1), else_=0)),
        ).where(
            Invoice.decided_at >= since,
            Invoice.status.in_([*SPEND_STATUSES, InvoiceStatus.REJECTED]),
        )
    ).one()
    stp_rate = round(float(decided[1] or 0) / decided[0], 4) if decided[0] else None

    cycle = session.execute(select(Invoice.created_at, Invoice.posted_at).where(Invoice.posted_at >= since)).all()
    hours = [(p - c).total_seconds() / 3600 for c, p in cycle if p is not None]
    avg_cycle = round(fmean(hours), 1) if hours else None

    queue = session.execute(
        select(func.count(), func.coalesce(func.sum(Invoice.total_amount), 0), func.min(Invoice.created_at)).where(
            Invoice.status == InvoiceStatus.NEEDS_REVIEW
        )
    ).one()
    oldest = round((now - queue[2]).total_seconds() / 3600, 1) if queue[2] else None

    month = _month_bucket(session, Invoice.invoice_date).label("month")
    twelve_months = _month_starts(12, now.date())
    monthly_rows = {
        row.month: row
        for row in session.execute(
            select(month, func.sum(Invoice.total_amount).label("spend"), func.count().label("n"))
            .where(
                Invoice.status.in_(SPEND_STATUSES), Invoice.invoice_date >= date.fromisoformat(f"{twelve_months[0]}-01")
            )
            .group_by(month)
        )
    }
    monthly = [
        SeriesPoint(
            period=m,
            spend=float(monthly_rows[m].spend or 0) if m in monthly_rows else 0.0,
            invoices=int(monthly_rows[m].n) if m in monthly_rows else 0,
        )
        for m in twelve_months
    ]

    vendor_name = func.coalesce(Vendor.name, Invoice.vendor_name, literal_column("'Unknown'"))
    top_vendors = [
        NamedValue(name=name, value=float(total or 0), count=int(n))
        for name, total, n in session.execute(
            select(vendor_name, func.sum(Invoice.total_amount), func.count())
            .select_from(Invoice)
            .outerjoin(Vendor, Vendor.id == Invoice.vendor_id)
            .where(Invoice.status.in_(SPEND_STATUSES), Invoice.invoice_date >= since_date)
            .group_by(vendor_name)
            .order_by(func.sum(Invoice.total_amount).desc())
            .limit(6)
        )
    ]

    exceptions = [
        NamedValue(name=code, value=float(n), count=int(n))
        for code, n in session.execute(
            select(InvoiceCheck.code, func.count())
            .join(Invoice, Invoice.id == InvoiceCheck.invoice_id)
            .where(
                InvoiceCheck.status.in_([CheckStatus.FAIL, CheckStatus.WARN]),
                Invoice.created_at >= since,
            )
            .group_by(InvoiceCheck.code)
            .order_by(func.count().desc())
        )
    ]

    return SummaryOut(
        period_days=days,
        kpis=Kpis(
            invoices_received=int(received),
            invoices_processed=int(processed),
            spend_approved=float(spend or 0),
            straight_through_rate=stp_rate,
            avg_cycle_hours=avg_cycle,
            review_queue_count=int(queue[0]),
            review_queue_value=float(queue[1] or 0),
            oldest_review_hours=oldest,
            failed_count=status_counts[InvoiceStatus.FAILED.value],
        ),
        status_counts=status_counts,
        monthly_spend=monthly,
        top_vendors=top_vendors,
        exceptions=exceptions,
    )
