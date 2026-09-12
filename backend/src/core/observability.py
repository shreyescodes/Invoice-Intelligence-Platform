"""Wires up OpenTelemetry once, at app startup.

The point of this file: the SAME instrumentation code runs whether
you're pointed at the local Grafana stack or Azure Application
Insights. Only the exporter changes, based on config — this is the
pattern real platform teams use so they aren't rewriting telemetry
code when they move from a laptop to production.

Traces: OTLP exporter -> OTEL_EXPORTER_OTLP_ENDPOINT (console locally
        unless you wire up a collector; Azure Monitor exporter in prod).
Metrics: Prometheus exporter -> scraped by the local Prometheus
        container at /metrics. In Azure, pair with Managed Prometheus
        or push via the Azure Monitor exporter instead.
"""

import logging

import structlog
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

from src.core.config import Settings


def configure_observability(app: FastAPI, settings: Settings) -> None:
    resource = Resource.create({SERVICE_NAME: settings.otel_service_name})

    # --- Tracing ---
    provider = TracerProvider(resource=resource)
    if settings.applicationinsights_connection_string:
        # Fix 5: Actually wire Application Insights instead of silently doing nothing.
        try:
            from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter
            azure_exporter = AzureMonitorTraceExporter(
                connection_string=settings.applicationinsights_connection_string
            )
            provider.add_span_processor(BatchSpanProcessor(azure_exporter))
            logging.info("Azure Monitor OpenTelemetry exporter configured.")
        except ImportError:
            logging.warning("azure-monitor-opentelemetry-exporter not installed; falling back to ConsoleSpanExporter.")
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    else:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app)

    # --- Structured logging (JSON, so it's queryable in Log Analytics /
    # Loki / whatever you point it at later) ---
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level.upper(), logging.INFO)
        ),
    )

    # --- Metrics: exposed at /metrics for Prometheus to scrape ---
    # Fix 2: /metrics is gated behind a simple API key check to prevent
    # unauthenticated enumeration of internal service telemetry.
    from fastapi import Depends, Response
    from fastapi.routing import APIRoute
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

    @app.get("/metrics", include_in_schema=False, dependencies=[Depends(require_user)])
    async def metrics() -> Response:
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
