"""Invoice upload, status, and search endpoints.

TODO(phase 2 -> 4, build in this order):
1. POST /invoices/upload — accept a PDF, write it to Blob Storage
   (blob_container_raw_invoices), then start the Durable Functions
   orchestration for it (POST to the orchestrator's HTTP starter
   endpoint) and return the InvoiceUploadResponse below.
2. GET /invoices/{invoice_id} — read the current InvoiceRecord from
   Cosmos DB by id (point read using vendor_id as partition key —
   you'll need to look it up or denormalize it into the URL/query).
3. GET /invoices — list/search with query params (status, vendor,
   date range). Start with a simple Cosmos SQL query; this is also a
   good place to demonstrate pagination with continuation tokens.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, UploadFile

from src.api.schemas.invoice import InvoiceRecord, InvoiceUploadResponse

router = APIRouter()


@router.post("/upload", response_model=InvoiceUploadResponse)
async def upload_invoice(file: UploadFile) -> InvoiceUploadResponse:
    raise HTTPException(501, "Not implemented — see TODO in this file, phase 2")


@router.get("/{invoice_id}", response_model=InvoiceRecord)
async def get_invoice(invoice_id: UUID) -> InvoiceRecord:
    raise HTTPException(501, "Not implemented — see TODO in this file, phase 4")


@router.get("", response_model=list[InvoiceRecord])
async def list_invoices(status: str | None = None, vendor_id: str | None = None) -> list[InvoiceRecord]:
    raise HTTPException(501, "Not implemented — see TODO in this file, phase 4")
