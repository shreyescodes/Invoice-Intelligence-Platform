from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest

from app.demo.invoice_pdf import Line, amount_in_words, inr
from app.services.extraction import ExtractionError, InvoiceExtractor
from app.services.extraction.base import ExtractionResult
from app.services.extraction.llm_refine import refine_with_llm
from app.services.extraction.parsing import detect_currency, parse_amount, parse_date, parse_invoice_text
from app.services.extraction.pdf_text import PdfTextExtractor
from tests.conftest import kaveri_invoice
from tests.fakes import FakeLLM


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("INR 1,23,456.50", Decimal("123456.50")),
        ("Rs. 4,500", Decimal("4500")),
        ("$1,234.99", Decimal("1234.99")),
        ("12000", Decimal("12000")),
        ("no number", None),
    ],
)
def test_parse_amount(text: str, expected: Decimal | None) -> None:
    assert parse_amount(text) == expected


@pytest.mark.parametrize(
    "text",
    ["14 Oct 2026", "14-Oct-2026", "2026-10-14", "14/10/2026", "14.10.2026", "October 14, 2026", "14th Oct 2026"],
)
def test_parse_date_formats(text: str) -> None:
    assert parse_date(text) == date(2026, 10, 14)


def test_detect_currency() -> None:
    assert detect_currency("Total INR 1,000.00", "USD") == "INR"
    assert detect_currency("Amount due $ 50.00", "INR") == "USD"
    assert detect_currency("nothing here", "INR") == "INR"


@pytest.mark.parametrize("style", ["classic", "modern", "compact"])
def test_pdf_layouts_are_extracted_completely(style: str) -> None:
    pdf = kaveri_invoice(style=style, invoice_date=date(2026, 10, 14))
    result = PdfTextExtractor().extract(pdf, "application/pdf")

    assert result.vendor_name is not None and result.vendor_name.lower().startswith("kaveri industrial")
    assert result.vendor_tax_id == "29AABCK4321P1Z9"  # the vendor's, not the buyer's GSTIN
    assert result.invoice_number == "KIC/26-27/0412"
    assert result.po_number == "4500012101"
    assert result.invoice_date == date(2026, 10, 14)
    assert result.due_date == date(2026, 11, 28)
    assert result.currency == "INR"
    assert result.subtotal == Decimal("81500.00")
    assert result.tax_amount == Decimal("14670.00")
    assert result.total_amount == Decimal("96170.00")
    assert [(li.description, li.quantity, li.amount) for li in result.line_items] == [
        ("Hydraulic hose assembly 3/4 in", Decimal(40), Decimal("58000.00")),
        ("Inductive proximity sensor M18", Decimal(10), Decimal("23500.00")),
    ]
    assert result.confidence > 0.85


def test_years_in_descriptions_are_not_mistaken_for_hsn_codes() -> None:
    lines = [Line("Managed Kubernetes cluster - Oct 2026", Decimal(1), Decimal("48000.00"))]
    result = PdfTextExtractor().extract(kaveri_invoice(style="modern", lines=lines), "application/pdf")
    assert result.line_items[0].description == "Managed Kubernetes cluster - Oct 2026"


def test_inconsistent_totals_are_extracted_as_printed() -> None:
    pdf = kaveri_invoice(subtotal_override=Decimal("81700.00"))
    result = PdfTextExtractor().extract(pdf, "application/pdf")
    assert result.subtotal == Decimal("81700.00")
    assert sum(li.amount for li in result.line_items) == Decimal("81500.00")


def test_tax_words_in_line_items_do_not_count_as_tax() -> None:
    text = "\n".join(
        [
            "Advisory Partners LLP",
            "GSTIN: 27AABFA1234B1Z5",
            "Invoice No: AP-77",
            "Invoice Date: 01/10/2026",
            "Bill To: Acme",
            "Description Qty Rate Amount",
            "Tax advisory services 1 50,000.00 50,000.00",
            "Subtotal 50,000.00",
            "IGST @ 18% 9,000.00",
            "Total INR 59,000.00",
        ]
    )
    result = parse_invoice_text(text, method="test")
    assert result.tax_amount == Decimal("9000.00")
    assert result.total_amount == Decimal("59000.00")
    assert result.line_items[0].description == "Tax advisory services"


def test_images_are_not_ocrd_by_the_text_extractor() -> None:
    result = PdfTextExtractor().extract(b"\x89PNG\r\n\x1a\n...", "image/png")
    assert result.confidence == 0
    assert result.warnings


def test_corrupt_pdf_raises() -> None:
    with pytest.raises(ExtractionError):
        PdfTextExtractor().extract(b"%PDF-1.7 this is not really a pdf", "application/pdf")


def test_llm_fills_only_low_confidence_fields() -> None:
    weak = ExtractionResult(method="pdf_text", raw_text="Some vendor invoice text")
    weak.invoice_number, weak.field_confidence["invoice_number"] = "INV-1", 0.95
    llm = FakeLLM(
        [
            json.dumps(
                {
                    "vendor_name": "Some Vendor Pvt Ltd",
                    "invoice_number": "WRONG",
                    "invoice_date": "2026-10-01",
                    "subtotal": "1000",
                    "tax_amount": "180",
                    "total_amount": "1,180.00",
                    "line_items": [{"description": "Widget", "quantity": 2, "unit_price": 500, "amount": 1000}],
                }
            )
        ]
    )
    result = refine_with_llm(weak, llm, threshold=0.8)
    assert result.invoice_number == "INV-1"  # confident field kept
    assert result.vendor_name == "Some Vendor Pvt Ltd"
    assert result.total_amount == Decimal("1180.00")
    assert result.method == "pdf_text+llm"
    assert len(result.line_items) == 1
    assert result.field_confidence["total_amount"] >= 0.85


def test_llm_failure_keeps_rule_based_result() -> None:
    weak = ExtractionResult(method="pdf_text", raw_text="text")
    result = refine_with_llm(weak, FakeLLM(["not json at all"]), threshold=0.8)
    assert result.method == "pdf_text"
    assert "LLM refinement unavailable" in result.warnings


def test_extractor_skips_llm_when_confident() -> None:
    llm = FakeLLM([])
    extractor = InvoiceExtractor(PdfTextExtractor(), llm, refine_below=0.75)
    result = extractor.extract(kaveri_invoice(), "application/pdf")
    assert result.method == "pdf_text"
    assert llm.calls == []


def test_indian_number_helpers() -> None:
    assert inr(Decimal("1234567.5")) == "12,34,567.50"
    assert inr(Decimal("999")) == "999.00"
    assert amount_in_words(Decimal("96170")) == "Indian Rupees Ninety Six Thousand One Hundred Seventy Only"
