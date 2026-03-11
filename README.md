## arxiv-paper-rag

An experimental local RAG workflow for arXiv papers. The repository currently combines two scripts:

- `ArXiv_craw/crawer.py`: searches arXiv for papers related to Retrieval-Augmented Generation, downloads PDFs, and stores paper metadata as JSONL.
- `local_paper_db/app/in.py` and `local_paper_db/app/search.py`: ingest the metadata into PostgreSQL with `pgvector`, then run retrieval + reranking + Ollama-based answer generation.

Chinese documentation: [README.zh-CN.md](README.zh-CN.md)

## What It Does

This project implements a simple end-to-end paper assistant:

1. Search arXiv with a fixed keyword and category.
2. Download matching PDFs to a local folder.
3. Save metadata such as title, authors, abstract, local PDF path, and arXiv URL.
4. Generate embeddings with Ollama and write them into PostgreSQL/pgvector.
5. Retrieve relevant papers with vector search.
6. Rerank the retrieved candidates with `BAAI/bge-reranker-v2-m3`.
7. Ask an Ollama chat model to answer questions grounded in the retrieved paper summaries.

## Repository Structure

```text
.
|-- ArXiv_craw/
|   |-- crawer.py
|   |-- pyproject.toml
|   `-- arxiv_papers_rag/        # local PDFs + metadata output, generated data
|-- local_paper_db/
|   `-- app/
|       |-- in.py                # ingestion script
|       |-- search.py            # local RAG search CLI
|       |-- metadata_log.jsonl   # example/generated metadata
|       `-- ingest_error.log
|-- requirements.txt
|-- pyproject.toml
|-- README.md
`-- README.zh-CN.md
```

## Architecture

```text
arXiv API
  -> crawer.py
  -> metadata_log.jsonl + PDFs
  -> in.py
  -> PostgreSQL + pgvector
  -> search.py
  -> reranker + Ollama
  -> final answer
```

## Requirements

- Python `3.13` according to `.python-version` and `pyproject.toml`
- PostgreSQL with the `pgvector` extension enabled
- A working Ollama service on `http://localhost:11434`
- Ollama models matching the hardcoded names in the scripts:
  - `qwen3-embedding:0.6b` in [`local_paper_db/app/in.py`](local_paper_db/app/in.py)
  - `qwen3-embedding` and `qwen3:0.6b` in [`local_paper_db/app/search.py`](local_paper_db/app/search.py)
- Enough disk space for downloaded PDFs
- Optional but recommended: GPU support for reranking and Ollama inference

## Installation

Create a virtual environment and install dependencies:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

If `FlagEmbedding` does not install a compatible `torch` build automatically in your environment, install the correct `torch` package first and then rerun `pip install -r requirements.txt`.

## Database Preparation

Create a database and enable the required extensions before running ingestion. The ingestion script creates the tables, but your database still needs `vector`, and `gen_random_uuid()` must be available.

Example:

```sql
CREATE DATABASE paper_db;
\c paper_db
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
```

Important: the current scripts use hardcoded database settings and they do not match each other out of the box.

- [`local_paper_db/app/in.py`](local_paper_db/app/in.py) uses database `pacoman` on port `5433`
- [`local_paper_db/app/search.py`](local_paper_db/app/search.py) uses database `paper_db` on port `5432`

Before running the project, edit those constants so both scripts point to the same PostgreSQL instance.

## Usage

### 1. Download arXiv papers

The crawler uses fixed settings inside [`ArXiv_craw/crawer.py`](ArXiv_craw/crawer.py):

- keyword: `Retrieval Augmented Generation`
- category: `cs.CL`
- max results: `100`

Run:

```bash
cd ArXiv_craw
python crawer.py
```

Outputs:

- PDFs in `ArXiv_craw/arxiv_papers_rag/`
- metadata in `ArXiv_craw/arxiv_papers_rag/metadata_log.jsonl`

### 2. Ingest metadata into PostgreSQL

The ingestion script reads `metadata_log.jsonl` from its current working directory. The repository currently also includes a copied/generated file at `local_paper_db/app/metadata_log.jsonl`.

If you just crawled fresh data, copy the JSONL file or change `METADATA_FILE` in the script.

Run:

```bash
cd local_paper_db/app
python in.py
```

What it does:

- checks Ollama embedding dimension dynamically
- creates `papers_meta` and `papers_embeddings`
- skips already ingested `arxiv_id` values
- batches embedding writes into PostgreSQL

### 3. Query the local RAG system

Run:

```bash
cd local_paper_db/app
python search.py
```

Then enter a research question in the terminal. The script will:

- embed the query with Ollama
- retrieve top `50` candidates from PostgreSQL
- rerank the candidates and keep top `5`
- stream the final answer from Ollama

Enter `q` to exit.

## Current Data Snapshot

At the time of writing, the local workspace contains:

- `100` downloaded PDFs under `ArXiv_craw/arxiv_papers_rag/`
- `99` metadata rows in `local_paper_db/app/metadata_log.jsonl`

These files are generated artifacts and are ignored by default for Git pushes.

## Known Limitations

- Configuration is hardcoded directly in Python files.
- The crawler, ingestion script, and search script do not share a single config source.
- `search.py` expects fields such as `summary_for_embedding` and `methodology`, while the crawler currently stores `summary`. Depending on your dataset, you may need to adjust the SQL query or enrich metadata before search.
- There is no web UI, API server, or automated test suite in the current repository.
- The repository is aimed at local experimentation, not production deployment.

## Suggested Improvements

- Move database and model settings into environment variables.
- Unify the metadata schema between crawl, ingest, and search.
- Add a setup script for PostgreSQL/pgvector.
- Add tests for ingestion and retrieval.
- Add a small sample dataset for reproducible demos.

## Verification

The Python files below were syntax-checked successfully in the local workspace:

- [`ArXiv_craw/crawer.py`](ArXiv_craw/crawer.py)
- [`local_paper_db/app/in.py`](local_paper_db/app/in.py)
- [`local_paper_db/app/search.py`](local_paper_db/app/search.py)
