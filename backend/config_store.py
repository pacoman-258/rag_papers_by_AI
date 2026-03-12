from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.schemas import (
    ChatConfigRequest,
    ChatConfigResponse,
    EmbeddingConfigModel,
    RerankConfigRequest,
    RerankConfigResponse,
    RetrievalConfigModel,
    RuntimeSettingsRequest,
    RuntimeSettingsResponse,
)
from local_paper_db.app.search_service import (
    ChatConfig,
    EmbeddingConfig,
    RerankConfig,
    RetrievalConfig,
    RuntimeSettings,
    get_env_default_settings,
    normalize_ollama_api_url,
)


CONFIG_PATH = Path("config/runtime_settings.json")


def ensure_config_file() -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        default_settings = runtime_settings_to_storage(get_env_default_settings())
        CONFIG_PATH.write_text(json.dumps(default_settings, ensure_ascii=False, indent=2), encoding="utf-8")


def runtime_settings_to_storage(settings: RuntimeSettings) -> dict[str, Any]:
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
        },
        "rerank": {
            "base_url": settings.rerank.base_url,
            "model": settings.rerank.model,
            "api_key": settings.rerank.api_key,
        },
    }


def storage_to_runtime_settings(data: dict[str, Any]) -> RuntimeSettings:
    embedding_api_url = normalize_ollama_api_url(data["embedding"]["api_url"])
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
        retrieval=RetrievalConfig(**data["retrieval"]),
        rerank=RerankConfig(**data["rerank"]),
    )


def load_runtime_settings() -> RuntimeSettings:
    ensure_config_file()
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return storage_to_runtime_settings(data)


def save_runtime_settings(settings: RuntimeSettings) -> RuntimeSettings:
    ensure_config_file()
    CONFIG_PATH.write_text(
        json.dumps(runtime_settings_to_storage(settings), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
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
    )


def runtime_settings_to_response(settings: RuntimeSettings) -> RuntimeSettingsResponse:
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
        ),
        rerank=RerankConfigResponse(
            base_url=settings.rerank.base_url,
            model=settings.rerank.model,
            has_api_key=bool(settings.rerank.api_key),
        ),
    )
