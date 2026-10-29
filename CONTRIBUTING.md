# Contributing

## Workflow

1. Branch from `main` (`feat/…`, `fix/…`, `docs/…`).
2. Keep commits focused, with messages in the imperative (`Add duplicate check for…`); a
   [Conventional Commits](https://www.conventionalcommits.org) prefix is welcome.
3. Open a pull request. CI must pass, and changes to the pipeline or the API need tests.

## Local checks

```bash
# backend
cd backend
uv run ruff check . && uv run ruff format --check .
uv run mypy app
uv run pytest                                   # SQLite
TEST_DATABASE_URL=postgresql+psycopg://iip:iip@localhost:5433/iip_test uv run pytest   # PostgreSQL

# frontend
cd frontend
npm run lint && npm run typecheck && npm test && npm run build
```

## Conventions

- **Schema changes** need an Alembic migration (`uv run alembic revision --autogenerate -m "…"`, then
  review it). The test suite fails if models and migrations disagree.
- **API changes:** regenerate the contract and client types, and commit both:
  `uv run iip export-openapi --out ../frontend/openapi.json`, then `npm run gen:api` in `frontend/`.
- **State changes** to an invoice go through `app/services/invoices.py` (`transition`) so the audit
  event and any follow-up job are written in the same transaction.
- **Money** is `Decimal` in Python and `NUMERIC` in the database, never `float`.
- **New validation rules** return a clear, reviewer-facing message: it is shown verbatim in the UI.
- **UI colours** come from the tokens in `frontend/src/index.css`, which have light and dark values;
  status is always shown as icon and label, never colour alone.
- **Screenshots** in `docs/screenshots` are generated, not hand-made:
  `npm run screenshots` against a freshly seeded stack.
