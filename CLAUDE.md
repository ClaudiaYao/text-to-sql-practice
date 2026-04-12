# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development commands

### Database (required first)
```bash
docker run -p 5432:5432 --rm rsundqvist/sakila-preload:postgres
# or
docker compose up -d
```

### Backend
```bash
cd backend
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload                     # http://localhost:8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev      # http://localhost:5173
npm run build    # type-check + production build
npm run lint     # ESLint
```

## Architecture

The request flow is: **user question → FastAPI → live schema fetch → LLM → SQL → PostgreSQL → JSON → React UI**.

### Backend (`backend/`)

```
backend/
├── app/
│   ├── main.py           # App factory: creates FastAPI instance, registers middleware & router
│   ├── config.py         # Pydantic Settings (reads backend/.env)
│   ├── database.py       # Async SQLAlchemy engine, get_db(), get_schema_description(), execute_query()
│   ├── api/
│   │   └── routes.py     # All endpoint handlers: POST /api/query, GET /api/schema, GET /health
│   ├── models/
│   │   └── schemas.py    # Pydantic request/response models (QueryRequest, QueryResponse)
│   └── agent/
│       └── gemini.py     # LLM abstraction: generate_sql() → Azure or Vertex AI (Phase 1 & 2 expand here)
├── data/
│   ├── vector_store/     # ChromaDB persisted collections (Phase 2)
│   └── seed/
│       └── sakila_examples.json  # Curated (question, SQL) pairs for few-shot RAG (Phase 2)
└── tests/
```

- **`app/main.py`** — thin app factory only; no business logic
- **`app/api/routes.py`** — orchestrates the query pipeline: schema fetch → LLM → execute SQL → return results
- **`app/agent/gemini.py`** — `generate_sql()` dispatches to `_azure_generate()` or `_vertexai_generate()` based on `LLM_PROVIDER`. System prompt enforces SELECT-only output; `_strip_sql()` handles markdown fences. LLM signals failure with `ERROR: <reason>` → raised as `ValueError`.
- **`app/database.py`** — `get_schema_description()` introspects `information_schema.columns` at query time; result is injected into LLM system prompt. `execute_query()` returns `(columns, rows)`.

### Frontend (`frontend/src/`)

- **`App.tsx`** — top-level state: `loading`, `error`, `result`, `viewMode`. Calls `api.ts` and fans out to child components.
- **`api.ts`** — single `runQuery()` function. In dev, Vite proxies `/api` → `localhost:8000` (configured in `vite.config.ts`), so no absolute URL is needed.
- Components are stateless display units: `QueryInput` (textarea + example chips), `SqlPanel` (collapsible SQL with copy), `ResultsTable` / `ResultsCards` (two views of the same data), `ViewToggle` (switches between them).

## Environment configuration

All backend config lives in `backend/.env` (copy from `backend/.env.example`). Key variables:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | asyncpg connection string for the Sakila container |
| `LLM_PROVIDER` | `azure` (default) or `vertexai` |
| `AZURE_OPENAI_ENDPOINT` / `AZURE_OPENAI_API_KEY` | Azure AI Foundry credentials |
| `AZURE_OPENAI_DEPLOYMENT` | Model deployment name (default: `gpt-4o`) |
| `VERTEXAI_PROJECT` / `VERTEXAI_LOCATION` / `VERTEXAI_MODEL` | GCP Vertex AI config |

Switching to Vertex AI requires `pip install google-cloud-aiplatform`.

## LLM prompt design

Two prompt templates live in `app/agent/gemini.py`:
- `_GENERATION_SYSTEM_PROMPT` — initial SQL generation (SELECT-only, no fences, limit 200 rows)
- `_CORRECTION_SYSTEM_PROMPT` + `_CORRECTION_USER_PROMPT` — targeted fix prompt; includes the failed SQL and error message

When changing query constraints or rules, edit these templates. Do not hardcode schema elsewhere.

## Agentic pipeline (Phase 1)

`app/agent/pipeline.py:run_pipeline()` is the single entry point called by the route.

```
question
  → get_schema_description()          # live DB introspection
  → generate_sql()                    # LLM call 1
  → validate_sql()                    # sqlglot: syntax + SELECT-only check
  → execute_query()                   # hit PostgreSQL
  → on failure: correct_sql() → re-validate → re-execute   (up to MAX_RETRIES=3 total)
  → PipelineResult(sql, columns, rows, attempts)
```

- `ValueError` from `generate_sql`/`correct_sql` (LLM `ERROR:` signal) short-circuits immediately — no retries
- `PipelineError` is raised when all retries are exhausted
- `attempts` is returned in the API response and shown as a badge in the UI when > 1

Phase 2 will add RAG schema retrieval and few-shot example retrieval (ChromaDB + Vertex AI embeddings).

## Changelog

> Update this section after every change so future Claude instances know what is done.

### 2026-04-12 — Initial build
- **Backend:** FastAPI app with `POST /api/query`, `GET /api/schema`, `GET /health`; async SQLAlchemy + asyncpg; live schema introspection; Azure AI Foundry + GCP Vertex AI LLM abstraction
- **Frontend:** React 19 + Vite + TypeScript + Tailwind CSS; components: `QueryInput`, `SqlPanel`, `ResultsTable`, `ResultsCards`, `ViewToggle`; Vite dev proxy for `/api`
- **Infra:** `docker-compose.yml` for Sakila PostgreSQL; `backend/.env.example` with all supported config vars

### 2026-04-12 — Phase 1: Agentic self-correction loop
- **New** `app/agent/sql_validator.py` — `validate_sql()` using `sqlglot` (syntax check + SELECT-only guard)
- **New** `app/agent/pipeline.py` — `run_pipeline()` orchestrates: generate → validate → execute → self-correct (up to 3 attempts)
- **Updated** `app/agent/gemini.py` — added `correct_sql()` with dedicated correction prompt; refactored to single `_call_llm()` dispatcher; two separate system prompts (generation vs correction)
- **Updated** `app/api/routes.py` — endpoint now calls `run_pipeline()` instead of raw `generate_sql` + `execute_query`
- **Updated** `app/models/schemas.py` + `frontend/src/types.ts` — `attempts: int` added to response
- **Updated** `frontend/src/components/SqlPanel.tsx` — amber "Self-corrected · N attempts" badge shown when `attempts > 1`
- **Updated** `requirements.txt` — added `sqlglot==25.24.5`

### 2026-04-12 — Backend restructure (standalone, no logic changes)
- Moved all Python source under `backend/app/` following FastAPI `app/` convention
- Split `main.py` into: `app/main.py` (app factory), `app/api/routes.py` (endpoints), `app/models/schemas.py` (Pydantic models)
- Renamed `llm.py` → `app/agent/gemini.py`; moved `config.py` → `app/config.py`; moved `database.py` → `app/database.py`
- Added `backend/data/seed/sakila_examples.json` — 8 curated Sakila Q&A pairs (ready for Phase 2 few-shot RAG)
- Added `backend/data/vector_store/` placeholder (ready for Phase 2 ChromaDB)
- Added `backend/tests/` package skeleton
- **Uvicorn command changed:** `uvicorn main:app` → `uvicorn app.main:app`
