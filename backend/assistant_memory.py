from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import psycopg2
from psycopg2.extras import Json, RealDictCursor

from local_paper_db.app.search_service import (
    DEFAULT_DB_CONFIG,
    RuntimeSettings,
    chat_completion,
    extract_first_json_object,
    get_embedding,
)


LOGGER = logging.getLogger(__name__)

DEFAULT_PROFILE_KEY = "local-default"
DEFAULT_SESSION_ID = "local-default-session"
SUMMARY_INTERVAL_TURNS = 6
MAJOR_SUMMARY_GROUP_SIZE = 3
RECALL_SEED_K = 8
RECALL_MAX_ITEMS = 5
RECALL_THRESHOLD = 0.72
MIN_MEMORY_CONFIDENCE = 0.58
MAX_EVENT_TEXT_LENGTH = 8000
MAX_SUMMARY_TEXT_LENGTH = 12000

_SCHEMA_READY_CACHE: set[str] = set()


@dataclass(slots=True)
class RecallResult:
    used: bool
    items: list[dict[str, Any]]
    prompt_block: str | None
    notice: str | None


def _db_signature(db_config: dict[str, str] | None = None) -> str:
    config = db_config or DEFAULT_DB_CONFIG
    return "|".join(str(config.get(key)) for key in ("host", "port", "dbname", "user"))


def _connect(db_config: dict[str, str] | None = None):
    return psycopg2.connect(**(db_config or DEFAULT_DB_CONFIG))


def _safe_text(value: Any, max_length: int = MAX_EVENT_TEXT_LENGTH) -> str:
    text = str(value or "").strip()
    if len(text) <= max_length:
        return text
    return text[:max_length].rstrip() + "..."


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.split()).strip()


def _normalize_workflow_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_normalize_workflow_value(item) for item in value][:64]
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in list(value.items())[:32]:
            normalized[str(key)] = _normalize_workflow_value(item)
        return normalized
    return str(value)


def normalize_workflow_context(workflow_context: Any) -> dict[str, Any] | None:
    if workflow_context is None:
        return None
    if hasattr(workflow_context, "model_dump"):
        workflow_context = workflow_context.model_dump()
    elif hasattr(workflow_context, "dict"):
        workflow_context = workflow_context.dict()
    if not isinstance(workflow_context, dict):
        return None
    normalized = _normalize_workflow_value(workflow_context)
    if not isinstance(normalized, dict):
        return None
    return normalized


def resolve_session_id(session_id: str | None) -> str:
    candidate = str(session_id or "").strip()
    if not candidate:
        return DEFAULT_SESSION_ID
    if len(candidate) > 128:
        return candidate[:128]
    return candidate


