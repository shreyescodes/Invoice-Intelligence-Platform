"""Renders realistic supplier invoices as PDFs (three different layouts) for demos and tests."""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

Style = Literal["classic", "modern", "compact"]
TWO_PLACES = Decimal("0.01")


@dataclass(slots=True)
class Party:
    name: str
    address: list[str]
    tax_id: str | None


@dataclass(slots=True)
class Line:
    description: str
    quantity: Decimal
    unit_price: Decimal
    hsn: str = "9983"
    unit: str = "EA"

    @property
    def amount(self) -> Decimal:
        return (self.quantity * self.unit_price).quantize(TWO_PLACES, ROUND_HALF_UP)


@dataclass(slots=True)
class InvoiceDocument:
    style: Style
    vendor: Party
    buyer: Party
    invoice_number: str
    invoice_date: date
    due_date: date | None
    po_number: str | None
    lines: list[Line]
    tax_rate: Decimal
    intra_state: bool
    bank_details: str | None = None
    # Overrides let demo scenarios print internally inconsistent invoices on purpose.
    subtotal_override: Decimal | None = None
    tax_override: Decimal | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def subtotal(self) -> Decimal:
        if self.subtotal_override is not None:
            return self.subtotal_override
        return sum((line.amount for line in self.lines), Decimal("0"))

    @property
    def tax_lines(self) -> list[tuple[str, Decimal, Decimal]]:
        total_tax = self.tax_override
        if total_tax is None:
            total_tax = (self.subtotal * self.tax_rate / 100).quantize(TWO_PLACES, ROUND_HALF_UP)
        if self.intra_state:
            half = (total_tax / 2).quantize(TWO_PLACES, ROUND_HALF_UP)
            return [("CGST", self.tax_rate / 2, half), ("SGST", self.tax_rate / 2, total_tax - half)]
        return [("IGST", self.tax_rate, total_tax)]

    @property
    def tax_total(self) -> Decimal:
        return sum((amount for _, _, amount in self.tax_lines), Decimal("0"))

    @property
    def total(self) -> Decimal:
        return self.subtotal + self.tax_total


def qty(value: Decimal) -> str:
    """40 -> "40", 2.500 -> "2.5" (Decimal.normalize() alone would print 4E+1)."""
    return format(value.normalize(), "f")


def inr(value: Decimal) -> str:
    """Indian digit grouping: 1234567.5 -> 12,34,567.50"""
    sign = "-" if value < 0 else ""
    whole, frac = f"{abs(value):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups: list[str] = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join([*groups, tail])
    return f"{sign}{whole}.{frac}"


