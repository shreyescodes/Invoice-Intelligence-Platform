"""Sync approved invoices from Cosmos DB to Snowflake."""
import logging
import snowflake.connector

from src.core.config import get_settings
from src.core.db import get_invoices_container

logger = logging.getLogger(__name__)

def sync_invoice_to_warehouse(invoice_id: str):
    """ETL script that runs at the end of the orchestration pipeline."""
    settings = get_settings()
    
    if not settings.using_real_snowflake:
        logger.info(f"Skipping Snowflake sync for {invoice_id} because credentials are not set.")
        return
        
    container = get_invoices_container()
    
    query = "SELECT * FROM c WHERE c.id = @id"
    items = list(container.query_items(
        query=query,
        parameters=[{"name": "@id", "value": str(invoice_id)}],
        enable_cross_partition_query=True
    ))
    
    if not items:
        logger.error(f"Cannot sync invoice {invoice_id} because it was not found in Cosmos DB.")
        return
        
    invoice = items[0]
    extracted = invoice.get("extracted", {})
    
    try:
        conn = snowflake.connector.connect(
            user=settings.snowflake_user,
            password=settings.snowflake_password,
            account=settings.snowflake_account,
            warehouse=settings.snowflake_warehouse,
            database=settings.snowflake_database,
            schema="PUBLIC"
        )
        
        cursor = conn.cursor()
        
        # Merge Vendor Dimension
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
        
        # Insert Fact
        cursor.execute(
            """
            INSERT INTO fact_invoice (
                invoice_id, vendor_id, invoice_number, status, subtotal, tax_amount, total_amount, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                str(invoice_id),
                vendor_id,
                extracted.get("invoice_number"),
                invoice.get("status"),
                float(extracted.get("subtotal", 0)),
                float(extracted.get("tax_amount", 0)),
                float(extracted.get("total_amount", 0)),
                invoice.get("created_at")
            )
        )
        
        conn.commit()
        logger.info(f"Successfully synced invoice {invoice_id} to Snowflake.")
        
    except Exception as e:
        logger.error(f"Failed to sync to Snowflake: {e}")
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()
