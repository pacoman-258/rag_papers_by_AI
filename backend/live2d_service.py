from __future__ import annotations

import json
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

from local_paper_db.app.search_service import (
    RuntimeSettings,
    chat_completion,
    extract_first_json_object,
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


def _build_live2d_system_prompt(available_expressions: list[str]) -> str:
    expression_text = ", ".join(available_expressions) if available_expressions else "(none)"
    return f"""
You are a warm and concise Live2D assistant inside an arXiv paper RAG workbench.
You can chat casually, explain answers, and suggest practical next steps.

Behavior rules:
- Be helpful, upbeat, and brief.
- Never invent papers, experiments, citations, or retrieval results.
- If linked workflow answer context exists, treat it as the only workflow context you know.
- If no workflow answer context exists, behave like a normal chatbot.
- For automatic QA/PST follow-ups, do not wait for user input. Send one concise suggestion or clarification.
- Avoid markdown tables and long lists.
- Speak naturally in Chinese when the user or context is Chinese, otherwise speak in English.

Return only one JSON object in this exact shape:
{{
  "reply_text": "assistant text shown in chat",
  "speak_text": "plain text for TTS, usually same as reply_text",
  "expression": "one exact expression from the allowed list, or empty string"
}}

Allowed expressions: {expression_text}
If no expression fits, use an empty string.
""".strip()


def _build_live2d_messages(
    *,
    source: str,
    message: str,
    history: list[dict[str, str]],
    answer_context: str | None,
    available_expressions: list[str],
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [
        {"role": "system", "content": _build_live2d_system_prompt(available_expressions)}
    ]

    if answer_context:
        messages.append(
            {
                "role": "system",
                "content": "Latest linked workflow answer context:\n" + answer_context,
            }
        )

    for item in history:
        messages.append({"role": item["role"], "content": item["text"]})

    if source == "user":
        messages.append(
            {
                "role": "user",
                "content": (
                    "User message:\n"
                    f"{message}\n\n"
                    "Reply naturally and keep it concise. Return JSON only."
                ),
            }
        )
    else:
        workflow_label = "QA" if source == "qa_auto" else "PST"
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
    history: list[dict[str, Any]] | None,
    answer_context: str | None,
    settings: RuntimeSettings,
    available_expressions: list[str],
) -> dict[str, Any]:
    normalized_history = _normalize_history(history)
    trimmed_context = trim_answer_context(answer_context)
    trimmed_message = str(message or "").strip()

    if source == "user" and not trimmed_message:
        raise HTTPException(status_code=400, detail="User message is empty.")

    messages = _build_live2d_messages(
        source=source,
        message=trimmed_message,
        history=normalized_history,
        answer_context=trimmed_context,
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
        if source == "user":
            reply_text = "我在呢，可以继续和我聊你的问题，或者先运行一次 QA / PST，我再帮你补充建议。"
        else:
            reply_text = "我看完这段回答啦。如果你愿意，我可以继续帮你把关键点拆得更清楚。"
    if not speak_text:
        speak_text = reply_text

    return {
        "reply_text": reply_text,
        "speak_text": speak_text,
        "expression": expression,
    }


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
