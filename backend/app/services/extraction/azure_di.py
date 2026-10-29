"""Azure AI Document Intelligence (prebuilt-invoice model) adapter. Handles scanned PDFs and images."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.config import Settings
from app.services.extraction.base import ExtractedLine, ExtractionError, ExtractionResult


def _currency(field: Any) -> Decimal | None:
    value = getattr(field, "value_currency", None)
    amount = getattr(value, "amount", None)
    if amount is None:
        number = getattr(field, "value_number", None)
        return Decimal(str(number)) if number is not None else None
    return Decimal(str(amount)).quantize(Decimal("0.01"))


def _number(field: Any) -> Decimal | None:
    value = getattr(field, "value_number", None)
    return Decimal(str(value)) if value is not None else None


class AzureDocumentIntelligenceExtractor:
    name = "azure_document_intelligence"

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        if client is None:
            from azure.ai.documentintelligence import DocumentIntelligenceClient

            if not settings.azure_di_endpoint:
                raise ValueError("AZURE_DI_ENDPOINT is required for the Document Intelligence extractor")
            credential: Any
            if settings.azure_di_key:
                from azure.core.credentials import AzureKeyCredential

                credential = AzureKeyCredential(settings.azure_di_key.get_secret_value())
            else:
                from azure.identity import DefaultAzureCredential

                credential = DefaultAzureCredential()
            client = DocumentIntelligenceClient(settings.azure_di_endpoint, credential)
        self._client = client

    def extract(self, data: bytes, content_type: str) -> ExtractionResult:
        from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
        from azure.core.exceptions import HttpResponseError

        try:
            poller = self._client.begin_analyze_document("prebuilt-invoice", AnalyzeDocumentRequest(bytes_source=data))
            analysis = poller.result()
        except HttpResponseError as exc:
            if exc.status_code and 400 <= exc.status_code < 500 and exc.status_code != 429:
                raise ExtractionError(f"Document Intelligence rejected the document: {exc.message}") from exc
            raise  # throttling / 5xx: let the job retry
        return self.map_result(analysis)

    def map_result(self, analysis: Any) -> ExtractionResult:
        result = ExtractionResult(method=self.name, raw_text=getattr(analysis, "content", "") or "")
        documents = getattr(analysis, "documents", None) or []
        if not documents:
            result.warnings.append("Document Intelligence found no invoice in the document")
            return result
        fields: dict[str, Any] = documents[0].fields or {}

        def take(name: str, attr: str, target: str) -> None:
            field = fields.get(name)
            value = getattr(field, attr, None) if field is not None else None
            if value is not None:
                setattr(result, target, value)
                result.field_confidence[target] = float(getattr(field, "confidence", 0.0) or 0.0)

        take("VendorName", "value_string", "vendor_name")
        take("VendorTaxId", "value_string", "vendor_tax_id")
        take("InvoiceId", "value_string", "invoice_number")
        take("PurchaseOrder", "value_string", "po_number")
        take("InvoiceDate", "value_date", "invoice_date")
        take("DueDate", "value_date", "due_date")

        for name, target in (("SubTotal", "subtotal"), ("TotalTax", "tax_amount"), ("InvoiceTotal", "total_amount")):
            field = fields.get(name)
            amount = _currency(field) if field is not None else None
            if amount is not None:
                setattr(result, target, amount)
                result.field_confidence[target] = float(getattr(field, "confidence", 0.0) or 0.0)
                code = getattr(getattr(field, "value_currency", None), "currency_code", None)
                if code:
                    result.currency = code

        items_field = fields.get("Items")
        for item in getattr(items_field, "value_array", None) or []:
            obj = getattr(item, "value_object", None) or {}
            description = getattr(obj.get("Description"), "value_string", None) or ""
            amount = _currency(obj["Amount"]) if "Amount" in obj else None
            quantity = _number(obj["Quantity"]) if "Quantity" in obj else Decimal("1")
            unit_price = _currency(obj["UnitPrice"]) if "UnitPrice" in obj else None
            if amount is None:
                continue
            quantity = quantity or Decimal("1")
            if unit_price is None:
                unit_price = (amount / quantity).quantize(Decimal("0.01"))
            result.line_items.append(ExtractedLine(description.strip(), quantity, unit_price, amount))
        return result
