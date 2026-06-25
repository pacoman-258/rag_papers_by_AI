from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


Provider = Literal["ollama", "openai_compatible", "google_translate"]
ModelListKind = Literal["chat", "embedding"]
AnswerLanguage = Literal["zh", "en"]
PaperReaderMode = Literal["guided", "standard"]
PaperReaderDiscipline = Literal[
    "general",
    "science_engineering",
    "mathematics",
    "medicine_biology",
    "economics_social_science",
    "philosophy_humanities",
    "policy_law",
]
PaperReaderDisciplineRequest = Literal[
    "auto",
    "general",
    "science_engineering",
    "mathematics",
    "medicine_biology",
    "economics_social_science",
    "philosophy_humanities",
    "policy_law",
]


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


class PaperReaderChatConfigRequest(ChatConfigRequest):
    max_context_tokens: int = Field(default=8192, ge=1)


class PaperReaderChatConfigResponse(ChatConfigResponse):
    max_context_tokens: int = Field(default=8192, ge=1)


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
    research_profile_enabled: bool = True


class RuntimeSettingsRequest(BaseModel):
    query_chat: ChatConfigRequest
    answer_chat: ChatConfigRequest
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
    paper_reader_chat: PaperReaderChatConfigResponse
    paper_reader_translation: ChatConfigResponse
    citation_trace_main_chat: ChatConfigResponse
    citation_trace_worker_chat: ChatConfigResponse
    embedding: EmbeddingConfigModel
    retrieval: RetrievalConfigModel
    rerank: RerankConfigResponse
    assistant_memory: AssistantMemoryConfigModel


class PaperReaderSessionFromArxivRequest(BaseModel):
    url: str
    answer_language: AnswerLanguage | None = None
    reader_mode: PaperReaderMode = "guided"
    discipline: PaperReaderDisciplineRequest = "auto"
    settings: RuntimeSettingsRequest | None = None


class PaperReaderHistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    text: str


class PaperReaderCitationModel(BaseModel):
    chunk_id: str
    section_title: str
    subsection_title: str | None = None
    page_start: int
    page_end: int
    excerpt: str | None = None
    score: float | None = None


class PaperReaderChunkModel(BaseModel):
    chunk_id: str
    section_title: str
    subsection_title: str | None = None
    page_start: int
    page_end: int
    text: str
    token_estimate: int
    score: float | None = None


class PaperReaderUsedChunkModel(PaperReaderChunkModel):
    pass


class PaperReaderIndexNodeModel(BaseModel):
    node_id: str
    title: str
    summary: str | None = None
    reading_focus_key: str | None = None
    page_start: int = 0
    page_end: int = 0
    page_indices: list[int] = Field(default_factory=list)
    chunk_ids: list[str] = Field(default_factory=list)
    children: list["PaperReaderIndexNodeModel"] = Field(default_factory=list)


class PaperReaderSelectedNodeModel(BaseModel):
    node_id: str
    title: str
    summary: str | None = None
    page_start: int = 0
    page_end: int = 0
    page_indices: list[int] = Field(default_factory=list)
    reason: str | None = None


class PaperReaderPageManifestModel(BaseModel):
    page_index: int
    title: str
    status: Literal["queued", "generating", "ready", "error"]
    estimated_tokens: int
    chunk_count: int
    page_start: int
    page_end: int
    source_node_ids: list[str] = Field(default_factory=list)


class PaperReaderSectionModel(BaseModel):
    title: str
    text: str | None = None
    bullets: list[str] = Field(default_factory=list)


class PaperReaderStructuredTextModel(BaseModel):
    original_en: str | None = None
    explanation: str | None = None
    display_text: str | None = None


class PaperReaderReadingBlockModel(BaseModel):
    chunk_id: str
    source_label: str
    page_start: int
    page_end: int
    original_en: str
    explanation: str | None = None
    display_text: str | None = None


class PaperReaderSourceTextSpanModel(BaseModel):
    text: str
    x: float
    y: float
    font_size: float
    font_weight: str = "400"
    font_style: str = "normal"


