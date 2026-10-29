from __future__ import annotations

import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.demo.invoice_pdf import Line
from app.services.ask import CATALOG, UnsafeQueryError, guard_sql
from tests.conftest import kaveri_invoice
from tests.fakes import FakeLLM
from tests.test_pipeline import upload

# --- SQL guard ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("dialect", ["postgresql", "sqlite"])
def test_guard_accepts_reads_and_enforces_limit(dialect: str) -> None:
    sql = guard_sql("select vendor_name, sum(total_amount) as spend from analytics_invoices group by 1", dialect, 50)
    assert sql.endswith("LIMIT 50")
    assert guard_sql("select * from analytics_invoices limit 10", dialect, 50).endswith("LIMIT 10")
    assert guard_sql("select * from analytics_invoices limit 5000", dialect, 50).endswith("LIMIT 50")
    cte = "with v as (select vendor_name from analytics_invoices) select * from v"
    assert "LIMIT 50" in guard_sql(cte, dialect, 50)
    union = "select vendor_id from analytics_vendors union select vendor_id from analytics_invoices"
    assert guard_sql(union, dialect, 50).endswith("LIMIT 50")


@pytest.mark.parametrize(
    "sql",
    [
        "delete from analytics_invoices",
        "update invoices set status = 'approved'",
        "select 1; drop table users",
        "select * from users",
        "select password_hash from users",
        "select * from pg_catalog.pg_user",
        "select * from information_schema.tables",
        "select pg_sleep(30)",
        "select pg_read_file('/etc/passwd')",
        "select * into stolen from analytics_invoices",
        "select * from analytics_invoices for update",
        "copy analytics_invoices to '/tmp/x'",
        "insert into analytics_vendors values (1)",
        "not even sql (",
        "",
    ],
)
def test_guard_rejects_dangerous_sql(sql: str) -> None:
    with pytest.raises(UnsafeQueryError):
        guard_sql(sql, "postgresql", 100)


@pytest.mark.parametrize("dialect", ["postgresql", "sqlite"])
def test_catalog_queries_pass_the_guard(dialect: str) -> None:
    for query in CATALOG:
        guard_sql(query.for_dialect(dialect), dialect, 500)


# --- Endpoints ------------------------------------------------------------------------------------------


@pytest.fixture
def processed(client: TestClient, auth, vendors, worker) -> None:
    upload(client, auth["clerk"], kaveri_invoice(number="KIC/S/1"), "1.pdf")
    other = [Line("Inductive proximity sensor M18", Decimal(4), Decimal("2350.00"), "8536")]
    upload(client, auth["clerk"], kaveri_invoice(number="KIC/S/2", po=None, lines=other), "2.pdf")
    worker.drain()


def test_dashboard_summary(client: TestClient, auth, processed: None) -> None:
    body = client.get("/api/v1/analytics/summary?days=30", headers=auth["viewer"]).json()
    kpis = body["kpis"]
    assert kpis["invoices_received"] == 2
    assert kpis["invoices_processed"] == 2
    assert kpis["review_queue_count"] == 1
    assert kpis["straight_through_rate"] == 1.0  # the only decided invoice was auto-approved
    assert kpis["spend_approved"] == pytest.approx(96170.0)
    assert body["status_counts"]["posted"] == 1
    assert len(body["monthly_spend"]) == 12
    assert body["top_vendors"][0]["name"] == "Kaveri Industrial Components Ltd"
    assert {e["name"] for e in body["exceptions"]} == {"PO_MATCH"}


@pytest.mark.parametrize("query", CATALOG, ids=lambda q: q.question[:30])
def test_every_catalog_question_runs(client: TestClient, auth, processed: None, query) -> None:
    response = client.post("/api/v1/analytics/ask", json={"question": query.question}, headers=auth["viewer"])
    assert response.status_code == 200, response.text
    assert response.json()["source"] == "catalog"


def test_catalog_answers_contain_data(client: TestClient, auth, processed: None) -> None:
    body = client.post(
        "/api/v1/analytics/ask", json={"question": "which invoices are waiting for review"}, headers=auth["viewer"]
    ).json()
    assert body["columns"][0] == "invoice_number"
    assert body["rows"][0][0] == "KIC/S/2"


def test_free_form_question_without_llm(client: TestClient, auth) -> None:
    response = client.post(
        "/api/v1/analytics/ask", json={"question": "how many vendors are in Pune?"}, headers=auth["viewer"]
    )
    assert response.status_code == 422
    assert response.json()["code"] == "question_not_supported"
    assert response.json()["extra"]["suggestions"]


def test_llm_generated_sql_is_guarded_and_executed(
    client: TestClient, auth, processed: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.routes import analytics as route

    llm = FakeLLM(
        [
            json.dumps(
                {
                    "sql": "SELECT vendor_name, COUNT(*) AS n FROM analytics_invoices GROUP BY vendor_name",
                    "chart": "bar",
                }
            ),
            "Kaveri Industrial Components Ltd has 2 invoices.",
        ]
    )
    monkeypatch.setattr(route, "get_llm", lambda: llm)
    response = client.post("/api/v1/analytics/ask", json={"question": "invoices per vendor?"}, headers=auth["viewer"])
    body = response.json()
    assert response.status_code == 200, body
    assert body["source"] == "llm"
    assert body["chart"] == "bar"
    assert body["rows"] == [["Kaveri Industrial Components Ltd", 2]]
    assert body["sql"].endswith("LIMIT 500")
    assert body["answer"].startswith("Kaveri")
    assert "analytics_invoices" in llm.calls[0][0]  # schema is in the system prompt


def test_llm_generated_write_is_refused(client: TestClient, auth, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.routes import analytics as route

    llm = FakeLLM([json.dumps({"sql": "DELETE FROM analytics_invoices"})])
    monkeypatch.setattr(route, "get_llm", lambda: llm)
    response = client.post("/api/v1/analytics/ask", json={"question": "remove everything"}, headers=auth["viewer"])
    assert response.status_code == 422
    assert response.json()["code"] == "unsafe_query"
