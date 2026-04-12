# SQL Copilot — Text-to-SQL Web App

Ask questions in plain English, get SQL + results instantly against the [Sakila](https://dev.mysql.com/doc/sakila/en/) PostgreSQL database.

## Stack

| Layer | Technology |
|---|---|
| Frontend | React 19 + Vite + TypeScript + Tailwind CSS |
| Backend | FastAPI (Python) |
| Database | PostgreSQL — Sakila preloaded via Docker |
| AI | Azure AI Foundry (GPT-4o) or GCP Vertex AI |

---

## Quick start

### 1. Start the database

```bash
docker run -p 5432:5432 --rm rsundqvist/sakila-preload:postgres
# or
docker compose up -d
```

### 2. Configure the backend

```bash
cp backend/.env.example backend/.env
# Edit backend/.env and fill in your Azure AI Foundry credentials:
#   AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com/
#   AZURE_OPENAI_API_KEY=<your-key>
#   AZURE_OPENAI_DEPLOYMENT=gpt-4o
```

To use **GCP Vertex AI** instead, set `LLM_PROVIDER=vertexai` and fill the `VERTEXAI_*` variables, then install the extra dependency:
```bash
pip install google-cloud-aiplatform
```

### 3. Start the backend

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
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

## Project layout

```
text-to-sql-practice/
├── backend/
│   ├── main.py         # FastAPI app + endpoints
│   ├── database.py     # Async SQLAlchemy + schema introspection
│   ├── llm.py          # Azure / Vertex AI abstraction
│   ├── config.py       # Pydantic settings (reads .env)
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── App.tsx
│       ├── api.ts
│       ├── types.ts
│       └── components/
│           ├── QueryInput.tsx   # textarea + example chips
│           ├── SqlPanel.tsx     # collapsible SQL display
│           ├── ResultsTable.tsx # tabular result view
│           ├── ResultsCards.tsx # card grid result view
│           └── ViewToggle.tsx   # table ↔ card toggle
└── docker-compose.yml
```

## API

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Health check |
| `/api/query` | POST | Convert question → SQL → execute → return results |
| `/api/schema` | GET | Return raw DB schema (debug) |

`POST /api/query` body:
```json
{ "question": "Show top 10 customers by total payment" }
```
