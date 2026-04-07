from __future__ import annotations

import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import psycopg2
import requests
from psycopg2 import extras, pool
from psycopg2.extras import Json
from tqdm import tqdm


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from local_paper_db.app.search_service import DEFAULT_DB_CONFIG, get_env_default_settings


SCRIPT_DIR = Path(__file__).resolve().parent
SETTINGS = get_env_default_settings()
DB_CONFIG = DEFAULT_DB_CONFIG
OLLAMA_URL = f"{SETTINGS.embedding.api_url}/embeddings"
OLLAMA_MODEL = SETTINGS.embedding.model
BATCH_SIZE = int(os.getenv("INGEST_BATCH_SIZE", "50"))
MAX_WORKERS = int(os.getenv("INGEST_MAX_WORKERS", "4"))
METADATA_FILE = os.getenv("INGEST_METADATA_FILE", "metadata_log.jsonl")
LOG_FILE = SCRIPT_DIR / "ingest_error.log"


logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.ERROR,
    format="%(asctime)s - %(message)s",
)


def resolve_metadata_path() -> Path:
    metadata_path = Path(METADATA_FILE)
    if metadata_path.is_absolute():
        return metadata_path
    return SCRIPT_DIR / metadata_path


try:
    db_pool = pool.SimpleConnectionPool(minconn=1, maxconn=MAX_WORKERS + 2, **DB_CONFIG)
except Exception as exc:  # pragma: no cover
    print(f"Failed to connect to PostgreSQL: {exc}")
    raise SystemExit(1) from exc


def get_db_conn():
    return db_pool.getconn()


def release_db_conn(conn) -> None:
    db_pool.putconn(conn)


def check_model_dimension() -> int:
    print(f"Checking embedding model dimension for '{OLLAMA_MODEL}'...")
    try:
        response = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": "dimension probe"},
            timeout=60,
        )
        response.raise_for_status()
        embedding = response.json().get("embedding")
        if not embedding:
            raise RuntimeError("Embedding API returned no vector.")
        dimension = len(embedding)
        print(f"Embedding dimension: {dimension}")
        return dimension
    except Exception as exc:
        print(f"Failed to reach Ollama embedding API: {exc}")
        raise SystemExit(1) from exc


def ensure_schema(dimension: int) -> None:
    conn = get_db_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            cursor.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS papers_meta (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    arxiv_id VARCHAR(50) UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    authors TEXT[],
                    published_date DATE,
                    primary_category TEXT,
                    pdf_local_path TEXT,
                    extracted_insights JSONB,
                    created_at TIMESTAMP DEFAULT NOW()
                );
                """
            )
            cursor.execute("ALTER TABLE papers_meta ADD COLUMN IF NOT EXISTS primary_category TEXT;")
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS papers_embeddings (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    paper_id UUID REFERENCES papers_meta(id) ON DELETE CASCADE,
                    embedding_type VARCHAR(50),
                    text_content TEXT,
                    embedding vector({dimension})
                );
                """
            )
            cursor.execute(
                """
                UPDATE papers_meta
                SET primary_category = COALESCE(primary_category, extracted_insights->>'primary_category')
                WHERE primary_category IS NULL;
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_papers_vec_hnsw
                ON papers_embeddings USING hnsw (embedding vector_cosine_ops);
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_papers_meta_published_date
                ON papers_meta (published_date DESC);
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_papers_meta_primary_category
                ON papers_meta (primary_category);
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_papers_meta_authors_gin
                ON papers_meta USING gin (authors);
                """
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        release_db_conn(conn)


def fetch_existing_ids() -> set[str]:
    conn = get_db_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT arxiv_id FROM papers_meta;")
            return {row[0] for row in cursor.fetchall()}
    finally:
        release_db_conn(conn)


def process_single_paper(line_data: str):
    try:
        meta = json.loads(line_data)
        arxiv_id = meta.get("arxiv_id")
        title = meta.get("title")
        text_to_embed = meta.get("summary") or title or ""
        if not text_to_embed:
            return False, None, f"Skipped {arxiv_id}: no text to embed."

        response = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": text_to_embed},
            timeout=60,
        )
        response.raise_for_status()
        embedding = response.json().get("embedding")
        if not embedding:
            return False, None, f"Skipped {arxiv_id}: embedding API returned no vector."

        db_payload = {
            "meta": {
                "arxiv_id": arxiv_id,
                "title": title,
                "authors": meta.get("authors", []),
                "published_date": meta.get("published_date"),
                "primary_category": meta.get("primary_category"),
                "pdf_local_path": meta.get("pdf_local_path"),
                "extracted_insights": Json(meta),
            },
            "vector": {
                "embedding_type": "summary",
                "text_content": text_to_embed,
                "embedding": embedding,
            },
        }
        return True, db_payload, None
    except Exception as exc:  # pragma: no cover
        return False, None, str(exc)