def ensure_assistant_memory_schema(db_config: dict[str, str] | None = None) -> None:
    signature = _db_signature(db_config)
    if signature in _SCHEMA_READY_CACHE:
        return

    conn = _connect(db_config)
    try:
        conn.autocommit = True
        with conn.cursor() as cursor:
            try:
                cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            except Exception as exc:
                LOGGER.warning("assistant-memory: failed to ensure pgvector extension: %s", exc)

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS assistant_profiles (
                    id UUID PRIMARY KEY,
                    profile_key TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL DEFAULT 'Local Default',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS assistant_sessions (
                    id TEXT PRIMARY KEY,
                    profile_id UUID NOT NULL REFERENCES assistant_profiles(id) ON DELETE CASCADE,
                    source TEXT NOT NULL DEFAULT 'user',
                    last_turn_index INTEGER NOT NULL DEFAULT 0,
                    last_long_term_memory_saved_marker TEXT,
                    last_long_term_memory_dismissed_marker TEXT,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS assistant_session_events (
                    id UUID PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES assistant_sessions(id) ON DELETE CASCADE,
                    turn_index INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'user',
                    message_text TEXT NOT NULL,
                    answer_context TEXT,
                    workflow_context JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE(session_id, turn_index)
                );
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS assistant_session_summary_blocks (
                    id UUID PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES assistant_sessions(id) ON DELETE CASCADE,
                    block_type TEXT NOT NULL,
                    start_turn INTEGER NOT NULL,
                    end_turn INTEGER NOT NULL,
                    content_text TEXT NOT NULL,
                    content_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE(session_id, block_type, start_turn, end_turn)
                );
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS assistant_memory_nodes (
                    id UUID PRIMARY KEY,
                    profile_id UUID NOT NULL REFERENCES assistant_profiles(id) ON DELETE CASCADE,
                    session_id TEXT REFERENCES assistant_sessions(id) ON DELETE SET NULL,
                    node_type TEXT NOT NULL,
                    content_text TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.0,
                    pinned BOOLEAN NOT NULL DEFAULT FALSE,
                    source_marker TEXT,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    deleted_at TIMESTAMPTZ
                );
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS assistant_memory_edges (
                    id UUID PRIMARY KEY,
                    profile_id UUID NOT NULL REFERENCES assistant_profiles(id) ON DELETE CASCADE,
                    src_node_id UUID NOT NULL REFERENCES assistant_memory_nodes(id) ON DELETE CASCADE,
                    dst_node_id UUID NOT NULL REFERENCES assistant_memory_nodes(id) ON DELETE CASCADE,
                    edge_type TEXT NOT NULL,
                    weight DOUBLE PRECISION NOT NULL DEFAULT 0.5,
                    evidence TEXT,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CHECK (src_node_id <> dst_node_id),
                    UNIQUE(profile_id, src_node_id, dst_node_id, edge_type)
                );
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS assistant_memory_embeddings (
                    memory_node_id UUID PRIMARY KEY REFERENCES assistant_memory_nodes(id) ON DELETE CASCADE,
                    embedding vector NOT NULL,
                    model_name TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assistant_sessions_profile ON assistant_sessions(profile_id);")
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_assistant_events_session_turn ON assistant_session_events(session_id, turn_index);"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_assistant_summary_session_type ON assistant_session_summary_blocks(session_id, block_type, end_turn);"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_assistant_memory_nodes_profile_active ON assistant_memory_nodes(profile_id, deleted_at, pinned, created_at DESC);"
            )
            cursor.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_assistant_memory_nodes_hash ON assistant_memory_nodes(profile_id, node_type, content_hash);"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_assistant_memory_edges_src ON assistant_memory_edges(profile_id, src_node_id);"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_assistant_memory_edges_dst ON assistant_memory_edges(profile_id, dst_node_id);"
            )
    finally:
        conn.close()

    _SCHEMA_READY_CACHE.add(signature)


def _get_or_create_profile_id(conn, profile_key: str = DEFAULT_PROFILE_KEY) -> str:
    with conn.cursor() as cursor:
        cursor.execute("SELECT id::text FROM assistant_profiles WHERE profile_key = %s LIMIT 1;", (profile_key,))
        row = cursor.fetchone()
        if row and row[0]:
            return str(row[0])
        profile_id = str(uuid.uuid4())
        cursor.execute(
            """
            INSERT INTO assistant_profiles (id, profile_key, display_name)
            VALUES (%s::uuid, %s, %s)
            ON CONFLICT (profile_key) DO UPDATE SET updated_at = NOW()
            RETURNING id::text;
            """,
            (profile_id, profile_key, "Local Default"),
        )
        return str(cursor.fetchone()[0])


def _ensure_session(
    conn,
    *,
    session_id: str,
    profile_id: str,
    source: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO assistant_sessions (id, profile_id, source, metadata)
            VALUES (%s, %s::uuid, %s, %s::jsonb)
            ON CONFLICT (id) DO UPDATE SET updated_at = NOW();
            """,
            (session_id, profile_id, source, Json(metadata or {})),
        )


def _session_event_count(conn, session_id: str) -> int:
    with conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM assistant_session_events WHERE session_id = %s;", (session_id,))
        return int(cursor.fetchone()[0] or 0)


def _assistant_turn_count(conn, session_id: str) -> int:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM assistant_session_events
            WHERE session_id = %s AND role = 'assistant';
            """,
            (session_id,),
        )
        return int(cursor.fetchone()[0] or 0)


def _latest_turn_index(conn, session_id: str) -> int:
    with conn.cursor() as cursor:
        cursor.execute("SELECT last_turn_index FROM assistant_sessions WHERE id = %s LIMIT 1;", (session_id,))
        row = cursor.fetchone()
        return int(row[0] or 0) if row else 0


def _backfill_history_if_needed(conn, session_id: str, history: list[dict[str, Any]] | None) -> None:
    if not history:
        return
    if _session_event_count(conn, session_id) > 0:
        return

    for item in history[-10:]:
        role = str(item.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        text = _safe_text(item.get("text"))
        if not text:
            continue
        _append_session_event(
            conn,
            session_id=session_id,
            role=role,
            source="history_seed",
            message_text=text,
            answer_context=None,
            workflow_context=None,
        )


def _append_session_event(
    conn,
    *,
    session_id: str,
    role: str,
    source: str,
    message_text: str,
    answer_context: str | None,
    workflow_context: dict[str, Any] | None,
) -> int:
    with conn.cursor() as cursor:
        cursor.execute("SELECT last_turn_index FROM assistant_sessions WHERE id = %s FOR UPDATE;", (session_id,))
        row = cursor.fetchone()
        last_turn = int(row[0] or 0) if row else 0
        next_turn = last_turn + 1
        cursor.execute(
            """
            INSERT INTO assistant_session_events (
                id, session_id, turn_index, role, source, message_text, answer_context, workflow_context
            )
            VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s::jsonb);
            """,
            (
                str(uuid.uuid4()),
                session_id,
                next_turn,
                role,
                source,
                _safe_text(message_text),
                _safe_text(answer_context) if answer_context else None,
                Json(workflow_context or {}),
            ),
        )
        cursor.execute(
            """
            UPDATE assistant_sessions
            SET last_turn_index = %s, updated_at = NOW()
            WHERE id = %s;
            """,
            (next_turn, session_id),
        )
        return next_turn


def _build_event_text(
    *,
    source: str,
    message: str,
    answer_context: str | None,
    workflow_context: dict[str, Any] | None,
) -> str:
    cleaned = _safe_text(message)
    if cleaned:
        return cleaned
    if workflow_context:
        parts: list[str] = []
        kind = _safe_text(workflow_context.get("kind"))
        query = _safe_text(workflow_context.get("query"))
        answer_text = _safe_text(workflow_context.get("answer_text"))
        if kind:
            parts.append(f"Workflow kind: {kind}")
        if query:
            parts.append(f"Workflow query: {query}")
        if answer_text:
            parts.append(f"Workflow answer: {answer_text}")
        if parts:
            return " | ".join(parts)
    if answer_context:
        return _safe_text(answer_context)
    if source == "qa_auto":
        return "[QA workflow auto follow-up trigger]"
    if source == "pst_auto":
        return "[PST workflow auto follow-up trigger]"
    return "[Empty user message]"


def _render_workflow_context_text(workflow_context: dict[str, Any] | None) -> str:
    if not workflow_context:
        return ""
    lines: list[str] = []
    kind = _safe_text(workflow_context.get("kind"))
    query = _safe_text(workflow_context.get("query"))
    answer_text = _safe_text(workflow_context.get("answer_text"), max_length=1800)
    paper_titles = workflow_context.get("paper_titles")
    paper_ids = workflow_context.get("paper_ids")
    constraints = workflow_context.get("applied_constraints")

    if kind:
        lines.append(f"- kind: {kind}")
    if query:
        lines.append(f"- query: {query}")
    if answer_text:
        lines.append(f"- answer: {answer_text}")
    if isinstance(paper_titles, list) and paper_titles:
        lines.append("- paper_titles: " + ", ".join(_safe_text(item, 120) for item in paper_titles[:6]))
    if isinstance(paper_ids, list) and paper_ids:
        lines.append("- paper_ids: " + ", ".join(_safe_text(item, 64) for item in paper_ids[:8]))
    if constraints:
        lines.append("- constraints: " + _safe_text(json.dumps(constraints, ensure_ascii=False), 600))
    return "\n".join(lines)


def _collect_events_after_turn(conn, session_id: str, start_turn_exclusive: int) -> list[dict[str, Any]]:
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            """
            SELECT
                id::text AS id,
                turn_index,
                role,
                source,
                message_text,
                answer_context,
                workflow_context,
                created_at
            FROM assistant_session_events
            WHERE session_id = %s AND turn_index > %s
            ORDER BY turn_index ASC;
            """,
            (session_id, start_turn_exclusive),
        )
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


def _collect_recent_events(conn, session_id: str, limit: int = 12) -> list[dict[str, Any]]:
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            """
            SELECT
                id::text AS id,
                turn_index,
                role,
                source,
                message_text,
                answer_context,
                workflow_context,
                created_at
            FROM assistant_session_events
            WHERE session_id = %s
            ORDER BY turn_index DESC
            LIMIT %s;
            """,
            (session_id, limit),
        )
        rows = cursor.fetchall()
    recent = [dict(row) for row in rows]
    return list(reversed(recent))


