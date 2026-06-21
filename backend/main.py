from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from threading import RLock

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from backend import citation_trace_service
from backend.config_store import (
    current_retrieval_providers,
    load_runtime_settings,
    merge_runtime_settings,
    merge_retrieval_providers,
    retrieval_providers_to_source_list,
    runtime_settings_to_response,
    save_runtime_settings,
    validate_retrieval_providers,
)
from backend.live2d_service import (
    delete_live2d_memory_item,
    generate_live2d_reply,
    get_live2d_audio,
    get_live2d_bootstrap_payload,
    list_live2d_memory_items,
    pin_live2d_memory_item,
    synthesize_live2d_tts,
)
from backend.paper_reader_service import (
    chat_with_paper,
    create_session_from_arxiv,
    create_session_from_pdf_bytes,
    get_page_content,
    get_session,
    get_session_pdf_path,
    get_session_settings,
    get_source_pages_for_reader_page,
    get_source_page_pdf_path,
    page_content_to_model,
    session_to_model,
    translate_selected_text,
)
from backend.ingest_manager import IngestManager
from backend.schemas import (
    AssistantMemoryDeleteResponse,
    AssistantMemoryItemModel,
    AssistantMemoryListResponse,
    AssistantMemoryPinRequest,
    AssistantMemoryPinResponse,
    CitationTraceExecuteRequest,
    CitationTraceSessionFromArxivRequest,
    CitationTraceSessionModel,
    IngestJobResponse,
    Live2DBootstrapResponse,
    Live2DChatRequest,
    Live2DChatResponse,
    Live2DTTSRequest,
    Live2DTTSResponse,
    ModelListRequest,
    ModelListResponse,
    PaperReaderChatRequest,
    PaperReaderChatResponse,
    PaperReaderPageContentModel,
    PaperReaderSelectionTranslateRequest,
    PaperReaderSelectionTranslateResponse,
    PaperReaderSessionFromArxivRequest,
    PaperReaderSessionModel,
    PaperReaderSourcePagesResponse,
    QueryPlanModel,
    RetrievalConstraintsModel,
    SearchExecuteRequest,
    SearchExecuteResponse,
    SearchPlanRequest,
    SearchRefineRequest,
    RankedPaperResponse,
    RuntimeSettingsRequest,
    RuntimeSettingsResponse,
    UsedMemoryItemModel,
)
from local_paper_db.app.search_service import (
    QueryPlan,
    RetrievalConstraints,
    SearchExecution,
    execute_search,
    get_database_overview,
    list_available_models,
    normalize_openai_compatible_base_url,
    plan_query,
    revise_query_plan,
    stream_answer_tokens,
    validate_runtime_settings,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"
FRONTEND_LIVE2D_DIST = FRONTEND_DIST / "live2d"


def sse_event(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


_RETRIEVAL_SOURCE_LOCK = RLock()


def retrieval_sources_from_settings(settings: RuntimeSettingsRequest | None) -> list[str]:
    base_providers = current_retrieval_providers()
    incoming_providers = settings.retrieval.providers if settings is not None else None
    providers = merge_retrieval_providers(base_providers, incoming_providers)
    validate_retrieval_providers(providers)
    return retrieval_providers_to_source_list(providers)


@contextmanager
def use_retrieval_sources(sources: list[str]):
    with _RETRIEVAL_SOURCE_LOCK:
        previous = os.environ.get("RETRIEVAL_ENABLED_SOURCES")
        os.environ["RETRIEVAL_ENABLED_SOURCES"] = ",".join(sources)
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop("RETRIEVAL_ENABLED_SOURCES", None)
            else:
                os.environ["RETRIEVAL_ENABLED_SOURCES"] = previous


def to_http_detail(exc: Exception) -> HTTPException:
    message = str(exc) or exc.__class__.__name__
    lowered = message.lower()
    if "not found" in lowered or "no relevant papers" in lowered or "no prior paper candidates" in lowered:
        return HTTPException(status_code=404, detail=message)
    if isinstance(exc, (ValueError, RuntimeError)):
        return HTTPException(status_code=400, detail=message)
    return HTTPException(status_code=502, detail=message)


@contextmanager
def retrieval_runtime_scope(payload_settings: RuntimeSettingsRequest | None):
    with _RETRIEVAL_SOURCE_LOCK:
        settings, sources = prepare_runtime_settings(payload_settings)
        with use_retrieval_sources(sources):
            yield settings, sources


app = FastAPI(title="arxiv-paper-rag")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ingest_manager = IngestManager(REPO_ROOT)
search_sessions: dict[str, tuple[SearchExecution, Any]] = {}


def normalize_session_id(raw_session_id: str | None) -> str:
    value = str(raw_session_id or "").strip()
    return value or uuid.uuid4().hex


def require_session_id(raw_session_id: str | None) -> str:
    value = str(raw_session_id or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="session_id is required.")
    return value


def compose_answer_context(payload: Live2DChatRequest) -> str | None:
    explicit = str(payload.answer_context or "").strip()
    if explicit:
        return explicit
    context = payload.workflow_context
    if context is None:
        return None
    if context.answer_text and context.answer_text.strip():
        return context.answer_text.strip()
    context_payload = context.model_dump(exclude_none=True)
    if not context_payload:
        return None
    return json.dumps(context_payload, ensure_ascii=False)


def coerce_used_memory_items(raw_items: Any) -> list[UsedMemoryItemModel]:
    if not isinstance(raw_items, list):
        return []
    items: list[UsedMemoryItemModel] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        memory_id = str(raw.get("memory_id") or raw.get("id") or "").strip()
        summary = str(raw.get("summary") or raw.get("text") or "").strip()
        if not memory_id or not summary:
            continue
        item = UsedMemoryItemModel(
            memory_id=memory_id,
            summary=summary,
            memory_type=(str(raw.get("memory_type")).strip() or None) if raw.get("memory_type") is not None else None,
            score=float(raw["score"]) if isinstance(raw.get("score"), (float, int)) else None,
            pinned=bool(raw.get("pinned", False)),
        )
        items.append(item)
    return items


def coerce_memory_list_items(raw_items: Any) -> list[AssistantMemoryItemModel]:
    if not isinstance(raw_items, list):
        return []
    items: list[AssistantMemoryItemModel] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        memory_id = str(raw.get("memory_id") or raw.get("id") or "").strip()
        summary = str(raw.get("summary") or raw.get("text") or "").strip()
        if not memory_id or not summary:
            continue
        items.append(
            AssistantMemoryItemModel(
                memory_id=memory_id,
                summary=summary,
                memory_type=(str(raw.get("memory_type")).strip() or None)
                if raw.get("memory_type") is not None
                else None,
                pinned=bool(raw.get("pinned", False)),
                score=float(raw["score"]) if isinstance(raw.get("score"), (float, int)) else None,
                created_at=(str(raw.get("created_at")).strip() or None) if raw.get("created_at") is not None else None,
                updated_at=(str(raw.get("updated_at")).strip() or None) if raw.get("updated_at") is not None else None,
            )
        )
    return items


def constraints_model_to_dataclass(model: RetrievalConstraintsModel | None) -> RetrievalConstraints:
    if model is None:
        return RetrievalConstraints()
    return RetrievalConstraints(
        published_after=model.published_after,
        published_before=model.published_before,
        authors=list(model.authors),
        primary_categories=list(model.primary_categories),
        sort_hint=model.sort_hint,
        is_implicit_latest=model.is_implicit_latest,
    )


def query_plan_model_to_dataclass(model: QueryPlanModel | None) -> QueryPlan | None:
    if model is None:
        return None
    return QueryPlan(
        answer_language=model.answer_language,
        intent_summary=model.intent_summary,
        retrieval_query_en=model.retrieval_query_en,
        keywords_en=list(model.keywords_en),
        constraints=constraints_model_to_dataclass(model.constraints),
        corpus_latest_date=model.corpus_latest_date,
    )


def citation_trace_session_to_model(
    session: citation_trace_service.CitationTraceSession,
) -> CitationTraceSessionModel:
    return CitationTraceSessionModel.model_validate(asdict(session))


def prepare_runtime_settings(payload_settings: RuntimeSettingsRequest | None) -> tuple[Any, list[str]]:
    base = load_runtime_settings()
    settings = merge_runtime_settings(base, payload_settings)
    sources = retrieval_sources_from_settings(payload_settings)
    validate_runtime_settings(settings)
    return settings, sources


def resolve_saved_model_list_api_key(payload: ModelListRequest) -> str | None:
    if payload.provider != "openai_compatible" or payload.api_key or payload.clear_api_key:
        return payload.api_key

    saved_settings = load_runtime_settings()
    requested_base_url = normalize_openai_compatible_base_url(payload.base_url)
    for chat_config in (
        saved_settings.query_chat,
        saved_settings.answer_chat,
        saved_settings.paper_reader_chat,
        saved_settings.paper_reader_translation,
    ):
        if chat_config.provider != "openai_compatible":
            continue
        if normalize_openai_compatible_base_url(chat_config.base_url) == requested_base_url and chat_config.api_key:
            return chat_config.api_key
    return None


def settings_from_optional_payload(
    payload_settings: RuntimeSettingsRequest | None = None,
    *,
    session_id: str | None = None,
) -> Any:
    if payload_settings is not None:
        settings, _sources = prepare_runtime_settings(payload_settings)
        return settings
    if session_id:
        return get_session_settings(session_id)
    settings, _sources = prepare_runtime_settings(None)
    return settings


def parse_runtime_settings_form(raw_settings: str | None) -> RuntimeSettingsRequest | None:
    text = str(raw_settings or "").strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
        if not payload:
            return None
        return RuntimeSettingsRequest.model_validate(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid paper reader settings payload: {exc}") from exc


def detail_from_exception(exc: Exception) -> str:
    if getattr(exc, "args", None):
        first = exc.args[0]
        if isinstance(first, str) and first.strip():
            return first
    return str(exc)


@app.get("/api/config", response_model=RuntimeSettingsResponse)
def get_config() -> RuntimeSettingsResponse:
    return runtime_settings_to_response(load_runtime_settings())


@app.put("/api/config", response_model=RuntimeSettingsResponse)
def put_config(payload: RuntimeSettingsRequest) -> RuntimeSettingsResponse:
    try:
        base = load_runtime_settings()
        base_providers = current_retrieval_providers()
        merged = merge_runtime_settings(base, payload)
        merged_providers = merge_retrieval_providers(base_providers, payload.retrieval.providers)
        validate_runtime_settings(merged)
        validate_retrieval_providers(merged_providers)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    saved = save_runtime_settings(merged, retrieval_providers=merged_providers)
    return runtime_settings_to_response(saved)


@app.post("/api/models/list", response_model=ModelListResponse)
def api_list_models(payload: ModelListRequest) -> ModelListResponse:
    try:
        models = list_available_models(
            provider=payload.provider,
            base_url=payload.base_url,
            api_key=resolve_saved_model_list_api_key(payload),
            kind=payload.kind,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ModelListResponse(models=models, provider=payload.provider)


@app.post("/api/search/plan", response_model=QueryPlanModel)
def api_plan_query(payload: SearchPlanRequest) -> QueryPlanModel:
    try:
        with retrieval_runtime_scope(payload.settings) as (settings, _sources):
            plan = plan_query(payload.question, settings)
        return QueryPlanModel(**asdict(plan))
    except HTTPException:
        raise
    except Exception as exc:
        raise to_http_detail(exc) from exc


@app.post("/api/paper-reader/session/from-arxiv", response_model=PaperReaderSessionModel)
def api_paper_reader_session_from_arxiv(
    payload: PaperReaderSessionFromArxivRequest,
) -> PaperReaderSessionModel:
    try:
        settings = settings_from_optional_payload(payload.settings)
        session = create_session_from_arxiv(
            payload.url,
            settings,
            answer_language=payload.answer_language,
            reader_mode=payload.reader_mode,
            discipline=payload.discipline,
        )
        return session_to_model(session)
    except HTTPException:
        raise
    except Exception as exc:
        raise to_http_detail(exc) from exc


@app.post("/api/paper-reader/session/from-file", response_model=PaperReaderSessionModel)
async def api_paper_reader_session_from_file(
    pdf: UploadFile = File(...),
    answer_language: str | None = Form(default=None),
    reader_mode: str | None = Form(default="guided"),
    discipline: str | None = Form(default="auto"),
    settings: str | None = Form(default=None),
) -> PaperReaderSessionModel:
    filename = str(pdf.filename or "uploaded.pdf").strip() or "uploaded.pdf"
    content_type = str(pdf.content_type or "").strip().lower()
    if content_type not in {"", "application/pdf"} and not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported.")

    try:
        payload_settings = parse_runtime_settings_form(settings)
        resolved_settings = settings_from_optional_payload(payload_settings)
        session = create_session_from_pdf_bytes(
            await pdf.read(),
            filename,
            resolved_settings,
            answer_language=answer_language,
            reader_mode=reader_mode,
            discipline=discipline,
        )
        return session_to_model(session)
    except HTTPException:
        raise
    except Exception as exc:
        raise to_http_detail(exc) from exc
    finally:
        await pdf.close()


@app.get("/api/paper-reader/session/{session_id}", response_model=PaperReaderSessionModel)
def api_paper_reader_session(session_id: str) -> PaperReaderSessionModel:
    try:
        return session_to_model(get_session(session_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=detail_from_exception(exc)) from exc
    except Exception as exc:
        raise to_http_detail(exc) from exc


@app.get("/api/paper-reader/session/{session_id}/pdf")
def api_paper_reader_pdf(session_id: str) -> FileResponse:
    try:
        pdf_path = get_session_pdf_path(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=detail_from_exception(exc)) from exc
    except Exception as exc:
        raise to_http_detail(exc) from exc
    if not pdf_path.exists() or not pdf_path.is_file():
        raise HTTPException(status_code=404, detail="Paper reader PDF file not found.")
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=pdf_path.name or "paper.pdf",
        content_disposition_type="inline",
    )


@app.get("/api/paper-reader/session/{session_id}/source-pages/{page_number}/pdf")
def api_paper_reader_source_page_pdf(session_id: str, page_number: int) -> FileResponse:
    try:
        pdf_path = get_source_page_pdf_path(session_id, page_number)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=detail_from_exception(exc)) from exc
    except IndexError as exc:
        raise HTTPException(status_code=404, detail=detail_from_exception(exc)) from exc
    except Exception as exc:
        raise to_http_detail(exc) from exc
    if not pdf_path.exists() or not pdf_path.is_file():
        raise HTTPException(status_code=404, detail="Paper reader source page PDF file not found.")
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=pdf_path.name or f"page-{page_number}.pdf",
        content_disposition_type="inline",
    )


@app.get("/api/paper-reader/session/{session_id}/pages/{page_index}", response_model=PaperReaderPageContentModel)
def api_paper_reader_page(session_id: str, page_index: int) -> PaperReaderPageContentModel:
    try:
        return page_content_to_model(get_page_content(session_id, page_index))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=detail_from_exception(exc)) from exc
    except IndexError as exc:
        raise HTTPException(status_code=404, detail=detail_from_exception(exc)) from exc
    except Exception as exc:
        raise to_http_detail(exc) from exc


@app.get("/api/paper-reader/session/{session_id}/pages/{page_index}/source", response_model=PaperReaderSourcePagesResponse)
def api_paper_reader_source_pages(session_id: str, page_index: int) -> PaperReaderSourcePagesResponse:
    try:
        return get_source_pages_for_reader_page(session_id, page_index)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=detail_from_exception(exc)) from exc
    except IndexError as exc:
        raise HTTPException(status_code=404, detail=detail_from_exception(exc)) from exc
    except Exception as exc:
        raise to_http_detail(exc) from exc


