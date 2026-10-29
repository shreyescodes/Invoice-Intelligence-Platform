"""Builds the long-lived service objects shared by the API and the worker."""

from __future__ import annotations

from functools import lru_cache

from app.config import Settings, get_settings
from app.services.anomaly import AnomalyModel, load_or_train
from app.services.erp import ErpClient
from app.services.extraction import build_extractor
from app.services.llm import LLMClient, build_llm_client
from app.services.pipeline import PipelineServices
from app.services.storage import DocumentStore, build_document_store


@lru_cache
def get_document_store() -> DocumentStore:
    return build_document_store(get_settings())


@lru_cache
def get_llm() -> LLMClient | None:
    return build_llm_client(get_settings())


@lru_cache
def get_anomaly_model() -> AnomalyModel:
    return load_or_train(get_settings().model_dir)


def build_pipeline_services(settings: Settings | None = None) -> PipelineServices:
    settings = settings or get_settings()
    return PipelineServices(
        settings=settings,
        store=get_document_store(),
        extractor=build_extractor(settings, get_llm()),
        erp=ErpClient.from_settings(settings),
        anomaly_model=get_anomaly_model(),
    )