def _upsert_summary_block(
    conn,
    *,
    session_id: str,
    block_type: str,
    start_turn: int,
    end_turn: int,
    content_text: str,
    content_json: dict[str, Any] | None = None,
) -> None:
    if not content_text.strip():
        return
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO assistant_session_summary_blocks (
                id, session_id, block_type, start_turn, end_turn, content_text, content_json
            )
            VALUES (%s::uuid, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (session_id, block_type, start_turn, end_turn)
            DO UPDATE SET
                content_text = EXCLUDED.content_text,
                content_json = EXCLUDED.content_json;
            """,
            (
                str(uuid.uuid4()),
                session_id,
                block_type,
                start_turn,
                end_turn,
                _safe_text(content_text, max_length=MAX_SUMMARY_TEXT_LENGTH),
                Json(content_json or {}),
            ),
        )


def _rebuild_raw_summary_block(conn, session_id: str) -> None:
    events = _collect_recent_events(conn, session_id, limit=12)
    if not events:
        return
    lines: list[str] = []
    for event in events:
        role = _safe_text(event.get("role"))
        source = _safe_text(event.get("source"))
        text = _safe_text(event.get("message_text"), max_length=420)
        if not text:
            continue
        lines.append(f"[{event['turn_index']}] {role}/{source}: {text}")
    if not lines:
        return
    _upsert_summary_block(
        conn,
        session_id=session_id,
        block_type="raw",
        start_turn=int(events[0]["turn_index"]),
        end_turn=int(events[-1]["turn_index"]),
        content_text="\n".join(lines),
        content_json={"event_ids": [event["id"] for event in events], "event_count": len(events)},
    )


def _build_summary_messages(
    *,
    summary_kind: str,
    source_text: str,
    workflow_context_text: str,
) -> list[dict[str, str]]:
    system_prompt = f"""
You create {summary_kind} assistant memory summaries for a local productivity assistant.
Return JSON only in this shape:
{{
  "summary": "compact natural-language summary",
  "preferences": ["stable preference 1"],
  "topics": ["topic 1"],
  "tasks": ["active task 1"],
  "facts": ["durable fact 1"]
}}
Rules:
- Focus on stable, reusable memory.
- Prefer workflow context facts over casual chat details.
- Do not invent missing details.
""".strip()

    user_prompt = "\n\n".join(
        [
            "Conversation source:",
            source_text,
            "Structured workflow context (higher priority):",
            workflow_context_text or "(none)",
            "Return JSON only.",
        ]
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _generate_summary_payload(
    *,
    summary_kind: str,
    source_text: str,
    workflow_context_text: str,
    settings: RuntimeSettings,
) -> dict[str, Any]:
    fallback_summary = _safe_text(source_text, max_length=800)
    if not fallback_summary:
        return {"summary": "", "preferences": [], "topics": [], "tasks": [], "facts": []}
    try:
        raw = chat_completion(
            _build_summary_messages(
                summary_kind=summary_kind,
                source_text=_safe_text(source_text, max_length=MAX_SUMMARY_TEXT_LENGTH),
                workflow_context_text=_safe_text(workflow_context_text, max_length=MAX_SUMMARY_TEXT_LENGTH),
            ),
            settings.answer_chat,
            settings.retrieval.request_timeout,
        )
        payload = extract_first_json_object(raw)
    except Exception:
        payload = {"summary": fallback_summary}

    summary = _safe_text(payload.get("summary") or fallback_summary, max_length=1400)

    def normalize_text_list(items: Any, max_items: int = 12) -> list[str]:
        if isinstance(items, str):
            raw_items = re.split(r"[;\n,]+", items)
        elif isinstance(items, list):
            raw_items = [str(item) for item in items]
        else:
            raw_items = []
        normalized: list[str] = []
        seen: set[str] = set()
        for raw_item in raw_items:
            text = _normalize_whitespace(raw_item)
            if not text:
                continue
            lowered = text.casefold()
            if lowered in seen:
                continue
            seen.add(lowered)
            normalized.append(text)
            if len(normalized) >= max_items:
                break
        return normalized

    return {
        "summary": summary,
        "preferences": normalize_text_list(payload.get("preferences")),
        "topics": normalize_text_list(payload.get("topics")),
        "tasks": normalize_text_list(payload.get("tasks")),
        "facts": normalize_text_list(payload.get("facts")),
    }


def _latest_summary_end_turn(conn, session_id: str, block_type: str) -> int:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COALESCE(MAX(end_turn), 0)
            FROM assistant_session_summary_blocks
            WHERE session_id = %s AND block_type = %s;
            """,
            (session_id, block_type),
        )
        return int(cursor.fetchone()[0] or 0)


def _maybe_create_mini_summary(
    conn,
    *,
    session_id: str,
    settings: RuntimeSettings,
) -> dict[str, Any] | None:
    assistant_turns = _assistant_turn_count(conn, session_id)
    if assistant_turns <= 0 or assistant_turns % SUMMARY_INTERVAL_TURNS != 0:
        return None

    last_mini_end = _latest_summary_end_turn(conn, session_id, "mini")
    events = _collect_events_after_turn(conn, session_id, last_mini_end)
    if not events:
        return None

    workflow_lines = []
    for event in events:
        workflow_context = normalize_workflow_context(event.get("workflow_context"))
        rendered = _render_workflow_context_text(workflow_context)
        if rendered:
            workflow_lines.append(rendered)

    source_lines = []
    for event in events:
        role = _safe_text(event.get("role"))
        source = _safe_text(event.get("source"))
        message = _safe_text(event.get("message_text"), max_length=500)
        if message:
            source_lines.append(f"{role}/{source}: {message}")

    payload = _generate_summary_payload(
        summary_kind="mini",
        source_text="\n".join(source_lines),
        workflow_context_text="\n".join(workflow_lines),
        settings=settings,
    )

    start_turn = int(events[0]["turn_index"])
    end_turn = int(events[-1]["turn_index"])
    _upsert_summary_block(
        conn,
        session_id=session_id,
        block_type="mini",
        start_turn=start_turn,
        end_turn=end_turn,
        content_text=payload["summary"],
        content_json=payload,
    )
    return {"start_turn": start_turn, "end_turn": end_turn, "payload": payload}


def _collect_recent_mini_blocks_for_major(conn, session_id: str) -> list[dict[str, Any]]:
    last_major_end = _latest_summary_end_turn(conn, session_id, "major")
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            """
            SELECT
                id::text AS id,
                start_turn,
                end_turn,
                content_text,
                content_json
            FROM assistant_session_summary_blocks
            WHERE session_id = %s
            AND block_type = 'mini'
            AND end_turn > %s
            ORDER BY end_turn ASC
            LIMIT %s;
            """,
            (session_id, last_major_end, MAJOR_SUMMARY_GROUP_SIZE),
        )
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


def _parse_model_items(values: Any, node_type: str, confidence: float) -> list[dict[str, Any]]:
    if isinstance(values, str):
        parts = re.split(r"[;\n,]+", values)
        values = [part for part in parts if part.strip()]
    if not isinstance(values, list):
        return []
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in values[:16]:
        text = _normalize_whitespace(str(raw))
        if not text:
            continue
        key = f"{node_type}:{text.casefold()}"
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            {
                "node_type": node_type,
                "text": text,
                "confidence": confidence,
                "metadata": {"source": "summary_model"},
            }
        )
    return normalized


