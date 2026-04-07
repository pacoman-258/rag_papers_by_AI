from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


Provider = Literal["ollama", "openai_compatible"]


class ChatConfigRequest(BaseModel):
    provider: Provider
    model: str
    base_url: str | None = None
    api_key: str | None = None
    clear_api_key: bool = False


class ChatConfigResponse(BaseModel):
    provider: Provider
    model: str
    base_url: str | None = None
    has_api_key: bool


class EmbeddingConfigModel(BaseModel):
    api_url: str
    model: str


class RetrievalConfigModel(BaseModel):
    top_k: int = Field(ge=1)
    top_n: int = Field(ge=1)
    request_timeout: int = Field(ge=1)


class RerankConfigRequest(BaseModel):
    base_url: str
    model: str
    api_key: str | None = None
    clear_api_key: bool = False


class RerankConfigResponse(BaseModel):
    base_url: str
    model: str
    has_api_key: bool


class RuntimeSettingsRequest(BaseModel):
    query_chat: ChatConfigRequest
    answer_chat: ChatConfigRequest
    embedding: EmbeddingConfigModel
    retrieval: RetrievalConfigModel
    rerank: RerankConfigRequest


class RuntimeSettingsResponse(BaseModel):
    query_chat: ChatConfigResponse
    answer_chat: ChatConfigResponse
    embedding: EmbeddingConfigModel
    retrieval: RetrievalConfigModel
    rerank: RerankConfigResponse


class RetrievalConstraintsModel(BaseModel):
    published_after: str | None = None
    published_before: str | None = None
    authors: list[str] = Field(default_factory=list)
    primary_categories: list[str] = Field(default_factory=list)
    sort_hint: Literal["relevance", "latest"] = "relevance"
    is_implicit_latest: bool = False


class QueryPlanModel(BaseModel):
    answer_language: Literal["zh", "en"]
    intent_summary: str
    retrieval_query_en: str
    keywords_en: list[str]
    constraints: RetrievalConstraintsModel = Field(default_factory=RetrievalConstraintsModel)
    corpus_latest_date: str | None = None


class SearchPlanRequest(BaseModel):
    question: str
    settings: RuntimeSettingsRequest | None = None


class SearchRefineRequest(BaseModel):
    question: str
    previous_plan: QueryPlanModel
    feedback: str
    settings: RuntimeSettingsRequest | None = None


class SearchExecuteRequest(BaseModel):
    question: str
    retrieval_text: str
    query_plan: QueryPlanModel | None = None
    settings: RuntimeSettingsRequest | None = None


class RankedPaperResponse(BaseModel):
    id: str
    title: str
    text: str
    method: str
    initial_score: float
    rerank_score: float
    authors: list[str] = Field(default_factory=list)
    published_date: str | None = None
    primary_category: str | None = None


class SearchExecuteResponse(BaseModel):
    search_id: str
    answer_language: Literal["zh", "en"]
    retrieval_text: str
    papers: list[RankedPaperResponse]
    warnings: list[str]
    applied_constraints: RetrievalConstraintsModel
    corpus_latest_date: str | None = None


class IngestJobResponse(BaseModel):
    job_id: str | None
    status: str
    started_at: str | None = None
    finished_at: str | None = None
    return_code: int | None = None
    recent_logs: list[str] = Field(default_factory=list)
    database_overview: dict[str, object] | None = None
