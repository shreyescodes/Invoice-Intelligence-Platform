# Architecture & Design

This document details the architectural topology of the Invoice Intelligence Platform, mapping the integration points and state flow across the system components.

## System Topology

The platform follows a microservices-inspired, event-driven architecture heavily leveraging serverless computing and managed platform-as-a-service (PaaS) offerings in Azure.

### 1. Presentation Layer (Frontend)
- **Framework:** React + Vite
- **Language:** TypeScript
- **Styling:** Tailwind CSS
- **Capabilities:** Displays a dynamic dashboard of invoice statuses, provides a chat interface for NL-to-SQL analytics querying, and surfaces a UI for manual human-in-the-loop approvals.

### 2. API Layer (Backend)
- **Framework:** FastAPI
- **Language:** Python 3.12
- **Responsibilities:** 
  - Exposes RESTful endpoints for the frontend.
  - Acts as the ingest point for raw invoice uploads.
  - Serves as the query translation bridge, taking natural language questions and using LLMs to generate Snowflake SQL.

### 3. Orchestration & Processing Layer (Azure Durable Functions)
The core processing engine is built on **Azure Durable Functions**. It ensures stateful execution of the extraction and validation pipeline.
- **Activity Functions:** Stateless functions that execute discrete steps (e.g., calling Azure Document Intelligence, invoking the ML Anomaly Detection model).
- **Orchestrator Function:** Manages the execution flow. It can yield execution, await external events (like a manual approval from the dashboard), and handle retries/compensating transactions automatically.

### 4. Data & Analytics Layer
The system maintains transactional and analytical data across specialized stores:
- **Azure Blob Storage:** Stores the immutable raw PDF invoices uploaded to the platform.
- **Azure Cosmos DB (NoSQL):** Serves as the operational datastore containing JSON documents representing the invoice metadata, line items, status, and anomaly scores.
- **Snowflake:** Acts as the analytical data warehouse. Periodically, data is ETL'd into a star schema (Fact & Dimension tables) optimized for aggregations, dashboarding, and natural language querying.

## Workflow: The Invoice Lifecycle

1. **Ingestion:** An invoice (PDF) is uploaded via the FastAPI endpoint. It is persisted to Azure Blob Storage, and an initial "PENDING" record is created in Cosmos DB.
2. **Extraction:** An Azure Function triggers on the new record. It invokes **Azure Document Intelligence** to perform OCR and structure the document. It then feeds the output to an **Azure OpenAI** LLM to sanitize and enforce schema validation according to predefined Pydantic models.
3. **Validation & Anomaly Detection:**
   - The invoice details are verified against a mock SAP ERP endpoint (checking PO validity).
   - An **Isolation Forest** ML model evaluates the invoice amount, vendor history, and tax ratios, assigning an `anomaly_score`.
4. **Approval Routing:**
   - If the anomaly score exceeds a threshold, the Orchestrator pauses the workflow and issues an external event waiter. The invoice status is marked as `NEEDS_REVIEW`.
   - A human reviewer uses the frontend to approve or reject the invoice. The approval sends an event back to the Orchestrator to resume execution.
5. **Fulfillment:** Once approved (or automatically cleared), the system registers the invoice in SAP (via the mock API) and marks it as `APPROVED` in Cosmos DB.
6. **Analytics:** A scheduled ETL pipeline extracts processed invoices from Cosmos DB, transforms them, and loads them into Snowflake for downstream analytics.

## Security & Access Control
- **Authentication:** Enforced via Microsoft Entra ID (OAuth2).
- **Secrets Management:** Handled natively by Azure Key Vault. The FastAPI and Azure Function apps authenticate to the Key Vault using Azure Managed Identities, ensuring no static secrets are stored in the codebase or environment variables.
- **Role-Based Access Control (RBAC):** Azure RBAC restricts which components can read/write to the Blob Storage and Cosmos DB.
