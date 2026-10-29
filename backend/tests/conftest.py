"""Shared fixtures.

Tests run against SQLite by default. Set TEST_DATABASE_URL (CI does) to run the same suite against
PostgreSQL - the job queue's row locking and the analytics SQL are dialect-sensitive.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="iip-tests-"))
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DATABASE_URL": os.environ.get("TEST_DATABASE_URL", f"sqlite:///{(_TMP / 'test.db').as_posix()}"),
        "STORAGE_BACKEND": "local",
        "STORAGE_LOCAL_PATH": str(_TMP / "documents"),
        "MODEL_DIR": str(_TMP / "models"),
        "JWT_SECRET": "test-secret-that-is-long-enough-0123456789",
        "LLM_PROVIDER": "none",
        "EXTRACTOR": "pdf_text",
        "ERP_BASE_URL": "http://erp.test",
        "ERP_API_KEY": "dev-erp-key",
        "WORKER_BACKOFF_BASE_SECONDS": "0",
        "DEMO_MODE": "false",
        "LOG_LEVEL": "WARNING",
        "CORS_ORIGINS": '["http://localhost:5173"]',
    }
)
os.environ.pop("ANALYTICS_DATABASE_URL", None)

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import Engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import Settings, get_settings  # noqa: E402
from app.db import Base, get_engine, get_session_factory  # noqa: E402
from app.demo.invoice_pdf import InvoiceDocument, Line, Party, render_invoice_pdf  # noqa: E402
from app.models import User, UserRole  # noqa: E402
from app.runtime import get_document_store  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services.anomaly import AnomalyModel, fit, synthetic_dataset  # noqa: E402
from app.services.erp import ErpClient  # noqa: E402
from app.services.extraction import build_extractor  # noqa: E402
from app.services.pipeline import PipelineServices  # noqa: E402
from app.services.vendors import sync_vendors  # noqa: E402
from app.worker import Worker  # noqa: E402
from tests.fakes import FakeErp  # noqa: E402

PASSWORD = "correct-horse-battery"
BUYER = Party(
    "Acme Manufacturing India Pvt Ltd", ["Plot 18, KIADB Industrial Area", "Bengaluru 561203"], "29AAACA4821K1Z6"
)
KAVERI = Party(
    "Kaveri Industrial Components Ltd", ["No. 42, Peenya Industrial Area", "Bengaluru 560058"], "29AABCK4321P1Z9"
)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    get_engine().dispose()
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture(scope="session")
def settings() -> Settings:
    return get_settings()


@pytest.fixture(scope="session")
def engine(settings: Settings) -> Engine:
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.attributes["configure_logger"] = False
    command.upgrade(config, "head")
    return get_engine()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        with engine.begin() as conn:
            for table in reversed(Base.metadata.sorted_tables):
                conn.execute(text(f"DELETE FROM {table.name}"))


@pytest.fixture(scope="session")
def anomaly_model() -> AnomalyModel:
    matrix, _ = synthetic_dataset(n_vendors=30, invoices_per_vendor=25)
    return fit(matrix, n_estimators=100)


@pytest.fixture
def erp() -> FakeErp:
    return FakeErp()


@pytest.fixture
def services(settings: Settings, erp: FakeErp, anomaly_model: AnomalyModel) -> PipelineServices:
    return PipelineServices(
        settings=settings,
        store=get_document_store(),
        extractor=build_extractor(settings, None),
        erp=ErpClient(settings.erp_base_url, "dev-erp-key", transport=erp.transport, backoff_seconds=0),
        anomaly_model=anomaly_model,
    )


@pytest.fixture
def vendors(db: Session, services: PipelineServices) -> None:
    sync_vendors(db, services.erp)
    db.commit()


@pytest.fixture
def worker(services: PipelineServices) -> Worker:
    return Worker(get_session_factory(), services, worker_id="test-worker")


@pytest.fixture
def users(db: Session) -> dict[str, User]:
    created = {}
    for role in UserRole:
        user = User(
            email=f"{role.value}@example.test",
            full_name=f"{role.value.title()} User",
            role=role,
            password_hash=hash_password(PASSWORD),
        )
        db.add(user)
        created[role.value] = user
    db.add(
        User(
            email="second-approver@example.test",
            full_name="Second Approver",
            role=UserRole.APPROVER,
            password_hash=hash_password(PASSWORD),
        )
    )
    db.commit()
    return created


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


def login(client: TestClient, email: str, password: str = PASSWORD) -> dict[str, str]:
    response = client.post("/api/v1/auth/token", data={"username": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def auth(client: TestClient, users: dict[str, User]) -> dict[str, dict[str, str]]:
    headers = {role: login(client, user.email) for role, user in users.items()}
    headers["approver2"] = login(client, "second-approver@example.test")
    return headers


def kaveri_invoice(
    *,
    number: str = "KIC/26-27/0412",
    po: str | None = "4500012101",
    lines: list[Line] | None = None,
    style: str = "classic",
    invoice_date: date | None = None,
    vendor: Party = KAVERI,
    **overrides: object,
) -> bytes:
    invoice_date = invoice_date or date.today() - timedelta(days=5)
    doc = InvoiceDocument(
        style=style,  # type: ignore[arg-type]
        vendor=vendor,
        buyer=BUYER,
        invoice_number=number,
        invoice_date=invoice_date,
        due_date=invoice_date + timedelta(days=45),
        po_number=po,
        lines=lines
        or [
            Line("Hydraulic hose assembly 3/4 in", Decimal(40), Decimal("1450.00"), "4009"),
            Line("Inductive proximity sensor M18", Decimal(10), Decimal("2350.00"), "8536"),
        ],
        tax_rate=Decimal(18),
        intra_state=True,
        **overrides,  # type: ignore[arg-type]
    )
    return render_invoice_pdf(doc)
