import unittest
from unittest.mock import patch

from backend.live2d_service import generate_live2d_reply
from backend.main import resolve_saved_model_list_api_key
from backend.schemas import ModelListRequest
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
        assistant_chat=ChatConfig(
            provider="openai_compatible",
            model="assistant-model",
            base_url="https://assistant.example/v1",
            api_key="assistant-key",
        ),
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

    def test_live2d_reply_uses_assistant_chat_config(self) -> None:
        settings = _settings()
        memory_context = {
            "session_id": "session-assistant",
            "memory_used": False,
            "used_memory_items": [],
            "memory_prompt_block": None,
            "memory_notice": None,
            "workflow_context": None,
        }

        with (
            patch("backend.live2d_service.prepare_live2d_chat_context", return_value=memory_context),
            patch("backend.live2d_service.finalize_live2d_chat_turn"),
            patch(
                "backend.live2d_service.chat_completion",
                return_value='{"reply_text":"hello","speak_text":"hello","expression":"smile"}',
            ) as chat_completion_mock,
        ):
            generate_live2d_reply(
                source="user",
                message="hello",
                language="en",
                history=[],
                answer_context=None,
                workflow_context=None,
                session_id="session-assistant",
                settings=settings,
                available_expressions=["smile"],
            )

        self.assertIs(chat_completion_mock.call_args.args[1], settings.assistant_chat)

    def test_model_list_reuses_saved_assistant_chat_api_key(self) -> None:
        settings = _settings()
        payload = ModelListRequest(
            provider="openai_compatible",
            base_url="https://assistant.example/v1",
            api_key=None,
            kind="chat",
        )

        with patch("backend.main.load_runtime_settings", return_value=settings):
            api_key = resolve_saved_model_list_api_key(payload)

        self.assertEqual(api_key, "assistant-key")


if __name__ == "__main__":
    unittest.main()
