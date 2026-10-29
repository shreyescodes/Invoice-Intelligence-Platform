"""Background worker: `python -m app.worker`.

Scale horizontally by running more replicas; jobs are claimed with row locks so each runs once.
"""

from __future__ import annotations

import os
import signal
import socket
import threading
import time
from collections.abc import Callable
from types import FrameType

from prometheus_client import start_http_server
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db import get_session_factory, session_scope
from app.models import Job
from app.observability import JOB_QUEUE_DEPTH, JOBS_COMPLETED, configure_logging, get_logger
from app.services import jobs
from app.services.pipeline import HANDLERS, PermanentJobError, PipelineServices, on_job_dead, record_retry
from app.services.vendors import sync_vendors

log = get_logger(__name__)


class Worker:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        services: PipelineServices,
        worker_id: str | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.services = services
        self.settings = services.settings
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}"
        self._last_maintenance = 0.0
        self._last_vendor_sync = 0.0

    def run_once(self) -> bool:
        """Claim and run one job. Returns False when the queue is empty."""
        with session_scope(self.session_factory) as session:
            job = jobs.claim_next(session, self.worker_id)
            if job is None:
                return False
            job_id, kind, invoice_id, attempt = job.id, job.kind, job.invoice_id, job.attempts

        log.info("job_started", job_id=job_id, kind=kind.value, invoice_id=str(invoice_id), attempt=attempt)
        session = self.session_factory()
        try:
            HANDLERS[kind](session, self.services, invoice_id)
            claimed = session.get(Job, job_id)
            if claimed is not None:
                jobs.mark_succeeded(claimed)
            session.commit()
            JOBS_COMPLETED.labels(kind.value, "succeeded").inc()
            log.info("job_succeeded", job_id=job_id, kind=kind.value)
        except PermanentJobError as exc:
            session.rollback()
            self._fail(job_id, str(exc), retryable=False)
        except Exception as exc:
            session.rollback()
            log.exception("job_errored", job_id=job_id, kind=kind.value)
            self._fail(job_id, f"{type(exc).__name__}: {exc}", retryable=True)
        finally:
            session.close()
        return True

    def _fail(self, job_id: int, error: str, *, retryable: bool) -> None:
        with session_scope(self.session_factory) as session:
            job = session.get(Job, job_id)
            if job is None:
                return
            dead = jobs.mark_failed(job, error, self.settings.worker_backoff_base_seconds, retryable=retryable)
            if dead:
                on_job_dead(session, job, error)
                JOBS_COMPLETED.labels(job.kind.value, "dead").inc()
                log.error("job_dead", job_id=job_id, kind=job.kind.value, error=error)
            else:
                record_retry(session, job, error)
                JOBS_COMPLETED.labels(job.kind.value, "retried").inc()
                log.warning("job_retry_scheduled", job_id=job_id, run_after=job.run_after.isoformat(), error=error)

    def maintenance(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if force or now - self._last_maintenance > 15:
            self._last_maintenance = now
            with session_scope(self.session_factory) as session:
                requeued = jobs.requeue_stale(session, self.settings.worker_lock_timeout_seconds)
                if requeued:
                    log.warning("stale_jobs_requeued", count=requeued)
                for kind, depth in jobs.queue_depth(session).items():
                    JOB_QUEUE_DEPTH.labels(kind).set(depth)
        if force or now - self._last_vendor_sync > self.settings.vendor_sync_interval_seconds:
            self._last_vendor_sync = now
            try:
                with session_scope(self.session_factory) as session:
                    sync_vendors(session, self.services.erp)
            except Exception as exc:
                log.warning("vendor_sync_failed", error=str(exc))

    def run_forever(self, stop: threading.Event) -> None:
        log.info("worker_started", worker_id=self.worker_id)
        self.maintenance(force=True)
        while not stop.is_set():
            try:
                self.maintenance()
                if not self.run_once():
                    stop.wait(self.settings.worker_poll_interval_seconds)
            except Exception:
                log.exception("worker_loop_error")
                stop.wait(5)
        log.info("worker_stopped", worker_id=self.worker_id)

    def drain(self, max_jobs: int = 10_000) -> int:
        """Run jobs until the queue is empty (used by tests and the demo seed)."""
        count = 0
        while count < max_jobs and self.run_once():
            count += 1
        return count


def install_signal_handlers(stop: threading.Event) -> None:
    def handler(signum: int, _: FrameType | None) -> None:
        log.info("shutdown_requested", signal=signum)
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, handler)


def start_background_worker(build: Callable[[], PipelineServices]) -> tuple[threading.Thread, threading.Event]:
    """Run a worker thread inside the API process (EMBEDDED_WORKER=true)."""
    stop = threading.Event()
    worker = Worker(get_session_factory(), build())
    thread = threading.Thread(target=worker.run_forever, args=(stop,), name="embedded-worker", daemon=True)
    thread.start()
    return thread, stop


def main() -> None:
    from app.runtime import build_pipeline_services

    settings = get_settings()
    configure_logging(settings)
    start_http_server(settings.worker_metrics_port)
    stop = threading.Event()
    install_signal_handlers(stop)
    Worker(get_session_factory(), build_pipeline_services(settings)).run_forever(stop)


if __name__ == "__main__":
    main()