@app.get("/api/paper-reader/session/{session_id}/pages/{page_index}/stream")
def api_paper_reader_page_stream(session_id: str, page_index: int) -> StreamingResponse:
    try:
        final_page = page_content_to_model(get_page_content(session_id, page_index))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=detail_from_exception(exc)) from exc
    except IndexError as exc:
        raise HTTPException(status_code=404, detail=detail_from_exception(exc)) from exc
    except Exception as exc:
        raise to_http_detail(exc) from exc

    def event_generator():
        yield sse_event("message", final_page.model_dump())
        yield sse_event("complete", {"page_index": page_index})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/paper-reader/session/{session_id}/chat", response_model=PaperReaderChatResponse)
def api_paper_reader_chat(session_id: str, payload: PaperReaderChatRequest) -> PaperReaderChatResponse:
    try:
        settings = settings_from_optional_payload(payload.settings, session_id=session_id)
        return chat_with_paper(session_id, payload, settings)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=detail_from_exception(exc)) from exc
    except IndexError as exc:
        raise HTTPException(status_code=404, detail=detail_from_exception(exc)) from exc
    except Exception as exc:
        raise to_http_detail(exc) from exc


@app.post(
    "/api/paper-reader/session/{session_id}/translate-selection",
    response_model=PaperReaderSelectionTranslateResponse,
)
def api_paper_reader_translate_selection(
    session_id: str,
    payload: PaperReaderSelectionTranslateRequest,
) -> PaperReaderSelectionTranslateResponse:
    try:
        settings = settings_from_optional_payload(payload.settings, session_id=session_id)
        return translate_selected_text(session_id, payload, settings)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=detail_from_exception(exc)) from exc
    except Exception as exc:
        raise to_http_detail(exc) from exc