def batch_insert_to_db(batch_data: list[dict[str, object]]) -> None:
    if not batch_data:
        return

    conn = get_db_conn()
    try:
        with conn.cursor() as cursor:
            paper_id_map: dict[str, object] = {}
            for item in batch_data:
                meta = item["meta"]
                cursor.execute(
                    """
                    INSERT INTO papers_meta (
                        arxiv_id,
                        title,
                        authors,
                        published_date,
                        primary_category,
                        pdf_local_path,
                        extracted_insights
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (arxiv_id) DO UPDATE SET
                        title = EXCLUDED.title,
                        authors = EXCLUDED.authors,
                        published_date = EXCLUDED.published_date,
                        primary_category = COALESCE(EXCLUDED.primary_category, papers_meta.primary_category),
                        pdf_local_path = EXCLUDED.pdf_local_path,
                        extracted_insights = EXCLUDED.extracted_insights
                    RETURNING arxiv_id, id;
                    """,
                    (
                        meta["arxiv_id"],
                        meta["title"],
                        meta["authors"],
                        meta["published_date"],
                        meta["primary_category"],
                        meta["pdf_local_path"],
                        meta["extracted_insights"],
                    ),
                )
                row = cursor.fetchone()
                if row:
                    paper_id_map[row[0]] = row[1]

            vector_rows = []
            for item in batch_data:
                arxiv_id = item["meta"]["arxiv_id"]
                if arxiv_id not in paper_id_map:
                    continue
                vector = item["vector"]
                vector_rows.append(
                    (
                        paper_id_map[arxiv_id],
                        vector["embedding_type"],
                        vector["text_content"],
                        json.dumps(vector["embedding"], separators=(",", ":")),
                    )
                )

            if vector_rows:
                extras.execute_values(
                    cursor,
                    """
                    INSERT INTO papers_embeddings (paper_id, embedding_type, text_content, embedding)
                    VALUES %s
                    """,
                    vector_rows,
                    template="(%s, %s, %s, %s::vector)",
                )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        logging.error("Database batch error: %s", exc)
        print(f"Database batch insert failed: {exc}")
    finally:
        release_db_conn(conn)


def main() -> None:
    dimension = check_model_dimension()
    ensure_schema(dimension)
    existing_ids = fetch_existing_ids()
    print(f"Existing papers in database: {len(existing_ids)}. They will be skipped automatically.")

    metadata_path = resolve_metadata_path()
    if not metadata_path.exists():
        print(f"Metadata file not found: {metadata_path}")
        return

    pending_lines: list[str] = []
    with metadata_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                logging.error("Invalid JSON line skipped.")
                continue
            if row.get("arxiv_id") not in existing_ids:
                pending_lines.append(line)

    total_tasks = len(pending_lines)
    print(f"Pending ingestion tasks: {total_tasks}")
    if total_tasks == 0:
        return

    batch_buffer: list[dict[str, object]] = []
    progress = tqdm(total=total_tasks, desc="Processing papers")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(process_single_paper, line) for line in pending_lines]
        for future in as_completed(futures):
            success, result, error = future.result()
            if success and result is not None:
                batch_buffer.append(result)
            elif error:
                logging.error(error)

            if len(batch_buffer) >= BATCH_SIZE:
                batch_insert_to_db(batch_buffer)
                batch_buffer = []
            progress.update(1)

    if batch_buffer:
        batch_insert_to_db(batch_buffer)

    progress.close()
    print("Ingestion completed. Check ingest_error.log for failures.")


if __name__ == "__main__":
    main()
