# 0002. Background work runs from a job table in PostgreSQL

- Status: accepted
- Date: 2026-10-29

## Context

Uploads must return quickly, and extraction, ERP lookups and posting must survive restarts, retry on
transient failures and never run twice in a way that has effects. The options were a broker (Redis/RQ,
RabbitMQ, Azure Service Bus), a workflow engine (Durable Functions, Temporal), or a table in the
database we already have.

The deciding problem is the **dual write**: with a broker, "commit the invoice as approved" and
"publish the posting message" are two systems. One can succeed without the other, so you end up with
approved invoices that never post, or postings for rolled-back approvals.

## Decision

A `jobs` table is the queue. Producers insert jobs in the same transaction as the state change (the
transactional outbox pattern, with the outbox *being* the queue). Workers claim jobs with
`SELECT … FOR UPDATE SKIP LOCKED`, run each handler in its own transaction, and reschedule failures
with exponential backoff and jitter. Jobs whose lock outlives a timeout are requeued. Handlers are
idempotent: they check the invoice's current state, and ERP postings carry an idempotency key.

## Consequences

- No extra infrastructure, and no window where state and work disagree.
- Horizontal scaling: workers never contend for the same row.
- Every job's attempts, errors and next run time are queryable with SQL, and visible in the audit trail.
- Throughput is bounded by the database. That is thousands of jobs per minute here, far above need; if
  it ever isn't, the same handlers can be fed from Service Bus with the table kept as the outbox.
- Polling adds up to `WORKER_POLL_INTERVAL_SECONDS` of latency (1s); `LISTEN/NOTIFY` could remove it.
