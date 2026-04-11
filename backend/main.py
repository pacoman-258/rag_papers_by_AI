from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from backend.config_store import (
    load_runtime_settings,
    merge_runtime_settings,
    runtime_settings_to_response,
    save_runtime_settings,
)
from backend.live2d_service import (
    generate_live2d_reply,
    get_live2d_audio,
    get_live2d_bootstrap_payload,
    synthesize_live2d_tts,
)
from backend.ingest_manager import IngestManager
from backend.schemas import (
    IngestJobResponse,
    Live2DBootstrapResponse,
    Live2DChatRequest,
    Live2DChatResponse,
    Live2DTTSRequest,
    Live2DTTSResponse,
    ModelListRequest,
    ModelListResponse,
    QueryPlanModel,
    RetrievalConstraintsModel,
    TargetPaperModel,
    SearchExecuteRequest,
    SearchExecuteResponse,
    SearchPlanRequest,
    SearchRefineRequest,
    TraceExecuteRequest,
    TraceExecuteResponse,
    TraceResolveRequest,
    TraceResolveResponse,
    RankedPaperResponse,
    RuntimeSettingsRequest,
    RuntimeSettingsResponse,
)
from local_paper_db.app.search_service import (
    QueryPlan,
    RetrievalConstraints,
    SearchExecution,
    TargetPaper,
    TraceExecution,
    execute_search,
    execute_trace,
    fetch_target_paper_by_id,
    get_database_overview,
    infer_user_language,
    list_available_models,
    normalize_openai_compatible_base_url,
    plan_query,
    resolve_target_paper,
    revise_query_plan,
    stream_answer_tokens,
    stream_trace_answer_tokens,
    validate_runtime_settings,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"
FRONTEND_LIVE2D_DIST = FRONTEND_DIST / "live2d"


def sse_event(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


app = FastAPI(title="arxiv-paper-rag")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ingest_manager = IngestManager(REPO_ROOT)
search_sessions: dict[str, tuple[SearchExecution, Any]] = {}
trace_sessions: dict[str, tuple[TraceExecution, Any]] = {}


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


def target_paper_to_model(target: TargetPaper) -> TargetPaperModel:
    return TargetPaperModel(
        id=target.id,
        arxiv_id=target.arxiv_id,
        title=target.title,
        summary=target.summary,
        authors=list(target.authors),
        published_date=target.published_date,
        primary_category=target.primary_category,
    )


def resolve_saved_model_list_api_key(payload: ModelListRequest) -> str | None:
    if payload.provider != "openai_compatible" or payload.api_key or payload.clear_api_key:
        return payload.api_key

    saved_settings = load_runtime_settings()
    requested_base_url = normalize_openai_compatible_base_url(payload.base_url)
    for chat_config in (saved_settings.query_chat, saved_settings.answer_chat):
        if chat_config.provider != "openai_compatible":
            continue
        if normalize_openai_compatible_base_url(chat_config.base_url) == requested_base_url and chat_config.api_key:
            return chat_config.api_key
    return None


@app.get("/api/config", response_model=RuntimeSettingsResponse)
def get_config() -> RuntimeSettingsResponse:
    return runtime_settings_to_response(load_runtime_settings())


@app.put("/api/config", response_model=RuntimeSettingsResponse)
def put_config(payload: RuntimeSettingsRequest) -> RuntimeSettingsResponse:
    base = load_runtime_settings()
    merged = merge_runtime_settings(base, payload)
    validate_runtime_settings(merged)
    saved = save_runtime_settings(merged)
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
    settings = merge_runtime_settings(load_runtime_settings(), payload.settings)
    validate_runtime_settings(settings)
    plan = plan_query(payload.question, settings)
    return QueryPlanModel(**asdict(plan))


@app.post("/api/search/plan/refine", response_model=QueryPlanModel)
def api_refine_query(payload: SearchRefineRequest) -> QueryPlanModel:
    settings = merge_runtime_settings(load_runtime_settings(), payload.settings)
    validate_runtime_settings(settings)
    plan = revise_query_plan(
        payload.question,
        previous_plan=query_plan_model_to_dataclass(payload.previous_plan),
        feedback=payload.feedback,
        settings=settings,
    )
    return QueryPlanModel(**asdict(plan))


@app.post("/api/search/execute", response_model=SearchExecuteResponse)
def api_execute_search(payload: SearchExecuteRequest) -> SearchExecuteResponse:
    settings = merge_runtime_settings(load_runtime_settings(), payload.settings)
    validate_runtime_settings(settings)
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
    )


@app.post("/api/trace/resolve-target", response_model=TraceResolveResponse)
def api_trace_resolve_target(payload: TraceResolveRequest) -> TraceResolveResponse:
    status, resolved_target, candidates, message = resolve_target_paper(payload.query)
    return TraceResolveResponse(
        status=status,
        query=payload.query,
        resolved_target=target_paper_to_model(resolved_target) if resolved_target else None,
        candidates=[target_paper_to_model(candidate) for candidate in candidates],
        message=message,
    )


@app.post("/api/trace/execute", response_model=TraceExecuteResponse)
def api_trace_execute(payload: TraceExecuteRequest) -> TraceExecuteResponse:
    settings = merge_runtime_settings(load_runtime_settings(), payload.settings)
    validate_runtime_settings(settings)
    target_paper = fetch_target_paper_by_id(payload.target_id)
    if target_paper is None:
        raise HTTPException(status_code=404, detail="Target paper not found.")
    answer_language = payload.answer_language or infer_user_language(target_paper.title)
    execution = execute_trace(
        target_paper=target_paper,
        settings=settings,
        answer_language=answer_language,
    )
    trace_id = uuid.uuid4().hex
    trace_sessions[trace_id] = (execution, settings)
    return TraceExecuteResponse(
        trace_id=trace_id,
        answer_language=execution.answer_language,
        retrieval_text=execution.retrieval_text,
        target_paper=target_paper_to_model(execution.target_paper),
        papers=[RankedPaperResponse(**asdict(paper)) for paper in execution.papers],
        warnings=execution.warnings,
    )


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


@app.get("/api/trace/{trace_id}/answer/stream")
def api_trace_stream_answer(trace_id: str) -> StreamingResponse:
    session = trace_sessions.get(trace_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Trace session not found.")

    execution, settings = session

    def event_generator():
        yield sse_event("start", {"trace_id": trace_id})
        try:
            for token in stream_trace_answer_tokens(execution, settings):
                yield sse_event("token", {"content": token})
            yield sse_event("complete", {"trace_id": trace_id})
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
    response = generate_live2d_reply(
        source=payload.source,
        message=payload.message,
        history=[item.model_dump() for item in payload.history],
        answer_context=payload.answer_context,
        settings=settings,
        available_expressions=list(bootstrap["available_expressions"]),
    )
    return Live2DChatResponse(**response)


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

    @app.get("/")
    def root() -> FileResponse:
        return FileResponse(FRONTEND_DIST / "index.html")

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found.")
        return FileResponse(FRONTEND_DIST / "index.html")
