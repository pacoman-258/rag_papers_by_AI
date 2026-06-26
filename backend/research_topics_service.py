from __future__ import annotations

import hashlib
import json
import re
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Literal

import psycopg2
from psycopg2.extras import RealDictCursor

from local_paper_db.app.search_service import DEFAULT_DB_CONFIG

TopicStatus = Literal["active", "paused", "archived"]
ThreadStatus = Literal["queued", "reading", "read", "skipped"]
InsightKind = Literal["conclusion", "evidence", "caveat", "contradiction", "open_question"]
InsightStatus = Literal["draft", "confirmed"]
SuggestionStatus = Literal["pending", "accepted", "dismissed", "expired"]

_ARXIV_ID_RE = re.compile(r"(?P<id>\d{4}\.\d{4,5})(?:v\d+)?")
USE_MEMORY_STORE = False


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def canonical_paper_key(paper: dict[str, Any]) -> str:
    for field in ("arxiv_id", "source_id", "canonical_id", "external_url", "url"):
        value = str(paper.get(field) or "")
        match = _ARXIV_ID_RE.search(value)
        if match:
            return f"arxiv:{match.group('id')}"

    source_id = paper.get("source_id") or paper.get("paper_id")
    if source_id:
        return f"source:{source_id}"

    title = _normalize_text(str(paper.get("title") or ""))
    digest = hashlib.sha256(title.encode("utf-8")).hexdigest()[:16]
    return f"title:{digest}"


def create_topic(
    title: str,
    description: str = "",
    keywords: list[str] | None = None,
    created_from: str = "manual",
) -> dict[str, Any]:
    return _with_store_fallback(
        _db_create_topic,
        _memory_create_topic,
        title=title,
        description=description,
        keywords=keywords,
        created_from=created_from,
    )


def list_topics() -> list[dict[str, Any]]:
    return _with_store_fallback(_db_list_topics, _memory_list_topics)


def get_topic(topic_id: str) -> dict[str, Any]:
    return _with_store_fallback(_db_get_topic, _memory_get_topic, topic_id)


def create_or_resume_thread(
    topic_id: str,
    paper: dict[str, Any],
    reader_session_id: str | None = None,
) -> dict[str, Any]:
    return _with_store_fallback(
        _db_create_or_resume_thread,
        _memory_create_or_resume_thread,
        topic_id=topic_id,
        paper=paper,
        reader_session_id=reader_session_id,
    )


def list_topic_threads(topic_id: str) -> list[dict[str, Any]]:
    return _with_store_fallback(_db_list_topic_threads, _memory_list_topic_threads, topic_id)


def get_thread(thread_id: str) -> dict[str, Any]:
    return _with_store_fallback(_db_get_thread, _memory_get_thread, thread_id)


