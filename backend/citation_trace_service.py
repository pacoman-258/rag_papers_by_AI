from __future__ import annotations

import json
import re
import tempfile
import uuid
from dataclasses import dataclass, field, replace
from io import BytesIO
from pathlib import Path
from typing import Any, Iterator, Literal

from pypdf import PdfReader

from local_paper_db.app.external_sources import fetch_arxiv_record, resolve_arxiv_candidates
from local_paper_db.app.search_service import (
    TargetPaper,
    build_canonical_paper_id,
    build_target_paper_retrieval_text,
    chat_completion,
    collect_prior_work_candidates,
    extract_first_json_object,
    get_embedding,
    normalize_whitespace,
)


PaperNodeSource = Literal["target", "arxiv", "local", "wos", "unresolved"]
CitationRelationType = Literal["explicit_reference", "retrieved_similar", "llm_inferred_influence"]
EvidenceLevel = Literal["strong", "medium", "weak"]
RoundStatus = Literal["pending", "running", "completed", "partial", "failed"]

REFERENCE_HEADING_PATTERN = re.compile(r"^\s*(references|bibliography)\s*$", re.IGNORECASE | re.MULTILINE)
NEXT_SECTION_PATTERN = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*\.?\s+)?(appendix|supplementary materials?|acknowledg(?:e)?ments?)\b",
    re.IGNORECASE,
)
ARXIV_ID_PATTERN = re.compile(r"\barxiv\s*:\s*(\d{4}\.\d{4,5})(?:v\d+)?\b", re.IGNORECASE)
DOI_PATTERN = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.IGNORECASE)
YEAR_PATTERN = re.compile(r"\b(19\d{2}|20\d{2})\b")
REFERENCE_SPLIT_PATTERN = re.compile(r"(?m)^\s*(?P<label>\[\d+\]|(?!(?:19|20)\d{2}\.)\d+\.)\s+")
REFERENCE_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<!\b[A-Z])\.\s+")
REFERENCE_ARXIV_TRAILING_YEAR_PATTERN = re.compile(r"\s*[,;]?\s*(?:19|20)\d{2}[a-z]?\.", re.IGNORECASE)
REFERENCE_YEAR_BOUNDARY_PATTERN = re.compile(r"\b(?:19|20)\d{2}[a-z]?\.\s+", re.IGNORECASE)
REFERENCE_SECTION_PROMPT_CHAR_LIMIT = 50000
REFERENCE_WORKER_MAX_REFERENCES = 200
ARXIV_URL_PATTERN = re.compile(
    r"^https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/(?P<id>\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?/?(?:[?#].*)?$",
    re.IGNORECASE,
)
NON_REFERENCE_FRAGMENT_PATTERN = re.compile(
    r"\b(algorithm|appendix|ablation|kernel|require:|write:|section|figure|table|"
    r"supplementary criteria|accuracy|completeness|public prosecutor)\b|[→←▷]",
    re.IGNORECASE,
)
TOPIC_STOPWORDS = {
    "about",
    "after",
    "also",
    "among",
    "and",
    "are",
    "around",
    "based",
    "been",
    "being",
    "between",
    "both",
    "can",
    "could",
    "from",
    "has",
    "have",
    "into",
    "its",
    "language",
    "model",
    "models",
    "more",
    "our",
    "paper",
    "preprint",
    "show",
    "study",
    "such",
    "than",
    "that",
    "the",
    "their",
    "these",
    "this",
    "through",
    "use",
    "using",
    "via",
    "we",
    "where",
    "while",
    "with",
}
SHORT_TOPIC_TOKENS = {"ai", "fp4", "fp8", "kv", "llm"}
TOKEN_ALIASES = {
    "cached": "cache",
    "caches": "cache",
    "caching": "cache",
    "agents": "agent",
    "apis": "api",
    "codebooks": "codebook",
    "compressing": "compression",
    "compressions": "compression",
    "quantisations": "quantization",
    "quantisation": "quantization",
    "quantizations": "quantization",
    "quantized": "quantization",
    "quantizing": "quantization",
    "rotations": "rotation",
    "serving": "serve",
    "tools": "tool",
}


@dataclass(slots=True)
class ReferenceEntry:
    reference_id: str
    raw_text: str
    raw_label: str | None = None
    arxiv_id: str | None = None
    doi: str | None = None
    year: str | None = None
    title_hint: str | None = None


@dataclass(slots=True)
class CitationTracePaperNode:
    paper_id: str
    source: PaperNodeSource
    source_id: str
    canonical_id: str
    title: str
    abstract: str = ""
    authors: list[str] = field(default_factory=list)
    published_date: str | None = None
    keywords: list[str] = field(default_factory=list)
    arxiv_id: str | None = None
    doi: str | None = None
    external_url: str | None = None


@dataclass(slots=True)
class CitationTraceScoreBreakdown:
    abstract_similarity: float = 0.0
    title_overlap: float = 0.0
    keyword_overlap: float = 0.0
    author_overlap: float = 0.0
    date_plausibility: float = 0.0
    reference_match: float = 0.0


@dataclass(slots=True)
class CitationTraceLedgerEntry:
    entry_id: str
    candidate_paper: CitationTracePaperNode
    seed_paper: CitationTracePaperNode | None
    round: int
    relation_type: CitationRelationType
    evidence_level: EvidenceLevel
    score_total: float
    score_breakdown: CitationTraceScoreBreakdown
    reference_text: str | None = None
    metadata_evidence: list[str] = field(default_factory=list)
    llm_assessment: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CitationTraceTopPaper:
    rank: int
    paper_id: str
    title: str
    influence_area: str
    reason: str
    evidence_level: EvidenceLevel
    is_explicitly_cited: bool
    is_exploratory: bool
    why_worth_reading: str
    uncertainty: str
    supporting_edge_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CitationTraceRoundSummary:
    round: int
    status: RoundStatus
    seed_count: int = 0
    candidate_count: int = 0
    selected_count: int = 0
    summary_text: str | None = None
    seed_paper_ids: list[str] = field(default_factory=list)
    ledger_entries: list[CitationTraceLedgerEntry] = field(default_factory=list)
    top_papers: list[CitationTraceTopPaper] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CitationTraceSession:
    session_id: str
    source_type: Literal["arxiv", "file"]
    source_id: str | None
    source_url: str | None
    target_paper: CitationTracePaperNode
    answer_language: str = "zh"
    status: RoundStatus = "pending"
    rounds: list[CitationTraceRoundSummary] = field(default_factory=list)
    ledger_entries: list[CitationTraceLedgerEntry] = field(default_factory=list)
    final_top5: list[CitationTraceTopPaper] = field(default_factory=list)
    reference_entries: list[ReferenceEntry] = field(default_factory=list)
    pdf_text: str = ""
    warnings: list[str] = field(default_factory=list)


_SESSION_CACHE: dict[str, CitationTraceSession] = {}
_SESSION_SETTINGS_CACHE: dict[str, Any] = {}


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def cache_session_settings(session_id: str, settings: Any) -> None:
    if session_id and settings is not None:
        _SESSION_SETTINGS_CACHE[session_id] = settings


