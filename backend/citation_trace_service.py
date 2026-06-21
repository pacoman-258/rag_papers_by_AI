from __future__ import annotations

import re
import tempfile
import uuid
from dataclasses import dataclass, field, replace
from io import BytesIO
from pathlib import Path
from typing import Any, Iterator, Literal

from pypdf import PdfReader

from local_paper_db.app.external_sources import fetch_arxiv_record
from local_paper_db.app.search_service import build_canonical_paper_id, normalize_whitespace


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
ARXIV_URL_PATTERN = re.compile(
    r"^https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/(?P<id>\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?/?(?:[?#].*)?$",
    re.IGNORECASE,
)


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


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


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
    session_id_suffix = re.sub(r"[^A-Za-z0-9_.-]+", "-", source_id).strip("-") or uuid.uuid4().hex[:12]
    target_paper = _paper_node_from_arxiv_record(record, source_id, url)
    session = CitationTraceSession(
        session_id=f"citation-trace-{session_id_suffix}",
        source_type="arxiv",
        source_id=resolved_source_id,
        source_url=url,
        target_paper=target_paper,
        answer_language=answer_language or "zh",
        reference_entries=reference_entries,
        pdf_text=pdf_text,
    )
    _SESSION_CACHE[session.session_id] = session
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


def _iter_reference_chunks(reference_text: str) -> Iterator[tuple[str | None, str]]:
    matches = list(REFERENCE_SPLIT_PATTERN.finditer(reference_text))
    if not matches:
        for paragraph in re.split(r"\n\s*\n", reference_text):
            normalized = normalize_whitespace(paragraph)
            if normalized:
                yield None, normalized
        return
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(reference_text)
        chunk = normalize_whitespace(reference_text[start:end])
        if chunk:
            yield match.group("label"), chunk


def extract_reference_entries(pdf_text: str) -> list[ReferenceEntry]:
    match = REFERENCE_HEADING_PATTERN.search(pdf_text or "")
    if match is None:
        return []
    tail = pdf_text[match.end() :]
    kept_lines: list[str] = []
    for line in tail.splitlines():
        if NEXT_SECTION_PATTERN.match(line):
            break
        kept_lines.append(line)
    reference_text = "\n".join(kept_lines).strip()
    return [_coerce_reference(label, chunk) for label, chunk in _iter_reference_chunks(reference_text)]


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


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


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
        + author_overlap * 0.05
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


def expand_seed_candidates(seed: CitationTracePaperNode, settings: Any) -> list[CitationTracePaperNode]:
    return []


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
    entries: list[CitationTraceLedgerEntry] = []
    warnings: list[str] = []
    for reference in session.reference_entries:
        try:
            node = resolve_reference_to_node(reference, settings)
        except Exception as exc:
            node = None
            warnings.append(f"{reference.title_hint or reference.reference_id}: {exc}")
        if node is None:
            _node, entry = build_unresolved_reference_record(
                reference,
                seed_paper_id=session.target_paper.paper_id,
            )
            entries.append(entry)
            continue
        entries.append(
            score_candidate_relationship(
                session.target_paper,
                node,
                round_number=1,
                relation_type="explicit_reference",
                reference_text=reference.raw_text,
            )
        )
    entries.sort(
        key=lambda item: (
            -item.score_total,
            item.candidate_paper.canonical_id.casefold(),
            item.candidate_paper.paper_id.casefold(),
        )
    )
    selected = entries[:10]
    return CitationTraceRoundSummary(
        round=1,
        status="completed" if selected else "partial",
        seed_count=1,
        candidate_count=len(entries),
        selected_count=len(selected),
        summary_text="Round 1 selected explicit references and unresolved reference records.",
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


def synthesize_final_top5(session: CitationTraceSession, settings: Any) -> list[CitationTraceTopPaper]:
    items: list[CitationTraceTopPaper] = []
    for index, entry in enumerate(session.ledger_entries[:5], start=1):
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
                uncertainty="LLM synthesis fallback used until model ranking is configured.",
                supporting_edge_ids=[entry.entry_id],
            )
        )
    return enforce_final_top5_policy(items)


def run_synthesis_stage(session: CitationTraceSession, settings: Any) -> Iterator[tuple[str, dict[str, Any]]]:
    yield "stage_start", {"stage": "synthesis", "session_id": session.session_id}
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
    yield "stage_start", {"session_id": session.session_id, "stage": "reference_resolution"}

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

    yield "stage_start", {"session_id": session.session_id, "stage": "round_two"}
    round_two = run_round_two(session, settings, round_one)
    session.rounds.append(round_two)
    session.ledger_entries.extend(round_two.ledger_entries)
    yield "round_summary", _round_summary_payload(round_two)
    for entry in round_two.ledger_entries:
        yield "ledger_entry", {
            "entry_id": entry.entry_id,
            "round": entry.round,
            "title": entry.candidate_paper.title,
        }
    for warning in round_two.warnings:
        yield "warning", {"message": warning}

    for event_name, payload in run_synthesis_stage(session, settings):
        yield event_name, payload

    if round_one.status == "failed" or round_two.status == "failed":
        session.status = "partial"
    elif round_one.warnings or round_two.warnings or session.warnings:
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
