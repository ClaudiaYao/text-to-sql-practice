# SQL Copilot — Text-to-SQL Web App

A chat window where you ask questions about the [Sakila](https://dev.mysql.com/doc/sakila/en/) PostgreSQL database in plain English. The backend turns each question into SQL, runs it **read-only**, and replies with both the data (table or cards) and a natural-language answer. Conversations are stored on the server and shown in a history sidebar.

> **Accuracy status:** the target is 99% execution accuracy on the golden test set (`backend/tests/golden/`). Use the live runner (see [Tests](#tests)) to measure it; "99%" means accuracy on that set, not a guarantee for arbitrary questions.

## Stack

| Layer    | Technology                                                       |
| -------- | ---------------------------------------------------------------- |
| Frontend | React 19 + Vite + TypeScript + Tailwind CSS                      |
| Backend  | FastAPI (Python), async SQLAlchemy + asyncpg, sqlglot            |
| Database | PostgreSQL — Sakila preloaded via Docker                         |
| AI       | AWS Bedrock (Claude, Converse API) — the only LLM provider       |
| History  | SQLite file (`backend/data/history/`, gitignored)                |

---

## Quick start

### 1. Start the database

```bash
docker run -p 5432:5432 --rm rsundqvist/sakila-preload:postgres
# or
docker compose up -d
```

The image only has the `postgres` superuser. Create the read-only `sakila` login that `.env` expects (once per fresh container):

```bash
docker exec -i $(docker compose ps -q sakila-db) psql -U postgres -d sakila < backend/scripts/create_readonly_role.sql
```

### 2. Configure the backend

```bash
cp backend/.env.example backend/.env
# Credentials come from the standard AWS chain (aws configure / aws sso login).
# Set AWS_REGION, AWS_PROFILE (optional) and BEDROCK_MODEL_ID in backend/.env,
# and enable the model under Bedrock > Model access in the AWS console.
# Never put AWS access keys in .env. Restart the server after editing it.
```

Every value comes from `backend/.env` (no hard-coded defaults); a missing required key stops startup and names the key. The keys are: `DATABASE_URL`; `AWS_REGION`, `AWS_PROFILE` (optional), `BEDROCK_MODEL_ID`; `QUERY_TIMEOUT_MS`, `MAX_ROWS`; `MAX_ATTEMPTS`, `FEWSHOT_TOP_K`, `COMPLEX_CANDIDATES`, `CANDIDATE_TEMPERATURE`; `CACHE_ENABLED`, `CACHE_MAX_ENTRIES`, `SQL_CACHE_TTL_SECONDS`, `ANSWER_CACHE_TTL_SECONDS`, `SCHEMA_CACHE_TTL_SECONDS`, `CACHE_PERSIST_PATH` (optional); `HISTORY_DB_PATH` (optional); `CORS_ORIGINS`.

### 3. Start the backend

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
# API available at http://localhost:8000
```

### 4. Start the frontend

```bash
cd frontend
npm install
npm run dev
# UI available at http://localhost:5173
```

---

## How it works

Everything runs in `backend/app/services/pipeline.py` (`run_pipeline`):

1. **Follow-ups:** a chat follow-up ("now only Canada") is rewritten by the LLM into a standalone question.
2. **SQL cache:** keyed on the schema hash + normalised question. A hit skips SQL generation but the SQL is **re-executed**, so data is never stale. A cached SQL that fails is evicted.
3. **Context:** the full introspected schema (tables, PK/FK, enums, value lists of small lookup tables), hand-written Sakila notes (`domain_notes.py`) and a few worked examples picked by keyword + SQL-technique match (`examples.py`, no embeddings).
4. **Generation:** a simple question gets one greedy candidate. A "complex" one (keyword rules in `is_complex`: rank, never, percent, "than the average", long questions, ...) gets a plan-then-SQL prompt and `COMPLEX_CANDIDATES` candidates (1 greedy + sampled).
5. **Validate + execute:** every candidate is checked by sqlglot (one read-only statement, no DML, no system schemas/functions, no `password`/`picture` columns) and run on a read-only connection with a statement timeout and a `MAX_ROWS` cap.
6. **Vote:** candidates are grouped by their *result set* (order- and column-name-insensitive). A non-empty group beats an empty one, then the larger group wins, then the earliest (greedy) candidate. `agreement` is returned.
7. **Self-correction:** if no candidate ran, the exact database/validator error goes back to the LLM, up to `MAX_ATTEMPTS`. A 0-row winner is checked by an LLM judge and may get one correction round.
8. **Answer:** non-empty results cache their SQL; the natural-language answer is cached on (question, actual rows).

Requests that cannot or must not be answered (e.g. "delete customer 5") are refused: HTTP 422. The system is **read-only by design** (validator + read-only transactions + a read-only database role). After a wrong answer or a prompt/notes change, clear the cache with `DELETE /api/cache`.

Where to fix accuracy problems: a systematic mistake → `services/domain_notes.py` or a rule in `services/prompts.py`; a pattern the model gets wrong → add a verified example to `data/seed/sakila_examples.json`; then clear the cache.

---

## Project layout

```
text-to-sql-practice/
├── backend/
│   ├── app/
│   │   ├── main.py, config.py, database.py, constants.py
│   │   ├── api/routes.py            # endpoints
│   │   ├── models/schemas.py
│   │   └── services/
│   │       ├── pipeline.py          # the whole question → SQL → answer flow
│   │       ├── llm.py               # Bedrock Converse + generate/correct/rewrite/judge/summarize
│   │       ├── prompts.py           # prompt templates and SQL-writing rules
│   │       ├── domain_notes.py      # hand-written Sakila semantics injected into prompts
│   │       ├── schema.py            # cached live schema introspection
│   │       ├── examples.py          # few-shot selection
│   │       ├── sql_validator.py     # sqlglot read-only validation
│   │       ├── history.py           # SQLite chat store
│   │       ├── cache.py             # SQL cache + answer cache
│   │       └── aws.py               # cached boto3 bedrock-runtime client
│   ├── data/seed/sakila_examples.json   # curated (question, SQL) pairs
│   ├── scripts/create_readonly_role.sql
│   ├── tests/                       # unit tests + golden set (tests/golden/)
│   └── requirements.txt, requirements-dev.txt
├── frontend/
│   └── src/
│       ├── App.tsx                  # chat view + history sidebar
│       ├── api.ts, types.ts
│       └── components/
│           ├── QueryInput.tsx       # textarea + example chips
│           ├── HistorySidebar.tsx   # conversation list, new chat, delete
│           ├── ChatMessage.tsx      # user/assistant bubbles (answer, badges, SQL, results)
│           ├── AnswerText.tsx       # renders **bold**, `code`, bullets in the answer
│           ├── SqlPanel.tsx         # collapsible SQL display
│           ├── ResultsTable.tsx     # tabular result view
│           ├── ResultsCards.tsx     # card grid result view
│           └── ViewToggle.tsx       # table ↔ card toggle
├── note/                            # this README and working notes
└── docker-compose.yml
```

## API

| Endpoint                       | Method | Description                                                                  |
| ------------------------------ | ------ | ---------------------------------------------------------------------------- |
| `/health`                      | GET    | Health check                                                                 |
| `/api/query`                   | POST   | Stateless: question → SQL → data + natural-language answer                   |
| `/api/chat`                    | POST   | Same, stored in a conversation so follow-ups ("now only Canada") work        |
| `/api/conversations`           | GET    | List stored conversations                                                    |
| `/api/conversations/{id}`      | GET    | One conversation with its messages (each assistant message holds the result) |
| `/api/conversations/{id}`      | DELETE | Delete a conversation                                                        |
| `/api/schema`                  | GET    | Schema text the LLM sees (debug)                                             |
| `/api/cache/stats`             | GET    | Cache hit/miss statistics                                                    |
| `/api/cache`                   | DELETE | Clear cached SQL and answers (does not touch chat history)                   |

```json
POST /api/chat
{ "message": "and for Canada?", "conversation_id": "<id from a previous reply, omit to start a new chat>" }
```

With a `conversation_id` the **server** loads the last 20 successful messages as context. The optional `history` array (`[{"role", "content"}]`) is only a fallback for a brand-new conversation. There is no authentication: every client sees every conversation.

Response fields: `answer`, `sql`, `columns`, `rows`, `row_count`, `truncated`, `execution_ms`, `attempts`
(0 = SQL served from cache), `cached`, `complex`, `candidates`, `agreement`, `standalone_question`, `conversation_id` (`/api/chat` only).

Error codes: 422 the request was refused/unanswerable, 400 no runnable SQL after all attempts, 502 the LLM call failed. A failed `/api/chat` turn is stored too, and its error body is `{detail, conversation_id}`.

## Tests

Run from `backend` with the venv active (no AWS needed; DB tests skip if Postgres is down; the live eval is deselected by default):

```bash
cd backend
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest                                   # everything except the live eval
pytest tests/test_api.py                 # one file
pytest -k "cache"                        # tests whose name matches a keyword
pytest -v                                # list each test as it runs
```

### Coverage

```bash
pip install pytest-cov                              # not in requirements-dev.txt yet
pytest --cov=app --cov-report=term-missing          # per-file table; "Missing" lists uncovered lines
pytest --cov=app --cov-report=html                  # browsable report: open htmlcov/index.html
pytest --cov=app --cov-branch                       # also measure if/else branches
pytest --cov=app --cov-fail-under=80                # fail if total coverage is below 80%
```

Start Postgres first (`docker compose up -d`), otherwise the DB-marked tests skip and coverage of `schema.py` / `database.py` drops. `.coverage` and `htmlcov/` are generated files.

### Live accuracy evaluation (needs Postgres + Bedrock credentials)

```bash
python -m tests.golden.runner                       # whole 100-question golden set
python -m tests.golden.runner --split dev           # tune on this
python -m tests.golden.runner --split heldout       # look at rarely, to detect overfitting
python -m tests.golden.runner --tier joins          # only one tier (simple, joins, aggregation, complex, dates, edge, followup, unanswerable, unsafe)
pytest -m eval -s                                   # same eval via pytest; GOLDEN_THRESHOLD env var, default 0.99
```

First run against a fresh Sakila container: `docker exec -i $(docker compose ps -q sakila-db) psql -U postgres -d sakila < backend/scripts/create_readonly_role.sql`.
