"""Stand-in for the SAP S/4HANA APIs the platform integrates with.

Field names follow the public API_BUSINESS_PARTNER, API_PURCHASEORDER_PROCESS_SRV and
API_SUPPLIERINVOICE_PROCESS_SRV services, flattened to plain JSON. State is in memory and resets on
restart. Set ERP_FAILURE_RATE (0-1) to inject 503s and exercise the platform's retry handling.
"""

from __future__ import annotations

import copy
import json
import os
import random
import threading
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

SEED_FILE = Path(os.environ.get("ERP_SEED_FILE", Path(__file__).with_name("seed.json")))
API_KEY = os.environ.get("ERP_API_KEY", "dev-erp-key")
FAILURE_RATE = float(os.environ.get("ERP_FAILURE_RATE", "0"))


class InvoiceItem(BaseModel):
    PurchaseOrderItem: str
    Quantity: Decimal = Field(gt=0)
    Amount: Decimal = Field(ge=0)


class SupplierInvoiceIn(BaseModel):
    SupplierInvoiceIDByInvcgParty: str = Field(min_length=1, max_length=40)
    Supplier: str
    PurchaseOrder: str | None = None
    DocumentDate: str
    InvoiceGrossAmount: Decimal = Field(ge=0)
    DocumentCurrency: str = Field(min_length=3, max_length=3)
    Items: list[InvoiceItem] = []


class ErpStore:
    def __init__(self, seed: dict[str, Any]) -> None:
        self._lock = threading.Lock()
        self.company = seed["company"]
        self.suppliers = {s["Supplier"]: s for s in seed["suppliers"]}
        self.purchase_orders: dict[str, dict[str, Any]] = {}
        for po in seed["purchase_orders"]:
            po = copy.deepcopy(po)
            for item in po["Items"]:
                item.setdefault("InvoicedQuantity", "0")
            self.purchase_orders[po["PurchaseOrder"]] = po
        self.invoices: dict[str, dict[str, Any]] = {}
        self._idempotency: dict[str, dict[str, Any]] = {}
        self._next_document = 5105600001

    def post_invoice(self, key: str, payload: SupplierInvoiceIn) -> tuple[dict[str, Any], bool]:
        with self._lock:
            if key in self._idempotency:
                return self._idempotency[key], False
            if payload.Supplier not in self.suppliers:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Supplier {payload.Supplier} unknown")
            for existing in self.invoices.values():
                if (
                    existing["Supplier"] == payload.Supplier
                    and existing["SupplierInvoiceIDByInvcgParty"] == payload.SupplierInvoiceIDByInvcgParty
                ):
                    raise HTTPException(status.HTTP_409_CONFLICT, "Supplier invoice already posted")

            po = self.purchase_orders.get(payload.PurchaseOrder or "")
            if payload.PurchaseOrder and po is None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Purchase order not found")
            if po is not None:
                items = {i["PurchaseOrderItem"]: i for i in po["Items"]}
                for line in payload.Items:
                    item = items.get(line.PurchaseOrderItem)
                    if item is None:
                        raise HTTPException(
                            status.HTTP_422_UNPROCESSABLE_ENTITY, f"PO item {line.PurchaseOrderItem} not found"
                        )
                    open_qty = Decimal(item["ReceivedQuantity"]) - Decimal(item["InvoicedQuantity"])
                    if line.Quantity > open_qty:
                        raise HTTPException(
                            status.HTTP_409_CONFLICT,
                            f"Item {line.PurchaseOrderItem}: invoiced quantity exceeds goods received",
                        )
                for line in payload.Items:
                    item = items[line.PurchaseOrderItem]
                    item["InvoicedQuantity"] = str(Decimal(item["InvoicedQuantity"]) + line.Quantity)

            document = str(self._next_document)
            self._next_document += 1
            record = {
                "SupplierInvoice": document,
                "FiscalYear": str(datetime.now(UTC).year),
                "CompanyCode": self.company["CompanyCode"],
                "Status": "posted",
                "PostingDate": datetime.now(UTC).date().isoformat(),
                **payload.model_dump(mode="json"),
            }
            self.invoices[document] = record
            self._idempotency[key] = record
            return record, True


store = ErpStore(json.loads(SEED_FILE.read_text(encoding="utf-8")))
app = FastAPI(title="Mock SAP S/4HANA", version="1.0.0")


@app.middleware("http")
async def inject_failures(request: Request, call_next: Any) -> Any:
    if FAILURE_RATE and request.url.path.startswith("/api") and random.random() < FAILURE_RATE:  # noqa: S311
        return JSONResponse({"detail": "Service temporarily unavailable"}, status_code=503)
    return await call_next(request)


def require_api_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    if x_api_key != API_KEY:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing X-API-Key")


Authenticated = Depends(require_api_key)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/company", dependencies=[Authenticated])
def company() -> dict[str, Any]:
    return store.company


@app.get("/api/suppliers", dependencies=[Authenticated])
def list_suppliers() -> dict[str, Any]:
    return {"value": list(store.suppliers.values())}


@app.get("/api/suppliers/{supplier_id}", dependencies=[Authenticated])
def get_supplier(supplier_id: str) -> dict[str, Any]:
    supplier = store.suppliers.get(supplier_id)
    if supplier is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Supplier {supplier_id} not found")
    return supplier


@app.get("/api/purchase-orders", dependencies=[Authenticated])
def list_purchase_orders(supplier: str | None = None) -> dict[str, Any]:
    orders = [po for po in store.purchase_orders.values() if supplier is None or po["Supplier"] == supplier]
    return {"value": orders}


@app.get("/api/purchase-orders/{po_number}", dependencies=[Authenticated])
def get_purchase_order(po_number: str) -> dict[str, Any]:
    po = store.purchase_orders.get(po_number)
    if po is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Purchase order {po_number} not found")
    return po


@app.post("/api/supplier-invoices", dependencies=[Authenticated])
def post_supplier_invoice(
    payload: SupplierInvoiceIn,
    idempotency_key: Annotated[str, Header(min_length=8, max_length=100)],
) -> JSONResponse:
    record, created = store.post_invoice(idempotency_key, payload)
    return JSONResponse(record, status_code=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
