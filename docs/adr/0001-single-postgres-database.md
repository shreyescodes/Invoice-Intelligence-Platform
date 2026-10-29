# 0001. One PostgreSQL database instead of Cosmos DB + Snowflake + Durable Functions

- Status: accepted
- Date: 2026-10-29

## Context

The first version of this project split state across Cosmos DB (invoices), Snowflake (analytics),
Blob Storage and Azure Durable Functions (orchestration). Nothing could run end to end without several
cloud services or emulators, and the pieces disagreed with each other: Cosmos's immutable partition key
(`vendor_id`) meant re-creating documents whenever extraction found the real vendor, the ETL to
Snowflake ran on a timer with a hand-rolled watermark, and approval state lived in two places (the
orchestrator and the document).

The workload is a few thousand invoices a day at most. It is relational (invoices, lines, checks,
vendors, users, audit events), it needs multi-row transactions (state change + audit event + job), and
its analytics are aggregates over the same data.

## Decision

Use PostgreSQL as the single system of record, including the work queue and the reporting views. Keep
object storage for documents. Run processing in a plain worker process instead of Durable Functions.

## Consequences

- Every state change, its audit event and its follow-up job commit atomically, so there are no
  dual-write inconsistencies.
- Analytics query live data through views; there is no ETL lag or second copy to reconcile. A
  warehouse can be added later by replicating these views if reporting volume ever demands it.
- The whole system runs locally with `docker compose up`, and tests run on SQLite or PostgreSQL.
- On Azure it maps onto managed services (Flexible Server, Container Apps) without
  vendor-specific programming models.
- We give up Cosmos's global distribution and Snowflake's elastic compute, which this workload doesn't need.
