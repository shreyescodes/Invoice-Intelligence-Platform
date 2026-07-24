"""Example test — the pattern to copy for every new endpoint.

Run: pytest tests/unit/test_health.py -v
Or all tests + coverage: pytest
"""


def test_health_returns_ok(client) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"


def test_health_reports_environment(client) -> None:
    response = client.get("/health")

    assert "environment" in response.json()
