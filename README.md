## arxiv-paper-rag

An experimental local workflow for collecting arXiv papers, ingesting them into PostgreSQL + pgvector, and searching them through a RAG pipeline with both CLI and web interfaces.

Chinese documentation: [README.zh-CN.md](README.zh-CN.md)

## What This Repository Contains

- `ArXiv_craw/crawer.py`
  Searches arXiv, downloads PDFs, and writes metadata JSONL.
- `local_paper_db/app/in.py`
  Embeds paper summaries with Ollama and stores them in PostgreSQL + pgvector.
- `local_paper_db/app/search.py`
  Thin CLI wrapper for the search pipeline.
- `local_paper_db/app/search_service.py`
  Reusable search service shared by CLI and FastAPI.
- `backend/main.py`
  FastAPI app for config management, search APIs, SSE answer streaming, and ingest management.
- `frontend/`
  React + Vite workbench for search and ingest operations.

## Search Pipeline

The search flow is:

1. The user submits a question.
2. `QUERY_CHAT_*` rewrites it into an English retrieval plan.
3. The user confirms the rewrite, asks for refinement, or chooses the original question.
4. Ollama generates an embedding for the confirmed retrieval text.
5. PostgreSQL + pgvector retrieves top `50` papers.
6. SiliconFlow reranks them with `BAAI/bge-reranker-v2-m3` and keeps top `10`.
7. `ANSWER_CHAT_*` answers only from those 10 papers.

Fallback behavior:

- If rewrite fails, the system falls back to the original question.
- If reranking fails, the system falls back to the top 10 vector-search results.

## Web Workbench

The FastAPI + React workbench exposes two tabs:

- `Search Workspace`
  Configure query chat, answer chat, rerank, embedding, and retrieval settings; generate and refine rewrites; inspect top-10 papers; stream the final answer.
- `Ingest Manager`
  Start `in.py` as a background job, inspect database counts, and watch ingest logs over SSE.

The frontend also includes an English / Chinese language switch and remembers the last selected UI language in the browser.

Configuration precedence is:

1. Request-level settings from the frontend
2. `config/runtime_settings.json`
3. Environment variables

API keys are write-only in the UI. The backend only returns `has_api_key: true/false`.
For safety, commit only [`config/runtime_settings.example.json`](config/runtime_settings.example.json); keep the real `config/runtime_settings.json` local.

## Repository Structure

```text
.
|-- ArXiv_craw/
|   |-- crawer.py
|   `-- arxiv_papers_rag/
|-- backend/
|   |-- config_store.py
|   |-- ingest_manager.py
|   |-- main.py
|   `-- schemas.py
|-- config/
|   `-- runtime_settings.json
|-- frontend/
|   |-- package.json
|   |-- src/
|   `-- vite.config.js
|-- local_paper_db/
|   `-- app/
|       |-- in.py
|       |-- search.py
|       `-- search_service.py
|-- pyproject.toml
|-- requirements.txt
|-- README.md
`-- README.zh-CN.md
```

## Requirements

- Python `3.13`
- Node.js `20+`
- PostgreSQL with `pgvector`
- Ollama running at `http://localhost:11434`
- An Ollama embedding model matching `OLLAMA_EMBED_MODEL`
- Optional local Ollama chat model for generation
- A SiliconFlow API key if you want API reranking
- Optional OpenAI-compatible API credentials if you want remote chat models

## Installation

### Python

```bash
python -m venv .venv
```

Activate the virtual environment:

```bash
# macOS / Linux
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1

# Windows cmd.exe
.venv\Scripts\activate.bat
```

Then install dependencies:

```bash
pip install -r requirements.txt
```

### Frontend

```bash
cd frontend
npm install
```

## Database Preparation

The ingestion script creates tables automatically, but PostgreSQL still needs required extensions:

```sql
CREATE DATABASE pacoman;
\c pacoman
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
```

Defaults:

- database: `pacoman`
- host: `localhost`
- port: `5433`

Override them with `PAPER_DB_*` environment variables if needed.

## Environment Variables

### Database and embeddings

- `PAPER_DB_NAME`
- `PAPER_DB_USER`
- `PAPER_DB_PASSWORD`
- `PAPER_DB_HOST`
- `PAPER_DB_PORT`
- `OLLAMA_API_URL`
- `OLLAMA_EMBED_MODEL`

### Query rewrite chat model

- `QUERY_CHAT_PROVIDER`
  `ollama` or `openai_compatible`
- `QUERY_CHAT_MODEL`
- `QUERY_CHAT_BASE_URL`
- `QUERY_CHAT_API_KEY`

### Final answer chat model

- `ANSWER_CHAT_PROVIDER`
  `ollama` or `openai_compatible`
- `ANSWER_CHAT_MODEL`
- `ANSWER_CHAT_BASE_URL`
- `ANSWER_CHAT_API_KEY`

### Rerank API

- `RERANK_API_KEY`
- `RERANK_BASE_URL`
  Default: `https://api.siliconflow.cn/v1`
- `RERANK_MODEL`
  Default: `BAAI/bge-reranker-v2-m3`

## Usage

### 1. Download papers

```bash
cd ArXiv_craw
python crawer.py
```

### 2. Ingest embeddings into PostgreSQL

```bash
cd local_paper_db/app
python in.py
```

### 3. Search from CLI

Interactive mode:

```bash
cd local_paper_db/app
python search.py
```

Single-query mode:

```bash
cd local_paper_db/app
python search.py "What is agentic RAG?"
```

Both modes still pause at the rewrite-confirmation step. You can:

1. Use the optimized query
2. Ask the model to improve the rewrite
3. Use the original question

### 4. Run the FastAPI backend

```bash
uvicorn backend.main:app --reload
```

### 5. Run the React frontend

```bash
cd frontend
npm run dev
```

Default dev URLs:

- Backend: `http://127.0.0.1:8000`
- Frontend: `http://127.0.0.1:5173`

### 6. Production frontend build

```bash
cd frontend
npm run build
```

If `frontend/dist` exists, FastAPI serves the built SPA automatically.

## macOS Notes

- The codebase is mostly cross-platform. The main platform-sensitive services are PostgreSQL + `pgvector`, Ollama, Python, and Node.js.
- New crawler runs now write `pdf_local_path` using portable `/` separators, so metadata generated on macOS, Linux, and Windows stays consistent.
- During ingestion, existing metadata with Windows-style `\` separators is normalized automatically before being written to PostgreSQL.
- If you migrate an existing Windows dataset to macOS, re-ingesting the JSONL metadata is recommended so the stored file paths are normalized.

## Notes About Providers

- Ollama is still used for embeddings.
- Query planning can use Ollama or any OpenAI-compatible API.
- Final answer generation can use Ollama or any OpenAI-compatible API.
- Reranking uses the SiliconFlow rerank API instead of local `FlagEmbedding`.

## Main Entry Points

- [`ArXiv_craw/crawer.py`](ArXiv_craw/crawer.py)
- [`local_paper_db/app/in.py`](local_paper_db/app/in.py)
- [`local_paper_db/app/search.py`](local_paper_db/app/search.py)
- [`backend/main.py`](backend/main.py)
