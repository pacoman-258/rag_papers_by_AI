# Research Topics Assistant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build topic-centered research archives where Paper Reader creates durable paper reading threads, Citation Trace is stored as a thread action, search only recommends next steps, and Live2D uses a dedicated assistant model configuration.

**Architecture:** Add `assistant_chat` as a first-class runtime model config, then add a focused `backend/research_topics_service.py` boundary for topics, paper reading threads, thread events, trace actions, insights, and suggestion cards. Frontend work adds a `Research Topics` page, quiet assistant suggestion cards, and workflow integration points while keeping search writes recommendation-only.

**Tech Stack:** Python 3.13, FastAPI, Pydantic, psycopg2/PostgreSQL, unittest, React 18, Vite, source-level frontend tests.

---

## File Structure

- Modify `local_paper_db/app/search_service.py`: add `assistant_chat` to `RuntimeSettings` and env defaults.
- Modify `backend/schemas.py`: add assistant config fields, research topic API models, and suggestion models.
- Modify `backend/config_store.py`: persist, merge, and respond with `assistant_chat` using write-only API key behavior.
- Modify `config/runtime_settings.example.json`: include default `assistant_chat`.
- Modify `backend/live2d_service.py`: use `settings.assistant_chat` for Live2D chat and suggestion synthesis.
- Create `backend/research_topics_service.py`: topic archive persistence, canonical paper keys, thread events, trace actions, insights, and rule-first suggestions.
- Modify `backend/main.py`: expose research topic and suggestion APIs, keeping route bodies thin.
- Modify `frontend/src/App.jsx`: add settings UI for `assistant_chat`, `research_topics` tab, assistant suggestion plumbing, and search recommendation handling.
- Create `frontend/src/ResearchTopicsPage.jsx`: full topic archive management surface.
- Modify `frontend/src/Live2DAssistant.jsx`: quiet suggestion-card area.
- Modify `frontend/src/PaperReaderPage.jsx`: topic attachment state, thread resume/create calls, and thread event publishing.
- Modify `frontend/src/CitationTracePage.jsx`: optional thread context and trace action persistence.
- Modify `frontend/src/styles.css`: topic archive and suggestion-card styles.
- Create `tests/test_assistant_chat_config.py`: runtime config and Live2D model routing tests.
- Create `tests/test_research_topics_service.py`: service-level topic/thread/event/action/insight/suggestion tests.
- Create `tests/test_research_topics_api.py`: FastAPI route tests with service functions patched.
- Create `tests/test_research_topics_frontend.py`: source-level frontend integration tests.
- Modify `README.md`, `README.zh-CN.md`, and `PROJECT_LOG.md` after implementation.

## Task 1: Assistant Chat Runtime Configuration

**Files:**
- Create: `tests/test_assistant_chat_config.py`
- Modify: `local_paper_db/app/search_service.py`
- Modify: `backend/schemas.py`
- Modify: `backend/config_store.py`
- Modify: `config/runtime_settings.example.json`

- [ ] **Step 1: Write failing config tests**

Create `tests/test_assistant_chat_config.py` with this content:

```python
import unittest
from unittest.mock import patch

from backend.config_store import runtime_settings_to_response, runtime_settings_to_storage, storage_to_runtime_settings
from local_paper_db.app.search_service import (
    AssistantMemoryConfig,
    ChatConfig,
    EmbeddingConfig,
    PaperReaderChatConfig,
    RerankConfig,
    RetrievalConfig,
    RuntimeSettings,
)


def _settings() -> RuntimeSettings:
    return RuntimeSettings(
        query_chat=ChatConfig(provider="ollama", model="query-model", base_url="http://localhost:11434/api"),
        answer_chat=ChatConfig(provider="ollama", model="answer-model", base_url="http://localhost:11434/api"),
        assistant_chat=ChatConfig(
            provider="openai_compatible",
            model="assistant-model",
            base_url="https://assistant.example/v1",
            api_key="assistant-key",
        ),
        paper_reader_chat=PaperReaderChatConfig(
            provider="ollama",
            model="reader-model",
            base_url="http://localhost:11434/api",
            max_context_tokens=8192,
        ),
        paper_reader_translation=ChatConfig(
            provider="ollama",
            model="translator-model",
            base_url="http://localhost:11434/api",
        ),
        citation_trace_main_chat=ChatConfig(
            provider="ollama",
            model="trace-main-model",
            base_url="http://localhost:11434/api",
        ),
        citation_trace_worker_chat=ChatConfig(
            provider="ollama",
            model="trace-worker-model",
            base_url="http://localhost:11434/api",
        ),
        embedding=EmbeddingConfig(api_url="http://localhost:11434/api", model="embed-model"),
        retrieval=RetrievalConfig(top_k=5, top_n=3, request_timeout=30),
        rerank=RerankConfig(base_url="https://rerank.example/v1", model="rerank-model"),
        assistant_memory=AssistantMemoryConfig(),
    )


class AssistantChatConfigTest(unittest.TestCase):
    def test_runtime_settings_round_trips_assistant_chat_without_echoing_key(self) -> None:
        settings = _settings()

        stored = runtime_settings_to_storage(settings)
        restored = storage_to_runtime_settings(stored)
        response = runtime_settings_to_response(restored)

        self.assertEqual(stored["assistant_chat"]["model"], "assistant-model")
        self.assertEqual(stored["assistant_chat"]["api_key"], "assistant-key")
        self.assertEqual(restored.assistant_chat.model, "assistant-model")
        self.assertEqual(restored.assistant_chat.base_url, "https://assistant.example/v1")
        self.assertEqual(restored.assistant_chat.api_key, "assistant-key")
        self.assertEqual(response.assistant_chat.model, "assistant-model")
        self.assertTrue(response.assistant_chat.has_api_key)
        self.assertFalse(hasattr(response.assistant_chat, "api_key"))

    def test_missing_assistant_chat_inherits_saved_answer_chat(self) -> None:
        settings = _settings()
        stored = runtime_settings_to_storage(settings)
        stored["answer_chat"].update(
            {
                "provider": "openai_compatible",
                "model": "answer-remote-model",
                "base_url": "https://answer.example/v1",
                "api_key": "answer-key",
            }
        )
        stored.pop("assistant_chat")

        with patch("backend.config_store.get_env_default_settings", return_value=_settings()):
            restored = storage_to_runtime_settings(stored)

        self.assertEqual(restored.assistant_chat.provider, "openai_compatible")
        self.assertEqual(restored.assistant_chat.model, "answer-remote-model")
        self.assertEqual(restored.assistant_chat.base_url, "https://answer.example/v1")
        self.assertEqual(restored.assistant_chat.api_key, "answer-key")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run config tests and verify failure**

Run:

```bash
.venv/bin/python -m unittest tests.test_assistant_chat_config
```

Expected: FAIL because `RuntimeSettings` and runtime settings schemas do not have `assistant_chat`.

- [ ] **Step 3: Add `assistant_chat` to runtime dataclass and env defaults**

In `local_paper_db/app/search_service.py`, update `RuntimeSettings`:

```python
@dataclass(slots=True)
class RuntimeSettings:
    query_chat: ChatConfig
    answer_chat: ChatConfig
    assistant_chat: ChatConfig
    paper_reader_chat: PaperReaderChatConfig
    paper_reader_translation: ChatConfig
    citation_trace_main_chat: ChatConfig
    citation_trace_worker_chat: ChatConfig
    embedding: EmbeddingConfig
    retrieval: RetrievalConfig
    rerank: RerankConfig
    assistant_memory: AssistantMemoryConfig = field(default_factory=AssistantMemoryConfig)
```

In `get_env_default_settings()`, create `assistant_chat` after `answer_chat`:

```python
    assistant_chat = ChatConfig(
        provider=normalize_provider(os.getenv("ASSISTANT_CHAT_PROVIDER", answer_chat.provider)),
        model=os.getenv("ASSISTANT_CHAT_MODEL", answer_chat.model),
        base_url=os.getenv("ASSISTANT_CHAT_BASE_URL", answer_chat.base_url),
        api_key=os.getenv("ASSISTANT_CHAT_API_KEY", answer_chat.api_key),
    )
```

Pass `assistant_chat=assistant_chat` into the returned `RuntimeSettings`.

- [ ] **Step 4: Add `assistant_chat` to request and response schemas**

In `backend/schemas.py`, update `RuntimeSettingsRequest` and `RuntimeSettingsResponse`:

```python
class RuntimeSettingsRequest(BaseModel):
    query_chat: ChatConfigRequest
    answer_chat: ChatConfigRequest
    assistant_chat: ChatConfigRequest | None = None
    paper_reader_chat: PaperReaderChatConfigRequest | None = None
    paper_reader_translation: ChatConfigRequest | None = None
    citation_trace_main_chat: ChatConfigRequest | None = None
    citation_trace_worker_chat: ChatConfigRequest | None = None
    embedding: EmbeddingConfigModel
    retrieval: RetrievalConfigRequest
    rerank: RerankConfigRequest
    assistant_memory: AssistantMemoryConfigModel | None = None


class RuntimeSettingsResponse(BaseModel):
    query_chat: ChatConfigResponse
    answer_chat: ChatConfigResponse
    assistant_chat: ChatConfigResponse
    paper_reader_chat: PaperReaderChatConfigResponse
    paper_reader_translation: ChatConfigResponse
    citation_trace_main_chat: ChatConfigResponse
    citation_trace_worker_chat: ChatConfigResponse
    embedding: EmbeddingConfigModel
    retrieval: RetrievalConfigModel
    rerank: RerankConfigResponse
    assistant_memory: AssistantMemoryConfigModel
