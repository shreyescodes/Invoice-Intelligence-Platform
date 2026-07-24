from uuid import UUID

from fastapi import APIRouter, HTTPException

from src.api.schemas.invoice import ApprovalDecision, InvoiceRecord, InvoiceStatus
from src.core.db import get_invoices_container

router = APIRouter()

@router.get("/pending", response_model=list[InvoiceRecord])
async def list_pending_approvals() -> list[InvoiceRecord]:
    container = get_invoices_container()
    
    query = "SELECT * FROM c WHERE c.status = 'pending_approval'"
    
    items = list(container.query_items(
        query=query,
        enable_cross_partition_query=True
    ))
    
    records = [InvoiceRecord.model_validate(i) for i in items]
    records.sort(key=lambda x: x.created_at, reverse=True)
    return records

@router.post("/{invoice_id}/decide")
async def decide(invoice_id: UUID, decision: ApprovalDecision) -> dict[str, str]:
    container = get_invoices_container()
    
    query = "SELECT * FROM c WHERE c.id = @id"
    parameters = [{"name": "@id", "value": str(invoice_id)}]
    
    items = list(container.query_items(
        query=query,
        parameters=parameters,
        enable_cross_partition_query=True
    ))
    
    if not items:
        raise HTTPException(404, "Invoice not found")
        
    item = items[0]
    
    item['status'] = InvoiceStatus.APPROVED.value if decision.approve else InvoiceStatus.REJECTED.value
    if decision.reason:
        item['anomaly_reason'] = f"Decision reason: {decision.reason}"
        
    container.replace_item(item=item, body=item)
    
    import logging

    import httpx
    logger = logging.getLogger(__name__)
    try:
        # Notify the sleeping Azure Functions orchestrator
        event_url = f"http://localhost:7071/api/approvals/{invoice_id}"
        async with httpx.AsyncClient() as client:
            resp = await client.post(event_url, json={"approve": decision.approve, "reason": decision.reason})
            resp.raise_for_status()
    except Exception as e:
        logger.warning(f"Failed to wake up orchestrator (is Azure Functions running?): {e}")
        
    return {"status": "ok"}
