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
from backend.ingest_manager import IngestManager
from backend.schemas import (
    IngestJobResponse,
    QueryPlanModel,
    SearchExecuteRequest,
    SearchExecuteResponse,
    SearchPlanRequest,
    SearchRefineRequest,
    RankedPaperResponse,
    RuntimeSettingsRequest,
    RuntimeSettingsResponse,
)
from local_paper_db.app.search_service import (
    QueryPlan,
    SearchExecution,
    execute_search,
    get_database_overview,
    plan_query,
    revise_query_plan,
    serialize_runtime_settings,
    stream_answer_tokens,
    validate_runtime_settings,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


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


def query_plan_model_to_dataclass(model: QueryPlanModel | None) -> QueryPlan | None:
    if model is None:
        return None
    return QueryPlan(
        answer_language=model.answer_language,
        intent_summary=model.intent_summary,
        retrieval_query_en=model.retrieval_query_en,
        keywords_en=list(model.keywords_en),
    )


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


if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/")
    def root() -> FileResponse:
        return FileResponse(FRONTEND_DIST / "index.html")

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found.")
        return FileResponse(FRONTEND_DIST / "index.html")
