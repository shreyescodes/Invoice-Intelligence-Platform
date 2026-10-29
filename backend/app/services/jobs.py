"""Durable job queue on the primary database.

Jobs are inserted in the same transaction as the state change that requires them (an outbox), so an
invoice can never be committed as "approved" without its ERP posting job. Workers claim jobs with
`SELECT ... FOR UPDATE SKIP LOCKED` on PostgreSQL, so any number of worker replicas can run safely.
"""

from __future__ import annotations

import random
import uuid
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import Job, JobKind, JobStatus


def enqueue(session: Session, kind: JobKind, invoice_id: uuid.UUID, max_attempts: int = 5) -> Job:
    job = Job(kind=kind, invoice_id=invoice_id, max_attempts=max_attempts, run_after=utcnow())
    session.add(job)
    return job


def claim_next(session: Session, worker_id: str) -> Job | None:
    """Lock and mark the next runnable job. Caller must commit to release the row lock."""
    stmt = (
        select(Job)
        .where(Job.status == JobStatus.QUEUED, Job.run_after <= utcnow())
        .order_by(Job.run_after, Job.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    job = session.scalars(stmt).first()
    if job is None:
        return None
    job.status = JobStatus.RUNNING
    job.locked_by = worker_id
    job.locked_at = utcnow()
    job.attempts += 1
    session.flush()
    return job


def mark_succeeded(job: Job) -> None:
    job.status = JobStatus.SUCCEEDED
    job.finished_at = utcnow()
    job.last_error = None
    job.locked_by = None


def mark_failed(job: Job, error: str, backoff_base_seconds: float, *, retryable: bool = True) -> bool:
    """Schedule a retry with exponential backoff and jitter. Returns True if the job is now dead."""
    job.last_error = error[:4000]
    job.locked_by = None
    if not retryable or job.attempts >= job.max_attempts:
        job.status = JobStatus.DEAD
        job.finished_at = utcnow()
        return True
    delay = backoff_base_seconds * (2 ** (job.attempts - 1))
    job.status = JobStatus.QUEUED
    job.run_after = utcnow() + timedelta(seconds=delay * random.uniform(0.8, 1.2))  # noqa: S311
    return False


def requeue_stale(session: Session, lock_timeout_seconds: int) -> int:
    """Return jobs held by crashed workers to the queue."""
    cutoff = utcnow() - timedelta(seconds=lock_timeout_seconds)
    result = session.execute(
        update(Job)
        .where(Job.status == JobStatus.RUNNING, Job.locked_at < cutoff)
        .values(status=JobStatus.QUEUED, locked_by=None, run_after=utcnow())
    )
    return int(getattr(result, "rowcount", 0) or 0)


def queue_depth(session: Session) -> dict[str, int]:
    rows = session.execute(
        select(Job.kind, func.count()).where(Job.status == JobStatus.QUEUED).group_by(Job.kind)
    ).all()
    depth = {kind.value: 0 for kind in JobKind}
    depth.update({kind.value if isinstance(kind, JobKind) else str(kind): int(count) for kind, count in rows})
    return depth