def _extract_workflow_items(
    workflow_contexts: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[tuple[str, str, str, float]]]:
    items: list[dict[str, Any]] = []
    relations: list[tuple[str, str, str, float]] = []
    seen_keys: set[str] = set()
    for context in workflow_contexts:
        kind = _normalize_whitespace(str(context.get("kind") or ""))
        query = _normalize_whitespace(str(context.get("query") or ""))
        answer_text = _normalize_whitespace(str(context.get("answer_text") or ""))
        paper_ids = context.get("paper_ids")
        paper_titles = context.get("paper_titles")

        if query:
            key = f"task:{query.casefold()}"
            if key not in seen_keys:
                seen_keys.add(key)
                items.append(
                    {
                        "node_type": "task",
                        "text": query,
                        "confidence": 0.82,
                        "metadata": {"source": "workflow_context", "kind": kind},
                    }
                )
        if kind:
            key = f"topic:{kind.casefold()}"
            if key not in seen_keys:
                seen_keys.add(key)
                items.append(
                    {
                        "node_type": "topic",
                        "text": f"{kind} workflow",
                        "confidence": 0.74,
                        "metadata": {"source": "workflow_context"},
                    }
                )
        if answer_text:
            key = f"workflow_episode:{answer_text[:180].casefold()}"
            if key not in seen_keys:
                seen_keys.add(key)
                items.append(
                    {
                        "node_type": "workflow_episode",
                        "text": _safe_text(answer_text, max_length=320),
                        "confidence": 0.66,
                        "metadata": {"source": "workflow_context"},
                    }
                )

        titles: list[str] = []
        if isinstance(paper_titles, list):
            titles.extend(_normalize_whitespace(str(title)) for title in paper_titles if str(title).strip())
        ids: list[str] = []
        if isinstance(paper_ids, list):
            ids.extend(_normalize_whitespace(str(paper_id)) for paper_id in paper_ids if str(paper_id).strip())

        paired_count = min(len(titles), len(ids))
        for index in range(paired_count):
            text = f"{titles[index]} ({ids[index]})"
            key = f"paper_ref:{text.casefold()}"
            if key in seen_keys:
                continue
            seen_keys.add(key)
            items.append(
                {
                    "node_type": "paper_ref",
                    "text": text,
                    "confidence": 0.86,
                    "metadata": {"paper_id": ids[index], "paper_title": titles[index], "source": "workflow_context"},
                }
            )
            if query:
                relations.append((f"task:{query.casefold()}", key, "mentions_paper", 0.82))

        for extra_title in titles[paired_count:]:
            key = f"paper_ref:{extra_title.casefold()}"
            if key in seen_keys:
                continue
            seen_keys.add(key)
            items.append(
                {
                    "node_type": "paper_ref",
                    "text": extra_title,
                    "confidence": 0.72,
                    "metadata": {"paper_title": extra_title, "source": "workflow_context"},
                }
            )
    return items, relations


def _build_memory_extraction_messages(
    *,
    major_summary_text: str,
    major_summary_payload: dict[str, Any],
    workflow_context_text: str,
) -> list[dict[str, str]]:
    prompt = """
You extract durable long-term memory for a local assistant.
Return one JSON object only:
{
  "preferences": ["..."],
  "topics": ["..."],
  "tasks": ["..."],
  "facts": ["..."]
}
Rules:
- Keep only stable facts/preferences/tasks likely useful in future sessions.
- Prefer structured workflow context over casual text.
- No markdown and no explanations.
""".strip()
    user = "\n\n".join(
        [
            "Major summary text:",
            major_summary_text,
            "Major summary structured payload:",
            json.dumps(major_summary_payload, ensure_ascii=False),
            "Structured workflow context:",
            workflow_context_text or "(none)",
            "Return JSON only.",
        ]
    )
    return [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user},
    ]


def _extract_memory_candidates_from_major(
    *,
    major_summary_payload: dict[str, Any],
    major_summary_text: str,
    workflow_contexts: list[dict[str, Any]],
    settings: RuntimeSettings,
) -> tuple[list[dict[str, Any]], list[tuple[str, str, str, float]]]:
    workflow_items, workflow_relations = _extract_workflow_items(workflow_contexts)

    extracted: dict[str, Any] = {}
    workflow_text = "\n\n".join(_render_workflow_context_text(item) for item in workflow_contexts if item)
    try:
        raw = chat_completion(
            _build_memory_extraction_messages(
                major_summary_text=major_summary_text,
                major_summary_payload=major_summary_payload,
                workflow_context_text=workflow_text,
            ),
            settings.answer_chat,
            settings.retrieval.request_timeout,
        )
        extracted = extract_first_json_object(raw)
    except Exception:
        extracted = {}

    items: list[dict[str, Any]] = []
    items.extend(_parse_model_items(extracted.get("preferences"), "preference", 0.8))
    items.extend(_parse_model_items(extracted.get("topics"), "topic", 0.7))
    items.extend(_parse_model_items(extracted.get("tasks"), "task", 0.72))
    items.extend(_parse_model_items(extracted.get("facts"), "fact", 0.62))

    for key, node_type, confidence in (
        ("preferences", "preference", 0.74),
        ("topics", "topic", 0.68),
        ("tasks", "task", 0.7),
        ("facts", "fact", 0.62),
    ):
        items.extend(_parse_model_items(major_summary_payload.get(key), node_type, confidence))
    items.extend(workflow_items)

    if not items:
        fallback = _normalize_whitespace(major_summary_text)
        if fallback:
            items.append(
                {
                    "node_type": "fact",
                    "text": _safe_text(fallback, max_length=320),
                    "confidence": 0.6,
                    "metadata": {"source": "major_summary_fallback"},
                }
            )

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        text = _normalize_whitespace(str(item.get("text") or ""))
        node_type = _normalize_whitespace(str(item.get("node_type") or "fact")).lower()
        confidence = float(item.get("confidence") or 0.6)
        if not text or confidence < MIN_MEMORY_CONFIDENCE:
            continue
        if node_type not in {"preference", "topic", "task", "fact", "workflow_episode", "paper_ref"}:
            node_type = "fact"
        key = f"{node_type}:{text.casefold()}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(
            {
                "key": key,
                "node_type": node_type,
                "text": text,
                "confidence": confidence,
                "metadata": item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
            }
        )
        if len(deduped) >= 24:
            break

    return deduped, workflow_relations


def _content_hash(node_type: str, text: str) -> str:
    return hashlib.sha1(f"{node_type}:{_normalize_whitespace(text).casefold()}".encode("utf-8")).hexdigest()


