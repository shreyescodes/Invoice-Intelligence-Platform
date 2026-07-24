"""Invoice upload, status, and search endpoints."""

from datetime import datetime
from uuid import UUID, uuid4
from decimal import Decimal

from fastapi import APIRouter, HTTPException, UploadFile
from azure.cosmos.exceptions import CosmosResourceNotFoundError

from src.api.schemas.invoice import InvoiceRecord, InvoiceUploadResponse, InvoiceStatus, ExtractedInvoice
from src.core.db import get_invoices_container, get_raw_invoices_container

router = APIRouter()

@router.post("/upload", response_model=InvoiceUploadResponse)
async def upload_invoice(file: UploadFile) -> InvoiceUploadResponse:
    invoice_id = uuid4()
    
    # Upload to blob storage
    blob_container = get_raw_invoices_container()
    blob_path = f"raw/{invoice_id}.pdf"
    blob_client = blob_container.get_blob_client(blob_path)
    file_content = await file.read()
    blob_client.upload_blob(file_content, overwrite=True)
    
    # Initialize record as processing
    record = InvoiceRecord(
        id=invoice_id,
        vendor_id="PENDING", # Will be updated by orchestrator
        status=InvoiceStatus.PROCESSING,
        blob_path=blob_path,
        anomaly_reason="Waiting for orchestrator..."
    )
    
    # Save to Cosmos DB initially
    container = get_invoices_container()
    container.create_item(body=record.model_dump(mode='json'))
    
    import httpx
    import logging
    logger = logging.getLogger(__name__)
    
    orchestration_id = f"ORCH-{uuid4().hex}"
    
    try:
        # Trigger Durable Functions orchestrator with the invoice_id as the orchestration instance ID
        orchestrator_url = f"http://localhost:7071/api/orchestrators/invoice_orchestrator/{invoice_id}"
        async with httpx.AsyncClient() as client:
            resp = await client.post(orchestrator_url, json=str(invoice_id))
            if resp.status_code in (200, 202):
                instance_data = resp.json()
                orchestration_id = instance_data.get("id", orchestration_id)
    except Exception as e:
        logger.warning(f"Failed to trigger Azure Functions orchestrator (is it running?): {e}")
    
    return InvoiceUploadResponse(
        invoice_id=invoice_id,
        status=record.status,
        orchestration_id=orchestration_id
    )

@router.get("/{invoice_id}", response_model=InvoiceRecord)
async def get_invoice(invoice_id: UUID) -> InvoiceRecord:
    container = get_invoices_container()
    
    query = "SELECT * FROM c WHERE c.id = @id"
    parameters = [{"name": "@id", "value": str(invoice_id)}]
    
    items = list(container.query_items(
        query=query,
        parameters=parameters,
        enable_cross_partition_query=True
    ))
    
    if not items:
        raise HTTPException(status_code=404, detail="Invoice not found")
        
    return InvoiceRecord.model_validate(items[0])

@router.get("", response_model=list[InvoiceRecord])
async def list_invoices(status: str | None = None, vendor_id: str | None = None) -> list[InvoiceRecord]:
    container = get_invoices_container()
    
    query = "SELECT * FROM c"
    parameters = []
    conditions = []
    
    if status:
        conditions.append("c.status = @status")
        parameters.append({"name": "@status", "value": status})
        
    if vendor_id:
        conditions.append("c.vendor_id = @vendor_id")
        parameters.append({"name": "@vendor_id", "value": vendor_id})
        
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
        
    items = list(container.query_items(
        query=query,
        parameters=parameters,
        enable_cross_partition_query=True
    ))
    
    records = [InvoiceRecord.model_validate(i) for i in items]
    records.sort(key=lambda x: x.created_at, reverse=True)
    return records
