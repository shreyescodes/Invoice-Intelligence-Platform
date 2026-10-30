"""Embedded CII e-invoices (ZUGFeRD 2 / Factur-X / XRechnung). Real corpus files are covered by the
benchmark in benchmarks/realworld; these tests pin the mapping and the safety properties."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.extraction.einvoice import embedded_xml, parse_cii
from app.services.extraction.pdf_text import PdfTextExtractor
from tests.conftest import kaveri_invoice

CII = b"""<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice
    xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
    xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
    xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100">
  <rsm:ExchangedDocument>
    <ram:ID>471102</ram:ID>
    <ram:TypeCode>380</ram:TypeCode>
    <ram:IssueDateTime><udt:DateTimeString format="102">20180305</udt:DateTimeString></ram:IssueDateTime>
  </rsm:ExchangedDocument>
  <rsm:SupplyChainTradeTransaction>
    <ram:IncludedSupplyChainTradeLineItem>
      <ram:SpecifiedTradeProduct><ram:Name>Trennbl\xc3\xa4tter A4</ram:Name></ram:SpecifiedTradeProduct>
      <ram:SpecifiedLineTradeAgreement>
        <ram:NetPriceProductTradePrice><ram:ChargeAmount>9.90</ram:ChargeAmount></ram:NetPriceProductTradePrice>
      </ram:SpecifiedLineTradeAgreement>
      <ram:SpecifiedLineTradeDelivery>
        <ram:BilledQuantity unitCode="H87">20</ram:BilledQuantity>
      </ram:SpecifiedLineTradeDelivery>
      <ram:SpecifiedLineTradeSettlement>
        <ram:SpecifiedTradeSettlementLineMonetarySummation>
          <ram:LineTotalAmount>198.00</ram:LineTotalAmount>
        </ram:SpecifiedTradeSettlementLineMonetarySummation>
      </ram:SpecifiedLineTradeSettlement>
    </ram:IncludedSupplyChainTradeLineItem>
    <ram:ApplicableHeaderTradeAgreement>
      <ram:SellerTradeParty>
        <ram:Name>Lieferant GmbH</ram:Name>
        <ram:SpecifiedTaxRegistration><ram:ID schemeID="FC">201/113/40209</ram:ID></ram:SpecifiedTaxRegistration>
        <ram:SpecifiedTaxRegistration><ram:ID schemeID="VA">DE123456789</ram:ID></ram:SpecifiedTaxRegistration>
      </ram:SellerTradeParty>
      <ram:BuyerOrderReferencedDocument><ram:IssuerAssignedID>2018-471331</ram:IssuerAssignedID></ram:BuyerOrderReferencedDocument>
    </ram:ApplicableHeaderTradeAgreement>
    <ram:ApplicableHeaderTradeSettlement>
      <ram:InvoiceCurrencyCode>EUR</ram:InvoiceCurrencyCode>
      <ram:SpecifiedTradePaymentTerms>
        <ram:DueDateDateTime><udt:DateTimeString format="102">20180404</udt:DateTimeString></ram:DueDateDateTime>
      </ram:SpecifiedTradePaymentTerms>
      <ram:SpecifiedTradeSettlementHeaderMonetarySummation>
        <ram:LineTotalAmount>198.00</ram:LineTotalAmount>
        <ram:TaxBasisTotalAmount>198.00</ram:TaxBasisTotalAmount>
        <ram:TaxTotalAmount currencyID="EUR">37.62</ram:TaxTotalAmount>
        <ram:GrandTotalAmount>235.62</ram:GrandTotalAmount>
        <ram:DuePayableAmount>235.62</ram:DuePayableAmount>
      </ram:SpecifiedTradeSettlementHeaderMonetarySummation>
    </ram:ApplicableHeaderTradeSettlement>
  </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>"""


def test_cii_mapping() -> None:
    result = parse_cii(CII)
    assert result is not None
    assert result.method == "embedded_cii"
    assert result.invoice_number == "471102"
    assert result.invoice_date == date(2018, 3, 5)
    assert result.due_date == date(2018, 4, 4)
    assert result.vendor_name == "Lieferant GmbH"
    assert result.vendor_tax_id == "DE123456789"  # VAT ID preferred over the domestic tax number
    assert result.po_number == "2018-471331"
    assert (result.subtotal, result.tax_amount, result.total_amount) == (
        Decimal("198.00"),
        Decimal("37.62"),
        Decimal("235.62"),
    )
    assert result.line_items[0].quantity == Decimal(20)
    assert result.confidence == 1.0


def test_hostile_or_irrelevant_xml_is_rejected() -> None:
    billion_laughs = b"""<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;">]>
    <rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100">&lol2;
    </rsm:CrossIndustryInvoice>"""
    assert parse_cii(billion_laughs) is None
    assert parse_cii(b"<Invoice>not cii</Invoice>") is None
    assert parse_cii(b"not xml at all") is None


def test_plain_pdfs_fall_back_to_text_extraction() -> None:
    pdf = kaveri_invoice()
    assert embedded_xml(pdf) is None
    assert PdfTextExtractor().extract(pdf, "application/pdf").method == "pdf_text"
