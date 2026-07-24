"""Natural-language question answering over invoice data.

The one genuinely open-ended piece — deliberately left loose so you
can shape it. Two reasonable designs, pick one for phase 7:

A) Text-to-SQL: give the LLM the star schema (fact_invoice, dim_vendor,
   dim_date columns), ask it to write a SQL query answering the
   question, execute it read-only against Snowflake (or the local
   Postgres stand-in), return the result. Simpler, and the answer is
   always grounded in real numbers — good for "how many invoices from
   vendor X exceeded ₹10,000 last month" style questions.

B) RAG over Cosmos DB: embed invoice records, retrieve the relevant
   ones for a question, let the LLM answer from that context. Better
   for fuzzier questions ("summarize unusual invoices this week") but
   needs an embedding model and a vector index.

Start with (A) — it's the more common enterprise pattern and reuses
everything you already built for the ETL layer. Guard against SQL
injection from LLM output: allowlist to SELECT-only, run against a
read-only role, and consider a query-plan sanity check before executing.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class ChatQuery(BaseModel):
    question: str


class ChatResponse(BaseModel):
    answer: str
    sql_used: str | None = None


@router.post("", response_model=ChatResponse)
async def ask(query: ChatQuery) -> ChatResponse:
    raise HTTPException(501, "Not implemented — see TODO in this file, phase 7")
