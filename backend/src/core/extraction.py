"""Azure AI Document Intelligence Integration."""
import logging
from datetime import datetime
from decimal import Decimal

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
from azure.core.credentials import AzureKeyCredential

from src.api.schemas.invoice import ExtractedInvoice
from src.core.config import get_settings

logger = logging.getLogger(__name__)

def get_doc_intel_client() -> DocumentIntelligenceClient:
    settings = get_settings()
    
    # This will fail at runtime if the endpoint/key are not set in .env
    if not settings.document_intelligence_endpoint or not settings.document_intelligence_key:
        raise ValueError("DOCUMENT_INTELLIGENCE_ENDPOINT and DOCUMENT_INTELLIGENCE_KEY must be set in .env")
        
    return DocumentIntelligenceClient(
        endpoint=settings.document_intelligence_endpoint,
        credential=AzureKeyCredential(settings.document_intelligence_key)
    )

def extract_invoice_data(blob_url: str) -> ExtractedInvoice:
    """Extract invoice data using pre-built invoice model."""
    logger.info(f"Extracting invoice data from {blob_url}")
    client = get_doc_intel_client()
    
    poller = client.begin_analyze_document(
        "prebuilt-invoice", 
        AnalyzeDocumentRequest(url_source=blob_url)
    )
    
    result = poller.result()
    
    vendor_name = "Unknown Vendor"
    invoice_number = "UNKNOWN"
    invoice_date = datetime.utcnow().date()
    subtotal = Decimal("0.00")
    total_amount = Decimal("0.00")
    tax_amount = Decimal("0.00")
    confidence = 0.0
    
    if result.documents and len(result.documents) > 0:
        doc = result.documents[0]
        fields = doc.fields
        
        if fields:
            if "VendorName" in fields and fields["VendorName"].value_string:
                vendor_name = fields["VendorName"].value_string
                confidence += fields["VendorName"].confidence or 0
                
            if "InvoiceId" in fields and fields["InvoiceId"].value_string:
                invoice_number = fields["InvoiceId"].value_string
                
            if "InvoiceDate" in fields and fields["InvoiceDate"].value_date:
                invoice_date = fields["InvoiceDate"].value_date
                    
            if "SubTotal" in fields and getattr(fields["SubTotal"], "value_currency", None):
                subtotal = Decimal(str(fields["SubTotal"].value_currency.amount))
                    
            if "TotalTax" in fields and getattr(fields["TotalTax"], "value_currency", None):
                tax_amount = Decimal(str(fields["TotalTax"].value_currency.amount))
                    
            if "InvoiceTotal" in fields and getattr(fields["InvoiceTotal"], "value_currency", None):
                total_amount = Decimal(str(fields["InvoiceTotal"].value_currency.amount))
                    
            confidence = confidence / max(len(fields), 1)
            
    return ExtractedInvoice(
        vendor_name=vendor_name,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        subtotal=subtotal,
        total_amount=total_amount,
        tax_amount=tax_amount,
        extraction_confidence=round(confidence, 2)
    )