class PaperReaderSourcePageModel(BaseModel):
    page_number: int
    text: str
    width: float | None = None
    height: float | None = None
    spans: list[PaperReaderSourceTextSpanModel] = Field(default_factory=list)


class PaperReaderSourcePagesResponse(BaseModel):
    session_id: str
    reader_page_index: int
    page_start: int
    page_end: int
    pages: list[PaperReaderSourcePageModel] = Field(default_factory=list)


class PaperReaderSelectionTranslateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=12000)
    answer_language: AnswerLanguage | None = None
    settings: RuntimeSettingsRequest | None = None


class PaperReaderSelectionTranslateResponse(BaseModel):
    session_id: str | None = None
    source_text: str
    translation: str


class PaperReaderSourceSectionModel(BaseModel):
    title: str
    subsection_title: str | None = None
    label: str
    page_start: int
    page_end: int
    chunk_ids: list[str] = Field(default_factory=list)


class PaperReaderStructuredStatusModel(BaseModel):
    state: Literal["pending", "ready", "repaired", "failed"] = "pending"
    format: str = "insight_cards_v1"
    message: str | None = None
    repair_attempted: bool = False


class PaperReaderInsightModel(BaseModel):
    insight_id: str
    title: str
    kind: str = "insight"
    summary: PaperReaderStructuredTextModel | None = None
    evidence: list[PaperReaderStructuredTextModel] = Field(default_factory=list)
    why_it_matters: list[PaperReaderStructuredTextModel] = Field(default_factory=list)
    source_chunk_ids: list[str] = Field(default_factory=list)
    source_section_labels: list[str] = Field(default_factory=list)
    citations: list[PaperReaderCitationModel] = Field(default_factory=list)


class PaperReaderStoryStageModel(BaseModel):
    key: str
    title: str
    description: str | None = None


class PaperReaderBlackboardNotesModel(BaseModel):
    core_concepts: list[str] = Field(default_factory=list)
    method_steps: list[str] = Field(default_factory=list)
    experiment_takeaways: list[str] = Field(default_factory=list)
    takeaway: str | None = None


class PaperReaderDisciplineGuidePanelModel(BaseModel):
    key: str
    title: str
    items: list[str] = Field(default_factory=list)
    takeaway: str | None = None


class PaperReaderDisciplineGuideModel(BaseModel):
    discipline: PaperReaderDiscipline
    title: str
    panels: list[PaperReaderDisciplineGuidePanelModel] = Field(default_factory=list)


class PaperReaderGlossaryTermModel(BaseModel):
    term: str
    explanation: str
    source: Literal["paper", "background"] = "paper"
    citation: PaperReaderCitationModel | None = None


class PaperReaderReadingHintModel(BaseModel):
    kind: Literal["must_know", "skim", "advanced"]
    text: str
    reason: str | None = None


class PaperReaderCheckpointModel(BaseModel):
    question: str
    answer: str
    review_hint: str | None = None
    source_page_index: int | None = None


class PaperReaderPageContentModel(BaseModel):
    page_index: int
    title: str
    status: Literal["queued", "generating", "ready", "error"]
    coverage: str | None = None
    page_overview: PaperReaderStructuredTextModel | None = None
    insights: list[PaperReaderInsightModel] = Field(default_factory=list)
    structured_status: PaperReaderStructuredStatusModel = Field(default_factory=PaperReaderStructuredStatusModel)
    reading_blocks: list[PaperReaderReadingBlockModel] = Field(default_factory=list)
    source_sections: list[PaperReaderSourceSectionModel] = Field(default_factory=list)
    mentor_script: list[PaperReaderStructuredTextModel] = Field(default_factory=list)
    blackboard_notes: PaperReaderBlackboardNotesModel | None = None
    discipline_guide: PaperReaderDisciplineGuideModel | None = None
    story_stage: PaperReaderStoryStageModel | None = None
    glossary_terms: list[PaperReaderGlossaryTermModel] = Field(default_factory=list)
    reading_hints: list[PaperReaderReadingHintModel] = Field(default_factory=list)
    checkpoints: list[PaperReaderCheckpointModel] = Field(default_factory=list)
    summary: str | None = None
    sections: list[PaperReaderSectionModel] = Field(default_factory=list)
    key_points: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    citations: list[PaperReaderCitationModel] = Field(default_factory=list)
    chunk_ids: list[str] = Field(default_factory=list)
    source_node_ids: list[str] = Field(default_factory=list)
    estimated_tokens: int = 0
    page_start: int = 0
    page_end: int = 0
    generated_at: str | None = None
    error: str | None = None


