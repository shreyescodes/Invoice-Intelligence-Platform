from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.demo.invoice_pdf import Line
from app.models import User
from tests.conftest import PASSWORD, kaveri_invoice, login
from tests.test_pipeline import detail, upload

# --- Operational endpoints ------------------------------------------------------------------------


def test_health_and_metrics(client: TestClient) -> None:
    assert client.get("/health/live").json() == {"status": "ok"}
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json()["checks"] == {"database": "ok", "storage": "ok"}
    assert "iip_http_requests_total" in client.get("/metrics").text


def test_request_id_is_echoed(client: TestClient) -> None:
    response = client.get("/health/live", headers={"X-Request-ID": "abc123"})
    assert response.headers["X-Request-ID"] == "abc123"


def test_meta_is_public_and_hides_demo_accounts(client: TestClient) -> None:
    body = client.get("/api/v1/meta").json()
    assert body["demo_mode"] is False
    assert body["demo_accounts"] == []
    assert body["auto_approve_limit"] == "250000.00"


# --- Authentication ---------------------------------------------------------------------------------


def test_login_and_me(client: TestClient, users: dict[str, User]) -> None:
    headers = login(client, "approver@example.test")
    me = client.get("/api/v1/auth/me", headers=headers).json()
    assert me["role"] == "approver"
    assert "password_hash" not in me


def test_wrong_password_and_lockout(client: TestClient, users: dict[str, User]) -> None:
    for _ in range(5):
        response = client.post("/api/v1/auth/token", data={"username": "clerk@example.test", "password": "nope"})
        assert response.status_code == 401
        assert response.headers["content-type"] == "application/problem+json"
    locked = client.post("/api/v1/auth/token", data={"username": "clerk@example.test", "password": PASSWORD})
    assert locked.status_code == 429


def test_protected_routes_require_a_valid_token(client: TestClient, users: dict[str, User]) -> None:
    assert client.get("/api/v1/invoices").status_code == 401
    bad = client.get("/api/v1/invoices", headers={"Authorization": "Bearer not-a-jwt"})
    assert bad.status_code == 401
    assert bad.json()["code"] == "unauthenticated"


def test_inactive_users_lose_access(client: TestClient, users: dict[str, User], db) -> None:
    headers = login(client, "clerk@example.test")
    users["clerk"].is_active = False
    db.commit()
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


# --- Uploads ------------------------------------------------------------------------------------------


def test_viewer_cannot_upload(client: TestClient, auth) -> None:
    response = client.post(
        "/api/v1/invoices", files={"file": ("a.pdf", kaveri_invoice(), "application/pdf")}, headers=auth["viewer"]
    )
    assert response.status_code == 403


@pytest.mark.parametrize(
    ("content", "status", "code"),
    [
        (b"MZ\x90\x00 executable", 415, "unsupported_media_type"),
        (b"", 415, "unsupported_media_type"),
    ],
)
def test_upload_rejects_bad_files(client: TestClient, auth, content: bytes, status: int, code: str) -> None:
    # The declared content type is a lie; the server sniffs the bytes.
    response = client.post(
        "/api/v1/invoices", files={"file": ("x.pdf", content, "application/pdf")}, headers=auth["clerk"]
    )
    assert response.status_code == status
    assert response.json()["code"] == code


def test_upload_size_limit(client: TestClient, auth, settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "max_upload_bytes", 1000)
    response = client.post(
        "/api/v1/invoices", files={"file": ("big.pdf", kaveri_invoice(), "application/pdf")}, headers=auth["clerk"]
    )
    assert response.status_code == 413


def test_same_document_cannot_be_uploaded_twice(client: TestClient, auth) -> None:
    pdf = kaveri_invoice()
    first = upload(client, auth["clerk"], pdf)
    again = client.post(
        "/api/v1/invoices", files={"file": ("copy.pdf", pdf, "application/pdf")}, headers=auth["approver"]
    )
    assert again.status_code == 409
    assert again.json()["extra"]["invoice_id"] == first


def test_document_download(client: TestClient, auth) -> None:
    pdf = kaveri_invoice()
    invoice_id = upload(client, auth["clerk"], pdf, name="../../etc/Kaveri Oct.pdf")
    response = client.get(f"/api/v1/invoices/{invoice_id}/document", headers=auth["viewer"])
    assert response.status_code == 200
    assert response.content == pdf
    assert response.headers["content-type"] == "application/pdf"
    assert "Kaveri%20Oct.pdf" in response.headers["content-disposition"]


def test_preview_renders_and_caches_pdf_pages(client: TestClient, auth) -> None:
    invoice_id = upload(client, auth["clerk"], kaveri_invoice())
    first = client.get(f"/api/v1/invoices/{invoice_id}/preview", headers=auth["viewer"])
    assert first.status_code == 200
    assert first.headers["content-type"] == "image/png"
    assert first.headers["x-page-count"] == "1"
    assert first.content[:8] == bytes.fromhex("89504e470d0a1a0a")  # PNG signature
    cached = client.get(f"/api/v1/invoices/{invoice_id}/preview", headers=auth["viewer"])
    assert cached.content == first.content
    assert client.get(f"/api/v1/invoices/{invoice_id}/preview?page=2", headers=auth["viewer"]).status_code == 404