def record_thread_event(
    thread_id: str,
    event_type: str,
    source: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return _with_store_fallback(
        _db_record_thread_event,
        _memory_record_thread_event,
        thread_id=thread_id,
        event_type=event_type,
        source=source,
        payload=payload,
    )


def record_citation_trace_action(
    thread_id: str,
    citation_trace_session_id: str,
    target_paper: dict[str, Any],
    final_top5: list[dict[str, Any]],
    warnings: list[str] | None = None,
    assistant_explanation: str = "",
) -> dict[str, Any]:
    return _with_store_fallback(
        _db_record_citation_trace_action,
        _memory_record_citation_trace_action,
        thread_id=thread_id,
        citation_trace_session_id=citation_trace_session_id,
        target_paper=target_paper,
        final_top5=final_top5,
        warnings=warnings,
        assistant_explanation=assistant_explanation,
    )


def create_topic_insight(
    topic_id: str,
    kind: InsightKind,
    text: str,
    source_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return _with_store_fallback(
        _db_create_topic_insight,
        _memory_create_topic_insight,
        topic_id=topic_id,
        kind=kind,
        text=text,
        source_refs=source_refs,
    )


def confirm_topic_insight(insight_id: str) -> dict[str, Any]:
    return _with_store_fallback(_db_confirm_topic_insight, _memory_confirm_topic_insight, insight_id)


def create_search_recommendation(
    *,
    query: str,
    paper: dict[str, Any],
    topic_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return _with_store_fallback(
        _db_create_search_recommendation,
        _memory_create_search_recommendation,
        query=query,
        paper=paper,
        topic_candidates=topic_candidates,
    )


def create_thread_open_question_suggestion(*, thread_id: str, question: str) -> dict[str, Any]:
    return _with_store_fallback(
        _db_create_thread_open_question_suggestion,
        _memory_create_thread_open_question_suggestion,
        thread_id=thread_id,
        question=question,
    )


def list_suggestions(status: str | None = "pending") -> list[dict[str, Any]]:
    return _with_store_fallback(_db_list_suggestions, _memory_list_suggestions, status)


def accept_suggestion(suggestion_id: str) -> dict[str, Any]:
    return _with_store_fallback(_db_accept_suggestion, _memory_accept_suggestion, suggestion_id)


def dismiss_suggestion(suggestion_id: str) -> dict[str, Any]:
    return _with_store_fallback(_db_dismiss_suggestion, _memory_dismiss_suggestion, suggestion_id)


def research_topics_schema_sql() -> str:
    return """
CREATE TABLE IF NOT EXISTS research_topics (
    topic_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    keywords JSONB NOT NULL DEFAULT '[]'::jsonb,
    status TEXT NOT NULL DEFAULT 'active',
    created_from TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_reading_threads (
    thread_id TEXT PRIMARY KEY,
    topic_id TEXT NOT NULL REFERENCES research_topics(topic_id) ON DELETE CASCADE,
    paper_key TEXT NOT NULL,
    paper_title TEXT NOT NULL,
    paper_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_page INTEGER NOT NULL DEFAULT 0,
    progress DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'queued',
    last_reader_session_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (topic_id, paper_key)
);

CREATE TABLE IF NOT EXISTS paper_reading_thread_events (
    row_id BIGSERIAL PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    thread_id TEXT NOT NULL REFERENCES paper_reading_threads(thread_id) ON DELETE CASCADE,
    topic_id TEXT NOT NULL REFERENCES research_topics(topic_id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    source TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS citation_trace_actions (
    row_id BIGSERIAL PRIMARY KEY,
    action_id TEXT NOT NULL UNIQUE,
    thread_id TEXT NOT NULL REFERENCES paper_reading_threads(thread_id) ON DELETE CASCADE,
    topic_id TEXT NOT NULL REFERENCES research_topics(topic_id) ON DELETE CASCADE,
    citation_trace_session_id TEXT NOT NULL,
    target_paper JSONB NOT NULL DEFAULT '{}'::jsonb,
    final_top5 JSONB NOT NULL DEFAULT '[]'::jsonb,
    warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    assistant_explanation TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS topic_insights (
    insight_id TEXT PRIMARY KEY,
    topic_id TEXT NOT NULL REFERENCES research_topics(topic_id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    source_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assistant_suggestions (
    suggestion_id TEXT PRIMARY KEY,
    source_workflow TEXT NOT NULL,
    source_stage TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    target_topic_candidates JSONB NOT NULL DEFAULT '[]'::jsonb,
    target_thread_id TEXT REFERENCES paper_reading_threads(thread_id) ON DELETE CASCADE,
    summary TEXT NOT NULL,
    recommended_action TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
""".strip()


def ensure_research_topics_schema(db_config: dict[str, Any] | None = None) -> None:
    with _connect(db_config) as conn:
        with conn.cursor() as cursor:
            cursor.execute(research_topics_schema_sql())


def _connect(db_config: dict[str, Any] | None = None):
    config = dict(db_config or DEFAULT_DB_CONFIG)
    config.setdefault("connect_timeout", 2)
    return psycopg2.connect(**config)


def _with_store_fallback(db_func: Any, memory_func: Any, *args: Any, **kwargs: Any) -> Any:
    if USE_MEMORY_STORE:
        return memory_func(*args, **kwargs)
    try:
        return db_func(*args, **kwargs)
    except (psycopg2.Error, OSError):
        _switch_to_memory_store()
        return memory_func(*args, **kwargs)


def _switch_to_memory_store() -> None:
    global USE_MEMORY_STORE
    USE_MEMORY_STORE = True


def _memory_create_topic(
    title: str,
    description: str = "",
    keywords: list[str] | None = None,
    created_from: str = "manual",
) -> dict[str, Any]:
    if not title.strip():
        raise ValueError("topic title cannot be empty")

    now = utc_now()
    topic = {
        "topic_id": _new_id("topic"),
        "title": title.strip(),
        "description": description,
        "keywords": list(keywords or []),
        "status": "active",
        "created_from": created_from,
        "created_at": now,
        "updated_at": now,
    }
    _MEMORY_STORE.topics[topic["topic_id"]] = topic
    return deepcopy(topic)


def _memory_list_topics() -> list[dict[str, Any]]:
    return deepcopy(_sort_by_updated_at(_MEMORY_STORE.topics.values()))


def _memory_get_topic(topic_id: str) -> dict[str, Any]:
    topic = _require_topic(topic_id)
    detail = deepcopy(topic)
    detail["threads"] = _memory_list_topic_threads(topic_id)
    detail["insights"] = _list_topic_insights(topic_id)
    return detail


def _memory_create_or_resume_thread(
    topic_id: str,
    paper: dict[str, Any],
    reader_session_id: str | None = None,
) -> dict[str, Any]:
    _require_topic(topic_id)
    paper_key = canonical_paper_key(paper)
    now = utc_now()

    for thread in _MEMORY_STORE.threads.values():
        if thread["topic_id"] == topic_id and thread["paper_key"] == paper_key:
            thread["status"] = "reading"
            thread["last_reader_session_id"] = reader_session_id
            thread["updated_at"] = now
            _touch_topic(topic_id, now)
            return deepcopy(thread)

    thread = {
        "thread_id": _new_id("thread"),
        "topic_id": topic_id,
        "paper_key": paper_key,
        "paper_title": str(paper.get("title") or "").strip() or "Untitled paper",
        "paper_metadata": deepcopy(paper),
        "last_page": 0,
        "progress": 0.0,
        "status": "reading",
        "last_reader_session_id": reader_session_id,
        "created_at": now,
        "updated_at": now,
    }
    _MEMORY_STORE.threads[thread["thread_id"]] = thread
    _touch_topic(topic_id, now)
    return deepcopy(thread)


def _memory_list_topic_threads(topic_id: str) -> list[dict[str, Any]]:
    _require_topic(topic_id)
    threads = [thread for thread in _MEMORY_STORE.threads.values() if thread["topic_id"] == topic_id]
    return deepcopy(_sort_by_updated_at(threads))


def _memory_get_thread(thread_id: str) -> dict[str, Any]:
    thread = _require_thread(thread_id)
    detail = deepcopy(thread)
    detail["events"] = deepcopy(_list_thread_events(thread_id))
    detail["citation_trace_actions"] = deepcopy(_list_thread_trace_actions(thread_id))
    return detail


def _memory_record_thread_event(
    thread_id: str,
    event_type: str,
    source: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if not event_type.strip():
        raise ValueError("event type cannot be empty")

    thread = _require_thread(thread_id)
    now = utc_now()
    event = {
        "event_id": _new_id("event"),
        "thread_id": thread_id,
        "topic_id": thread["topic_id"],
        "event_type": event_type,
        "source": source,
        "payload": deepcopy(payload),
        "created_at": now,
    }
    _MEMORY_STORE.thread_events[event["event_id"]] = event
    thread["updated_at"] = now
    _touch_topic(thread["topic_id"], now)
    return deepcopy(event)


def _memory_record_citation_trace_action(
    thread_id: str,
    citation_trace_session_id: str,
    target_paper: dict[str, Any],
    final_top5: list[dict[str, Any]],
    warnings: list[str] | None = None,
    assistant_explanation: str = "",
) -> dict[str, Any]:
    if not citation_trace_session_id.strip():
        raise ValueError("citation trace session id cannot be empty")

    thread = _require_thread(thread_id)
    now = utc_now()
    action = {
        "action_id": _new_id("trace_action"),
        "thread_id": thread_id,
        "topic_id": thread["topic_id"],
        "citation_trace_session_id": citation_trace_session_id,
        "target_paper": deepcopy(target_paper),
        "final_top5": deepcopy(final_top5),
        "warnings": list(warnings or []),
        "assistant_explanation": assistant_explanation,
        "created_at": now,
    }
    _MEMORY_STORE.trace_actions[action["action_id"]] = action
    thread["updated_at"] = now
    _touch_topic(thread["topic_id"], now)
    _memory_record_thread_event(
        thread_id=thread_id,
        event_type="citation_trace.completed",
        source="citation_trace",
        payload={
            "citation_trace_session_id": citation_trace_session_id,
            "action_id": action["action_id"],
        },
    )
    return deepcopy(action)


def _memory_create_topic_insight(
    topic_id: str,
    kind: InsightKind,
    text: str,
    source_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not text.strip():
        raise ValueError("insight text cannot be empty")

    _require_topic(topic_id)
    now = utc_now()
    insight = {
        "insight_id": _new_id("insight"),
        "topic_id": topic_id,
        "kind": kind,
        "text": text,
        "source_refs": deepcopy(source_refs or []),
        "status": "draft",
        "created_at": now,
        "updated_at": now,
    }
    _MEMORY_STORE.insights[insight["insight_id"]] = insight
    _touch_topic(topic_id, now)
    return deepcopy(insight)


def _memory_confirm_topic_insight(insight_id: str) -> dict[str, Any]:
    insight = _require_insight(insight_id)
    now = utc_now()
    insight["status"] = "confirmed"
    insight["updated_at"] = now
    _touch_topic(insight["topic_id"], now)
    return deepcopy(insight)


def _memory_create_search_recommendation(
    *,
    query: str,
    paper: dict[str, Any],
    topic_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return _memory_store_suggestion(
        {
            "suggestion_id": _new_id("suggestion"),
            "source_workflow": "search",
            "source_stage": "completed",
            "risk_level": "low",
            "target_topic_candidates": deepcopy(topic_candidates or []),
            "target_thread_id": None,
            "summary": f"Open {paper.get('title') or 'this paper'} in Paper Reader before writing topic records.",
            "recommended_action": "open_in_topic",
            "payload": {"query": query, "paper": deepcopy(paper)},
            "status": "pending",
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
    )


def _memory_create_thread_open_question_suggestion(*, thread_id: str, question: str) -> dict[str, Any]:
    _require_thread(thread_id)
    return _memory_store_suggestion(
        {
            "suggestion_id": _new_id("suggestion"),
            "source_workflow": "paper_reader",
            "source_stage": "running",
            "risk_level": "low",
            "target_topic_candidates": [],
            "target_thread_id": thread_id,
            "summary": "Save this as an open question in the current paper thread.",
            "recommended_action": "save_open_question",
            "payload": {"question": str(question or "").strip()},
            "status": "pending",
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
    )


def _memory_store_suggestion(suggestion: dict[str, Any]) -> dict[str, Any]:
    _MEMORY_STORE.suggestions[suggestion["suggestion_id"]] = suggestion
    return deepcopy(suggestion)


def _memory_list_suggestions(status: str | None = "pending") -> list[dict[str, Any]]:
    items = list(_MEMORY_STORE.suggestions.values())
    if status:
        items = [item for item in items if item.get("status") == status]
    return sorted((deepcopy(item) for item in items), key=lambda item: item["created_at"], reverse=True)


def _memory_accept_suggestion(suggestion_id: str) -> dict[str, Any]:
    suggestion = _require_suggestion(suggestion_id)
    if suggestion["status"] != "pending":
        return deepcopy(suggestion)
    now = utc_now()
    if suggestion["recommended_action"] == "save_open_question":
        question = str(suggestion.get("payload", {}).get("question") or "").strip()
        _memory_record_thread_event(
            thread_id=suggestion["target_thread_id"],
            event_type="paper_reader.open_question",
            source="assistant",
            payload={"question": question},
        )
    suggestion["status"] = "accepted"
    suggestion["updated_at"] = now
    return deepcopy(suggestion)


def _memory_dismiss_suggestion(suggestion_id: str) -> dict[str, Any]:
    suggestion = _require_suggestion(suggestion_id)
    suggestion["status"] = "dismissed"
    suggestion["updated_at"] = utc_now()
    return deepcopy(suggestion)


def _db_create_topic(
    title: str,
    description: str = "",
    keywords: list[str] | None = None,
    created_from: str = "manual",
) -> dict[str, Any]:
    if not title.strip():
        raise ValueError("topic title cannot be empty")

    ensure_research_topics_schema()
    now = utc_now()
    topic_id = _new_id("topic")
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                INSERT INTO research_topics (
                    topic_id, title, description, keywords, status, created_from, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    topic_id,
                    title.strip(),
                    description,
                    json.dumps(list(keywords or [])),
                    "active",
                    created_from,
                    now,
                    now,
                ),
            )
            return _topic_from_row(cursor.fetchone())


def _db_list_topics() -> list[dict[str, Any]]:
    ensure_research_topics_schema()
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT * FROM research_topics ORDER BY updated_at DESC")
            return [_topic_from_row(row) for row in cursor.fetchall()]


def _db_get_topic(topic_id: str) -> dict[str, Any]:
    ensure_research_topics_schema()
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            topic = _db_require_topic(cursor, topic_id)
            detail = _topic_from_row(topic)
            detail["threads"] = _db_list_topic_threads_with_cursor(cursor, topic_id)
            detail["insights"] = _db_list_topic_insights_with_cursor(cursor, topic_id)
            return detail


def _db_create_or_resume_thread(
    topic_id: str,
    paper: dict[str, Any],
    reader_session_id: str | None = None,
) -> dict[str, Any]:
    ensure_research_topics_schema()
    paper_key = canonical_paper_key(paper)
    paper_title = str(paper.get("title") or "").strip() or "Untitled paper"
    now = utc_now()
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            _db_require_topic(cursor, topic_id)
            cursor.execute(
                """
                INSERT INTO paper_reading_threads (
                    thread_id, topic_id, paper_key, paper_title, paper_metadata,
                    last_page, progress, status, last_reader_session_id, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (topic_id, paper_key) DO UPDATE SET
                    status = 'reading',
                    last_reader_session_id = EXCLUDED.last_reader_session_id,
                    updated_at = EXCLUDED.updated_at
                RETURNING *
                """,
                (
                    _new_id("thread"),
                    topic_id,
                    paper_key,
                    paper_title,
                    json.dumps(deepcopy(paper)),
                    0,
                    0.0,
                    "reading",
                    reader_session_id,
                    now,
                    now,
                ),
            )
            thread = _thread_from_row(cursor.fetchone())
            _db_touch_topic(cursor, topic_id, now)
            return thread


def _db_list_topic_threads(topic_id: str) -> list[dict[str, Any]]:
    ensure_research_topics_schema()
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            _db_require_topic(cursor, topic_id)
            return _db_list_topic_threads_with_cursor(cursor, topic_id)


def _db_get_thread(thread_id: str) -> dict[str, Any]:
    ensure_research_topics_schema()
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            thread = _thread_from_row(_db_require_thread(cursor, thread_id))
            thread["events"] = _db_list_thread_events_with_cursor(cursor, thread_id)
            thread["citation_trace_actions"] = _db_list_thread_trace_actions_with_cursor(cursor, thread_id)
            return thread


def _db_record_thread_event(
    thread_id: str,
    event_type: str,
    source: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if not event_type.strip():
        raise ValueError("event type cannot be empty")

    ensure_research_topics_schema()
    now = utc_now()
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            thread = _db_require_thread(cursor, thread_id)
            event = _db_insert_thread_event(
                cursor=cursor,
                thread_id=thread_id,
                topic_id=thread["topic_id"],
                event_type=event_type,
                source=source,
                payload=payload,
                created_at=now,
            )
            _db_touch_thread(cursor, thread_id, now)
            _db_touch_topic(cursor, thread["topic_id"], now)
            return event


def _db_record_citation_trace_action(
    thread_id: str,
    citation_trace_session_id: str,
    target_paper: dict[str, Any],
    final_top5: list[dict[str, Any]],
    warnings: list[str] | None = None,
    assistant_explanation: str = "",
) -> dict[str, Any]:
    if not citation_trace_session_id.strip():
        raise ValueError("citation trace session id cannot be empty")

    ensure_research_topics_schema()
    now = utc_now()
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            thread = _db_require_thread(cursor, thread_id)
            action_id = _new_id("trace_action")
            cursor.execute(
                """
                INSERT INTO citation_trace_actions (
                    action_id, thread_id, topic_id, citation_trace_session_id,
                    target_paper, final_top5, warnings, assistant_explanation, created_at
                )
                VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s)
                RETURNING *
                """,
                (
                    action_id,
                    thread_id,
                    thread["topic_id"],
                    citation_trace_session_id,
                    json.dumps(deepcopy(target_paper)),
                    json.dumps(deepcopy(final_top5)),
                    json.dumps(list(warnings or [])),
                    assistant_explanation,
                    now,
                ),
            )
            action = _trace_action_from_row(cursor.fetchone())
            _db_insert_thread_event(
                cursor=cursor,
                thread_id=thread_id,
                topic_id=thread["topic_id"],
                event_type="citation_trace.completed",
                source="citation_trace",
                payload={
                    "citation_trace_session_id": citation_trace_session_id,
                    "action_id": action_id,
                },
                created_at=now,
            )
            _db_touch_thread(cursor, thread_id, now)
            _db_touch_topic(cursor, thread["topic_id"], now)
            return action


def _db_create_topic_insight(
    topic_id: str,
    kind: InsightKind,
    text: str,
    source_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not text.strip():
        raise ValueError("insight text cannot be empty")

    ensure_research_topics_schema()
    now = utc_now()
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            _db_require_topic(cursor, topic_id)
            cursor.execute(
                """
                INSERT INTO topic_insights (
                    insight_id, topic_id, kind, text, source_refs, status, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s)
                RETURNING *
                """,
                (
                    _new_id("insight"),
                    topic_id,
                    kind,
                    text,
                    json.dumps(deepcopy(source_refs or [])),
                    "draft",
                    now,
                    now,
                ),
            )
            insight = _insight_from_row(cursor.fetchone())
            _db_touch_topic(cursor, topic_id, now)
            return insight


def _db_confirm_topic_insight(insight_id: str) -> dict[str, Any]:
    ensure_research_topics_schema()
    now = utc_now()
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            _db_require_insight(cursor, insight_id)
            cursor.execute(
                """
                UPDATE topic_insights
                SET status = 'confirmed', updated_at = %s
                WHERE insight_id = %s
                RETURNING *
                """,
                (now, insight_id),
            )
            insight = _insight_from_row(cursor.fetchone())
            _db_touch_topic(cursor, insight["topic_id"], now)
            return insight


def _db_create_search_recommendation(
    *,
    query: str,
    paper: dict[str, Any],
    topic_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return _db_store_suggestion(
        {
            "suggestion_id": _new_id("suggestion"),
            "source_workflow": "search",
            "source_stage": "completed",
            "risk_level": "low",
            "target_topic_candidates": deepcopy(topic_candidates or []),
            "target_thread_id": None,
            "summary": f"Open {paper.get('title') or 'this paper'} in Paper Reader before writing topic records.",
            "recommended_action": "open_in_topic",
            "payload": {"query": query, "paper": deepcopy(paper)},
            "status": "pending",
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
    )


def _db_create_thread_open_question_suggestion(*, thread_id: str, question: str) -> dict[str, Any]:
    ensure_research_topics_schema()
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            _db_require_thread(cursor, thread_id)
    return _db_store_suggestion(
        {
            "suggestion_id": _new_id("suggestion"),
            "source_workflow": "paper_reader",
            "source_stage": "running",
            "risk_level": "low",
            "target_topic_candidates": [],
            "target_thread_id": thread_id,
            "summary": "Save this as an open question in the current paper thread.",
            "recommended_action": "save_open_question",
            "payload": {"question": str(question or "").strip()},
            "status": "pending",
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
    )


def _db_store_suggestion(suggestion: dict[str, Any]) -> dict[str, Any]:
    ensure_research_topics_schema()
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                INSERT INTO assistant_suggestions (
                    suggestion_id, source_workflow, source_stage, risk_level,
                    target_topic_candidates, target_thread_id, summary,
                    recommended_action, payload, status, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s::jsonb, %s, %s, %s)
                RETURNING *
                """,
                (
                    suggestion["suggestion_id"],
                    suggestion["source_workflow"],
                    suggestion["source_stage"],
                    suggestion["risk_level"],
                    json.dumps(deepcopy(suggestion["target_topic_candidates"])),
                    suggestion["target_thread_id"],
                    suggestion["summary"],
                    suggestion["recommended_action"],
                    json.dumps(deepcopy(suggestion["payload"])),
                    suggestion["status"],
                    suggestion["created_at"],
                    suggestion["updated_at"],
                ),
            )
            return _suggestion_from_row(cursor.fetchone())


def _db_list_suggestions(status: str | None = "pending") -> list[dict[str, Any]]:
    ensure_research_topics_schema()
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            if status:
                cursor.execute(
                    """
                    SELECT *
                    FROM assistant_suggestions
                    WHERE status = %s
                    ORDER BY created_at DESC
                    """,
                    (status,),
                )
            else:
                cursor.execute("SELECT * FROM assistant_suggestions ORDER BY created_at DESC")
            return [_suggestion_from_row(row) for row in cursor.fetchall()]


def _db_accept_suggestion(suggestion_id: str) -> dict[str, Any]:
    ensure_research_topics_schema()
    now = utc_now()
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            suggestion = _suggestion_from_row(_db_require_suggestion(cursor, suggestion_id))
            if suggestion["status"] != "pending":
                return suggestion
            if suggestion["recommended_action"] == "save_open_question":
                thread_id = suggestion["target_thread_id"]
                question = str(suggestion.get("payload", {}).get("question") or "").strip()
                thread = _db_require_thread(cursor, thread_id)
                _db_insert_thread_event(
                    cursor=cursor,
                    thread_id=thread_id,
                    topic_id=thread["topic_id"],
                    event_type="paper_reader.open_question",
                    source="assistant",
                    payload={"question": question},
                    created_at=now,
                )
                _db_touch_thread(cursor, thread_id, now)
                _db_touch_topic(cursor, thread["topic_id"], now)
            cursor.execute(
                """
                UPDATE assistant_suggestions
                SET status = 'accepted', updated_at = %s
                WHERE suggestion_id = %s
                RETURNING *
                """,
                (now, suggestion_id),
            )
            return _suggestion_from_row(cursor.fetchone())


def _db_dismiss_suggestion(suggestion_id: str) -> dict[str, Any]:
    ensure_research_topics_schema()
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            _db_require_suggestion(cursor, suggestion_id)
            cursor.execute(
                """
                UPDATE assistant_suggestions
                SET status = 'dismissed', updated_at = %s
                WHERE suggestion_id = %s
                RETURNING *
                """,
                (utc_now(), suggestion_id),
            )
            return _suggestion_from_row(cursor.fetchone())


class ResearchTopicMemoryStore:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.topics: dict[str, dict[str, Any]] = {}
        self.threads: dict[str, dict[str, Any]] = {}
        self.thread_events: dict[str, dict[str, Any]] = {}
        self.trace_actions: dict[str, dict[str, Any]] = {}
        self.insights: dict[str, dict[str, Any]] = {}
        self.suggestions: dict[str, dict[str, Any]] = {}


_MEMORY_STORE = ResearchTopicMemoryStore()


def _normalize_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _sort_by_updated_at(items: Any) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: item.get("updated_at", ""), reverse=True)


def _touch_topic(topic_id: str, now: str | None = None) -> None:
    _MEMORY_STORE.topics[topic_id]["updated_at"] = now or utc_now()


def _require_topic(topic_id: str) -> dict[str, Any]:
    try:
        return _MEMORY_STORE.topics[topic_id]
    except KeyError as exc:
        raise KeyError(f"topic not found: {topic_id}") from exc


def _require_thread(thread_id: str) -> dict[str, Any]:
    try:
        return _MEMORY_STORE.threads[thread_id]
    except KeyError as exc:
        raise KeyError(f"thread not found: {thread_id}") from exc


def _require_insight(insight_id: str) -> dict[str, Any]:
    try:
        return _MEMORY_STORE.insights[insight_id]
    except KeyError as exc:
        raise KeyError(f"insight not found: {insight_id}") from exc


def _require_suggestion(suggestion_id: str) -> dict[str, Any]:
    try:
        return _MEMORY_STORE.suggestions[suggestion_id]
    except KeyError as exc:
        raise KeyError(f"assistant suggestion not found: {suggestion_id}") from exc


def _list_topic_insights(topic_id: str) -> list[dict[str, Any]]:
    insights = [insight for insight in _MEMORY_STORE.insights.values() if insight["topic_id"] == topic_id]
    return deepcopy(_sort_by_updated_at(insights))


def _list_thread_events(thread_id: str) -> list[dict[str, Any]]:
    return [
        event
        for event in _MEMORY_STORE.thread_events.values()
        if event["thread_id"] == thread_id
    ]


def _list_thread_trace_actions(thread_id: str) -> list[dict[str, Any]]:
    return [
        action
        for action in _MEMORY_STORE.trace_actions.values()
        if action["thread_id"] == thread_id
    ]


def _decode_json_value(value: Any, default: Any) -> Any:
    if value is None:
        return deepcopy(default)
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return deepcopy(default)
    return deepcopy(value)


def _topic_from_row(row: Any) -> dict[str, Any]:
    return {
        "topic_id": row["topic_id"],
        "title": row["title"],
        "description": row.get("description") or "",
        "keywords": _decode_json_value(row.get("keywords"), []),
        "status": row.get("status") or "active",
        "created_from": row.get("created_from") or "manual",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _thread_from_row(row: Any) -> dict[str, Any]:
    return {
        "thread_id": row["thread_id"],
        "topic_id": row["topic_id"],
        "paper_key": row["paper_key"],
        "paper_title": row["paper_title"],
        "paper_metadata": _decode_json_value(row.get("paper_metadata"), {}),
        "last_page": int(row.get("last_page") or 0),
        "progress": float(row.get("progress") or 0.0),
        "status": row.get("status") or "queued",
        "last_reader_session_id": row.get("last_reader_session_id"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _thread_event_from_row(row: Any) -> dict[str, Any]:
    return {
        "event_id": row["event_id"],
        "thread_id": row["thread_id"],
        "topic_id": row["topic_id"],
        "event_type": row["event_type"],
        "source": row["source"],
        "payload": _decode_json_value(row.get("payload"), {}),
        "created_at": row["created_at"],
    }


def _trace_action_from_row(row: Any) -> dict[str, Any]:
    return {
        "action_id": row["action_id"],
        "thread_id": row["thread_id"],
        "topic_id": row["topic_id"],
        "citation_trace_session_id": row["citation_trace_session_id"],
        "target_paper": _decode_json_value(row.get("target_paper"), {}),
        "final_top5": _decode_json_value(row.get("final_top5"), []),
        "warnings": _decode_json_value(row.get("warnings"), []),
        "assistant_explanation": row.get("assistant_explanation") or "",
        "created_at": row["created_at"],
    }


def _insight_from_row(row: Any) -> dict[str, Any]:
    return {
        "insight_id": row["insight_id"],
        "topic_id": row["topic_id"],
        "kind": row["kind"],
        "text": row["text"],
        "source_refs": _decode_json_value(row.get("source_refs"), []),
        "status": row.get("status") or "draft",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _suggestion_from_row(row: Any) -> dict[str, Any]:
    return {
        "suggestion_id": row["suggestion_id"],
        "source_workflow": row["source_workflow"],
        "source_stage": row["source_stage"],
        "risk_level": row["risk_level"],
        "target_topic_candidates": _decode_json_value(row.get("target_topic_candidates"), []),
        "target_thread_id": row.get("target_thread_id"),
        "summary": row["summary"],
        "recommended_action": row["recommended_action"],
        "payload": _decode_json_value(row.get("payload"), {}),
        "status": row.get("status") or "pending",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _db_require_topic(cursor: Any, topic_id: str) -> Any:
    cursor.execute("SELECT * FROM research_topics WHERE topic_id = %s", (topic_id,))
    row = cursor.fetchone()
    if row is None:
        raise KeyError(f"topic not found: {topic_id}")
    return row


def _db_require_thread(cursor: Any, thread_id: str) -> Any:
    cursor.execute("SELECT * FROM paper_reading_threads WHERE thread_id = %s", (thread_id,))
    row = cursor.fetchone()
    if row is None:
        raise KeyError(f"thread not found: {thread_id}")
    return row


def _db_require_insight(cursor: Any, insight_id: str) -> Any:
    cursor.execute("SELECT * FROM topic_insights WHERE insight_id = %s", (insight_id,))
    row = cursor.fetchone()
    if row is None:
        raise KeyError(f"insight not found: {insight_id}")
    return row


def _db_require_suggestion(cursor: Any, suggestion_id: str) -> Any:
    cursor.execute("SELECT * FROM assistant_suggestions WHERE suggestion_id = %s", (suggestion_id,))
    row = cursor.fetchone()
    if row is None:
        raise KeyError(f"assistant suggestion not found: {suggestion_id}")
    return row


def _db_touch_topic(cursor: Any, topic_id: str, now: str) -> None:
    cursor.execute("UPDATE research_topics SET updated_at = %s WHERE topic_id = %s", (now, topic_id))


def _db_touch_thread(cursor: Any, thread_id: str, now: str) -> None:
    cursor.execute("UPDATE paper_reading_threads SET updated_at = %s WHERE thread_id = %s", (now, thread_id))


def _db_list_topic_threads_with_cursor(cursor: Any, topic_id: str) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT *
        FROM paper_reading_threads
        WHERE topic_id = %s
        ORDER BY updated_at DESC
        """,
        (topic_id,),
    )
    return [_thread_from_row(row) for row in cursor.fetchall()]


def _db_list_topic_insights_with_cursor(cursor: Any, topic_id: str) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT *
        FROM topic_insights
        WHERE topic_id = %s
        ORDER BY updated_at DESC
        """,
        (topic_id,),
    )
    return [_insight_from_row(row) for row in cursor.fetchall()]


def _db_list_thread_events_with_cursor(cursor: Any, thread_id: str) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT *
        FROM paper_reading_thread_events
        WHERE thread_id = %s
        ORDER BY row_id ASC
        """,
        (thread_id,),
    )
    return [_thread_event_from_row(row) for row in cursor.fetchall()]


def _db_list_thread_trace_actions_with_cursor(cursor: Any, thread_id: str) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT *
        FROM citation_trace_actions
        WHERE thread_id = %s
        ORDER BY row_id ASC
        """,
        (thread_id,),
    )
    return [_trace_action_from_row(row) for row in cursor.fetchall()]


def _db_insert_thread_event(
    cursor: Any,
    thread_id: str,
    topic_id: str,
    event_type: str,
    source: str,
    payload: dict[str, Any],
    created_at: str,
) -> dict[str, Any]:
    cursor.execute(
        """
        INSERT INTO paper_reading_thread_events (
            event_id, thread_id, topic_id, event_type, source, payload, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
        RETURNING *
        """,
        (
            _new_id("event"),
            thread_id,
            topic_id,
            event_type,
            source,
            json.dumps(deepcopy(payload)),
            created_at,
        ),
    )
    return _thread_event_from_row(cursor.fetchone())
