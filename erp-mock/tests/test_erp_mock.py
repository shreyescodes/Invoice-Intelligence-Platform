from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from erp_mock import main

HEADERS = {"X-API-Key": "dev-erp-key"}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(main, "store", main.ErpStore(json.loads(main.SEED_FILE.read_text(encoding="utf-8"))))
    return TestClient(main.app)


def _invoice(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "SupplierInvoiceIDByInvcgParty": "KIC/26-27/0999",
        "Supplier": "100010",
        "PurchaseOrder": "4500012101",
        "DocumentDate": "2026-10-20",
        "InvoiceGrossAmount": "68440.00",
        "DocumentCurrency": "INR",
        "Items": [{"PurchaseOrderItem": "10", "Quantity": "40", "Amount": "58000.00"}],
    }
    body.update(overrides)
    return body


def test_requires_api_key(client: TestClient) -> None:
    assert client.get("/api/suppliers").status_code == 401


def test_lists_suppliers_and_purchase_orders(client: TestClient) -> None:
    suppliers = client.get("/api/suppliers", headers=HEADERS).json()["value"]
    assert {s["Supplier"] for s in suppliers} >= {"100010", "100017"}
    po = client.get("/api/purchase-orders/4500012101", headers=HEADERS).json()
    assert po["Supplier"] == "100010"
    assert po["Items"][0]["InvoicedQuantity"] == "0"
    assert client.get("/api/purchase-orders/999", headers=HEADERS).status_code == 404


def test_posting_is_idempotent_and_updates_invoiced_quantity(client: TestClient) -> None:
    headers = {**HEADERS, "Idempotency-Key": "invoice-0001"}
    first = client.post("/api/supplier-invoices", json=_invoice(), headers=headers)
    again = client.post("/api/supplier-invoices", json=_invoice(), headers=headers)
    assert first.status_code == 201
    assert again.status_code == 200
    assert first.json()["SupplierInvoice"] == again.json()["SupplierInvoice"]

    po = client.get("/api/purchase-orders/4500012101", headers=HEADERS).json()
    assert po["Items"][0]["InvoicedQuantity"] == "40"


def test_rejects_quantity_above_goods_receipt(client: TestClient) -> None:
    body = _invoice(
        PurchaseOrder="4500012105",
        Supplier="100012",
        Items=[{"PurchaseOrderItem": "10", "Quantity": "6", "Amount": "168000"}],
    )
    response = client.post("/api/supplier-invoices", json=body, headers={**HEADERS, "Idempotency-Key": "k-12345678"})
    assert response.status_code == 409


def test_rejects_duplicate_supplier_invoice_number(client: TestClient) -> None:
    client.post("/api/supplier-invoices", json=_invoice(), headers={**HEADERS, "Idempotency-Key": "first-key"})
    duplicate = _invoice(Items=[])
    response = client.post(
        "/api/supplier-invoices", json=duplicate, headers={**HEADERS, "Idempotency-Key": "second-key"}
    )
    assert response.status_code == 409
