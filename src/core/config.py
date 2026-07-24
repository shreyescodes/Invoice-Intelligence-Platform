"""Central app configuration.

Loaded from environment variables (.env locally, real env vars / Key
Vault references in Azure). Nothing here should read a secret directly
in production — see security.py for how Managed Identity resolves
Key Vault secrets at runtime instead of baking them into env vars.
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["local", "dev", "prod"] = "local"
    log_level: str = "INFO"

    # Storage
    azure_storage_connection_string: str
    blob_container_raw_invoices: str = "raw-invoices"

    # Cosmos DB
    cosmos_endpoint: str
    cosmos_key: str
    cosmos_database: str = "invoice_platform"
    cosmos_container_invoices: str = "invoices"
    cosmos_container_audit: str = "audit-log"

    # Document Intelligence
    document_intelligence_endpoint: str = ""
    document_intelligence_key: str = ""

    # LLM
    llm_provider: Literal["ollama", "azure_openai"] = "ollama"
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "qwen2.5:14b"
    azure_openai_endpoint: str = ""
    azure_openai_deployment: str = ""
    azure_openai_api_version: str = "2024-10-21"
    azure_openai_api_key: str = ""

    # Mock SAP
    mock_sap_base_url: str = "http://localhost:8100"

    # Analytics warehouse
    snowflake_account: str = ""
    snowflake_user: str = ""
    snowflake_password: str = ""
    snowflake_warehouse: str = ""
    snowflake_database: str = ""
    local_analytics_dsn: str = "postgresql://postgres:postgres@localhost:5433/analytics"

    # Key Vault
    key_vault_url: str = ""

    # Auth
    azure_tenant_id: str = ""
    azure_client_id: str = ""
    oauth2_audience: str = ""

    # Observability
    otel_service_name: str = "invoice-platform-api"
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    applicationinsights_connection_string: str = ""

    # MLflow
    mlflow_tracking_uri: str = "http://localhost:5001"

    @property
    def using_real_snowflake(self) -> bool:
        return bool(self.snowflake_account)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
