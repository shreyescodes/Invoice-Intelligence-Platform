"""Activity: OCR + structured extraction on one invoice.

TODO(phase 2):
1. Pull the blob (given its path) from Blob Storage into memory.
2. Call Azure AI Document Intelligence's prebuilt-invoice model
   (azure-ai-documentintelligence SDK, `begin_analyze_document`).
   F0 free tier note: it only reads the first 2 pages per document —
   fine for typical 1-2 page vendor invoices, but know this limit
   exists before you're confused by a 5-page test PDF returning
   nothing for pages 3-5.
3. Map the SDK's AnalyzedDocument.fields onto ExtractedInvoice
   (src/api/schemas/invoice.py). Field names differ from your schema —
   don't assume, print the raw response once and look.
4. For any field Document Intelligence returns with low confidence,
   call src.llm.provider.extract_json with the raw OCR text and ask
   the model to re-extract just that field. This is where Ollama vs
   Azure OpenAI is genuinely invisible to the rest of the pipeline.
5. Return an ExtractedInvoice (as a dict — activity functions
   serialize to JSON, Pydantic's .model_dump(mode="json") handles
   Decimal/date encoding).
"""

from typing import Any


def extract_document(blob_path: str) -> dict[str, Any]:
    raise NotImplementedError("Build this in phase 2 — see module docstring")
