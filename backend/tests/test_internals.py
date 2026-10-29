"""Job queue, storage, anomaly model, security helpers and migrations."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import build_engine, utcnow
from app.models import Invoice, InvoiceStatus, Job, JobKind, JobStatus, UserRole
from app.security import LoginThrottle, create_access_token, decode_access_token, hash_password, verify_password
from app.services import jobs
from app.services.anomaly import AnomalyModel, HistoricalInvoice, build_features, explain, synthetic_dataset
from app.services.storage import DocumentNotFoundError, LocalDocumentStore


def _invoice(db: Session) -> Invoice:
    invoice = Invoice(
        file_name="x.pdf",
        content_type="application/pdf",
        file_size=1,
        file_sha256=uuid.uuid4().hex,
        storage_key="k",
        status=InvoiceStatus.RECEIVED,
    )
    db.add(invoice)
    db.flush()
    return invoice


def test_job_claim_backoff_and_dead_letter(db: Session) -> None:
    invoice = _invoice(db)
    jobs.enqueue(db, JobKind.PROCESS_INVOICE, invoice.id, max_attempts=2)
    db.commit()

    job = jobs.claim_next(db, "w1")
    assert job is not None and job.status is JobStatus.RUNNING and job.attempts == 1
    db.commit()
    assert jobs.claim_next(db, "w2") is None  # nothing else runnable

    assert jobs.mark_failed(job, "boom", backoff_base_seconds=60) is False
    assert job.status is JobStatus.QUEUED and job.run_after > utcnow() + timedelta(seconds=40)
    db.commit()
    assert jobs.claim_next(db, "w1") is None  # backing off

    job.run_after = utcnow()
    db.commit()
    job = jobs.claim_next(db, "w1")
    assert job is not None
    assert jobs.mark_failed(job, "boom again", backoff_base_seconds=60) is True
    assert job.status is JobStatus.DEAD


def test_stale_jobs_are_requeued(db: Session) -> None:
    invoice = _invoice(db)
    db.add(
        Job(
            kind=JobKind.POST_TO_ERP,
            invoice_id=invoice.id,
            status=JobStatus.RUNNING,
            locked_at=utcnow() - timedelta(hours=1),
            locked_by="dead-worker",
        )
    )
    db.commit()
    assert jobs.requeue_stale(db, lock_timeout_seconds=300) == 1
    db.commit()
    assert jobs.queue_depth(db)["post_to_erp"] == 1


def test_local_store_round_trip_and_path_traversal(tmp_path: Path) -> None:
    store = LocalDocumentStore(tmp_path)
    store.put("invoices/2026/10/a.pdf", b"data", "application/pdf")
    assert store.get("invoices/2026/10/a.pdf") == b"data"
    store.delete("invoices/2026/10/a.pdf")
    with pytest.raises(DocumentNotFoundError):
        store.get("invoices/2026/10/a.pdf")
    for key in ("../outside.pdf", "/etc/passwd", "a/../../b"):
        with pytest.raises(ValueError, match="invalid storage key"):
            store.put(key, b"x", "application/pdf")


def test_anomaly_model_separates_injected_anomalies(anomaly_model: AnomalyModel) -> None:
    matrix, labels = synthetic_dataset(n_vendors=30, seed=99, anomaly_rate=0.08)
    scores = anomaly_model.score_matrix(matrix)
    assert scores[labels == 1].mean() > scores[labels == 0].mean() + 0.25
    assert np.median(scores[labels == 0]) < 0.3


def test_anomaly_features_and_reasons() -> None:
    today = date(2026, 10, 1)
    history = [HistoricalInvoice(today - timedelta(days=30 * i), 50_000.0, 0.18) for i in range(1, 8)]
    normal = build_features(51_234, 43_419, 7_815, today, 2, history)
    spike = build_features(500_000, 423_729, 76_271, today, 2, history)
    assert explain(normal) == []
    assert any("10.0x" in reason for reason in explain(spike))
    assert explain(build_features(10_430, 8_839, 1_591, today, 1, []))[0].startswith("First invoice")
    assert explain(normal, score=0.7) == ["Unusual combination of amount, tax rate and timing for this vendor"]
    low = build_features(17_000, 14_407, 2_593, today, 1, history)
    assert any("unusually low" in reason for reason in explain(low))


def test_anomaly_model_persists(anomaly_model: AnomalyModel, tmp_path: Path) -> None:
    path = anomaly_model.save(tmp_path)
    loaded = AnomalyModel.load(path)
    features = build_features(10_000, 8_475, 1_525, date(2026, 1, 1), 1, [])
    assert loaded.score(features) == anomaly_model.score(features)


def test_passwords_and_tokens(settings: Settings) -> None:
    hashed = hash_password("s3cret-password")
    assert verify_password(hashed, "s3cret-password")
    assert not verify_password(hashed, "wrong")
    assert not verify_password(None, "anything")
    token, ttl = create_access_token(uuid.uuid4(), UserRole.CLERK, settings)
    assert decode_access_token(token, settings)["role"] == "clerk"
    assert ttl == settings.jwt_ttl_minutes * 60


def test_login_throttle_window() -> None:
    throttle = LoginThrottle(max_failures=2, window_seconds=60)
    throttle.record_failure("A@x.test")
    assert not throttle.is_locked("a@x.test")
    throttle.record_failure("a@x.test")
    assert throttle.is_locked("a@x.test")
    throttle.reset("a@x.test")
    assert not throttle.is_locked("a@x.test")


def test_production_settings_refuse_insecure_defaults() -> None:
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(environment="production", jwt_secret="dev-only-insecure-secret-change-me-0123456789")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="DEMO_MODE"):
        Settings(environment="production", jwt_secret="x" * 40, demo_mode=True)  # type: ignore[arg-type]


def test_migrations_build_the_full_schema(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.attributes.update(database_url=url, configure_logger=False)
    command.upgrade(config, "head")
    command.check(config)  # models and migrations have not drifted apart
    names = inspect(build_engine(url)).get_view_names()
    assert set(names) == {"analytics_invoices", "analytics_line_items", "analytics_checks", "analytics_vendors"}
    command.downgrade(config, "base")
