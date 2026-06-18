import json
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import paper_reader_service as prs
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
        self.assertEqual(restored.paper_reader_translation.model, "translator-model")
        self.assertEqual(response.paper_reader_translation.model, "translator-model")
        self.assertFalse(response.paper_reader_translation.has_api_key)

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


if __name__ == "__main__":
    unittest.main()
