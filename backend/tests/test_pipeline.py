"""End-to-end pipeline: upload -> worker -> extraction -> validation -> scoring -> approval -> ERP."""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.demo.invoice_pdf import Line, Party
from app.models import Job, JobStatus
from app.worker import Worker
from tests.conftest import kaveri_invoice
from tests.fakes import FakeErp


def upload(client: TestClient, headers: dict[str, str], pdf: bytes, name: str = "invoice.pdf") -> str:
    response = client.post("/api/v1/invoices", files={"file": (name, pdf, "application/pdf")}, headers=headers)
    assert response.status_code == 202, response.text
    return str(response.json()["id"])


def detail(client: TestClient, headers: dict[str, str], invoice_id: str) -> dict:  # type: ignore[type-arg]
    response = client.get(f"/api/v1/invoices/{invoice_id}", headers=headers)
    assert response.status_code == 200
    return dict(response.json())


def failed_checks(invoice: dict) -> set[str]:  # type: ignore[type-arg]
    return {c["code"] for c in invoice["checks"] if c["status"] == "fail"}


def test_clean_invoice_is_auto_approved_and_posted(client, auth, vendors, worker: Worker, erp: FakeErp) -> None:
    invoice_id = upload(client, auth["clerk"], kaveri_invoice())
    assert worker.drain() == 2  # process, then post

    invoice = detail(client, auth["viewer"], invoice_id)
    assert invoice["status"] == "posted"
    assert invoice["auto_approved"] is True
    assert invoice["vendor"]["erp_id"] == "100010"
    assert invoice["total_amount"] == "96170.00"
    assert invoice["erp_document_number"] == erp.posted_invoices()[0]["SupplierInvoice"]
    assert [li["po_item"] for li in invoice["line_items"]] == ["10", "20"]
    assert {c["status"] for c in invoice["checks"]} == {"pass"}
    assert [e["action"] for e in invoice["events"]] == [
        "uploaded",
        "processing_started",
        "auto_approved",
        "posted_to_erp",
    ]
    assert erp.store.purchase_orders["4500012101"]["Items"][0]["InvoicedQuantity"] == "40"


def test_price_variance_goes_to_review_and_can_be_approved(client, auth, vendors, worker, erp) -> None:
    lines = [Line("Hydraulic hose assembly 3/4 in", Decimal(40), Decimal("1595.00"), "4009")]
    invoice_id = upload(client, auth["clerk"], kaveri_invoice(lines=lines))
    worker.drain()

    invoice = detail(client, auth["approver"], invoice_id)
    assert invoice["status"] == "needs_review"
    assert failed_checks(invoice) == {"PRICE_MATCH"}
    assert any("billed at" in reason for reason in invoice["review_reasons"])
    assert invoice["allowed_actions"] == ["approve", "reject"]

    response = client.post(
        f"/api/v1/invoices/{invoice_id}/approve", json={"comment": "Rate increase agreed"}, headers=auth["approver"]
    )
    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    worker.drain()
    invoice = detail(client, auth["approver"], invoice_id)
    assert invoice["status"] == "posted"
    assert invoice["decided_by"]["role"] == "approver"
    assert invoice["decision_comment"] == "Rate increase agreed"


def test_short_goods_receipt(client, auth, vendors, worker, erp) -> None:
    erp.store.purchase_orders["4500012101"]["Items"][0]["ReceivedQuantity"] = "30"
    invoice_id = upload(client, auth["clerk"], kaveri_invoice())
    worker.drain()
    invoice = detail(client, auth["clerk"], invoice_id)
    assert invoice["status"] == "needs_review"
    assert failed_checks(invoice) == {"GOODS_RECEIPT"}


def test_duplicate_invoice_number_is_caught(client, auth, vendors, worker, erp) -> None:
    upload(client, auth["clerk"], kaveri_invoice())
    worker.drain()
    erp.store.purchase_orders["4500012101"]["Items"][0]["InvoicedQuantity"] = "0"
    erp.store.purchase_orders["4500012101"]["Items"][1]["InvoicedQuantity"] = "0"
    second = upload(client, auth["clerk"], kaveri_invoice(number="KIC-26-27-0412", style="modern"))
    worker.drain()
    assert "DUPLICATE" in failed_checks(detail(client, auth["clerk"], second))


