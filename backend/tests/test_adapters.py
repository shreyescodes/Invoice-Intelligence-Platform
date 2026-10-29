"""Adapters for optional cloud services, tested without network access."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace as NS

import pytest

from app.config import Settings
from app.services.extraction.azure_di import AzureDocumentIntelligenceExtractor
from app.services.llm import LLMError, parse_json_response


def money(amount: float, confidence: float = 0.9) -> NS:
    return NS(value_currency=NS(amount=amount, currency_code="INR"), confidence=confidence)


def test_document_intelligence_result_mapping(settings: Settings) -> None:
    analysis = NS(
        content="raw text",
        documents=[
            NS(
                fields={
                    "VendorName": NS(value_string="Kaveri Industrial Components Ltd", confidence=0.97),
                    "VendorTaxId": NS(value_string="29AABCK4321P1Z9", confidence=0.9),
                    "InvoiceId": NS(value_string="KIC/26-27/0412", confidence=0.99),
                    "PurchaseOrder": NS(value_string="4500012101", confidence=0.95),
                    "InvoiceDate": NS(value_date=date(2026, 10, 14), confidence=0.98),
                    "SubTotal": money(81500),
                    "TotalTax": money(14670),
                    "InvoiceTotal": money(96170, 0.99),
                    "Items": NS(
                        value_array=[
                            NS(
                                value_object={
                                    "Description": NS(value_string="Hydraulic hose"),
                                    "Quantity": NS(value_number=40),
                                    "UnitPrice": money(1450),
                                    "Amount": money(58000),
                                }
                            ),
                            NS(value_object={"Description": NS(value_string="Sensor"), "Amount": money(23500)}),
                        ]
                    ),
                }
            )
        ],
    )
    extractor = AzureDocumentIntelligenceExtractor(settings, client=object())
    result = extractor.map_result(analysis)
    assert result.vendor_name == "Kaveri Industrial Components Ltd"
    assert result.invoice_number == "KIC/26-27/0412"
    assert result.invoice_date == date(2026, 10, 14)
    assert result.total_amount == Decimal("96170.00")
    assert result.field_confidence["total_amount"] == 0.99
    assert [(li.quantity, li.unit_price) for li in result.line_items] == [
        (Decimal(40), Decimal("1450.00")),
        (Decimal(1), Decimal("23500.00")),  # quantity defaults to 1 when absent
    ]


def test_document_intelligence_without_documents(settings: Settings) -> None:
    result = AzureDocumentIntelligenceExtractor(settings, client=object()).map_result(NS(content="", documents=[]))
    assert result.confidence == 0
    assert result.warnings


@pytest.mark.parametrize(
    "reply",
    ['{"sql": "select 1"}', '```json\n{"sql": "select 1"}\n```', 'Sure! Here you go: {"sql": "select 1"} Thanks.'],
)
def test_parse_json_response_tolerates_wrapping(reply: str) -> None:
    assert parse_json_response(reply) == {"sql": "select 1"}


@pytest.mark.parametrize("reply", ["no json here", "[1, 2, 3]", "{broken"])
def test_parse_json_response_rejects_garbage(reply: str) -> None:
    with pytest.raises(LLMError):
        parse_json_response(reply)
