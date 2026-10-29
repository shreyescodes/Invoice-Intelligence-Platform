# Deployment and operations

## Environments

| | Database | Documents | Extraction | Secrets |
|---|---|---|---|---|
| Laptop, no Docker | SQLite | `backend/data/documents` | PDF text | `.env` |
| `docker compose` | PostgreSQL 16 (+ read-only reporting role) | named volume | PDF text | compose variables |
| Azure | PostgreSQL Flexible Server | Blob Storage (managed identity) | PDF text or Document Intelligence | Key Vault references |

## Deploying to Azure

[`infra/main.bicep`](../infra/main.bicep) provisions everything except the registry, which
[`infra/registry.bicep`](../infra/registry.bicep) creates first, so images can be pushed before the
apps reference them:

- **Container Apps** environment (Consumption workload profile) with `web` (public ingress), `api`
  (internal ingress, HTTP-concurrency autoscaling), `worker` (no ingress) and, unless you supply
  `erpBaseUrl`, the mock ERP (internal ingress)
- **Container Apps job** `migrate`, triggered by the deploy workflow before traffic shifts
- **PostgreSQL Flexible Server** 16 (Burstable B1ms, 14-day backups, TLS required)
- **Storage account** with versioning and soft delete, shared-key access disabled
- **Key Vault** (RBAC, purge protection) holding the database URL, JWT secret and ERP key
- **User-assigned managed identity** with `AcrPull`, `Key Vault Secrets User` and
  `Storage Blob Data Contributor`; no passwords or keys are stored in app settings
- **Log Analytics** workspace receiving container stdout (the JSON logs)

### One-time setup

1. Create a resource group and an Entra ID app registration with a **federated credential** for this
   repository (`repo:<owner>/<repo>:environment:production`). Give it `Contributor` and
   `User Access Administrator` (needed to create the role assignments) on the resource group.
2. In the repository, create a `production` environment with required reviewers, and add the secrets
   `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `AZURE_RESOURCE_GROUP`,
   `POSTGRES_ADMIN_PASSWORD` and `JWT_SECRET` (`openssl rand -base64 48`).
3. Run **Actions → Deploy to Azure**. The workflow deploys the registry, builds and pushes the three
   images tagged with the commit SHA, deploys `main.bicep`, runs the migration job and smoke-tests
   `/api/v1/meta` through the public endpoint.

### After the first deployment

Create the reporting role used by the Ask page and point the API at it:

```sql
CREATE ROLE iip_readonly LOGIN PASSWORD '<strong password>';
ALTER ROLE iip_readonly SET default_transaction_read_only = on;
ALTER ROLE iip_readonly SET statement_timeout = '5s';
GRANT CONNECT ON DATABASE iip TO iip_readonly;
GRANT USAGE ON SCHEMA public TO iip_readonly;
GRANT SELECT ON analytics_invoices, analytics_line_items, analytics_checks, analytics_vendors TO iip_readonly;
```

Then store `postgresql+psycopg://iip_readonly:<password>@<server>:5432/iip?sslmode=require` in Key
Vault as `analytics-database-url` and add it to the API's secrets and environment. Without it, Ask
queries still run behind the SQL guard in a read-only transaction, but on the application's own
connection.

Create real users with `iip create-user --email … --name … --role admin --password-env VAR`, run as a
one-off execution of the `migrate` job (same image and secrets) with the command overridden, or from
any machine that can reach the database with `DATABASE_URL` set. Leave `demoMode` off so the demo
accounts are never created or advertised.

### Hardening checklist for production

- Put Container Apps and PostgreSQL on a VNet with private endpoints, and remove the "allow Azure
  services" firewall rule.
- Front `web` with Azure Front Door and a WAF policy (rate limiting also covers login attempts across
  replicas).
- Persist the anomaly model to Blob Storage (or train it in CI) instead of on replica start-up.
- Replace local accounts with Entra ID single sign-on (the role checks map directly onto app roles).
- Configure alert rules on the Log Analytics workspace, or scrape the `/metrics` endpoints with Azure
  Monitor managed Prometheus using the rules in [`deploy/monitoring/alerts.yml`](../deploy/monitoring/alerts.yml).

## Releases and migrations

- Migrations are forward-only in production and must stay compatible with the previous release's code
  (expand, deploy, then contract in a later release), because the old revision keeps serving while the
  new one starts.
- `iip migrate` is idempotent; the deploy workflow runs it before the new revision takes traffic.
- CI's `alembic check` (in the test suite) fails if a model change has no migration.

## Runbook

### An invoice is in `failed`

The detail page shows the stage (`processing` or `posting`) and the last error, and the audit trail
shows every retry.

| Error | Cause | Action |
|---|---|---|
| `Unreadable PDF …` | corrupt, encrypted or scanned document | ask the vendor for a digital PDF, or enable the Document Intelligence extractor, then **Retry processing** |
| `ERP unreachable …` / `ERP returned 503` | ERP outage longer than the retry window | once the ERP is back, **Retry**; the posting is idempotent |
| `Item 10: invoiced quantity exceeds goods received` | someone else invoiced the goods first, or the receipt was reversed | resolve in the ERP, then retry posting; or reject the invoice |
| `Supplier invoice already posted` | it was posted outside this system | reject the invoice as a duplicate |

Retrying needs the admin role and re-queues only the failed stage.

### The queue is backing up (`JobBacklogGrowing`)

1. Check worker health and logs (`job_errored`, `job_retry_scheduled`).
2. If the ERP is slow, `iip_erp_requests_total{result="unavailable"}` will be climbing: the jobs will
   drain on their own when it recovers.
3. Otherwise scale the worker; replicas claim jobs with `SKIP LOCKED` and never pick the same job.

### A worker crashed mid-job

Nothing to do. Jobs left `running` longer than `WORKER_LOCK_TIMEOUT_SECONDS` (5 minutes by default)
are returned to the queue by any live worker, and handlers are idempotent.

### Rotating secrets

- **JWT secret:** update the Key Vault secret and restart the API revision. Existing sessions end;
  users sign in again.
- **Database password:** rotate on the server, update `database-url` in Key Vault, restart the API and
  worker.
- **ERP key:** update `erp-api-key`; the worker picks it up on restart.

### Backups and restore

PostgreSQL Flexible Server keeps point-in-time backups for 14 days (set in Bicep). Restore to a new
server, then update `database-url`. Documents in Blob Storage have versioning and 30-day soft delete.

## Useful commands

```bash
iip migrate                    # apply migrations
iip seed [--process]           # demo data (skips if invoices already exist)
iip sync-vendors               # pull the supplier master from the ERP now
iip train-anomaly [--from-db]  # retrain and save the anomaly model
iip create-user --email … --name … --role admin|approver|clerk|viewer --password-env VAR
iip generate-samples --out samples/invoices
iip export-openapi --out ../frontend/openapi.json
iip worker                     # run a worker (metrics on :9101)
```