```

- [ ] **Step 5: Persist, merge, and respond with `assistant_chat`**

In `backend/config_store.py`, add `assistant_chat` to `runtime_settings_to_storage()`:

```python
        "assistant_chat": {
            "provider": settings.assistant_chat.provider,
            "model": settings.assistant_chat.model,
            "base_url": settings.assistant_chat.base_url,
            "api_key": settings.assistant_chat.api_key,
        },
```

In `storage_to_runtime_settings()`, read optional data and fallback to saved `answer_chat`:

```python
    assistant_chat_data = (
        data.get("assistant_chat") if isinstance(data.get("assistant_chat"), dict) else {}
    )
```

After `answer_chat` is created:

```python
    assistant_has_identity = bool(
        assistant_chat_data.get("provider") or assistant_chat_data.get("model")
    )
    assistant_fallback = default_settings.assistant_chat if assistant_has_identity else answer_chat
    assistant_chat = ChatConfig(
        provider=assistant_chat_data.get("provider") or assistant_fallback.provider,
        model=assistant_chat_data.get("model") or assistant_fallback.model,
        base_url=assistant_chat_data.get("base_url") or assistant_fallback.base_url,
        api_key=assistant_chat_data.get("api_key", assistant_fallback.api_key),
    )
```

Pass `assistant_chat=assistant_chat` into `RuntimeSettings`.

In `merge_runtime_settings()`, merge optional incoming assistant config:

```python
    assistant_chat = merge_optional_chat(
        base.assistant_chat,
        incoming.assistant_chat,
        embedding_api_url,
    )
```

Pass `assistant_chat=assistant_chat` into the returned `RuntimeSettings`.

In `runtime_settings_to_response()`, add:

```python
        assistant_chat=ChatConfigResponse(
            provider=settings.assistant_chat.provider,
            model=settings.assistant_chat.model,
            base_url=settings.assistant_chat.base_url,
            has_api_key=bool(settings.assistant_chat.api_key),
        ),
```

- [ ] **Step 6: Update example config**

In `config/runtime_settings.example.json`, insert after `answer_chat`:

```json
  "assistant_chat": {
    "provider": "ollama",
    "model": "qwen3:8b",
    "base_url": null,
    "api_key": null
  },
```

- [ ] **Step 7: Run config tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_assistant_chat_config tests.test_paper_reader_translation
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add tests/test_assistant_chat_config.py local_paper_db/app/search_service.py backend/schemas.py backend/config_store.py config/runtime_settings.example.json
git commit -m "Add assistant chat runtime config"
```

## Task 2: Live2D Uses Assistant Chat Model

**Files:**
- Modify: `tests/test_assistant_chat_config.py`
- Modify: `backend/live2d_service.py`

- [ ] **Step 1: Add failing Live2D routing test**

Append to `tests/test_assistant_chat_config.py`:

```python
from backend import live2d_service


class Live2DAssistantChatRoutingTest(unittest.TestCase):
    def test_live2d_reply_uses_assistant_chat_config(self) -> None:
        settings = _settings()
        captured_models: list[str] = []

        def fake_chat_completion(_messages, config, _timeout):
            captured_models.append(config.model)
            return '{"reply_text":"我在。","speak_text":"我在。","expression":""}'

        with patch("backend.live2d_service.prepare_live2d_chat_context", return_value={
            "session_id": "session-1",
            "memory_used": False,
            "used_memory_items": [],
            "memory_prompt_block": None,
            "memory_notice": None,
            "workflow_context": None,
        }):
            with patch("backend.live2d_service.finalize_live2d_chat_turn"):
                with patch("backend.live2d_service.chat_completion", side_effect=fake_chat_completion):
                    result = live2d_service.generate_live2d_reply(
                        source="user",
                        message="你好",
                        language="zh",
                        history=[],
                        answer_context=None,
                        workflow_context=None,
                        session_id="session-1",
                        settings=settings,
                        available_expressions=[],
                    )

        self.assertEqual(result["reply_text"], "我在。")
        self.assertEqual(captured_models, ["assistant-model"])
```

- [ ] **Step 2: Run the new test and verify failure**

Run:

```bash
.venv/bin/python -m unittest tests.test_assistant_chat_config.Live2DAssistantChatRoutingTest
```

Expected: FAIL because Live2D still calls `chat_completion(..., settings.answer_chat, ...)`.

- [ ] **Step 3: Route Live2D chat through `assistant_chat`**

In `backend/live2d_service.py`, replace:

```python
    raw_content = chat_completion(messages, settings.answer_chat, settings.retrieval.request_timeout)
```

with:

```python
    raw_content = chat_completion(messages, settings.assistant_chat, settings.retrieval.request_timeout)
```

- [ ] **Step 4: Run Live2D routing tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_assistant_chat_config tests.test_paper_reader_live2d_behavior tests.test_assistant_research_profile
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_assistant_chat_config.py backend/live2d_service.py
git commit -m "Use assistant chat model for Live2D"
```

## Task 3: Research Topics Service Core

**Files:**
- Create: `backend/research_topics_service.py`
- Create: `tests/test_research_topics_service.py`

- [ ] **Step 1: Write failing service tests**

Create `tests/test_research_topics_service.py` with this content:

```python
import unittest

from backend import research_topics_service as rts


class ResearchTopicsServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        rts._MEMORY_STORE.reset()

    def test_canonical_paper_key_prefers_arxiv_id(self) -> None:
        self.assertEqual(
            rts.canonical_paper_key(
                {
                    "arxiv_id": "https://arxiv.org/abs/1706.03762v7",
                    "title": "Attention Is All You Need",
                }
            ),
            "arxiv:1706.03762",
        )

    def test_same_topic_and_paper_resumes_one_thread(self) -> None:
        topic = rts.create_topic(title="Graph RAG Memory", description="", keywords=["graph rag"])
        first = rts.create_or_resume_thread(
            topic_id=topic["topic_id"],
            paper={
                "arxiv_id": "1706.03762",
                "title": "Attention Is All You Need",
                "source": "arxiv",
            },
            reader_session_id="reader-1",
        )
        second = rts.create_or_resume_thread(
            topic_id=topic["topic_id"],
            paper={
                "arxiv_id": "1706.03762v3",
                "title": "Attention Is All You Need",
                "source": "arxiv",
            },
            reader_session_id="reader-2",
        )

        self.assertEqual(first["thread_id"], second["thread_id"])
        self.assertEqual(second["last_reader_session_id"], "reader-2")
        self.assertEqual(len(rts.list_topic_threads(topic["topic_id"])), 1)

    def test_thread_events_and_trace_actions_are_thread_scoped(self) -> None:
        topic = rts.create_topic(title="Long Context RAG", description="", keywords=[])
        thread = rts.create_or_resume_thread(
            topic_id=topic["topic_id"],
            paper={"title": "Context Windows for RAG", "source_id": "paper-1"},
            reader_session_id="reader-1",
        )

        event = rts.record_thread_event(
            thread_id=thread["thread_id"],
            event_type="paper_reader.question",
            source="user",
            payload={"question": "What is the main bottleneck?"},
        )
        action = rts.record_citation_trace_action(
            thread_id=thread["thread_id"],
            citation_trace_session_id="trace-1",
            target_paper={"title": "Context Windows for RAG"},
            final_top5=[{"title": "Prior Context Paper"}],
            warnings=["weak evidence"],
            assistant_explanation="Treat this as a caveat.",
        )

        detail = rts.get_thread(thread["thread_id"])
        self.assertEqual(event["thread_id"], thread["thread_id"])
        self.assertEqual(action["thread_id"], thread["thread_id"])
        self.assertEqual(detail["events"][0]["payload"]["question"], "What is the main bottleneck?")
        self.assertEqual(detail["citation_trace_actions"][0]["warnings"], ["weak evidence"])

    def test_topic_insights_start_as_drafts_until_confirmed(self) -> None:
        topic = rts.create_topic(title="Retrieval Degradation", description="", keywords=[])
        insight = rts.create_topic_insight(
            topic_id=topic["topic_id"],
            kind="caveat",
            text="Author overlap alone is weak evidence.",
            source_refs=[{"source": "citation_trace", "id": "trace-1"}],
        )
        confirmed = rts.confirm_topic_insight(insight["insight_id"])

        self.assertEqual(insight["status"], "draft")
        self.assertEqual(confirmed["status"], "confirmed")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run service tests and verify failure**

Run:

```bash
.venv/bin/python -m unittest tests.test_research_topics_service
```

Expected: FAIL because `backend.research_topics_service` does not exist.

- [ ] **Step 3: Create service dataclasses and in-process store**

Create `backend/research_topics_service.py` with these imports and helpers:

```python
from __future__ import annotations

import hashlib
import re
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Literal


TopicStatus = Literal["active", "paused", "archived"]
ThreadStatus = Literal["queued", "reading", "read", "skipped"]
InsightKind = Literal["conclusion", "evidence", "caveat", "contradiction", "open_question"]
InsightStatus = Literal["draft", "confirmed"]
SuggestionStatus = Literal["pending", "accepted", "dismissed", "expired"]


_ARXIV_ID_RE = re.compile(r"(?P<id>\d{4}\.\d{4,5})(?:v\d+)?")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def canonical_paper_key(paper: dict[str, Any]) -> str:
    for key in ("arxiv_id", "source_id", "canonical_id", "external_url", "url"):
        value = str(paper.get(key) or "").strip()
        match = _ARXIV_ID_RE.search(value)
        if match:
            return f"arxiv:{match.group('id')}"
    source = str(paper.get("source") or "paper").strip().lower() or "paper"
    source_id = str(paper.get("source_id") or paper.get("paper_id") or "").strip().lower()
    if source_id:
        return f"{source}:{source_id}"
    title = re.sub(r"\s+", " ", str(paper.get("title") or "").strip().lower())
    digest = hashlib.sha256(title.encode("utf-8")).hexdigest()[:16]
    return f"title:{digest}"
```

Add an in-process store for the first implementation pass:

