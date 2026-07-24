"""A small stand-in for SAP S/4HANA's OData APIs.

Why this exists: you almost certainly don't have access to a real SAP
system, and SAP Business Accelerator Hub's live sandbox (api.sap.com)
is for exploring the shape of the real APIs, not for wiring into a
CI pipeline you'll run repeatedly. So: look at the real Purchase
Order API and Business Partner API on api.sap.com, note the field
names and structure, and mirror that shape here — that's what makes
this a legitimate stand-in rather than an invented API.

This is deliberately a separate, tiny FastAPI app (not part of the
main platform) so it reads clearly as "the external system", the way
a real SAP instance would be external to your platform.

Field names below are illustrative — replace with what you actually
find in the Business Partner / Purchase Order API docs on
api.sap.com before treating this as done.
"""

from decimal import Decimal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Mock SAP OData Service")

# Seed data. Add more vendors/POs as your test invoices need them.
_BUSINESS_PARTNERS = {
    "VENDOR-1001": {"BusinessPartner": "VENDOR-1001", "BusinessPartnerName": "Acme Supplies Pvt Ltd", "TaxNumber": "29AACME1234F1Z5"},
}

_PURCHASE_ORDERS = {
    "PO-4500001": {
        "PurchaseOrder": "PO-4500001",
        "Supplier": "VENDOR-1001",
        "items": [
            {"Item": "10", "Material": "Office Chairs", "OrderQuantity": Decimal("20"), "NetPriceAmount": Decimal("3500.00")},
        ],
    },
}


class PostingRequest(BaseModel):
    invoice_id: str
    po_number: str
    total_amount: Decimal


@app.get("/BusinessPartners('{partner_id}')")
def get_business_partner(partner_id: str) -> dict:
    partner = _BUSINESS_PARTNERS.get(partner_id)
    if not partner:
        raise HTTPException(404, f"BusinessPartner {partner_id} not found")
    return partner


@app.get("/PurchaseOrders('{po_number}')")
def get_purchase_order(po_number: str) -> dict:
    po = _PURCHASE_ORDERS.get(po_number)
    if not po:
        raise HTTPException(404, f"PurchaseOrder {po_number} not found")
    return po


# Idempotency: same invoice_id posted twice returns the same result
# instead of creating a duplicate. Mirrors what post_to_sap.py's
# retry-safety needs from a real system.
_POSTED: dict[str, dict] = {}


@app.post("/InvoicePostings")
def post_invoice(req: PostingRequest) -> dict:
    if req.invoice_id in _POSTED:
        return _POSTED[req.invoice_id]
    result = {"invoice_id": req.invoice_id, "posting_document": f"51{len(_POSTED) + 1000000}", "status": "posted"}
    _POSTED[req.invoice_id] = result
    return result


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
