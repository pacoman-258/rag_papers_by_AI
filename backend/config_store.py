from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from backend.schemas import (
    AssistantMemoryConfigModel,
    ChatConfigRequest,
    ChatConfigResponse,
    EmbeddingConfigModel,
    RerankConfigRequest,
    RerankConfigResponse,
    RetrievalConfigModel,
    RetrievalProvidersModel,
    RuntimeSettingsRequest,
    RuntimeSettingsResponse,
)
from local_paper_db.app.search_service import (
    AssistantMemoryConfig,
    ChatConfig,
    EmbeddingConfig,
    RerankConfig,
    RetrievalConfig,
    RuntimeSettings,
    get_env_default_settings,
    normalize_ollama_api_url,
)


CONFIG_PATH = Path("config/runtime_settings.json")
_DEFAULT_RETRIEVAL_PROVIDERS = RetrievalProvidersModel()
_CURRENT_RETRIEVAL_PROVIDERS = _DEFAULT_RETRIEVAL_PROVIDERS.model_copy()


def coerce_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _default_retrieval_providers() -> RetrievalProvidersModel:
    return _DEFAULT_RETRIEVAL_PROVIDERS.model_copy()


def _coerce_retrieval_providers(
    value: Any,
    default: RetrievalProvidersModel | None = None,
) -> RetrievalProvidersModel:
    fallback = default or _default_retrieval_providers()
    data = value if isinstance(value, dict) else {}
    return RetrievalProvidersModel(
        local=coerce_bool(data.get("local"), fallback.local),
        arxiv=coerce_bool(data.get("arxiv"), fallback.arxiv),
        wos=coerce_bool(data.get("wos"), fallback.wos),
    )


def _set_current_retrieval_providers(providers: RetrievalProvidersModel) -> RetrievalProvidersModel:
    global _CURRENT_RETRIEVAL_PROVIDERS
    _CURRENT_RETRIEVAL_PROVIDERS = providers.model_copy()
    return _CURRENT_RETRIEVAL_PROVIDERS.model_copy()


def current_retrieval_providers() -> RetrievalProvidersModel:
    return _CURRENT_RETRIEVAL_PROVIDERS.model_copy()


def retrieval_providers_to_source_list(providers: RetrievalProvidersModel | None) -> list[str]:
    resolved = providers or current_retrieval_providers()
    sources: list[str] = []
    if resolved.local:
        sources.append("local")
    if resolved.arxiv:
        sources.append("arxiv")
    if resolved.wos:
        sources.append("wos")
    return sources


def validate_retrieval_providers(providers: RetrievalProvidersModel) -> None:
    if not (providers.local or providers.arxiv or providers.wos):
        raise RuntimeError("At least one retrieval provider must be enabled.")


def sync_retrieval_enabled_sources(providers: RetrievalProvidersModel | None = None) -> None:
    os.environ["RETRIEVAL_ENABLED_SOURCES"] = ",".join(retrieval_providers_to_source_list(providers))


def merge_retrieval_providers(
    base: RetrievalProvidersModel,
    incoming: RetrievalProvidersModel | None,
) -> RetrievalProvidersModel:
    if incoming is None:
        return base.model_copy()
    return RetrievalProvidersModel(
        local=incoming.local,
        arxiv=incoming.arxiv,
        wos=incoming.wos,
    )


def ensure_config_file() -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        default_settings = runtime_settings_to_storage(get_env_default_settings(), _default_retrieval_providers())
        CONFIG_PATH.write_text(json.dumps(default_settings, ensure_ascii=False, indent=2), encoding="utf-8")