def _upsert_memory_node(
    conn,
    *,
    profile_id: str,
    session_id: str,
    node_type: str,
    text: str,
    confidence: float,
    source_marker: str,
    metadata: dict[str, Any] | None = None,
    pinned: bool = False,
) -> str:
    content_hash = _content_hash(node_type, text)
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO assistant_memory_nodes (
                id, profile_id, session_id, node_type, content_text, content_hash, confidence, pinned, source_marker, metadata
            )
            VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (profile_id, node_type, content_hash)
            DO UPDATE SET
                confidence = GREATEST(assistant_memory_nodes.confidence, EXCLUDED.confidence),
                pinned = assistant_memory_nodes.pinned OR EXCLUDED.pinned,
                source_marker = EXCLUDED.source_marker,
                metadata = assistant_memory_nodes.metadata || EXCLUDED.metadata,
                updated_at = NOW(),
                deleted_at = NULL
            RETURNING id::text;
            """,
            (
                str(uuid.uuid4()),
                profile_id,
                session_id,
                node_type,
                _safe_text(text, max_length=2000),
                content_hash,
                float(confidence),
                bool(pinned),
                source_marker,
                Json(metadata or {}),
            ),
        )
        return str(cursor.fetchone()[0])


def _upsert_memory_edge(
    conn,
    *,
    profile_id: str,
    src_node_id: str,
    dst_node_id: str,
    edge_type: str,
    weight: float,
    metadata: dict[str, Any] | None = None,
    evidence: str | None = None,
) -> None:
    if src_node_id == dst_node_id:
        return
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO assistant_memory_edges (
                id, profile_id, src_node_id, dst_node_id, edge_type, weight, evidence, metadata
            )
            VALUES (%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s::jsonb)
            ON CONFLICT (profile_id, src_node_id, dst_node_id, edge_type)
            DO UPDATE SET
                weight = GREATEST(assistant_memory_edges.weight, EXCLUDED.weight),
                evidence = COALESCE(EXCLUDED.evidence, assistant_memory_edges.evidence),
                metadata = assistant_memory_edges.metadata || EXCLUDED.metadata,
                updated_at = NOW();
            """,
            (
                str(uuid.uuid4()),
                profile_id,
                src_node_id,
                dst_node_id,
                edge_type,
                float(weight),
                _safe_text(evidence, max_length=600) if evidence else None,
                Json(metadata or {}),
            ),
        )


def _upsert_memory_embedding(
    conn,
    *,
    node_id: str,
    text: str,
    settings: RuntimeSettings,
) -> None:
    embedding = get_embedding(text, settings)
    vector_literal = json.dumps(embedding, separators=(",", ":"))
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO assistant_memory_embeddings (memory_node_id, embedding, model_name)
            VALUES (%s::uuid, %s::vector, %s)
            ON CONFLICT (memory_node_id)
            DO UPDATE SET
                embedding = EXCLUDED.embedding,
                model_name = EXCLUDED.model_name,
                updated_at = NOW();
            """,
            (node_id, vector_literal, settings.embedding.model),
        )


def _build_key_to_node_id_map(items: list[dict[str, Any]], node_ids: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item, node_id in zip(items, node_ids):
        key = str(item.get("key") or "")
        if key:
            mapping[key] = node_id
    return mapping


def _save_memories_from_major_summary(
    conn,
    *,
    profile_id: str,
    session_id: str,
    marker: str,
    major_summary_payload: dict[str, Any],
    major_summary_text: str,
    source_events: list[dict[str, Any]],
    settings: RuntimeSettings,
) -> int:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT last_long_term_memory_saved_marker
            FROM assistant_sessions
            WHERE id = %s
            LIMIT 1;
            """,
            (session_id,),
        )
        row = cursor.fetchone()
    if row and row[0] == marker:
        return 0

    workflow_contexts = [
        context
        for context in (
            normalize_workflow_context(event.get("workflow_context"))
            for event in source_events
        )
        if context
    ]
    candidates, workflow_relations = _extract_memory_candidates_from_major(
        major_summary_payload=major_summary_payload,
        major_summary_text=major_summary_text,
        workflow_contexts=workflow_contexts,
        settings=settings,
    )
    if not candidates:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE assistant_sessions
                SET last_long_term_memory_dismissed_marker = %s, updated_at = NOW()
                WHERE id = %s;
                """,
                (marker, session_id),
            )
        return 0

    node_ids: list[str] = []
    for item in candidates:
        node_id = _upsert_memory_node(
            conn,
            profile_id=profile_id,
            session_id=session_id,
            node_type=item["node_type"],
            text=item["text"],
            confidence=float(item["confidence"]),
            source_marker=marker,
            metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
        )
        node_ids.append(node_id)
        try:
            _upsert_memory_embedding(conn, node_id=node_id, text=item["text"], settings=settings)
        except Exception as exc:
            LOGGER.warning("assistant-memory: failed to update embedding for node %s: %s", node_id, exc)

    key_to_node_id = _build_key_to_node_id_map(candidates, node_ids)
    for src_key, dst_key, edge_type, weight in workflow_relations:
        src_node_id = key_to_node_id.get(src_key)
        dst_node_id = key_to_node_id.get(dst_key)
        if not src_node_id or not dst_node_id:
            continue
        _upsert_memory_edge(
            conn,
            profile_id=profile_id,
            src_node_id=src_node_id,
            dst_node_id=dst_node_id,
            edge_type=edge_type,
            weight=weight,
            metadata={"source": "workflow_relation"},
        )

    limited_pairs = 0
    for left in range(len(node_ids)):
        for right in range(left + 1, len(node_ids)):
            src_node_id = node_ids[left]
            dst_node_id = node_ids[right]
            _upsert_memory_edge(
                conn,
                profile_id=profile_id,
                src_node_id=src_node_id,
                dst_node_id=dst_node_id,
                edge_type="derived_from_summary",
                weight=0.58,
                metadata={"source_marker": marker},
                evidence=_safe_text(major_summary_text, max_length=420),
            )
            _upsert_memory_edge(
                conn,
                profile_id=profile_id,
                src_node_id=dst_node_id,
                dst_node_id=src_node_id,
                edge_type="derived_from_summary",
                weight=0.58,
                metadata={"source_marker": marker},
                evidence=_safe_text(major_summary_text, max_length=420),
            )
            limited_pairs += 1
            if limited_pairs >= 36:
                break
        if limited_pairs >= 36:
            break

    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE assistant_sessions
            SET last_long_term_memory_saved_marker = %s, updated_at = NOW()
            WHERE id = %s;
            """,
            (marker, session_id),
        )
    return len(node_ids)


