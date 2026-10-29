from __future__ import annotations

from app.config import Settings
from app.services.extraction.base import ExtractedLine, ExtractionError, ExtractionResult, Extractor
from app.services.extraction.llm_refine import refine_with_llm
from app.services.llm import LLMClient

__all__ = [
    "ExtractedLine",
    "ExtractionError",
    "ExtractionResult",
    "Extractor",
    "InvoiceExtractor",
    "build_extractor",
]


class InvoiceExtractor:
    """Primary extractor plus optional LLM clean-up when confidence is low."""

    def __init__(self, primary: Extractor, llm: LLMClient | None, refine_below: float) -> None:
        self.primary = primary
        self.llm = llm
        self.refine_below = refine_below
        self.name = primary.name

    def extract(self, data: bytes, content_type: str) -> ExtractionResult:
        result = self.primary.extract(data, content_type)
        if self.llm is not None and (result.confidence < self.refine_below or not result.line_items):
            result = refine_with_llm(result, self.llm, threshold=self.refine_below)
        return result


def build_extractor(settings: Settings, llm: LLMClient | None) -> InvoiceExtractor:
    primary: Extractor
    if settings.extractor == "azure_document_intelligence":
        from app.services.extraction.azure_di import AzureDocumentIntelligenceExtractor

        primary = AzureDocumentIntelligenceExtractor(settings)
    else:
        from app.services.extraction.pdf_text import PdfTextExtractor

        primary = PdfTextExtractor()
    return InvoiceExtractor(primary, llm, settings.llm_refine_below_confidence)
