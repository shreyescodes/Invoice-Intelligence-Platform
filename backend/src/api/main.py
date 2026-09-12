"""FastAPI app entrypoint.

Run locally with: uvicorn src.api.main:app --reload
Or via docker compose: docker compose up api
"""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routers import approvals, chat, invoices
from src.core.config import get_settings
from src.core.observability import configure_observability
from src.core.security import require_user

settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.environment != "local":
        try:
            from src.core.security import azure_scheme
            await azure_scheme.openid_config.load_config()
            import logging
            logging.info("Successfully loaded Azure AD OpenID configuration keys.")
        except Exception as e:
            import logging
            logging.error(f"Failed to load Azure AD OpenID keys: {e}")
    yield

app = FastAPI(
    title="Invoice Intelligence Platform",
    description="AI-powered invoice processing, validation, and analytics",
    version="0.1.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

configure_observability(app, settings)

app.include_router(invoices.router, prefix="/invoices", tags=["invoices"], dependencies=[Depends(require_user)])
app.include_router(approvals.router, prefix="/approvals", tags=["approvals"], dependencies=[Depends(require_user)])
app.include_router(chat.router, prefix="/chat", tags=["chat"], dependencies=[Depends(require_user)])


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness/readiness probe. Extend this to check Cosmos DB and
    Blob Storage connectivity once those clients exist (phase 2) —
    a health check that only pings itself doesn't catch much."""
    return {"status": "ok", "environment": settings.environment}
