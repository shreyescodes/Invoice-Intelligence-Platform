# Invoice Intelligence Platform

First of all, welcome guys!

This is an AI-powered accounts-payable automation platform I built as a learning project. I am ingesting vendor invoices, extracting structured data using OCR + an LLM, validating everything against my SAP purchase orders, scoring for anomalies, routing for human approval when needed, posting back to SAP, and finally feeding a Snowflake-backed analytics layer.

I have built this as a proper enterprise-grade AP-automation platform. Kindly check the codebase to see how I have done the needful for every component.

## Tech Stack

- **Frontend:** React, Vite, TypeScript, Tailwind CSS
- **Backend:** Python 3.12, FastAPI, Pydantic v2, Pytest 
- **Azure Cloud:** Azure Functions (Durable Functions), Cosmos DB, Blob Storage, Key Vault, Document Intelligence, Azure OpenAI, Managed Identity, OAuth2 (Entra ID)
- **Data & ML:** Snowflake, SQL, MLflow, scikit-learn, Azure ML 
- **DevOps:** GitHub Actions CI/CD, OpenTelemetry, Prometheus, Grafana

## Pre-requisites & Local Setup

Kindly follow the below steps to set up the project on your local machine (zero Azure cost to start).

```bash
# 1. Clone the repo
git clone git@github.com:shreyescodes/Invoice-Intelligence-Platform.git
cd Invoice-Intelligence-Platform

# 2. Setup environment variables
cp .env.example .env

# 3. Start the background services
docker compose up -d azurite cosmosdb-emulator analytics-db mock-sap ollama mlflow prometheus grafana

# 4. Pull a local model (see model choices below)
docker compose exec ollama ollama pull qwen2.5:14b

# 5. Setup Python backend
cd backend
python -m venv venv312
venv312\Scripts\activate
pip install -e ".[dev]" 

# 6. Start the API
uvicorn src.api.main:app --reload
```

In a separate terminal, kindly start the frontend UI:
```bash
cd frontend
npm install
npm run dev
```

Please find below the local URLs for testing:
- Frontend UI: http://localhost:5173
- API Docs: http://localhost:8000/docs
- Mock SAP: http://localhost:8100/docs
- Grafana: http://localhost:3000 (anonymous admin access)
- Cosmos DB emulator: https://localhost:8081/_explorer/index.html

To run backend tests, simply execute: `pytest tests/`
To check backend linting, please run: `ruff check .`

## Local-first Model Choices

If you set `LLM_PROVIDER=ollama` in your `.env`, I am routing every LLM call through the local Ollama container. This means zero token cost and no Azure OpenAI access request needed while developing! I will swap to `azure_openai` only for the final production deployment.

| Hardware | Model | Pull command |
|---|---|---|
| 16GB RAM, no/modest GPU | Qwen 2.5 14B | `ollama pull qwen2.5:14b` |
| 16GB, JSON-heavy extraction | Granite 4.0 | `ollama pull granite4` |
| 24GB+ VRAM | Qwen 3.6 27B | `ollama pull qwen3.6:27b` |

## What I Have Implemented (Phases)

I have successfully completed all phases of the project:

1. **Foundations** - Scaffold is up and running, CI lints and tests are green.
2. **Extraction** - Document Intelligence + LLM cleanup, `extract_document` activity is fully working.
3. **Orchestration** - Azure Durable Functions orchestrator is in place, handling mock SAP validation and approval wait states.
4. **Data layer** - Cosmos DB writes and ETL into the Snowflake star schema are done.
5. **ML** - Isolation Forest anomaly model is integrated and wired into the orchestrator.
6. **Cloud & API** - FastAPI endpoints are ready.
7. **Chat & UI** - React frontend is built, and the NL-to-SQL chat endpoint is up and running.

## Cost Notes

Kindly note that everything above runs free locally! When deploying to Azure, please be aware that Snowflake and Azure OpenAI are the two genuinely billable pieces. Budget a small spend for the final demo rather than developing against them directly. 

If you have any doubts, please revert back to me! 

Cheers!
