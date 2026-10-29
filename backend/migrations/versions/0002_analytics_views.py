"""Analytics views for reporting and natural-language questions.

The views are the only objects the read-only reporting role can see, so the NL-to-SQL feature
cannot reach credentials, the job queue or raw document text even if the SQL guard were bypassed.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-29
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

READONLY_ROLE = "iip_readonly"

VIEWS = {
    "analytics_vendors": """
        SELECT v.erp_id AS vendor_id, v.name AS vendor_name, v.city, v.payment_terms_days, v.is_active
        FROM vendors v
    """,
    "analytics_invoices": """
        SELECT i.id AS invoice_id, i.invoice_number, i.status, v.erp_id AS vendor_id,
               COALESCE(v.name, i.vendor_name) AS vendor_name, i.po_number, i.invoice_date, i.due_date,
               i.currency, i.subtotal, i.tax_amount, i.total_amount, i.anomaly_score, i.auto_approved,
               i.extraction_confidence, i.created_at AS received_at, i.decided_at, i.posted_at
        FROM invoices i
        LEFT JOIN vendors v ON v.id = i.vendor_id
    """,
    "analytics_line_items": """
        SELECT li.invoice_id, li.line_no, li.description, li.quantity, li.unit_price, li.amount, li.po_item
        FROM invoice_line_items li
    """,
    "analytics_checks": """
        SELECT c.invoice_id, c.code AS check_code, c.status AS check_status, c.message
        FROM invoice_checks c
    """,
}


def upgrade() -> None:
    for name, body in VIEWS.items():
        op.execute(f"CREATE VIEW {name} AS {body.strip()}")
    if op.get_bind().dialect.name == "postgresql":
        views = ", ".join(VIEWS)
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{READONLY_ROLE}') THEN
                    GRANT SELECT ON {views} TO {READONLY_ROLE};
                END IF;
            END
            $$;
            """
        )


def downgrade() -> None:
    for name in reversed(list(VIEWS)):
        op.execute(f"DROP VIEW IF EXISTS {name}")
