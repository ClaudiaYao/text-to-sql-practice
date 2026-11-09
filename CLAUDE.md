# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project goal

A chat window where a user asks questions about the Sakila (PostgreSQL) database in natural language. The system converts the question to SQL, runs it, and replies with **both** the data (table/cards) **and** a natural-language answer. It must handle simple and complex queries (joins, aggregation, CTEs, window functions, set operations, date math) with a target of **99% execution accuracy on the golden test set** (Phase D — not built yet, so the accuracy is currently *unmeasured*).

## Working rules

- **Never delete or rewrite the user's code comments.** If one breaks syntax, comment it out with `#`; keep all of its text.
- Update this file (architecture, roadmap status, changelog) after every change.
- Keep the code free of unused providers/options; the stack is AWS Bedrock + PostgreSQL only.

## Development commands

```bash
# Database (required first)
docker compose up -d      # or: docker run -p 5432:5432 --rm rsundqvist/sakila-preload:postgres
# The image only has the `postgres` superuser; create the read-only `sakila` login that .env expects (once per fresh container):
docker exec -i $(docker compose ps -q sakila-db) psql -U postgres -d sakila < backend/scripts/create_readonly_role.sql

# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env      # edit; .env is gitignored. AWS creds come from the standard chain (aws sso login, etc.)
uvicorn app.main:app --reload          # http://localhost:8000
pytest                                  # 100 tests; DB-marked ones auto-skip if Postgres is down; none need AWS
python -m tests.golden.runner           # LIVE accuracy eval (needs Postgres + Bedrock creds); --split dev|heldout, --tier, --limit, --threshold
pytest -m eval -s                       # same eval via pytest (GOLDEN_THRESHOLD, default 0.99)

# Frontend
cd frontend && npm install && npm run dev     # http://localhost:5173  (npm run build / npm run lint)
```

Never put AWS access keys in `.env`. The Claude model in `BEDROCK_MODEL_ID` must be enabled under Bedrock → Model access. Restart the server after editing `.env`.

## Architecture

```
backend/app/
├── main.py            # app factory, CORS, lifespan warm-up (schema + examples)
├── config.py          # pydantic-settings; ALL values from backend/.env (absolute path), no defaults except optional aws_profile/cache_persist_path
├── constants.py       # BLOCKED_COLUMNS (password, picture), ALLOWED_SCHEMAS
├── database.py        # async engine (read-only + statement_timeout on every connection); execute_query()
├── api/routes.py      # /api/query, /api/chat, /api/schema, /api/cache/stats, DELETE /api/cache, /health
├── models/schemas.py  # QueryRequest, ChatRequest, QueryResponse
└── services/
    ├── pipeline.py        # run_pipeline(): the whole flow (see below)
    ├── llm.py             # Bedrock Converse + tasks: generate_candidates, correct_sql, rewrite_question, judge_empty, summarize
    ├── prompts.py         # ALL prompt templates and the SQL-writing rules
    ├── domain_notes.py    # hand-written Sakila semantics injected into prompts (edit to fix systematic errors)
    ├── schema.py          # cached introspection: tables, PK, FK, enums, small-table value hints
    ├── examples.py        # few-shot selection (keyword + technique hints; no embeddings)
    ├── sql_validator.py   # sqlglot: one read-only statement, no DML/system access
    ├── cache.py           # TTLCache, sql_cache, answer_cache, normalize_question()
    └── aws.py             # cached boto3 bedrock-runtime client
backend/data/seed/sakila_examples.json   # 30 curated (question, SQL) pairs
backend/tests/                           # unit tests + golden set (see "Golden set" below)
frontend/src/  App.tsx, api.ts, components/{QueryInput,SqlPanel,ResultsTable,ResultsCards,ViewToggle}.tsx
```

### Pipeline (`services/pipeline.py`)

