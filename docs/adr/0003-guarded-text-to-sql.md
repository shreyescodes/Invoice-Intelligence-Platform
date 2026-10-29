# 0003. Natural-language questions run guarded, read-only SQL

- Status: accepted
- Date: 2026-10-29

## Context

Finance users want answers like "spend by vendor this quarter" without waiting for a report. Letting an
LLM write SQL is the most flexible way to provide that, but model output is untrusted input: it can be
wrong, and a prompt injection hidden in invoice text or in the question can try to make it destructive
or exfiltrating. A keyword blocklist (rejecting queries that contain `DROP`, and so on) is easy to bypass
and also rejects harmless queries.

## Decision

Defence in depth, with each layer sufficient on its own for the most likely failures:

1. **Curated queries first.** Common questions map to reviewed SQL, which also makes the feature useful
   with no LLM configured.
2. **AST validation** (sqlglot): exactly one statement, which must be a `SELECT` or set operation, with
   no DML or DDL nodes, no `SELECT INTO`, no `FOR UPDATE`, and no `pg_*`, `lo_*`, `dblink`,
   `current_setting`-style functions.
3. **Allowlisted relations:** only the four `analytics_*` views (and the query's own CTEs), with no
   schema-qualified names. The views omit credentials, raw document text and the job queue.
4. **Row limit:** a `LIMIT` is applied or tightened, so results can't be unbounded.
5. **Execution:** a `READ ONLY` transaction with a statement timeout, on a connection whose role has
   `SELECT` on the views and nothing else (`default_transaction_read_only = on` as well).

The executed (normalised) SQL is shown to the user, along with whether it came from the catalogue or a model.

## Consequences

- A malicious or wrong query fails safely with a 422 and a reason; it cannot modify data, read other
  tables or run for long.
- Some legitimate but exotic SQL (functions outside the parser's knowledge, schema-qualified names) is
  rejected; widening the allowlist is a reviewed code change.
- Answers are only as correct as the generated SQL; showing it keeps the result auditable.