```python
class ResearchTopicMemoryStore:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.topics: dict[str, dict[str, Any]] = {}
        self.threads: dict[str, dict[str, Any]] = {}
        self.thread_events: dict[str, list[dict[str, Any]]] = {}
        self.trace_actions: dict[str, list[dict[str, Any]]] = {}
        self.insights: dict[str, dict[str, Any]] = {}
        self.suggestions: dict[str, dict[str, Any]] = {}


_MEMORY_STORE = ResearchTopicMemoryStore()
```

This in-process store is the fallback used when the durable PostgreSQL topic store is unavailable. Task 4 adds the durable schema and switches the normal service path to PostgreSQL while preserving these function signatures.

- [ ] **Step 4: Implement topic and thread functions**

Add to `backend/research_topics_service.py`:

```python
def create_topic(
    *,
    title: str,
    description: str = "",
    keywords: list[str] | None = None,
    created_from: str = "manual",
) -> dict[str, Any]:
    now = utc_now()
    topic = {
        "topic_id": _new_id("topic"),
        "title": str(title or "").strip(),
        "description": str(description or "").strip(),
        "keywords": [str(item).strip() for item in (keywords or []) if str(item).strip()],
        "status": "active",
        "created_from": created_from,
        "created_at": now,
        "updated_at": now,
    }
    if not topic["title"]:
        raise ValueError("Topic title is required.")
    _MEMORY_STORE.topics[topic["topic_id"]] = topic
    return deepcopy(topic)


def list_topics() -> list[dict[str, Any]]:
    return sorted((deepcopy(item) for item in _MEMORY_STORE.topics.values()), key=lambda item: item["updated_at"], reverse=True)


def get_topic(topic_id: str) -> dict[str, Any]:
    topic = _MEMORY_STORE.topics.get(topic_id)
    if topic is None:
        raise KeyError("Research topic not found.")
    result = deepcopy(topic)
    result["threads"] = list_topic_threads(topic_id)
    result["insights"] = [
        deepcopy(item) for item in _MEMORY_STORE.insights.values() if item["topic_id"] == topic_id
    ]
    return result


def create_or_resume_thread(
    *,
    topic_id: str,
    paper: dict[str, Any],
    reader_session_id: str | None = None,
) -> dict[str, Any]:
    if topic_id not in _MEMORY_STORE.topics:
        raise KeyError("Research topic not found.")
    paper_key = canonical_paper_key(paper)
    now = utc_now()
    for thread in _MEMORY_STORE.threads.values():
        if thread["topic_id"] == topic_id and thread["paper_key"] == paper_key:
            thread["last_reader_session_id"] = reader_session_id or thread.get("last_reader_session_id")
            thread["status"] = "reading"
            thread["updated_at"] = now
            _MEMORY_STORE.topics[topic_id]["updated_at"] = now
            return deepcopy(thread)
    thread = {
        "thread_id": _new_id("thread"),
        "topic_id": topic_id,
        "paper_key": paper_key,
        "paper_title": str(paper.get("title") or "").strip() or "Untitled paper",
        "paper_metadata": deepcopy(paper),
        "status": "reading",
        "last_page": 0,
        "progress": 0.0,
        "last_reader_session_id": reader_session_id,
        "created_at": now,
        "updated_at": now,
    }
    _MEMORY_STORE.threads[thread["thread_id"]] = thread
    _MEMORY_STORE.thread_events[thread["thread_id"]] = []
    _MEMORY_STORE.trace_actions[thread["thread_id"]] = []
    _MEMORY_STORE.topics[topic_id]["updated_at"] = now
    return deepcopy(thread)


def list_topic_threads(topic_id: str) -> list[dict[str, Any]]:
    return sorted(
        (deepcopy(item) for item in _MEMORY_STORE.threads.values() if item["topic_id"] == topic_id),
        key=lambda item: item["updated_at"],
        reverse=True,
    )
```

- [ ] **Step 5: Implement events, trace actions, and insights**

Add:

```python
def get_thread(thread_id: str) -> dict[str, Any]:
    thread = _MEMORY_STORE.threads.get(thread_id)
    if thread is None:
        raise KeyError("Paper reading thread not found.")
    result = deepcopy(thread)
    result["events"] = deepcopy(_MEMORY_STORE.thread_events.get(thread_id, []))
    result["citation_trace_actions"] = deepcopy(_MEMORY_STORE.trace_actions.get(thread_id, []))
    return result


def record_thread_event(
    *,
    thread_id: str,
    event_type: str,
    source: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if thread_id not in _MEMORY_STORE.threads:
        raise KeyError("Paper reading thread not found.")
    now = utc_now()
    event = {
        "event_id": _new_id("event"),
        "thread_id": thread_id,
        "event_type": str(event_type or "").strip(),
        "source": str(source or "").strip(),
        "payload": deepcopy(payload),
        "created_at": now,
    }
    if not event["event_type"]:
        raise ValueError("Thread event type is required.")
    _MEMORY_STORE.thread_events.setdefault(thread_id, []).append(event)
    _MEMORY_STORE.threads[thread_id]["updated_at"] = now
    return deepcopy(event)


def record_citation_trace_action(
    *,
    thread_id: str,
    citation_trace_session_id: str,
    target_paper: dict[str, Any],
    final_top5: list[dict[str, Any]],
    warnings: list[str] | None = None,
    assistant_explanation: str = "",
) -> dict[str, Any]:
    if thread_id not in _MEMORY_STORE.threads:
        raise KeyError("Paper reading thread not found.")
    action = {
        "action_id": _new_id("trace_action"),
        "thread_id": thread_id,
        "citation_trace_session_id": str(citation_trace_session_id or "").strip(),
        "target_paper": deepcopy(target_paper),
        "final_top5": deepcopy(final_top5),
        "warnings": [str(item) for item in (warnings or [])],
        "assistant_explanation": str(assistant_explanation or "").strip(),
        "created_at": utc_now(),
    }
    if not action["citation_trace_session_id"]:
        raise ValueError("Citation trace session id is required.")
    _MEMORY_STORE.trace_actions.setdefault(thread_id, []).append(action)
    record_thread_event(
        thread_id=thread_id,
        event_type="citation_trace.completed",
        source="citation_trace",
        payload={"action_id": action["action_id"], "citation_trace_session_id": action["citation_trace_session_id"]},
    )
    return deepcopy(action)


def create_topic_insight(
    *,
    topic_id: str,
    kind: InsightKind,
    text: str,
    source_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if topic_id not in _MEMORY_STORE.topics:
        raise KeyError("Research topic not found.")
    insight = {
        "insight_id": _new_id("insight"),
        "topic_id": topic_id,
        "kind": kind,
        "status": "draft",
        "text": str(text or "").strip(),
        "source_refs": deepcopy(source_refs or []),
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    if not insight["text"]:
        raise ValueError("Topic insight text is required.")
    _MEMORY_STORE.insights[insight["insight_id"]] = insight
    return deepcopy(insight)


def confirm_topic_insight(insight_id: str) -> dict[str, Any]:
    insight = _MEMORY_STORE.insights.get(insight_id)
    if insight is None:
        raise KeyError("Topic insight not found.")
    insight["status"] = "confirmed"
    insight["updated_at"] = utc_now()
    return deepcopy(insight)
```