_ONES = (
    "",
    "One",
    "Two",
    "Three",
    "Four",
    "Five",
    "Six",
    "Seven",
    "Eight",
    "Nine",
    "Ten",
    "Eleven",
    "Twelve",
    "Thirteen",
    "Fourteen",
    "Fifteen",
    "Sixteen",
    "Seventeen",
    "Eighteen",
    "Nineteen",
)
_TENS = ("", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety")


def _words_below_1000(n: int) -> str:
    parts: list[str] = []
    if n >= 100:
        parts.append(f"{_ONES[n // 100]} Hundred")
        n %= 100
    if n >= 20:
        parts.append(_TENS[n // 10] + (f" {_ONES[n % 10]}" if n % 10 else ""))
    elif n:
        parts.append(_ONES[n])
    return " ".join(parts)


def amount_in_words(value: Decimal) -> str:
    rupees = int(value)
    paise = int((value - rupees) * 100)
    parts: list[str] = []
    for divisor, label in ((10_000_000, "Crore"), (100_000, "Lakh"), (1000, "Thousand")):
        if rupees >= divisor:
            parts.append(f"{_words_below_1000(rupees // divisor)} {label}")
            rupees %= divisor
    if rupees:
        parts.append(_words_below_1000(rupees))
    words = " ".join(parts) or "Zero"
    return f"Indian Rupees {words}" + (f" and {_words_below_1000(paise)} Paise" if paise else "") + " Only"


def _fmt_date(value: date, style: Style) -> str:
    return {"classic": value.strftime("%d %b %Y"), "modern": value.isoformat(), "compact": value.strftime("%d/%m/%Y")}[
        style
    ]


class _Renderer:
    def __init__(self, doc: InvoiceDocument) -> None:
        self.doc = doc
        self.buffer = io.BytesIO()
        self.c = canvas.Canvas(self.buffer, pagesize=A4, invariant=1, pageCompression=1)
        self.c.setTitle(f"Invoice {doc.invoice_number}")
        self.c.setAuthor(doc.vendor.name)
        self.width, self.height = A4
        self.left, self.right = 18 * mm, A4[0] - 18 * mm

    def text(
        self,
        x: float,
        y: float,
        value: str,
        size: float = 9,
        bold: bool = False,
        align: Literal["left", "right"] = "left",
        color: colors.Color = colors.black,
    ) -> None:
        self.c.setFillColor(color)
        self.c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        if align == "right":
            self.c.drawRightString(x, y, value)
        else:
            self.c.drawString(x, y, value)
        self.c.setFillColor(colors.black)

    def render(self) -> bytes:
        getattr(self, f"_render_{self.doc.style}")()
        self.c.showPage()
        self.c.save()
        return self.buffer.getvalue()

    # -- shared blocks -------------------------------------------------------------------------

    def _party(self, x: float, y: float, label: str, party: Party, size: float = 9) -> float:
        self.text(x, y, label, size, bold=True, color=colors.HexColor("#555555"))
        y -= 13
        self.text(x, y, party.name, size + 1, bold=True)
        for line in party.address:
            y -= 12
            self.text(x, y, line, size)
        if party.tax_id:
            y -= 12
            self.text(x, y, f"GSTIN: {party.tax_id}", size)
        return y

    def _summary(self, y: float, labels: tuple[str, str, str], ruled: bool) -> float:
        doc = self.doc
        label_x, value_x = self.right - 70 * mm, self.right
        rows: list[tuple[str, str, bool]] = [(labels[0], inr(doc.subtotal), False)]
        for name, rate, amount in doc.tax_lines:
            rate_text = f"{rate.normalize()}%"
            rows.append((f"{name} @ {rate_text}" if labels[1] == "@" else f"{name} {rate_text}", inr(amount), False))
        rows.append((labels[2], inr(doc.total), True))
        for label, value, bold in rows:
            if bold and ruled:
                self.c.setLineWidth(0.8)
                self.c.line(label_x, y + 11, value_x, y + 11)
            self.text(label_x, y, label, 10 if bold else 9, bold=bold)
            self.text(value_x, y, value, 10 if bold else 9, bold=bold, align="right")
            y -= 15
        return y

    def _footer(self, y: float) -> None:
        doc = self.doc
        y -= 8
        self.text(self.left, y, f"Amount in words: {amount_in_words(doc.total)}", 8)
        y -= 22
        if doc.bank_details:
            self.text(self.left, y, f"Bank details: {doc.bank_details}", 8)
            y -= 12
        for note in doc.notes:
            self.text(self.left, y, note, 8)
            y -= 12
        self.text(
            self.left,
            20 * mm,
            "This is a computer generated invoice and does not require a signature.",
            7,
            color=colors.HexColor("#777777"),
        )

    # -- layouts -------------------------------------------------------------------------------

    def _render_classic(self) -> None:
        doc, c = self.doc, self.c
        top = self.height - 20 * mm
        self.text(self.left, top, doc.vendor.name, 15, bold=True)
        self.text(self.right, top, "TAX INVOICE", 16, bold=True, align="right")
        y = top - 15
        for line in doc.vendor.address:
            self.text(self.left, y, line)
            y -= 12
        if doc.vendor.tax_id:
            self.text(self.left, y, f"GSTIN: {doc.vendor.tax_id}")

        meta_x, meta_y = self.right - 62 * mm, top - 15
        meta = [("Invoice No:", doc.invoice_number), ("Invoice Date:", _fmt_date(doc.invoice_date, "classic"))]
        if doc.due_date:
            meta.append(("Due Date:", _fmt_date(doc.due_date, "classic")))
        if doc.po_number:
            meta.append(("PO Number:", doc.po_number))
        for label, value in meta:
            self.text(meta_x, meta_y, label, bold=True)
            self.text(self.right, meta_y, value, align="right")
            meta_y -= 12

        y = min(y, meta_y) - 22
        y = self._party(self.left, y, "Bill To:", doc.buyer) - 22

        columns = [
            ("#", 8 * mm),
            ("Description", 78 * mm),
            ("HSN/SAC", 20 * mm),
            ("Qty", 16 * mm),
            ("Unit Price", 26 * mm),
            ("Amount", 26 * mm),
        ]
        row_h = 16
        xs = [self.left]
        for _, w in columns:
            xs.append(xs[-1] + w)
        rows = [[name for name, _ in columns]] + [
            [str(i + 1), li.description, li.hsn, qty(li.quantity), inr(li.unit_price), inr(li.amount)]
            for i, li in enumerate(doc.lines)
        ]
        table_top = y
        c.setFillColor(colors.HexColor("#EEF1F5"))
        c.rect(xs[0], table_top - row_h + 4, xs[-1] - xs[0], row_h, stroke=0, fill=1)
        c.setFillColor(colors.black)
        c.setLineWidth(0.5)
        for r, row in enumerate(rows):
            row_y = table_top - r * row_h
            for i, value in enumerate(row):
                numeric = i >= 3
                x = xs[i + 1] - 4 if numeric else xs[i] + 4
                self.text(x, row_y - 7, value, 8.5, bold=r == 0, align="right" if numeric else "left")
        bottom = table_top - len(rows) * row_h + 4
        for r in range(len(rows) + 1):
            line_y = table_top + 4 - r * row_h
            c.line(xs[0], line_y, xs[-1], line_y)
        for x in xs:
            c.line(x, table_top + 4, x, bottom)

        y = self._summary(bottom - 18, ("Subtotal", "@", "Total (INR)"), ruled=True)
        self._footer(y - 6)

    def _render_modern(self) -> None:
        doc, c = self.doc, self.c
        band = 34 * mm
        c.setFillColor(colors.HexColor("#0F3D4C"))
        c.rect(0, self.height - band, self.width, band, stroke=0, fill=1)
        top = self.height - 17 * mm
        self.text(self.left, top, doc.vendor.name, 16, bold=True, color=colors.white)
        self.text(self.right, top, "INVOICE", 20, bold=True, align="right", color=colors.white)
        self.text(self.left, top - 14, ", ".join(doc.vendor.address), 8, color=colors.HexColor("#CFE3EA"))

        y = self.height - band - 14 * mm
        meta = [("Invoice #", doc.invoice_number), ("Date of Issue", _fmt_date(doc.invoice_date, "modern"))]
        if doc.due_date:
            meta.append(("Payment Due", _fmt_date(doc.due_date, "modern")))
        if doc.po_number:
            meta.append(("Purchase Order", doc.po_number))
        meta_x = self.right - 60 * mm
        meta_y = y
        for label, value in meta:
            self.text(meta_x, meta_y, f"{label}:", 9, bold=True, color=colors.HexColor("#0F3D4C"))
            self.text(self.right, meta_y, value, 9, align="right")
            meta_y -= 13
        if doc.vendor.tax_id:
            self.text(self.left, y, f"GSTIN: {doc.vendor.tax_id}", 9, bold=True)
        y = self._party(self.left, y - 24, "Billed To", doc.buyer)
        y = min(y, meta_y) - 26

        cols = [
            ("Description", self.left + 2),
            ("Qty", self.right - 70 * mm),
            ("Rate", self.right - 38 * mm),
            ("Amount", self.right),
        ]
        self.text(cols[0][1], y, cols[0][0], 9, bold=True, color=colors.HexColor("#0F3D4C"))
        for name, x in cols[1:]:
            self.text(x, y, name, 9, bold=True, align="right", color=colors.HexColor("#0F3D4C"))
        c.setStrokeColor(colors.HexColor("#0F3D4C"))
        c.setLineWidth(1)
        c.line(self.left, y - 5, self.right, y - 5)
        c.setStrokeColor(colors.HexColor("#D5DEE2"))
        c.setLineWidth(0.5)
        for li in doc.lines:
            y -= 18
            self.text(cols[0][1], y, li.description, 9)
            self.text(cols[1][1], y, qty(li.quantity), 9, align="right")
            self.text(cols[2][1], y, inr(li.unit_price), 9, align="right")
            self.text(cols[3][1], y, inr(li.amount), 9, align="right")
            c.line(self.left, y - 6, self.right, y - 6)
        c.setStrokeColor(colors.black)
        y = self._summary(y - 26, ("Taxable Value", " ", "Amount Due (INR)"), ruled=True)
        self._footer(y - 6)

    def _render_compact(self) -> None:
        doc = self.doc
        top = self.height - 18 * mm
        self.text(self.left, top, doc.vendor.name.upper(), 13, bold=True)
        y = top - 14
        for line in doc.vendor.address:
            self.text(self.left, y, line, 8.5)
            y -= 11
        if doc.vendor.tax_id:
            self.text(self.left, y, f"GSTIN: {doc.vendor.tax_id}", 8.5)
            y -= 11
        y -= 14
        self.text(self.left, y, "TAX INVOICE", 11, bold=True)
        y -= 18
        self.text(self.left, y, f"Bill No. {doc.invoice_number}", 9)
        self.text(self.left + 85 * mm, y, f"Dated {_fmt_date(doc.invoice_date, 'compact')}", 9)
        y -= 13
        if doc.po_number:
            self.text(self.left, y, f"PO Ref: {doc.po_number}", 9)
        if doc.due_date:
            self.text(self.left + 85 * mm, y, f"Due On: {_fmt_date(doc.due_date, 'compact')}", 9)
        y -= 22
        self.text(self.left, y, f"Buyer: {doc.buyer.name}", 9, bold=True)
        for line in doc.buyer.address:
            y -= 11
            self.text(self.left + 12 * mm, y, line, 8.5)
        if doc.buyer.tax_id:
            y -= 11
            self.text(self.left + 12 * mm, y, f"GSTIN: {doc.buyer.tax_id}", 8.5)
        y -= 24

        x_sl, x_desc, x_hsn = self.left, self.left + 9 * mm, self.right - 82 * mm
        x_qty, x_rate, x_amt = self.right - 56 * mm, self.right - 30 * mm, self.right
        self.text(x_sl, y, "Sl", 9, bold=True)
        self.text(x_desc, y, "Particulars", 9, bold=True)
        self.text(x_hsn, y, "HSN", 9, bold=True)
        self.text(x_qty, y, "Qty", 9, bold=True, align="right")
        self.text(x_rate, y, "Rate", 9, bold=True, align="right")
        self.text(x_amt, y, "Amount", 9, bold=True, align="right")
        for i, li in enumerate(doc.lines, start=1):
            y -= 14
            self.text(x_sl, y, str(i), 9)
            self.text(x_desc, y, li.description, 9)
            self.text(x_hsn, y, li.hsn, 9)
            self.text(x_qty, y, qty(li.quantity), 9, align="right")
            self.text(x_rate, y, inr(li.unit_price), 9, align="right")
            self.text(x_amt, y, inr(li.amount), 9, align="right")
        y = self._summary(y - 26, ("Sub Total", "@", "Grand Total"), ruled=False)
        self._footer(y - 6)


def render_invoice_pdf(doc: InvoiceDocument) -> bytes:
    return _Renderer(doc).render()
