# Local Setup & Deployment

This guide outlines how to bootstrap the Invoice Intelligence Platform locally for development and how it is deployed to Azure.

## Prerequisites

- **Docker Desktop** (for local backing services)
- **Node.js 20+**
- **Python 3.12**
- **Git**
- **Azure CLI** (`az`) & **GitHub CLI** (`gh`) (Optional, for deployment)

## Local Development Setup

### 1. Environment Configuration
Clone the repository and copy the environment template:
```bash
git clone git@github.com:shreyescodes/Invoice-Intelligence-Platform.git
cd Invoice-Intelligence-Platform
cp .env.example .env
```

### 2. Backing Services (Docker)
We use Docker Compose to spin up local equivalents of Azure services and other dependencies:
```bash
docker compose up -d azurite cosmosdb-emulator analytics-db mock-sap ollama mlflow prometheus grafana
```
*Note: `azurite` mocks Azure Blob Storage, and `cosmosdb-emulator` mocks Cosmos DB.*

### 3. Local LLM (Ollama)
For local development, we route LLM calls through a local Ollama container to avoid Azure OpenAI costs.
```bash
# Pull the required model
docker compose exec ollama ollama pull qwen2.5:14b
```
Ensure `LLM_PROVIDER=ollama` is set in your `.env` file.

### 4. Backend (FastAPI)
Create a virtual environment, install dependencies, and run the server:
```bash
cd backend
python -m venv venv
# Windows: venv\Scripts\activate
# Unix: source venv/bin/activate
pip install -e ".[dev]"
uvicorn src.api.main:app --reload
```

### 5. Frontend (React)
In a new terminal window:
```bash
cd frontend
npm install
npm run dev
```

## Production Deployment (Azure)

The platform is designed to be deployed to Azure using Infrastructure-as-Code (Bicep) and GitHub Actions.

### 1. Infrastructure Provisioning
The infrastructure is defined in `infra/main.bicep`. It provisions:
- Azure App Service (for FastAPI)
- Azure Function App (for Orchestration)
- Azure Cosmos DB Account
- Azure Storage Account
- Azure Key Vault
- Azure Document Intelligence & OpenAI Services
- Managed Identities

### 2. CI/CD Pipelines
The repository utilizes GitHub Actions located in `.github/workflows/`:
- **Python Package (`ci.yml`):** Runs on every push/PR to `main`. Executes `ruff` for linting and `mypy` for static type checking, ensuring code quality before deployment.
- **Build and Deploy (`deploy.yml`):** Deploys the application to Azure.
  - Deploys infrastructure using `az deployment group create`.
  - Packages and zips the FastAPI application and pushes it to Azure Web Apps.
  - Packages and deploys the Orchestrator code to Azure Functions.
  - Builds the React frontend and pushes to Azure Static Web Apps.

### 3. Required GitHub Secrets
To enable the deployment pipeline, you must configure a Service Principal in Azure and add the following secrets to your GitHub repository:
- `AZURE_CLIENT_ID`
- `AZURE_TENANT_ID`
- `AZURE_SUBSCRIPTION_ID`
- `AZURE_RESOURCE_GROUP`
- `AZURE_STATIC_WEB_APPS_API_TOKEN`