1. Chat follow-up → LLM rewrites it into a standalone question.
2. **SQL cache** (key = schema hash + normalised question): hit → validate and *re-execute* (data stays fresh), no SQL-generation LLM call. A cached SQL that fails is evicted.
3. Few-shot examples selected; `is_complex()` (strong/weak keyword rules) chooses the path:
   - simple → one greedy candidate;
   - complex → plan-then-SQL prompt, `COMPLEX_CANDIDATES` candidates (1 greedy + sampled).
4. Each candidate is validated (sqlglot) and executed (read-only, timeout). **Majority vote on result sets** (order- and column-name-insensitive); ties go to the greedy candidate.
5. If nothing ran: self-correction with the exact DB/validator error, up to `MAX_ATTEMPTS`.
6. If 0 rows: an LLM judge decides whether empty is plausible; if the filter looks wrong, one correction round.
7. Non-empty results cache their SQL; the natural-language answer is cached on (question, actual rows).

`Unanswerable` (model replied `ERROR: …`, e.g. a write request) → HTTP 422, no retries. `PipelineError` → 400. `LLMError` → 502.

### Cache notes
- Only SQL (not rows) is cached long-term, so answers can never be stale; the answer cache is keyed on the result itself.
- SQL cache optionally persists to `CACHE_PERSIST_PATH`; keys include the schema hash, so a schema change invalidates automatically.
- After a wrong answer or a prompt change: `DELETE /api/cache`.
- Not implemented: single-flight for identical concurrent questions, user feedback → eviction, shared (Redis) cache for multi-worker deploys.

### Config (`backend/.env`; each field ← the upper-cased env var of the same name)
`DATABASE_URL`; `AWS_REGION`, `AWS_PROFILE` (optional), `BEDROCK_MODEL_ID`; `QUERY_TIMEOUT_MS`, `MAX_ROWS`; `MAX_ATTEMPTS`, `FEWSHOT_TOP_K`, `COMPLEX_CANDIDATES`, `CANDIDATE_TEMPERATURE`; `CACHE_ENABLED`, `CACHE_MAX_ENTRIES`, `SQL_CACHE_TTL_SECONDS`, `ANSWER_CACHE_TTL_SECONDS`, `SCHEMA_CACHE_TTL_SECONDS`, `CACHE_PERSIST_PATH` (optional); `CORS_ORIGINS`. Missing required keys fail at startup with the key named.

### Golden set (`backend/tests/golden/`)

- `sakila_golden.json`: 100 cases in 9 tiers — simple 14, joins 15, aggregation 14, complex 18, dates 10, edge 12, followup 6 (with chat `history`), unanswerable 5, unsafe 6 (these two must be *refused*). Each answerable case has hand-written reference SQL; `split` is `dev` (tune on this) or `heldout` (every 3rd case; look at it rarely, to detect overfitting).
- `scoring.py`: execution accuracy. Column names ignored, extra columns allowed, rows compared as a multiset (sequence if `ordered`), integers exact, floats within 0.011, `char(n)` padding ignored, midnight timestamps == dates. Both-empty matches.
- `runner.py`: runs the real pipeline per case (cache disabled), scores it, prints a per-tier table + failures, reports a **95% Wilson lower bound** (with n=100 even a perfect score only proves ≥ ~96%), saves JSON to `tests/golden/reports/` (gitignored).
- Verified against the real DB: every reference runs, none exceeds `MAX_ROWS`, top-N boundaries and "first/latest" cases were checked for ties, and no golden question overlaps a few-shot example (`test_no_leakage…`). Do not copy golden questions into `sakila_examples.json`.
- `test_golden_set.py` also runs an **offline oracle** (fake LLM returns the reference SQL through the real pipeline/DB/scorer → must be 100%) and a mutation test (scorer must reject wrong answers).
- Limitation: the same author wrote the prompts, examples and questions, so the set is biased toward what the system already handles. Add your own real-world questions (and every production failure) to it.

### Dataset facts (verified on the live image; golden cases depend on them)
599 customers, 1000 films, 16044 rentals (2005-05-24 → 2006-02-14), 16049 payments (5 share a `rental_id`), 183 unreturned rentals, 42 films with no inventory, 15 inactive customers (`active=0`; `activebool` is TRUE for all), all `customer.create_date` and `film.release_year` identical, `language.name` is `char(20)` (blank-padded). Per-store revenue differs by attribution (staff vs inventory). The payment_p2007_* inheritance children and `uuid_test_table` are hidden from the prompt.