def test_unknown_vendor_and_missing_po(client, auth, vendors, worker) -> None:
    stranger = Party("Nimbus Print & Signage", ["Lower Parel", "Mumbai 400013"], "27AAHFN5512C1Z0")
    invoice_id = upload(client, auth["clerk"], kaveri_invoice(vendor=stranger, po=None, number="NPS/2026/118"))
    worker.drain()
    invoice = detail(client, auth["approver"], invoice_id)
    assert invoice["status"] == "needs_review"
    assert failed_checks(invoice) >= {"VENDOR_MATCH", "PO_MATCH"}
    approve = client.post(f"/api/v1/invoices/{invoice_id}/approve", json={}, headers=auth["approver"])
    assert approve.status_code == 409  # cannot post without a vendor master record


def test_erp_outage_is_retried_then_parks_invoice(client, auth, vendors, worker, erp, db: Session) -> None:
    invoice_id = upload(client, auth["clerk"], kaveri_invoice())
    erp.down = True
    for _ in range(worker.settings.worker_max_attempts):
        assert worker.run_once()
    assert not worker.run_once()

    invoice = detail(client, auth["admin"], invoice_id)
    assert invoice["status"] == "failed"
    assert invoice["failure_stage"] == "processing"
    assert "ERP unreachable" in invoice["last_error"]
    assert [e["action"] for e in invoice["events"]].count("retry_scheduled") == 4
    assert invoice["allowed_actions"] == ["retry"]

    erp.down = False
    response = client.post(f"/api/v1/invoices/{invoice_id}/retry", headers=auth["admin"])
    assert response.status_code == 200
    worker.drain()
    assert detail(client, auth["admin"], invoice_id)["status"] == "posted"


def test_transient_erp_errors_are_absorbed_by_client_retries(client, auth, vendors, worker, erp) -> None:
    invoice_id = upload(client, auth["clerk"], kaveri_invoice())
    erp.unavailable = 2  # two 503s, the client's third attempt succeeds
    worker.drain()
    assert detail(client, auth["clerk"], invoice_id)["status"] == "posted"


def test_erp_rejection_at_posting_fails_without_retrying(client, auth, vendors, worker, erp, db: Session) -> None:
    lines = [Line("Hydraulic hose assembly 3/4 in", Decimal(40), Decimal("1595.00"), "4009")]
    invoice_id = upload(client, auth["clerk"], kaveri_invoice(lines=lines))
    worker.drain()
    # Someone else invoices the goods first, so the ERP refuses our posting.
    erp.store.purchase_orders["4500012101"]["Items"][0]["InvoicedQuantity"] = "40"
    client.post(f"/api/v1/invoices/{invoice_id}/approve", json={}, headers=auth["approver"])
    worker.drain()

    invoice = detail(client, auth["admin"], invoice_id)
    assert invoice["status"] == "failed"
    assert invoice["failure_stage"] == "posting"
    jobs = db.scalars(select(Job).where(Job.invoice_id == uuid.UUID(invoice_id))).all()
    assert all(j.status in (JobStatus.SUCCEEDED, JobStatus.DEAD) for j in jobs)
    assert all(j.attempts == 1 for j in jobs if j.status is JobStatus.DEAD)


def test_unreadable_document_fails_permanently(client, auth, vendors, worker) -> None:
    invoice_id = upload(client, auth["clerk"], b"%PDF-1.4 garbage that is not a pdf")
    worker.drain()
    invoice = detail(client, auth["admin"], invoice_id)
    assert invoice["status"] == "failed"
    assert "Unreadable PDF" in invoice["last_error"]


def test_amount_anomaly_is_flagged_against_vendor_history(client, auth, vendors, worker, erp) -> None:
    po = erp.store.purchase_orders["4500012109"]
    for item in po["Items"]:
        item["ReceivedQuantity"] = "100000"
    normal = [
        Line("Deep groove ball bearing 6205-2RS", Decimal(q), Decimal("185.00"), "8482")
        for q in (180, 200, 220, 190, 210, 205)
    ]
    for i, line in enumerate(normal):
        upload(
            client, auth["clerk"], kaveri_invoice(number=f"KIC/H/{i}", po="4500012109", lines=[line]), name=f"h{i}.pdf"
        )
        worker.drain()
    spike = [Line("Deep groove ball bearing 6205-2RS", Decimal(2400), Decimal("185.00"), "8482")]
    invoice_id = upload(client, auth["clerk"], kaveri_invoice(number="KIC/H/99", po="4500012109", lines=spike))
    worker.drain()

    invoice = detail(client, auth["clerk"], invoice_id)
    assert invoice["anomaly_score"] > 0.5
    assert invoice["status"] == "needs_review"
    assert any("this vendor's median" in r for r in invoice["anomaly_reasons"])