def _maybe_create_major_summary_and_memory(
    conn,
    *,
    profile_id: str,
    session_id: str,
    settings: RuntimeSettings,
) -> dict[str, Any] | None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM assistant_session_summary_blocks
            WHERE session_id = %s AND block_type = 'mini';
            """,
            (session_id,),
        )
        mini_count = int(cursor.fetchone()[0] or 0)
    if mini_count <= 0 or mini_count % MAJOR_SUMMARY_GROUP_SIZE != 0:
        return None

    mini_blocks = _collect_recent_mini_blocks_for_major(conn, session_id)
    if len(mini_blocks) != MAJOR_SUMMARY_GROUP_SIZE:
        return None

    source_text = "\n".join(
        f"[Mini {index + 1}] {block['content_text']}"
        for index, block in enumerate(mini_blocks)
    )
    workflow_lines: list[str] = []
    start_turn = int(mini_blocks[0]["start_turn"])
    end_turn = int(mini_blocks[-1]["end_turn"])
    source_events = _collect_events_after_turn(conn, session_id, start_turn_exclusive=start_turn - 1)
    source_events = [event for event in source_events if int(event["turn_index"]) <= end_turn]
    for event in source_events:
        workflow_context = normalize_workflow_context(event.get("workflow_context"))
        rendered = _render_workflow_context_text(workflow_context)
        if rendered:
            workflow_lines.append(rendered)

    payload = _generate_summary_payload(
        summary_kind="major",
        source_text=source_text,
        workflow_context_text="\n".join(workflow_lines),
        settings=settings,
    )
    major_text = _safe_text(payload.get("summary"), max_length=2200)
    if not major_text:
        return None

    _upsert_summary_block(
        conn,
        session_id=session_id,
        block_type="major",
        start_turn=start_turn,
        end_turn=end_turn,
        content_text=major_text,
        content_json=payload,
    )
    marker = f"major:{end_turn}"
    saved_count = _save_memories_from_major_summary(
        conn,
        profile_id=profile_id,
        session_id=session_id,
        marker=marker,
        major_summary_payload=payload,
        major_summary_text=major_text,
        source_events=source_events,
        settings=settings,
    )
    return {"start_turn": start_turn, "end_turn": end_turn, "saved_count": saved_count}


def _latest_major_summary_text(conn, session_id: str) -> str | None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT content_text
            FROM assistant_session_summary_blocks
            WHERE session_id = %s AND block_type = 'major'
            ORDER BY end_turn DESC
            LIMIT 1;
            """,
            (session_id,),
        )
        row = cursor.fetchone()
    if not row:
        return None
    value = _safe_text(row[0], max_length=1400)
    return value or None


def _build_recall_query_text(
    *,
    message: str,
    answer_context: str | None,
    workflow_context: dict[str, Any] | None,
    latest_major_summary: str | None,
) -> str:
    parts: list[str] = []
    cleaned_message = _safe_text(message)
    if cleaned_message:
        parts.append(cleaned_message)
    if workflow_context:
        parts.append(_render_workflow_context_text(workflow_context))
    elif answer_context:
        parts.append(_safe_text(answer_context, max_length=1200))
    if latest_major_summary:
        parts.append(f"Recent major session summary: {latest_major_summary}")
    return "\n".join(part for part in parts if part).strip()


def _vector_seed_memories(
    conn,
    *,
    profile_id: str,
    query_vector_literal: str,
    limit: int = RECALL_SEED_K,
) -> list[dict[str, Any]]:
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            """
            SELECT
                n.id::text AS memory_id,
                n.node_type,
                n.content_text,
                n.pinned,
                n.confidence,
                n.metadata,
                n.created_at,
                1 - (e.embedding <=> %s::vector) AS similarity
            FROM assistant_memory_embeddings AS e
            JOIN assistant_memory_nodes AS n ON n.id = e.memory_node_id
            WHERE n.profile_id = %s::uuid
            AND n.deleted_at IS NULL
            ORDER BY e.embedding <=> %s::vector
            LIMIT %s;
            """,
            (query_vector_literal, profile_id, query_vector_literal, limit),
        )
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


def _expand_neighbors(
    conn,
    *,
    profile_id: str,
    seed_ids: list[str],
    limit: int = 128,
) -> list[dict[str, Any]]:
    if not seed_ids:
        return []
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            """
            SELECT
                e.src_node_id::text AS src_node_id,
                e.dst_node_id::text AS dst_node_id,
                e.edge_type,
                e.weight,
                COALESCE(e.metadata, '{}'::jsonb) AS edge_metadata,
                n.id::text AS memory_id,
                n.node_type,
                n.content_text,
                n.pinned,
                n.confidence,
                n.metadata,
                n.created_at
            FROM assistant_memory_edges AS e
            JOIN assistant_memory_nodes AS n ON n.id = (
                CASE
                    WHEN e.src_node_id = ANY(%s::uuid[]) THEN e.dst_node_id
                    ELSE e.src_node_id
                END
            )
            WHERE e.profile_id = %s::uuid
            AND (e.src_node_id = ANY(%s::uuid[]) OR e.dst_node_id = ANY(%s::uuid[]))
            AND n.deleted_at IS NULL
            LIMIT %s;
            """,
            (seed_ids, profile_id, seed_ids, limit),
        )
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


def _recency_bonus(created_at: Any) -> float:
    if not isinstance(created_at, datetime):
        return 0.0
    now = datetime.now(timezone.utc)
    delta_days = max(0.0, (now - created_at.astimezone(timezone.utc)).total_seconds() / 86400.0)
    if delta_days <= 3:
        return 0.05
    if delta_days <= 14:
        return 0.03
    if delta_days <= 45:
        return 0.01
    return 0.0


def _format_memory_item(item: dict[str, Any], score: float, source_tags: list[str]) -> dict[str, Any]:
    return {
        "memory_id": item.get("memory_id"),
        "node_type": item.get("node_type"),
        "summary": _safe_text(item.get("content_text"), max_length=320),
        "content": _safe_text(item.get("content_text"), max_length=320),
        "text": _safe_text(item.get("content_text"), max_length=320),
        "score": round(score, 4),
        "pinned": bool(item.get("pinned")),
        "confidence": float(item.get("confidence") or 0.0),
        "source_tags": source_tags,
    }


def _build_memory_prompt_block(
    memory_items: list[dict[str, Any]],
    workflow_context: dict[str, Any] | None,
) -> str | None:
    if not memory_items and not workflow_context:
        return None
    sections: list[str] = []
    if memory_items:
        lines = ["Relevant long-term memory:"]
        for item in memory_items:
            node_type = _safe_text(item.get("node_type") or "fact")
            summary = _safe_text(item.get("summary") or item.get("text"), max_length=260)
            if not summary:
                continue
            lines.append(f"- [{node_type}] {summary}")
        if len(lines) > 1:
            sections.append("\n".join(lines))
    if workflow_context:
        rendered = _render_workflow_context_text(workflow_context)
        if rendered:
            sections.append("Current workflow context:\n" + rendered)
    content = "\n\n".join(section for section in sections if section.strip())
    return content or None