- [ ] **Step 6: Run service tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_research_topics_service
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/research_topics_service.py tests/test_research_topics_service.py
git commit -m "Add research topics service core"
```

## Task 4: PostgreSQL Durable Topic Store

**Files:**
- Modify: `tests/test_research_topics_service.py`
- Modify: `backend/research_topics_service.py`

- [ ] **Step 1: Add failing durable-store tests**

Append to `tests/test_research_topics_service.py`:

```python
class ResearchTopicsDurableStoreTest(unittest.TestCase):
    def test_schema_sql_contains_research_topic_tables(self) -> None:
        sql = rts.research_topics_schema_sql()

        self.assertIn("CREATE TABLE IF NOT EXISTS research_topics", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS paper_reading_threads", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS paper_reading_thread_events", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS citation_trace_actions", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS topic_insights", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS assistant_suggestions", sql)
        self.assertIn("UNIQUE (topic_id, paper_key)", sql)

    def test_service_can_force_memory_store_for_tests_and_degraded_mode(self) -> None:
        rts._MEMORY_STORE.reset()
        original = rts.USE_MEMORY_STORE
        try:
            rts.USE_MEMORY_STORE = True
            topic = rts.create_topic(title="Fallback Topic", description="", keywords=[])
            self.assertEqual(topic["title"], "Fallback Topic")
            self.assertEqual(rts.list_topics()[0]["topic_id"], topic["topic_id"])
        finally:
            rts.USE_MEMORY_STORE = original
```

- [ ] **Step 2: Run durable-store tests and verify failure**

Run:

```bash
.venv/bin/python -m unittest tests.test_research_topics_service.ResearchTopicsDurableStoreTest
```

Expected: FAIL because schema SQL and `USE_MEMORY_STORE` do not exist.

- [ ] **Step 3: Add schema SQL and store selector**

In `backend/research_topics_service.py`, add imports:

```python
import json

import psycopg2
from psycopg2.extras import RealDictCursor

from local_paper_db.app.search_service import DEFAULT_DB_CONFIG
```

Add:

```python
USE_MEMORY_STORE = False


def research_topics_schema_sql() -> str:
    return """
    CREATE TABLE IF NOT EXISTS research_topics (
        topic_id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        keywords JSONB NOT NULL DEFAULT '[]'::jsonb,
        status TEXT NOT NULL DEFAULT 'active',
        created_from TEXT NOT NULL DEFAULT 'manual',
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL
    );
    CREATE TABLE IF NOT EXISTS paper_reading_threads (
        thread_id TEXT PRIMARY KEY,
        topic_id TEXT NOT NULL REFERENCES research_topics(topic_id) ON DELETE CASCADE,
        paper_key TEXT NOT NULL,
        paper_title TEXT NOT NULL,
        paper_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        status TEXT NOT NULL DEFAULT 'reading',
        last_page INTEGER NOT NULL DEFAULT 0,
        progress DOUBLE PRECISION NOT NULL DEFAULT 0,
        last_reader_session_id TEXT,
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL,
        UNIQUE (topic_id, paper_key)
    );
    CREATE TABLE IF NOT EXISTS paper_reading_thread_events (
        event_id TEXT PRIMARY KEY,
        thread_id TEXT NOT NULL REFERENCES paper_reading_threads(thread_id) ON DELETE CASCADE,
        event_type TEXT NOT NULL,
        source TEXT NOT NULL,
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL
    );
    CREATE TABLE IF NOT EXISTS citation_trace_actions (
        action_id TEXT PRIMARY KEY,
        thread_id TEXT NOT NULL REFERENCES paper_reading_threads(thread_id) ON DELETE CASCADE,
        citation_trace_session_id TEXT NOT NULL,
        target_paper JSONB NOT NULL DEFAULT '{}'::jsonb,
        final_top5 JSONB NOT NULL DEFAULT '[]'::jsonb,
        warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
        assistant_explanation TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMPTZ NOT NULL
    );
    CREATE TABLE IF NOT EXISTS topic_insights (
        insight_id TEXT PRIMARY KEY,
        topic_id TEXT NOT NULL REFERENCES research_topics(topic_id) ON DELETE CASCADE,
        kind TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'draft',
        text TEXT NOT NULL,
        source_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL
    );
    CREATE TABLE IF NOT EXISTS assistant_suggestions (
        suggestion_id TEXT PRIMARY KEY,
        source_workflow TEXT NOT NULL,
        source_stage TEXT NOT NULL,
        risk_level TEXT NOT NULL,
        target_topic_candidates JSONB NOT NULL DEFAULT '[]'::jsonb,
        target_thread_id TEXT,
        summary TEXT NOT NULL,
        recommended_action TEXT NOT NULL,
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TIMESTAMPTZ NOT NULL
    );
    """.strip()


def _connect(db_config: dict[str, str] | None = None):
    return psycopg2.connect(**(db_config or DEFAULT_DB_CONFIG))


def ensure_research_topics_schema(db_config: dict[str, str] | None = None) -> None:
    with _connect(db_config) as conn:
        with conn.cursor() as cur:
            cur.execute(research_topics_schema_sql())
```

- [ ] **Step 4: Wrap public functions with fallback**

Refactor public functions so they use PostgreSQL unless `USE_MEMORY_STORE` is true or database setup raises. Keep the memory functions by moving their current bodies into private helpers named `_memory_create_topic`, `_memory_list_topics`, `_memory_get_topic`, `_memory_create_or_resume_thread`, `_memory_list_topic_threads`, `_memory_get_thread`, `_memory_record_thread_event`, `_memory_record_citation_trace_action`, `_memory_create_topic_insight`, `_memory_confirm_topic_insight`, `_memory_store_suggestion`, `_memory_list_suggestions`, `_memory_accept_suggestion`, and `_memory_dismiss_suggestion`.

Add this helper:

```python
def _use_memory_fallback(exc: Exception) -> bool:
    return isinstance(exc, (psycopg2.Error, OSError, RuntimeError))
```

Implement `create_topic()` with the same signature:

```python
def create_topic(
    *,
    title: str,
    description: str = "",
    keywords: list[str] | None = None,
    created_from: str = "manual",
) -> dict[str, Any]:
    if USE_MEMORY_STORE:
        return _memory_create_topic(title=title, description=description, keywords=keywords, created_from=created_from)
    now = utc_now()
    topic = {
        "topic_id": _new_id("topic"),
        "title": str(title or "").strip(),
        "description": str(description or "").strip(),
        "keywords": [str(item).strip() for item in (keywords or []) if str(item).strip()],
        "status": "active",
        "created_from": created_from,
        "created_at": now,
        "updated_at": now,
    }
    if not topic["title"]:
        raise ValueError("Topic title is required.")
    try:
        ensure_research_topics_schema()
        with _connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO research_topics
                        (topic_id, title, description, keywords, status, created_from, created_at, updated_at)
                    VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s)
                    RETURNING topic_id, title, description, keywords, status, created_from, created_at, updated_at
                    """,
                    (
                        topic["topic_id"],
                        topic["title"],
                        topic["description"],
                        json.dumps(topic["keywords"]),
                        topic["status"],
                        topic["created_from"],
                        topic["created_at"],
                        topic["updated_at"],
                    ),
                )
                return dict(cur.fetchone())
    except Exception as exc:
        if _use_memory_fallback(exc):
            return _memory_create_topic(title=title, description=description, keywords=keywords, created_from=created_from)
        raise
```

Implement `list_topics()` with a PostgreSQL branch and fallback:

```python
def list_topics() -> list[dict[str, Any]]:
    if USE_MEMORY_STORE:
        return _memory_list_topics()
    try:
        ensure_research_topics_schema()
        with _connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT topic_id, title, description, keywords, status, created_from, created_at, updated_at
                    FROM research_topics
                    ORDER BY updated_at DESC
                    """
                )
                return [dict(row) for row in cur.fetchall()]
    except Exception as exc:
        if _use_memory_fallback(exc):
            return _memory_list_topics()
        raise
```

Implement `create_or_resume_thread()` with `ON CONFLICT` so `(topic_id, paper_key)` remains unique:

```python
def create_or_resume_thread(
    *,
    topic_id: str,
    paper: dict[str, Any],
    reader_session_id: str | None = None,
) -> dict[str, Any]:
    if USE_MEMORY_STORE:
        return _memory_create_or_resume_thread(topic_id=topic_id, paper=paper, reader_session_id=reader_session_id)
    paper_key = canonical_paper_key(paper)
    now = utc_now()
    try:
        ensure_research_topics_schema()
        with _connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT topic_id FROM research_topics WHERE topic_id = %s", (topic_id,))
                if cur.fetchone() is None:
                    raise KeyError("Research topic not found.")
                cur.execute(
                    """
                    INSERT INTO paper_reading_threads
                        (thread_id, topic_id, paper_key, paper_title, paper_metadata, status, last_page, progress, last_reader_session_id, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s::jsonb, 'reading', 0, 0, %s, %s, %s)
                    ON CONFLICT (topic_id, paper_key)
                    DO UPDATE SET
                        status = 'reading',
                        last_reader_session_id = EXCLUDED.last_reader_session_id,
                        updated_at = EXCLUDED.updated_at
                    RETURNING thread_id, topic_id, paper_key, paper_title, paper_metadata, status, last_page, progress, last_reader_session_id, created_at, updated_at
                    """,
                    (
                        _new_id("thread"),
                        topic_id,
                        paper_key,
                        str(paper.get("title") or "").strip() or "Untitled paper",
                        json.dumps(paper, ensure_ascii=False),
                        reader_session_id,
                        now,
                        now,
                    ),
                )
                thread = dict(cur.fetchone())
                cur.execute("UPDATE research_topics SET updated_at = %s WHERE topic_id = %s", (now, topic_id))
                return thread
    except KeyError:
        raise
    except Exception as exc:
        if _use_memory_fallback(exc):
            return _memory_create_or_resume_thread(topic_id=topic_id, paper=paper, reader_session_id=reader_session_id)
        raise
```

Implement `record_thread_event()` with this SQL branch:

```python
cur.execute(
    """
    INSERT INTO paper_reading_thread_events
        (event_id, thread_id, event_type, source, payload, created_at)
    VALUES (%s, %s, %s, %s, %s::jsonb, %s)
    RETURNING event_id, thread_id, event_type, source, payload, created_at
    """,
    (event_id, thread_id, event_type, source, json.dumps(payload, ensure_ascii=False), now),
)
```

Implement `record_citation_trace_action()` with this SQL branch:

```python
cur.execute(
    """
    INSERT INTO citation_trace_actions
        (action_id, thread_id, citation_trace_session_id, target_paper, final_top5, warnings, assistant_explanation, created_at)
    VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s)
    RETURNING action_id, thread_id, citation_trace_session_id, target_paper, final_top5, warnings, assistant_explanation, created_at
    """,
    (
        action_id,
        thread_id,
        citation_trace_session_id,
        json.dumps(target_paper, ensure_ascii=False),
        json.dumps(final_top5, ensure_ascii=False),
        json.dumps(warnings or [], ensure_ascii=False),
        assistant_explanation,
        now,
    ),
)
```

Implement `create_topic_insight()`, `confirm_topic_insight()`, `list_suggestions()`, `accept_suggestion()`, and `dismiss_suggestion()` with equivalent explicit `INSERT`, `UPDATE`, and `SELECT` statements against the tables from `research_topics_schema_sql()`. Each public function must keep the exact response keys from Task 3 so API and frontend tests do not change.

- [ ] **Step 5: Run durable-store tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_research_topics_service
```

Expected: PASS.

- [ ] **Step 6: Commit durable store**

```bash
git add backend/research_topics_service.py tests/test_research_topics_service.py
git commit -m "Add durable research topics schema"
```

## Task 5: Research Topics API Models And Routes

**Files:**
- Create: `tests/test_research_topics_api.py`
- Modify: `backend/schemas.py`
- Modify: `backend/main.py`

- [ ] **Step 1: Write failing API tests**

Create `tests/test_research_topics_api.py`:

```python
import unittest

from fastapi.testclient import TestClient

from backend.main import app
from backend import research_topics_service as rts


class ResearchTopicsApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        rts._MEMORY_STORE.reset()

    def tearDown(self) -> None:
        rts._MEMORY_STORE.reset()

    def test_create_topic_and_attach_paper_thread(self) -> None:
        topic_response = self.client.post(
            "/api/research-topics",
            json={"title": "Graph RAG Memory", "description": "Long-term graph memory", "keywords": ["graph rag"]},
        )
        self.assertEqual(topic_response.status_code, 200)
        topic = topic_response.json()

        thread_response = self.client.post(
            f"/api/research-topics/{topic['topic_id']}/papers",
            json={
                "paper": {"title": "Attention Is All You Need", "arxiv_id": "1706.03762", "source": "arxiv"},
                "reader_session_id": "reader-1",
            },
        )
        self.assertEqual(thread_response.status_code, 200)
        first_thread = thread_response.json()

        second_response = self.client.post(
            f"/api/research-topics/{topic['topic_id']}/papers",
            json={
                "paper": {"title": "Attention Is All You Need", "arxiv_id": "1706.03762v2", "source": "arxiv"},
                "reader_session_id": "reader-2",
            },
        )
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(first_thread["thread_id"], second_response.json()["thread_id"])

    def test_thread_event_and_trace_action_routes(self) -> None:
        topic = rts.create_topic(title="Citation Evidence", description="", keywords=[])
        thread = rts.create_or_resume_thread(
            topic_id=topic["topic_id"],
            paper={"title": "Citation Paper", "source_id": "paper-1"},
            reader_session_id="reader-1",
        )

        event_response = self.client.post(
            f"/api/research-topics/threads/{thread['thread_id']}/events",
            json={"event_type": "paper_reader.progress", "source": "paper_reader", "payload": {"last_page": 4}},
        )
        self.assertEqual(event_response.status_code, 200)

        action_response = self.client.post(
            f"/api/research-topics/threads/{thread['thread_id']}/citation-trace-actions",
            json={
                "citation_trace_session_id": "trace-1",
                "target_paper": {"title": "Citation Paper"},
                "final_top5": [{"title": "Prior Work"}],
                "warnings": ["weak evidence"],
                "assistant_explanation": "Save as caveat.",
            },
        )
        self.assertEqual(action_response.status_code, 200)

        detail_response = self.client.get(f"/api/research-topics/{topic['topic_id']}/threads/{thread['thread_id']}")
        self.assertEqual(detail_response.status_code, 200)
        detail = detail_response.json()
        self.assertEqual(detail["events"][0]["payload"]["last_page"], 4)
        self.assertEqual(detail["citation_trace_actions"][0]["citation_trace_session_id"], "trace-1")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run API tests and verify failure**

Run:

```bash
.venv/bin/python -m unittest tests.test_research_topics_api
```

Expected: FAIL because `/api/research-topics` routes do not exist.

- [ ] **Step 3: Add Pydantic models**

In `backend/schemas.py`, add after assistant memory models:

```python
class ResearchTopicCreateRequest(BaseModel):
    title: str
    description: str = ""
    keywords: list[str] = Field(default_factory=list)


class PaperThreadAttachRequest(BaseModel):
    paper: dict[str, Any]
    reader_session_id: str | None = None


class ThreadEventCreateRequest(BaseModel):
    event_type: str
    source: str
    payload: dict[str, Any] = Field(default_factory=dict)


class CitationTraceActionCreateRequest(BaseModel):
    citation_trace_session_id: str
    target_paper: dict[str, Any] = Field(default_factory=dict)
    final_top5: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    assistant_explanation: str = ""


class TopicInsightCreateRequest(BaseModel):
    kind: Literal["conclusion", "evidence", "caveat", "contradiction", "open_question"]
    text: str
    source_refs: list[dict[str, Any]] = Field(default_factory=list)
```

- [ ] **Step 4: Import models and service**

In `backend/main.py`, import the new request models from `backend.schemas` and add:

```python
from backend import research_topics_service
```

- [ ] **Step 5: Add thin route handlers**

In `backend/main.py`, add before the Live2D routes:

```python
@app.get("/api/research-topics")
def api_research_topics_list() -> dict[str, Any]:
    return {"items": research_topics_service.list_topics()}