### Where to fix accuracy problems
1. Systematic mistake (wrong join/column semantics) → `domain_notes.py` or a rule in `prompts.py`.
2. Pattern the model gets wrong → add a verified example to `data/seed/sakila_examples.json` (keep SQL valid; `tests/test_examples.py` checks every example).
3. Then `DELETE /api/cache` so stale SQL is not served.

## Roadmap

- **Done:** Phase A (foundation fixes, RAG removed), Phase C basics (domain notes, 30 examples, plan + vote, judge), Phase D (unit tests + golden set + scorer + runner), chat + NL-answer **backend**.
- **BLOCKED — first live accuracy number:** `~/.aws/config` and `~/.aws/credentials` are owned by root (mode 600), so the user's boto3 finds no credentials. User must fix ownership (`sudo chown -R "$USER" ~/.aws`) or `aws sso login` / export creds, and confirm `BEDROCK_MODEL_ID`. Then: `python -m tests.golden.runner --split dev`, fix failures via domain notes / examples / prompts, re-run, and check `--split heldout` before claiming any accuracy. "99%" = execution accuracy on this set, not a guarantee for arbitrary questions.
- **Next — Phase B frontend:** chat window (message bubbles; each assistant bubble = `answer` + collapsible SQL + table/cards + badges for cached / self-corrected / low agreement); call `/api/chat` with history; `frontend/src/types.ts` still has the old response shape.
- **Later:** clarification questions for ambiguous requests, single-flight + feedback-driven cache eviction, Redis cache.
- **Known unverified:** nothing has run against live Bedrock yet (Postgres is verified: all 30 seed examples and 94 reference queries execute); `BEDROCK_MODEL_ID` default is an unverified guess; the follow-up rewrite, empty-result judge and answer summariser prompts are untested with a real model.

## Changelog

> Update this section after every change so future Claude instances know what is done.

### 2026-11-09 — Frontend text contrast + footer

- Raised every muted gray text class one step (`gray-300→100`, `400→200`, `500→300`, `600→400`; hover → white; placeholder `500→400`; disabled states left dim) across `App.tsx` and all components. Footer now reads "Powered by AWS Bedrock" (was Azure AI Foundry).

### 2026-11-09 — Golden set + live-DB verification

- **New** `tests/golden/` (100-case golden set, `scoring.py`, `runner.py`), `tests/test_scoring.py`, `tests/test_golden_set.py`, `tests/test_golden_eval.py` (`-m eval`); 100 tests pass (incl. offline oracle at 100% and scorer mutation test). `pytest.ini` uses a session event loop; `conftest.py` no longer overrides the real `DATABASE_URL`.
- **Fixed by running against real Sakila:** schema text listed the `payment_p2007_*` inheritance children, `uuid_test_table`, `last_update` columns and padded `char(20)` hints → hidden/trimmed (`constants.py`: `HIDDEN_TABLES`, `HIDDEN_COLUMNS`; `schema.py`: pg_inherits filter, short type names, array types). Scorer bug found by tests: ints off by one passed via relative tolerance → integers now exact.
- **Golden-set fixes found by verification:** 3 references exceeded `MAX_ROWS` (would score correct answers wrong) → narrowed; ambiguous ties at top-N boundaries / equal timestamps → rewritten; one reference returned 0 rows → rewritten.
- **Domain notes:** `customer.active` (not `activebool`) is the real status flag; store attribution (staff vs inventory); payments are not 1:1 with rentals. (The `active` note was added after seeing golden case `edge-05` fail by design — it is a dev-split case, but the fact came from inspecting the data.)
- **DB:** image has no `sakila` role → `backend/scripts/create_readonly_role.sql` (read-only login matching `.env`). Removed obsolete `version:` from `docker-compose.yml`.
- **Blocked:** no live LLM score yet — root-owned `~/.aws` (see Roadmap).

