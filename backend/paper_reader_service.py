from __future__ import annotations

import ast
import json
import math
import re
import tempfile
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import requests
from pypdf import PdfReader

from backend.schemas import (
    PaperReaderCitationModel,
    PaperReaderChatRequest,
    PaperReaderChatResponse,
    PaperReaderChunkModel,
    PaperReaderInsightModel,
    PaperReaderPageContentModel,
    PaperReaderPageManifestModel,
    PaperReaderSectionModel,
    PaperReaderSessionModel,
    PaperReaderSourceSectionModel,
    PaperReaderStructuredStatusModel,
    PaperReaderStructuredTextModel,
)
from local_paper_db.app.external_sources import fetch_arxiv_record
from local_paper_db.app.search_service import (
    ChatConfig,
    RuntimeSettings,
    chat_completion,
    cosine_similarity,
    extract_arxiv_base_id,
    extract_first_json_object,
    get_embedding,
    infer_user_language,
    normalize_whitespace,
    stream_chat_tokens,
)


DEFAULT_MAX_CONTEXT_TOKENS = 8192
DEFAULT_TARGET_PAGE_TOKENS = 6000
DEFAULT_TARGET_CHUNK_TOKENS = 1800
READING_FOCUS_ORDER = (
    ("core_question", "Core question"),
    ("method_or_mechanism", "Method or mechanism"),
    ("evidence_or_experiments", "Evidence or experiments"),
    ("conclusion", "Conclusion"),
    ("open_questions_or_limitations", "Open questions or limitations"),
)
COMMON_SECTION_HEADINGS = {
    "abstract",
    "introduction",
    "background",
    "related work",
    "method",
    "methods",
    "approach",
    "model",
    "experiments",
    "experiment",
    "results",
    "discussion",
    "conclusion",
    "conclusions",
    "limitations",
    "appendix",
}
TERMINAL_SECTION_HEADINGS = {
    "references",
    "bibliography",
}
ARXIV_URL_PATTERN = re.compile(
    r"^https?://(?:www\.)?arxiv\.org/(?P<kind>abs|pdf)/(?P<id>\d{4}\.\d{4,5}(?:v\d+)?)(?:\.pdf)?/?$",
    re.IGNORECASE,
)
NUMBERED_HEADING_PATTERN = re.compile(r"^(?P<num>\d+(?:\.\d+)*)\s*[.)]?\s+(?P<title>.+)$")
ROMAN_HEADING_PATTERN = re.compile(r"^(?P<num>[ivxlcdm]+)\.?\s+(?P<title>.+)$", re.IGNORECASE)
CHUNK_SPLIT_SENTENCE_PATTERN = re.compile(r"(?<=[。！？!?】【。.])\s+")
CORE_QUESTION_KEYWORDS = (
    "abstract",
    "introduction",
    "background",
    "motivation",
    "problem",
    "overview",
    "preliminar",
    "related work",
)
METHOD_KEYWORDS = (
    "method",
    "approach",
    "model",
    "architecture",
    "algorithm",
    "framework",
    "training",
    "implementation",
    "inference",
    "optimization",
)
EVIDENCE_KEYWORDS = (
    "experiment",
    "evaluation",
    "result",
    "analysis",
    "ablation",
    "benchmark",
    "dataset",
    "performance",
    "case study",
)
CONCLUSION_KEYWORDS = (
    "conclusion",
    "conclusions",
    "closing",
    "final remarks",
    "summary",
)
OPEN_QUESTION_KEYWORDS = (
    "limitation",
    "limitations",
    "future work",
    "open question",
    "discussion",
    "failure",
    "risk",
    "ethic",
    "societal impact",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_paper_reader_chat_config(settings: RuntimeSettings) -> ChatConfig:
    config = settings.paper_reader_chat
    return ChatConfig(
        provider=config.provider,
        model=config.model,
        base_url=config.base_url,
        api_key=config.api_key,
    )


def _normalize_title(title: str | None, fallback: str) -> str:
    normalized = normalize_whitespace(str(title or "")).strip()
    return normalized or fallback


def _count_tokens(text: str) -> int:
    if not text.strip():
        return 0
    total = 0
    ascii_run = 0
    for char in text:
        if "\u4e00" <= char <= "\u9fff":
            if ascii_run:
                total += math.ceil(ascii_run / 4)
                ascii_run = 0
            total += 1
            continue
        if char.isspace():
            ascii_run += 1
            continue
        ascii_run += 1
    if ascii_run:
        total += math.ceil(ascii_run / 4)
    return max(total, 1)


def _compute_budget(max_context_tokens: int) -> tuple[int, int, int]:
    reserved_output_tokens = max(1024, math.floor(max_context_tokens * 0.2))
    reserved_scaffold_tokens = 1200
    page_input_budget = max_context_tokens - reserved_output_tokens - reserved_scaffold_tokens
    return reserved_output_tokens, reserved_scaffold_tokens, page_input_budget


def _compute_target_page_budget(page_input_budget: int) -> int:
    return max(1, min(page_input_budget, DEFAULT_TARGET_PAGE_TOKENS))


def _compute_target_chunk_budget(page_input_budget: int) -> int:
    return max(1, min(page_input_budget, DEFAULT_TARGET_CHUNK_TOKENS))


def _normalize_answer_language(value: str | None, fallback_text: str = "") -> str:
    normalized = normalize_whitespace(str(value or "")).strip().lower()
    if normalized in {"zh", "en"}:
        return normalized
    inferred = infer_user_language(fallback_text or "")
    return "zh" if inferred == "zh" else "en"


def _reader_explanation_label(answer_language: str) -> str:
    return "中文解读" if answer_language == "zh" else "Explanation (EN)"


def _reader_explanation_language(answer_language: str) -> str:
    return "Simplified Chinese" if answer_language == "zh" else "English"


def _clip_original_excerpt(text: str, max_length: int = 220) -> str:
    normalized = normalize_whitespace(text)
    if not normalized:
        return ""
    if len(normalized) <= max_length:
        return normalized
    return normalized[:max_length].rstrip() + "..."


def _normalize_multiline_text(text: str | None) -> str:
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [normalize_whitespace(line) for line in raw.split("\n")]
    normalized_lines = [line for line in lines if line]
    return "\n".join(normalized_lines).strip()


def _contains_any_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.casefold()
    return any(keyword in lowered for keyword in keywords)


def _reading_focus_title(focus_key: str) -> str:
    for key, title in READING_FOCUS_ORDER:
        if key == focus_key:
            return title
    return "Evidence or experiments"


def _fallback_section_titles_for_plan(plan: PaperReaderPagePlan) -> tuple[str, str]:
    if plan.focus_key == "open_questions_or_limitations":
        return plan.focus_title, "Questions or caveats"
    if plan.focus_key == "conclusion":
        return plan.focus_title, "Takeaways"
    return plan.focus_title, "Supporting details"


def _format_reader_block_text(original_excerpt: str, explanation_text: str, answer_language: str) -> str:
    explanation_label = _reader_explanation_label(answer_language)
    original_line = f"Original (EN): {_clip_original_excerpt(original_excerpt) or '(missing)'}"
    explanation_line = f"{explanation_label}: {normalize_whitespace(explanation_text) or '(missing)'}"
    return f"{original_line}\n{explanation_line}"


def _format_reader_inline_item(original_excerpt: str, explanation_text: str, answer_language: str) -> str:
    explanation_label = _reader_explanation_label(answer_language)
    return (
        f"Original (EN): {_clip_original_excerpt(original_excerpt) or '(missing)'}"
        f" | {explanation_label}: {normalize_whitespace(explanation_text) or '(missing)'}"
    )


def _ensure_reader_block_text(text: str | None, answer_language: str, fallback_original: str) -> str | None:
    normalized = _normalize_multiline_text(text)
    if not normalized:
        return None
    explanation_label = _reader_explanation_label(answer_language)
    if "Original (EN):" in normalized and explanation_label in normalized:
        return normalized
    return _format_reader_block_text(fallback_original, normalized, answer_language)


def _ensure_reader_inline_item(text: str | None, answer_language: str, fallback_original: str) -> str | None:
    normalized = normalize_whitespace(text or "")
    if not normalized:
        return None
    explanation_label = _reader_explanation_label(answer_language)
    if "Original (EN):" in normalized and explanation_label in normalized:
        return normalized
    return _format_reader_inline_item(fallback_original, normalized, answer_language)


def _parse_reader_block_parts(text: str | None, answer_language: str) -> tuple[str | None, str | None]:
    normalized = _normalize_multiline_text(text)
    if not normalized:
        return None, None
    explanation_label = _reader_explanation_label(answer_language)
    original: str | None = None
    explanation_lines: list[str] = []
    capture_explanation = False
    for raw_line in normalized.split("\n"):
        line = raw_line.strip()
        if line.startswith("Original (EN):"):
            original = normalize_whitespace(line.partition(":")[2])
            capture_explanation = False
            continue
        if line.startswith(f"{explanation_label}:"):
            explanation_lines = [normalize_whitespace(line.partition(":")[2])]
            capture_explanation = True
            continue
        if capture_explanation:
            extra = normalize_whitespace(line)
            if extra:
                explanation_lines.append(extra)
    explanation = "\n".join(line for line in explanation_lines if line).strip() or None
    return original or None, explanation


def _parse_reader_inline_parts(text: str | None, answer_language: str) -> tuple[str | None, str | None]:
    normalized = normalize_whitespace(text or "")
    if not normalized:
        return None, None
    explanation_label = _reader_explanation_label(answer_language)
    original: str | None = None
    explanation: str | None = None
    for part in (item.strip() for item in normalized.split("|")):
        if part.startswith("Original (EN):"):
            original = normalize_whitespace(part.partition(":")[2]) or None
        elif part.startswith(f"{explanation_label}:"):
            explanation = normalize_whitespace(part.partition(":")[2]) or None
    return original, explanation


def _build_structured_text(
    *,
    original_en: str | None,
    explanation: str | None,
    answer_language: str,
    inline: bool = False,
) -> PaperReaderStructuredTextModel | None:
    normalized_original = normalize_whitespace(original_en or "")
    normalized_explanation = _normalize_multiline_text(explanation) if not inline else normalize_whitespace(explanation or "")
    if not normalized_original and not normalized_explanation:
        return None
    display_text = (
        _format_reader_inline_item(normalized_original, normalized_explanation, answer_language)
        if inline
        else _format_reader_block_text(normalized_original, normalized_explanation, answer_language)
    )
    return PaperReaderStructuredTextModel(
        original_en=normalized_original or None,
        explanation=normalized_explanation or None,
        display_text=display_text,
    )


def _coerce_structured_block(
    value: Any,
    answer_language: str,
    fallback_original: str,
) -> PaperReaderStructuredTextModel | None:
    if value is None:
        return None
    original: str | None = None
    explanation: str | None = None
    display_text: str | None = None
    if isinstance(value, dict):
        original = normalize_whitespace(
            value.get("original_en")
            or value.get("original")
            or value.get("quote")
            or value.get("source_text")
            or ""
        ) or None
        display_candidates = (
            value.get("display_text"),
            value.get("displayText"),
            value.get("formatted_text"),
            value.get("formattedText"),
        )
        for candidate in display_candidates:
            display_text = _normalize_multiline_text(candidate)
            if display_text:
                break
        explanation_candidates = (
            value.get("explanation"),
            value.get("interpretation"),
            value.get("analysis"),
            value.get("note"),
        )
        for candidate in explanation_candidates:
            explanation = _normalize_multiline_text(candidate)
            if explanation:
                break
        if not explanation:
            freeform = _normalize_multiline_text(value.get("text") or value.get("body") or value.get("content") or value.get("summary"))
            if freeform:
                if "Original (EN):" in freeform:
                    display_text = display_text or freeform
                else:
                    explanation = freeform
    else:
        display_text = _normalize_multiline_text(value)

    if display_text and (not original or not explanation):
        parsed_original, parsed_explanation = _parse_reader_block_parts(display_text, answer_language)
        original = original or parsed_original
        explanation = explanation or parsed_explanation
    if not explanation and display_text and "Original (EN):" not in display_text:
        explanation = display_text
    if not original:
        original = fallback_original
    return _build_structured_text(
        original_en=original,
        explanation=explanation,
        answer_language=answer_language,
    )


def _coerce_structured_inline(
    value: Any,
    answer_language: str,
    fallback_original: str,
) -> PaperReaderStructuredTextModel | None:
    if value is None:
        return None
    original: str | None = None
    explanation: str | None = None
    display_text: str | None = None
    if isinstance(value, dict):
        original = normalize_whitespace(
            value.get("original_en")
            or value.get("original")
            or value.get("quote")
            or value.get("source_text")
            or ""
        ) or None
        display_candidates = (
            value.get("display_text"),
            value.get("displayText"),
            value.get("formatted_text"),
            value.get("formattedText"),
        )
        for candidate in display_candidates:
            display_text = normalize_whitespace(candidate or "")
            if display_text:
                break
        explanation_candidates = (
            value.get("explanation"),
            value.get("interpretation"),
            value.get("analysis"),
            value.get("note"),
            value.get("text"),
            value.get("body"),
            value.get("content"),
            value.get("summary"),
        )
        for candidate in explanation_candidates:
            explanation = normalize_whitespace(candidate or "")
            if explanation:
                break
    else:
        display_text = normalize_whitespace(value or "")

    if display_text and (not original or not explanation):
        parsed_original, parsed_explanation = _parse_reader_inline_parts(display_text, answer_language)
        original = original or parsed_original
        explanation = explanation or parsed_explanation
    if not explanation and display_text and "Original (EN):" not in display_text:
        explanation = display_text
    if not original:
        original = fallback_original
    return _build_structured_text(
        original_en=original,
        explanation=explanation,
        answer_language=answer_language,
        inline=True,
    )


def _strip_code_fence(text: str) -> str:
    normalized = str(text or "").strip()
    if "```" not in normalized:
        return normalized
    fenced = re.search(r"```(?:json)?\s*(.*?)```", normalized, re.IGNORECASE | re.DOTALL)
    if fenced is not None:
        return fenced.group(1).strip()
    return normalized.replace("```", "").strip()


def _parse_json_object(raw_text: str) -> dict[str, Any] | None:
    with suppress(Exception):
        parsed = extract_first_json_object(raw_text)
        if isinstance(parsed, dict):
            return parsed
    with suppress(Exception):
        parsed = json.loads(raw_text)
        if isinstance(parsed, dict):
            return parsed
    return None


def _repair_json_object(raw_text: str) -> dict[str, Any] | None:
    candidate = _strip_code_fence(raw_text).strip()
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start >= 0 and end > start:
        candidate = candidate[start : end + 1]
    candidate = candidate.translate(
        str.maketrans(
            {
                "“": '"',
                "”": '"',
                "‘": "'",
                "’": "'",
            }
        )
    )
    candidate = re.sub(r",(\s*[}\]])", r"\1", candidate)
    repaired = _parse_json_object(candidate)
    if repaired is not None:
        return repaired
    with suppress(Exception):
        literal = ast.literal_eval(candidate)
        if isinstance(literal, dict):
            reparsed = json.loads(json.dumps(literal, ensure_ascii=False))
            if isinstance(reparsed, dict):
                return reparsed
    return None


def _extract_structured_json_object(raw_text: str) -> tuple[dict[str, Any] | None, bool]:
    direct = _parse_json_object(raw_text)
    if direct is not None:
        return direct, False
    if not str(raw_text or "").strip():
        return None, False
    repaired = _repair_json_object(raw_text)
    if repaired is not None:
        return repaired, True
    return None, True


def _split_sentences(text: str) -> list[str]:
    normalized = normalize_whitespace(text)
    if not normalized:
        return []
    parts = [part.strip() for part in CHUNK_SPLIT_SENTENCE_PATTERN.split(normalized) if part.strip()]
    return parts or [normalized]


def _split_long_text(text: str, budget: int) -> list[str]:
    sentences = _split_sentences(text)
    if not sentences:
        return []

    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for sentence in sentences:
        sentence_tokens = _count_tokens(sentence)
        if sentence_tokens > budget:
            if current:
                chunks.append(" ".join(current).strip())
                current = []
                current_tokens = 0
            window_chars = max(512, budget * 4)
            for start in range(0, len(sentence), window_chars):
                piece = sentence[start : start + window_chars].strip()
                if piece:
                    chunks.append(piece)
            continue
        if current and current_tokens + sentence_tokens > budget:
            chunks.append(" ".join(current).strip())
            current = [sentence]
            current_tokens = sentence_tokens
            continue
        current.append(sentence)
        current_tokens += sentence_tokens
    if current:
        chunks.append(" ".join(current).strip())
    return [chunk for chunk in chunks if chunk.strip()]


def _heading_from_line(line: str, has_section: bool) -> tuple[int, str] | None:
    normalized = normalize_whitespace(line)
    if not normalized or len(normalized) > 160:
        return None
    lowered = normalized.casefold().strip(":")
    if lowered in TERMINAL_SECTION_HEADINGS:
        return 1, normalized
    if lowered in COMMON_SECTION_HEADINGS:
        return 1, normalized

    numbered = NUMBERED_HEADING_PATTERN.match(normalized)
    if numbered is not None:
        depth = numbered.group("num").count(".") + 1
        title = normalize_whitespace(numbered.group("title"))
        return max(1, min(depth, 3)), title

    roman = ROMAN_HEADING_PATTERN.match(normalized)
    if roman is not None and len(normalized.split()) <= 12:
        return 1, normalize_whitespace(roman.group("title"))

    words = normalized.split()
    if len(words) <= 12 and normalized[-1] not in ".:;,":
        alpha_words = [word for word in words if any(ch.isalpha() for ch in word)]
        if alpha_words and sum(word[0].isupper() for word in alpha_words) >= max(1, len(alpha_words) - 1):
            if has_section or len(words) <= 8:
                return 1, normalized
    return None


def _extract_pdf_pages(pdf_path: Path) -> list[tuple[int, str]]:
    reader = PdfReader(str(pdf_path))
    pages: list[tuple[int, str]] = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        pages.append((index, text))
    return pages


def _parse_arxiv_url(url: str) -> str:
    normalized = normalize_whitespace(url)
    match = ARXIV_URL_PATTERN.match(normalized)
    if match is None:
        raise ValueError("Only arxiv.org/abs or arxiv.org/pdf URLs are supported.")
    arxiv_id = match.group("id")
    base_id = extract_arxiv_base_id(arxiv_id) or arxiv_id
    return base_id


def _download_arxiv_pdf(arxiv_id: str, session_dir: Path, timeout: int) -> Path:
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    response = requests.get(
        pdf_url,
        timeout=timeout,
        headers={"User-Agent": "arxiv-paper-rag/1.0"},
    )
    response.raise_for_status()
    pdf_path = session_dir / f"{arxiv_id.replace('/', '_')}.pdf"
    pdf_path.write_bytes(response.content)
    return pdf_path


def _section_label(section_title: str | None, subsection_title: str | None) -> str:
    section = normalize_whitespace(section_title or "Untitled")
    if subsection_title:
        subsection = normalize_whitespace(subsection_title)
        return f"{section} - {subsection}"
    return section


@dataclass(slots=True)
class PaperReaderChunk:
    chunk_id: str
    text: str
    section_title: str
    subsection_title: str | None
    reading_focus_key: str
    reading_focus_title: str
    page_start: int
    page_end: int
    token_estimate: int
    embedding: list[float] | None = None


@dataclass(slots=True)
class PaperReaderPagePlan:
    page_index: int
    title: str
    focus_key: str
    focus_title: str
    section_title: str
    subsection_title: str | None
    source_section_titles: list[str] = field(default_factory=list)
    chunk_ids: list[str] = field(default_factory=list)
    page_start: int = 0
    page_end: int = 0
    estimated_tokens: int = 0


@dataclass(slots=True)
class PaperReaderPageContent:
    page_index: int
    title: str
    status: str = "queued"
    coverage: str | None = None
    page_overview: PaperReaderStructuredTextModel | None = None
    insights: list[PaperReaderInsightModel] = field(default_factory=list)
    structured_status: PaperReaderStructuredStatusModel = field(default_factory=PaperReaderStructuredStatusModel)
    source_sections: list[PaperReaderSourceSectionModel] = field(default_factory=list)
    summary: str | None = None
    sections: list[PaperReaderSectionModel] = field(default_factory=list)
    key_points: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    citations: list[PaperReaderCitationModel] = field(default_factory=list)
    chunk_ids: list[str] = field(default_factory=list)
    estimated_tokens: int = 0
    page_start: int = 0
    page_end: int = 0
    generated_at: str | None = None
    error_message: str | None = None


@dataclass(slots=True)
class PaperReaderSession:
    session_id: str
    source_type: str
    source_url: str | None
    source_id: str | None
    paper_title: str
    authors: list[str]
    published_date: str | None
    answer_language: str
    pdf_path: Path
    max_context_tokens: int
    reserved_output_tokens: int
    reserved_scaffold_tokens: int
    page_input_budget: int
    settings: RuntimeSettings
    current_page_index: int = 0
    session_status: str = "active"
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    chunks: list[PaperReaderChunk] = field(default_factory=list)
    pages: list[PaperReaderPagePlan] = field(default_factory=list)
    page_contents: dict[int, PaperReaderPageContent] = field(default_factory=dict)
    page_statuses: dict[int, str] = field(default_factory=dict)


_SESSION_LOCK = threading.RLock()
_SESSION_CACHE: dict[str, PaperReaderSession] = {}
_PAGE_TASKS: dict[tuple[str, int], Future[Any]] = {}
_PAGE_EXECUTOR = ThreadPoolExecutor(max_workers=max(2, (threading.active_count() or 2)))


def _get_session(session_id: str) -> PaperReaderSession:
    session = _SESSION_CACHE.get(session_id)
    if session is None:
        raise KeyError("Paper reader session not found.")
    return session


def _touch_session(session: PaperReaderSession) -> None:
    session.updated_at = _now_iso()


def _session_title_from_pdf(pdf_path: Path, fallback: str) -> str:
    try:
        reader = PdfReader(str(pdf_path))
        metadata = reader.metadata
        title = getattr(metadata, "title", None) if metadata is not None else None
        return _normalize_title(title, fallback)
    except Exception:
        return fallback


def _build_blocks(pages: list[tuple[int, str]]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    current_section = "Abstract"
    current_subsection: str | None = None
    seen_section = False
    stop_after_references = False

    for page_number, page_text in pages:
        if stop_after_references:
            break

        lines = page_text.splitlines()
        paragraph_lines: list[str] = []

        def flush_paragraph() -> None:
            nonlocal paragraph_lines
            if not paragraph_lines:
                return
            paragraph_text = normalize_whitespace(" ".join(paragraph_lines))
            paragraph_lines = []
            if not paragraph_text:
                return
            block = {
                "text": paragraph_text,
                "section_title": current_section,
                "subsection_title": current_subsection,
                "page_start": page_number,
                "page_end": page_number,
            }
            blocks.append(block)

        for line in lines:
            stripped = line.strip()
            if not stripped:
                flush_paragraph()
                continue

            heading = _heading_from_line(stripped, seen_section)
            if heading is not None:
                flush_paragraph()
                level, heading_text = heading
                seen_section = True
                if heading_text.casefold() in TERMINAL_SECTION_HEADINGS:
                    stop_after_references = True
                    break
                if level <= 1:
                    current_section = _normalize_title(heading_text, current_section)
                    current_subsection = None
                else:
                    current_subsection = _normalize_title(heading_text, current_subsection or heading_text)
                continue

            paragraph_lines.append(stripped)

        flush_paragraph()

    return blocks


def _chunk_blocks(blocks: list[dict[str, Any]], budget: int) -> list[PaperReaderChunk]:
    chunks: list[PaperReaderChunk] = []
    for block in blocks:
        text = normalize_whitespace(block["text"])
        if not text:
            continue
        pieces = [text] if _count_tokens(text) <= budget else _split_long_text(text, budget)
        for piece in pieces:
            token_estimate = _count_tokens(piece)
            focus_key = "evidence_or_experiments"
            focus_title = _reading_focus_title(focus_key)
            chunks.append(
                PaperReaderChunk(
                    chunk_id=uuid.uuid4().hex,
                    text=piece,
                    section_title=block["section_title"],
                    subsection_title=block["subsection_title"],
                    reading_focus_key=focus_key,
                    reading_focus_title=focus_title,
                    page_start=int(block["page_start"]),
                    page_end=int(block["page_end"]),
                    token_estimate=token_estimate,
                )
            )
    return chunks


def _classify_reading_focus(chunk: PaperReaderChunk, index: int, total_chunks: int) -> tuple[str, str]:
    heading_text = " ".join(
        part for part in (chunk.section_title, chunk.subsection_title or "") if normalize_whitespace(part)
    ).casefold()
    content_text = normalize_whitespace(chunk.text).casefold()[:1200]
    position_ratio = (index + 1) / max(total_chunks, 1)

    if _contains_any_keyword(heading_text, OPEN_QUESTION_KEYWORDS) or _contains_any_keyword(content_text, OPEN_QUESTION_KEYWORDS):
        return "open_questions_or_limitations", _reading_focus_title("open_questions_or_limitations")
    if _contains_any_keyword(heading_text, CONCLUSION_KEYWORDS):
        return "conclusion", _reading_focus_title("conclusion")
    if _contains_any_keyword(heading_text, EVIDENCE_KEYWORDS) or _contains_any_keyword(content_text, EVIDENCE_KEYWORDS):
        return "evidence_or_experiments", _reading_focus_title("evidence_or_experiments")
    if _contains_any_keyword(heading_text, METHOD_KEYWORDS) or _contains_any_keyword(content_text, METHOD_KEYWORDS):
        return "method_or_mechanism", _reading_focus_title("method_or_mechanism")
    if _contains_any_keyword(heading_text, CORE_QUESTION_KEYWORDS):
        return "core_question", _reading_focus_title("core_question")
    if _contains_any_keyword(content_text, CONCLUSION_KEYWORDS) and position_ratio >= 0.75:
        return "conclusion", _reading_focus_title("conclusion")
    if position_ratio <= 0.22:
        return "core_question", _reading_focus_title("core_question")
    if position_ratio >= 0.9:
        return "conclusion", _reading_focus_title("conclusion")
    if position_ratio <= 0.6:
        return "method_or_mechanism", _reading_focus_title("method_or_mechanism")
    return "evidence_or_experiments", _reading_focus_title("evidence_or_experiments")


def _assign_reading_focuses(chunks: list[PaperReaderChunk]) -> list[PaperReaderChunk]:
    total_chunks = len(chunks)
    for index, chunk in enumerate(chunks):
        focus_key, focus_title = _classify_reading_focus(chunk, index, total_chunks)
        chunk.reading_focus_key = focus_key
        chunk.reading_focus_title = focus_title
    return chunks


def _make_page_title(title: str, page_count: int, index: int) -> str:
    if page_count <= 1:
        return title
    return f"{title} ({index + 1}/{page_count})"


def _pack_chunks_into_pages(chunks: list[PaperReaderChunk], budget: int) -> list[PaperReaderPagePlan]:
    pages: list[PaperReaderPagePlan] = []
    focus_buckets: dict[str, list[PaperReaderChunk]] = {key: [] for key, _ in READING_FOCUS_ORDER}
    for chunk in chunks:
        focus_buckets.setdefault(chunk.reading_focus_key, []).append(chunk)

    for focus_key, focus_title in READING_FOCUS_ORDER:
        focus_chunks = focus_buckets.get(focus_key) or []
        if not focus_chunks:
            continue

        current: list[PaperReaderChunk] = []
        current_tokens = 0
        current_source_section: str | None = None

        def flush_page() -> None:
            nonlocal current, current_tokens, current_source_section
            if not current:
                return
            source_section_titles = list(
                dict.fromkeys(_section_label(chunk.section_title, chunk.subsection_title) for chunk in current)
            )
            pages.append(
                PaperReaderPagePlan(
                    page_index=len(pages),
                    title=focus_title,
                    focus_key=focus_key,
                    focus_title=focus_title,
                    section_title=focus_title,
                    subsection_title=None,
                    source_section_titles=source_section_titles,
                    chunk_ids=[chunk.chunk_id for chunk in current],
                    page_start=min(chunk.page_start for chunk in current),
                    page_end=max(chunk.page_end for chunk in current),
                    estimated_tokens=current_tokens,
                )
            )
            current = []
            current_tokens = 0
            current_source_section = None

        for chunk in focus_chunks:
            semantic_boundary = (
                current
                and _section_label(chunk.section_title, chunk.subsection_title) != current_source_section
                and current_tokens >= max(1, budget // 2)
            )
            if current and (current_tokens + chunk.token_estimate > budget or semantic_boundary):
                flush_page()
            current.append(chunk)
            current_tokens += chunk.token_estimate
            current_source_section = _section_label(chunk.section_title, chunk.subsection_title)

        flush_page()

    title_groups: dict[str, list[PaperReaderPagePlan]] = {}
    for page in pages:
        title_groups.setdefault(page.focus_title, []).append(page)
    for focus_title, group in title_groups.items():
        if len(group) <= 1:
            continue
        for index, page in enumerate(group):
            page.title = _make_page_title(focus_title, len(group), index)

    for index, page in enumerate(pages):
        page.page_index = index

    return pages


def _chunks_for_plan(session: PaperReaderSession, plan: PaperReaderPagePlan) -> list[PaperReaderChunk]:
    chunk_map = {chunk.chunk_id: chunk for chunk in session.chunks}
    return [chunk_map[chunk_id] for chunk_id in plan.chunk_ids if chunk_id in chunk_map]


def _format_page_input(session: PaperReaderSession, plan: PaperReaderPagePlan) -> str:
    chunks = _chunks_for_plan(session, plan)
    parts = []
    for chunk in chunks:
        heading = _section_label(chunk.section_title, chunk.subsection_title)
        parts.append(f"[{heading} | pages {chunk.page_start}-{chunk.page_end}]\n{chunk.text}")
    return "\n\n".join(parts).strip()


def _coerce_int(value: Any, fallback: int) -> int:
    with suppress(Exception):
        return int(value)
    return fallback


def _build_source_sections(session: PaperReaderSession, plan: PaperReaderPagePlan) -> list[PaperReaderSourceSectionModel]:
    source_sections: list[PaperReaderSourceSectionModel] = []
    index_by_key: dict[tuple[str, str | None], int] = {}
    for chunk in _chunks_for_plan(session, plan):
        key = (chunk.section_title, chunk.subsection_title)
        existing_index = index_by_key.get(key)
        if existing_index is None:
            index_by_key[key] = len(source_sections)
            source_sections.append(
                PaperReaderSourceSectionModel(
                    title=chunk.section_title,
                    subsection_title=chunk.subsection_title,
                    label=_section_label(chunk.section_title, chunk.subsection_title),
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    chunk_ids=[chunk.chunk_id],
                )
            )
            continue
        existing = source_sections[existing_index]
        if chunk.chunk_id not in existing.chunk_ids:
            existing.chunk_ids.append(chunk.chunk_id)
        existing.page_start = min(existing.page_start, chunk.page_start)
        existing.page_end = max(existing.page_end, chunk.page_end)
    return source_sections


def _default_coverage_text(plan: PaperReaderPagePlan, source_sections: list[PaperReaderSourceSectionModel]) -> str | None:
    labels = [section.label for section in source_sections if section.label]
    if labels:
        return ", ".join(labels[:4])
    if plan.source_section_titles:
        return ", ".join(plan.source_section_titles[:4])
    return None


def _safe_page_error_message(answer_language: str) -> str:
    if answer_language == "zh":
        return "当前页的结构化 insight card 生成失败，请重试本页。"
    return "The page could not be converted into structured insight cards. Please retry this page."


def _safe_chat_error_message(answer_language: str) -> str:
    if answer_language == "zh":
        return "我没能把当前页证据整理成可靠的结构化回答，请在本页重试这个问题。"
    return "I could not format a reliable answer from the current page evidence. Please retry this question on this page."


def _build_page_messages(session: PaperReaderSession, plan: PaperReaderPagePlan) -> list[dict[str, str]]:
    page_text = _format_page_input(session, plan)
    answer_language = session.answer_language
    explanation_language = _reader_explanation_language(session.answer_language)
    metadata = {
        "session_id": session.session_id,
        "paper_title": session.paper_title,
        "source_type": session.source_type,
        "source_id": session.source_id,
        "page_index": plan.page_index,
        "page_title": plan.title,
        "page_range": [plan.page_start, plan.page_end],
        "reading_focus_title": plan.focus_title,
        "covered_source_sections": list(plan.source_section_titles),
        "answer_language": answer_language,
    }
    prompt = (
        "You are generating one reading page for a paper reader.\n"
        "Return a single JSON object only.\n"
        "Required top-level keys: page_title, coverage, page_overview, insights, citations.\n"
        "This paper reader paginates the full paper by document-level reading focus buckets.\n"
        f"This page belongs to the focus bucket: {plan.focus_title}.\n"
        "Do not rebuild all five global focus buckets inside this one page.\n"
        "page_overview must be an object with keys: original_en, explanation.\n"
        "insights must contain 1 to 3 insight cards for the current page only.\n"
        "Each insight item must have: title, kind, summary, evidence, source_chunk_ids.\n"
        "summary must be an object with keys: original_en, explanation.\n"
        "evidence must be an array of 0 to 3 objects, and each object must also use: original_en, explanation.\n"
        "Keep page_overview concise: at most 2 sentences per field.\n"
        "Keep each explanation concise: at most 2 sentences.\n"
        "Use only one short original_en excerpt for page_overview and one short original_en excerpt per insight summary.\n"
        "Do not serialize nested JSON as strings inside any field.\n"
        "source_chunk_ids must reference only chunk_id values from the supplied chunks.\n"
        "Each citation must include chunk_id, section_title, subsection_title, page_start, page_end, excerpt.\n"
        f"Strict language rule: keep every original_en field in English, and every explanation field in {explanation_language}.\n"
        "Do not return legacy free-text sections, markdown, or commentary outside the JSON object.\n"
        f"Metadata: {json.dumps(metadata, ensure_ascii=False)}\n"
        f"Chunks:\n{page_text}"
    )
    return [{"role": "user", "content": prompt}]


def _build_chat_messages(
    session: PaperReaderSession,
    plan: PaperReaderPagePlan,
    request: PaperReaderChatRequest,
    selected_chunks: list[PaperReaderChunk],
) -> list[dict[str, str]]:
    answer_language = _normalize_answer_language(request.answer_language, session.paper_title) or session.answer_language
    explanation_label = _reader_explanation_label(answer_language)
    explanation_language = _reader_explanation_language(answer_language)
    history_lines = [f"{item.role}: {item.text}" for item in request.history if item.text.strip()]
    chunk_lines = []
    for chunk in selected_chunks:
        title = _section_label(chunk.section_title, chunk.subsection_title)
        chunk_lines.append(
            f"[{chunk.chunk_id} | {title} | pages {chunk.page_start}-{chunk.page_end}]\n{chunk.text}"
        )
    prompt = (
        "You answer questions about a single paper using only the supplied chunks.\n"
        "Return a JSON object with the keys: answer_text, citations, used_chunks.\n"
        "Each citation must include chunk_id, section_title, subsection_title, page_start, page_end, excerpt.\n"
        "Each used_chunk must include chunk_id, section_title, subsection_title, page_start, page_end, text, token_estimate, score.\n"
        f"Strict language rule: keep the original evidence in English, and explain it only in {explanation_language}.\n"
        "The answer_text must follow this format for every major point:\n"
        "Original (EN): <short verbatim or tightly grounded English snippet from the supplied chunks>\n"
        f"{explanation_label}: <grounded explanation in {explanation_language}>\n"
        "If you need multiple points, separate them with blank lines and repeat the same format for each point.\n"
        "Do not add explanations in any other language.\n"
        f"Paper title: {session.paper_title}\n"
        f"Current page: {plan.page_index} - {plan.title}\n"
        f"Conversation history:\n{chr(10).join(history_lines) if history_lines else '(none)'}\n"
        f"Question:\n{request.message.strip()}\n"
        f"Relevant chunks:\n{chr(10).join(chunk_lines)}"
    )
    return [{"role": "user", "content": prompt}]


def _ensure_chunk_embedding(chunk: PaperReaderChunk, settings: RuntimeSettings) -> list[float]:
    if chunk.embedding is not None:
        return chunk.embedding
    chunk.embedding = get_embedding(chunk.text, settings)
    return chunk.embedding


def _select_chat_chunks(
    session: PaperReaderSession,
    page_index: int,
    request: PaperReaderChatRequest,
    settings: RuntimeSettings,
) -> tuple[PaperReaderPagePlan, list[PaperReaderChunk]]:
    if page_index < 0 or page_index >= len(session.pages):
        raise IndexError("Requested page is out of range.")
    plan = session.pages[page_index]
    page_chunk_ids = set(plan.chunk_ids)
    current_page_chunks = [chunk for chunk in session.chunks if chunk.chunk_id in page_chunk_ids]
    query_text = request.message.strip()
    if request.history:
        history_tail = " ".join(item.text for item in request.history[-3:] if item.text.strip())
        query_text = f"{history_tail} {query_text}".strip()
    query_vec = get_embedding(query_text, settings)

    scored: list[tuple[float, PaperReaderChunk]] = []
    for chunk in session.chunks:
        embedding = _ensure_chunk_embedding(chunk, settings)
        score = cosine_similarity(query_vec, embedding)
        if chunk.chunk_id in page_chunk_ids:
            score += 0.15
        if chunk.reading_focus_key == plan.focus_key:
            score += 0.08
        if _section_label(chunk.section_title, chunk.subsection_title) in plan.source_section_titles:
            score += 0.05
        scored.append((score, chunk))
    scored.sort(key=lambda item: item[0], reverse=True)

    page_candidates = [item for item in scored if item[1].chunk_id in page_chunk_ids][:6]
    global_candidates = [item for item in scored if item[1].chunk_id not in {chunk.chunk_id for _, chunk in page_candidates}][:6]
    selected = [chunk for _, chunk in page_candidates + global_candidates]

    if not selected:
        selected = current_page_chunks[:4] or session.chunks[:4]
    return plan, selected


def _normalize_chunk_id_list(raw_value: Any, allowed_chunk_ids: set[str]) -> list[str]:
    if isinstance(raw_value, str):
        candidates = [part.strip() for part in raw_value.split(",")]
    elif isinstance(raw_value, list):
        candidates = [str(item or "").strip() for item in raw_value]
    else:
        candidates = []
    chunk_ids: list[str] = []
    for chunk_id in candidates:
        if chunk_id and chunk_id in allowed_chunk_ids and chunk_id not in chunk_ids:
            chunk_ids.append(chunk_id)
    return chunk_ids


def _infer_insight_kind(raw_kind: Any, title: str, plan: PaperReaderPagePlan) -> str:
    candidate = normalize_whitespace(raw_kind or "").casefold().replace(" ", "_")
    if candidate:
        return candidate
    hint_text = f"{title} {plan.focus_key} {plan.focus_title}".casefold()
    if "limit" in hint_text or "open_question" in hint_text or "caveat" in hint_text:
        return "limitation"
    if "question" in hint_text:
        return "question"
    if "method" in hint_text or "mechanism" in hint_text or "approach" in hint_text:
        return "method"
    if "evidence" in hint_text or "experiment" in hint_text or "result" in hint_text:
        return "evidence"
    if "conclusion" in hint_text or "takeaway" in hint_text:
        return "takeaway"
    return "insight"


def _coerce_page_citations(
    raw_value: Any,
    plan: PaperReaderPagePlan,
    chunk_lookup: dict[str, PaperReaderChunk],
) -> list[PaperReaderCitationModel]:
    citations: list[PaperReaderCitationModel] = []
    raw_citations = raw_value if isinstance(raw_value, list) else []
    for item in raw_citations:
        if not isinstance(item, dict):
            continue
        chunk_id = str(item.get("chunk_id") or "").strip()
        chunk = chunk_lookup.get(chunk_id)
        citations.append(
            PaperReaderCitationModel(
                chunk_id=chunk.chunk_id if chunk is not None else (chunk_id or uuid.uuid4().hex),
                section_title=_normalize_title(
                    item.get("section_title"),
                    chunk.section_title if chunk is not None else plan.section_title,
                ),
                subsection_title=(str(item.get("subsection_title")).strip() or None)
                if item.get("subsection_title") is not None
                else (chunk.subsection_title if chunk is not None else None),
                page_start=_coerce_int(item.get("page_start"), chunk.page_start if chunk is not None else plan.page_start),
                page_end=_coerce_int(item.get("page_end"), chunk.page_end if chunk is not None else plan.page_end),
                excerpt=(str(item.get("excerpt")).strip() or None)
                if item.get("excerpt") is not None
                else (chunk.text[:240] if chunk is not None else None),
                score=float(item["score"]) if isinstance(item.get("score"), (float, int)) else None,
            )
        )
    return citations


def _build_sections_from_insights(insights: list[PaperReaderInsightModel]) -> list[PaperReaderSectionModel]:
    sections: list[PaperReaderSectionModel] = []
    for insight in insights:
        bullets = [item.display_text for item in insight.evidence if item.display_text]
        text = insight.summary.display_text if insight.summary is not None else None
        if not text and not bullets:
            continue
        sections.append(PaperReaderSectionModel(title=insight.title, text=text, bullets=bullets))
    return sections


def _collect_limitation_items(insights: list[PaperReaderInsightModel]) -> list[str]:
    limitation_items: list[str] = []
    for insight in insights:
        kind = insight.kind.casefold()
        if any(token in kind for token in ("limit", "question", "caveat", "risk", "failure")):
            if insight.summary is not None and insight.summary.display_text:
                limitation_items.append(insight.summary.display_text)
            limitation_items.extend(item.display_text for item in insight.evidence if item.display_text)
    return limitation_items


def _build_page_placeholder(
    session: PaperReaderSession,
    plan: PaperReaderPagePlan,
    *,
    status: str,
    message: str | None = None,
    repair_attempted: bool = False,
) -> PaperReaderPageContent:
    source_sections = _build_source_sections(session, plan)
    structured_state = "failed" if status == "error" else "pending"
    return PaperReaderPageContent(
        page_index=plan.page_index,
        title=plan.title,
        status=status,
        coverage=_default_coverage_text(plan, source_sections),
        structured_status=PaperReaderStructuredStatusModel(
            state=structured_state,
            message=message,
            repair_attempted=repair_attempted,
        ),
        source_sections=source_sections,
        chunk_ids=list(plan.chunk_ids),
        estimated_tokens=plan.estimated_tokens,
        page_start=plan.page_start,
        page_end=plan.page_end,
        error_message=message if status == "error" else None,
    )


def _page_content_from_output(
    session: PaperReaderSession,
    plan: PaperReaderPagePlan,
    raw_text: str,
) -> PaperReaderPageContent:
    fallback_title = plan.title
    chunk_lookup = {chunk.chunk_id: chunk for chunk in session.chunks}
    allowed_chunk_ids = set(plan.chunk_ids)
    source_sections = _build_source_sections(session, plan)
    source_section_lookup = {section.label: section for section in source_sections}
    fallback_original = ""
    for chunk_id in plan.chunk_ids:
        chunk = chunk_lookup.get(chunk_id)
        if chunk is not None:
            fallback_original = _clip_original_excerpt(chunk.text)
            break
    parsed, repair_attempted = _extract_structured_json_object(raw_text)
    if parsed is None:
        return _build_page_placeholder(
            session,
            plan,
            status="error",
            message=_safe_page_error_message(session.answer_language),
            repair_attempted=repair_attempted,
        )

    citations = _coerce_page_citations(parsed.get("citations"), plan, chunk_lookup)
    citation_lookup = {citation.chunk_id: citation for citation in citations}

    overview = _coerce_structured_block(
        parsed.get("page_overview") or parsed.get("overview") or parsed.get("summary"),
        session.answer_language,
        fallback_original,
    )

    raw_insights = parsed.get("insights") if isinstance(parsed.get("insights"), list) else []
    insights: list[PaperReaderInsightModel] = []
    for index, item in enumerate(raw_insights):
        if not isinstance(item, dict):
            continue
        title = _normalize_title(item.get("title"), f"Insight {index + 1}")
        summary_block = _coerce_structured_block(
            item.get("summary") or item.get("insight") or item.get("text"),
            session.answer_language,
            fallback_original,
        )
        evidence_blocks = [
            evidence_block
            for evidence_item in (
                item.get("evidence")
                if isinstance(item.get("evidence"), list)
                else item.get("bullets")
                if isinstance(item.get("bullets"), list)
                else item.get("supporting_points")
                if isinstance(item.get("supporting_points"), list)
                else []
            )[:3]
            if (evidence_block := _coerce_structured_inline(evidence_item, session.answer_language, fallback_original))
        ]
        source_chunk_ids = _normalize_chunk_id_list(
            item.get("source_chunk_ids") or item.get("chunk_ids") or item.get("citation_chunk_ids"),
            allowed_chunk_ids,
        )
        if not source_chunk_ids and citations:
            source_chunk_ids = [citation.chunk_id for citation in citations[:2] if citation.chunk_id in allowed_chunk_ids]
        source_section_labels = [
            _section_label(chunk_lookup[chunk_id].section_title, chunk_lookup[chunk_id].subsection_title)
            for chunk_id in source_chunk_ids
            if chunk_id in chunk_lookup
        ]
        if not source_section_labels:
            raw_labels = item.get("source_section_labels") if isinstance(item.get("source_section_labels"), list) else []
            source_section_labels = [normalize_whitespace(label) for label in raw_labels if normalize_whitespace(label)]
        insight_citations = [citation_lookup[chunk_id] for chunk_id in source_chunk_ids if chunk_id in citation_lookup]
        if not insight_citations:
            insight_citations = [_chunk_to_citation(chunk_lookup[chunk_id]) for chunk_id in source_chunk_ids if chunk_id in chunk_lookup]
        if not summary_block and not evidence_blocks:
            continue
        insights.append(
            PaperReaderInsightModel(
                insight_id=f"{plan.page_index}-{index + 1}",
                title=title,
                kind=_infer_insight_kind(item.get("kind"), title, plan),
                summary=summary_block,
                evidence=evidence_blocks,
                source_chunk_ids=source_chunk_ids,
                source_section_labels=list(dict.fromkeys(source_section_labels)),
                citations=insight_citations,
            )
        )
        if len(insights) >= 3:
            break

    if not insights:
        raw_sections = parsed.get("sections") if isinstance(parsed.get("sections"), list) else []
        for index, item in enumerate(raw_sections[:3]):
            if not isinstance(item, dict):
                continue
            title = _normalize_title(item.get("title"), f"Insight {index + 1}")
            summary_block = _coerce_structured_block(item.get("text") or item.get("summary"), session.answer_language, fallback_original)
            evidence_blocks = [
                evidence_block
                for bullet in (item.get("bullets") if isinstance(item.get("bullets"), list) else [])[:3]
                if (evidence_block := _coerce_structured_inline(bullet, session.answer_language, fallback_original))
            ]
            if not summary_block and not evidence_blocks:
                continue
            insights.append(
                PaperReaderInsightModel(
                    insight_id=f"{plan.page_index}-legacy-{index + 1}",
                    title=title,
                    kind=_infer_insight_kind(None, title, plan),
                    summary=summary_block,
                    evidence=evidence_blocks,
                    source_chunk_ids=[],
                    source_section_labels=[section.label for section in source_sections[:2]],
                    citations=citations[:2],
                )
            )

    key_point_items = parsed.get("key_points") if isinstance(parsed.get("key_points"), list) else []
    limitation_items = parsed.get("limitations") if isinstance(parsed.get("limitations"), list) else []

    if not insights:
        synthesized_summary = _coerce_structured_block(parsed.get("summary"), session.answer_language, fallback_original)
        synthesized_evidence = [
            evidence_block
            for item in (key_point_items or limitation_items)[:3]
            if (evidence_block := _coerce_structured_inline(item, session.answer_language, fallback_original))
        ]
        if synthesized_summary is not None or synthesized_evidence:
            insights.append(
                PaperReaderInsightModel(
                    insight_id=f"{plan.page_index}-fallback-1",
                    title=plan.focus_title,
                    kind=_infer_insight_kind(None, plan.focus_title, plan),
                    summary=synthesized_summary,
                    evidence=synthesized_evidence,
                    source_chunk_ids=[],
                    source_section_labels=[section.label for section in source_sections[:2]],
                    citations=citations[:2],
                )
            )

    if overview is None and insights:
        overview = insights[0].summary

    if overview is None or not insights:
        return _build_page_placeholder(
            session,
            plan,
            status="error",
            message=_safe_page_error_message(session.answer_language),
            repair_attempted=repair_attempted,
        )

    if not citations:
        citations = [_chunk_to_citation(chunk_lookup[chunk_id]) for chunk_id in plan.chunk_ids[:4] if chunk_id in chunk_lookup]

    sections = _build_sections_from_insights(insights)
    key_points = [insight.summary.display_text for insight in insights if insight.summary is not None and insight.summary.display_text]
    key_points.extend(
        item.display_text
        for item in (
            _coerce_structured_inline(value, session.answer_language, fallback_original) for value in key_point_items[:3]
        )
        if item is not None and item.display_text
    )
    key_points = list(dict.fromkeys(key_points))
    limitations = _collect_limitation_items(insights)
    limitations.extend(
        item.display_text
        for item in (
            _coerce_structured_inline(value, session.answer_language, fallback_original) for value in limitation_items[:3]
        )
        if item is not None and item.display_text
    )
    limitations = list(dict.fromkeys(limitations))
    coverage = normalize_whitespace(parsed.get("coverage") or "") or _default_coverage_text(plan, source_sections)
    title = _normalize_title(parsed.get("page_title"), fallback_title)
    return PaperReaderPageContent(
        page_index=plan.page_index,
        title=title,
        status="ready",
        coverage=coverage or None,
        page_overview=overview,
        insights=insights,
        structured_status=PaperReaderStructuredStatusModel(
            state="repaired" if repair_attempted else "ready",
            repair_attempted=repair_attempted,
            message=None,
        ),
        source_sections=source_sections,
        summary=overview.display_text,
        sections=sections,
        key_points=key_points,
        limitations=limitations,
        citations=citations,
        chunk_ids=list(plan.chunk_ids),
        estimated_tokens=plan.estimated_tokens,
        page_start=plan.page_start,
        page_end=plan.page_end,
        generated_at=_now_iso(),
    )


def _store_page_content(session: PaperReaderSession, content: PaperReaderPageContent) -> PaperReaderPageContent:
    session.page_contents[content.page_index] = content
    session.page_statuses[content.page_index] = content.status
    session.current_page_index = content.page_index
    _touch_session(session)
    return content


def _generate_page_content_internal(
    session_id: str,
    page_index: int,
    settings: RuntimeSettings,
    *,
    stream: bool = False,
) -> PaperReaderPageContent | Iterator[str]:
    with _SESSION_LOCK:
        session = _get_session(session_id)
        if page_index < 0 or page_index >= len(session.pages):
            raise IndexError("Requested page is out of range.")
        plan = session.pages[page_index]
        existing = session.page_contents.get(page_index)
        if existing is not None and existing.status == "ready":
            if stream:
                def ready_stream() -> Iterator[str]:
                    yield json.dumps(page_content_to_model(existing).model_dump(), ensure_ascii=False)

                return ready_stream()
            return existing
        status = session.page_statuses.get(page_index)
        if status == "generating":
            if stream:
                def waiting_stream() -> Iterator[str]:
                    while True:
                        with _SESSION_LOCK:
                            current = session.page_contents.get(page_index)
                            current_status = session.page_statuses.get(page_index, "queued")
                        if current is not None and current_status == "ready":
                            yield json.dumps(page_content_to_model(current).model_dump(), ensure_ascii=False)
                            return
                        if current_status == "error":
                            yield json.dumps(
                                {
                                    "status": "error",
                                    "page_index": page_index,
                                    "message": current.error_message if current else "page generation failed",
                                },
                                ensure_ascii=False,
                            )
                            return
                        time.sleep(0.2)

                return waiting_stream()
            return session.page_contents.get(page_index) or PaperReaderPageContent(
                page_index=page_index,
                title=plan.title,
                status="generating",
                estimated_tokens=plan.estimated_tokens,
                page_start=plan.page_start,
                page_end=plan.page_end,
                chunk_ids=list(plan.chunk_ids),
            )
        session.page_statuses[page_index] = "generating"
        _touch_session(session)

    chat_config = _default_paper_reader_chat_config(settings)
    messages = _build_page_messages(session, plan)

    if stream:
        def event_stream() -> Iterator[str]:
            collected: list[str] = []
            try:
                for token in stream_chat_tokens(messages, chat_config, settings.retrieval.request_timeout, settings.embedding.api_url):
                    collected.append(token)
                    yield token
                content = _page_content_from_output(session, plan, "".join(collected))
                with _SESSION_LOCK:
                    _store_page_content(session, content)
                    if page_index + 1 < len(session.pages):
                        _schedule_prefetch(session.session_id, page_index + 1, settings)
                yield json.dumps({"status": "complete", "page_index": page_index, "title": content.title}, ensure_ascii=False)
            except Exception as exc:
                error_content = PaperReaderPageContent(
                    page_index=page_index,
                    title=plan.title,
                    status="error",
                    estimated_tokens=plan.estimated_tokens,
                    page_start=plan.page_start,
                    page_end=plan.page_end,
                    chunk_ids=list(plan.chunk_ids),
                    error_message=str(exc),
                )
                with _SESSION_LOCK:
                    _store_page_content(session, error_content)
                yield json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False)

        return event_stream()

    try:
        raw_text = chat_completion(messages, chat_config, settings.retrieval.request_timeout)
        content = _page_content_from_output(session, plan, raw_text)
    except Exception as exc:
        content = PaperReaderPageContent(
            page_index=page_index,
            title=plan.title,
            status="error",
            estimated_tokens=plan.estimated_tokens,
            page_start=plan.page_start,
            page_end=plan.page_end,
            chunk_ids=list(plan.chunk_ids),
            error_message=str(exc),
        )
    with _SESSION_LOCK:
        _store_page_content(session, content)
        if content.status == "ready" and page_index + 1 < len(session.pages):
            _schedule_prefetch(session.session_id, page_index + 1, settings)
    return content


def _prefetch_page(session_id: str, page_index: int, settings: RuntimeSettings) -> None:
    with suppress(Exception):
        _generate_page_content_internal(session_id, page_index, settings, stream=False)


def _schedule_prefetch(session_id: str, page_index: int, settings: RuntimeSettings) -> None:
    key = (session_id, page_index)
    if key in _PAGE_TASKS:
        return
    _PAGE_TASKS[key] = _PAGE_EXECUTOR.submit(_prefetch_page, session_id, page_index, settings)


def _build_session(
    *,
    source_type: str,
    source_url: str | None,
    source_id: str | None,
    pdf_path: Path,
    settings: RuntimeSettings,
    answer_language: str | None = None,
    record: Any | None = None,
) -> PaperReaderSession:
    max_context_tokens = settings.paper_reader_chat.max_context_tokens
    reserved_output_tokens, reserved_scaffold_tokens, page_input_budget = _compute_budget(max_context_tokens)
    if page_input_budget <= 0:
        raise RuntimeError("paper_reader_chat.max_context_tokens is too small for the configured page budget.")
    target_page_budget = _compute_target_page_budget(page_input_budget)
    target_chunk_budget = _compute_target_chunk_budget(page_input_budget)

    pages = _extract_pdf_pages(pdf_path)
    if not pages:
        raise RuntimeError("PDF text extraction failed or returned no pages.")

    title_hint = None
    authors: list[str] = []
    published_date: str | None = None
    if record is not None:
        title_hint = getattr(record, "title", None)
        authors = list(getattr(record, "authors", []) or [])
        published_date = getattr(record, "published_date", None)
        source_id = getattr(record, "arxiv_id", None) or source_id
    paper_title = _normalize_title(title_hint, _session_title_from_pdf(pdf_path, pdf_path.stem))
    resolved_answer_language = _normalize_answer_language(answer_language, paper_title)

    blocks = _build_blocks(pages)
    if not blocks:
        raise RuntimeError("No extractable text was found in the PDF. OCR is not supported.")

    chunks = _assign_reading_focuses(_chunk_blocks(blocks, target_chunk_budget))
    if not chunks:
        raise RuntimeError("Failed to build readable chunks from the PDF text.")

    page_plans = _pack_chunks_into_pages(chunks, target_page_budget)
    if not page_plans:
        raise RuntimeError("Failed to build page plans for the paper.")

    session = PaperReaderSession(
        session_id=uuid.uuid4().hex,
        source_type=source_type,
        source_url=source_url,
        source_id=source_id,
        paper_title=paper_title,
        authors=authors,
        published_date=published_date,
        answer_language=resolved_answer_language,
        pdf_path=pdf_path,
        max_context_tokens=max_context_tokens,
        reserved_output_tokens=reserved_output_tokens,
        reserved_scaffold_tokens=reserved_scaffold_tokens,
        page_input_budget=page_input_budget,
        settings=settings,
        chunks=chunks,
        pages=page_plans,
        page_statuses={plan.page_index: "queued" for plan in page_plans},
    )
    with _SESSION_LOCK:
        _SESSION_CACHE[session.session_id] = session

    _generate_page_content_internal(session.session_id, 0, settings, stream=False)
    return session


def create_session_from_arxiv(
    url: str,
    settings: RuntimeSettings,
    *,
    answer_language: str | None = None,
) -> PaperReaderSession:
    arxiv_id = _parse_arxiv_url(url)
    record = fetch_arxiv_record(arxiv_id)
    if record is None:
        raise RuntimeError("Unable to resolve the requested arXiv paper.")
    session_dir = Path(tempfile.mkdtemp(prefix="paper-reader-"))
    pdf_path = _download_arxiv_pdf(record.arxiv_id or arxiv_id, session_dir, settings.retrieval.request_timeout)
    return _build_session(
        source_type="arxiv",
        source_url=url,
        source_id=record.arxiv_id or arxiv_id,
        pdf_path=pdf_path,
        settings=settings,
        answer_language=answer_language,
        record=record,
    )


def create_session_from_pdf_bytes(
    pdf_bytes: bytes,
    filename: str,
    settings: RuntimeSettings,
    *,
    answer_language: str | None = None,
) -> PaperReaderSession:
    if not pdf_bytes:
        raise RuntimeError("Uploaded PDF is empty.")
    if len(pdf_bytes) > 50 * 1024 * 1024:
        raise RuntimeError("Uploaded PDF is too large. The current limit is 50 MB.")
    suffix = ".pdf" if filename.lower().endswith(".pdf") else Path(filename).suffix or ".pdf"
    session_dir = Path(tempfile.mkdtemp(prefix="paper-reader-"))
    pdf_path = session_dir / f"{uuid.uuid4().hex}{suffix}"
    pdf_path.write_bytes(pdf_bytes)
    return _build_session(
        source_type="file",
        source_url=None,
        source_id=filename,
        pdf_path=pdf_path,
        settings=settings,
        answer_language=answer_language,
        record=None,
    )


def get_session(session_id: str) -> PaperReaderSession:
    with _SESSION_LOCK:
        return _get_session(session_id)


def get_session_settings(session_id: str) -> RuntimeSettings:
    with _SESSION_LOCK:
        session = _get_session(session_id)
        return session.settings


def get_page_content(session_id: str, page_index: int) -> PaperReaderPageContent:
    with _SESSION_LOCK:
        session = _get_session(session_id)
        if page_index < 0 or page_index >= len(session.pages):
            raise IndexError("Requested page is out of range.")
        content = session.page_contents.get(page_index)
        if content is None:
            plan = session.pages[page_index]
            return PaperReaderPageContent(
                page_index=plan.page_index,
                title=plan.title,
                status=session.page_statuses.get(page_index, "queued"),
                estimated_tokens=plan.estimated_tokens,
                page_start=plan.page_start,
                page_end=plan.page_end,
                chunk_ids=list(plan.chunk_ids),
            )
        session.current_page_index = page_index
        _touch_session(session)
        return content


def stream_page_content_tokens(session_id: str, page_index: int, settings: RuntimeSettings) -> Iterator[str]:
    result = _generate_page_content_internal(session_id, page_index, settings, stream=True)
    if isinstance(result, Iterator):
        yield from result
    elif isinstance(result, PaperReaderPageContent):
        yield json.dumps(page_content_to_model(result).model_dump(), ensure_ascii=False)


def _chunk_to_model(chunk: PaperReaderChunk, score: float | None = None) -> PaperReaderChunkModel:
    return PaperReaderChunkModel(
        chunk_id=chunk.chunk_id,
        section_title=chunk.section_title,
        subsection_title=chunk.subsection_title,
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        text=chunk.text,
        token_estimate=chunk.token_estimate,
        score=score,
    )


def _chunk_to_citation(chunk: PaperReaderChunk, score: float | None = None) -> PaperReaderCitationModel:
    return PaperReaderCitationModel(
        chunk_id=chunk.chunk_id,
        section_title=chunk.section_title,
        subsection_title=chunk.subsection_title,
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        excerpt=chunk.text[:240],
        score=score,
    )


def chat_with_paper(
    session_id: str,
    request: PaperReaderChatRequest,
    settings: RuntimeSettings,
) -> PaperReaderChatResponse:
    with _SESSION_LOCK:
        session = _get_session(session_id)
        page_index = request.page_index if request.page_index is not None else session.current_page_index
        plan, selected_chunks = _select_chat_chunks(session, page_index, request, settings)
        session.current_page_index = page_index
        _touch_session(session)

    chat_config = _default_paper_reader_chat_config(settings)
    messages = _build_chat_messages(session, plan, request, selected_chunks)
    raw_text = chat_completion(messages, chat_config, settings.retrieval.request_timeout)
    answer_language = _normalize_answer_language(request.answer_language, session.paper_title) or session.answer_language
    fallback_original = _clip_original_excerpt(selected_chunks[0].text) if selected_chunks else ""

    parsed, _repair_attempted = _extract_structured_json_object(raw_text)
    if parsed is None:
        parsed = {}

    answer_text = _ensure_reader_block_text(parsed.get("answer_text"), answer_language, fallback_original)
    if not answer_text:
        answer_text = _ensure_reader_block_text(_safe_chat_error_message(answer_language), answer_language, fallback_original) or ""
    citations = []
    raw_citations = parsed.get("citations") if isinstance(parsed.get("citations"), list) else []
    citation_lookup = {chunk.chunk_id: chunk for chunk in selected_chunks}
    for item in raw_citations:
        if not isinstance(item, dict):
            continue
        chunk_id = str(item.get("chunk_id") or "").strip()
        chunk = citation_lookup.get(chunk_id)
        citations.append(
            PaperReaderCitationModel(
                chunk_id=chunk_id or uuid.uuid4().hex,
                section_title=_normalize_title(item.get("section_title"), chunk.section_title if chunk else plan.section_title),
                subsection_title=(str(item.get("subsection_title")).strip() or None)
                if item.get("subsection_title") is not None
                else (chunk.subsection_title if chunk else None),
                page_start=int(item.get("page_start") or (chunk.page_start if chunk else plan.page_start)),
                page_end=int(item.get("page_end") or (chunk.page_end if chunk else plan.page_end)),
                excerpt=(str(item.get("excerpt")).strip() or None) if item.get("excerpt") is not None else (chunk.text[:240] if chunk else None),
                score=float(item["score"]) if isinstance(item.get("score"), (float, int)) else None,
            )
        )
    if not citations:
        citations = [_chunk_to_citation(chunk) for chunk in selected_chunks[:4]]

    used_chunks_raw = parsed.get("used_chunks") if isinstance(parsed.get("used_chunks"), list) else []
    used_chunks: list[PaperReaderChunkModel] = []
    used_lookup = {chunk.chunk_id: chunk for chunk in selected_chunks}
    for item in used_chunks_raw:
        if not isinstance(item, dict):
            continue
        chunk_id = str(item.get("chunk_id") or "").strip()
        chunk = used_lookup.get(chunk_id)
        if chunk is None:
            continue
        used_chunks.append(
            PaperReaderChunkModel(
                chunk_id=chunk.chunk_id,
                section_title=chunk.section_title,
                subsection_title=chunk.subsection_title,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                text=chunk.text,
                token_estimate=chunk.token_estimate,
                score=float(item["score"]) if isinstance(item.get("score"), (float, int)) else None,
            )
        )
    if not used_chunks:
        used_chunks = [_chunk_to_model(chunk) for chunk in selected_chunks[:6]]

    return PaperReaderChatResponse(
        session_id=session_id,
        page_index=plan.page_index,
        page_title=plan.title,
        answer_text=answer_text,
        citations=citations,
        used_chunks=used_chunks,
    )


def session_to_model(session: PaperReaderSession) -> PaperReaderSessionModel:
    pages = [
        PaperReaderPageManifestModel(
            page_index=plan.page_index,
            title=plan.title,
            status=session.page_statuses.get(plan.page_index, "queued"),
            estimated_tokens=plan.estimated_tokens,
            chunk_count=len(plan.chunk_ids),
            page_start=plan.page_start,
            page_end=plan.page_end,
        )
        for plan in session.pages
    ]
    return PaperReaderSessionModel(
        session_id=session.session_id,
        source_type=session.source_type,
        source_url=session.source_url,
        source_id=session.source_id,
        paper_title=session.paper_title,
        authors=list(session.authors),
        published_date=session.published_date,
        answer_language=_normalize_answer_language(session.answer_language, session.paper_title),
        max_context_tokens=session.max_context_tokens,
        page_input_budget=session.page_input_budget,
        current_page_index=session.current_page_index,
        page_count=len(session.pages),
        session_status=session.session_status,
        pages=pages,
    )


def page_content_to_model(content: PaperReaderPageContent) -> PaperReaderPageContentModel:
    return PaperReaderPageContentModel(
        page_index=content.page_index,
        title=content.title,
        status=content.status,
        coverage=content.coverage,
        page_overview=content.page_overview,
        insights=list(content.insights),
        structured_status=content.structured_status,
        source_sections=list(content.source_sections),
        summary=content.summary,
        sections=list(content.sections),
        key_points=list(content.key_points),
        limitations=list(content.limitations),
        citations=list(content.citations),
        chunk_ids=list(content.chunk_ids),
        estimated_tokens=content.estimated_tokens,
        page_start=content.page_start,
        page_end=content.page_end,
        generated_at=content.generated_at,
        error=content.error_message,
    )