@app.post("/api/research-topics")
def api_research_topics_create(payload: ResearchTopicCreateRequest) -> dict[str, Any]:
    try:
        return research_topics_service.create_topic(
            title=payload.title,
            description=payload.description,
            keywords=payload.keywords,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/research-topics/{topic_id}")
def api_research_topic_detail(topic_id: str) -> dict[str, Any]:
    try:
        return research_topics_service.get_topic(topic_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/research-topics/{topic_id}/papers")
def api_research_topic_attach_paper(topic_id: str, payload: PaperThreadAttachRequest) -> dict[str, Any]:
    try:
        return research_topics_service.create_or_resume_thread(
            topic_id=topic_id,
            paper=payload.paper,
            reader_session_id=payload.reader_session_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/research-topics/{topic_id}/threads/{thread_id}")
def api_research_topic_thread_detail(topic_id: str, thread_id: str) -> dict[str, Any]:
    try:
        thread = research_topics_service.get_thread(thread_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if thread.get("topic_id") != topic_id:
        raise HTTPException(status_code=404, detail="Paper reading thread not found in this topic.")
    return thread


@app.post("/api/research-topics/threads/{thread_id}/events")
def api_research_topic_thread_event(thread_id: str, payload: ThreadEventCreateRequest) -> dict[str, Any]:
    try:
        return research_topics_service.record_thread_event(
            thread_id=thread_id,
            event_type=payload.event_type,
            source=payload.source,
            payload=payload.payload,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/research-topics/threads/{thread_id}/citation-trace-actions")
def api_research_topic_trace_action(thread_id: str, payload: CitationTraceActionCreateRequest) -> dict[str, Any]:
    try:
        return research_topics_service.record_citation_trace_action(
            thread_id=thread_id,
            citation_trace_session_id=payload.citation_trace_session_id,
            target_paper=payload.target_paper,
            final_top5=payload.final_top5,
            warnings=payload.warnings,
            assistant_explanation=payload.assistant_explanation,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
```

- [ ] **Step 6: Run API tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_research_topics_api tests.test_research_topics_service
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/schemas.py backend/main.py tests/test_research_topics_api.py
git commit -m "Expose research topic APIs"
```

## Task 6: Rule-First Assistant Suggestions

**Files:**
- Modify: `tests/test_research_topics_service.py`
- Modify: `backend/research_topics_service.py`
- Modify: `backend/schemas.py`
- Modify: `backend/main.py`

- [ ] **Step 1: Add failing suggestion tests**

Append to `tests/test_research_topics_service.py`:

```python
class ResearchTopicSuggestionTest(unittest.TestCase):
    def setUp(self) -> None:
        rts._MEMORY_STORE.reset()

    def test_search_suggestion_is_recommendation_only(self) -> None:
        topic = rts.create_topic(title="Graph RAG", description="", keywords=["graph rag"])
        suggestion = rts.create_search_recommendation(
            query="graph rag memory",
            paper={"title": "Graph RAG Memory", "arxiv_id": "2401.00001"},
            topic_candidates=[topic],
        )

        self.assertEqual(suggestion["source_workflow"], "search")
        self.assertEqual(suggestion["recommended_action"], "open_in_topic")
        self.assertEqual(suggestion["status"], "pending")
        self.assertEqual(rts.list_topic_threads(topic["topic_id"]), [])

    def test_accept_search_suggestion_does_not_write_topic_records(self) -> None:
        topic = rts.create_topic(title="Graph RAG", description="", keywords=["graph rag"])
        suggestion = rts.create_search_recommendation(
            query="graph rag memory",
            paper={"title": "Graph RAG Memory", "arxiv_id": "2401.00001"},
            topic_candidates=[topic],
        )
        accepted = rts.accept_suggestion(suggestion["suggestion_id"])

        self.assertEqual(accepted["status"], "accepted")
        self.assertEqual(rts.list_topic_threads(topic["topic_id"]), [])

    def test_paper_reader_suggestion_can_save_open_question_after_thread_exists(self) -> None:
        topic = rts.create_topic(title="Graph RAG", description="", keywords=[])
        thread = rts.create_or_resume_thread(
            topic_id=topic["topic_id"],
            paper={"title": "Graph RAG Memory", "arxiv_id": "2401.00001"},
            reader_session_id="reader-1",
        )
        suggestion = rts.create_thread_open_question_suggestion(
            thread_id=thread["thread_id"],
            question="Does graph structure reduce retrieval drift?",
        )
        accepted = rts.accept_suggestion(suggestion["suggestion_id"])

        self.assertEqual(accepted["status"], "accepted")
        detail = rts.get_thread(thread["thread_id"])
        self.assertEqual(detail["events"][-1]["event_type"], "paper_reader.open_question")
        self.assertEqual(detail["events"][-1]["payload"]["question"], "Does graph structure reduce retrieval drift?")
```

- [ ] **Step 2: Run suggestion tests and verify failure**

Run:

```bash
.venv/bin/python -m unittest tests.test_research_topics_service.ResearchTopicSuggestionTest
```

Expected: FAIL because suggestion functions do not exist.

- [ ] **Step 3: Implement suggestion functions**

Add to `backend/research_topics_service.py`:

```python
def _store_suggestion(suggestion: dict[str, Any]) -> dict[str, Any]:
    _MEMORY_STORE.suggestions[suggestion["suggestion_id"]] = suggestion
    return deepcopy(suggestion)


def create_search_recommendation(
    *,
    query: str,
    paper: dict[str, Any],
    topic_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return _store_suggestion(
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
        }
    )


def create_thread_open_question_suggestion(*, thread_id: str, question: str) -> dict[str, Any]:
    if thread_id not in _MEMORY_STORE.threads:
        raise KeyError("Paper reading thread not found.")
    return _store_suggestion(
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
        }
    )


def list_suggestions(status: str | None = "pending") -> list[dict[str, Any]]:
    items = list(_MEMORY_STORE.suggestions.values())
    if status:
        items = [item for item in items if item.get("status") == status]
    return sorted((deepcopy(item) for item in items), key=lambda item: item["created_at"], reverse=True)


def accept_suggestion(suggestion_id: str) -> dict[str, Any]:
    suggestion = _MEMORY_STORE.suggestions.get(suggestion_id)
    if suggestion is None:
        raise KeyError("Assistant suggestion not found.")
    if suggestion["status"] != "pending":
        return deepcopy(suggestion)
    if suggestion["recommended_action"] == "save_open_question":
        question = str(suggestion.get("payload", {}).get("question") or "").strip()
        record_thread_event(
            thread_id=suggestion["target_thread_id"],
            event_type="paper_reader.open_question",
            source="assistant",
            payload={"question": question},
        )
    suggestion["status"] = "accepted"
    return deepcopy(suggestion)


def dismiss_suggestion(suggestion_id: str) -> dict[str, Any]:
    suggestion = _MEMORY_STORE.suggestions.get(suggestion_id)
    if suggestion is None:
        raise KeyError("Assistant suggestion not found.")
    suggestion["status"] = "dismissed"
    return deepcopy(suggestion)
```

- [ ] **Step 4: Add suggestion API request models**

In `backend/schemas.py`, add:

```python
class SearchSuggestionCreateRequest(BaseModel):
    query: str = ""
    paper: dict[str, Any]
    topic_candidates: list[dict[str, Any]] = Field(default_factory=list)
```

- [ ] **Step 5: Add suggestion routes**

In `backend/main.py`, add:

```python
@app.get("/api/assistant/suggestions")
def api_assistant_suggestions(status: str | None = "pending") -> dict[str, Any]:
    return {"items": research_topics_service.list_suggestions(status=status)}


@app.post("/api/assistant/suggestions/search")
def api_assistant_search_suggestion(payload: SearchSuggestionCreateRequest) -> dict[str, Any]:
    return research_topics_service.create_search_recommendation(
        query=payload.query,
        paper=payload.paper,
        topic_candidates=payload.topic_candidates,
    )


@app.post("/api/assistant/suggestions/{suggestion_id}/accept")
def api_assistant_suggestion_accept(suggestion_id: str) -> dict[str, Any]:
    try:
        return research_topics_service.accept_suggestion(suggestion_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/assistant/suggestions/{suggestion_id}/dismiss")
def api_assistant_suggestion_dismiss(suggestion_id: str) -> dict[str, Any]:
    try:
        return research_topics_service.dismiss_suggestion(suggestion_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
```

- [ ] **Step 6: Add API test for search suggestion no-write behavior**

Append to `tests/test_research_topics_api.py`:

```python
    def test_search_suggestion_route_does_not_write_topic_records(self) -> None:
        topic = rts.create_topic(title="Graph RAG", description="", keywords=["graph rag"])
        response = self.client.post(
            "/api/assistant/suggestions/search",
            json={
                "query": "graph rag memory",
                "paper": {"title": "Graph RAG Memory", "arxiv_id": "2401.00001"},
                "topic_candidates": [topic],
            },
        )
        self.assertEqual(response.status_code, 200)
        suggestion = response.json()

        accept_response = self.client.post(f"/api/assistant/suggestions/{suggestion['suggestion_id']}/accept")
        self.assertEqual(accept_response.status_code, 200)
        self.assertEqual(rts.list_topic_threads(topic["topic_id"]), [])
```

- [ ] **Step 7: Run suggestion tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_research_topics_service tests.test_research_topics_api
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/research_topics_service.py backend/schemas.py backend/main.py tests/test_research_topics_service.py tests/test_research_topics_api.py
git commit -m "Add research assistant suggestions"
```

## Task 7: Paper Reader Topic Attachment And Thread Events

**Files:**
- Create: `tests/test_research_topics_frontend.py`
- Modify: `frontend/src/PaperReaderPage.jsx`
- Modify: `frontend/src/App.jsx`

- [ ] **Step 1: Write failing frontend source test**

Create `tests/test_research_topics_frontend.py`:

```python
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "frontend/src/App.jsx"
PAPER_READER = ROOT / "frontend/src/PaperReaderPage.jsx"
TOPICS_PAGE = ROOT / "frontend/src/ResearchTopicsPage.jsx"
ASSISTANT = ROOT / "frontend/src/Live2DAssistant.jsx"
CITATION_TRACE = ROOT / "frontend/src/CitationTracePage.jsx"


class ResearchTopicsFrontendTest(unittest.TestCase):
    def test_app_exposes_research_topics_tab_and_assistant_chat_settings(self) -> None:
        text = APP.read_text(encoding="utf-8")

        self.assertIn("ResearchTopicsPage", text)
        self.assertIn("researchTopicsTab", text)
        self.assertIn('activeTab === "research_topics"', text)
        self.assertIn("assistant_chat", text)
        self.assertIn("assistantChatModel", text)

    def test_paper_reader_can_attach_to_topic_and_publish_thread_events(self) -> None:
        text = PAPER_READER.read_text(encoding="utf-8")

        self.assertIn("/api/research-topics", text)
        self.assertIn("attachPaperToResearchTopic", text)
        self.assertIn("currentResearchThread", text)
        self.assertIn("recordResearchThreadEvent", text)
        self.assertIn("paper_reader.progress", text)
        self.assertIn("paper_reader.question", text)
```

- [ ] **Step 2: Run frontend test and verify failure**

Run:

```bash
.venv/bin/python -m unittest tests.test_research_topics_frontend.ResearchTopicsFrontendTest.test_paper_reader_can_attach_to_topic_and_publish_thread_events
```

Expected: FAIL because Paper Reader has no research topic attachment code.

- [ ] **Step 3: Add Paper Reader state and attach helper**

In `frontend/src/PaperReaderPage.jsx`, add state near other session state:

```jsx
  const [currentResearchTopic, setCurrentResearchTopic] = useState(null);
  const [currentResearchThread, setCurrentResearchThread] = useState(null);
  const [researchTopicError, setResearchTopicError] = useState("");
```

Add helper functions inside the component:

```jsx
  async function attachPaperToResearchTopic(topic) {
    if (!topic?.topic_id || !session) {
      return null;
    }
    const paper = {
      title: session.paper_title,
      source: session.source_type,
      source_id: session.source_id,
      source_url: session.source_url,
      arxiv_id: session.source_type === "arxiv" ? session.source_id : null,
      authors: session.authors || [],
      published_date: session.published_date || null
    };
    const response = await fetch(`/api/research-topics/${encodeURIComponent(topic.topic_id)}/papers`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        paper,
        reader_session_id: session.session_id
      })
    });
    const payload = await readJsonWithDetailFallback(response);
    if (!response.ok) {
      throw new Error(payload.detail || `Research topic attach failed (HTTP ${response.status})`);
    }
    setCurrentResearchTopic(topic);
    setCurrentResearchThread(payload);
    setResearchTopicError("");
    return payload;
  }

  async function recordResearchThreadEvent(eventType, payload, source = "paper_reader") {
    if (!currentResearchThread?.thread_id) {
      return null;
    }
    const response = await fetch(`/api/research-topics/threads/${encodeURIComponent(currentResearchThread.thread_id)}/events`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        event_type: eventType,
        source,
        payload
      })
    });
    const eventPayload = await readJsonWithDetailFallback(response);
    if (!response.ok) {
      throw new Error(eventPayload.detail || `Research thread event failed (HTTP ${response.status})`);
    }
    return eventPayload;
  }
```

- [ ] **Step 4: Record reading progress and questions**

Add an effect after active page state is available:

```jsx
  useEffect(() => {
    if (!currentResearchThread?.thread_id || !session?.session_id) {
      return;
    }
    void recordResearchThreadEvent("paper_reader.progress", {
      session_id: session.session_id,
      last_page: activeSourcePageNumber || activePageIndex + 1,
      page_index: activePageIndex,
      paper_title: session.paper_title || ""
    }).catch((error) => setResearchTopicError(String(error)));
  }, [currentResearchThread?.thread_id, session?.session_id, activePageIndex, activeSourcePageNumber]);
```

In the Paper Reader chat submit handler, after a successful assistant reply is available, call:

```jsx
      void recordResearchThreadEvent("paper_reader.question", {
        session_id: session.session_id,
        question,
        answer: payload.answer || payload.message || ""
      }, "user").catch((error) => setResearchTopicError(String(error)));
```

Use the local variable names that exist in the current chat handler.

- [ ] **Step 5: Add minimal topic attachment UI**

Render a compact status near the Paper Reader header:

```jsx
          <div className="paper-reader-topic-strip">
            <span>{currentResearchTopic ? currentResearchTopic.title : copy.researchTopicDetached}</span>
            {currentResearchThread ? <span>{copy.researchThreadActive}</span> : null}
            {researchTopicError ? <span className="warning-box">{researchTopicError}</span> : null}
          </div>
```

Add copy keys for Chinese and English:

```jsx
researchTopicDetached: "未关联课题",
researchThreadActive: "精读线程记录中",
```

```jsx
researchTopicDetached: "No topic linked",
researchThreadActive: "Reading thread active",
```

The first UI pass only displays state and exposes the helper. Task 9 connects topic selection from the full topic page and assistant suggestions.

- [ ] **Step 6: Run frontend source test**

Run:

```bash
.venv/bin/python -m unittest tests.test_research_topics_frontend
```

Expected: the Paper Reader assertion passes; other assertions can still fail until their tasks are done.

- [ ] **Step 7: Commit Paper Reader integration**

```bash
git add frontend/src/PaperReaderPage.jsx tests/test_research_topics_frontend.py
git commit -m "Connect Paper Reader to research threads"
```

## Task 8: Citation Trace Action Storage

**Files:**
- Modify: `tests/test_research_topics_frontend.py`
- Modify: `frontend/src/CitationTracePage.jsx`

- [ ] **Step 1: Add failing Citation Trace frontend assertion**

Append to `tests/test_research_topics_frontend.py`:

```python
    def test_citation_trace_can_store_action_in_research_thread(self) -> None:
        text = CITATION_TRACE.read_text(encoding="utf-8")

        self.assertIn("researchThread", text)
        self.assertIn("storeCitationTraceAction", text)
        self.assertIn("/citation-trace-actions", text)
        self.assertIn("citation_trace.completed", text)
