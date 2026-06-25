import json
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import paper_reader_service as prs
from backend import live2d_service
from backend.config_store import runtime_settings_to_response, runtime_settings_to_storage, storage_to_runtime_settings
from backend.schemas import PaperReaderSelectionTranslateRequest
from local_paper_db.app.search_service import (
    AssistantMemoryConfig,
    ChatConfig,
    EmbeddingConfig,
    PaperReaderChatConfig,
    RerankConfig,
    RetrievalConfig,
    RuntimeSettings,
)


def _chunk(chunk_id: str, text: str) -> prs.PaperReaderChunk:
    return prs.PaperReaderChunk(
        chunk_id=chunk_id,
        text=text,
        section_title="Abstract",
        subsection_title=None,
        reading_focus_key="problem_and_claim",
        reading_focus_title="Problem and claim",
        page_start=1,
        page_end=1,
        token_estimate=20,
    )


def _plan() -> prs.PaperReaderPagePlan:
    return prs.PaperReaderPagePlan(
        page_index=0,
        title="Problem and claim",
        focus_key="problem_and_claim",
        focus_title="Problem and claim",
        section_title="Problem and claim",
        subsection_title=None,
        source_section_titles=["Abstract"],
        chunk_ids=["c-abstract"],
        page_start=1,
        page_end=1,
        estimated_tokens=20,
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


def _session(settings: RuntimeSettings) -> prs.PaperReaderSession:
    plan = _plan()
    return prs.PaperReaderSession(
        session_id="session-translation",
        source_type="file",
        source_url=None,
        source_id="paper.pdf",
        paper_title="Attention Is All You Need",
        authors=[],
        published_date=None,
        answer_language="zh",
        reader_mode="guided",
        discipline="science_engineering",
        discipline_source="manual",
        pdf_path=Path("/tmp/paper.pdf"),
        max_context_tokens=8192,
        reserved_output_tokens=1024,
        reserved_scaffold_tokens=1200,
        page_input_budget=5968,
        settings=settings,
        chunks=[
            _chunk(
                "c-abstract",
                "We propose a new simple network architecture, the Transformer, based solely on attention mechanisms.",
            )
        ],
        pages=[plan],
        page_statuses={0: "queued"},
    )


class PaperReaderTranslationTest(unittest.TestCase):
    def test_runtime_settings_round_trips_separate_translation_config(self):
        settings = _settings()

        stored = runtime_settings_to_storage(settings)
        restored = storage_to_runtime_settings(stored)
        response = runtime_settings_to_response(restored)

        self.assertEqual(stored["paper_reader_translation"]["model"], "translator-model")
        self.assertEqual(stored["citation_trace_main_chat"]["model"], "trace-main-model")
        self.assertEqual(stored["citation_trace_worker_chat"]["model"], "trace-worker-model")
        self.assertEqual(restored.paper_reader_translation.model, "translator-model")
        self.assertEqual(restored.citation_trace_main_chat.model, "trace-main-model")
        self.assertEqual(restored.citation_trace_worker_chat.model, "trace-worker-model")
        self.assertEqual(response.paper_reader_translation.model, "translator-model")
        self.assertEqual(response.citation_trace_main_chat.model, "trace-main-model")
        self.assertEqual(response.citation_trace_worker_chat.model, "trace-worker-model")
        self.assertFalse(response.paper_reader_translation.has_api_key)
        self.assertFalse(response.citation_trace_main_chat.has_api_key)
        self.assertFalse(response.citation_trace_worker_chat.has_api_key)

    def test_missing_translation_config_inherits_saved_paper_reader_chat(self):
        settings = _settings()
        stored = runtime_settings_to_storage(settings)
        stored["paper_reader_chat"].update(
            {
                "provider": "openai_compatible",
                "model": "reader-remote-model",
                "base_url": "https://reader.example/v1",
                "api_key": "reader-key",
            }
        )
        stored.pop("paper_reader_translation")

        with patch("backend.config_store.get_env_default_settings", return_value=_settings()):
            restored = storage_to_runtime_settings(stored)

        self.assertEqual(restored.paper_reader_translation.provider, "openai_compatible")
        self.assertEqual(restored.paper_reader_translation.model, "reader-remote-model")
        self.assertEqual(restored.paper_reader_translation.base_url, "https://reader.example/v1")
        self.assertEqual(restored.paper_reader_translation.api_key, "reader-key")

    def test_missing_citation_trace_configs_inherit_saved_answer_and_reader_models(self):
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
        stored["paper_reader_chat"].update(
            {
                "provider": "openai_compatible",
                "model": "reader-remote-model",
                "base_url": "https://reader.example/v1",
                "api_key": "reader-key",
            }
        )
        stored.pop("citation_trace_main_chat")
        stored.pop("citation_trace_worker_chat")

        with patch("backend.config_store.get_env_default_settings", return_value=_settings()):
            restored = storage_to_runtime_settings(stored)

        self.assertEqual(restored.citation_trace_main_chat.provider, "openai_compatible")
        self.assertEqual(restored.citation_trace_main_chat.model, "answer-remote-model")
        self.assertEqual(restored.citation_trace_main_chat.base_url, "https://answer.example/v1")
        self.assertEqual(restored.citation_trace_main_chat.api_key, "answer-key")
        self.assertEqual(restored.citation_trace_worker_chat.provider, "openai_compatible")
        self.assertEqual(restored.citation_trace_worker_chat.model, "reader-remote-model")
        self.assertEqual(restored.citation_trace_worker_chat.base_url, "https://reader.example/v1")
        self.assertEqual(restored.citation_trace_worker_chat.api_key, "reader-key")

    def test_page_generation_uses_translation_config_for_missing_reading_block_explanations(self):
        settings = _settings()
        session = _session(settings)
        main_output = {
            "page_title": "Problem and claim",
            "coverage": "Abstract",
            "page_overview": {
                "original_en": "We propose a new simple network architecture.",
                "explanation": "本页说明 Transformer 的核心主张。",
            },
            "insights": [
                {
                    "title": "提出 Transformer",
                    "kind": "method",
                    "summary": {
                        "original_en": "We propose a new simple network architecture.",
                        "explanation": "作者提出一种完全基于注意力机制的新架构。",
                    },
                    "evidence": [],
                    "source_chunk_ids": ["c-abstract"],
                }
            ],
            "citations": [],
        }
        translation_output = {
            "translations": [
                {
                    "chunk_id": "c-abstract",
                    "explanation": "作者提出 Transformer，这是一种完全基于注意力机制的简单网络架构。",
                }
            ]
        }
        called_models: list[str] = []

        def fake_chat_completion(_messages, config, _timeout):
            called_models.append(config.model)
            if config.model == "reader-model":
                return json.dumps(main_output)
            if config.model == "translator-model":
                return json.dumps(translation_output)
            raise AssertionError(f"unexpected model {config.model}")

        with patch.dict(prs._SESSION_CACHE, {session.session_id: session}, clear=True):
            with patch("backend.paper_reader_service.chat_completion", side_effect=fake_chat_completion):
                content = prs._generate_page_content_internal(session.session_id, 0, settings, stream=False)

        self.assertEqual(called_models, ["reader-model", "translator-model"])
        self.assertEqual(content.reading_blocks[0].explanation, translation_output["translations"][0]["explanation"])
        self.assertEqual(content.reading_blocks[0].display_text, translation_output["translations"][0]["explanation"])

    def test_selected_text_translation_uses_translation_config_only(self):
        settings = _settings()
        session = _session(settings)
        request = PaperReaderSelectionTranslateRequest(
            text="Attention mechanisms connect any two positions with a constant number of operations.",
            answer_language="zh",
        )
        called_models: list[str] = []
        captured_prompts: list[str] = []

        def fake_chat_completion(messages, config, _timeout):
            called_models.append(config.model)
            captured_prompts.append(messages[-1]["content"])
            return json.dumps({"translation": "注意力机制用常数次操作连接任意两个位置。"}, ensure_ascii=False)

        with patch.dict(prs._SESSION_CACHE, {session.session_id: session}, clear=True):
            with patch("backend.paper_reader_service.chat_completion", side_effect=fake_chat_completion):
                response = prs.translate_selected_text(session.session_id, request, settings)

        self.assertEqual(called_models, ["translator-model"])
        self.assertIn("Translate only", captured_prompts[0])
        self.assertIn("Do not explain", captured_prompts[0])
        self.assertEqual(response.translation, "注意力机制用常数次操作连接任意两个位置。")
        self.assertEqual(response.source_text, request.text)

    def test_standalone_selected_text_translation_uses_translation_config_without_session(self):
        settings = _settings()
        request = PaperReaderSelectionTranslateRequest(
            text="Attention mechanisms connect any two positions with a constant number of operations.",
            answer_language="zh",
        )
        called_models: list[str] = []

        def fake_chat_completion(_messages, config, _timeout):
            called_models.append(config.model)
            return json.dumps({"translation": "注意力机制用常数次操作连接任意两个位置。"}, ensure_ascii=False)

        with patch("backend.paper_reader_service.chat_completion", side_effect=fake_chat_completion):
            response = prs.translate_standalone_selected_text(request, settings)

        self.assertEqual(called_models, ["translator-model"])
        self.assertIsNone(response.session_id)
        self.assertEqual(response.translation, "注意力机制用常数次操作连接任意两个位置。")
        self.assertEqual(response.source_text, request.text)

    def test_selected_text_translation_can_use_google_translate_mode(self):
        settings = _settings()
        settings.paper_reader_translation = ChatConfig(
            provider="google_translate",
            model="",
            base_url=None,
            api_key=None,
        )
        session = _session(settings)
        request = PaperReaderSelectionTranslateRequest(
            text="Attention mechanisms connect any two positions with a constant number of operations.",
            answer_language="zh",
        )

        with patch.dict(prs._SESSION_CACHE, {session.session_id: session}, clear=True):
            with patch("backend.paper_reader_service.chat_completion") as chat_completion_mock:
                with patch(
                    "backend.paper_reader_service.google_translate_text",
                    return_value="注意力机制用常数次操作连接任意两个位置。",
                ) as google_translate_mock:
                    response = prs.translate_selected_text(session.session_id, request, settings)

        chat_completion_mock.assert_not_called()
        google_translate_mock.assert_called_once_with(
            request.text,
            "zh",
            timeout=settings.retrieval.request_timeout,
        )
        self.assertEqual(response.translation, "注意力机制用常数次操作连接任意两个位置。")
        self.assertEqual(response.source_text, request.text)

    def test_assistant_context_uses_whole_paper_source_pages(self):
        settings = _settings()
        session = _session(settings)
        session.source_pages = [
            (1, "The abstract introduces attention-only sequence modeling."),
            (2, "The method section describes multi-head attention and feed-forward layers."),
            (3, "The experiments compare translation quality and training cost."),
        ]
        session.chunks.append(
            prs.PaperReaderChunk(
                chunk_id="c-method",
                text="Multi-head attention projects queries, keys, and values into several representation subspaces.",
                section_title="Method",
                subsection_title="Multi-head attention",
                reading_focus_key="method_or_system",
                reading_focus_title="Method or system",
                page_start=2,
                page_end=2,
                token_estimate=24,
            )
        )

        with patch.dict(prs._SESSION_CACHE, {session.session_id: session}, clear=True):
            response = prs.build_assistant_context(session.session_id)

        self.assertEqual(response.session_id, session.session_id)
        self.assertIn("Whole-paper context", response.answer_context)
        self.assertIn("Attention Is All You Need", response.answer_context)
        self.assertIn("PDF page 1", response.answer_context)
        self.assertIn("PDF page 3", response.answer_context)
        self.assertIn("multi-head attention", response.answer_context)
        self.assertEqual(response.workflow_context.kind, "paper_reader")
        self.assertEqual(response.workflow_context.session_id, session.session_id)
        self.assertIn("whole_paper", response.workflow_context.metadata)
        self.assertNotIn("current page", response.answer_context.lower())

    def test_live2d_paper_reader_context_renders_manual_selection_focus(self):
        workflow_context = {
            "kind": "paper_reader",
            "paper_title": "Attention Is All You Need",
            "answer_language": "zh",
            "metadata": {
                "selected_excerpt": {
                    "text": "Scaled dot-product attention divides by the square root of the key dimension.",
                    "page_numbers": ["3"],
                    "created_at": "2026-06-24T15:00:00Z",
                }
            },
        }

        rendered = "\n".join(live2d_service._render_paper_reader_context_lines(workflow_context))
        system_prompt = live2d_service._build_live2d_system_prompt([], workflow_context, reply_language="zh")

        self.assertIn("selected_excerpt", rendered)
        self.assertIn("Scaled dot-product attention", rendered)
        self.assertIn("source_pages: 3", rendered)
        self.assertIn("whole paper", system_prompt)
        self.assertNotIn("page-local", system_prompt)
        self.assertNotIn("current page context", system_prompt)

    def test_live2d_paper_reader_context_renders_conversation_context(self):
        workflow_context = {
            "kind": "paper_reader",
            "paper_title": "Attention Is All You Need",
            "answer_language": "zh",
            "metadata": {
                "conversation_context": {
                    "recent_messages": [
                        {"role": "user", "text": "先解释一下 attention 的缩放项。"},
                        {"role": "assistant", "text": "缩放项用于控制点积幅度，避免 softmax 过尖。"},
                    ],
                    "current_user_message": "那它和多头注意力有什么关系？",
                }
            },
        }

        rendered = "\n".join(live2d_service._render_paper_reader_context_lines(workflow_context))

        self.assertIn("conversation_recent_user", rendered)
        self.assertIn("attention 的缩放项", rendered)
        self.assertIn("conversation_recent_assistant", rendered)
        self.assertIn("softmax", rendered)
        self.assertIn("current_user_message", rendered)
        self.assertIn("多头注意力", rendered)


if __name__ == "__main__":
    unittest.main()