# --- Listing --------------------------------------------------------------------------------------------


def test_list_filter_search_and_paginate(client: TestClient, auth, vendors, worker) -> None:
    upload(client, auth["clerk"], kaveri_invoice(number="KIC/A/1"), "a.pdf")
    upload(client, auth["clerk"], kaveri_invoice(number="KIC/A/2", po=None), "b.pdf")
    upload(client, auth["clerk"], kaveri_invoice(number="KIC/A/3", po="999"), "c.pdf")
    worker.drain()

    page = client.get("/api/v1/invoices?page_size=2&sort=-created_at", headers=auth["viewer"]).json()
    assert page["total"] == 3 and len(page["items"]) == 2

    review = client.get("/api/v1/invoices?status=needs_review", headers=auth["viewer"]).json()
    assert {i["invoice_number"] for i in review["items"]} == {"KIC/A/2", "KIC/A/3"}

    found = client.get("/api/v1/invoices?q=a/1", headers=auth["viewer"]).json()
    assert [i["invoice_number"] for i in found["items"]] == ["KIC/A/1"]

    by_vendor = client.get("/api/v1/invoices?q=kaveri", headers=auth["viewer"]).json()
    assert by_vendor["total"] == 3

    assert client.get("/api/v1/invoices?sort=password", headers=auth["viewer"]).status_code == 400
    assert client.get("/api/v1/invoices?page_size=500", headers=auth["viewer"]).status_code == 422


def test_vendors_endpoint_reports_spend(client: TestClient, auth, vendors, worker) -> None:
    upload(client, auth["clerk"], kaveri_invoice())
    worker.drain()
    rows = client.get("/api/v1/vendors", headers=auth["viewer"]).json()
    kaveri = next(v for v in rows if v["erp_id"] == "100010")
    assert kaveri["invoice_count"] == 1
    assert kaveri["total_spend"] == "96170.00"
    assert rows[0]["erp_id"] == "100010"  # sorted by spend


# --- Approvals ---------------------------------------------------------------------------------------


@pytest.fixture
def review_invoice(client: TestClient, auth, vendors, worker) -> str:
    lines = [Line("Hydraulic hose assembly 3/4 in", Decimal(40), Decimal("1595.00"), "4009")]
    invoice_id = upload(client, auth["approver2"], kaveri_invoice(lines=lines))
    worker.drain()
    return invoice_id


def test_clerks_cannot_approve(client: TestClient, auth, review_invoice: str) -> None:
    response = client.post(f"/api/v1/invoices/{review_invoice}/approve", json={}, headers=auth["clerk"])
    assert response.status_code == 403
    assert detail(client, auth["clerk"], review_invoice)["allowed_actions"] == []


def test_segregation_of_duties(client: TestClient, auth, review_invoice: str) -> None:
    # approver2 uploaded the invoice, so approver2 may not approve it
    response = client.post(f"/api/v1/invoices/{review_invoice}/approve", json={}, headers=auth["approver2"])
    assert response.status_code == 403
    assert "Segregation of duties" in response.json()["detail"]


def test_approver_limit(client: TestClient, auth, settings, review_invoice: str, monkeypatch) -> None:
    monkeypatch.setattr(settings, "approver_limit", Decimal("10000"))
    response = client.post(f"/api/v1/invoices/{review_invoice}/approve", json={}, headers=auth["approver"])
    assert response.status_code == 403
    assert client.post(f"/api/v1/invoices/{review_invoice}/approve", json={}, headers=auth["admin"]).status_code == 200


def test_reject_requires_reason_and_is_final(client: TestClient, auth, review_invoice: str) -> None:
    url = f"/api/v1/invoices/{review_invoice}"
    assert client.post(f"{url}/reject", json={"comment": "  "}, headers=auth["approver"]).status_code == 422
    response = client.post(f"{url}/reject", json={"comment": "Price not agreed"}, headers=auth["approver"])
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    again = client.post(f"{url}/approve", json={}, headers=auth["approver"])
    assert again.status_code == 409
    assert again.json()["code"] == "invalid_state"


def test_retry_is_admin_only(client: TestClient, auth, review_invoice: str) -> None:
    assert client.post(f"/api/v1/invoices/{review_invoice}/retry", headers=auth["approver"]).status_code == 403
    assert client.post(f"/api/v1/invoices/{review_invoice}/retry", headers=auth["admin"]).status_code == 409


def test_unknown_invoice(client: TestClient, auth) -> None:
    response = client.get("/api/v1/invoices/00000000-0000-0000-0000-000000000000", headers=auth["viewer"])
    assert response.status_code == 404
    assert client.get("/api/v1/invoices/not-a-uuid", headers=auth["viewer"]).status_code == 422
