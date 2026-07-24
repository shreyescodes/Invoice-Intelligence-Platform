"""One client interface, two backends.

Ollama exposes an OpenAI-compatible /v1 endpoint, so the `openai`
Python SDK works against either target unchanged — only base_url and
auth differ. Build and test the entire pipeline against Ollama at
zero cost; flip LLM_PROVIDER=azure_openai for the final demo without
touching any calling code.

Azure OpenAI auth note: this uses an API key for simplicity. In a
real deployment, prefer Entra ID auth (azure-identity's
get_bearer_token_provider) so the Function App's Managed Identity
authenticates instead of a stored key — see security.py.
"""

from functools import lru_cache

from openai import AzureOpenAI, OpenAI

from src.core.config import Settings, get_settings


@lru_cache
def get_llm_client(settings: Settings | None = None) -> tuple[OpenAI | AzureOpenAI, str]:
    """Returns (client, model_name). Call get_llm_client(get_settings())."""
    settings = settings or get_settings()

    if settings.llm_provider == "azure_openai":
        client = AzureOpenAI(
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
        )
        return client, settings.azure_openai_deployment

    client = OpenAI(base_url=settings.ollama_base_url, api_key="ollama")  # key is unused
    return client, settings.ollama_model


@lru_cache
def get_async_llm_client(settings: Settings | None = None):
    from openai import AsyncAzureOpenAI, AsyncOpenAI
    settings = settings or get_settings()

    if settings.llm_provider == "azure_openai":
        client = AsyncAzureOpenAI(
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
        )
        return client, settings.azure_openai_deployment

    client = AsyncOpenAI(base_url=settings.ollama_base_url, api_key="ollama")
    return client, settings.ollama_model


def extract_json(prompt: str, *, settings: Settings | None = None) -> str:
    """Send a prompt, get back the model's raw text response.

    TODO(phase 3): use this for two things —
    1. Extraction cleanup: when Document Intelligence's confidence is
       low on a field, pass the raw OCR text + the field name and ask
       the model to re-extract it as JSON matching your Pydantic schema.
    2. The /chat endpoint's text-to-SQL: turn a finance user's
       question into a query against the Snowflake star schema.

    For structured output, prefer the client's response_format /
    tool-calling support over parsing free text where the model
    supports it — Ollama's OpenAI-compatible endpoint supports
    `response_format={"type": "json_object"}` for the models in the
    README's local-model table.
    """
    client, model = get_llm_client(settings)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content or ""