class PaperReaderSessionModel(BaseModel):
    session_id: str
    source_type: Literal["arxiv", "file"]
    source_url: str | None = None
    source_id: str | None = None
    paper_title: str
    authors: list[str] = Field(default_factory=list)
    published_date: str | None = None
    answer_language: AnswerLanguage
    reader_mode: PaperReaderMode = "guided"
    discipline: PaperReaderDiscipline = "general"
    discipline_source: Literal["auto", "manual"] = "auto"
    max_context_tokens: int
    page_input_budget: int
    current_page_index: int = 0
    page_count: int
    source_page_count: int | None = None
    session_status: str
    pages: list[PaperReaderPageManifestModel] = Field(default_factory=list)
    index_status: Literal["ready", "fallback"] = "fallback"
    index_tree: PaperReaderIndexNodeModel | None = None


class PaperReaderChatRequest(BaseModel):
    message: str
    history: list[PaperReaderHistoryMessage] = Field(default_factory=list)
    page_index: int | None = None
    answer_language: AnswerLanguage | None = None
    reader_mode: PaperReaderMode | None = None
    discipline: PaperReaderDisciplineRequest | None = None
    settings: RuntimeSettingsRequest | None = None


class PaperReaderChatResponse(BaseModel):
    session_id: str
    page_index: int
    page_title: str | None = None
    answer_text: str
    citations: list[PaperReaderCitationModel] = Field(default_factory=list)
    used_chunks: list[PaperReaderUsedChunkModel] = Field(default_factory=list)
    selected_nodes: list[PaperReaderSelectedNodeModel] = Field(default_factory=list)


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
    answer_language: AnswerLanguage
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


class CitationTraceSessionFromArxivRequest(BaseModel):
    url: str
    answer_language: AnswerLanguage | None = None
    settings: RuntimeSettingsRequest | None = None


class CitationTracePaperNodeModel(BaseModel):
    paper_id: str
    source: Literal["target", "arxiv", "local", "wos", "unresolved"]
    source_id: str
    canonical_id: str
    title: str
    abstract: str = ""
    authors: list[str] = Field(default_factory=list)
    published_date: str | None = None
    keywords: list[str] = Field(default_factory=list)
    arxiv_id: str | None = None
    doi: str | None = None
    external_url: str | None = None


class CitationTraceReferenceEntryModel(BaseModel):
    reference_id: str
    raw_text: str
    raw_label: str | None = None
    arxiv_id: str | None = None
    doi: str | None = None
    year: str | None = None
    title_hint: str | None = None


class CitationTraceScoreBreakdownModel(BaseModel):
    abstract_similarity: float = 0.0
    title_overlap: float = 0.0
    keyword_overlap: float = 0.0
    author_overlap: float = 0.0
    date_plausibility: float = 0.0
    reference_match: float = 0.0


class CitationTraceLedgerEntryModel(BaseModel):
    entry_id: str
    candidate_paper: CitationTracePaperNodeModel
    seed_paper: CitationTracePaperNodeModel | None
    round: int
    relation_type: Literal["explicit_reference", "retrieved_similar", "llm_inferred_influence"]
    evidence_level: Literal["strong", "medium", "weak"]
    score_total: float
    score_breakdown: CitationTraceScoreBreakdownModel
    reference_text: str | None = None
    metadata_evidence: list[str] = Field(default_factory=list)
    llm_assessment: str | None = None
    warnings: list[str] = Field(default_factory=list)