def recall_memory_for_message(
    *,
    session_id: str,
    profile_id: str,
    message: str,
    answer_context: str | None,
    workflow_context: dict[str, Any] | None,
    settings: RuntimeSettings,
    db_config: dict[str, str] | None = None,
) -> RecallResult:
    query_text = ""
    latest_major_summary = None
    conn = _connect(db_config)
    try:
        with conn:
            latest_major_summary = _latest_major_summary_text(conn, session_id)
    finally:
        conn.close()

    query_text = _build_recall_query_text(
        message=message,
        answer_context=answer_context,
        workflow_context=workflow_context,
        latest_major_summary=latest_major_summary,
    )
    if not query_text:
        return RecallResult(used=False, items=[], prompt_block=None, notice=None)

    try:
        query_vector = get_embedding(query_text, settings)
    except Exception as exc:
        LOGGER.warning("assistant-memory: recall embedding failed: %s", exc)
        return RecallResult(used=False, items=[], prompt_block=None, notice=None)
    query_vector_literal = json.dumps(query_vector, separators=(",", ":"))

    conn = _connect(db_config)
    try:
        with conn:
            seeds = _vector_seed_memories(
                conn,
                profile_id=profile_id,
                query_vector_literal=query_vector_literal,
                limit=RECALL_SEED_K,
            )
            if not seeds:
                return RecallResult(used=False, items=[], prompt_block=None, notice=None)

            seed_score_map: dict[str, float] = {
                str(seed["memory_id"]): max(0.0, float(seed.get("similarity") or 0.0))
                for seed in seeds
            }
            candidates: dict[str, dict[str, Any]] = {}
            score_map: dict[str, float] = {}
            tag_map: dict[str, set[str]] = {}

            for seed in seeds:
                memory_id = str(seed.get("memory_id") or "")
                if not memory_id:
                    continue
                score = max(0.0, float(seed.get("similarity") or 0.0))
                score += _recency_bonus(seed.get("created_at"))
                if seed.get("pinned"):
                    score += 0.08
                candidates[memory_id] = seed
                score_map[memory_id] = score
                tag_map[memory_id] = {"vector_seed"}

            neighbors = _expand_neighbors(
                conn,
                profile_id=profile_id,
                seed_ids=list(seed_score_map.keys()),
            )
            for edge in neighbors:
                memory_id = str(edge.get("memory_id") or "")
                if not memory_id:
                    continue
                src_id = str(edge.get("src_node_id") or "")
                dst_id = str(edge.get("dst_node_id") or "")
                parent_seed = seed_score_map.get(src_id) or seed_score_map.get(dst_id) or 0.0
                edge_weight = max(0.0, float(edge.get("weight") or 0.0))
                score = parent_seed * 0.65 + edge_weight * 0.28
                score += _recency_bonus(edge.get("created_at"))
                if edge.get("pinned"):
                    score += 0.08
                current_score = score_map.get(memory_id, -1.0)
                if score > current_score:
                    score_map[memory_id] = score
                    candidates[memory_id] = edge
                tags = tag_map.setdefault(memory_id, set())
                tags.add("graph_expand")

            ranked = sorted(score_map.items(), key=lambda item: item[1], reverse=True)
            selected: list[dict[str, Any]] = []
            for memory_id, score in ranked:
                if score < RECALL_THRESHOLD:
                    continue
                item = candidates.get(memory_id)
                if not item:
                    continue
                selected.append(_format_memory_item(item, score, sorted(tag_map.get(memory_id, {"vector_seed"}))))
                if len(selected) >= RECALL_MAX_ITEMS:
                    break

            if not selected:
                return RecallResult(used=False, items=[], prompt_block=None, notice=None)

            prompt_block = _build_memory_prompt_block(selected, workflow_context)
            return RecallResult(
                used=True,
                items=selected,
                prompt_block=prompt_block,
                notice="我会参考一些历史记忆来让建议更连续。",
            )
    finally:
        conn.close()


def _looks_like_explicit_remember_request(message: str) -> bool:
    lowered = message.casefold()
    return (
        "remember this" in lowered
        or "记住" in message
        or "记下来" in message
        or "帮我记" in message
        or "请记住" in message
    )


def _extract_explicit_memory_text(message: str, workflow_context: dict[str, Any] | None) -> str:
    cleaned = _normalize_whitespace(message)
    if cleaned:
        cleaned = re.sub(r"^(请)?(帮我)?(记住|记下来|remember this)[:：]?\s*", "", cleaned, flags=re.IGNORECASE)
    if cleaned:
        return _safe_text(cleaned, max_length=500)
    workflow_text = _render_workflow_context_text(workflow_context)
    if workflow_text:
        return _safe_text(workflow_text, max_length=500)
    return ""


def _save_explicit_memory_if_requested(
    conn,
    *,
    profile_id: str,
    session_id: str,
    message: str,
    workflow_context: dict[str, Any] | None,
    settings: RuntimeSettings,
    turn_index: int,
) -> str | None:
    if not _looks_like_explicit_remember_request(message):
        return None
    memory_text = _extract_explicit_memory_text(message, workflow_context)
    if not memory_text:
        return None
    node_type = "preference" if ("偏好" in memory_text or "prefer" in memory_text.casefold()) else "fact"
    marker = f"explicit:{turn_index}"
    node_id = _upsert_memory_node(
        conn,
        profile_id=profile_id,
        session_id=session_id,
        node_type=node_type,
        text=memory_text,
        confidence=0.95,
        source_marker=marker,
        metadata={"source": "explicit_user_request"},
        pinned=True,
    )
    try:
        _upsert_memory_embedding(conn, node_id=node_id, text=memory_text, settings=settings)
    except Exception as exc:
        LOGGER.warning("assistant-memory: explicit memory embedding failed: %s", exc)
    return node_id


def get_or_create_session(
    *,
    session_id: str | None,
    source: str,
    profile_key: str = DEFAULT_PROFILE_KEY,
    history: list[dict[str, Any]] | None = None,
    db_config: dict[str, str] | None = None,
) -> dict[str, Any]:
    ensure_assistant_memory_schema(db_config)
    resolved_session_id = resolve_session_id(session_id)
    conn = _connect(db_config)
    try:
        with conn:
            profile_id = _get_or_create_profile_id(conn, profile_key)
            _ensure_session(
                conn,
                session_id=resolved_session_id,
                profile_id=profile_id,
                source=source,
                metadata={"local_first": True},
            )
            _backfill_history_if_needed(conn, resolved_session_id, history)
        return {"session_id": resolved_session_id, "profile_id": profile_id}
    finally:
        conn.close()


def prepare_live2d_chat_context(
    *,
    source: str,
    message: str,
    answer_context: str | None,
    workflow_context: Any,
    settings: RuntimeSettings,
    session_id: str | None = None,
    history: list[dict[str, Any]] | None = None,
    profile_key: str = DEFAULT_PROFILE_KEY,
    db_config: dict[str, str] | None = None,
) -> dict[str, Any]:
    ensure_assistant_memory_schema(db_config)
    normalized_workflow = normalize_workflow_context(workflow_context)
    session_state = get_or_create_session(
        session_id=session_id,
        source=source,
        profile_key=profile_key,
        history=history,
        db_config=db_config,
    )
    resolved_session_id = session_state["session_id"]
    profile_id = session_state["profile_id"]
    user_event_turn = 0

    conn = _connect(db_config)
    try:
        with conn:
            user_role = "user" if source == "user" else "system"
            event_text = _build_event_text(
                source=source,
                message=message,
                answer_context=answer_context,
                workflow_context=normalized_workflow,
            )
            user_event_turn = _append_session_event(
                conn,
                session_id=resolved_session_id,
                role=user_role,
                source=source,
                message_text=event_text,
                answer_context=answer_context,
                workflow_context=normalized_workflow,
            )
            _save_explicit_memory_if_requested(
                conn,
                profile_id=profile_id,
                session_id=resolved_session_id,
                message=message,
                workflow_context=normalized_workflow,
                settings=settings,
                turn_index=user_event_turn,
            )
    finally:
        conn.close()

    recall_result = recall_memory_for_message(
        session_id=resolved_session_id,
        profile_id=profile_id,
        message=message,
        answer_context=answer_context,
        workflow_context=normalized_workflow,
        settings=settings,
        db_config=db_config,
    )
    return {
        "session_id": resolved_session_id,
        "profile_id": profile_id,
        "user_event_turn": user_event_turn,
        "workflow_context": normalized_workflow,
        "memory_used": recall_result.used,
        "used_memory_items": recall_result.items,
        "memory_prompt_block": recall_result.prompt_block,
        "memory_notice": recall_result.notice,
    }


