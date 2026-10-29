"""Natural-language questions over accounts-payable data.

A question is answered either from a catalogue of curated, reviewed queries or - when an LLM is
configured - by generated SQL. Generated SQL is never trusted:

1. it is parsed into an AST and must be a single SELECT (no DML/DDL, SELECT INTO, locking clauses),
2. it may only reference the `analytics_*` views,
3. dangerous functions (pg_sleep, pg_read_file, dblink, ...) are rejected,
4. a row limit is enforced, and
5. it runs in a READ ONLY transaction with a statement timeout, on a connection that in deployed
   environments belongs to a role with SELECT on the views and nothing else.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import sqlglot
from rapidfuzz import fuzz, process
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlglot import exp

from app.config import Settings
from app.db import build_engine, get_engine
from app.errors import DomainError
from app.observability import get_logger
from app.services.llm import LLMClient, LLMError, parse_json_response

log = get_logger(__name__)

ALLOWED_TABLES = frozenset({"analytics_invoices", "analytics_line_items", "analytics_checks", "analytics_vendors"})
_DENIED_FUNCTION_PREFIXES = (
    "pg_",
    "lo_",
    "dblink",
    "current_setting",
    "set_config",
    "query_to_xml",
    "copy",
    "load_extension",
    "readfile",
    "writefile",
    "sqlite_",
    "txid_",
    "inet_",
    "version",
)
_FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Command,
    exp.Into,
    exp.Lock,
    exp.Set,
    exp.Pragma,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
)

SCHEMA_DESCRIPTION = """\
analytics_invoices(invoice_id, invoice_number, status, vendor_id, vendor_name, po_number, invoice_date DATE,
  due_date DATE, currency, subtotal NUMERIC, tax_amount NUMERIC, total_amount NUMERIC, anomaly_score FLOAT 0-1,
  auto_approved BOOLEAN, extraction_confidence FLOAT 0-1, received_at TIMESTAMP, decided_at TIMESTAMP,
  posted_at TIMESTAMP)
  -- status is one of: received, processing, needs_review, approved, posted, rejected, failed.
  -- Spend = invoices with status 'approved' or 'posted'.
analytics_line_items(invoice_id, line_no, description, quantity, unit_price, amount, po_item)
analytics_checks(invoice_id, check_code, check_status, message)
  -- check_status is pass, warn or fail. check_code e.g. DUPLICATE, PRICE_MATCH, GOODS_RECEIPT, PO_MATCH,
  -- VENDOR_MATCH, LINE_TOTALS, INVOICE_TOTAL, TAX_RATE, DATES, REQUIRED_FIELDS.
