"""ErpNextClient against a recorded-shape fake of Frappe's REST API. The same client is exercised
against a real ERPNext site in tests/integration/test_erpnext_live.py."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.services.erp import ErpRejectedError
from app.services.erpnext import ErpNextClient

PO = {
    "name": "PUR-ORD-2026-00001",
    "docstatus": 1,
    "supplier": "Kaveri Industrial Components Ltd",
    "company": "Acme Manufacturing India Pvt Ltd",
    "currency": "INR",
    "conversion_rate": 1,
    "transaction_date": "2026-10-01",
    "items": [
        {
            "name": "row-hose",
            "item_code": "HOSE-34",
            "item_name": "Hydraulic hose assembly 3/4 in",
            "qty": 40.0,
            "uom": "Nos",
            "rate": 1450.0,
            "received_qty": 40.0,
            "conversion_factor": 1.0,
        },
        {
            "name": "row-sensor",
            "item_code": "PROX-M18",
            "item_name": "Inductive proximity sensor M18",
            "qty": 10.0,
            "uom": "Nos",
            "rate": 2350.0,
            "received_qty": 6.0,
            "conversion_factor": 1.0,
        },
    ],
}


class FakeErpNext:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.invoices: list[dict[str, Any]] = []
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.headers.get("authorization") != "token key:secret":
            return httpx.Response(401, json={"exc_type": "AuthenticationError"})
        path, params = request.url.path, request.url.params
        filters = json.loads(params.get("filters", "[]"))
        if path == "/api/resource/Supplier":
            return self._data(
                [
                    {
                        "name": "Kaveri Industrial Components Ltd",
                        "supplier_name": "Kaveri Industrial Components Ltd",
                        "tax_id": "29AABCK4321P1Z9",
                        "default_currency": None,
                        "payment_terms": "Net 45",
                        "supplier_primary_address": "Kaveri-Billing",
                    }
                ]
            )
        if path == "/api/resource/Address/Kaveri-Billing":
            return self._data(
                {
                    "address_line1": "No. 42, Peenya Industrial Area",
                    "city": "Bengaluru",
                    "pincode": "560058",
                    "state": "Karnataka",
                }
            )
        if path == "/api/resource/Payment Terms Template/Net 45":
            return self._data({"terms": [{"credit_days": 45}]})
        if path == "/api/resource/Company":
            return self._data([{"name": "Acme Manufacturing India Pvt Ltd"}])
        if path == "/api/resource/Company/Acme Manufacturing India Pvt Ltd":
            return self._data(
                {
                    "company_name": "Acme Manufacturing India Pvt Ltd",
                    "default_currency": "INR",
                    "tax_id": "29AAACA4821K1Z6",
                }
            )
        if path == f"/api/resource/Purchase Order/{PO['name']}":
            return self._data(PO)
        if path.startswith("/api/resource/Purchase Order/"):
            return httpx.Response(404, json={"exc_type": "DoesNotExistError"})
        if path == "/api/resource/Purchase Invoice Item":
            assert params["parent"] == "Purchase Invoice"
            rows = [
                {"po_detail": item["po_detail"], "qty": item["qty"]} for inv in self.invoices for item in inv["items"]
            ]
            return self._data(rows)
        if path == "/api/resource/Purchase Invoice" and request.method == "GET":
            marker = filters[0][2].strip("%")
            return self._data(
                [{"name": i["name"], "posting_date": "2026-10-30"} for i in self.invoices if marker in i["remarks"]]
            )
        if path == "/api/resource/Purchase Invoice" and request.method == "POST":
            body = json.loads(request.content)
            if body["supplier"] != PO["supplier"]:
                messages = [json.dumps({"message": "Could not find <strong>Supplier</strong>: Nobody"})]
                return httpx.Response(
                    417, json={"exc_type": "LinkValidationError", "_server_messages": json.dumps(messages)}
                )
            body["name"] = f"ACC-PINV-2026-{len(self.invoices) + 1:05d}"
            self.invoices.append(body)
            net = sum(Decimal(str(i["qty"])) * Decimal(str(i["rate"])) for i in body["items"])
            tax = sum(Decimal(str(t["tax_amount"])) for t in body["taxes"])
            return self._data({"name": body["name"], "posting_date": "2026-10-30", "grand_total": float(net + tax)})
        if path == "/api/resource/Fiscal Year":
            return self._data([{"name": "2026-2027"}])
        raise AssertionError(f"unexpected {request.method} {request.url}")

    @staticmethod
    def _data(data: object) -> httpx.Response:
        return httpx.Response(200, json={"data": data})


@pytest.fixture
def fake() -> FakeErpNext:
    return FakeErpNext()


@pytest.fixture
def client(fake: FakeErpNext) -> ErpNextClient:
    return ErpNextClient(
        "http://erpnext.test", "key", "secret", tax_account="Input GST - AMI", transport=fake.transport
    )


def payload(supplier: str = PO["supplier"]) -> dict[str, Any]:
    return {
        "SupplierInvoiceIDByInvcgParty": "KIC/26-27/0412",
        "Supplier": supplier,
        "PurchaseOrder": PO["name"],
        "DocumentDate": "2026-10-25",
        "InvoiceGrossAmount": "68440.00",
        "DocumentCurrency": "INR",
        "Items": [{"PurchaseOrderItem": "row-hose", "Quantity": "40", "Amount": "58000.00"}],
    }


def test_suppliers_map_tax_id_address_and_payment_terms(client: ErpNextClient) -> None:
    [supplier] = client.list_suppliers()
    assert supplier.erp_id == "Kaveri Industrial Components Ltd"
    assert supplier.tax_id == "29AABCK4321P1Z9"
    assert (supplier.city, supplier.postal_code, supplier.region) == ("Bengaluru", "560058", "Karnataka")
    assert supplier.currency == "INR"  # falls back to the company currency
    assert supplier.payment_terms_days == 45
    assert client.get_company()["TaxNumber"] == "29AAACA4821K1Z6"


def test_purchase_order_carries_received_and_invoiced_quantities(client: ErpNextClient) -> None:
    po = client.get_purchase_order(PO["name"])
    assert po is not None
    hose, sensor = po.items
    assert (hose.item, hose.net_price, hose.received_quantity, hose.invoiced_quantity) == (
        "row-hose",
        Decimal("1450.0"),
        Decimal("40.0"),
        Decimal(0),
    )
    assert sensor.open_quantity == Decimal("6.0")
    assert client.get_purchase_order("PUR-ORD-2026-99999") is None


def test_posting_submits_a_purchase_invoice_linked_to_the_po(client: ErpNextClient, fake: FakeErpNext) -> None:
    result = client.post_supplier_invoice("6b1c", payload())
    assert (result.document_number, result.fiscal_year) == ("ACC-PINV-2026-00001", "2026-2027")
    [invoice] = fake.invoices
    assert invoice["docstatus"] == 1
    assert invoice["bill_no"] == "KIC/26-27/0412"
    assert invoice["items"] == [
        {
            "item_code": "HOSE-34",
            "qty": 40.0,
            "rate": 1450.0,
            "uom": "Nos",
            "conversion_factor": 1.0,
            "purchase_order": PO["name"],
            "po_detail": "row-hose",
        }
    ]
    assert invoice["taxes"][0] == {
        "charge_type": "Actual",
        "account_head": "Input GST - AMI",
        "description": "Tax as invoiced",
        "tax_amount": 10440.0,
        "category": "Total",
        "add_deduct_tax": "Add",
    }
    assert client.get_purchase_order(PO["name"]).items[0].invoiced_quantity == Decimal("40.0")  # type: ignore[union-attr]


def test_posting_is_idempotent_on_the_key(client: ErpNextClient, fake: FakeErpNext) -> None:
    first = client.post_supplier_invoice("6b1c", payload())
    again = client.post_supplier_invoice("6b1c", payload())
    assert again.document_number == first.document_number
    assert len(fake.invoices) == 1
    assert sum(r.method == "POST" for r in fake.requests) == 1


def test_validation_errors_are_business_rejections_with_frappes_message(client: ErpNextClient) -> None:
    with pytest.raises(ErpRejectedError) as excinfo:
        client.post_supplier_invoice("7d2e", payload(supplier="Nobody"))
    assert excinfo.value.status_code == 417
    assert excinfo.value.detail == "Could not find Supplier: Nobody"


def test_unknown_po_line_is_rejected_before_anything_is_sent(client: ErpNextClient, fake: FakeErpNext) -> None:
    body = payload()
    body["Items"][0]["PurchaseOrderItem"] = "row-missing"
    with pytest.raises(ErpRejectedError, match="no item row-missing"):
        client.post_supplier_invoice("8e3f", body)
    assert not fake.invoices


def test_erpnext_provider_needs_a_secret_and_tax_account() -> None:
    with pytest.raises(ValueError, match="ERP_API_SECRET and ERPNEXT_TAX_ACCOUNT"):
        Settings(erp_provider="erpnext", erp_api_secret=None)
