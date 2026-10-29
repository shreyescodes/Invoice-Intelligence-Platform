from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import AppSettings, CurrentUser, DbSession
from app.runtime import get_llm
from app.schemas import AskIn, AskOut, Problem, Suggestions, SummaryOut
from app.services.analytics import dashboard_summary
from app.services.ask import CATALOG, ask

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary", response_model=SummaryOut, summary="Dashboard KPIs")
def summary(session: DbSession, _: CurrentUser, days: Annotated[int, Query(ge=7, le=730)] = 90) -> SummaryOut:
    return dashboard_summary(session, days)


@router.get("/ask/suggestions", response_model=Suggestions)
def suggestions(settings: AppSettings, _: CurrentUser) -> Suggestions:
    return Suggestions(questions=[c.question for c in CATALOG], llm_enabled=settings.llm_enabled)


@router.post(
    "/ask",
    response_model=AskOut,
    responses={422: {"model": Problem}},
    summary="Answer a natural-language question with a guarded, read-only SQL query",
)
def ask_question(body: AskIn, settings: AppSettings, _: CurrentUser) -> AskOut:
    result = ask(body.question, settings, get_llm())
    return AskOut(
        question=result.question,
        answer=result.answer,
        sql=result.sql,
        columns=result.columns,
        rows=result.rows,
        source=result.source,
        chart=result.chart,
        model=result.model,
        truncated=result.truncated,
    )