def runtime_settings_to_storage(
    settings: RuntimeSettings,
    retrieval_providers: RetrievalProvidersModel | None = None,
) -> dict[str, Any]:
    providers = retrieval_providers or current_retrieval_providers()
    return {
        "query_chat": {
            "provider": settings.query_chat.provider,
            "model": settings.query_chat.model,
            "base_url": settings.query_chat.base_url,
            "api_key": settings.query_chat.api_key,
        },
        "answer_chat": {
            "provider": settings.answer_chat.provider,
            "model": settings.answer_chat.model,
            "base_url": settings.answer_chat.base_url,
            "api_key": settings.answer_chat.api_key,
        },
        "embedding": {
            "api_url": settings.embedding.api_url,
            "model": settings.embedding.model,
        },
        "retrieval": {
            "top_k": settings.retrieval.top_k,
            "top_n": settings.retrieval.top_n,
            "request_timeout": settings.retrieval.request_timeout,
            "providers": {
                "local": providers.local,
                "arxiv": providers.arxiv,
                "wos": providers.wos,
            },
        },
        "rerank": {
            "base_url": settings.rerank.base_url,
            "model": settings.rerank.model,
            "api_key": settings.rerank.api_key,
        },
        "assistant_memory": {
            "enabled": settings.assistant_memory.enabled,
            "summary_interval_turns": settings.assistant_memory.summary_interval_turns,
            "major_summary_group_size": settings.assistant_memory.major_summary_group_size,
            "max_recall_items": settings.assistant_memory.max_recall_items,
            "recall_threshold": settings.assistant_memory.recall_threshold,
            "auto_save_enabled": settings.assistant_memory.auto_save_enabled,
        },
    }


def storage_to_runtime_settings(data: dict[str, Any]) -> RuntimeSettings:
    default_settings = get_env_default_settings()
    embedding_api_url = normalize_ollama_api_url(data["embedding"]["api_url"])
    default_assistant_memory = get_env_default_settings().assistant_memory
    assistant_memory_data = data.get("assistant_memory") if isinstance(data.get("assistant_memory"), dict) else {}
    retrieval_data = data.get("retrieval") if isinstance(data.get("retrieval"), dict) else {}
    retrieval_providers = _coerce_retrieval_providers(
        retrieval_data.get("providers"),
        _default_retrieval_providers(),
    )
    validate_retrieval_providers(retrieval_providers)
    _set_current_retrieval_providers(retrieval_providers)
    return RuntimeSettings(
        query_chat=ChatConfig(
            provider=data["query_chat"]["provider"],
            model=data["query_chat"]["model"],
            base_url=data["query_chat"].get("base_url") or embedding_api_url,
            api_key=data["query_chat"].get("api_key"),
        ),
        answer_chat=ChatConfig(
            provider=data["answer_chat"]["provider"],
            model=data["answer_chat"]["model"],
            base_url=data["answer_chat"].get("base_url") or embedding_api_url,
            api_key=data["answer_chat"].get("api_key"),
        ),
        embedding=EmbeddingConfig(api_url=embedding_api_url, model=data["embedding"]["model"]),
        retrieval=RetrievalConfig(
            top_k=int(retrieval_data.get("top_k", default_settings.retrieval.top_k)),
            top_n=int(retrieval_data.get("top_n", default_settings.retrieval.top_n)),
            request_timeout=int(retrieval_data.get("request_timeout", default_settings.retrieval.request_timeout)),
        ),
        rerank=RerankConfig(**data["rerank"]),
        assistant_memory=AssistantMemoryConfig(
            enabled=coerce_bool(assistant_memory_data.get("enabled"), default_assistant_memory.enabled),
            summary_interval_turns=int(
                assistant_memory_data.get("summary_interval_turns", default_assistant_memory.summary_interval_turns)
            ),
            major_summary_group_size=int(
                assistant_memory_data.get("major_summary_group_size", default_assistant_memory.major_summary_group_size)
            ),
            max_recall_items=int(
                assistant_memory_data.get("max_recall_items", default_assistant_memory.max_recall_items)
            ),
            recall_threshold=float(
                assistant_memory_data.get("recall_threshold", default_assistant_memory.recall_threshold)
            ),
            auto_save_enabled=coerce_bool(
                assistant_memory_data.get("auto_save_enabled"), default_assistant_memory.auto_save_enabled
            ),
        ),
    )


def load_runtime_settings() -> RuntimeSettings:
    ensure_config_file()
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    settings = storage_to_runtime_settings(data)
    sync_retrieval_enabled_sources(current_retrieval_providers())
    return settings