@app.post("/api/search/plan/refine", response_model=QueryPlanModel)
def api_refine_query(payload: SearchRefineRequest) -> QueryPlanModel:
    try:
        with retrieval_runtime_scope(payload.settings) as (settings, _sources):
            plan = revise_query_plan(
                payload.question,
                previous_plan=query_plan_model_to_dataclass(payload.previous_plan),
                feedback=payload.feedback,
                settings=settings,
            )
        return QueryPlanModel(**asdict(plan))
    except HTTPException:
        raise
    except Exception as exc:
        raise to_http_detail(exc) from exc


@app.post("/api/search/execute", response_model=SearchExecuteResponse)
def api_execute_search(payload: SearchExecuteRequest) -> SearchExecuteResponse:
    try:
        with retrieval_runtime_scope(payload.settings) as (settings, _sources):
            execution = execute_search(
                original_query=payload.question,
                retrieval_text=payload.retrieval_text,
                query_plan=query_plan_model_to_dataclass(payload.query_plan),
                settings=settings,
            )
        search_id = uuid.uuid4().hex
        search_sessions[search_id] = (execution, settings)
        return SearchExecuteResponse(
            search_id=search_id,
            answer_language=execution.answer_language,
            retrieval_text=execution.retrieval_text,
            papers=[RankedPaperResponse(**asdict(paper)) for paper in execution.papers],
            warnings=execution.warnings,
            applied_constraints=RetrievalConstraintsModel(**asdict(execution.applied_constraints)),
            corpus_latest_date=execution.corpus_latest_date,
            retrieval_sources=list(execution.retrieval_sources),
            source_freshness=dict(execution.source_freshness),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise to_http_detail(exc) from exc


@app.post("/api/citation-trace/session/from-arxiv", response_model=CitationTraceSessionModel)
def api_create_citation_trace_session_from_arxiv(
    payload: CitationTraceSessionFromArxivRequest,
) -> CitationTraceSessionModel:
    try:
        with retrieval_runtime_scope(payload.settings) as (settings, _sources):
            session = citation_trace_service.create_session_from_arxiv(
                payload.url,
                settings,
                payload.answer_language,
            )
        return citation_trace_session_to_model(session)
    except HTTPException:
        raise
    except Exception as exc:
        raise to_http_detail(exc) from exc


@app.post("/api/citation-trace/session/from-file", response_model=CitationTraceSessionModel)
async def api_create_citation_trace_session_from_file(
    file: UploadFile = File(...),
    answer_language: str | None = Form(default=None),
    settings: str | None = Form(default=None),
) -> CitationTraceSessionModel:
    filename = str(file.filename or "paper.pdf").strip() or "paper.pdf"
    try:
        payload_settings = parse_runtime_settings_form(settings)
        with retrieval_runtime_scope(payload_settings) as (runtime_settings, _sources):
            session = citation_trace_service.create_session_from_pdf_bytes(
                filename,
                await file.read(),
                runtime_settings,
                answer_language,
            )
        return citation_trace_session_to_model(session)
    except HTTPException:
        raise
    except Exception as exc:
        raise to_http_detail(exc) from exc
    finally:
        await file.close()


@app.get("/api/citation-trace/session/{session_id}", response_model=CitationTraceSessionModel)
def api_get_citation_trace_session(session_id: str) -> CitationTraceSessionModel:
    try:
        return citation_trace_session_to_model(citation_trace_service.get_session(session_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=detail_from_exception(exc)) from exc


@app.post("/api/citation-trace/session/{session_id}/execute", response_model=CitationTraceSessionModel)
def api_execute_citation_trace_session(
    session_id: str,
    payload: CitationTraceExecuteRequest | None = None,
) -> CitationTraceSessionModel:
    try:
        session = citation_trace_service.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=detail_from_exception(exc)) from exc
    try:
        payload_settings = payload.settings if payload is not None else None
        with retrieval_runtime_scope(payload_settings) as (settings, _sources):
            for _event, _data in citation_trace_service.run_citation_trace_events(session, settings):
                pass
        return citation_trace_session_to_model(session)
    except HTTPException:
        raise
    except Exception as exc:
        raise to_http_detail(exc) from exc


@app.get("/api/citation-trace/session/{session_id}/stream")
def api_stream_citation_trace_session(session_id: str) -> StreamingResponse:
    try:
        session = citation_trace_service.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=detail_from_exception(exc)) from exc

    def event_generator():
        try:
            with retrieval_runtime_scope(None) as (settings, _sources):
                for event, data in citation_trace_service.run_citation_trace_events(session, settings):
                    yield sse_event(event, data)
        except Exception as exc:
            yield sse_event("error", {"message": str(exc)})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/search/{search_id}/answer/stream")