def finalize_live2d_chat_turn(
    *,
    session_id: str,
    source: str,
    assistant_reply: str,
    answer_context: str | None,
    workflow_context: Any,
    settings: RuntimeSettings,
    profile_key: str = DEFAULT_PROFILE_KEY,
    db_config: dict[str, str] | None = None,
) -> dict[str, Any]:
    ensure_assistant_memory_schema(db_config)
    resolved_session_id = resolve_session_id(session_id)
    normalized_workflow = normalize_workflow_context(workflow_context)

    conn = _connect(db_config)
    try:
        with conn:
            profile_id = _get_or_create_profile_id(conn, profile_key)
            _ensure_session(
                conn,
                session_id=resolved_session_id,
                profile_id=profile_id,
                source=source,
                metadata={"local_first": True},
            )
            assistant_turn = _append_session_event(
                conn,
                session_id=resolved_session_id,
                role="assistant",
                source=source,
                message_text=assistant_reply,
                answer_context=answer_context,
                workflow_context=normalized_workflow,
            )
            _rebuild_raw_summary_block(conn, resolved_session_id)
            mini_result = _maybe_create_mini_summary(
                conn,
                session_id=resolved_session_id,
                settings=settings,
            )
            major_result = _maybe_create_major_summary_and_memory(
                conn,
                profile_id=profile_id,
                session_id=resolved_session_id,
                settings=settings,
            )
        return {
            "session_id": resolved_session_id,
            "assistant_turn": assistant_turn,
            "mini_summary_created": mini_result is not None,
            "major_summary_created": major_result is not None,
            "major_summary_saved_memory_count": int(major_result["saved_count"]) if major_result else 0,
        }
    finally:
        conn.close()


def list_assistant_memory_items(
    *,
    session_id: str | None = None,
    limit: int = 30,
    profile_key: str = DEFAULT_PROFILE_KEY,
    include_deleted: bool = False,
    db_config: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    ensure_assistant_memory_schema(db_config)
    resolved_session_id = resolve_session_id(session_id) if session_id else None
    conn = _connect(db_config)
    try:
        with conn:
            profile_id = _get_or_create_profile_id(conn, profile_key)
            where_clauses = ["n.profile_id = %s::uuid"]
            params: list[Any] = [profile_id]
            if not include_deleted:
                where_clauses.append("n.deleted_at IS NULL")
            if resolved_session_id:
                where_clauses.append("(n.session_id = %s OR n.session_id IS NULL)")
                params.append(resolved_session_id)
            params.append(max(1, min(limit, 200)))
            where_sql = " AND ".join(where_clauses)
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    f"""
                    SELECT
                        n.id::text AS memory_id,
                        n.node_type,
                        n.content_text AS summary,
                        n.pinned,
                        n.confidence,
                        n.source_marker,
                        n.session_id,
                        n.metadata,
                        n.created_at,
                        n.updated_at,
                        n.deleted_at
                    FROM assistant_memory_nodes AS n
                    WHERE {where_sql}
                    ORDER BY n.pinned DESC, n.updated_at DESC
                    LIMIT %s;
                    """,
                    params,
                )
                rows = cursor.fetchall()
    finally:
        conn.close()

    result: list[dict[str, Any]] = []
    for row in rows:
        row_dict = dict(row)
        row_dict["summary"] = _safe_text(row_dict.get("summary"), max_length=320)
        result.append(row_dict)
    return result


def pin_assistant_memory_item(
    memory_id: str,
    *,
    pinned: bool = True,
    profile_key: str = DEFAULT_PROFILE_KEY,
    db_config: dict[str, str] | None = None,
) -> dict[str, Any]:
    ensure_assistant_memory_schema(db_config)
    conn = _connect(db_config)
    try:
        with conn:
            profile_id = _get_or_create_profile_id(conn, profile_key)
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    UPDATE assistant_memory_nodes
                    SET pinned = %s, updated_at = NOW()
                    WHERE id = %s::uuid
                    AND profile_id = %s::uuid
                    AND deleted_at IS NULL
                    RETURNING id::text AS memory_id, pinned, node_type, content_text AS summary, updated_at;
                    """,
                    (bool(pinned), memory_id, profile_id),
                )
                row = cursor.fetchone()
        if not row:
            raise KeyError("Memory item not found.")
        return dict(row)
    finally:
        conn.close()


def delete_assistant_memory_item(
    memory_id: str,
    *,
    profile_key: str = DEFAULT_PROFILE_KEY,
    db_config: dict[str, str] | None = None,
) -> bool:
    ensure_assistant_memory_schema(db_config)
    conn = _connect(db_config)
    try:
        with conn:
            profile_id = _get_or_create_profile_id(conn, profile_key)
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE assistant_memory_nodes
                    SET deleted_at = NOW(), updated_at = NOW()
                    WHERE id = %s::uuid
                    AND profile_id = %s::uuid
                    AND deleted_at IS NULL;
                    """,
                    (memory_id, profile_id),
                )
                return cursor.rowcount > 0
    finally:
        conn.close()


def get_live2d_memory_state(
    *,
    session_id: str | None = None,
    limit: int = 20,
    profile_key: str = DEFAULT_PROFILE_KEY,
    db_config: dict[str, str] | None = None,
) -> dict[str, Any]:
    resolved_session_id = resolve_session_id(session_id)
    items = list_assistant_memory_items(
        session_id=resolved_session_id,
        limit=limit,
        profile_key=profile_key,
        include_deleted=False,
        db_config=db_config,
    )
    return {
        "session_id": resolved_session_id,
        "items": items,
        "count": len(items),
    }


__all__ = [
    "DEFAULT_PROFILE_KEY",
    "DEFAULT_SESSION_ID",
    "delete_assistant_memory_item",
    "ensure_assistant_memory_schema",
    "finalize_live2d_chat_turn",
    "get_live2d_memory_state",
    "get_or_create_session",
    "list_assistant_memory_items",
    "normalize_workflow_context",
    "pin_assistant_memory_item",
    "prepare_live2d_chat_context",
    "resolve_session_id",
]
