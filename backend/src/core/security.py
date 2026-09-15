"""Auth building blocks.

Two separate concerns live here, don't conflate them:

1. Service-to-service auth (this app calling Key Vault, Cosmos DB,
   Azure OpenAI): use DefaultAzureCredential. Locally it falls back to
   your `az login` session; in Azure it picks up the Function App's
   system-assigned Managed Identity automatically. Same code, zero
   secrets, in both places. That's the whole point of Managed Identity.

2. User-facing auth (a finance user hitting the FastAPI endpoints):
   OAuth2 bearer tokens issued by Entra ID (Azure AD), validated on
   every request. This is a stub — fill in with `fastapi-azure-auth`
   or MSAL token validation once you have an App Registration set up.
   Do this in phase 6, after the core pipeline works end to end.

Workload Identity Federation (GitLab CI -> Azure, no stored secrets)
is a CI-side concern, not app code — see .gitlab-ci.yml for that.
"""

from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.core.config import Settings, get_settings

_credential: DefaultAzureCredential | None = None


def get_credential() -> DefaultAzureCredential:
    """Singleton DefaultAzureCredential — expensive to construct repeatedly."""
    global _credential
    if _credential is None:
        _credential = DefaultAzureCredential()
    return _credential


def get_secret(secret_name: str, settings: Settings) -> str:
    """Fetch a secret from Key Vault via Managed Identity."""
    if not settings.key_vault_url:
        raise RuntimeError("KEY_VAULT_URL not set — are you running locally?")
    client = SecretClient(vault_url=settings.key_vault_url, credential=get_credential())
    return client.get_secret(secret_name).value  # type: ignore[return-value]


_bearer_scheme = HTTPBearer(auto_error=False)

# Setup fastapi-azure-auth scheme
settings_cache = get_settings()
azure_scheme = None
if settings_cache.environment != "local":
    try:
        from fastapi_azure_auth import SingleTenantAzureAuthorizationCodeBearer  # type: ignore[import-not-found,attr-defined]
        if settings_cache.azure_client_id and settings_cache.azure_tenant_id:
            azure_scheme = SingleTenantAzureAuthorizationCodeBearer(
                app_client_id=settings_cache.azure_client_id,
                tenant_id=settings_cache.azure_tenant_id,
                scopes={f"api://{settings_cache.azure_client_id}/user_impersonation": "user_impersonation"}
            )
    except ImportError:
        pass


async def require_user(
    settings: Settings = Depends(get_settings),
    token: dict | HTTPAuthorizationCredentials | None = Depends(azure_scheme) if azure_scheme else Depends(_bearer_scheme),
) -> dict:
    """FastAPI dependency: validate an Entra ID access token."""
    if settings.environment == "local":
        return {"sub": "local-dev-user", "roles": ["Admin"]}

    if azure_scheme is None:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, 
            "Azure Auth not configured. Verify fastapi-azure-auth is installed and AZURE_CLIENT_ID/AZURE_TENANT_ID are set."
        )

    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
        
    return token if isinstance(token, dict) else {"sub": "unknown"}