```

- [ ] **Step 2: Run the new assertion and verify failure**

Run:

```bash
.venv/bin/python -m unittest tests.test_research_topics_frontend.ResearchTopicsFrontendTest.test_citation_trace_can_store_action_in_research_thread
```

Expected: FAIL because Citation Trace does not know about research threads.

- [ ] **Step 3: Add optional prop and storage helper**

In `frontend/src/CitationTracePage.jsx`, change the component signature:

```jsx
export default function CitationTracePage({ language, t, runtimePayload, onAssistantAutoReply, renderAssistantLayer, researchThread = null }) {
```

Add helper inside the component:

```jsx
  async function storeCitationTraceAction(nextSession) {
    if (!researchThread?.thread_id || !nextSession?.session_id) {
      return null;
    }
    const response = await fetch(`/api/research-topics/threads/${encodeURIComponent(researchThread.thread_id)}/citation-trace-actions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        citation_trace_session_id: nextSession.session_id,
        target_paper: nextSession.target_paper || {},
        final_top5: nextSession.final_top5 || [],
        warnings: nextSession.warnings || [],
        assistant_explanation: buildAssistantAnswerContext(nextSession)
      })
    });
    const payload = await readJsonWithDetailFallback(response);
    if (!response.ok) {
      throw new Error(payload.detail || `Citation Trace action save failed (HTTP ${response.status})`);
    }
    return payload;
  }
```

- [ ] **Step 4: Call storage on completion**

Where Citation Trace execution receives the completed session, add:

```jsx
      if (researchThread?.thread_id) {
        await storeCitationTraceAction(nextSession);
      }
```

Use the existing completed session variable name in that block.

Ensure the string `citation_trace.completed` appears in a local event payload or comment-free constant:

```jsx
const CITATION_TRACE_COMPLETED_EVENT = "citation_trace.completed";
```

- [ ] **Step 5: Run Citation Trace frontend test**

Run:

```bash
.venv/bin/python -m unittest tests.test_research_topics_frontend.ResearchTopicsFrontendTest.test_citation_trace_can_store_action_in_research_thread
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/CitationTracePage.jsx tests/test_research_topics_frontend.py
git commit -m "Store citation trace actions in reading threads"
```

## Task 9: Research Topics Page And Settings UI

**Files:**
- Create: `frontend/src/ResearchTopicsPage.jsx`
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/styles.css`
- Modify: `tests/test_research_topics_frontend.py`

- [ ] **Step 1: Run app/settings frontend assertion and verify failure**

Run:

```bash
.venv/bin/python -m unittest tests.test_research_topics_frontend.ResearchTopicsFrontendTest.test_app_exposes_research_topics_tab_and_assistant_chat_settings
```

Expected: FAIL because App does not import `ResearchTopicsPage` or expose `assistant_chat`.

- [ ] **Step 2: Create Research Topics page skeleton**

Create `frontend/src/ResearchTopicsPage.jsx`:

```jsx
import { useEffect, useState } from "react";

const copy = {
  zh: {
    title: "课题档案",
    empty: "还没有课题。小助手会在精读开始时建议创建或关联课题。",
    refresh: "刷新",
    threads: "论文精读线程",
    insights: "阶段结论与疑点",
    suggestions: "建议卡"
  },
  en: {
    title: "Research Topics",
    empty: "No topics yet. The assistant will suggest creating or linking topics when paper reading starts.",
    refresh: "Refresh",
    threads: "Paper reading threads",
    insights: "Insights and caveats",
    suggestions: "Suggestions"
  }
};

function t(language) {
  return copy[language] || copy.zh;
}

export default function ResearchTopicsPage({ language }) {
  const text = t(language);
  const [topics, setTopics] = useState([]);
  const [selectedTopic, setSelectedTopic] = useState(null);
  const [suggestions, setSuggestions] = useState([]);
  const [error, setError] = useState("");

  async function loadTopics() {
    setError("");
    const [topicsResponse, suggestionsResponse] = await Promise.all([
      fetch("/api/research-topics"),
      fetch("/api/assistant/suggestions")
    ]);
    const topicsPayload = await topicsResponse.json();
    const suggestionsPayload = await suggestionsResponse.json();
    if (!topicsResponse.ok) {
      throw new Error(topicsPayload.detail || `Topics failed (HTTP ${topicsResponse.status})`);
    }
    if (!suggestionsResponse.ok) {
      throw new Error(suggestionsPayload.detail || `Suggestions failed (HTTP ${suggestionsResponse.status})`);
    }
    const items = topicsPayload.items || [];
    setTopics(items);
    setSelectedTopic((current) => current || items[0] || null);
    setSuggestions(suggestionsPayload.items || []);
  }

  useEffect(() => {
    void loadTopics().catch((loadError) => setError(String(loadError)));
  }, []);

  const threads = selectedTopic?.threads || [];
  const insights = selectedTopic?.insights || [];

  return (
    <main className="research-topics-page">
      <section className="research-topics-sidebar">
        <div className="section-title-row">
          <h2>{text.title}</h2>
          <button type="button" onClick={() => void loadTopics().catch((loadError) => setError(String(loadError)))}>
            {text.refresh}
          </button>
        </div>
        {topics.length ? (
          topics.map((topic) => (
            <button
              type="button"
              key={topic.topic_id}
              className={selectedTopic?.topic_id === topic.topic_id ? "topic-list-item active" : "topic-list-item"}
              onClick={() => setSelectedTopic(topic)}
            >
              <span>{topic.title}</span>
              <small>{(topic.keywords || []).join(", ")}</small>
            </button>
          ))
        ) : (
          <p className="muted">{text.empty}</p>
        )}
      </section>

      <section className="research-topics-main">
        {error ? <div className="warning-box">{error}</div> : null}
        <h3>{selectedTopic?.title || text.title}</h3>
        <div className="topic-section">
          <h4>{text.threads}</h4>
          {threads.map((thread) => (
            <article className="topic-thread-row" key={thread.thread_id}>
              <strong>{thread.paper_title}</strong>
              <span>{thread.status}</span>
            </article>
          ))}
        </div>
        <div className="topic-section">
          <h4>{text.insights}</h4>
          {insights.map((insight) => (
            <article className="topic-insight-row" key={insight.insight_id}>
              <strong>{insight.kind}</strong>
              <p>{insight.text}</p>
            </article>
          ))}
        </div>
        <div className="topic-section">
          <h4>{text.suggestions}</h4>
          {suggestions.map((suggestion) => (
            <article className="assistant-suggestion-card" key={suggestion.suggestion_id}>
              <strong>{suggestion.recommended_action}</strong>
              <p>{suggestion.summary}</p>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}
```

- [ ] **Step 3: Import and route the page in App**

In `frontend/src/App.jsx`, add:

```jsx
import ResearchTopicsPage from "./ResearchTopicsPage.jsx";
```

Add copy keys in both languages:

```jsx
researchTopicsTab: "Research Topics",
assistantChatModel: "Assistant Chat",
```

```jsx
researchTopicsTab: "课题档案",
assistantChatModel: "小助手模型",
```

Add `assistant_chat` to the empty model catalog state:

```jsx
assistant_chat: buildEmptyModelCatalog(),
```

Add it to settings initialization and save payload in the same style as `answer_chat`:

```jsx
assistant_chat: { ...config.assistant_chat, api_key: "", clear_api_key: false },
```

```jsx
assistant_chat: {
  provider: settings.assistant_chat.provider,
  model: settings.assistant_chat.model,
  base_url: settings.assistant_chat.base_url || null,
  api_key: settings.assistant_chat.api_key || null,
  clear_api_key: settings.assistant_chat.clear_api_key
},
```

Add it to the settings model section list wherever `answer_chat`, `paper_reader_chat`, and citation trace configs are handled.

Add a tab button:

```jsx
<button className={activeTab === "research_topics" ? "active" : ""} onClick={() => setActiveTab("research_topics")}>
  {t("researchTopicsTab")}
</button>
```

Render:

```jsx
{activeTab === "research_topics" ? (
  <ResearchTopicsPage language={language} />
) : null}
```

- [ ] **Step 4: Add styles**

In `frontend/src/styles.css`, add:

```css
.research-topics-page {
  display: grid;
  grid-template-columns: minmax(220px, 280px) minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.research-topics-sidebar,
.research-topics-main,
.topic-section {
  min-width: 0;
}

.topic-list-item {
  width: 100%;
  display: grid;
  gap: 4px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  text-align: left;
}

.topic-list-item.active {
  border-color: var(--accent);
}

.topic-thread-row,
.topic-insight-row,
.assistant-suggestion-card {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  background: var(--surface);
}

@media (max-width: 860px) {
  .research-topics-page {
    grid-template-columns: 1fr;
  }
}
```

Use existing CSS variables; if a variable name differs, replace with the existing nearest equivalent after scanning `frontend/src/styles.css`.

- [ ] **Step 5: Run frontend tests and build**

Run:

```bash
.venv/bin/python -m unittest tests.test_research_topics_frontend tests.test_citation_trace_frontend tests.test_research_profile_frontend
cd frontend && npm run build
```

Expected: PASS and Vite build succeeds.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/App.jsx frontend/src/ResearchTopicsPage.jsx frontend/src/styles.css tests/test_research_topics_frontend.py
git commit -m "Add research topics page and assistant settings UI"
```

## Task 10: Quiet Assistant Suggestion Cards

**Files:**
- Modify: `tests/test_research_topics_frontend.py`
- Modify: `frontend/src/Live2DAssistant.jsx`
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Add failing assistant suggestion assertion**

Append to `tests/test_research_topics_frontend.py`:

```python
    def test_live2d_renders_quiet_suggestion_cards(self) -> None:
        text = ASSISTANT.read_text(encoding="utf-8")

        self.assertIn("assistantSuggestions", text)
        self.assertIn("assistant-suggestion-card", text)
        self.assertIn("/api/assistant/suggestions/", text)
        self.assertNotIn("alert(", text)
```

- [ ] **Step 2: Run assertion and verify failure**

Run:

```bash
.venv/bin/python -m unittest tests.test_research_topics_frontend.ResearchTopicsFrontendTest.test_live2d_renders_quiet_suggestion_cards
```

Expected: FAIL because Live2D does not render suggestion cards.

- [ ] **Step 3: Pass suggestions into Live2D**

In `frontend/src/App.jsx`, add state:

```jsx
const [assistantSuggestions, setAssistantSuggestions] = useState([]);
```

Add loader:

```jsx
async function refreshAssistantSuggestions() {
  const response = await fetch("/api/assistant/suggestions");
  const payload = await response.json();
  if (!response.ok) {
    return;
  }
  setAssistantSuggestions(payload.items || []);
}
```

Call it after search completion, Citation Trace completion, and Paper Reader context updates:

```jsx
void refreshAssistantSuggestions();
```

Pass to `IsolatedAssistantLayer` and `Live2DAssistant`:

```jsx
assistantSuggestions={assistantSuggestions}
onAssistantSuggestionsChange={setAssistantSuggestions}
```

- [ ] **Step 4: Render quiet cards in Live2D**

In `frontend/src/Live2DAssistant.jsx`, add props:

```jsx
  assistantSuggestions = [],
  onAssistantSuggestionsChange
```

Add action helper:

```jsx
  async function updateAssistantSuggestion(suggestionId, action) {
    const response = await fetch(`/api/assistant/suggestions/${encodeURIComponent(suggestionId)}/${action}`, {
      method: "POST"
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || `Suggestion ${action} failed (HTTP ${response.status})`);
    }
    if (typeof onAssistantSuggestionsChange === "function") {
      onAssistantSuggestionsChange((items) =>
        (items || []).map((item) => (item.suggestion_id === suggestionId ? payload : item)).filter((item) => item.status === "pending")
      );
    }
  }
```

Render after the linked context chip:

```jsx
            {assistantSuggestions.length ? (
              <div className="assistant-suggestion-list" aria-live="polite">
                {assistantSuggestions.slice(0, 4).map((suggestion) => (
                  <article className="assistant-suggestion-card" key={suggestion.suggestion_id}>
                    <strong>{suggestion.summary}</strong>
                    <div className="assistant-suggestion-actions">
                      <button type="button" onClick={() => void updateAssistantSuggestion(suggestion.suggestion_id, "accept")}>
                        {t.acceptSuggestion || "Accept"}
                      </button>
                      <button type="button" onClick={() => void updateAssistantSuggestion(suggestion.suggestion_id, "dismiss")}>
                        {t.dismissSuggestion || "Dismiss"}
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            ) : null}
```

Add copy keys:

```jsx
acceptSuggestion: "接受",
dismissSuggestion: "忽略",
```

```jsx
acceptSuggestion: "Accept",
dismissSuggestion: "Dismiss",
```

- [ ] **Step 5: Add quiet card styles**

In `frontend/src/styles.css`, add:

```css
.assistant-suggestion-list {
  display: grid;
  gap: 8px;
  margin: 8px 0;
}

.assistant-suggestion-card {
  display: grid;
  gap: 8px;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px;
  background: var(--surface);
}

.assistant-suggestion-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
```

- [ ] **Step 6: Run frontend tests and build**

Run:

```bash
.venv/bin/python -m unittest tests.test_research_topics_frontend tests.test_paper_reader_live2d_behavior
cd frontend && npm run build
```

Expected: PASS and Vite build succeeds.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/App.jsx frontend/src/Live2DAssistant.jsx frontend/src/styles.css tests/test_research_topics_frontend.py
git commit -m "Show quiet assistant suggestion cards"
```

## Task 11: Documentation, Logs, And Full Verification

**Files:**
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `PROJECT_LOG.md`
- Modify: `docs/superpowers/specs/2026-06-25-research-topics-assistant-design.md` only if implementation changed the contract.

- [ ] **Step 1: Update README docs**

In `README.zh-CN.md`, add a concise section under Web workbench capabilities:

```md
- `课题档案`
  以课题为项目、论文精读为最小线程单位保存研究状态。搜索只提供下一步推荐；进入 Paper Reader 并关联课题后，阅读进度、用户问题、助手回答和显式同步的选区会记录到论文精读线程。Citation Trace 可作为该线程中的一次溯源行动保存。小助手建议卡默认安静显示，不打断主工作流。
```

In `README.md`, add the equivalent English section:

```md
- `Research Topics`
  Stores research state with topics as projects and Paper Reader sessions as paper-level reading threads. Search only recommends next steps; durable records begin after a paper is attached to a topic in Paper Reader. Reading progress, user questions, assistant replies, synced excerpts, and Citation Trace actions can be saved under the paper thread. Assistant suggestion cards stay quiet and do not interrupt the main workflow.
```

Add `ASSISTANT_CHAT_*` environment variables near other chat settings in both READMEs:

```md
- `ASSISTANT_CHAT_PROVIDER`
- `ASSISTANT_CHAT_MODEL`
- `ASSISTANT_CHAT_BASE_URL`
- `ASSISTANT_CHAT_API_KEY`
```

- [ ] **Step 2: Update PROJECT_LOG**

Add a top entry:

```md
## YYYY-MM-DD HH:MM

- 摘要：实现课题档案助手骨架，新增小助手独立 `assistant_chat` 配置、课题/论文精读线程 API、建议卡、Paper Reader 线程事件、Citation Trace 行动记录和课题档案页面。
- 涉及文件：`local_paper_db/app/search_service.py`、`backend/schemas.py`、`backend/config_store.py`、`backend/live2d_service.py`、`backend/research_topics_service.py`、`backend/main.py`、`frontend/src/App.jsx`、`frontend/src/Live2DAssistant.jsx`、`frontend/src/PaperReaderPage.jsx`、`frontend/src/CitationTracePage.jsx`、`frontend/src/ResearchTopicsPage.jsx`、`frontend/src/styles.css`、`config/runtime_settings.example.json`、`README.md`、`README.zh-CN.md`、`tests/test_assistant_chat_config.py`、`tests/test_research_topics_service.py`、`tests/test_research_topics_api.py`、`tests/test_research_topics_frontend.py`、`PROJECT_LOG.md`
- 验证：执行 `.venv/bin/python -m unittest tests.test_assistant_chat_config tests.test_research_topics_service tests.test_research_topics_api tests.test_research_topics_frontend tests.test_paper_reader_live2d_behavior tests.test_citation_trace_frontend tests.test_research_profile_frontend`（通过）；执行 `.venv/bin/python -m unittest discover -s tests`（通过）；执行 `.venv/bin/python -m py_compile backend/research_topics_service.py backend/main.py backend/schemas.py backend/config_store.py backend/live2d_service.py local_paper_db/app/search_service.py`（通过）；执行 `npm run build`（在 `frontend/` 下，通过）；执行 `git diff --check`（通过）。
- 后续：当前课题服务先提供可测试骨架；若切换到 PostgreSQL 持久化，需要保留现有 API 契约并增加数据库迁移/降级测试。
```

Replace `YYYY-MM-DD HH:MM` with `date '+%Y-%m-%d %H:%M'`.

- [ ] **Step 3: Run targeted verification**

Run:

```bash
.venv/bin/python -m unittest tests.test_assistant_chat_config tests.test_research_topics_service tests.test_research_topics_api tests.test_research_topics_frontend tests.test_paper_reader_live2d_behavior tests.test_citation_trace_frontend tests.test_research_profile_frontend
```

Expected: PASS.

- [ ] **Step 4: Run full backend verification**

Run:

```bash
.venv/bin/python -m unittest discover -s tests
.venv/bin/python -m py_compile backend/research_topics_service.py backend/main.py backend/schemas.py backend/config_store.py backend/live2d_service.py local_paper_db/app/search_service.py
```

Expected: PASS.

- [ ] **Step 5: Run frontend build**

Run:

```bash
cd frontend && npm run build
```

Expected: PASS.

- [ ] **Step 6: Run diff check**

Run:

```bash
git diff --check
```

Expected: no output.

- [ ] **Step 7: Commit docs and final integration**

```bash
git add README.md README.zh-CN.md PROJECT_LOG.md docs/superpowers/specs/2026-06-25-research-topics-assistant-design.md
git commit -m "Document research topics assistant"
```

## Self-Review

- Spec coverage: `assistant_chat` is covered in Tasks 1, 2, 9, and 11. Topic projects, unique paper reading threads, durable storage, thread events, Citation Trace actions, search no-write recommendations, quiet suggestion cards, and topic archive UI are covered in Tasks 3 through 10. Documentation and verification are covered in Task 11.
- Placeholder scan: this plan intentionally avoids open-ended implementation markers. Each task has concrete files, code snippets, commands, and expected outcomes.
- Type consistency: service functions introduced in Task 3 are preserved by Task 4 and reused by Tasks 5 and 6. Frontend names introduced in Tasks 7 through 10 use `currentResearchThread`, `assistantSuggestions`, `ResearchTopicsPage`, and `assistant_chat` consistently.
