"""Structured e-invoices embedded in PDFs (ZUGFeRD 2.x, Factur-X, XRechnung CII).

Hybrid PDF e-invoices carry a machine-readable copy of the invoice as an XML attachment, using the
UN/CEFACT Cross Industry Invoice (CII) syntax. When one is present it is authoritative, so there is no
need to guess from the printed layout. E-invoicing is mandatory for B2B in Germany (from 2025) and
France (from 2026), so these documents are increasingly common.

The attachment is untrusted input and is parsed with defusedxml (no entity expansion, no external
entities).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from app.services.extraction.base import ExtractedLine, ExtractionResult

NS = {
    "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
    "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
}
ATTACHMENT_NAMES = ("factur-x.xml", "zugferd-invoice.xml", "xrechnung.xml", "zugferd_2p0.xml")
EMBEDDED_CONFIDENCE = 1.0
MAX_XML_BYTES = 5 * 1024 * 1024


def embedded_xml(pdf_bytes: bytes) -> bytes | None:
    """Return the CII XML attached to a PDF, if any."""
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(pdf_bytes)
    except pdfium.PdfiumError:
        return None
    try:
        candidates: list[tuple[str, bytes]] = []
        for index in range(pdf.count_attachments()):
            attachment = pdf.get_attachment(index)
            name = attachment.get_name().lower()
            if name.endswith(".xml"):
                data = bytes(attachment.get_data())
                if len(data) <= MAX_XML_BYTES:
                    candidates.append((name, data))
    finally:
        pdf.close()
    candidates.sort(key=lambda c: (c[0] not in ATTACHMENT_NAMES, c[0]))
    for _, data in candidates:
        if b"CrossIndustryInvoice" in data[:20_000]:
            return data
    return None


def _text(node: Any, path: str) -> str | None:
    found = node.find(path, NS)
    if found is None or found.text is None:
        return None
    return str(found.text).strip() or None


def _amount(node: Any, path: str, currency: str | None = None) -> Decimal | None:
    for found in node.findall(path, NS):
        if currency and found.get("currencyID") not in (None, currency):
            continue  # TaxTotalAmount may be repeated in the accounting currency
        try:
            return Decimal(str(found.text).strip())
        except (InvalidOperation, AttributeError):
            return None
    return None


def _date(node: Any, path: str) -> date | None:
    value = _text(node, path)
    if not value:
        return None
    try:
        return datetime.strptime(value[:8], "%Y%m%d").date()  # noqa: DTZ007 - format 102 is a calendar date
    except ValueError:
        return None


def parse_cii(xml: bytes) -> ExtractionResult | None:
    """Map a CII document to an ExtractionResult, or None if it isn't a usable invoice."""
    try:
        root = ElementTree.fromstring(xml)
    except (ElementTree.ParseError, DefusedXmlException, ValueError):
        return None
    if not root.tag.endswith("CrossIndustryInvoice"):
        return None

    trade = "rsm:SupplyChainTradeTransaction/"
    agreement = trade + "ram:ApplicableHeaderTradeAgreement/"
    settlement = trade + "ram:ApplicableHeaderTradeSettlement/"
    totals = settlement + "ram:SpecifiedTradeSettlementHeaderMonetarySummation/"
    seller = agreement + "ram:SellerTradeParty/"

    result = ExtractionResult(method="embedded_cii")
    result.invoice_number = _text(root, "rsm:ExchangedDocument/ram:ID")
    result.invoice_date = _date(root, "rsm:ExchangedDocument/ram:IssueDateTime/udt:DateTimeString")
    result.vendor_name = _text(root, seller + "ram:Name")
    # Prefer the VAT ID (schemeID "VA") over a domestic tax number ("FC", e.g. a German Steuernummer).
    registrations = {
        reg.get("schemeID"): str(reg.text).strip()
        for reg in root.findall(seller + "ram:SpecifiedTaxRegistration/ram:ID", NS)
        if reg.text and reg.text.strip()
    }
    result.vendor_tax_id = registrations.get("VA") or registrations.get("FC") or registrations.get(None)
    result.po_number = _text(root, agreement + "ram:BuyerOrderReferencedDocument/ram:IssuerAssignedID")
    result.currency = _text(root, settlement + "ram:InvoiceCurrencyCode") or result.currency
    result.due_date = _date(root, settlement + "ram:SpecifiedTradePaymentTerms/ram:DueDateDateTime/udt:DateTimeString")
    result.subtotal = _amount(root, totals + "ram:TaxBasisTotalAmount") or _amount(root, totals + "ram:LineTotalAmount")
    result.tax_amount = _amount(root, totals + "ram:TaxTotalAmount", result.currency)
    result.total_amount = _amount(root, totals + "ram:GrandTotalAmount")

    for item in root.findall(trade + "ram:IncludedSupplyChainTradeLineItem", NS):
        description = _text(item, "ram:SpecifiedTradeProduct/ram:Name") or ""
        quantity = _amount(item, "ram:SpecifiedLineTradeDelivery/ram:BilledQuantity")
        price = _amount(item, "ram:SpecifiedLineTradeAgreement/ram:NetPriceProductTradePrice/ram:ChargeAmount")
        amount = _amount(
            item,
            "ram:SpecifiedLineTradeSettlement/ram:SpecifiedTradeSettlementLineMonetarySummation/ram:LineTotalAmount",
        )
        if amount is None:
            continue
        quantity = quantity if quantity and quantity > 0 else Decimal(1)
        price = price if price is not None else (amount / quantity).quantize(Decimal("0.01"))
        result.line_items.append(ExtractedLine(description, quantity, price, amount))

    for field in (
        "vendor_name",
        "invoice_number",
        "invoice_date",
        "total_amount",
        "subtotal",
        "tax_amount",
        "vendor_tax_id",
        "po_number",
    ):
        if getattr(result, field) is not None:
            result.field_confidence[field] = EMBEDDED_CONFIDENCE
    if result.invoice_number is None or result.total_amount is None:
        return None
    return result
