"""Invoice upload, status, and search endpoints."""

from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from src.api.schemas.invoice import InvoiceRecord, InvoiceStatus, InvoiceUploadResponse
from src.core.db import get_invoices_container, get_raw_invoices_container

router = APIRouter()

@router.post("/upload", response_model=InvoiceUploadResponse)
async def upload_invoice(file: UploadFile) -> InvoiceUploadResponse:
    # Strict Audit Fix: File Type Validation
    allowed_types = ["application/pdf", "image/jpeg", "image/png"]
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Invalid file type. Only PDF, JPEG, and PNG are allowed.")

    # Strict Audit Fix: File Size Validation (Max 10 MB)
    MAX_FILE_SIZE = 10 * 1024 * 1024
    file_content = await file.read()
    if len(file_content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large. Maximum size is 10MB.")
        
    if len(file_content) == 0:
        raise HTTPException(status_code=400, detail="File is empty.")

    invoice_id = uuid4()
    
    # Upload to blob storage
    blob_container = get_raw_invoices_container()
    blob_path = f"raw/{invoice_id}.pdf"
    blob_client = blob_container.get_blob_client(blob_path)
    
    await run_in_threadpool(blob_client.upload_blob, file_content, overwrite=True)
    
    # Initialize record as processing
    record = InvoiceRecord(
        id=invoice_id,
        vendor_id="PENDING", # Will be updated by orchestrator
        status=InvoiceStatus.RECEIVED,
        blob_path=blob_path,
        anomaly_reason="Waiting for orchestrator..."
    )
    
    # Save to Cosmos DB initially
    container = get_invoices_container()
    await run_in_threadpool(container.create_item, body=record.model_dump(mode='json'))
    
    import logging

    import httpx
    logger = logging.getLogger(__name__)
    
    orchestration_id = f"ORCH-{uuid4().hex}"
    
    try:
        from src.core.config import get_settings
        settings = get_settings()
        # Trigger Durable Functions orchestrator with the invoice_id as the orchestration instance ID
        orchestrator_url = f"{settings.orchestrator_base_url}/orchestrators/invoice_orchestrator/{invoice_id}"
        headers = {}
        if settings.orchestrator_host_key:
            headers["x-functions-key"] = settings.orchestrator_host_key

        async with httpx.AsyncClient() as client:
            resp = await client.post(orchestrator_url, json=str(invoice_id), headers=headers)
            if resp.status_code in (200, 202):
                instance_data = resp.json()
                orchestration_id = instance_data.get("id", orchestration_id)
            else:
                logger.warning(f"Orchestrator returned status {resp.status_code}: {resp.text}")
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
    
    def fetch_items():
        return list(container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True
        ))
        
    items = await run_in_threadpool(fetch_items)
    
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
        
    def fetch_list():
        return list(container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True
        ))
        
    items = await run_in_threadpool(fetch_list)
    
    records = [InvoiceRecord.model_validate(i) for i in items]
    records.sort(key=lambda x: x.created_at, reverse=True)
    return records
