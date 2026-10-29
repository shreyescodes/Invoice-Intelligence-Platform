"""Structured logging and Prometheus metrics shared by the API and the worker."""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from prometheus_client import Counter, Gauge, Histogram

from app.config import Settings


def configure_logging(settings: Settings) -> None:
    """JSON logs in production (one event per line, queryable in Log Analytics / Loki), pretty logs locally."""
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]
    renderer: Any = (
        structlog.processors.JSONRenderer()
        if settings.log_format == "json"
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            renderer,
        ],
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # Access logs come from our own middleware, with request ids and user ids attached.
    logging.getLogger("uvicorn.access").disabled = True
    for noisy in ("httpx", "httpcore", "pdfminer", "azure", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.stdlib.get_logger(name)


# --- Metrics ----------------------------------------------------------------------------------------

HTTP_REQUESTS = Counter("iip_http_requests_total", "HTTP requests handled", ["method", "route", "status"])
HTTP_LATENCY = Histogram(
    "iip_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
INVOICES_UPLOADED = Counter("iip_invoices_uploaded_total", "Invoice documents accepted for processing")
PIPELINE_OUTCOMES = Counter("iip_pipeline_outcomes_total", "Result of automated invoice processing", ["outcome"])
PIPELINE_DURATION = Histogram(
    "iip_pipeline_duration_seconds",
    "Time to extract, validate and score one invoice",
    buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)
JOBS_COMPLETED = Counter("iip_jobs_completed_total", "Background jobs finished", ["kind", "result"])
JOB_QUEUE_DEPTH = Gauge("iip_job_queue_depth", "Jobs waiting to run", ["kind"])
ERP_REQUESTS = Counter("iip_erp_requests_total", "Calls to the ERP API", ["operation", "result"])
DECISIONS = Counter("iip_invoice_decisions_total", "Human approval decisions", ["decision"])
