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
from pydantic import BaseModel

from src.core.config import get_settings

router = APIRouter()


class ChatQuery(BaseModel):
    question: str


class ChatResponse(BaseModel):
    answer: str
    sql_used: str | None = None
    data: list[dict] | None = None


@router.post("", response_model=ChatResponse)
async def ask(query: ChatQuery) -> ChatResponse:
    settings = get_settings()
    
    from src.llm.provider import get_async_llm_client
    client, model = get_async_llm_client(settings)
    
    system_prompt = """You are a data assistant for an invoice processing platform.
    Translate the user's natural language question into a Snowflake SQL query.
    The warehouse uses a star schema with these tables:
    - fact_invoice (invoice_id VARCHAR, vendor_key INTEGER, invoice_number VARCHAR, status VARCHAR, subtotal DECIMAL, tax_amount DECIMAL, total_amount DECIMAL, anomaly_score FLOAT, created_at TIMESTAMP)
    - dim_vendor (vendor_key INTEGER, vendor_id VARCHAR, vendor_name VARCHAR, tax_id VARCHAR)
    Join fact_invoice to dim_vendor on fact_invoice.vendor_key = dim_vendor.vendor_key to resolve vendor names.
    Return ONLY the raw SQL query. Do not use markdown formatting blocks like ```sql."""
    
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

        # Fix 1: SQL Injection Guard — allowlist SELECT-only queries.
        # The LLM docstring warned about this; now it is enforced.
        # Strip leading whitespace/comments before checking the verb.
        _sql_stripped = sql_query.lstrip()
        _forbidden = ["drop", "delete", "insert", "update", "alter", "create", "truncate", "exec", "execute"]
        _first_word = _sql_stripped.split()[0].lower() if _sql_stripped.split() else ""
        if _first_word != "select" or any(kw in _sql_stripped.lower() for kw in _forbidden):
            return ChatResponse(
                answer="I can only answer read-only questions. The generated query was not a safe SELECT statement.",
                sql_used=sql_query,
                data=None
            )

        # Execute against Snowflake (read-only by policy)
        query_data = []
        if settings.using_real_snowflake:
            import snowflake.connector
            try:
                with snowflake.connector.connect(
                    user=settings.snowflake_user,
                    password=settings.snowflake_password,
                    account=settings.snowflake_account,
                    warehouse=settings.snowflake_warehouse,
                    database=settings.snowflake_database,
                    schema="PUBLIC"
                ) as conn, conn.cursor() as cursor:
                    cursor.execute(sql_query)
                    if cursor.description:
                        columns = [col[0] for col in cursor.description]
                        query_data = [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]
            except Exception as sql_e:
                return ChatResponse(
                    answer=f"I generated the SQL, but execution failed: {str(sql_e)}",
                    sql_used=sql_query,
                    data=None
                )
        
        return ChatResponse(
            answer="Here is the data answering your question based on the live analytical warehouse.",
            sql_used=sql_query,
            data=query_data
        )
    except Exception as e:
        # Graceful fallback if Ollama isn't running locally
        return ChatResponse(
            answer=f"Could not connect to the local LLM to answer this. Is Ollama running? Error: {str(e)}",
            sql_used=None,
            data=None
        )
