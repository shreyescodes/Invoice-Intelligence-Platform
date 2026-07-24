"""Incremental ETL: Cosmos DB -> analytics warehouse star schema.

TODO(phase 4):
1. Read Cosmos DB's change feed for the invoices container
   (azure-cosmos's ContainerProxy.query_items_change_feed, or the
   simpler approach: track a `updated_at` watermark and query
   `WHERE c.updated_at > @last_run` — start with this, it's easier to
   reason about than the change feed API, then swap in the real
   change feed once the simple version works).
2. Transform each InvoiceRecord into the star schema:
   - dim_vendor (vendor_id, vendor_name, tax_id)
   - dim_date (date_key, year, month, day, quarter)
   - fact_invoice (invoice_id, vendor_key, date_key, subtotal,
     tax_amount, total_amount, anomaly_score, status, approval_latency)
3. Load: use snowflake-connector-python's write_pandas for the real
   target, or plain psycopg2/SQLAlchemy for the local Postgres
   stand-in — same SQL schema, different connection. This is exactly
   the ELT pattern: land raw, transform in SQL views, not a bespoke
   Python transform per warehouse.
4. Run this on a timer (a timer-triggered Azure Function, e.g. every
   15 minutes) rather than per-invoice — batch loads are how this is
   actually done in production, not row-by-row inserts.

Snowflake trial cost note: your X-Small warehouse bills per-second
with a 60-second minimum whenever it's active. Set
AUTO_SUSPEND = 60 on the warehouse (SQL: ALTER WAREHOUSE ... SET
AUTO_SUSPEND = 60) so idle time between ETL runs doesn't burn trial
credits — this one setting is the difference between a $400 credit
lasting your whole build and draining in a weekend.
"""

from typing import Any


def run_incremental_load(since_watermark: str) -> dict[str, Any]:
    raise NotImplementedError("Build this in phase 4 — see module docstring")


DIM_VENDOR_DDL = """
CREATE TABLE IF NOT EXISTS dim_vendor (
    vendor_key INTEGER AUTOINCREMENT PRIMARY KEY,
    vendor_id VARCHAR NOT NULL UNIQUE,
    vendor_name VARCHAR,
    tax_id VARCHAR
);
"""

FACT_INVOICE_DDL = """
CREATE TABLE IF NOT EXISTS fact_invoice (
    invoice_id VARCHAR PRIMARY KEY,
    vendor_key INTEGER REFERENCES dim_vendor(vendor_key),
    invoice_date DATE,
    subtotal DECIMAL(18,2),
    tax_amount DECIMAL(18,2),
    total_amount DECIMAL(18,2),
    anomaly_score FLOAT,
    status VARCHAR,
    loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""