def get_cached_session_settings(session_id: str) -> Any | None:
    return _SESSION_SETTINGS_CACHE.get(session_id)


def _arxiv_id_from_url(url: str) -> str:
    value = normalize_whitespace(url)
    match = ARXIV_URL_PATTERN.match(value)
    if match is None:
        raise ValueError("Only arxiv.org/abs or arxiv.org/pdf URLs are supported.")
    return match.group("id")


def _request_timeout(settings: Any) -> int:
    timeout = getattr(getattr(settings, "retrieval", None), "request_timeout", None)
    try:
        parsed = int(timeout)
    except (TypeError, ValueError):
        return 30
    return parsed if parsed > 0 else 30


def _pdf_reader_to_text(reader: PdfReader) -> str:
    page_texts: list[str] = []
    for page in reader.pages:
        page_texts.append(page.extract_text() or "")
    return "\n\n".join(page_texts).strip()


def pdf_bytes_to_text(content: bytes) -> str:
    if not content or not content.strip():
        raise ValueError("Uploaded PDF is empty.")
    if b"%%EOF" not in content:
        raise ValueError("Uploaded file is not a valid PDF.")
    try:
        reader = PdfReader(BytesIO(content))
        text = _pdf_reader_to_text(reader)
    except Exception as exc:
        raise ValueError("Uploaded file is not a valid PDF.") from exc
    if not normalize_whitespace(text):
        raise ValueError("Uploaded PDF has no extractable text.")
    return text


def _safe_uploaded_filename(filename: str | None) -> str:
    normalized = normalize_whitespace(filename or "paper.pdf").replace("\\", "/")
    basename = Path(normalized).name.strip()
    if not basename or basename in {".", ".."}:
        return "paper.pdf"
    return basename


def download_arxiv_pdf_text(arxiv_id: str, settings: Any) -> str:
    from backend.paper_reader_service import _download_arxiv_pdf

    with tempfile.TemporaryDirectory(prefix="citation-trace-arxiv-") as temp_dir:
        pdf_path = _download_arxiv_pdf(arxiv_id, Path(temp_dir), _request_timeout(settings))
        reader = PdfReader(str(pdf_path))
        return _pdf_reader_to_text(reader)


def _paper_node_from_arxiv_record(record: Any, fallback_arxiv_id: str, source_url: str) -> CitationTracePaperNode:
    resolved_arxiv_id = (
        _normalize_arxiv_id(getattr(record, "arxiv_id", None))
        or _normalize_arxiv_id(getattr(record, "source_id", None))
        or fallback_arxiv_id
    )
    authors = [normalize_whitespace(author) for author in list(getattr(record, "authors", []) or [])]
    title = normalize_whitespace(getattr(record, "title", "") or f"arXiv {resolved_arxiv_id}")
    abstract = normalize_whitespace(getattr(record, "summary", "") or "")
    published_date = getattr(record, "published_date", None)
    doi = getattr(record, "doi", None)
    primary_category = getattr(record, "primary_category", None)
    external_url = getattr(record, "external_url", None) or source_url
    canonical_id = build_canonical_paper_id(
        title=title,
        authors=authors,
        published_date=published_date,
        arxiv_id=resolved_arxiv_id,
        doi=doi,
    )
    return CitationTracePaperNode(
        paper_id="target",
        source="target",
        source_id=resolved_arxiv_id,
        canonical_id=canonical_id,
        title=title,
        abstract=abstract,
        authors=authors,
        published_date=published_date,
        keywords=[primary_category] if primary_category else [],
        arxiv_id=resolved_arxiv_id,
        doi=doi,
        external_url=external_url,
    )


def create_session_from_arxiv(
    url: str,
    settings: Any,
    answer_language: str | None = None,
) -> CitationTraceSession:
    source_id = _arxiv_id_from_url(url)
    record = fetch_arxiv_record(source_id)
    if record is None:
        raise RuntimeError("Unable to resolve the requested arXiv paper.")
    resolved_source_id = (
        _normalize_arxiv_id(getattr(record, "arxiv_id", None))
        or _normalize_arxiv_id(getattr(record, "source_id", None))
        or source_id
    )
    pdf_text = download_arxiv_pdf_text(resolved_source_id, settings)
    reference_entries = extract_reference_entries(pdf_text)
    session_id_suffix = re.sub(r"[^A-Za-z0-9_.-]+", "-", source_id).strip("-") or "arxiv"
    target_paper = _paper_node_from_arxiv_record(record, source_id, url)
    session = CitationTraceSession(
        session_id=f"citation-trace-{session_id_suffix}-{uuid.uuid4().hex[:12]}",
        source_type="arxiv",
        source_id=resolved_source_id,
        source_url=url,
        target_paper=target_paper,
        answer_language=answer_language or "zh",
        reference_entries=reference_entries,
        pdf_text=pdf_text,
    )
    _SESSION_CACHE[session.session_id] = session
    cache_session_settings(session.session_id, settings)
    return session


def create_session_from_pdf_bytes(
    filename: str,
    content: bytes,
    settings: Any,
    answer_language: str | None = None,
) -> CitationTraceSession:
    normalized_filename = _safe_uploaded_filename(filename)
    pdf_text = pdf_bytes_to_text(content)
    target_paper = CitationTracePaperNode(
        paper_id="target",
        source="target",
        source_id=normalized_filename,
        canonical_id=f"file:{normalized_filename}",
        title=normalized_filename,
        abstract=normalize_whitespace(pdf_text)[:1200],
    )
    session = CitationTraceSession(
        session_id=f"citation-trace-file-{uuid.uuid4().hex[:12]}",
        source_type="file",
        source_id=normalized_filename,
        source_url=None,
        target_paper=target_paper,
        answer_language=answer_language or "zh",
        reference_entries=extract_reference_entries(pdf_text),
        pdf_text=pdf_text,
    )
    _SESSION_CACHE[session.session_id] = session
    cache_session_settings(session.session_id, settings)
    return session


def get_session(session_id: str) -> CitationTraceSession:
    try:
        return _SESSION_CACHE[session_id]
    except KeyError as exc:
        raise KeyError("Citation trace session not found.") from exc


def _title_hint_from_reference(text: str) -> str | None:
    normalized = normalize_whitespace(text)
    if not normalized:
        return None
    without_label = re.sub(r"^(\[\d+\]|\d+\.)\s*", "", normalized).strip()
    pieces = [piece.strip() for piece in REFERENCE_SENTENCE_SPLIT_PATTERN.split(without_label) if piece.strip()]
    for piece in pieces[1:4]:
        if len(piece.split()) >= 3 and not YEAR_PATTERN.fullmatch(piece):
            return piece[:240]
    return pieces[0][:240] if pieces else normalized[:240]


def _coerce_reference(label: str | None, text: str) -> ReferenceEntry:
    normalized = normalize_whitespace(text)
    arxiv_match = ARXIV_ID_PATTERN.search(normalized)
    doi_match = DOI_PATTERN.search(normalized)
    year_match = YEAR_PATTERN.search(normalized)
    return ReferenceEntry(
        reference_id=_new_id("ref"),
        raw_text=normalized,
        raw_label=label,
        arxiv_id=arxiv_match.group(1) if arxiv_match else None,
        doi=doi_match.group(0) if doi_match else None,
        year=year_match.group(1) if year_match else None,
        title_hint=_title_hint_from_reference(normalized),
    )


