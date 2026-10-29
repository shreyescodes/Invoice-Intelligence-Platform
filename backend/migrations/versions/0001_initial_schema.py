"""Initial schema: users, vendors, invoices, line items, checks, audit trail, job queue.

Revision ID: 0001
Revises:
Create Date: 2026-10-29
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('users',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('full_name', sa.String(length=200), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('role', sa.Enum('admin', 'approver', 'clerk', 'viewer', name='userrole', native_enum=False, length=20), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)

    op.create_table('vendors',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('erp_id', sa.String(length=20), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('tax_id', sa.String(length=32), nullable=True),
    sa.Column('city', sa.String(length=100), nullable=True),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('payment_terms_days', sa.Integer(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('synced_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('erp_id'),
    sa.UniqueConstraint('tax_id')
    )
    op.create_index(op.f('ix_vendors_name'), 'vendors', ['name'], unique=False)

    op.create_table('invoices',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.Enum('received', 'processing', 'needs_review', 'approved', 'posted', 'rejected', 'failed', name='invoicestatus', native_enum=False, length=20), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('file_name', sa.String(length=255), nullable=False),
    sa.Column('content_type', sa.String(length=100), nullable=False),
    sa.Column('file_size', sa.Integer(), nullable=False),
    sa.Column('file_sha256', sa.String(length=64), nullable=False),
    sa.Column('storage_key', sa.String(length=500), nullable=False),
    sa.Column('uploaded_by_id', sa.Uuid(), nullable=True),
    sa.Column('vendor_id', sa.Uuid(), nullable=True),
    sa.Column('vendor_name', sa.String(length=200), nullable=True),
    sa.Column('vendor_tax_id', sa.String(length=32), nullable=True),
    sa.Column('invoice_number', sa.String(length=64), nullable=True),
    sa.Column('invoice_number_key', sa.String(length=64), nullable=True),
    sa.Column('po_number', sa.String(length=32), nullable=True),
    sa.Column('invoice_date', sa.Date(), nullable=True),
    sa.Column('due_date', sa.Date(), nullable=True),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('subtotal', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('tax_amount', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('total_amount', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('extraction_method', sa.String(length=40), nullable=True),
    sa.Column('extraction_confidence', sa.Float(), nullable=True),
    sa.Column('field_confidence', sa.JSON(), nullable=True),
    sa.Column('raw_text', sa.Text(), nullable=True),
    sa.Column('anomaly_score', sa.Float(), nullable=True),
    sa.Column('anomaly_reasons', sa.JSON(), nullable=True),
    sa.Column('review_reasons', sa.JSON(), nullable=True),
    sa.Column('model_version', sa.String(length=40), nullable=True),
    sa.Column('auto_approved', sa.Boolean(), nullable=False),
    sa.Column('decided_by_id', sa.Uuid(), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decision_comment', sa.Text(), nullable=True),
    sa.Column('erp_document_number', sa.String(length=32), nullable=True),
    sa.Column('posted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('failure_stage', sa.String(length=20), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['decided_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['uploaded_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['vendor_id'], ['vendors.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('file_sha256')
    )
    op.create_index(op.f('ix_invoices_invoice_date'), 'invoices', ['invoice_date'], unique=False)
    op.create_index(op.f('ix_invoices_po_number'), 'invoices', ['po_number'], unique=False)
    op.create_index('ix_invoices_status_created', 'invoices', ['status', 'created_at'], unique=False)
    op.create_index(op.f('ix_invoices_vendor_id'), 'invoices', ['vendor_id'], unique=False)
    op.create_index('ix_invoices_vendor_number_key', 'invoices', ['vendor_id', 'invoice_number_key'], unique=False)

    op.create_table('audit_events',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('invoice_id', sa.Uuid(), nullable=True),
    sa.Column('actor_id', sa.Uuid(), nullable=True),
    sa.Column('action', sa.String(length=50), nullable=False),
    sa.Column('from_status', sa.String(length=20), nullable=True),
    sa.Column('to_status', sa.String(length=20), nullable=True),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.Column('details', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audit_events_created_at'), 'audit_events', ['created_at'], unique=False)
    op.create_index(op.f('ix_audit_events_invoice_id'), 'audit_events', ['invoice_id'], unique=False)

    op.create_table('invoice_checks',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('invoice_id', sa.Uuid(), nullable=False),
    sa.Column('code', sa.String(length=40), nullable=False),
    sa.Column('status', sa.Enum('pass', 'warn', 'fail', name='checkstatus', native_enum=False, length=10), nullable=False),
    sa.Column('message', sa.String(length=500), nullable=False),
    sa.Column('details', sa.JSON(), nullable=True),
    sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_invoice_checks_invoice_id'), 'invoice_checks', ['invoice_id'], unique=False)

    op.create_table('invoice_line_items',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('invoice_id', sa.Uuid(), nullable=False),
    sa.Column('line_no', sa.Integer(), nullable=False),
    sa.Column('description', sa.String(length=500), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('unit_price', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('po_item', sa.String(length=10), nullable=True),
    sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_invoice_line_items_invoice_id'), 'invoice_line_items', ['invoice_id'], unique=False)

    op.create_table('jobs',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('kind', sa.Enum('process_invoice', 'post_to_erp', name='jobkind', native_enum=False, length=40), nullable=False),
    sa.Column('invoice_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.Enum('queued', 'running', 'succeeded', 'dead', name='jobstatus', native_enum=False, length=20), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('max_attempts', sa.Integer(), nullable=False),
    sa.Column('run_after', sa.DateTime(timezone=True), nullable=False),
    sa.Column('locked_by', sa.String(length=100), nullable=True),
    sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_jobs_invoice_id'), 'jobs', ['invoice_id'], unique=False)
    op.create_index('ix_jobs_status_run_after', 'jobs', ['status', 'run_after'], unique=False)



def downgrade() -> None:
    op.drop_index('ix_jobs_status_run_after', table_name='jobs')
    op.drop_index(op.f('ix_jobs_invoice_id'), table_name='jobs')

    op.drop_table('jobs')
    op.drop_index(op.f('ix_invoice_line_items_invoice_id'), table_name='invoice_line_items')

    op.drop_table('invoice_line_items')
    op.drop_index(op.f('ix_invoice_checks_invoice_id'), table_name='invoice_checks')

    op.drop_table('invoice_checks')
    op.drop_index(op.f('ix_audit_events_invoice_id'), table_name='audit_events')
    op.drop_index(op.f('ix_audit_events_created_at'), table_name='audit_events')

    op.drop_table('audit_events')
    op.drop_index('ix_invoices_vendor_number_key', table_name='invoices')
    op.drop_index(op.f('ix_invoices_vendor_id'), table_name='invoices')
    op.drop_index('ix_invoices_status_created', table_name='invoices')
    op.drop_index(op.f('ix_invoices_po_number'), table_name='invoices')
    op.drop_index(op.f('ix_invoices_invoice_date'), table_name='invoices')

    op.drop_table('invoices')
    op.drop_index(op.f('ix_vendors_name'), table_name='vendors')

    op.drop_table('vendors')
    op.drop_index(op.f('ix_users_email'), table_name='users')

    op.drop_table('users')
