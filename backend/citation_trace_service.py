from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Iterator, Literal

from local_paper_db.app.search_service import normalize_whitespace


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
    top_papers: list[CitationTraceTopPaper] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


_SESSION_CACHE: dict[str, CitationTraceSession] = {}


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _arxiv_id_from_url(url: str) -> str:
    value = normalize_whitespace(url).rstrip("/")
    suffix = value.rsplit("/", 1)[-1] if value else ""
    arxiv_id = _normalize_arxiv_id(suffix)
    return arxiv_id or suffix or _new_id("arxiv")


def create_session_from_arxiv(
    url: str,
    settings: Any,
    answer_language: str | None = None,
) -> CitationTraceSession:
    source_id = _arxiv_id_from_url(url)
    session_id_suffix = re.sub(r"[^A-Za-z0-9_.-]+", "-", source_id).strip("-") or uuid.uuid4().hex[:12]
    target_paper = CitationTracePaperNode(
        paper_id="target",
        source="target",
        source_id=source_id,
        canonical_id=f"arxiv:{source_id}",
        title=f"arXiv {source_id}",
        arxiv_id=source_id,
        external_url=url,
    )
    session = CitationTraceSession(
        session_id=f"citation-trace-{session_id_suffix}",
        source_type="arxiv",
        source_id=source_id,
        source_url=url,
        target_paper=target_paper,
        answer_language=answer_language or "zh",
    )
    _SESSION_CACHE[session.session_id] = session
    return session


def get_session(session_id: str) -> CitationTraceSession:
    try:
        return _SESSION_CACHE[session_id]
    except KeyError as exc:
        raise KeyError("Citation trace session not found.") from exc


def run_citation_trace_events(
    session: CitationTraceSession,
    settings: Any,
) -> Iterator[tuple[str, dict[str, Any]]]:
    session.status = "running"
    yield "stage_start", {"session_id": session.session_id, "stage": "round_1"}

    if not session.rounds:
        session.rounds.append(
            CitationTraceRoundSummary(
                round=1,
                status="completed",
                seed_paper_ids=[session.target_paper.paper_id],
            )
        )
    round_summary = session.rounds[0]
    session.status = "completed"
    yield "round_summary", asdict(round_summary)
    yield "complete", {"session_id": session.session_id, "status": session.status}


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
