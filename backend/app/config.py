"""Application settings, loaded from environment variables (and `.env` in development)."""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_DEFAULT_SECRET = "dev-only-insecure-secret-change-me-0123456789"  # noqa: S105


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Runtime ---------------------------------------------------------------
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_format: Literal["console", "json"] = "console"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    demo_mode: bool = Field(
        default=False, description="Expose demo account hints on the login screen. Never enable in production."
    )

    # --- Database --------------------------------------------------------------
    database_url: str = "sqlite:///./data/iip.db"
    # Optional separate connection for natural-language analytics. In docker-compose and Azure this
    # points at a role that only has SELECT on the analytics_* views.
    analytics_database_url: str | None = None
    db_pool_size: int = 5
    db_echo: bool = False

    # --- Auth ------------------------------------------------------------------
    jwt_secret: SecretStr = SecretStr(_INSECURE_DEFAULT_SECRET)
    jwt_algorithm: str = "HS256"
    jwt_ttl_minutes: int = 8 * 60
    login_max_failures: int = 5
    login_lockout_seconds: int = 300

    # --- Document storage ------------------------------------------------------
    storage_backend: Literal["local", "azure_blob"] = "local"
    storage_local_path: Path = Path("./data/documents")
    azure_storage_account_url: str | None = None  # e.g. https://<account>.blob.core.windows.net
    azure_storage_connection_string: SecretStr | None = None  # for Azurite / key-based auth
    azure_storage_container: str = "invoices"
    max_upload_bytes: int = 15 * 1024 * 1024

    # --- Extraction ------------------------------------------------------------
    extractor: Literal["pdf_text", "azure_document_intelligence"] = "pdf_text"
    azure_di_endpoint: str | None = None
    azure_di_key: SecretStr | None = None  # omit to use managed identity
    llm_refine_below_confidence: float = 0.75

    # --- LLM (OpenAI-compatible: OpenAI, Azure OpenAI, Ollama, vLLM...) ---------
    llm_provider: Literal["none", "openai", "azure_openai"] = "none"
    llm_base_url: str | None = None  # e.g. http://ollama:11434/v1
    llm_api_key: SecretStr | None = None
    llm_model: str = "gpt-4o-mini"
    azure_openai_endpoint: str | None = None
    azure_openai_api_version: str = "2024-10-21"
    llm_timeout_seconds: float = 30.0

    # --- ERP ----------------------------------------------------------------------
    # sap_mock: the SAP S/4HANA-shaped API of erp-mock. erpnext: a real ERPNext (v15/v16) site, where
    # ERP_API_KEY / ERP_API_SECRET are an API user's token pair.
    erp_provider: Literal["sap_mock", "erpnext"] = "sap_mock"
    erp_base_url: str = "http://localhost:8100"
    erp_api_key: SecretStr = SecretStr("dev-erp-key")
    erp_api_secret: SecretStr | None = None
    erpnext_company: str | None = None  # defaults to the site's only company
    erpnext_tax_account: str | None = None  # account head for the invoice's tax, e.g. "Input GST - AMI"
    erp_timeout_seconds: float = 10.0
    vendor_sync_interval_seconds: int = 600

    # --- Approval policy ---------------------------------------------------------
    auto_approve_limit: Decimal = Decimal("250000")
    approver_limit: Decimal = Decimal("1000000")
    anomaly_review_threshold: float = 0.5
    min_extraction_confidence: float = 0.8
    price_tolerance_pct: Decimal = Decimal("2.0")
    amount_tolerance: Decimal = Decimal("1.00")

    # --- Anomaly model -----------------------------------------------------------
    model_dir: Path = Path("./data/models")

    # --- Background worker -------------------------------------------------------
    worker_poll_interval_seconds: float = 1.0
    worker_max_attempts: int = 5
    worker_backoff_base_seconds: float = 5.0
    worker_lock_timeout_seconds: int = 300
    worker_metrics_port: int = 9101
    embedded_worker: bool = Field(
        default=False, description="Run the job worker inside the API process (single-process dev setups)."
    )

    # --- Natural-language analytics -------------------------------------------------
    ask_max_rows: int = 500
    ask_statement_timeout_ms: int = 5000

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def llm_enabled(self) -> bool:
        return self.llm_provider != "none"

    @model_validator(mode="after")
    def _check_production_safety(self) -> Settings:
        if self.is_production:
            if self.jwt_secret.get_secret_value() == _INSECURE_DEFAULT_SECRET:
                raise ValueError("JWT_SECRET must be set to a strong random value in production")
            if self.demo_mode:
                raise ValueError("DEMO_MODE must be disabled in production")
        if len(self.jwt_secret.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters")
        if self.erp_provider == "erpnext" and (self.erp_api_secret is None or not self.erpnext_tax_account):
            raise ValueError("ERP_PROVIDER=erpnext needs ERP_API_SECRET and ERPNEXT_TAX_ACCOUNT")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
