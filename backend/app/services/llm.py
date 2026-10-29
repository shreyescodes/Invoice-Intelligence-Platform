"""Thin wrapper over OpenAI-compatible chat APIs (OpenAI, Azure OpenAI, Ollama, vLLM...)."""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

from app.config import Settings


class LLMError(RuntimeError):
    pass


class LLMClient(Protocol):
    model: str

    def complete(self, system: str, user: str, *, json_mode: bool = False) -> str: ...


def parse_json_response(text: str) -> dict[str, Any]:
    """Models sometimes wrap JSON in markdown fences or add a sentence; take the first object."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise LLMError("model did not return JSON") from None
        try:
            value = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise LLMError("model returned malformed JSON") from exc
    if not isinstance(value, dict):
        raise LLMError("model returned JSON that is not an object")
    return value


class OpenAICompatibleClient:
    def __init__(self, settings: Settings) -> None:
        import openai

        self.model = settings.llm_model
        self._client: Any
        if settings.llm_provider == "azure_openai":
            if not settings.azure_openai_endpoint:
                raise ValueError("AZURE_OPENAI_ENDPOINT is required when LLM_PROVIDER=azure_openai")
            if settings.llm_api_key:
                self._client = openai.AzureOpenAI(
                    azure_endpoint=settings.azure_openai_endpoint,
                    api_version=settings.azure_openai_api_version,
                    api_key=settings.llm_api_key.get_secret_value(),
                    timeout=settings.llm_timeout_seconds,
                )
            else:
                from azure.identity import DefaultAzureCredential, get_bearer_token_provider

                token_provider = get_bearer_token_provider(
                    DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
                )
                self._client = openai.AzureOpenAI(
                    azure_endpoint=settings.azure_openai_endpoint,
                    api_version=settings.azure_openai_api_version,
                    azure_ad_token_provider=token_provider,
                    timeout=settings.llm_timeout_seconds,
                )
        else:
            api_key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else "not-needed"
            self._client = openai.OpenAI(
                base_url=settings.llm_base_url, api_key=api_key, timeout=settings.llm_timeout_seconds
            )

    def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        import openai

        kwargs: dict[str, Any] = {"response_format": {"type": "json_object"}} if json_mode else {}
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                temperature=0,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                **kwargs,
            )
        except openai.OpenAIError as exc:
            raise LLMError(f"LLM request failed: {exc}") from exc
        content = response.choices[0].message.content
        if not content:
            raise LLMError("LLM returned an empty response")
        return str(content)


def build_llm_client(settings: Settings) -> LLMClient | None:
    if not settings.llm_enabled:
        return None
    return OpenAICompatibleClient(settings)