### 2026-11-09 — Backend regenerated (no RAG, caching, accuracy engine)

`backend/app/` was deleted and rebuilt from the plan:
- **Removed RAG** (ChromaDB, embeddings, schema retrieval) and the Titan/RAG/Chroma settings; the full schema is always sent. Few-shot examples are chosen by keyword + SQL-technique match (`services/examples.py`).
- **New** `services/cache.py` (SQL cache + answer cache, LRU+TTL, optional disk persistence), `services/schema.py` (cached introspection incl. PKs, FKs, enums, value hints), `services/domain_notes.py`, `services/prompts.py`, `services/llm.py` (Bedrock Converse; generate/correct/rewrite/judge/summarize), `services/pipeline.py`.
- **Accuracy:** plan-then-SQL and N-candidate majority vote on result sets for complex questions; self-correction with DB error; LLM-judged empty-result check; rollback between retries.
- **Safety:** validator allows SELECT/CTE/UNION/INTERSECT/EXCEPT only (single statement, no DML anywhere, no system schemas/functions, blocked columns); connections are `default_transaction_read_only` with `statement_timeout`; rows capped by `MAX_ROWS`.
- **API:** `POST /api/query`, `POST /api/chat` (history → standalone question), `GET /api/schema`, `GET /api/cache/stats`, `DELETE /api/cache`, `GET /health`. Responses now include `answer`, `cached`, `truncated`, `complex`, `candidates`, `agreement`.
- **Seed examples:** 18 → 30 (EXCEPT, percent-of-total, LAG, ties, relational division…); fixed one whose SQL did not match its question.
- **Tests:** 73 unit tests (validator, cache, parsing, examples, pipeline with scripted LLM/DB, API). **Not yet done:** golden-set accuracy eval, frontend chat UI. Nothing has been run against live Bedrock/Postgres yet.

### 2026-11-09 — Switch to AWS Bedrock only (earlier today)

- **Removed** Azure OpenAI and GCP Vertex AI (code, config, README, requirements). Bedrock is the only provider.
- **New** `app/services/aws.py` (cached boto3 `bedrock-runtime` client); `llm.py` `_call_llm()` uses the Converse API; `embeddings.py` uses Titan v2.
- **Updated** `app/config.py` — no hardcoded defaults; everything is read from `backend/.env` via an absolute path (only `aws_profile` is optional).
- **Moved** `app/agent/*` → `app/services/*` (old files deleted, not yet committed); renamed `gemini.py` → `llm.py`.
- **Fixed** `config.py`: the user's explanatory comment block at the bottom is preserved (uncommented lines prefixed with `#` so the file parses).
- **Decided** roadmap (Phases A–E below). Not yet implemented: validator fix, rollback on retry, read-only DB, chat endpoint, NL answers, tests, RAG removal.

### Earlier history (condensed; provider details superseded by the Bedrock switch)

- **Initial build:** FastAPI (`/api/query`, `/api/schema`, `/health`), async SQLAlchemy + asyncpg, live schema introspection; React 19 + Vite + TS + Tailwind frontend (`QueryInput`, `SqlPanel`, `ResultsTable`, `ResultsCards`, `ViewToggle`); `docker-compose.yml` for Sakila.
- **Restructure:** source moved under `backend/app/` (`main`, `api/routes`, `models/schemas`, `config`, `database`); `backend/tests/` skeleton; uvicorn command is `uvicorn app.main:app`.
- **Phase 1:** `sql_validator.validate_sql()` (sqlglot) and `pipeline.run_pipeline()` with a self-correction loop (max 3 attempts); `attempts` in the API response; amber "Self-corrected" badge in `SqlPanel`.
- **Phase 2:** ChromaDB RAG for schema + few-shot examples (to be removed in Phase A).
- **Phase 3:** FK relationships appended to the schema; complexity detection; few-shot examples passed to correction; empty-result retry; `max_tokens` 1024; seed examples expanded to 18 (CTEs, window functions, INTERSECT, subqueries, date math).
