"""The full pipeline against a real ERPNext site: supplier master, PO and goods receipts read from
ERPNext, the invoice posted to it as a Purchase Invoice. Needs the site from deploy/erpnext, prepared by
tests.integration.erpnext_bootstrap (CI job "ERPNext integration"); skipped otherwise."""

from __future__ import annotations

import os
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest

from app.config import Settings
from app.demo.invoice_pdf import Line
from app.runtime import get_document_store
from app.services.anomaly import AnomalyModel
from app.services.erpnext import ErpNextClient
from app.services.extraction import build_extractor
from app.services.pipeline import PipelineServices
from tests.conftest import kaveri_invoice
from tests.test_pipeline import detail, failed_checks, upload

pytestmark = pytest.mark.skipif(not os.environ.get("ERPNEXT_URL"), reason="needs a live ERPNext site (deploy/erpnext)")


@pytest.fixture
def erpnext() -> Iterator[ErpNextClient]:
    client = ErpNextClient(
        os.environ["ERPNEXT_URL"],
        os.environ["ERPNEXT_API_KEY"],
        os.environ["ERPNEXT_API_SECRET"],
        tax_account=os.environ["ERPNEXT_TAX_ACCOUNT"],
        company=os.environ["ERPNEXT_COMPANY"],
        timeout=120,
    )
    yield client
    client.close()


@pytest.fixture
def services(settings: Settings, erpnext: ErpNextClient, anomaly_model: AnomalyModel) -> PipelineServices:
    return PipelineServices(
        settings=settings,
        store=get_document_store(),
        extractor=build_extractor(settings, None),
        erp=erpnext,
        anomaly_model=anomaly_model,
    )


def purchase_invoice(erpnext: ErpNextClient, name: str) -> dict[str, Any]:
    doc = erpnext._doc("test", "Purchase Invoice", name)
    assert doc is not None
    return doc


def test_master_data_and_goods_receipts_come_from_erpnext(erpnext: ErpNextClient) -> None:
    supplier = erpnext.get_supplier(os.environ["ERPNEXT_SUPPLIER"])
    assert supplier is not None
    assert (supplier.tax_id, supplier.city, supplier.payment_terms_days) == ("29AABCK4321P1Z9", "Bengaluru", 45)
    assert supplier.erp_id in {s.erp_id for s in erpnext.list_suppliers()}

    po = erpnext.get_purchase_order(os.environ["ERPNEXT_PO_PARTIAL"])
    assert po is not None and po.supplier_id == supplier.erp_id
    [valve] = po.items
    assert (valve.quantity, valve.received_quantity, valve.open_quantity) == (6, 4, 4)
    assert erpnext.get_purchase_order("PUR-ORD-1900-00001") is None


def test_clean_invoice_is_posted_to_erpnext_once(client, auth, vendors, worker, erpnext: ErpNextClient) -> None:
    po_number = os.environ["ERPNEXT_PO_RECEIVED"]
    invoice_id = upload(client, auth["clerk"], kaveri_invoice(po=po_number))
    assert worker.drain() == 2

    invoice = detail(client, auth["viewer"], invoice_id)
    assert invoice["status"] == "posted", invoice["review_reasons"] or invoice.get("failure_reason")
    assert {c["status"] for c in invoice["checks"]} == {"pass"}

    posted = purchase_invoice(erpnext, invoice["erp_document_number"])
    assert posted["docstatus"] == 1
    assert posted["supplier"] == os.environ["ERPNEXT_SUPPLIER"]
    assert posted["bill_no"] == invoice["invoice_number"]
    assert Decimal(str(posted["grand_total"])) == Decimal(invoice["total_amount"])
    assert {row["purchase_order"] for row in posted["items"]} == {po_number}

    po = erpnext.get_purchase_order(po_number)
    assert po is not None
    assert [item.invoiced_quantity for item in po.items] == [40, 10]

    again = erpnext.post_supplier_invoice(invoice_id, {})
    assert again.document_number == invoice["erp_document_number"]


def test_billing_more_than_was_received_is_stopped(client, auth, vendors, worker) -> None:
    lines = [Line("Solenoid valve 1/2 in 24V DC", Decimal(6), Decimal("3200.00"), "8481")]
    pdf = kaveri_invoice(number="KIC/26-27/0413", po=os.environ["ERPNEXT_PO_PARTIAL"], lines=lines)
    invoice_id = upload(client, auth["clerk"], pdf)
    worker.drain()

    invoice = detail(client, auth["approver"], invoice_id)
    assert invoice["status"] == "needs_review"
    assert "GOODS_RECEIPT" in failed_checks(invoice)
