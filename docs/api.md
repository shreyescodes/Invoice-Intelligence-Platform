# API Reference

The backend of the Invoice Intelligence Platform exposes a REST API via FastAPI. Below are the core routers and endpoints. The interactive Swagger UI is available at `http://localhost:8000/docs`.

## 1. Invoices (`/invoices`)

Manages the ingestion, retrieval, and status updates of invoices.

- **`POST /invoices/upload`**
  Uploads a raw PDF invoice.
  - **Payload:** `multipart/form-data` containing the file.
  - **Process:** Saves the file to Blob Storage and initializes a `PENDING` record in Cosmos DB. Returns the generated `invoice_id`.

- **`GET /invoices`**
  Retrieves a paginated list of all invoices.
  - **Response:** Array of `InvoiceRecord` objects.

- **`GET /invoices/{invoice_id}`**
  Fetches the complete details and extracted items of a specific invoice.

- **`POST /invoices/{invoice_id}/status`**
  Updates the status of an invoice (e.g., transitioning from `NEEDS_REVIEW` to `APPROVED`).
  - **Process:** Modifies the record in Cosmos DB. Due to partition key immutability, this operation deletes the old record and creates a new one.

## 2. Approvals (`/approvals`)

Handles the human-in-the-loop review process for anomalous invoices.

- **`GET /approvals/pending`**
  Fetches all invoices currently marked as `NEEDS_REVIEW`.
  
- **`POST /approvals/{invoice_id}/approve`**
  Approves a pending invoice.
  - **Process:** Triggers an external event back to the waiting Durable Functions Orchestrator to resume the workflow.

- **`POST /approvals/{invoice_id}/reject`**
  Rejects a pending invoice.

## 3. Chat / Analytics (`/chat`)

Enables natural language querying of the Snowflake analytical data.

- **`POST /chat/query`**
  Submits a natural language question.
  - **Payload:** JSON with `{ "query": "string" }`
  - **Process:** Uses an LLM to translate the question into a valid Snowflake SQL query, executes the query against the data warehouse, and returns both the SQL and the result set.

## Schema Highlights

### `InvoiceRecord` (Cosmos DB Document)
```json
{
  "id": "uuid",
  "vendor_id": "string",
  "status": "RECEIVED | PROCESSING | NEEDS_REVIEW | APPROVED | REJECTED",
  "blob_path": "string",
  "subtotal": 100.0,
  "tax_amount": 5.0,
  "total_amount": 105.0,
  "anomaly_score": 0.05,
  "anomaly_reason": "string",
  "line_items": [...]
}
```