def save_runtime_settings(
    settings: RuntimeSettings,
    retrieval_providers: RetrievalProvidersModel | None = None,
) -> RuntimeSettings:
    ensure_config_file()
    providers = retrieval_providers or current_retrieval_providers()
    validate_retrieval_providers(providers)
    _set_current_retrieval_providers(providers)
    CONFIG_PATH.write_text(
        json.dumps(runtime_settings_to_storage(settings, providers), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    sync_retrieval_enabled_sources(providers)
    return settings


def merge_chat(base: ChatConfig, incoming: ChatConfigRequest) -> ChatConfig:
    api_key = base.api_key
    if incoming.clear_api_key:
        api_key = None
    elif incoming.api_key not in (None, ""):
        api_key = incoming.api_key

    return ChatConfig(
        provider=incoming.provider,
        model=incoming.model,
        base_url=incoming.base_url,
        api_key=api_key,
    )


def merge_rerank(base: RerankConfig, incoming: RerankConfigRequest) -> RerankConfig:
    api_key = base.api_key
    if incoming.clear_api_key:
        api_key = None
    elif incoming.api_key not in (None, ""):
        api_key = incoming.api_key

    return RerankConfig(base_url=incoming.base_url, model=incoming.model, api_key=api_key)


def merge_runtime_settings(
    base: RuntimeSettings,
    incoming: RuntimeSettingsRequest | None,
) -> RuntimeSettings:
    if incoming is None:
        return base

    embedding_api_url = normalize_ollama_api_url(incoming.embedding.api_url)
    query_chat = merge_chat(base.query_chat, incoming.query_chat)
    answer_chat = merge_chat(base.answer_chat, incoming.answer_chat)

    if query_chat.provider == "ollama" and not query_chat.base_url:
        query_chat = ChatConfig(
            provider=query_chat.provider,
            model=query_chat.model,
            base_url=embedding_api_url,
            api_key=query_chat.api_key,
        )
    if answer_chat.provider == "ollama" and not answer_chat.base_url:
        answer_chat = ChatConfig(
            provider=answer_chat.provider,
            model=answer_chat.model,
            base_url=embedding_api_url,
            api_key=answer_chat.api_key,
        )
    assistant_memory = (
        AssistantMemoryConfig(
            enabled=incoming.assistant_memory.enabled,
            summary_interval_turns=incoming.assistant_memory.summary_interval_turns,
            major_summary_group_size=incoming.assistant_memory.major_summary_group_size,
            max_recall_items=incoming.assistant_memory.max_recall_items,
            recall_threshold=incoming.assistant_memory.recall_threshold,
            auto_save_enabled=incoming.assistant_memory.auto_save_enabled,
        )
        if incoming.assistant_memory is not None
        else base.assistant_memory
    )

    return RuntimeSettings(
        query_chat=query_chat,
        answer_chat=answer_chat,
        embedding=EmbeddingConfig(
            api_url=incoming.embedding.api_url,
            model=incoming.embedding.model,
        ),
        retrieval=RetrievalConfig(
            top_k=incoming.retrieval.top_k,
            top_n=incoming.retrieval.top_n,
            request_timeout=incoming.retrieval.request_timeout,
        ),
        rerank=merge_rerank(base.rerank, incoming.rerank),
        assistant_memory=assistant_memory,
    )


def runtime_settings_to_response(
    settings: RuntimeSettings,
    retrieval_providers: RetrievalProvidersModel | None = None,
) -> RuntimeSettingsResponse:
    providers = retrieval_providers or current_retrieval_providers()
    return RuntimeSettingsResponse(
        query_chat=ChatConfigResponse(
            provider=settings.query_chat.provider,
            model=settings.query_chat.model,
            base_url=settings.query_chat.base_url,
            has_api_key=bool(settings.query_chat.api_key),
        ),
        answer_chat=ChatConfigResponse(
            provider=settings.answer_chat.provider,
            model=settings.answer_chat.model,
            base_url=settings.answer_chat.base_url,
            has_api_key=bool(settings.answer_chat.api_key),
        ),
        embedding=EmbeddingConfigModel(
            api_url=settings.embedding.api_url,
            model=settings.embedding.model,
        ),
        retrieval=RetrievalConfigModel(
            top_k=settings.retrieval.top_k,
            top_n=settings.retrieval.top_n,
            request_timeout=settings.retrieval.request_timeout,
            providers=providers,
        ),
        rerank=RerankConfigResponse(
            base_url=settings.rerank.base_url,
            model=settings.rerank.model,
            has_api_key=bool(settings.rerank.api_key),
        ),
        assistant_memory=AssistantMemoryConfigModel(
            enabled=settings.assistant_memory.enabled,
            summary_interval_turns=settings.assistant_memory.summary_interval_turns,
            major_summary_group_size=settings.assistant_memory.major_summary_group_size,
            max_recall_items=settings.assistant_memory.max_recall_items,
            recall_threshold=settings.assistant_memory.recall_threshold,
            auto_save_enabled=settings.assistant_memory.auto_save_enabled,
        ),
    )