def _trim_collapsed_reference_prefix(segment: str, arxiv_start: int) -> str:
    prefix = segment[:arxiv_start]
    boundaries = list(REFERENCE_YEAR_BOUNDARY_PATTERN.finditer(prefix))
    if not boundaries:
        return segment.strip()
    trimmed = segment[boundaries[-1].end() :].strip()
    return trimmed if len(trimmed.split()) >= 4 else segment.strip()


def _iter_unlabeled_reference_paragraph_chunks(paragraph: str) -> Iterator[str]:
    normalized = normalize_whitespace(paragraph)
    if not normalized:
        return
    arxiv_matches = list(ARXIV_ID_PATTERN.finditer(normalized))
    if not arxiv_matches:
        yield normalized
        return

    previous_end = 0
    for match in arxiv_matches:
        if match.start() < previous_end:
            continue
        segment_end = match.end()
        trailing_match = REFERENCE_ARXIV_TRAILING_YEAR_PATTERN.match(normalized[segment_end : segment_end + 40])
        if trailing_match is not None:
            segment_end += trailing_match.end()
        segment = normalized[previous_end:segment_end].strip()
        relative_arxiv_start = max(0, match.start() - previous_end)
        trimmed = _trim_collapsed_reference_prefix(segment, relative_arxiv_start)
        if trimmed:
            yield trimmed
        previous_end = segment_end

    tail = normalize_whitespace(normalized[previous_end:])
    if tail:
        yield tail


def _iter_reference_chunks(reference_text: str) -> Iterator[tuple[str | None, str]]:
    matches = list(REFERENCE_SPLIT_PATTERN.finditer(reference_text))
    if not matches:
        for paragraph in re.split(r"\n\s*\n", reference_text):
            for chunk in _iter_unlabeled_reference_paragraph_chunks(paragraph):
                yield None, chunk
        return
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(reference_text)
        chunk = normalize_whitespace(reference_text[start:end])
        if chunk:
            yield match.group("label"), chunk


def extract_reference_section_text(pdf_text: str) -> str:
    match = REFERENCE_HEADING_PATTERN.search(pdf_text or "")
    if match is None:
        return ""
    tail = pdf_text[match.end() :]
    kept_lines: list[str] = []
    for line in tail.splitlines():
        if NEXT_SECTION_PATTERN.match(line):
            break
        kept_lines.append(line)
    return "\n".join(kept_lines).strip()


def extract_reference_entries(pdf_text: str) -> list[ReferenceEntry]:
    reference_text = extract_reference_section_text(pdf_text)
    if not reference_text:
        return []
    return [_coerce_reference(label, chunk) for label, chunk in _iter_reference_chunks(reference_text)]


def _worker_reference_resolution_messages(
    session: CitationTraceSession,
    reference_text: str,
) -> list[dict[str, str]]:
    fallback_preview = [
        {
            "raw_text": entry.raw_text,
            "title_hint": entry.title_hint,
            "arxiv_id": entry.arxiv_id,
            "doi": entry.doi,
            "year": entry.year,
        }
        for entry in session.reference_entries[:30]
    ]
    clipped_reference_text = reference_text[:REFERENCE_SECTION_PROMPT_CHAR_LIMIT]
    return [
        {
            "role": "system",
            "content": (
                "Extract bibliography references from a paper References/Bibliography section. "
                "Return exactly one JSON object with key references. references must be a list "
                "of objects with raw_text, title_hint, arxiv_id, doi, and year. Use null when "
                "a field is absent. Use only text that appears in the supplied References section; "
                "do not invent papers, identifiers, authors, or years. Exclude appendix prose, "
                "rubrics, prompts, review criteria, algorithm text, and any fragment that is not "
                "a bibliography entry. Preserve enough raw_text for provenance."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Target paper title: {session.target_paper.title}\n\n"
                "Rule parser preview, may contain noisy fragments:\n"
                f"{json.dumps(fallback_preview, ensure_ascii=False)}\n\n"
                "References section text:\n"
                f"{clipped_reference_text}"
            ),
        },
    ]


def _string_or_none(value: Any) -> str | None:
    normalized = normalize_whitespace(str(value)) if value is not None else ""
    return normalized or None


def _worker_reference_entry_from_item(item: Any) -> ReferenceEntry | None:
    if not isinstance(item, dict):
        return None
    raw_text = _string_or_none(item.get("raw_text") or item.get("reference") or item.get("citation"))
    title_hint = _string_or_none(item.get("title_hint") or item.get("title"))
    if raw_text is None:
        raw_text = title_hint
    if raw_text is None or not raw_text.strip(" .;:"):
        return None

    arxiv_id = (
        _normalize_arxiv_id(item.get("arxiv_id"))
        or _normalize_arxiv_id(raw_text)
    )
    doi = _normalize_doi(item.get("doi")) or _normalize_doi(raw_text)
    year_value = _string_or_none(item.get("year"))
    year_match = YEAR_PATTERN.search(year_value or "") or YEAR_PATTERN.search(raw_text)
    year = year_match.group(1) if year_match else None
    entry = ReferenceEntry(
        reference_id=_new_id("ref"),
        raw_text=raw_text,
        raw_label=None,
        arxiv_id=arxiv_id,
        doi=doi,
        year=year,
        title_hint=(title_hint or _title_hint_from_reference(raw_text) or "")[:240] or None,
    )
    return None if _is_non_reference_fragment(entry) else entry


