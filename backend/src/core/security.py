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
    """Fetch a secret from Key Vault via Managed Identity.

    Locally, settings.key_vault_url is usually empty — fall back to
    .env values instead (see config.py). Only exercise this path once
    you've provisioned a real Key Vault (phase 6).
    """
    if not settings.key_vault_url:
        raise RuntimeError("KEY_VAULT_URL not set — are you running locally?")
    client = SecretClient(vault_url=settings.key_vault_url, credential=get_credential())
    return client.get_secret(secret_name).value  # type: ignore[return-value]


_bearer_scheme = HTTPBearer(auto_error=False)


async def require_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> dict:
    """FastAPI dependency: validate an Entra ID access token.

    TODO(phase 6): validate `creds.credentials` as a JWT — check
    signature against Entra ID's JWKS endpoint for your tenant, verify
    `aud` matches settings.oauth2_audience and `iss` matches your
    tenant's issuer, then return the decoded claims. Consider
    `fastapi-azure-auth` (wraps this) instead of hand-rolling it.

    Until this is implemented, every route using this dependency
    should be treated as UNAUTHENTICATED — don't deploy it as-is.
    """
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    raise NotImplementedError("Wire up Entra ID token validation here")
