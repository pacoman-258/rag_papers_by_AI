import json
import unittest
from unittest.mock import patch

from backend import assistant_memory as am
from backend import live2d_service as live2d
from backend.schemas import ResearchProfileRefreshRequest
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


def _paper_reader_context() -> dict:
    return {
        "kind": "paper_reader",
        "paper_title": "Graph RAG for Scientific Paper Reading",
        "discipline": "science_engineering",
        "page_title": "Method or mechanism",
        "latest_page_summary": "The page explains graph retrieval, reranking, and long-term assistant memory.",
        "question": "How could this help personalize future paper reading?",
        "glossary_terms": [
            {"term": "graph RAG", "explanation": "retrieval over paper and memory graphs"},
        ],
        "blackboard_notes": {
            "core_concepts": ["graph RAG", "assistant memory", "personalized paper reading"],
            "method_steps": ["extract paper signals", "connect them as memory nodes"],
        },
    }


class AssistantResearchProfileTest(unittest.TestCase):
    def test_major_memory_extraction_creates_research_profile_nodes_from_paper_reader_context(self) -> None:
        model_payload = {
            "preferences": [],
            "topics": [],
            "tasks": [],
            "facts": [],
            "expertise_signals": [
                {
                    "label": "paper-centric graph RAG and long-term assistant memory",
                    "confidence": 0.84,
                    "evidence": ["Graph RAG for Scientific Paper Reading"],
                }
            ],
            "research_directions": [
                {
                    "label": "personalized paper reading assistants",
                    "confidence": 0.78,
                    "evidence": ["How could this help personalize future paper reading?"],
                }
            ],
            "reading_preferences": [
                {
                    "label": "prefers method-level explanations grounded in current paper pages",
                    "confidence": 0.72,
                    "evidence": ["Method or mechanism"],
                }
            ],
        }

        with patch("backend.assistant_memory.chat_completion", return_value=json.dumps(model_payload)):
            items, _relations = am._extract_memory_candidates_from_major(
                major_summary_payload={"summary": "The user studied graph RAG memory for paper reading."},
                major_summary_text="The user studied graph RAG memory for paper reading.",
                workflow_contexts=[_paper_reader_context()],
                settings=_settings(),
            )

        by_type = {item["node_type"]: item for item in items}
        self.assertIn("expertise_signal", by_type)
        self.assertIn("research_direction", by_type)
        self.assertIn("reading_preference", by_type)
        self.assertEqual(by_type["expertise_signal"]["text"], "paper-centric graph RAG and long-term assistant memory")
        self.assertEqual(by_type["expertise_signal"]["metadata"]["source"], "research_profile")
        self.assertIn("Graph RAG for Scientific Paper Reading", by_type["expertise_signal"]["metadata"]["evidence"])

    def test_research_profile_extraction_filters_sensitive_or_low_confidence_claims(self) -> None:
        model_payload = {
            "expertise_signals": [
                {"label": "the user is a 16-year-old student", "confidence": 0.95, "evidence": ["chat tone"]},
                {"label": "paper recommendation systems", "confidence": 0.42, "evidence": ["weak signal"]},
                {
                    "label": "retrieval evaluation for paper reading",
                    "confidence": 0.76,
                    "evidence": ["Graph RAG for Scientific Paper Reading"],
                },
            ],
            "research_directions": [],
            "reading_preferences": [],
        }

        with patch("backend.assistant_memory.chat_completion", return_value=json.dumps(model_payload)):
            items, _relations = am._extract_memory_candidates_from_major(
                major_summary_payload={"summary": "The user read a paper."},
                major_summary_text="The user read a paper.",
                workflow_contexts=[_paper_reader_context()],
                settings=_settings(),
            )

        profile_texts = [item["text"] for item in items if item["node_type"] in am.RESEARCH_PROFILE_NODE_TYPES]
        self.assertEqual(profile_texts, ["retrieval evaluation for paper reading"])

    def test_memory_prompt_block_separates_inferred_profile_from_ordinary_memory(self) -> None:
        prompt = am._build_memory_prompt_block(
            [
                {
                    "node_type": "expertise_signal",
                    "summary": "paper-centric graph RAG",
                    "score": 0.9,
                    "confidence": 0.84,
                },
                {
                    "node_type": "fact",
                    "summary": "User loaded Attention Is All You Need.",
                    "score": 0.82,
                    "confidence": 0.7,
                },
            ],
            {"kind": "paper_reader", "paper_title": "Graph RAG for Scientific Paper Reading"},
        )

        self.assertIn("Inferred research profile", prompt)
        self.assertIn("treat as uncertain", prompt)
        self.assertIn("[expertise_signal] paper-centric graph RAG", prompt)
        self.assertIn("Relevant long-term memory", prompt)
        self.assertIn("[fact] User loaded Attention Is All You Need.", prompt)

    def test_memory_options_follow_runtime_settings(self) -> None:
        settings = _settings()
        settings.assistant_memory = AssistantMemoryConfig(
            enabled=True,
            summary_interval_turns=2,
            major_summary_group_size=4,
            max_recall_items=3,
            recall_threshold=0.61,
            auto_save_enabled=False,
            research_profile_enabled=False,
        )

        options = am._memory_options(settings)

        self.assertEqual(options.summary_interval_turns, 2)
        self.assertEqual(options.major_summary_group_size, 4)
        self.assertEqual(options.max_recall_items, 3)
        self.assertEqual(options.recall_threshold, 0.61)
        self.assertFalse(options.auto_save_enabled)
        self.assertFalse(options.research_profile_enabled)

    def test_research_profile_item_format_exposes_manageable_evidence(self) -> None:
        item = am._format_research_profile_item(
            {
                "memory_id": "memory-1",
                "node_type": "research_direction",
                "summary": "personalized paper reading assistants",
                "confidence": 0.786,
                "pinned": True,
                "metadata": {
                    "evidence": ["Graph RAG for Scientific Paper Reading", "Method or mechanism"],
                    "paper_titles": ["Graph RAG for Scientific Paper Reading"],
                },
                "created_at": "2026-06-22T12:00:00+00:00",
                "updated_at": "2026-06-22T12:30:00+00:00",
            }
        )

        self.assertEqual(item["memory_id"], "memory-1")
        self.assertEqual(item["kind"], "research_direction")
        self.assertEqual(item["label"], "personalized paper reading assistants")
        self.assertEqual(item["confidence"], 0.786)
        self.assertTrue(item["pinned"])
        self.assertEqual(item["evidence"], ["Graph RAG for Scientific Paper Reading", "Method or mechanism"])

    def test_research_profile_refresh_request_accepts_workflow_context(self) -> None:
        payload = ResearchProfileRefreshRequest.model_validate(
            {
                "session_id": "session-1",
                "workflow_context": _paper_reader_context(),
            }
        )

        self.assertEqual(payload.workflow_context.kind, "paper_reader")
        self.assertEqual(payload.workflow_context.paper_title, "Graph RAG for Scientific Paper Reading")

    def test_live2d_research_profile_refresh_forwards_workflow_context(self) -> None:
        workflow_context = _paper_reader_context()
        with patch(
            "backend.live2d_service.refresh_research_profile_state",
            return_value={"session_id": "session-1", "items": [], "count": 0},
        ) as refresh_mock:
            state = live2d.refresh_live2d_research_profile(
                session_id="session-1",
                settings=_settings(),
                workflow_context=workflow_context,
            )

        self.assertTrue(state["available"])
        self.assertEqual(refresh_mock.call_args.kwargs["workflow_context"], workflow_context)

    def test_live2d_research_profile_list_degrades_when_memory_store_is_unavailable(self) -> None:
        with patch("backend.live2d_service.get_research_profile_state", side_effect=RuntimeError("db unavailable")):
            state = live2d.list_live2d_research_profile(session_id="session-1")

        self.assertFalse(state["available"])
        self.assertEqual(state["session_id"], "session-1")
        self.assertEqual(state["items"], [])
        self.assertIn("memory database", state["notice"])


if __name__ == "__main__":
    unittest.main()
