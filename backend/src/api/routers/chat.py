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

from fastapi import APIRouter
from openai import AsyncOpenAI
from pydantic import BaseModel

from src.core.config import get_settings

router = APIRouter()


class ChatQuery(BaseModel):
    question: str


class ChatResponse(BaseModel):
    answer: str
    sql_used: str | None = None


@router.post("", response_model=ChatResponse)
async def ask(query: ChatQuery) -> ChatResponse:
    settings = get_settings()
    
    from src.llm.provider import get_async_llm_client
    client, model = get_async_llm_client(settings)
    
    system_prompt = """You are a data assistant for an invoice processing platform.
    Translate the user's natural language question into a PostgreSQL SQL query.
    Assume a table `invoices` with columns: id, vendor_id, status, subtotal, tax_amount, total_amount, created_at.
    Return ONLY the raw SQL query, nothing else. Do not use markdown formatting blocks like ```sql."""
    
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query.question}
            ],
            temperature=0.0
        )
        sql_query = response.choices[0].message.content.strip()
        
        # In Phase 6, we will execute this against Snowflake/Postgres.
        # For now, we return the generated SQL to the frontend.
        return ChatResponse(
            answer="I translated your question into a SQL query. (Actual database execution is mocked until Phase 6 data warehouse is built).",
            sql_used=sql_query
        )
    except Exception as e:
        # Graceful fallback if Ollama isn't running locally
        return ChatResponse(
            answer=f"Could not connect to the local LLM to answer this. Is Ollama running? Error: {str(e)}",
            sql_used=None
        )
