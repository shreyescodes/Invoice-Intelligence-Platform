"""FastAPI app entrypoint.

Run locally with: uvicorn src.api.main:app --reload
Or via docker compose: docker compose up api
"""

from fastapi import FastAPI

from src.api.routers import approvals, chat, invoices
from src.core.config import get_settings
from src.core.observability import configure_observability

settings = get_settings()

app = FastAPI(
    title="Invoice Intelligence Platform",
    description="AI-powered invoice processing, validation, and analytics",
    version="0.1.0",
)

configure_observability(app, settings)

app.include_router(invoices.router, prefix="/invoices", tags=["invoices"])
app.include_router(approvals.router, prefix="/approvals", tags=["approvals"])
app.include_router(chat.router, prefix="/chat", tags=["chat"])


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness/readiness probe. Extend this to check Cosmos DB and
    Blob Storage connectivity once those clients exist (phase 2) —
    a health check that only pings itself doesn't catch much."""
    return {"status": "ok", "environment": settings.environment}
