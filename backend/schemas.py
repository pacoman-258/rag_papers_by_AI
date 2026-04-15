from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


Provider = Literal["ollama", "openai_compatible"]
ModelListKind = Literal["chat", "embedding"]


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


class RetrievalProvidersModel(BaseModel):
    local: bool = True
    arxiv: bool = True
    wos: bool = False


class RetrievalConfigRequest(BaseModel):
    top_k: int = Field(ge=1)
    top_n: int = Field(ge=1)
    request_timeout: int = Field(ge=1)
    providers: RetrievalProvidersModel | None = None


class RetrievalConfigModel(BaseModel):
    top_k: int = Field(ge=1)
    top_n: int = Field(ge=1)
    request_timeout: int = Field(ge=1)
    providers: RetrievalProvidersModel = Field(default_factory=RetrievalProvidersModel)


class RerankConfigRequest(BaseModel):
    base_url: str
    model: str
    api_key: str | None = None
    clear_api_key: bool = False


class RerankConfigResponse(BaseModel):
    base_url: str
    model: str
    has_api_key: bool


class AssistantMemoryConfigModel(BaseModel):
    enabled: bool = True
    summary_interval_turns: int = Field(default=6, ge=1)
    major_summary_group_size: int = Field(default=3, ge=1)
    max_recall_items: int = Field(default=5, ge=1)
    recall_threshold: float = Field(default=0.72, ge=0.0, le=1.0)
    auto_save_enabled: bool = True


class RuntimeSettingsRequest(BaseModel):
    query_chat: ChatConfigRequest
    answer_chat: ChatConfigRequest
    embedding: EmbeddingConfigModel
    retrieval: RetrievalConfigRequest
    rerank: RerankConfigRequest
    assistant_memory: AssistantMemoryConfigModel | None = None


class RuntimeSettingsResponse(BaseModel):
    query_chat: ChatConfigResponse
    answer_chat: ChatConfigResponse
    embedding: EmbeddingConfigModel
    retrieval: RetrievalConfigModel
    rerank: RerankConfigResponse
    assistant_memory: AssistantMemoryConfigModel


class ModelListRequest(BaseModel):
    provider: Provider
    base_url: str | None = None
    api_key: str | None = None
    clear_api_key: bool = False
    kind: ModelListKind


class ModelListResponse(BaseModel):
    models: list[str] = Field(default_factory=list)
    provider: Provider


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


class TargetPaperModel(BaseModel):
    id: str
    source: str
    source_id: str
    canonical_id: str
    title: str
    summary: str
    authors: list[str] = Field(default_factory=list)
    published_date: str | None = None
    primary_category: str | None = None
    arxiv_id: str | None = None
    external_url: str | None = None
    matched_sources: list[str] = Field(default_factory=list)


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
    source: str
    source_id: str
    canonical_id: str
    title: str
    text: str
    method: str
    initial_score: float
    rerank_score: float
    authors: list[str] = Field(default_factory=list)
    published_date: str | None = None
    primary_category: str | None = None
    external_url: str | None = None
    arxiv_id: str | None = None
    matched_sources: list[str] = Field(default_factory=list)


class SearchExecuteResponse(BaseModel):
    search_id: str
    answer_language: Literal["zh", "en"]
    retrieval_text: str
    papers: list[RankedPaperResponse]
    warnings: list[str]
    applied_constraints: RetrievalConstraintsModel
    corpus_latest_date: str | None = None
    retrieval_sources: list[str] = Field(default_factory=list)
    source_freshness: dict[str, str | None] = Field(default_factory=dict)


class TraceResolveRequest(BaseModel):
    query: str


class TraceResolveResponse(BaseModel):
    status: Literal["resolved", "ambiguous", "not_found"]
    query: str
    resolved_target: TargetPaperModel | None = None
    candidates: list[TargetPaperModel] = Field(default_factory=list)
    message: str | None = None


class TraceExecuteRequest(BaseModel):
    target_id: str
    answer_language: Literal["zh", "en"] | None = None
    settings: RuntimeSettingsRequest | None = None


class TraceExecuteResponse(BaseModel):
    trace_id: str
    answer_language: Literal["zh", "en"]
    retrieval_text: str
    target_paper: TargetPaperModel
    papers: list[RankedPaperResponse]
    warnings: list[str]
    retrieval_sources: list[str] = Field(default_factory=list)
    source_freshness: dict[str, str | None] = Field(default_factory=dict)


class IngestJobResponse(BaseModel):
    job_id: str | None
    status: str
    started_at: str | None = None
    finished_at: str | None = None
    return_code: int | None = None
    recent_logs: list[str] = Field(default_factory=list)
    database_overview: dict[str, object] | None = None


class Live2DBootstrapResponse(BaseModel):
    model_url: str
    available_expressions: list[str] = Field(default_factory=list)
    default_expression: str | None = None
    default_voice: str
    tts_enabled: bool
    position: Literal["bottom-right"]


class Live2DHistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    text: str


class WorkflowContextModel(BaseModel):
    kind: str | None = None
    query: str | None = None
    answer_text: str | None = None
    paper_ids: list[str] = Field(default_factory=list)
    paper_titles: list[str] = Field(default_factory=list)
    target_paper_id: str | None = None
    applied_constraints: RetrievalConstraintsModel | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class UsedMemoryItemModel(BaseModel):
    memory_id: str
    summary: str
    memory_type: str | None = None
    score: float | None = None
    pinned: bool = False


class Live2DChatRequest(BaseModel):
    source: Literal["user", "qa_auto", "pst_auto"]
    message: str = ""
    history: list[Live2DHistoryMessage] = Field(default_factory=list)
    session_id: str | None = None
    workflow_context: WorkflowContextModel | None = None
    answer_context: str | None = None


class Live2DChatResponse(BaseModel):
    reply_text: str
    expression: str | None = None
    speak_text: str
    session_id: str
    memory_used: bool = False
    memory_notice: str | None = None
    used_memory_items: list[UsedMemoryItemModel] = Field(default_factory=list)


class AssistantMemoryItemModel(BaseModel):
    memory_id: str
    summary: str
    memory_type: str | None = None
    pinned: bool = False
    score: float | None = None
    created_at: str | None = None
    updated_at: str | None = None


class AssistantMemoryListResponse(BaseModel):
    session_id: str
    items: list[AssistantMemoryItemModel] = Field(default_factory=list)


class AssistantMemoryPinRequest(BaseModel):
    pinned: bool = True


class AssistantMemoryPinResponse(BaseModel):
    session_id: str
    memory_id: str
    pinned: bool


class AssistantMemoryDeleteResponse(BaseModel):
    session_id: str
    memory_id: str
    deleted: bool


class Live2DTTSRequest(BaseModel):
    text: str
    voice: str | None = None
    rate: str | None = None


class Live2DTTSResponse(BaseModel):
    audio_url: str
    duration_ms: int
    media_type: str
