from uuid import UUID

from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from src.api.schemas.invoice import ApprovalDecision, InvoiceRecord, InvoiceStatus
from src.core.db import get_invoices_container

router = APIRouter()

@router.get("/pending", response_model=list[InvoiceRecord])
async def list_pending_approvals() -> list[InvoiceRecord]:
    container = get_invoices_container()
    
    query = "SELECT * FROM c WHERE c.status = 'pending_approval'"
    
    def fetch_pending():
        return list(container.query_items(
            query=query,
            enable_cross_partition_query=True
        ))
        
    items = await run_in_threadpool(fetch_pending)
    
    records = [InvoiceRecord.model_validate(i) for i in items]
    records.sort(key=lambda x: x.created_at, reverse=True)
    return records

@router.post("/{invoice_id}/decide")
async def decide(invoice_id: UUID, decision: ApprovalDecision) -> dict[str, str]:
    container = get_invoices_container()
    
    query = "SELECT * FROM c WHERE c.id = @id"
    parameters = [{"name": "@id", "value": str(invoice_id)}]
    
    def fetch_decision_item():
        return list(container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True
        ))
        
    items = await run_in_threadpool(fetch_decision_item)
    
    if not items:
        raise HTTPException(404, "Invoice not found")
        
    item = items[0]
    
    item['status'] = InvoiceStatus.APPROVED.value if decision.approve else InvoiceStatus.REJECTED.value
    if decision.reason:
        item['anomaly_reason'] = f"Decision reason: {decision.reason}"
        
    await run_in_threadpool(container.replace_item, item=item, body=item)
    
    import logging

    import httpx
    logger = logging.getLogger(__name__)
    try:
        from src.core.config import get_settings
        settings = get_settings()
        # Notify the sleeping Azure Functions orchestrator
        event_url = f"{settings.orchestrator_base_url}/approvals/{invoice_id}"
        headers = {}
        if settings.orchestrator_host_key:
            headers["x-functions-key"] = settings.orchestrator_host_key

        async with httpx.AsyncClient() as client:
            resp = await client.post(event_url, json={"approve": decision.approve, "reason": decision.reason}, headers=headers)
            resp.raise_for_status()
    except Exception as e:
        logger.warning(f"Failed to wake up orchestrator (is Azure Functions running?): {e}")
        
    return {"status": "ok"}