def api_stream_answer(search_id: str) -> StreamingResponse:
    session = search_sessions.get(search_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Search session not found.")

    execution, settings = session

    def event_generator():
        yield sse_event("start", {"search_id": search_id})
        try:
            for token in stream_answer_tokens(execution, settings):
                yield sse_event("token", {"content": token})
            yield sse_event("complete", {"search_id": search_id})
        except Exception as exc:
            yield sse_event("error", {"message": str(exc)})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/ingest/status", response_model=IngestJobResponse)
def api_ingest_status() -> IngestJobResponse:
    job = ingest_manager.get_status()
    overview = None
    try:
        overview = get_database_overview()
    except Exception as exc:
        overview = {"error": str(exc)}

    if job is None:
        return IngestJobResponse(
            job_id=None,
            status="idle",
            recent_logs=[],
            database_overview=overview,
        )

    return IngestJobResponse(
        job_id=job.job_id,
        status=job.status,
        started_at=job.started_at.isoformat() if job.started_at else None,
        finished_at=job.finished_at.isoformat() if job.finished_at else None,
        return_code=job.return_code,
        recent_logs=job.logs[-50:],
        database_overview=overview,
    )


@app.post("/api/ingest/run", response_model=IngestJobResponse)
def api_ingest_run() -> IngestJobResponse:
    try:
        job = ingest_manager.start()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return IngestJobResponse(
        job_id=job.job_id,
        status=job.status,
        started_at=job.started_at.isoformat(),
        recent_logs=[],
    )


@app.get("/api/ingest/{job_id}/logs/stream")
def api_ingest_logs(job_id: str) -> StreamingResponse:
    job = ingest_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Ingest job not found.")

    def event_generator():
        seen = 0
        while True:
            current_job = ingest_manager.get_job(job_id)
            if current_job is None:
                yield sse_event("error", {"message": "Ingest job not found."})
                return

            while seen < len(current_job.logs):
                yield sse_event("log", {"line": current_job.logs[seen]})
                seen += 1

            yield sse_event("status", {"status": current_job.status})

            if current_job.status in {"completed", "failed"}:
                yield sse_event(
                    "complete",
                    {
                        "status": current_job.status,
                        "return_code": current_job.return_code,
                    },
                )
                return

            time.sleep(0.5)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/live2d/bootstrap", response_model=Live2DBootstrapResponse)
def api_live2d_bootstrap() -> Live2DBootstrapResponse:
    return Live2DBootstrapResponse(**get_live2d_bootstrap_payload())


@app.post("/api/live2d/chat", response_model=Live2DChatResponse)
def api_live2d_chat(payload: Live2DChatRequest) -> Live2DChatResponse:
    settings = load_runtime_settings()
    validate_runtime_settings(settings)
    bootstrap = get_live2d_bootstrap_payload()
    workflow_context_data = (
        payload.workflow_context.model_dump(exclude_none=True)
        if payload.workflow_context is not None
        else None
    )
    session_id = normalize_session_id(payload.session_id)
    response = generate_live2d_reply(
        source=payload.source,
        message=payload.message,
        language=payload.language,
        history=[item.model_dump() for item in payload.history],
        answer_context=compose_answer_context(payload),
        workflow_context=workflow_context_data,
        session_id=session_id,
        settings=settings,
        available_expressions=list(bootstrap["available_expressions"]),
    )
    used_memory_items = coerce_used_memory_items(response.get("used_memory_items"))
    return Live2DChatResponse(
        reply_text=response["reply_text"],
        expression=response.get("expression"),
        speak_text=response["speak_text"],
        session_id=str(response.get("session_id") or session_id),
        memory_used=bool(response.get("memory_used")) or bool(used_memory_items),
        memory_notice=response.get("memory_notice"),
        used_memory_items=used_memory_items,
    )


@app.get("/api/live2d/memory", response_model=AssistantMemoryListResponse)
def api_live2d_memory_list(session_id: str) -> AssistantMemoryListResponse:
    resolved_session_id = require_session_id(session_id)
    try:
        raw_items = list_live2d_memory_items(
            session_id=resolved_session_id,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to list memory items: {exc}") from exc

    if isinstance(raw_items, dict):
        raw_items = raw_items.get("items")
    return AssistantMemoryListResponse(
        session_id=resolved_session_id,
        items=coerce_memory_list_items(raw_items),
    )


@app.post("/api/live2d/memory/{memory_id}/pin", response_model=AssistantMemoryPinResponse)
def api_live2d_memory_pin(
    memory_id: str,
    payload: AssistantMemoryPinRequest | None = None,
    session_id: str | None = None,
) -> AssistantMemoryPinResponse:
    normalized_memory_id = str(memory_id or "").strip()
    if not normalized_memory_id:
        raise HTTPException(status_code=400, detail="memory_id is required.")
    resolved_session_id = str(session_id or "").strip()
    pinned = True if payload is None else payload.pinned
    try:
        raw_result = pin_live2d_memory_item(
            memory_id=normalized_memory_id,
            pinned=pinned,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to pin memory item: {exc}") from exc

    if isinstance(raw_result, dict) and isinstance(raw_result.get("pinned"), bool):
        pinned = raw_result["pinned"]

    return AssistantMemoryPinResponse(
        session_id=resolved_session_id,
        memory_id=normalized_memory_id,
        pinned=pinned,
    )


@app.delete("/api/live2d/memory/{memory_id}", response_model=AssistantMemoryDeleteResponse)
def api_live2d_memory_delete(memory_id: str, session_id: str | None = None) -> AssistantMemoryDeleteResponse:
    normalized_memory_id = str(memory_id or "").strip()
    if not normalized_memory_id:
        raise HTTPException(status_code=400, detail="memory_id is required.")
    resolved_session_id = str(session_id or "").strip()
    try:
        raw_result = delete_live2d_memory_item(
            memory_id=normalized_memory_id,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to delete memory item: {exc}") from exc

    deleted = True
    if isinstance(raw_result, dict) and isinstance(raw_result.get("deleted"), bool):
        deleted = raw_result["deleted"]

    return AssistantMemoryDeleteResponse(
        session_id=resolved_session_id,
        memory_id=normalized_memory_id,
        deleted=deleted,
    )


@app.post("/api/live2d/tts", response_model=Live2DTTSResponse)
async def api_live2d_tts(payload: Live2DTTSRequest) -> Live2DTTSResponse:
    result = await synthesize_live2d_tts(
        text=payload.text,
        voice=payload.voice,
        rate=payload.rate,
    )
    return Live2DTTSResponse(
        audio_url=result["audio_url"],
        duration_ms=result["duration_ms"],
        media_type=result["media_type"],
    )


@app.get("/api/live2d/audio/{file_id}")
def api_live2d_audio(file_id: str) -> FileResponse:
    path, media_type = get_live2d_audio(file_id)
    return FileResponse(path, media_type=media_type)


if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")
    if FRONTEND_LIVE2D_DIST.exists():
        app.mount("/live2d", StaticFiles(directory=FRONTEND_LIVE2D_DIST), name="live2d")

    @app.api_route("/api/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    def api_fallback(full_path: str) -> None:
        raise HTTPException(status_code=404, detail="Not found.")

    @app.get("/")
    def root() -> FileResponse:
        return FileResponse(FRONTEND_DIST / "index.html")

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found.")
        return FileResponse(FRONTEND_DIST / "index.html")
