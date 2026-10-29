"""Server-side page rendering, so every browser shows the same preview (no PDF plug-in needed)."""

from __future__ import annotations

import io

from app.errors import NotFoundError
from app.models import Invoice
from app.services.storage import DocumentNotFoundError, DocumentStore

RENDER_SCALE = 2.0  # ~144 dpi: sharp on high-density screens, ~150 KB per page


def page_count(data: bytes) -> int:
    import pypdfium2 as pdfium

    with pdfium.PdfDocument(data) as pdf:
        return len(pdf)


def render_page(data: bytes, page: int) -> bytes:
    import pypdfium2 as pdfium

    with pdfium.PdfDocument(data) as pdf:
        if page < 1 or page > len(pdf):
            raise NotFoundError(f"Page {page} does not exist")
        image = pdf[page - 1].render(scale=RENDER_SCALE).to_pil()
    buffer = io.BytesIO()
    image.save(buffer, "PNG", optimize=True)
    return buffer.getvalue()


def get_preview(store: DocumentStore, invoice: Invoice, page: int) -> tuple[bytes, str, int]:
    """Return (image bytes, media type, page count), rendering and caching PDF pages on first request."""
    original = store.get(invoice.storage_key)
    if invoice.content_type != "application/pdf":
        if page != 1:
            raise NotFoundError(f"Page {page} does not exist")
        return original, invoice.content_type, 1
    total = page_count(original)
    key = f"previews/{invoice.id}/page-{page}.png"
    try:
        return store.get(key), "image/png", total
    except DocumentNotFoundError:
        image = render_page(original, page)
        store.put(key, image, "image/png")
        return image, "image/png", total
