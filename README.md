# Invoice Intelligence Platform

AI-powered accounts-payable automation: ingest vendor invoices, extract
structured data with OCR + an LLM, validate against SAP purchase
orders, score for anomalies, route for human approval when needed,
post back to SAP, and feed a Snowflake-backed analytics layer.

Built as a learning project — every component exists because a real
enterprise AP-automation platform needs it, not because it fits a
skills checklist. See the TODO in each file for what to build and why.

## Stack

Python 3.11, FastAPI, Pydantic v2, Pytest · Azure Functions (Durable
Functions), Cosmos DB, Blob Storage, Key Vault, Document Intelligence,
Azure OpenAI · Snowflake, SQL · GitLab CI/CD, Workload Identity
Federation · OpenTelemetry, Prometheus, Grafana, Application Insights
· MLflow, scikit-learn, Azure ML · Managed Identity, OAuth2 (Entra ID)

## Local setup (zero Azure cost to start)

```bash
git clone git@github.com:shreyescodes/Invoice-Intelligence-Platform.git
cd Invoice-Intelligence-Platform
cp .env.example .env
docker compose up -d azurite cosmosdb-emulator analytics-db mock-sap ollama mlflow prometheus grafana

# pull a local model (see model choices below)
docker compose exec ollama ollama pull qwen2.5:14b

cd backend
pip install -e ".[dev]" --break-system-packages   # or use a venv
uvicorn src.api.main:app --reload
```

- API: http://localhost:8000/docs
- Mock SAP: http://localhost:8100/docs
- Grafana: http://localhost:3000 (anonymous admin access, local only)
- MLflow: http://localhost:5001
- Cosmos DB emulator explorer: https://localhost:8081/_explorer/index.html

Run tests: `pytest`
Lint/typecheck: `ruff check . && mypy src`

## Local-first model choices

`LLM_PROVIDER=ollama` in `.env` routes every LLM call through the
local Ollama container — zero token cost, no Azure OpenAI access
request needed while you build. Swap to `azure_openai` only for the
final integration pass (see src/llm/provider.py — same code path
either way).

| Hardware | Model | Pull command |
|---|---|---|
| 16GB RAM, no/modest GPU | Qwen 2.5 14B | `ollama pull qwen2.5:14b` |
| 16GB, JSON-heavy extraction | Granite 4.0 | `ollama pull granite4` |
| 24GB+ VRAM | Qwen 3.6 27B | `ollama pull qwen3.6:27b` |

All expose an OpenAI-compatible API at `:11434/v1` — the SDK code
never changes, only the model tag.

## Phase roadmap

Build in this order — each phase produces something that runs before
you move on. Detail and rationale for each is in the file TODOs, not
duplicated here.

1. **Foundations** — this scaffold runs, `/health` passes, CI lints and tests green
2. **Extraction** — Document Intelligence + LLM cleanup, `extract_document` activity
3. **Orchestration** — Durable Functions orchestrator, mock SAP validation, approval wait
4. **Data layer** — Cosmos DB writes, ETL into the star schema, dashboards read real data
5. **ML** — anomaly model, MLflow tracking, wired into the orchestrator
6. **Cloud + security** — real Azure resources, Key Vault, Managed Identity, WIF deploy
7. **Chat + polish** — NL query endpoint, OAuth2 on the API, Grafana dashboards finished

## Cost notes

Everything above runs free locally. When you do touch real Azure/
Snowflake resources: Cosmos DB and Azure Functions have an
always-free tier, Document Intelligence F0 gives 500 pages/month,
Grafana Cloud free tier is generous if you want a hosted dashboard
instead of the local one. Snowflake and Azure OpenAI are the two
genuinely billable pieces — budget a small one-time spend for the
final demo rather than developing against them directly. Full
reasoning in chat / commit history, not repeated here.
