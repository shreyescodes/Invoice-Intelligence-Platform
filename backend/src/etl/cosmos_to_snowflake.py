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

import logging
from typing import Any
import snowflake.connector

from src.core.config import get_settings
from src.core.db import get_invoices_container

logger = logging.getLogger(__name__)

def run_incremental_load(since_watermark: str) -> dict[str, Any]:
    """Runs a batch ETL sync of invoices updated since the watermark."""
    settings = get_settings()
    
    if not settings.using_real_snowflake:
        logger.info(f"Skipping Snowflake batch ETL sync since using_real_snowflake is false.")
        return {"status": "skipped", "reason": "Credentials not set"}

    container = get_invoices_container()
    
    query = "SELECT * FROM c WHERE c.updated_at >= @watermark"
    items = list(container.query_items(
        query=query,
        parameters=[{"name": "@watermark", "value": since_watermark}],
        enable_cross_partition_query=True
    ))
    
    if not items:
        logger.info("No new or updated invoices found in Cosmos DB since watermark.")
        return {"status": "success", "processed_count": 0}
        
    try:
        with snowflake.connector.connect(
            user=settings.snowflake_user,
            password=settings.snowflake_password,
            account=settings.snowflake_account,
            warehouse=settings.snowflake_warehouse,
            database=settings.snowflake_database,
            schema="PUBLIC"
        ) as conn:
            with conn.cursor() as cursor:
                for invoice in items:
                    extracted = invoice.get("extracted", {})
                    vendor_id = invoice.get("vendor_id")
                    vendor_name = extracted.get("vendor_name", "Unknown")
                    
                    cursor.execute(
                        """
                        MERGE INTO dim_vendor target
                        USING (SELECT %s AS vendor_id, %s AS vendor_name) source
                        ON target.vendor_id = source.vendor_id
                        WHEN MATCHED THEN UPDATE SET vendor_name = source.vendor_name
                        WHEN NOT MATCHED THEN INSERT (vendor_id, vendor_name) VALUES (source.vendor_id, source.vendor_name)
                        """,
                        (vendor_id, vendor_name)
                    )
                    
                    cursor.execute(
                        """
                        MERGE INTO fact_invoice target
                        USING (
                            SELECT 
                                %s AS invoice_id, 
                                (SELECT vendor_key FROM dim_vendor WHERE vendor_id = %s LIMIT 1) AS vendor_key, 
                                %s AS invoice_number, 
                                %s AS status, 
                                %s AS subtotal, 
                                %s AS tax_amount, 
                                %s AS total_amount, 
                                %s AS anomaly_score,
                                %s AS created_at
                        ) source
                        ON target.invoice_id = source.invoice_id
                        WHEN MATCHED THEN UPDATE SET 
                            vendor_key = source.vendor_key,
                            invoice_number = source.invoice_number,
                            status = source.status, 
                            subtotal = source.subtotal, 
                            tax_amount = source.tax_amount, 
                            total_amount = source.total_amount,
                            anomaly_score = source.anomaly_score
                        WHEN NOT MATCHED THEN INSERT (invoice_id, vendor_key, invoice_number, status, subtotal, tax_amount, total_amount, anomaly_score, created_at) 
                        VALUES (source.invoice_id, source.vendor_key, source.invoice_number, source.status, source.subtotal, source.tax_amount, source.total_amount, source.anomaly_score, source.created_at)
                        """,
                        (
                            str(invoice.get("id")),
                            vendor_id,
                            extracted.get("invoice_number"),
                            invoice.get("status"),
                            float(extracted.get("subtotal", 0)),
                            float(extracted.get("tax_amount", 0)),
                            float(extracted.get("total_amount", 0)),
                            float(invoice.get("anomaly_score") or 0.0),
                            invoice.get("created_at")
                        )
                    )
            conn.commit()
            
        logger.info(f"Successfully processed {len(items)} invoices to Snowflake.")
        return {"status": "success", "processed_count": len(items)}
        
    except Exception as e:
        logger.error(f"Failed to batch sync to Snowflake: {e}")
        return {"status": "error", "error": str(e)}


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
    invoice_number VARCHAR,
    subtotal DECIMAL(18,2),
    tax_amount DECIMAL(18,2),
    total_amount DECIMAL(18,2),
    anomaly_score FLOAT,
    status VARCHAR,
    created_at TIMESTAMP,
    loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""
