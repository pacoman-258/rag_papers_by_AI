## arxiv-paper-rag

An experimental paper-retrieval workbench for collecting arXiv metadata, indexing local corpora in PostgreSQL + pgvector, and answering questions through a hybrid RAG pipeline that can combine local storage with live external sources such as arXiv and Web of Science.

Chinese documentation: [README.zh-CN.md](README.zh-CN.md)

## What This Repository Contains

- `ArXiv_craw/crawer.py`
  Searches arXiv, downloads PDFs, and writes metadata JSONL.
- `local_paper_db/app/in.py`
  Embeds paper summaries with Ollama and stores them in PostgreSQL + pgvector.
- `local_paper_db/app/search.py`
  Thin CLI wrapper for the search pipeline.
- `local_paper_db/app/search_service.py`
  Reusable search orchestration shared by CLI and FastAPI.
- `local_paper_db/app/external_sources.py`
  Adapters for arXiv and Web of Science metadata retrieval.
- `backend/main.py`
  FastAPI app for config management, search APIs, SSE answer streaming, and ingest management.
- `frontend/`
  React + Vite workbench for search, trace, provider toggles, and ingest operations.

## Search Pipeline

The search flow is:

1. The user submits a question.
2. `QUERY_CHAT_*` rewrites it into an English retrieval plan.
3. The user confirms the rewrite, asks for refinement, or chooses the original question.
4. Ollama generates an embedding for the confirmed retrieval text.
5. Enabled retrieval providers gather candidates:
   - `local`: PostgreSQL + pgvector vector search
   - `arxiv`: live metadata search through the arXiv API
   - `wos`: live metadata search through the Web of Science API
6. Candidates from all enabled providers are deduplicated into a unified coarse-ranking pool.
7. SiliconFlow reranks them with `BAAI/bge-reranker-v2-m3` and keeps top `10`.
8. `ANSWER_CHAT_*` answers only from those 10 papers.

Fallback behavior:

- If rewrite fails, the system falls back to the original question.
- If one provider fails, the system continues with the remaining enabled providers and surfaces a warning.
- If reranking fails, the system falls back to the top 10 vector-search results.
- If every enabled provider returns no usable candidates, the request fails with a clear search error.

## Web Workbench

The FastAPI + React workbench exposes two tabs:

- `Search Workspace`
  Configure query chat, answer chat, rerank, embedding, and retrieval settings; enable or disable `local`, `arxiv`, and `wos`; generate and refine rewrites; inspect top-10 papers with source badges and external links; and stream the final answer.
- `Ingest Manager`
  Start `in.py` as a background job, inspect local-database counts, and watch ingest logs over SSE.

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
|       |-- external_sources.py
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
- PostgreSQL with `pgvector` if you want the `local` retrieval provider
- Ollama running at `http://localhost:11434`
- An Ollama embedding model matching `OLLAMA_EMBED_MODEL`
- Optional local Ollama chat model for generation
- A SiliconFlow API key if you want API reranking
- Optional Web of Science API credentials if you want the `wos` provider
- Optional OpenAI-compatible API credentials if you want remote chat models

## Installation

### Python

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### Frontend

```bash
cd frontend
npm install
```

## Database Preparation

If you plan to use the `local` retrieval provider, PostgreSQL still needs the required extensions:

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

### Retrieval providers

- `RETRIEVAL_ENABLED_SOURCES`
  Comma-separated provider list such as `local,arxiv,wos`
- `RETRIEVAL_PROVIDER_LOCAL`
- `RETRIEVAL_PROVIDER_ARXIV`
- `RETRIEVAL_PROVIDER_WOS`
- `ARXIV_SEARCH_MAX_RESULTS`
- `ARXIV_SEARCH_TIMEOUT`
- `WOS_API_BASE_URL`
- `WOS_API_KEY`
- `WOS_SEARCH_MAX_RESULTS`
- `WOS_SEARCH_TIMEOUT`

The runtime settings example enables `local` and `arxiv` by default, while `wos` is disabled until valid credentials are configured. The same provider switches are also exposed in the web Settings page.

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

The CLI uses the same retrieval-provider settings as the backend service. If you want a live-source-only workflow, disable `local` and keep `arxiv` or `wos` enabled through `config/runtime_settings.json` or environment variables.

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

## Notes About Providers

- Ollama is still used for embeddings.
- Query planning can use Ollama or any OpenAI-compatible API.
- Final answer generation can use Ollama or any OpenAI-compatible API.
- Reranking uses the SiliconFlow rerank API instead of local `FlagEmbedding`.
- `local` is now optional rather than mandatory.
- arXiv retrieval is tuned for broader keyword-based metadata recall instead of exact full-sentence matching.
- Web of Science is supported as an optional provider and is expected to be quota- and credential-constrained.
- Search and trace responses now include retrieval provenance such as source badges, matched sources, and freshness hints.

## Main Entry Points

- [`ArXiv_craw/crawer.py`](ArXiv_craw/crawer.py)
- [`local_paper_db/app/in.py`](local_paper_db/app/in.py)
- [`local_paper_db/app/search.py`](local_paper_db/app/search.py)
- [`backend/main.py`](backend/main.py)