analytics_vendors(vendor_id, vendor_name, city, payment_terms_days, is_active)"""


class UnsafeQueryError(DomainError):
    status_code = 422
    code = "unsafe_query"


class QuestionNotUnderstoodError(DomainError):
    status_code = 422
    code = "question_not_supported"


@dataclass(frozen=True, slots=True)
class CatalogQuery:
    question: str
    sql: dict[str, str]  # dialect -> SQL; "default" applies to every dialect
    chart: Literal["bar", "line", "table"] = "table"

    def for_dialect(self, dialect: str) -> str:
        return self.sql.get(dialect, self.sql["default"])


CATALOG: tuple[CatalogQuery, ...] = (
    CatalogQuery(
        "What is our total spend by vendor this year?",
        {
            "default": "SELECT vendor_name, COUNT(*) AS invoices, SUM(total_amount) AS total_spend "
            "FROM analytics_invoices WHERE status IN ('approved', 'posted') "
            "AND invoice_date >= DATE_TRUNC('year', CURRENT_DATE) GROUP BY vendor_name ORDER BY total_spend DESC",
            "sqlite": "SELECT vendor_name, COUNT(*) AS invoices, SUM(total_amount) AS total_spend "
            "FROM analytics_invoices WHERE status IN ('approved', 'posted') "
            "AND invoice_date >= strftime('%Y-01-01', 'now') GROUP BY vendor_name ORDER BY total_spend DESC",
        },
        chart="bar",
    ),
    CatalogQuery(
        "Show monthly invoice spend for the last 6 months",
        {
            "default": "SELECT TO_CHAR(DATE_TRUNC('month', invoice_date), 'YYYY-MM') AS month, COUNT(*) AS invoices, "
            "SUM(total_amount) AS total_spend FROM analytics_invoices WHERE status IN ('approved', 'posted') "
            "AND invoice_date >= DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '5 months' GROUP BY 1 ORDER BY 1",
            "sqlite": "SELECT strftime('%Y-%m', invoice_date) AS month, COUNT(*) AS invoices, "
            "SUM(total_amount) AS total_spend FROM analytics_invoices WHERE status IN ('approved', 'posted') "
            "AND invoice_date >= date('now', 'start of month', '-5 months') GROUP BY 1 ORDER BY 1",
        },
        chart="line",
    ),
    CatalogQuery(
        "Which invoices are waiting for review?",
        {
            "default": "SELECT invoice_number, vendor_name, total_amount, invoice_date, "
            "ROUND(CAST(anomaly_score AS NUMERIC), 2) AS anomaly_score FROM analytics_invoices "
            "WHERE status = 'needs_review' ORDER BY received_at",
        },
    ),
    CatalogQuery(
        "What are the most common exceptions?",
        {
            "default": "SELECT c.check_code, COUNT(*) AS occurrences, COUNT(DISTINCT c.invoice_id) AS invoices "
            "FROM analytics_checks c WHERE c.check_status IN ('fail', 'warn') "
            "GROUP BY c.check_code ORDER BY occurrences DESC",
        },
        chart="bar",
    ),
    CatalogQuery(
        "What is the straight-through processing rate by vendor?",
        {
            "default": "SELECT vendor_name, COUNT(*) AS approved_invoices, "
            "SUM(CASE WHEN auto_approved THEN 1 ELSE 0 END) AS auto_approved, "
            "ROUND(100.0 * SUM(CASE WHEN auto_approved THEN 1 ELSE 0 END) / COUNT(*), 1) AS stp_rate_pct "
            "FROM analytics_invoices WHERE status IN ('approved', 'posted') "
            "GROUP BY vendor_name ORDER BY stp_rate_pct DESC",
        },
        chart="bar",
    ),
    CatalogQuery(
        "Top 10 largest invoices this quarter",
        {
            "default": "SELECT invoice_number, vendor_name, invoice_date, total_amount, status "
            "FROM analytics_invoices WHERE invoice_date >= DATE_TRUNC('quarter', CURRENT_DATE) "
            "ORDER BY total_amount DESC LIMIT 10",
            "sqlite": "SELECT invoice_number, vendor_name, invoice_date, total_amount, status "
            "FROM analytics_invoices WHERE invoice_date >= date('now', 'start of month', "
            "printf('-%d months', (CAST(strftime('%m', 'now') AS INTEGER) - 1) % 3)) "
            "ORDER BY total_amount DESC LIMIT 10",
        },
    ),
    CatalogQuery(
        "How long does it take from receipt to ERP posting, by vendor?",
        {
            "default": "SELECT vendor_name, COUNT(*) AS posted_invoices, "
            "ROUND(CAST(AVG(EXTRACT(EPOCH FROM (posted_at - received_at)) / 3600) AS NUMERIC), 1) AS avg_hours "
            "FROM analytics_invoices WHERE posted_at IS NOT NULL GROUP BY vendor_name ORDER BY avg_hours DESC",
            "sqlite": "SELECT vendor_name, COUNT(*) AS posted_invoices, "
            "ROUND(AVG((julianday(posted_at) - julianday(received_at)) * 24), 1) AS avg_hours "
            "FROM analytics_invoices WHERE posted_at IS NOT NULL GROUP BY vendor_name ORDER BY avg_hours DESC",
        },
        chart="bar",
    ),
)

_SQLGLOT_DIALECTS = {"postgresql": "postgres", "sqlite": "sqlite"}


def _limit_value(select: exp.Select) -> int | None:
    limit = select.args.get("limit")
    if limit is None:
        return None
    literal = limit.args.get("expression")
    if isinstance(literal, exp.Literal) and not literal.is_string:
        try:
            return int(literal.this)
        except ValueError:
            return None
    return None


def guard_sql(sql: str, dialect: str, max_rows: int) -> str:
    """Validate an untrusted query and return a normalised, row-limited version of it."""
    read = _SQLGLOT_DIALECTS.get(dialect, dialect)
    try:
        statements = [s for s in sqlglot.parse(sql, read=read) if s is not None]
    except sqlglot.errors.SqlglotError as exc:
        raise UnsafeQueryError(f"Query could not be parsed: {exc}") from exc
    if len(statements) != 1:
        raise UnsafeQueryError("Exactly one SQL statement is allowed")
    statement = statements[0]
    if not isinstance(statement, exp.Query):
        raise UnsafeQueryError("Only SELECT queries are allowed")
    for node in statement.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise UnsafeQueryError(f"{type(node).__name__.upper()} is not allowed")

    cte_names = {cte.alias_or_name.lower() for cte in statement.find_all(exp.CTE)}
    for table in statement.find_all(exp.Table):
        name = table.name.lower()
        if table.args.get("db") is not None or table.args.get("catalog") is not None:
            raise UnsafeQueryError("Schema-qualified table names are not allowed")
        if name and name not in ALLOWED_TABLES and name not in cte_names:
            raise UnsafeQueryError(f"Table '{table.name}' is not available; use the analytics_* views")
    for function in statement.find_all(exp.Func):
        names = {function.sql_name().lower()}
        if isinstance(function, exp.Anonymous):
            names.add(str(function.name).lower())
        if any(n.startswith(_DENIED_FUNCTION_PREFIXES) for n in names):
            raise UnsafeQueryError(f"Function '{next(iter(names))}' is not allowed")

    if isinstance(statement, exp.Select):
        current = _limit_value(statement)
        statement = statement.limit(min(current, max_rows) if current else max_rows)
    else:
        statement = exp.select("*").from_(statement.subquery("q")).limit(max_rows)
    return statement.sql(dialect=read)


# --- Execution ------------------------------------------------------------------------------------


def _readonly_sqlite_engine(url: str, settings: Settings) -> Engine:
    """A connection that SQLite itself refuses to write through (mode=ro + query_only)."""
    database = make_url(url).database or ""
    uri = Path(database).resolve().as_uri() + "?mode=ro"

    def connect() -> sqlite3.Connection:
        connection = sqlite3.connect(uri, uri=True, check_same_thread=False)
        connection.execute("PRAGMA query_only = ON")
        return connection

    return create_engine("sqlite://", creator=connect, echo=settings.db_echo)


def analytics_engine(settings: Settings) -> Engine:
    return _analytics_engine_for(settings.analytics_database_url or settings.database_url)


@lru_cache
def _analytics_engine_for(url: str) -> Engine:
    from app.config import get_settings

    settings = get_settings()
    if make_url(url).get_backend_name() == "sqlite":
        return _readonly_sqlite_engine(url, settings)
    if url == settings.database_url:
        return get_engine()
    return build_engine(url, settings)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    return value


def execute_readonly(engine: Engine, sql: str, settings: Settings) -> tuple[list[str], list[list[Any]]]:
    with engine.connect() as conn:
        if engine.dialect.name == "postgresql":
            conn.exec_driver_sql("SET TRANSACTION READ ONLY")
            conn.exec_driver_sql(f"SET LOCAL statement_timeout = {int(settings.ask_statement_timeout_ms)}")
        result = conn.execute(text(sql))
        columns = list(result.keys())
        rows = [[_jsonable(v) for v in row] for row in result.fetchmany(settings.ask_max_rows)]
        conn.rollback()
    return columns, rows


# --- Orchestration --------------------------------------------------------------------------------


@dataclass(slots=True)
class AskResult:
    question: str
    sql: str
    columns: list[str]
    rows: list[list[Any]]
    source: Literal["catalog", "llm"]
    answer: str
    chart: Literal["bar", "line", "table"] = "table"
    model: str | None = None
    truncated: bool = False
    notes: list[str] = field(default_factory=list)


SQL_SYSTEM_PROMPT = """You are a senior analyst writing SQL for an accounts-payable data mart.
Write ONE read-only {dialect} SELECT query that answers the user's question.
Only these views exist:
{schema}
Rules: never modify data; only reference the views above; give every computed column a snake_case alias;
order results meaningfully; return at most 100 rows unless the user asks for more; amounts are in INR;
today is {today}. Use case-insensitive matching (LOWER(...) LIKE LOWER('%...%')) for vendor names.
Respond with JSON only: {{"sql": "<query>", "chart": "bar" | "line" | "table"}}
Use "line" for time series, "bar" for comparisons across up to 15 categories, otherwise "table"."""

ANSWER_SYSTEM_PROMPT = """You summarise query results for a finance team in one or two plain sentences.
State the key numbers (format INR amounts with the Indian digit grouping, e.g. 12,34,567).
Do not speculate beyond the data. If there are no rows, say that nothing matched."""


def match_catalog(question: str, threshold: float = 82) -> CatalogQuery | None:
    best = process.extractOne(
        question, {i: c.question for i, c in enumerate(CATALOG)}, scorer=fuzz.token_set_ratio, score_cutoff=threshold
    )
    return CATALOG[best[2]] if best else None


def _summarise_catalog(query: CatalogQuery, columns: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return "No invoices matched."
    return f"{len(rows)} row{'s' if len(rows) != 1 else ''} from the curated query “{query.question}”."


def ask(question: str, settings: Settings, llm: LLMClient | None, engine: Engine | None = None) -> AskResult:
    question = question.strip()
    engine = engine or analytics_engine(settings)
    dialect = engine.dialect.name
    curated = match_catalog(question, threshold=97 if llm is not None else 82)

    if curated is not None:
        sql = guard_sql(curated.for_dialect(dialect), dialect, settings.ask_max_rows)
        columns, rows = execute_readonly(engine, sql, settings)
        return AskResult(
            question,
            sql,
            columns,
            rows,
            "catalog",
            _summarise_catalog(curated, columns, rows),
            chart=curated.chart,
            truncated=len(rows) >= settings.ask_max_rows,
        )

    if llm is None:
        raise QuestionNotUnderstoodError(
            "Free-form questions need an LLM provider (set LLM_PROVIDER). Try one of the suggested questions.",
            suggestions=[c.question for c in CATALOG],
        )

    prompt = SQL_SYSTEM_PROMPT.format(
        dialect="PostgreSQL" if dialect == "postgresql" else "SQLite",
        schema=SCHEMA_DESCRIPTION,
        today=date.today().isoformat(),  # noqa: DTZ011 - calendar date for the prompt
    )
    try:
        reply = parse_json_response(llm.complete(prompt, question, json_mode=True))
    except LLMError as exc:
        raise QuestionNotUnderstoodError(f"The language model could not answer: {exc}") from exc
    raw_sql = str(reply.get("sql") or "").strip()
    if not raw_sql:
        raise QuestionNotUnderstoodError("The language model did not produce a query for that question")
    chart: Literal["bar", "line", "table"] = (
        reply["chart"] if reply.get("chart") in ("bar", "line", "table") else "table"
    )

    sql = guard_sql(raw_sql, dialect, settings.ask_max_rows)
    try:
        columns, rows = execute_readonly(engine, sql, settings)
    except Exception as exc:
        log.warning("ask_query_failed", error=str(exc), sql=sql)
        raise QuestionNotUnderstoodError(
            "The generated query failed to run; try rephrasing the question", sql=sql
        ) from exc

    try:
        preview = json.dumps({"columns": columns, "rows": rows[:25]}, default=str)
        answer = llm.complete(ANSWER_SYSTEM_PROMPT, f"Question: {question}\nResult: {preview}").strip()
    except LLMError:
        answer = f"{len(rows)} rows returned."
    log.info("ask_answered", source="llm", model=llm.model, rows=len(rows))
    return AskResult(
        question,
        sql,
        columns,
        rows,
        "llm",
        answer,
        chart=chart,
        model=llm.model,
        truncated=len(rows) >= settings.ask_max_rows,
    )