class CitationTraceRoundSummaryModel(BaseModel):
    round: int
    status: Literal["pending", "running", "completed", "partial", "failed"]
    seed_count: int = 0
    candidate_count: int = 0
    selected_count: int = 0
    summary_text: str | None = None
    seed_paper_ids: list[str] = Field(default_factory=list)
    ledger_entries: list[CitationTraceLedgerEntryModel] = Field(default_factory=list)
    top_papers: list["CitationTraceTopPaperModel"] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CitationTraceTopPaperModel(BaseModel):
    rank: int
    paper_id: str
    title: str
    influence_area: str
    reason: str
    evidence_level: Literal["strong", "medium", "weak"]
    is_explicitly_cited: bool
    is_exploratory: bool
    why_worth_reading: str
    uncertainty: str
    supporting_edge_ids: list[str] = Field(default_factory=list)


class CitationTraceSessionModel(BaseModel):
    session_id: str
    source_type: Literal["arxiv", "file"]
    source_id: str | None
    source_url: str | None
    target_paper: CitationTracePaperNodeModel
    answer_language: AnswerLanguage
    status: Literal["pending", "running", "completed", "partial", "failed"] = "pending"
    rounds: list[CitationTraceRoundSummaryModel] = Field(default_factory=list)
    ledger_entries: list[CitationTraceLedgerEntryModel] = Field(default_factory=list)
    final_top5: list[CitationTraceTopPaperModel] = Field(default_factory=list)
    reference_entries: list[CitationTraceReferenceEntryModel] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CitationTraceExecuteRequest(BaseModel):
    settings: RuntimeSettingsRequest | None = None


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
    answer_language: AnswerLanguage | None = None
    session_id: str | None = None
    source: str | None = None
    query: str | None = None
    answer_text: str | None = None
    paper_title: str | None = None
    arxiv_id: str | None = None
    page_language: AnswerLanguage | None = None
    reader_mode: PaperReaderMode | None = None
    discipline: PaperReaderDiscipline | None = None
    discipline_source: Literal["auto", "manual"] | None = None
    page_index: int | None = None
    page_title: str | None = None
    page_count: int | None = None
    story_stage: dict[str, Any] | None = None
    discipline_guide: dict[str, Any] | None = None
    blackboard_notes: dict[str, Any] | None = None
    glossary_terms: list[dict[str, Any]] = Field(default_factory=list)
    checkpoint_status: str | None = None
    section_titles: list[str] = Field(default_factory=list)
    latest_page_summary: str | None = None
    latest_answer_text: str | None = None
    question: str | None = None
    paper_ids: list[str] = Field(default_factory=list)
    paper_titles: list[str] = Field(default_factory=list)
    target_paper_id: str | None = None
    applied_constraints: RetrievalConstraintsModel | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PaperReaderAssistantContextResponse(BaseModel):
    session_id: str
    answer_context: str
    workflow_context: WorkflowContextModel


class UsedMemoryItemModel(BaseModel):
    memory_id: str
    summary: str
    memory_type: str | None = None
    score: float | None = None
    pinned: bool = False


class Live2DChatRequest(BaseModel):
    source: Literal["user", "qa_auto", "citation_trace_auto"]
    message: str = ""
    language: AnswerLanguage | None = None
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


class ResearchProfileItemModel(BaseModel):
    memory_id: str
    kind: Literal["expertise_signal", "research_direction", "reading_preference"]
    label: str
    confidence: float | None = None
    evidence: list[str] = Field(default_factory=list)
    pinned: bool = False
    created_at: str | None = None
    updated_at: str | None = None


class ResearchProfileResponse(BaseModel):
    session_id: str
    enabled: bool = True
    available: bool = True
    notice: str | None = None
    items: list[ResearchProfileItemModel] = Field(default_factory=list)


class ResearchProfileRefreshRequest(BaseModel):
    session_id: str | None = None


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
