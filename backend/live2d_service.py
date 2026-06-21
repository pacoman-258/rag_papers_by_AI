from __future__ import annotations

import json
import logging
import mimetypes
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

try:
    import edge_tts
except Exception:  # pragma: no cover
    edge_tts = None

from fastapi import HTTPException

from backend.assistant_memory import (
    delete_assistant_memory_item,
    finalize_live2d_chat_turn,
    get_live2d_memory_state,
    pin_assistant_memory_item,
    prepare_live2d_chat_context,
)
from local_paper_db.app.search_service import (
    RuntimeSettings,
    chat_completion,
    extract_first_json_object,
    infer_user_language,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
LIVE2D_PUBLIC_ROOT = REPO_ROOT / "frontend" / "public" / "live2d"
LIVE2D_DIST_ROOT = REPO_ROOT / "frontend" / "dist" / "live2d"
LIVE2D_AUDIO_CACHE_DIR = Path(tempfile.gettempdir()) / "arxiv_paper_rag_live2d_audio"
DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"
DEFAULT_RATE = "+0%"
DEFAULT_POSITION = "bottom-right"
DEFAULT_CONTEXT_LIMIT = 4000
DEFAULT_AUDIO_DURATION_MS = 700
PREFERRED_MODEL_NAMES = (
    "AnAn - model.model3.json",
    "hiyori_free_t08.model3.json",
)

_AUDIO_INDEX: dict[str, dict[str, Any]] = {}
LOGGER = logging.getLogger(__name__)


def get_live2d_runtime_root() -> Path:
    if LIVE2D_DIST_ROOT.exists():
        return LIVE2D_DIST_ROOT
    return LIVE2D_PUBLIC_ROOT


def trim_answer_context(text: str | None, max_length: int = DEFAULT_CONTEXT_LIMIT) -> str | None:
    value = str(text or "").strip()
    if not value:
        return None
    if len(value) <= max_length:
        return value
    return value[:max_length].rstrip() + "..."


def _safe_text(value: Any, max_length: int = DEFAULT_CONTEXT_LIMIT) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    if len(text) <= max_length:
        return text
    return text[:max_length].rstrip() + "..."


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except Exception:
        return None


def _coerce_string_list(value: Any, *, limit: int = 8, max_length: int = 120) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    items: list[str] = []
    for item in value[:limit]:
        text = _safe_text(item, max_length=max_length)
        if text:
            items.append(text)
    return items


def ensure_audio_cache_dir() -> None:
    LIVE2D_AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def cleanup_audio_cache(max_age_seconds: int = 1800) -> None:
    ensure_audio_cache_dir()
    now = time.time()
    stale_ids: list[str] = []
    for file_id, metadata in list(_AUDIO_INDEX.items()):
        path = metadata.get("path")
        if not isinstance(path, Path) or not path.exists():
            stale_ids.append(file_id)
            continue
        if now - path.stat().st_mtime > max_age_seconds:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass
            stale_ids.append(file_id)
    for file_id in stale_ids:
        _AUDIO_INDEX.pop(file_id, None)

    for path in LIVE2D_AUDIO_CACHE_DIR.iterdir():
        if not path.is_file():
            continue
        try:
            if now - path.stat().st_mtime > max_age_seconds:
                path.unlink(missing_ok=True)
        except Exception:
            continue


def _find_model_path() -> Path:
    live2d_root = get_live2d_runtime_root()
    model_root = live2d_root / "model"
    if not model_root.exists():
        raise RuntimeError(f"No Live2D model directory found under {model_root}.")

    candidates = [
        path
        for path in model_root.rglob("*.model3.json")
        if not path.name.endswith(".autogen.model3.json")
    ]
    if not candidates:
        raise RuntimeError("No Live2D .model3.json file was found.")

    for preferred in PREFERRED_MODEL_NAMES:
        for path in candidates:
            if path.name == preferred:
                return path

    return sorted(candidates)[0]


def _relative_live2d_url(path: Path) -> str:
    relative = path.relative_to(get_live2d_runtime_root())
    encoded = "/".join(quote(part) for part in relative.parts)
    return f"/live2d/{encoded}"


def _extract_expression_defs(model_json: dict[str, Any]) -> list[dict[str, Any]]:
    expressions = model_json.get("FileReferences", {}).get("Expressions")
    return expressions if isinstance(expressions, list) else []


def _scan_expression_defs(model_path: Path) -> list[str]:
    expressions: list[str] = []
    for file_path in sorted(model_path.parent.glob("*.exp3.json")):
        name = file_path.name[:-10] if file_path.name.lower().endswith(".exp3.json") else file_path.stem
        cleaned = str(name).strip()
        if cleaned:
            expressions.append(cleaned)
    return expressions


def _normalize_expression_list(items: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        label = str(item or "").strip()
        if not label:
            continue
        lowered = label.casefold()
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(label)
    return normalized


def _read_model_json(model_path: Path) -> dict[str, Any]:
    try:
        return json.loads(model_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _pick_default_expression(expressions: list[str]) -> str | None:
    if not expressions:
        return None

    preferred_keywords = ("think", "exp1", "shy", "note", "abb")
    for keyword in preferred_keywords:
        for expression in expressions:
            if keyword in expression.casefold():
                return expression
    return expressions[0]


def _normalize_workflow_kind(workflow_context: dict[str, Any] | None) -> str:
    if not isinstance(workflow_context, dict):
        return ""
    return _safe_text(workflow_context.get("kind"), max_length=64).casefold()


def _normalize_reply_language(
    language: str | None,
    workflow_context: dict[str, Any] | None,
    answer_context: str | None,
    message: str | None,
) -> str:
    explicit = _safe_text(language, max_length=16).casefold()
    if explicit in {"zh", "en"}:
        return explicit
    if isinstance(workflow_context, dict):
        for key in ("answer_language", "page_language", "language"):
            workflow_language = _safe_text(workflow_context.get(key), max_length=16).casefold()
            if workflow_language in {"zh", "en"}:
                return workflow_language
    sample = "\n".join(
        part
        for part in (
            _safe_text(message, max_length=400),
            _safe_text(answer_context, max_length=600),
            _safe_text((workflow_context or {}).get("query") if isinstance(workflow_context, dict) else "", max_length=200),
            _safe_text((workflow_context or {}).get("paper_title") if isinstance(workflow_context, dict) else "", max_length=200),
        )
        if part
    )
    inferred = infer_user_language(sample)
    return "zh" if inferred == "zh" else "en"


def _reply_language_name(reply_language: str) -> str:
    return "Simplified Chinese" if reply_language == "zh" else "English"


def _fallback_live2d_reply(source: str, workflow_kind: str, reply_language: str) -> str:
    if reply_language == "en":
        if source == "user" and workflow_kind == "paper_reader":
            return "I can keep unpacking this page with you. If you want, I can explain the method, point out the key evidence, or guide you into the next section."
        if source == "user":
            return "I'm here. We can keep talking through your question, or you can run QA / Citation Trace first and I'll help you interpret the result."
        if workflow_kind == "paper_reader":
            return "I've caught up with this page. If you want, I can highlight the key point, explain the method, or suggest what to read next."
        return "I've read the latest result. If you want, I can break the key point down more clearly."
    if source == "user" and workflow_kind == "paper_reader":
        return "我可以继续陪你拆解这一页。如果你愿意，我可以解释方法、指出关键证据，或者带你进入下一部分。"
    if source == "user":
        return "我在呢，可以继续和我聊你的问题，或者先运行一次 QA / 论文溯源，我再帮你解读结果。"
    if workflow_kind == "paper_reader":
        return "这一页我已经接上了。如果你愿意，我可以继续帮你解释方法、提醒关键点，或者带你看下一部分。"
    return "我看完最新结果了。如果你愿意，我可以继续帮你把关键点拆得更清楚。"


def _render_paper_reader_context_lines(workflow_context: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    paper_title = _safe_text(workflow_context.get("paper_title"), max_length=240)
    page_index = _coerce_int(workflow_context.get("page_index"))
    page_title = _safe_text(workflow_context.get("page_title"), max_length=240)
    section_titles = _coerce_string_list(workflow_context.get("section_titles"), limit=8, max_length=100)
    latest_page_summary = _safe_text(workflow_context.get("latest_page_summary"), max_length=1800)
    latest_answer_text = _safe_text(workflow_context.get("latest_answer_text"), max_length=1800)
    source = _safe_text(workflow_context.get("source"), max_length=48)
    page_count = _coerce_int(workflow_context.get("page_count"))
    answer_language = _safe_text(workflow_context.get("answer_language"), max_length=16).casefold()
    reader_mode = _safe_text(workflow_context.get("reader_mode"), max_length=32)
    discipline = _safe_text(workflow_context.get("discipline"), max_length=64)
    discipline_source = _safe_text(workflow_context.get("discipline_source"), max_length=16)
    story_stage = workflow_context.get("story_stage") if isinstance(workflow_context.get("story_stage"), dict) else {}
    story_stage_title = _safe_text(story_stage.get("title"), max_length=160) if story_stage else ""
    discipline_guide = workflow_context.get("discipline_guide") if isinstance(workflow_context.get("discipline_guide"), dict) else {}
    guide_panels = discipline_guide.get("panels") if isinstance(discipline_guide.get("panels"), list) else []
    blackboard_notes = workflow_context.get("blackboard_notes")
    glossary_terms = workflow_context.get("glossary_terms") if isinstance(workflow_context.get("glossary_terms"), list) else []
    checkpoint_status = _safe_text(workflow_context.get("checkpoint_status"), max_length=48)

    if paper_title:
        lines.append(f"- paper_title: {paper_title}")
    if page_index is not None:
        lines.append(f"- page_index: {page_index}")
        if page_index >= 0:
            page_label = f"第{page_index + 1}页" if answer_language == "zh" else f"Page {page_index + 1}"
            lines.append(f"- page_label: {page_label}")
    if page_title:
        lines.append(f"- page_title: {page_title}")
    if page_count is not None and page_count > 0:
        lines.append(f"- page_count: {page_count}")
    if answer_language in {"zh", "en"}:
        lines.append(f"- answer_language: {answer_language}")
    if reader_mode:
        lines.append(f"- reader_mode: {reader_mode}")
    if discipline:
        suffix = f" ({discipline_source})" if discipline_source else ""
        lines.append(f"- discipline: {discipline}{suffix}")
    if story_stage_title:
        lines.append(f"- story_stage: {story_stage_title}")
    if guide_panels:
        panel_titles = []
        for item in guide_panels[:5]:
            if isinstance(item, dict):
                title = _safe_text(item.get("title"), max_length=100)
                if title:
                    panel_titles.append(title)
        if panel_titles:
            lines.append("- discipline_guide_panels: " + ", ".join(panel_titles))
    if section_titles:
        lines.append("- section_titles: " + ", ".join(section_titles))
    if isinstance(blackboard_notes, dict):
        takeaway = _safe_text(blackboard_notes.get("takeaway"), max_length=500)
        if takeaway:
            lines.append(f"- blackboard_takeaway: {takeaway}")
    if glossary_terms:
        term_names = []
        for item in glossary_terms[:6]:
            if isinstance(item, dict):
                term = _safe_text(item.get("term"), max_length=80)
                if term:
                    term_names.append(term)
        if term_names:
            lines.append("- glossary_terms: " + ", ".join(term_names))
    if checkpoint_status:
        lines.append(f"- checkpoint_status: {checkpoint_status}")
    if source:
        lines.append(f"- source: {source}")
    if latest_page_summary:
        lines.append(f"- latest_page_summary: {latest_page_summary}")
    if latest_answer_text:
        lines.append(f"- latest_answer_text: {latest_answer_text}")
    lines.append(
        "- guidance: act as a professional guided-reading mentor, follow the paper discipline, focus on the current page, explain what matters, suggest the next reading step, and do not invent citations or paper-wide claims."
    )
    return lines


def _render_workflow_context_lines(workflow_context: dict[str, Any] | None) -> list[str]:
    if not workflow_context:
        return []
    kind = _normalize_workflow_kind(workflow_context)
    if kind == "paper_reader":
        return _render_paper_reader_context_lines(workflow_context)

    lines: list[str] = []
    query = _safe_text(workflow_context.get("query"), max_length=900)
    answer_text = _safe_text(workflow_context.get("answer_text"), max_length=1800)
    paper_titles = workflow_context.get("paper_titles")
    paper_ids = workflow_context.get("paper_ids")
    constraints = workflow_context.get("applied_constraints")

    if kind:
        lines.append(f"- kind: {kind}")
    if query:
        lines.append(f"- query: {query}")
    if answer_text:
        lines.append(f"- answer: {answer_text}")
    if isinstance(paper_titles, list) and paper_titles:
        lines.append("- paper_titles: " + ", ".join(_safe_text(item, 120) for item in paper_titles[:6]))
    if isinstance(paper_ids, list) and paper_ids:
        lines.append("- paper_ids: " + ", ".join(_safe_text(item, 64) for item in paper_ids[:8]))
    if constraints:
        lines.append("- constraints: " + _safe_text(json.dumps(constraints, ensure_ascii=False), 600))
    return lines


def get_live2d_bootstrap_payload() -> dict[str, Any]:
    try:
        model_path = _find_model_path()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    model_json = _read_model_json(model_path)
    expression_defs = _extract_expression_defs(model_json)
    expression_names = [
        str(item.get("Name") or "").strip()
        for item in expression_defs
        if isinstance(item, dict)
    ]
    if not expression_names:
        expression_names = _scan_expression_defs(model_path)
    expression_names = _normalize_expression_list(expression_names)

    return {
        "model_url": _relative_live2d_url(model_path),
        "available_expressions": expression_names,
        "default_expression": _pick_default_expression(expression_names),
        "default_voice": DEFAULT_VOICE,
        "tts_enabled": edge_tts is not None,
        "position": DEFAULT_POSITION,
    }


def _normalize_history(history: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for item in history or []:
        role = str(item.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        normalized.append({"role": role, "text": text})
    return normalized[-10:]


def _normalized_key(value: str) -> str:
    return "".join(ch for ch in value.casefold() if ch.isalnum())


def coerce_expression_name(expression: str | None, available_expressions: list[str]) -> str | None:
    raw = str(expression or "").strip()
    if not raw or not available_expressions:
        return None

    if raw in available_expressions:
        return raw

    normalized = _normalized_key(raw)
    for item in available_expressions:
        if _normalized_key(item) == normalized:
            return item

    fallback_pairs = (
        ("think", "think"),
        ("idea", "think"),
        ("angry", "angry"),
        ("mad", "angry"),
        ("shy", "shy"),
        ("calm", "abb"),
        ("neutral", "abb"),
        ("note", "note"),
    )
    for keyword, target in fallback_pairs:
        if keyword in normalized:
            for item in available_expressions:
                if target in item.casefold():
                    return item

    return None


def _build_live2d_system_prompt(
    available_expressions: list[str],
    workflow_context: dict[str, Any] | None = None,
    reply_language: str = "zh",
) -> str:
    expression_text = ", ".join(available_expressions) if available_expressions else "(none)"
    workflow_kind = _normalize_workflow_kind(workflow_context)
    reply_language_name = _reply_language_name(reply_language)
    paper_reader_rules = ""
    if workflow_kind == "paper_reader":
        page_ref_hint = 'Prefer "这一页" / "这一部分"' if reply_language == "zh" else 'Prefer "this page" / "this section"'
        paper_reader_rules = """
- When the workflow context is paper_reader, treat it as a page-local paper reading assistant.
- Explain the current page in plain language, follow the discipline-specific reading frame, point out what matters, and suggest the next sensible reading step.
- Use cautious language. Do not invent citations, experiments, formulas, or paper-wide conclusions beyond the provided page context.
- {page_ref_hint} language when the user is reading a paper.
- If the user asks for a broader summary, explain that you can only ground the reply in the current page context and can help continue page by page.
""".strip().format(page_ref_hint=page_ref_hint)
    return f"""
You are a warm and concise Live2D assistant inside an arXiv paper RAG workbench.
You can chat casually, explain answers, and suggest practical next steps.

Behavior rules:
- Be helpful, upbeat, and brief.
- Reply strictly in {reply_language_name}.
- Keep both reply_text and speak_text in {reply_language_name}.
- Never invent papers, experiments, citations, or retrieval results.
- If linked workflow answer context exists, treat it as the only workflow context you know.
- If long-term memory hints are provided, use them as soft personalization signals.
- Do not claim certainty when memory hints might be outdated.
- If no workflow answer context exists, behave like a normal chatbot.
- For automatic QA/Citation Trace follow-ups, do not wait for user input. Send one concise suggestion or clarification.
- Avoid markdown tables and long lists.
- Only keep a very short English paper phrase when you are directly quoting the original wording; all explanation around it must stay in {reply_language_name}.
{paper_reader_rules}

Return only one JSON object in this exact shape:
{{
  "reply_text": "assistant text shown in chat",
  "speak_text": "plain text for TTS, usually same as reply_text",
  "expression": "one exact expression from the allowed list, or empty string"
}}

Allowed expressions: {expression_text}
If no expression fits, use an empty string.
""".strip()


def _format_workflow_context_for_prompt(workflow_context: dict[str, Any] | None) -> str | None:
    if not workflow_context:
        return None
    lines = _render_workflow_context_lines(workflow_context)
    if lines:
        return "\n".join(lines)
    try:
        text = json.dumps(workflow_context, ensure_ascii=False, indent=2)
    except Exception:
        text = str(workflow_context)
    text = text.strip()
    if not text:
        return None
    return text if len(text) <= DEFAULT_CONTEXT_LIMIT else text[:DEFAULT_CONTEXT_LIMIT].rstrip() + "..."


def _build_live2d_messages(
    *,
    source: str,
    message: str,
    reply_language: str,
    history: list[dict[str, str]],
    answer_context: str | None,
    workflow_context: dict[str, Any] | None,
    memory_prompt_block: str | None,
    available_expressions: list[str],
) -> list[dict[str, str]]:
    workflow_kind = _normalize_workflow_kind(workflow_context)
    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": _build_live2d_system_prompt(
                available_expressions,
                workflow_context,
                reply_language=reply_language,
            ),
        }
    ]

    workflow_context_text = _format_workflow_context_for_prompt(workflow_context)
    if workflow_context_text:
        messages.append(
            {
                "role": "system",
                "content": "Latest linked workflow structured context:\n" + workflow_context_text,
            }
        )
    if answer_context:
        messages.append(
            {
                "role": "system",
                "content": "Latest linked workflow answer context:\n" + answer_context,
            }
        )
    if memory_prompt_block:
        messages.append(
            {
                "role": "system",
                "content": "Long-term memory context (only when relevant):\n" + memory_prompt_block,
            }
        )

    for item in history:
        messages.append({"role": item["role"], "content": item["text"]})

    if source == "user":
        user_prompt = (
            "User message:\n"
            f"{message}\n\n"
            "Reply naturally and keep it concise. Return JSON only."
        )
        if workflow_kind == "paper_reader":
            user_prompt += (
                "\n\nThis is a paper reading page. Ground the reply in the current page context, "
                "help the user understand what matters, and suggest what to inspect next. "
                "Do not invent citations or paper-wide conclusions."
            )
        messages.append(
            {
                "role": "user",
                "content": user_prompt,
            }
        )
    else:
        if workflow_kind == "paper_reader":
            auto_prompt = (
                "The paper_reader workflow just updated the current paper page."
                " Without waiting for user input, send one concise follow-up that helps the user understand"
                " the current page, notice the key point, or know what to read next."
                " Ground the reply in the current page context and do not invent citations or paper-wide claims."
                " Return JSON only."
            )
        else:
            workflow_label = "QA" if source == "qa_auto" else "Citation Trace"
            auto_prompt = (
                f"The {workflow_label} workflow just finished."
                " Without waiting for user input, send one concise proactive follow-up based on the linked workflow answer."
                " Return JSON only."
            )
        if answer_context:
            auto_prompt += "\n\nFocus on what the user can understand or do next."
        messages.append({"role": "user", "content": auto_prompt})

    return messages


def generate_live2d_reply(
    *,
    source: str,
    message: str,
    language: str | None,
    history: list[dict[str, Any]] | None,
    answer_context: str | None,
    workflow_context: dict[str, Any] | None = None,
    session_id: str | None = None,
    settings: RuntimeSettings,
    available_expressions: list[str],
    db_config: dict[str, str] | None = None,
) -> dict[str, Any]:
    normalized_history = _normalize_history(history)
    trimmed_context = trim_answer_context(answer_context)
    trimmed_message = str(message or "").strip()
    resolved_workflow_context = workflow_context if isinstance(workflow_context, dict) else None
    reply_language = _normalize_reply_language(language, resolved_workflow_context, trimmed_context, trimmed_message)
    if resolved_workflow_context is not None and str(resolved_workflow_context.get("answer_language") or "").strip().lower() not in {"zh", "en"}:
        resolved_workflow_context = {
            **resolved_workflow_context,
            "answer_language": reply_language,
        }

    if source == "user" and not trimmed_message:
        raise HTTPException(status_code=400, detail="User message is empty.")

    memory_context: dict[str, Any] = {
        "session_id": str(session_id or "").strip() or None,
        "memory_used": False,
        "used_memory_items": [],
        "memory_prompt_block": None,
        "memory_notice": None,
        "workflow_context": resolved_workflow_context,
    }
    try:
        memory_context = prepare_live2d_chat_context(
            source=source,
            message=trimmed_message,
            answer_context=trimmed_context,
            workflow_context=resolved_workflow_context,
            settings=settings,
            session_id=session_id,
            history=history,
            db_config=db_config,
        )
    except Exception as exc:
        LOGGER.warning("live2d memory prepare failed, fallback to stateless chat: %s", exc)

    memory_workflow_context = memory_context.get("workflow_context")
    if isinstance(memory_workflow_context, dict) and str(memory_workflow_context.get("answer_language") or "").strip().lower() not in {"zh", "en"}:
        memory_context["workflow_context"] = {
            **memory_workflow_context,
            "answer_language": reply_language,
        }

    messages = _build_live2d_messages(
        source=source,
        message=trimmed_message,
        reply_language=reply_language,
        history=normalized_history,
        answer_context=trimmed_context,
        workflow_context=memory_context.get("workflow_context"),
        memory_prompt_block=memory_context.get("memory_prompt_block"),
        available_expressions=available_expressions,
    )
    raw_content = chat_completion(messages, settings.answer_chat, settings.retrieval.request_timeout)

    try:
        payload = extract_first_json_object(raw_content)
    except Exception:
        payload = {
            "reply_text": raw_content.strip(),
            "speak_text": raw_content.strip(),
            "expression": "",
        }

    reply_text = str(payload.get("reply_text") or "").strip()
    speak_text = str(payload.get("speak_text") or reply_text).strip()
    expression = coerce_expression_name(payload.get("expression"), available_expressions)

    if not reply_text:
        workflow_kind = _normalize_workflow_kind(memory_context.get("workflow_context"))
        reply_text = _fallback_live2d_reply(source, workflow_kind, reply_language)
    if not speak_text:
        speak_text = reply_text

    try:
        finalize_live2d_chat_turn(
            session_id=str(memory_context.get("session_id") or session_id or ""),
            source=source,
            assistant_reply=reply_text,
            answer_context=trimmed_context,
            workflow_context=memory_context.get("workflow_context"),
            settings=settings,
            db_config=db_config,
        )
    except Exception as exc:
        LOGGER.warning("live2d memory finalize failed: %s", exc)

    return {
        "reply_text": reply_text,
        "speak_text": speak_text,
        "expression": expression,
        "session_id": memory_context.get("session_id") or session_id,
        "memory_used": bool(memory_context.get("memory_used")),
        "memory_notice": memory_context.get("memory_notice"),
        "used_memory_items": memory_context.get("used_memory_items") or [],
    }


def list_live2d_memory_items(
    *,
    session_id: str | None = None,
    limit: int = 20,
    db_config: dict[str, str] | None = None,
) -> dict[str, Any]:
    try:
        return get_live2d_memory_state(session_id=session_id, limit=limit, db_config=db_config)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to list assistant memory: {exc}") from exc


def pin_live2d_memory_item(
    memory_id: str,
    *,
    db_config: dict[str, str] | None = None,
) -> dict[str, Any]:
    try:
        return pin_assistant_memory_item(memory_id, pinned=True, db_config=db_config)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to pin assistant memory: {exc}") from exc


def delete_live2d_memory_item(
    memory_id: str,
    *,
    db_config: dict[str, str] | None = None,
) -> dict[str, Any]:
    try:
        deleted = delete_assistant_memory_item(memory_id, db_config=db_config)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to delete assistant memory: {exc}") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory item not found.")
    return {"memory_id": memory_id, "deleted": True}


def tts_available() -> bool:
    return edge_tts is not None


def _guess_duration_ms(text: str) -> int:
    return max(DEFAULT_AUDIO_DURATION_MS, int(len(text) * 220))


async def synthesize_live2d_tts(
    *,
    text: str,
    voice: str | None = None,
    rate: str | None = None,
) -> dict[str, Any]:
    if edge_tts is None:
        raise HTTPException(status_code=503, detail="edge-tts is not installed.")

    content = str(text or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="TTS text is empty.")

    cleanup_audio_cache()
    ensure_audio_cache_dir()

    file_id = uuid.uuid4().hex
    output_path = LIVE2D_AUDIO_CACHE_DIR / f"{file_id}.mp3"
    communicator = edge_tts.Communicate(
        text=content,
        voice=str(voice or DEFAULT_VOICE).strip() or DEFAULT_VOICE,
        rate=str(rate or DEFAULT_RATE).strip() or DEFAULT_RATE,
    )
    try:
        await communicator.save(str(output_path))
    except Exception as exc:
        output_path.unlink(missing_ok=True)
        raise HTTPException(status_code=502, detail=f"TTS synthesis failed: {exc}") from exc

    media_type = mimetypes.guess_type(output_path.name)[0] or "audio/mpeg"
    payload = {
        "file_id": file_id,
        "audio_url": f"/api/live2d/audio/{file_id}",
        "duration_ms": _guess_duration_ms(content),
        "media_type": media_type,
        "path": output_path,
    }
    _AUDIO_INDEX[file_id] = payload
    return payload


def get_live2d_audio(file_id: str) -> tuple[Path, str]:
    cleanup_audio_cache()
    metadata = _AUDIO_INDEX.get(file_id)
    path = metadata.get("path") if metadata else None
    if not isinstance(path, Path) or not path.exists():
        fallback_path = LIVE2D_AUDIO_CACHE_DIR / f"{file_id}.mp3"
        if not fallback_path.exists():
            _AUDIO_INDEX.pop(file_id, None)
            raise HTTPException(status_code=404, detail="Audio file not found.")
        path = fallback_path

    media_type = str(metadata.get("media_type") or mimetypes.guess_type(path.name)[0] or "audio/mpeg") if metadata else (
        mimetypes.guess_type(path.name)[0] or "audio/mpeg"
    )
    return path, media_type