def _worker_reference_entries_from_payload(payload: dict[str, Any]) -> list[ReferenceEntry]:
    raw_items = payload.get("references")
    if not isinstance(raw_items, list):
        return []
    entries: list[ReferenceEntry] = []
    seen: set[str] = set()
    for item in raw_items[:REFERENCE_WORKER_MAX_REFERENCES]:
        entry = _worker_reference_entry_from_item(item)
        if entry is None:
            continue
        dedupe_key = (
            entry.arxiv_id
            or entry.doi
            or normalize_whitespace(entry.raw_text).casefold()
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        entries.append(entry)
    return entries


def resolve_references_with_worker(
    session: CitationTraceSession,
    settings: Any,
) -> list[ReferenceEntry]:
    config = getattr(settings, "citation_trace_worker_chat", None)
    reference_text = extract_reference_section_text(session.pdf_text)
    if config is None or not reference_text:
        return session.reference_entries
    try:
        raw = chat_completion(
            _worker_reference_resolution_messages(session, reference_text),
            config,
            _request_timeout_from_settings(settings),
        )
        parsed = extract_first_json_object(raw)
        worker_entries = _worker_reference_entries_from_payload(parsed)
    except Exception as exc:
        session.warnings.append(f"Worker reference parsing failed; using rule parser fallback: {exc}")
        return session.reference_entries

    if not worker_entries:
        session.warnings.append("Worker reference parsing returned no usable references; using rule parser fallback.")
        return session.reference_entries
    session.reference_entries = worker_entries
    return session.reference_entries


def build_unresolved_reference_record(
    reference: ReferenceEntry,
    *,
    seed_paper_id: str,
) -> tuple[CitationTracePaperNode, CitationTraceLedgerEntry]:
    title = reference.title_hint or reference.raw_text[:120] or "Unresolved reference"
    node = CitationTracePaperNode(
        paper_id=_new_id("paper"),
        source="unresolved",
        source_id=reference.reference_id,
        canonical_id=f"unresolved:{reference.reference_id}",
        title=title,
        abstract=reference.raw_text,
        doi=reference.doi,
        arxiv_id=reference.arxiv_id,
    )
    seed = CitationTracePaperNode(
        paper_id=seed_paper_id,
        source="target",
        source_id=seed_paper_id,
        canonical_id=seed_paper_id,
        title="Target paper",
    )
    entry = CitationTraceLedgerEntry(
        entry_id=_new_id("ledger"),
        candidate_paper=node,
        seed_paper=seed,
        round=1,
        relation_type="explicit_reference",
        evidence_level="weak",
        score_total=0.15,
        score_breakdown=CitationTraceScoreBreakdown(reference_match=0.3),
        reference_text=reference.raw_text,
        metadata_evidence=[],
        warnings=["Unresolved reference"],
    )
    return node, entry


def _token_set(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", normalize_whitespace(text).casefold())
        if len(token) > 2
    }


def _canonical_topic_token(token: str) -> str:
    normalized = TOKEN_ALIASES.get(token, token)
    if normalized.endswith("ies") and len(normalized) > 4:
        return f"{normalized[:-3]}y"
    if normalized.endswith("s") and len(normalized) > 4:
        return normalized[:-1]
    return normalized


def _topic_token_set(text: str) -> set[str]:
    tokens: set[str] = set()
    for raw_token in re.findall(r"[a-z0-9]+", normalize_whitespace(str(text)).casefold()):
        token = _canonical_topic_token(raw_token)
        if token in TOPIC_STOPWORDS:
            continue
        if len(token) <= 2 and token not in SHORT_TOPIC_TOKENS:
            continue
        if token.isdigit() and len(token) == 4:
            continue
        tokens.add(token)
    return tokens


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _token_recall(query_tokens: set[str], document_tokens: set[str]) -> float:
    if not query_tokens or not document_tokens:
        return 0.0
    return len(query_tokens & document_tokens) / len(query_tokens)


def _token_precision(query_tokens: set[str], document_tokens: set[str]) -> float:
    if not query_tokens or not document_tokens:
        return 0.0
    return len(query_tokens & document_tokens) / len(document_tokens)


def _token_f1(left: set[str], right: set[str]) -> float:
    precision = _token_precision(left, right)
    recall = _token_recall(left, right)
    if precision <= 0.0 or recall <= 0.0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _target_relevance_score(target: CitationTracePaperNode, candidate: CitationTracePaperNode) -> float:
    target_title_tokens = _topic_token_set(target.title)
    target_text_tokens = _topic_token_set(
        " ".join([target.title, target.abstract, " ".join(target.keywords)])
    )
    candidate_title_tokens = _topic_token_set(candidate.title)
    candidate_text_tokens = _topic_token_set(
        " ".join([candidate.title, candidate.abstract, " ".join(candidate.keywords)])
    )
    title_alignment = _token_f1(target_title_tokens, candidate_title_tokens)
    target_title_coverage = _token_recall(target_title_tokens, candidate_text_tokens)
    topic_alignment = _token_f1(target_text_tokens, candidate_text_tokens)
    return min(1.0, max(title_alignment, target_title_coverage * 0.85, topic_alignment))


def _reference_title_similarity(query: str, candidate: CitationTracePaperNode) -> float:
    query_tokens = _topic_token_set(query)
    title_tokens = _topic_token_set(candidate.title)
    if not query_tokens or not title_tokens:
        return 0.0
    return max(_token_f1(query_tokens, title_tokens), _token_recall(query_tokens, title_tokens) * 0.85)


def _is_non_reference_fragment(reference: ReferenceEntry) -> bool:
    text = normalize_whitespace(reference.raw_text or "")
    if reference.arxiv_id or reference.doi:
        return False
    if reference.year:
        return False
    if not text:
        return True
    if NON_REFERENCE_FRAGMENT_PATTERN.search(text):
        return True
    tokens = _topic_token_set(text)
    punctuation_density = sum(1 for char in text if char in "=;:()[]{}") / max(len(text), 1)
    return len(tokens) > 45 and punctuation_density > 0.04


def _date_plausibility(seed_date: str | None, candidate_date: str | None) -> float:
    if not seed_date or not candidate_date:
        return 0.25
    return 1.0 if candidate_date <= seed_date else 0.0


def _normalize_arxiv_id(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"(\d{4}\.\d{4,5})(?:v\d+)?", value, re.IGNORECASE)
    return match.group(1) if match else None


def _normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    normalized = normalize_whitespace(value).casefold()
    normalized = re.sub(r"^(doi:\s*|https?://(?:dx\.)?doi\.org/)", "", normalized)
    match = DOI_PATTERN.search(normalized)
    doi = match.group(0) if match else normalized
    return doi.rstrip(".,;") or None


def _candidate_arxiv_ids(candidate: CitationTracePaperNode) -> set[str]:
    values = [
        candidate.arxiv_id,
        candidate.source_id if candidate.source == "arxiv" else None,
        candidate.canonical_id,
    ]
    return {arxiv_id for value in values if (arxiv_id := _normalize_arxiv_id(value))}


def _candidate_dois(candidate: CitationTracePaperNode) -> set[str]:
    values = [candidate.doi, candidate.source_id, candidate.canonical_id]
    return {doi for value in values if (doi := _normalize_doi(value)) and doi.startswith("10.")}


def _reference_metadata_match(candidate: CitationTracePaperNode, reference_text: str | None) -> float:
    if not reference_text:
        return 0.0
    reference_arxiv_ids = {
        arxiv_id for value in ARXIV_ID_PATTERN.findall(reference_text) if (arxiv_id := _normalize_arxiv_id(value))
    }
    reference_dois = {doi for value in DOI_PATTERN.findall(reference_text) if (doi := _normalize_doi(value))}
    if _candidate_arxiv_ids(candidate) & reference_arxiv_ids:
        return 1.0
    if _candidate_dois(candidate) & reference_dois:
        return 1.0
    return 0.0


def _score_to_level(score: float, relation_type: CitationRelationType) -> EvidenceLevel:
    if relation_type == "explicit_reference" and score >= 0.55:
        return "strong"
    if score >= 0.7:
        return "strong"
    if score >= 0.4:
        return "medium"
    return "weak"


def score_candidate_relationship(
    seed: CitationTracePaperNode,
    candidate: CitationTracePaperNode,
    *,
    round_number: int,
    relation_type: CitationRelationType,
    reference_text: str | None = None,
) -> CitationTraceLedgerEntry:
    title_overlap = _jaccard(_token_set(seed.title), _token_set(candidate.title))
    abstract_similarity = _jaccard(_token_set(seed.abstract), _token_set(candidate.abstract))
    keyword_overlap = _jaccard(
        {item.casefold() for item in seed.keywords},
        {item.casefold() for item in candidate.keywords},
    )
    author_overlap = _jaccard(
        {item.casefold() for item in seed.authors},
        {item.casefold() for item in candidate.authors},
    )
    date_score = _date_plausibility(seed.published_date, candidate.published_date)
    reference_match = (
        _reference_metadata_match(candidate, reference_text)
        if relation_type == "explicit_reference"
        else 0.0
    )
    total = (
        abstract_similarity * 0.1
        + title_overlap * 0.07
        + keyword_overlap * 0.05
        + author_overlap * 0.01
        + date_score * 0.03
        + reference_match * 0.7
    )
    breakdown = CitationTraceScoreBreakdown(
        abstract_similarity=round(abstract_similarity, 4),
        title_overlap=round(title_overlap, 4),
        keyword_overlap=round(keyword_overlap, 4),
        author_overlap=round(author_overlap, 4),
        date_plausibility=round(date_score, 4),
        reference_match=round(reference_match, 4),
    )
    metadata_evidence = []
    if candidate.arxiv_id:
        metadata_evidence.append(f"arXiv:{candidate.arxiv_id}")
    if candidate.doi:
        metadata_evidence.append(f"DOI:{candidate.doi}")
    if candidate.published_date:
        metadata_evidence.append(f"published:{candidate.published_date}")
    score_total = round(total, 4)
    return CitationTraceLedgerEntry(
        entry_id=_new_id("ledger"),
        candidate_paper=candidate,
        seed_paper=seed,
        round=round_number,
        relation_type=relation_type,
        evidence_level=_score_to_level(score_total, relation_type),
        score_total=score_total,
        score_breakdown=breakdown,
        reference_text=reference_text,
        metadata_evidence=metadata_evidence,
    )


def select_round_candidates(
    seed: CitationTracePaperNode,
    candidates: list[CitationTracePaperNode],
    *,
    round_number: int,
    limit: int,
) -> list[CitationTraceLedgerEntry]:
    entries = [
        score_candidate_relationship(
            seed,
            candidate,
            round_number=round_number,
            relation_type="retrieved_similar",
        )
        for candidate in candidates
    ]
    entries.sort(
        key=lambda item: (
            -item.score_total,
            item.candidate_paper.canonical_id.casefold(),
            item.candidate_paper.source.casefold(),
            item.candidate_paper.source_id.casefold(),
            item.candidate_paper.paper_id.casefold(),
            item.candidate_paper.title.casefold(),
        )
    )
    return entries[:limit]


def resolve_reference_to_node(reference: ReferenceEntry, settings: Any) -> CitationTracePaperNode | None:
    if not reference.arxiv_id:
        return None
    record = fetch_arxiv_record(reference.arxiv_id)
    if record is None:
        return None
    arxiv_id = (
        _normalize_arxiv_id(getattr(record, "arxiv_id", None))
        or _normalize_arxiv_id(getattr(record, "source_id", None))
        or reference.arxiv_id
    )
    authors = [normalize_whitespace(author) for author in list(getattr(record, "authors", []) or [])]
    title = normalize_whitespace(getattr(record, "title", "") or reference.title_hint or arxiv_id)
    abstract = normalize_whitespace(getattr(record, "summary", "") or "")
    published_date = getattr(record, "published_date", None)
    doi = getattr(record, "doi", None)
    return CitationTracePaperNode(
        paper_id=arxiv_id,
        source="arxiv",
        source_id=getattr(record, "source_id", None) or arxiv_id,
        canonical_id=build_canonical_paper_id(
            title=title,
            authors=authors,
            published_date=published_date,
            arxiv_id=arxiv_id,
            doi=doi,
        ),
        title=title,
        abstract=abstract,
        authors=authors,
        published_date=published_date,
        arxiv_id=arxiv_id,
        doi=doi,
        external_url=getattr(record, "external_url", None),
    )


def _paper_node_from_external_record(record: Any) -> CitationTracePaperNode:
    arxiv_id = (
        _normalize_arxiv_id(getattr(record, "arxiv_id", None))
        or _normalize_arxiv_id(getattr(record, "source_id", None))
    )
    source_id = normalize_whitespace(str(getattr(record, "source_id", "") or arxiv_id or ""))
    title = normalize_whitespace(str(getattr(record, "title", "") or source_id or "Untitled paper"))
    abstract = normalize_whitespace(str(getattr(record, "summary", "") or title))
    authors = [normalize_whitespace(str(author)) for author in list(getattr(record, "authors", []) or [])]
    published_date = getattr(record, "published_date", None)
    doi = getattr(record, "doi", None)
    primary_category = getattr(record, "primary_category", None)
    canonical_id = build_canonical_paper_id(
        title=title,
        authors=authors,
        published_date=published_date,
        arxiv_id=arxiv_id,
        doi=doi,
    )
    return CitationTracePaperNode(
        paper_id=arxiv_id or source_id or canonical_id,
        source="arxiv",
        source_id=source_id or arxiv_id or canonical_id,
        canonical_id=canonical_id,
        title=title,
        abstract=abstract,
        authors=authors,
        published_date=published_date,
        keywords=[primary_category] if primary_category else [],
        arxiv_id=arxiv_id,
        doi=doi,
        external_url=getattr(record, "external_url", None),
    )


def _reference_query(reference: ReferenceEntry) -> str:
    if reference.title_hint:
        return normalize_whitespace(reference.title_hint)
    text = DOI_PATTERN.sub("", ARXIV_ID_PATTERN.sub("", reference.raw_text or ""))
    text = YEAR_PATTERN.sub("", text)
    return normalize_whitespace(text)[:240]


def _year_from_date(value: str | None) -> int | None:
    if not value:
        return None
    match = YEAR_PATTERN.search(str(value))
    return int(match.group(1)) if match else None


def _reference_author_overlap(reference: ReferenceEntry, candidate: CitationTracePaperNode) -> float:
    reference_tokens = _token_set(reference.raw_text)
    if not reference_tokens or not candidate.authors:
        return 0.0
    author_tokens: set[str] = set()
    for author in candidate.authors:
        parts = _token_set(author)
        if parts:
            author_tokens.add(sorted(parts, key=len)[-1])
    return 1.0 if reference_tokens & author_tokens else 0.0


def _reference_date_score(reference: ReferenceEntry, target: CitationTracePaperNode, candidate: CitationTracePaperNode) -> float:
    candidate_year = _year_from_date(candidate.published_date)
    target_year = _year_from_date(target.published_date)
    reference_year = int(reference.year) if reference.year and reference.year.isdigit() else None
    if candidate_year is None:
        return 0.25
    if target_year is not None and candidate_year > target_year:
        return 0.0
    if reference_year is not None:
        delta = abs(candidate_year - reference_year)
        if delta == 0:
            return 1.0
        if delta <= 1:
            return 0.8
        if delta <= 3:
            return 0.5
        return 0.2
    return 0.75


def _score_recalled_candidate(
    session: CitationTraceSession,
    reference: ReferenceEntry,
    candidate: CitationTracePaperNode,
    *,
    source_label: str,
) -> CitationTraceLedgerEntry:
    query = _reference_query(reference)
    reference_title_score = _reference_title_similarity(query, candidate)
    target_relevance = _target_relevance_score(session.target_paper, candidate)
    reference_match = _reference_metadata_match(candidate, reference.raw_text)
    author_overlap = _reference_author_overlap(reference, candidate)
    author_bonus = author_overlap * 0.01
    date_score = _reference_date_score(reference, session.target_paper, candidate)
    source_confidence = 1.0 if source_label == "arxiv_id" else 0.7
    substantive_signal = max(target_relevance, reference_title_score, reference_match)
    total = (
        target_relevance * 0.46
        + reference_title_score * 0.32
        + reference_match * 0.13
        + date_score * 0.04
        + source_confidence * 0.03
        + author_bonus
    )
    exact_arxiv_match = (
        candidate.arxiv_id
        and reference.arxiv_id
        and _normalize_arxiv_id(candidate.arxiv_id) == _normalize_arxiv_id(reference.arxiv_id)
    )
    if exact_arxiv_match and reference_title_score >= 0.35 and target_relevance >= 0.1:
        total += 0.1
    warnings: list[str] = []
    if target_relevance < 0.08:
        cap = 0.45 if reference_title_score >= 0.65 else 0.35
        if total > cap:
            total = cap
        if reference_match >= 1.0:
            warnings.append("Exact identifier match but low target-topic alignment; demoted.")
    if substantive_signal < 0.25:
        if author_overlap > 0:
            total = min(total, 0.08)
            warnings.append("Author overlap is only a small bonus; no title, topic, or identifier evidence matched.")
        else:
            total = min(total, 0.12)
    if reference_title_score < 0.12 and reference_match >= 1.0:
        total = min(total, 0.42)
        warnings.append("Exact identifier match but weak title agreement with the parsed reference text.")
    score_total = round(min(total, 1.0), 4)
    metadata = [f"reference:{reference.reference_id}", f"recall:{source_label}"]
    if candidate.arxiv_id:
        metadata.append(f"arXiv:{candidate.arxiv_id}")
    if candidate.doi:
        metadata.append(f"DOI:{candidate.doi}")
    if candidate.published_date:
        metadata.append(f"published:{candidate.published_date}")
    return CitationTraceLedgerEntry(
        entry_id=_new_id("ledger"),
        candidate_paper=candidate,
        seed_paper=session.target_paper,
        round=1,
        relation_type="explicit_reference",
        evidence_level=_score_to_level(score_total, "explicit_reference"),
        score_total=score_total,
        score_breakdown=CitationTraceScoreBreakdown(
            abstract_similarity=round(target_relevance, 4),
            title_overlap=round(reference_title_score, 4),
            author_overlap=round(author_bonus, 4),
            date_plausibility=round(date_score, 4),
            reference_match=round(reference_match, 4),
        ),
        reference_text=reference.raw_text,
        metadata_evidence=metadata,
        warnings=warnings,
    )


def recall_reference_candidates(
    session: CitationTraceSession,
    settings: Any,
    *,
    limit: int = 15,
) -> list[CitationTraceLedgerEntry]:
    indexed_entries: list[tuple[int, int, CitationTraceLedgerEntry]] = []
    unresolved_entries: list[tuple[int, int, CitationTraceLedgerEntry]] = []
    for reference_index, reference in enumerate(session.reference_entries):
        entries_for_reference: list[CitationTraceLedgerEntry] = []
        if _is_non_reference_fragment(reference):
            label = reference.title_hint or reference.raw_text[:80] or reference.reference_id
            session.warnings.append(f"Skipped unresolved reference fragment: {normalize_whitespace(label)}")
            continue
        if reference.arxiv_id:
            try:
                node = resolve_reference_to_node(reference, settings)
            except Exception as exc:
                node = None
                session.warnings.append(f"{reference.title_hint or reference.reference_id}: {exc}")
            if node is not None:
                entries_for_reference.append(
                    _score_recalled_candidate(session, reference, node, source_label="arxiv_id")
                )
        else:
            query = _reference_query(reference)
            if query:
                try:
                    records = resolve_arxiv_candidates(query, limit=limit)
                except Exception as exc:
                    records = []
                    session.warnings.append(f"{reference.title_hint or reference.reference_id}: {exc}")
                for record in records[:limit]:
                    entries_for_reference.append(
                        _score_recalled_candidate(
                            session,
                            reference,
                            _paper_node_from_external_record(record),
                            source_label="title",
                        )
                    )
        if not entries_for_reference:
            _node, entry = build_unresolved_reference_record(
                reference,
                seed_paper_id=session.target_paper.paper_id,
            )
            unresolved_entries.append((reference_index, 0, entry))
            continue
        for candidate_index, entry in enumerate(entries_for_reference):
            indexed_entries.append((reference_index, candidate_index, entry))

    source_entries = indexed_entries if indexed_entries else unresolved_entries
    best_by_key: dict[str, tuple[int, int, CitationTraceLedgerEntry]] = {}
    for reference_index, candidate_index, entry in source_entries:
        key = (
            entry.candidate_paper.canonical_id
            or entry.candidate_paper.arxiv_id
            or entry.candidate_paper.source_id
            or entry.candidate_paper.paper_id
        ).casefold()
        existing = best_by_key.get(key)
        if existing is None or (
            -entry.score_total,
            reference_index,
            candidate_index,
        ) < (
            -existing[2].score_total,
            existing[0],
            existing[1],
        ):
            best_by_key[key] = (reference_index, candidate_index, entry)
    sorted_entries = sorted(
        best_by_key.values(),
        key=lambda item: (
            -item[2].score_total,
            item[0],
            item[1],
            item[2].candidate_paper.title.casefold(),
        ),
    )
    return [entry for _reference_index, _candidate_index, entry in sorted_entries[:limit]]


def _search_source_for_node(node: CitationTracePaperNode) -> str:
    return node.source if node.source in {"arxiv", "local", "wos"} else "arxiv"


def _target_paper_from_node(node: CitationTracePaperNode) -> TargetPaper:
    source = _search_source_for_node(node)
    source_id = normalize_whitespace(node.source_id or node.arxiv_id or node.paper_id)
    primary_category = node.keywords[0] if node.keywords else None
    return TargetPaper(
        id=f"{source}:{source_id}",
        source=source,
        source_id=source_id,
        canonical_id=node.canonical_id,
        title=node.title,
        summary=node.abstract or node.title,
        authors=list(node.authors),
        published_date=node.published_date,
        primary_category=primary_category,
        arxiv_id=node.arxiv_id,
        external_url=node.external_url,
        matched_sources=[source],
    )


def _candidate_node_from_retrieved_paper(paper: Any) -> CitationTracePaperNode:
    source = str(getattr(paper, "source", "local") or "local")
    if source not in {"arxiv", "local", "wos"}:
        source = "local"
    source_id = normalize_whitespace(str(getattr(paper, "source_id", "") or getattr(paper, "id", "")))
    title = normalize_whitespace(str(getattr(paper, "title", "") or source_id or "Untitled paper"))
    authors = [normalize_whitespace(str(author)) for author in list(getattr(paper, "authors", []) or [])]
    published_date = getattr(paper, "published_date", None)
    arxiv_id = getattr(paper, "arxiv_id", None)
    primary_category = getattr(paper, "primary_category", None)
    canonical_id = getattr(paper, "canonical_id", None) or build_canonical_paper_id(
        title=title,
        authors=authors,
        published_date=published_date,
        arxiv_id=arxiv_id,
    )
    return CitationTracePaperNode(
        paper_id=normalize_whitespace(str(getattr(paper, "id", "") or f"{source}:{source_id}")),
        source=source,
        source_id=source_id,
        canonical_id=canonical_id,
        title=title,
        abstract=normalize_whitespace(str(getattr(paper, "text", "") or "")),
        authors=authors,
        published_date=published_date,
        keywords=[primary_category] if primary_category else [],
        arxiv_id=arxiv_id,
        external_url=getattr(paper, "external_url", None),
    )


def expand_seed_candidates(seed: CitationTracePaperNode, settings: Any) -> list[CitationTracePaperNode]:
    target_paper = _target_paper_from_node(seed)
    retrieval_text = build_target_paper_retrieval_text(target_paper)
    query_vec = get_embedding(retrieval_text, settings)
    batch = collect_prior_work_candidates(query_vec, target_paper, settings)
    candidates: list[CitationTracePaperNode] = []
    seen: set[str] = {seed.canonical_id.casefold()}
    for paper in batch.papers:
        node = _candidate_node_from_retrieved_paper(paper)
        dedupe_key = node.canonical_id.casefold()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        candidates.append(node)
    return candidates


def _round_summary_payload(summary: CitationTraceRoundSummary) -> dict[str, Any]:
    return {
        "round": summary.round,
        "status": summary.status,
        "seed_count": summary.seed_count,
        "candidate_count": summary.candidate_count,
        "selected_count": summary.selected_count,
        "summary_text": summary.summary_text,
        "seed_paper_ids": list(summary.seed_paper_ids),
        "warnings": list(summary.warnings),
    }


def run_round_one(session: CitationTraceSession, settings: Any) -> CitationTraceRoundSummary:
    warning_count_before = len(session.warnings)
    selected = recall_reference_candidates(session, settings, limit=15)
    warnings = session.warnings[warning_count_before:]
    return CitationTraceRoundSummary(
        round=1,
        status="completed" if selected else "partial",
        seed_count=1,
        candidate_count=len(selected),
        selected_count=len(selected),
        summary_text="Round 1 recalled the top 15 reference-grounded candidates.",
        seed_paper_ids=[session.target_paper.paper_id],
        ledger_entries=selected,
        warnings=warnings,
    )


def run_round_two(
    session: CitationTraceSession,
    settings: Any,
    round_one: CitationTraceRoundSummary,
) -> CitationTraceRoundSummary:
    entries: list[CitationTraceLedgerEntry] = []
    warnings: list[str] = []
    candidate_count = 0
    seeds = [
        entry.candidate_paper
        for entry in round_one.ledger_entries[:10]
        if entry.candidate_paper.source != "unresolved"
    ]
    for seed in seeds:
        try:
            candidates = expand_seed_candidates(seed, settings)
            candidate_count += len(candidates)
            entries.extend(select_round_candidates(seed, candidates, round_number=2, limit=3))
        except Exception as exc:
            warnings.append(f"{seed.title}: {exc}")
    status: RoundStatus = "completed"
    if warnings and entries:
        status = "partial"
    elif warnings and not entries:
        status = "failed"
    return CitationTraceRoundSummary(
        round=2,
        status=status,
        seed_count=len(seeds),
        candidate_count=candidate_count,
        selected_count=len(entries),
        summary_text="Round 2 expanded each resolved round 1 seed independently.",
        seed_paper_ids=[seed.paper_id for seed in seeds],
        ledger_entries=entries,
        warnings=warnings,
    )


def _fallback_final_top5(session: CitationTraceSession) -> list[CitationTraceTopPaper]:
    items: list[CitationTraceTopPaper] = []
    candidate_entries = [
        entry for entry in session.ledger_entries if entry.candidate_paper.source != "unresolved"
    ] or list(session.ledger_entries)
    ranked_entries = sorted(
        candidate_entries,
        key=lambda entry: (
            -entry.score_total,
            entry.candidate_paper.title.casefold(),
            entry.entry_id,
        ),
    )
    for index, entry in enumerate(ranked_entries[:5], start=1):
        relation_is_explicit = entry.relation_type == "explicit_reference"
        items.append(
            CitationTraceTopPaper(
                rank=index,
                paper_id=entry.candidate_paper.paper_id,
                title=entry.candidate_paper.title,
                influence_area="unknown",
                reason=entry.llm_assessment or "Selected from the current evidence ledger.",
                evidence_level=entry.evidence_level,
                is_explicitly_cited=relation_is_explicit,
                is_exploratory=not relation_is_explicit,
                why_worth_reading="It is one of the strongest currently available provenance candidates.",
                uncertainty="LLM ranking fallback used; ordered by the reference recall score.",
                supporting_edge_ids=[entry.entry_id],
            )
        )
    return enforce_final_top5_policy(items)


def _request_timeout_from_settings(settings: Any) -> int:
    return _request_timeout(settings)


def _candidate_assessment_messages(
    session: CitationTraceSession,
    entry: CitationTraceLedgerEntry,
) -> list[dict[str, str]]:
    target = session.target_paper
    candidate = entry.candidate_paper
    return [
        {
            "role": "system",
            "content": (
                "You assess whether a referenced candidate paper is useful for citation provenance. "
                "Return one JSON object with keys: paper_summary, comparison_points, supporting_evidence, "
                "negative_evidence, confidence, suggested_score. Do not invent evidence."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Target paper:\nTitle: {target.title}\nAbstract: {target.abstract}\n\n"
                f"Reference text:\n{entry.reference_text or ''}\n\n"
                f"Candidate paper:\nTitle: {candidate.title}\nAbstract: {candidate.abstract}\n"
                f"Authors: {', '.join(candidate.authors)}\nPublished: {candidate.published_date or 'unknown'}"
            ),
        },
    ]


def _format_llm_field(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(_format_llm_field(item) for item in value)
    if isinstance(value, dict):
        return ", ".join(
            f"{normalize_whitespace(str(key))}: {_format_llm_field(item)}"
            for key, item in value.items()
        )
    return normalize_whitespace(str(value))


def assess_recalled_candidates(session: CitationTraceSession, settings: Any) -> None:
    config = getattr(settings, "citation_trace_worker_chat", None)
    if config is None:
        return
    for entry in session.ledger_entries[:15]:
        try:
            raw = chat_completion(
                _candidate_assessment_messages(session, entry),
                config,
                _request_timeout_from_settings(settings),
            )
            parsed = extract_first_json_object(raw)
            entry.llm_assessment = (
                f"summary: {_format_llm_field(parsed.get('paper_summary'))}\n"
                f"comparison_points: {_format_llm_field(parsed.get('comparison_points'))}\n"
                f"supporting_evidence: {_format_llm_field(parsed.get('supporting_evidence'))}\n"
                f"negative_evidence: {_format_llm_field(parsed.get('negative_evidence'))}\n"
                f"confidence: {_format_llm_field(parsed.get('confidence'))}\n"
                f"suggested_score: {_format_llm_field(parsed.get('suggested_score'))}"
            )
        except Exception as exc:
            entry.warnings.append(f"Worker assessment failed: {exc}")


def _main_ranking_messages(session: CitationTraceSession) -> list[dict[str, str]]:
    candidate_lines = []
    for entry in session.ledger_entries[:15]:
        candidate_lines.append(
            {
                "entry_id": entry.entry_id,
                "paper_id": entry.candidate_paper.paper_id,
                "source": entry.candidate_paper.source,
                "arxiv_id": entry.candidate_paper.arxiv_id,
                "title": entry.candidate_paper.title,
                "score_total": entry.score_total,
                "score_breakdown": {
                    "target_topic_alignment": entry.score_breakdown.abstract_similarity,
                    "reference_title_alignment": entry.score_breakdown.title_overlap,
                    "author_bonus": entry.score_breakdown.author_overlap,
                    "date_plausibility": entry.score_breakdown.date_plausibility,
                    "identifier_match": entry.score_breakdown.reference_match,
                },
                "reference_text": entry.reference_text,
                "llm_assessment": entry.llm_assessment,
                "warnings": list(entry.warnings),
            }
        )
    return [
        {
            "role": "system",
            "content": (
                "Rank citation provenance candidates. Return one JSON object with key top5. "
                "top5 must be a list of objects with paper_id, influence_area, reason, "
                "why_worth_reading, uncertainty. Prefer candidates with strong target-topic "
                "alignment and reference-title alignment. Do not rank unresolved snippets, "
                "appendix/algorithm fragments, or papers that only share an identifier with a "
                "polluted reference but are unrelated to the target topic. Treat author_bonus as "
                "a small tie-breaker only, never as primary evidence. Use only supplied evidence."
            ),
        },
        {
            "role": "user",
            "content": f"Target paper: {session.target_paper.title}\nCandidates:\n{candidate_lines}",
        },
    ]


def synthesize_final_top5(session: CitationTraceSession, settings: Any) -> list[CitationTraceTopPaper]:
    config = getattr(settings, "citation_trace_main_chat", None)
    if config is None:
        return _fallback_final_top5(session)
    try:
        raw = chat_completion(_main_ranking_messages(session), config, _request_timeout_from_settings(settings))
        parsed = extract_first_json_object(raw)
        requested = parsed.get("top5") if isinstance(parsed.get("top5"), list) else []
    except Exception:
        return _fallback_final_top5(session)

    entries_by_paper_id = {entry.candidate_paper.paper_id: entry for entry in session.ledger_entries}
    items: list[CitationTraceTopPaper] = []
    for item in requested:
        if not isinstance(item, dict):
            continue
        paper_id = normalize_whitespace(item.get("paper_id") or "")
        entry = entries_by_paper_id.get(paper_id)
        if entry is None:
            continue
        relation_is_explicit = entry.relation_type == "explicit_reference"
        items.append(
            CitationTraceTopPaper(
                rank=len(items) + 1,
                paper_id=entry.candidate_paper.paper_id,
                title=entry.candidate_paper.title,
                influence_area=normalize_whitespace(item.get("influence_area") or "unknown") or "unknown",
                reason=normalize_whitespace(item.get("reason") or entry.llm_assessment or "Selected by citation trace ranking."),
                evidence_level=entry.evidence_level,
                is_explicitly_cited=relation_is_explicit,
                is_exploratory=not relation_is_explicit,
                why_worth_reading=normalize_whitespace(item.get("why_worth_reading") or "Worth reading as a high-ranked provenance candidate."),
                uncertainty=normalize_whitespace(item.get("uncertainty") or ""),
                supporting_edge_ids=[entry.entry_id],
            )
        )
        if len(items) >= 5:
            break
    return enforce_final_top5_policy(items) if items else _fallback_final_top5(session)


def run_synthesis_stage(session: CitationTraceSession, settings: Any) -> Iterator[tuple[str, dict[str, Any]]]:
    yield "stage_start", {"stage": "main_ranking", "session_id": session.session_id}
    try:
        session.final_top5 = synthesize_final_top5(session, settings)
    except Exception as exc:
        session.final_top5 = []
        message = f"Synthesis failed: {exc}"
        session.warnings.append(message)
        yield "warning", {"message": message}
        return
    yield "synthesis_complete", {"session_id": session.session_id, "final_top5_count": len(session.final_top5)}


def run_citation_trace_events(
    session: CitationTraceSession,
    settings: Any,
) -> Iterator[tuple[str, dict[str, Any]]]:
    session.status = "running"
    session.warnings = []
    session.final_top5 = []
    yield "stage_start", {"session_id": session.session_id, "stage": "reference_resolution"}
    warning_count_before = len(session.warnings)
    resolve_references_with_worker(session, settings)
    for warning in session.warnings[warning_count_before:]:
        yield "warning", {"message": warning}

    yield "stage_start", {"session_id": session.session_id, "stage": "candidate_recall"}
    round_one = run_round_one(session, settings)
    session.rounds = [round_one]
    session.ledger_entries = list(round_one.ledger_entries)
    yield "round_summary", _round_summary_payload(round_one)
    for entry in round_one.ledger_entries:
        yield "ledger_entry", {
            "entry_id": entry.entry_id,
            "round": entry.round,
            "title": entry.candidate_paper.title,
        }
    for warning in round_one.warnings:
        yield "warning", {"message": warning}

    yield "stage_start", {"session_id": session.session_id, "stage": "worker_assessment"}
    assess_recalled_candidates(session, settings)
    yield "worker_assessment_complete", {
        "session_id": session.session_id,
        "candidate_count": len(session.ledger_entries[:15]),
    }

    for event_name, payload in run_synthesis_stage(session, settings):
        yield event_name, payload

    if round_one.status in {"partial", "failed"}:
        session.status = "partial"
    elif round_one.warnings or session.warnings:
        session.status = "partial"
    else:
        session.status = "completed"
    yield "complete", {
        "session_id": session.session_id,
        "status": session.status,
        "final_top5_count": len(session.final_top5),
    }


def enforce_final_top5_policy(items: list[CitationTraceTopPaper]) -> list[CitationTraceTopPaper]:
    selected: list[CitationTraceTopPaper] = []
    weak_exploratory_count = 0
    for item in sorted(items, key=lambda value: value.rank):
        is_weak_exploratory = item.is_exploratory and item.evidence_level == "weak"
        if is_weak_exploratory and weak_exploratory_count >= 2:
            continue
        selected.append(item)
        if is_weak_exploratory:
            weak_exploratory_count += 1
        if len(selected) >= 5:
            break
    return [replace(item, rank=index) for index, item in enumerate(selected, start=1)]
