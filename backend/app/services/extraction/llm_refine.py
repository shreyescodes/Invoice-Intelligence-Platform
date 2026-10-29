"""Fills in fields the rule-based parser was unsure about, using an LLM over the document text."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

from app.observability import get_logger
from app.services.extraction.base import ExtractedLine, ExtractionResult
from app.services.extraction.parsing import cross_check, parse_date
from app.services.llm import LLMClient, LLMError, parse_json_response

log = get_logger(__name__)

LLM_FIELD_CONFIDENCE = 0.85
MAX_PROMPT_CHARS = 12_000

SYSTEM_PROMPT = """You extract data from supplier invoices for an accounts-payable system.
Return a single JSON object with exactly these keys (use null when a value is not present):
vendor_name, vendor_tax_id, invoice_number, po_number, invoice_date (YYYY-MM-DD), due_date (YYYY-MM-DD),
currency (ISO 4217), subtotal, tax_amount, total_amount (numbers, no thousands separators),
line_items (array of {description, quantity, unit_price, amount}).
The vendor is the party issuing the invoice, never the "Bill To" customer.
Copy values exactly as printed. Never guess or compute values that are not on the document."""


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except InvalidOperation:
        return None


def refine_with_llm(result: ExtractionResult, llm: LLMClient, threshold: float) -> ExtractionResult:
    if not result.raw_text.strip():
        return result
    weak = [
        name
        for name in (
            "vendor_name",
            "vendor_tax_id",
            "invoice_number",
            "po_number",
            "invoice_date",
            "due_date",
            "subtotal",
            "tax_amount",
            "total_amount",
        )
        if result.field_confidence.get(name, 0.0) < threshold
    ]
    if not weak and result.line_items:
        return result

    try:
        reply = llm.complete(SYSTEM_PROMPT, result.raw_text[:MAX_PROMPT_CHARS], json_mode=True)
        data = parse_json_response(reply)
    except LLMError as exc:
        log.warning("llm_refine_failed", error=str(exc))
        result.warnings.append("LLM refinement unavailable")
        return result

    converters: dict[str, Any] = {
        "invoice_date": lambda v: parse_date(str(v)),
        "due_date": lambda v: parse_date(str(v)),
        "subtotal": _decimal,
        "tax_amount": _decimal,
        "total_amount": _decimal,
    }
    filled: list[str] = []
    for name in weak:
        raw = data.get(name)
        if raw in (None, ""):
            continue
        value = converters.get(name, lambda v: str(v).strip())(raw)
        if value is not None:
            setattr(result, name, value)
            result.field_confidence[name] = LLM_FIELD_CONFIDENCE
            filled.append(name)

    if not result.line_items and isinstance(data.get("line_items"), list):
        for item in data["line_items"]:
            if not isinstance(item, dict):
                continue
            qty, price, amount = (_decimal(item.get(k)) for k in ("quantity", "unit_price", "amount"))
            if amount is not None and item.get("description"):
                qty = qty if qty and qty > 0 else Decimal("1")
                price = price if price is not None else (amount / qty).quantize(Decimal("0.01"))
                result.line_items.append(ExtractedLine(str(item["description"]), qty, price, amount))
        if result.line_items:
            filled.append("line_items")

    if filled:
        result.method = f"{result.method}+llm"
        cross_check(result)
        log.info("llm_refined_fields", fields=json.dumps(filled), model=llm.model)
    return result
