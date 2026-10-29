from __future__ import annotations

import io

from app.services.extraction.base import ExtractionError, ExtractionResult
from app.services.extraction.parsing import parse_invoice_text

MAX_PAGES = 20


class PdfTextExtractor:
    """Reads the embedded text layer and ruled tables of a PDF. No OCR: scanned documents come back
    empty and are routed to manual review (or use the Azure Document Intelligence extractor)."""

    name = "pdf_text"

    def __init__(self, default_currency: str = "INR") -> None:
        self.default_currency = default_currency

    def extract(self, data: bytes, content_type: str) -> ExtractionResult:
        if content_type != "application/pdf":
            result = ExtractionResult(method=self.name)
            result.warnings.append("Image documents need OCR; enable the Azure Document Intelligence extractor")
            return result

        import pdfplumber
        from pdfminer.pdfparser import PDFSyntaxError

        try:
            with pdfplumber.open(io.BytesIO(data)) as pdf:
                pages = pdf.pages[:MAX_PAGES]
                text = "\n".join(page.extract_text(x_tolerance=1.5, y_tolerance=3) or "" for page in pages)
                tables = [table for page in pages for table in page.extract_tables()]
        except (PDFSyntaxError, ValueError, KeyError) as exc:
            raise ExtractionError(f"Unreadable PDF: {exc}") from exc
        except Exception as exc:  # pdfminer raises a zoo of exception types on malformed input
            if exc.__class__.__module__.startswith(("pdfminer", "pdfplumber")):
                raise ExtractionError(f"Unreadable PDF: {exc}") from exc
            raise

        return parse_invoice_text(text, method=self.name, default_currency=self.default_currency, table_rows=tables)
