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

The system prompt in `app/agent/gemini.py:_SYSTEM_PROMPT_TEMPLATE` receives the full live schema and instructs the model to output raw SQL only, SELECT-only, prefer JOINs, limit to 200 rows. When adding schema hints or query constraints, edit this template — do not hardcode schema elsewhere.

Phase 1 will add a self-correction loop and `sqlglot` validation inside `app/agent/`.
Phase 2 will add RAG schema retrieval and few-shot example retrieval (ChromaDB + Vertex AI embeddings).

## Changelog

> Update this section after every change so future Claude instances know what is done.

### 2026-04-12 — Initial build
- **Backend:** FastAPI app with `POST /api/query`, `GET /api/schema`, `GET /health`; async SQLAlchemy + asyncpg; live schema introspection; Azure AI Foundry + GCP Vertex AI LLM abstraction
- **Frontend:** React 19 + Vite + TypeScript + Tailwind CSS; components: `QueryInput`, `SqlPanel`, `ResultsTable`, `ResultsCards`, `ViewToggle`; Vite dev proxy for `/api`
- **Infra:** `docker-compose.yml` for Sakila PostgreSQL; `backend/.env.example` with all supported config vars

### 2026-04-12 — Backend restructure (standalone, no logic changes)
- Moved all Python source under `backend/app/` following FastAPI `app/` convention
- Split `main.py` into: `app/main.py` (app factory), `app/api/routes.py` (endpoints), `app/models/schemas.py` (Pydantic models)
- Renamed `llm.py` → `app/agent/gemini.py`; moved `config.py` → `app/config.py`; moved `database.py` → `app/database.py`
- Added `backend/data/seed/sakila_examples.json` — 8 curated Sakila Q&A pairs (ready for Phase 2 few-shot RAG)
- Added `backend/data/vector_store/` placeholder (ready for Phase 2 ChromaDB)
- Added `backend/tests/` package skeleton
- **Uvicorn command changed:** `uvicorn main:app` → `uvicorn app.main:app`
