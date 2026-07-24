"""Human-in-the-loop approval endpoint.

This is the piece that makes Durable Functions worth using here: the
orchestrator calls `context.wait_for_external_event("ApprovalDecision")`
and genuinely pauses (no compute billed while waiting) until this
endpoint raises that event. A queue-based approach would need you to
hand-roll the wait/resume state machine yourself.

TODO(phase 3):
1. GET /approvals/pending — query Cosmos DB for status=pending_approval.
2. POST /approvals/{invoice_id}/decide — call the Durable Functions
   management API's "raise event" endpoint
   (POST {orchestration_url}/raiseEvent/ApprovalDecision) with the
   ApprovalDecision body, using the orchestration_id stored on the
   InvoiceRecord. The azure-durable-functions client SDK wraps this,
   or call the REST API directly with httpx.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException

from src.api.schemas.invoice import ApprovalDecision, InvoiceRecord

router = APIRouter()


@router.get("/pending", response_model=list[InvoiceRecord])
async def list_pending_approvals() -> list[InvoiceRecord]:
    raise HTTPException(501, "Not implemented — see TODO in this file, phase 3")


@router.post("/{invoice_id}/decide")
async def decide(invoice_id: UUID, decision: ApprovalDecision) -> dict[str, str]:
    raise HTTPException(501, "Not implemented — see TODO in this file, phase 3")
