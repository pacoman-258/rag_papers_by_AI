# Citation Trace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the old PST-lite trace workflow with a standalone `Citation Trace / 论文溯源` workspace backed by a new citation trace service, evidence ledger, two-round expansion, and an evidence-ledger fallback top 5 until model ranking is wired in.

**Architecture:** Add `backend/citation_trace_service.py` as the new orchestration boundary and expose it through `/api/citation-trace/*`. Remove user-visible PST routes, frontend mode, and assistant source naming instead of keeping compatibility. Keep reusable search primitives such as `TargetPaper`, `RetrievedPaper`, external source lookup, embeddings, rerank, and chat model calls.

**Tech Stack:** Python 3.13, FastAPI, Pydantic, unittest, React 18 + Vite, SSE, existing `local_paper_db.app.search_service` and `external_sources` helpers.

---

## Scope And File Map

Create:

- `backend/citation_trace_service.py`: citation trace sessions, reference extraction, candidate scoring, round execution, LLM synthesis prompt, progress event generation.
- `tests/test_citation_trace_service.py`: pure backend service tests with no network.
- `tests/test_citation_trace_api.py`: FastAPI route tests and removal checks for old `/api/trace/*`.
- `frontend/src/CitationTracePage.jsx`: standalone citation trace UI tab.
- `tests/test_citation_trace_frontend.py`: static frontend contract checks.

Modify:

- `backend/schemas.py`: remove `Trace*` schemas; add citation trace request/response models; update `Live2DChatRequest.source`.
- `backend/main.py`: remove old trace sessions/routes/imports; add citation trace routes and SSE stream.
- `backend/live2d_service.py`: replace PST wording with Citation Trace wording and handle `citation_trace_auto`.
- `backend/assistant_memory.py`: replace `pst_auto` memory trigger text with `citation_trace_auto`.
- `local_paper_db/app/search_service.py`: remove `TraceExecution`, `execute_trace`, trace prompt streaming helpers; keep target paper resolution and prior-work retrieval helpers only if citation trace uses them.
- `local_paper_db/app/search.py`: remove `--trace` CLI mode or rename it only if wired to the new citation trace service. The first implementation removes it to avoid a half-compatible CLI.
- `frontend/src/App.jsx`: remove embedded PST workspace state/UI and add `CitationTracePage`.
- `frontend/src/styles.css`: add citation trace layout styles using existing variables and card patterns.
- `README.md` and `README.zh-CN.md`: replace trace/PST docs with Citation Trace docs.
- `PROJECT_LOG.md`: add the implementation log entry at the top.

Current worktree note: there are pre-existing unstaged changes. Stage only files changed by the current task at each commit.

---

### Task 1: Add Citation Trace Service Data Model And Pure Reference Helpers

**Files:**
- Create: `backend/citation_trace_service.py`
- Create: `tests/test_citation_trace_service.py`

- [ ] **Step 1: Write failing tests for references, unresolved entries, and final top5 guard**

Create `tests/test_citation_trace_service.py` with this content:

```python
import unittest

from backend import citation_trace_service as cts


class CitationTraceServiceTest(unittest.TestCase):
    def test_extract_reference_entries_from_references_section(self):
        text = """
        Abstract
        We study useful things.

        References
        [1] Ashish Vaswani, Noam Shazeer. Attention Is All You Need. arXiv:1706.03762, 2017.
        [2] D. Bahdanau, K. Cho, Y. Bengio. Neural Machine Translation by Jointly Learning to Align and Translate. 2015.
        [3] J. Doe. An Unresolved Report. Technical memo.
        Appendix
        Extra material.
        """

        entries = cts.extract_reference_entries(text)

        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0].raw_label, "[1]")
        self.assertIn("Attention Is All You Need", entries[0].raw_text)
        self.assertEqual(entries[0].arxiv_id, "1706.03762")
        self.assertIn("Bahdanau", entries[1].raw_text)
        self.assertIsNone(entries[2].arxiv_id)

    def test_unresolved_reference_stays_visible_as_node_and_ledger_entry(self):
        reference = cts.ReferenceEntry(
            reference_id="ref-1",
            raw_text="J. Doe. An Unresolved Report. Technical memo.",
            raw_label=None,
            arxiv_id=None,
            doi=None,
            year=None,
            title_hint="An Unresolved Report",
        )

        node, entry = cts.build_unresolved_reference_record(reference, seed_paper_id="target")

        self.assertEqual(node.source, "unresolved")
        self.assertEqual(node.title, "An Unresolved Report")
        self.assertEqual(entry.relation_type, "explicit_reference")
        self.assertEqual(entry.evidence_level, "weak")
        self.assertIn("Unresolved reference", entry.warnings)

    def test_final_top5_limits_low_evidence_exploratory_entries_to_two(self):
        items = [
            cts.CitationTraceTopPaper(rank=1, paper_id="p1", title="P1", influence_area="method", reason="strong", evidence_level="strong", is_explicitly_cited=True, is_exploratory=False, why_worth_reading="core", uncertainty="", supporting_edge_ids=[]),
            cts.CitationTraceTopPaper(rank=2, paper_id="p2", title="P2", influence_area="theory", reason="weak one", evidence_level="weak", is_explicitly_cited=False, is_exploratory=True, why_worth_reading="explore", uncertainty="weak evidence", supporting_edge_ids=[]),
            cts.CitationTraceTopPaper(rank=3, paper_id="p3", title="P3", influence_area="problem", reason="weak two", evidence_level="weak", is_explicitly_cited=False, is_exploratory=True, why_worth_reading="explore", uncertainty="weak evidence", supporting_edge_ids=[]),
            cts.CitationTraceTopPaper(rank=4, paper_id="p4", title="P4", influence_area="dataset", reason="weak three", evidence_level="weak", is_explicitly_cited=False, is_exploratory=True, why_worth_reading="explore", uncertainty="weak evidence", supporting_edge_ids=[]),
        ]

        trimmed = cts.enforce_final_top5_policy(items)

        self.assertEqual([item.paper_id for item in trimmed], ["p1", "p2", "p3"])
        self.assertLessEqual(sum(1 for item in trimmed if item.is_exploratory and item.evidence_level == "weak"), 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the new service tests and verify they fail**

Run:

```bash
.venv/bin/python -m unittest tests.test_citation_trace_service
```

Expected: fail with `ImportError` or `AttributeError` because `backend.citation_trace_service` and the referenced types/functions do not exist.

- [ ] **Step 3: Add minimal dataclasses and pure helper implementation**

Create `backend/citation_trace_service.py` with these definitions as the initial content:

```python
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Iterator, Literal

from local_paper_db.app.search_service import normalize_whitespace


PaperNodeSource = Literal["target", "arxiv", "local", "wos", "unresolved"]
CitationRelationType = Literal["explicit_reference", "retrieved_similar", "llm_inferred_influence"]
EvidenceLevel = Literal["strong", "medium", "weak"]
RoundStatus = Literal["pending", "running", "completed", "partial", "failed"]

REFERENCE_HEADING_PATTERN = re.compile(r"^\s*(references|bibliography)\s*$", re.IGNORECASE | re.MULTILINE)
NEXT_SECTION_PATTERN = re.compile(r"^\s*(appendix|supplementary material|acknowledg(?:e)?ments)\b", re.IGNORECASE)
ARXIV_ID_PATTERN = re.compile(r"\barxiv\s*:\s*(\d{4}\.\d{4,5})(?:v\d+)?\b", re.IGNORECASE)
DOI_PATTERN = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.IGNORECASE)
YEAR_PATTERN = re.compile(r"\b(19\d{2}|20\d{2})\b")
REFERENCE_SPLIT_PATTERN = re.compile(r"(?m)^\s*(?P<label>\[\d+\]|\d+\.)\s+")


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


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _title_hint_from_reference(text: str) -> str | None:
    normalized = normalize_whitespace(text)
    if not normalized:
        return None
    without_label = re.sub(r"^(\[\d+\]|\d+\.)\s*", "", normalized).strip()
    pieces = [piece.strip() for piece in re.split(r"\.\s+", without_label) if piece.strip()]
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
```

- [ ] **Step 4: Run service tests and verify they pass**

Run:

```bash
.venv/bin/python -m unittest tests.test_citation_trace_service
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 1**

Run:

```bash
git add backend/citation_trace_service.py tests/test_citation_trace_service.py
git commit -m "Add citation trace service primitives"
```

Expected: commit succeeds with only these two files staged.

---

### Task 2: Add Candidate Scoring, Round Selection, And LLM Synthesis Contracts

**Files:**
- Modify: `backend/citation_trace_service.py`
- Modify: `tests/test_citation_trace_service.py`

- [ ] **Step 1: Add failing tests for scoring and round limits**

Append these tests inside `CitationTraceServiceTest`:

```python
    def test_score_candidate_marks_explicit_reference_as_strong_when_metadata_matches(self):
        seed = cts.CitationTracePaperNode(
            paper_id="target",
            source="target",
            source_id="target",
            canonical_id="target",
            title="Transformer Translation",
            abstract="Attention models improve neural machine translation.",
            authors=["Ashish Vaswani", "Noam Shazeer"],
            published_date="2017-06-01",
            keywords=["attention", "translation"],
        )
        candidate = cts.CitationTracePaperNode(
            paper_id="paper-1",
            source="arxiv",
            source_id="1706.03762",
            canonical_id="arxiv:1706.03762",
            title="Attention Is All You Need",
            abstract="The Transformer relies entirely on attention mechanisms for translation.",
            authors=["Ashish Vaswani", "Noam Shazeer"],
            published_date="2017-05-01",
            keywords=["attention", "translation"],
            arxiv_id="1706.03762",
        )

        entry = cts.score_candidate_relationship(
            seed,
            candidate,
            round_number=1,
            relation_type="explicit_reference",
            reference_text="Attention Is All You Need. arXiv:1706.03762",
        )

        self.assertEqual(entry.evidence_level, "strong")
        self.assertGreater(entry.score_total, 0.7)
        self.assertEqual(entry.score_breakdown.reference_match, 1.0)

    def test_select_round_candidates_uses_all_when_fewer_than_limit(self):
        seed = cts.CitationTracePaperNode("target", "target", "target", "target", "Target")
        candidates = [
            cts.CitationTracePaperNode("p1", "arxiv", "p1", "p1", "First", abstract="alpha"),
            cts.CitationTracePaperNode("p2", "arxiv", "p2", "p2", "Second", abstract="beta"),
        ]

        selected = cts.select_round_candidates(seed, candidates, round_number=1, limit=10)

        self.assertEqual([entry.candidate_paper.paper_id for entry in selected], ["p1", "p2"])

    def test_select_round_candidates_caps_round_two_at_three_per_seed(self):
        seed = cts.CitationTracePaperNode("seed", "arxiv", "seed", "seed", "Seed")
        candidates = [
            cts.CitationTracePaperNode(f"p{index}", "arxiv", f"p{index}", f"p{index}", f"Paper {index}", abstract="shared method")
            for index in range(5)
        ]

        selected = cts.select_round_candidates(seed, candidates, round_number=2, limit=3)

        self.assertEqual(len(selected), 3)
        self.assertTrue(all(entry.round == 2 for entry in selected))
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```bash
.venv/bin/python -m unittest tests.test_citation_trace_service
```

Expected: fail with missing `score_candidate_relationship` and `select_round_candidates`.

- [ ] **Step 3: Implement scoring helpers**

Add these functions to `backend/citation_trace_service.py`:

```python
def _token_set(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", normalize_whitespace(text).casefold()) if len(token) > 2}


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _date_plausibility(seed_date: str | None, candidate_date: str | None) -> float:
    if not seed_date or not candidate_date:
        return 0.25
    return 1.0 if candidate_date <= seed_date else 0.0


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
    keyword_overlap = _jaccard(set(item.casefold() for item in seed.keywords), set(item.casefold() for item in candidate.keywords))
    author_overlap = _jaccard(set(item.casefold() for item in seed.authors), set(item.casefold() for item in candidate.authors))
    date_score = _date_plausibility(seed.published_date, candidate.published_date)
    reference_match = 1.0 if relation_type == "explicit_reference" else 0.0
    total = (
        abstract_similarity * 0.3
        + title_overlap * 0.18
        + keyword_overlap * 0.12
        + author_overlap * 0.1
        + date_score * 0.1
        + reference_match * 0.2
    )
    breakdown = CitationTraceScoreBreakdown(
        abstract_similarity=round(abstract_similarity, 4),
        title_overlap=round(title_overlap, 4),
        keyword_overlap=round(keyword_overlap, 4),
        author_overlap=round(author_overlap, 4),
        date_plausibility=round(date_score, 4),
        reference_match=round(reference_match, 4),
    )
    evidence = _score_to_level(total, relation_type)
    metadata_evidence = []
    if candidate.arxiv_id:
        metadata_evidence.append(f"arXiv:{candidate.arxiv_id}")
    if candidate.doi:
        metadata_evidence.append(f"DOI:{candidate.doi}")
    if candidate.published_date:
        metadata_evidence.append(f"published:{candidate.published_date}")
    return CitationTraceLedgerEntry(
        entry_id=_new_id("ledger"),
        candidate_paper=candidate,
        seed_paper=seed,
        round=round_number,
        relation_type=relation_type,
        evidence_level=evidence,
        score_total=round(total, 4),
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
    entries.sort(key=lambda item: item.score_total, reverse=True)
    return entries[:limit]
```

- [ ] **Step 4: Run citation trace service tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_citation_trace_service
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 2**

Run:

```bash
git add backend/citation_trace_service.py tests/test_citation_trace_service.py
git commit -m "Add citation trace scoring helpers"
```

Expected: commit succeeds with only these files staged.

---

### Task 3: Add Citation Trace Schemas And API Route Skeleton

**Files:**
- Modify: `backend/schemas.py`
- Modify: `backend/main.py`
- Modify: `backend/citation_trace_service.py`
- Create: `tests/test_citation_trace_api.py`

- [ ] **Step 1: Write failing API tests**

Create `tests/test_citation_trace_api.py`:

```python
import unittest
from fastapi.testclient import TestClient

from backend.main import app
from backend import citation_trace_service as cts


class CitationTraceApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_old_trace_routes_are_removed(self):
        response = self.client.post("/api/trace/resolve-target", json={"query": "1706.03762"})
        self.assertEqual(response.status_code, 404)

    def test_create_citation_trace_session_from_arxiv_uses_service(self):
        session = cts.CitationTraceSession(
            session_id="session-1",
            source_type="arxiv",
            source_id="1706.03762",
            source_url="https://arxiv.org/abs/1706.03762",
            target_paper=cts.CitationTracePaperNode(
                paper_id="target",
                source="target",
                source_id="1706.03762",
                canonical_id="arxiv:1706.03762",
                title="Attention Is All You Need",
                arxiv_id="1706.03762",
            ),
            answer_language="zh",
        )
        original = cts.create_session_from_arxiv
        try:
            cts.create_session_from_arxiv = lambda url, settings, answer_language: session
            response = self.client.post(
                "/api/citation-trace/session/from-arxiv",
                json={"url": "https://arxiv.org/abs/1706.03762", "answer_language": "zh"},
            )
        finally:
            cts.create_session_from_arxiv = original

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["session_id"], "session-1")
        self.assertEqual(payload["target_paper"]["title"], "Attention Is All You Need")

    def test_execute_stream_emits_progress_events(self):
        session = cts.CitationTraceSession(
            session_id="session-stream",
            source_type="arxiv",
            source_id="1706.03762",
            source_url="https://arxiv.org/abs/1706.03762",
            target_paper=cts.CitationTracePaperNode("target", "target", "1706.03762", "arxiv:1706.03762", "Attention"),
            answer_language="zh",
        )
        cts._SESSION_CACHE[session.session_id] = session

        response = self.client.get("/api/citation-trace/session/session-stream/stream")

        self.assertEqual(response.status_code, 200)
        body = response.text
        self.assertIn("event: stage_start", body)
        self.assertIn("event: complete", body)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run API tests and verify they fail**

Run:

```bash
.venv/bin/python -m unittest tests.test_citation_trace_api
```

Expected: fail because citation trace schemas, routes, and session dataclass are missing.

- [ ] **Step 3: Add schema models**

In `backend/schemas.py`, remove `TraceResolveRequest`, `TraceResolveResponse`, `TraceExecuteRequest`, and `TraceExecuteResponse`. Add these models near the search response models:

```python
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
    seed_paper: CitationTracePaperNodeModel | None = None
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
    ledger_entries: list[CitationTraceLedgerEntryModel] = Field(default_factory=list)
    summary_text: str | None = None
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
    source_id: str
    source_url: str | None = None
    answer_language: AnswerLanguage
    target_paper: CitationTracePaperNodeModel
    rounds: list[CitationTraceRoundSummaryModel] = Field(default_factory=list)
    ledger_entries: list[CitationTraceLedgerEntryModel] = Field(default_factory=list)
    final_top5: list[CitationTraceTopPaperModel] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CitationTraceExecuteRequest(BaseModel):
    settings: RuntimeSettingsRequest | None = None
```

Update `Live2DChatRequest.source`:

```python
source: Literal["user", "qa_auto", "citation_trace_auto"]
```

- [ ] **Step 4: Add session dataclass and serializer helpers**

In `backend/citation_trace_service.py`, add:

```python
@dataclass(slots=True)
class CitationTraceRoundSummary:
    round: int
    status: RoundStatus
    seed_count: int = 0
    candidate_count: int = 0
    selected_count: int = 0
    ledger_entries: list[CitationTraceLedgerEntry] = field(default_factory=list)
    summary_text: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CitationTraceSession:
    session_id: str
    source_type: Literal["arxiv", "file"]
    source_id: str
    source_url: str | None
    target_paper: CitationTracePaperNode
    answer_language: str
    rounds: list[CitationTraceRoundSummary] = field(default_factory=list)
    ledger_entries: list[CitationTraceLedgerEntry] = field(default_factory=list)
    final_top5: list[CitationTraceTopPaper] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


_SESSION_CACHE: dict[str, CitationTraceSession] = {}


def create_session_from_arxiv(url: str, settings: Any, answer_language: str | None = None) -> CitationTraceSession:
    language = answer_language or "zh"
    session = CitationTraceSession(
        session_id=uuid.uuid4().hex,
        source_type="arxiv",
        source_id=url.rstrip("/").split("/")[-1],
        source_url=url,
        target_paper=CitationTracePaperNode(
            paper_id="target",
            source="target",
            source_id=url.rstrip("/").split("/")[-1],
            canonical_id=f"arxiv:{url.rstrip('/').split('/')[-1]}",
            title=url.rstrip("/").split("/")[-1],
            arxiv_id=url.rstrip("/").split("/")[-1],
        ),
        answer_language=language,
    )
    _SESSION_CACHE[session.session_id] = session
    return session


def get_session(session_id: str) -> CitationTraceSession:
    session = _SESSION_CACHE.get(session_id)
    if session is None:
        raise KeyError("Citation trace session not found.")
    return session


def run_citation_trace_events(session: CitationTraceSession, settings: Any) -> Iterator[tuple[str, dict[str, Any]]]:
    yield "stage_start", {"stage": "load_paper", "session_id": session.session_id}
    if not session.rounds:
        session.rounds.append(CitationTraceRoundSummary(round=1, status="completed"))
    yield "round_summary", {"round": 1, "status": "completed"}
    yield "complete", {"session_id": session.session_id}
```

- [ ] **Step 5: Add routes in `backend/main.py` and remove old trace routes**

Update imports from `backend.schemas` to include the new citation models and remove the old trace models. Import the service:

```python
from backend import citation_trace_service
```

Remove `trace_sessions`, `api_trace_resolve_target`, `api_trace_execute`, and `api_trace_stream_answer`.

Add serializer and routes:

```python
def citation_trace_session_to_model(session: citation_trace_service.CitationTraceSession) -> CitationTraceSessionModel:
    return CitationTraceSessionModel.model_validate(asdict(session))


@app.post("/api/citation-trace/session/from-arxiv", response_model=CitationTraceSessionModel)
def api_citation_trace_session_from_arxiv(payload: CitationTraceSessionFromArxivRequest) -> CitationTraceSessionModel:
    try:
        with retrieval_runtime_scope(payload.settings) as (settings, _sources):
            session = citation_trace_service.create_session_from_arxiv(
                payload.url,
                settings,
                payload.answer_language,
            )
        return citation_trace_session_to_model(session)
    except Exception as exc:
        raise to_http_detail(exc) from exc


@app.get("/api/citation-trace/session/{session_id}", response_model=CitationTraceSessionModel)
def api_citation_trace_session(session_id: str) -> CitationTraceSessionModel:
    try:
        return citation_trace_session_to_model(citation_trace_service.get_session(session_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/citation-trace/session/{session_id}/execute", response_model=CitationTraceSessionModel)
def api_citation_trace_execute(session_id: str, payload: CitationTraceExecuteRequest) -> CitationTraceSessionModel:
    try:
        with retrieval_runtime_scope(payload.settings) as (settings, _sources):
            session = citation_trace_service.get_session(session_id)
            for _event_name, _payload in citation_trace_service.run_citation_trace_events(session, settings):
                pass
        return citation_trace_session_to_model(session)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise to_http_detail(exc) from exc


@app.get("/api/citation-trace/session/{session_id}/stream")
def api_citation_trace_stream(session_id: str) -> StreamingResponse:
    try:
        session = citation_trace_service.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    def event_generator():
        try:
            settings = settings_from_optional_payload(None)
            for event_name, payload in citation_trace_service.run_citation_trace_events(session, settings):
                yield sse_event(event_name, payload)
        except Exception as exc:
            yield sse_event("error", {"message": str(exc)})

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

- [ ] **Step 6: Run API tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_citation_trace_api
```

Expected: all tests pass.

- [ ] **Step 7: Run service tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_citation_trace_service
```

Expected: all tests pass.

- [ ] **Step 8: Commit Task 3**

Run:

```bash
git add backend/schemas.py backend/main.py backend/citation_trace_service.py tests/test_citation_trace_api.py
git commit -m "Add citation trace API skeleton"
```

Expected: commit succeeds with only these files staged.

---

### Task 4: Implement Real arXiv Intake, PDF Upload Route, And Reference Resolution

**Files:**
- Modify: `backend/citation_trace_service.py`
- Modify: `backend/main.py`
- Modify: `backend/schemas.py`
- Modify: `tests/test_citation_trace_service.py`
- Modify: `tests/test_citation_trace_api.py`

- [ ] **Step 1: Add failing tests for arXiv metadata and PDF upload**

Add to `tests/test_citation_trace_service.py`:

```python
    def test_create_session_from_arxiv_uses_resolved_metadata(self):
        class Record:
            arxiv_id = "1706.03762"
            source = "arxiv"
            source_id = "1706.03762"
            title = "Attention Is All You Need"
            summary = "Transformer architecture."
            authors = ["Ashish Vaswani"]
            published_date = "2017-06-12"
            primary_category = "cs.CL"
            external_url = "https://arxiv.org/abs/1706.03762"
            doi = None

        original_fetch = cts.fetch_arxiv_record
        original_download = cts.download_arxiv_pdf_text
        try:
            cts.fetch_arxiv_record = lambda arxiv_id: Record()
            cts.download_arxiv_pdf_text = lambda arxiv_id, settings: "References\n[1] Prior Work. arXiv:1601.00001"
            session = cts.create_session_from_arxiv("https://arxiv.org/abs/1706.03762", settings=None, answer_language="en")
        finally:
            cts.fetch_arxiv_record = original_fetch
            cts.download_arxiv_pdf_text = original_download

        self.assertEqual(session.target_paper.title, "Attention Is All You Need")
        self.assertEqual(session.target_paper.abstract, "Transformer architecture.")
        self.assertEqual(len(session.reference_entries), 1)
```

Add to `tests/test_citation_trace_api.py`:

```python
    def test_create_citation_trace_session_from_file_accepts_pdf_upload(self):
        session = cts.CitationTraceSession(
            session_id="file-session",
            source_type="file",
            source_id="paper.pdf",
            source_url=None,
            target_paper=cts.CitationTracePaperNode("target", "target", "paper.pdf", "file:paper.pdf", "paper.pdf"),
            answer_language="en",
        )
        original = cts.create_session_from_pdf_bytes
        try:
            cts.create_session_from_pdf_bytes = lambda filename, content, settings, answer_language: session
            response = self.client.post(
                "/api/citation-trace/session/from-file",
                data={"answer_language": "en"},
                files={"file": ("paper.pdf", b"%PDF fake", "application/pdf")},
            )
        finally:
            cts.create_session_from_pdf_bytes = original

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["session_id"], "file-session")
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
.venv/bin/python -m unittest tests.test_citation_trace_service tests.test_citation_trace_api
```

Expected: fail because real intake helpers and file route are missing.

- [ ] **Step 3: Extend service session and arXiv intake**

In `backend/citation_trace_service.py`, import:

```python
import tempfile
from pathlib import Path
from pypdf import PdfReader

from local_paper_db.app.external_sources import fetch_arxiv_record
from local_paper_db.app.search_service import build_canonical_paper_id
```

Extend `CitationTraceSession`:

```python
reference_entries: list[ReferenceEntry] = field(default_factory=list)
pdf_text: str = ""
```

Add helpers:

```python
ARXIV_URL_PATTERN = re.compile(
    r"^https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/(?P<id>\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?/?$",
    re.IGNORECASE,
)


def parse_arxiv_url(url: str) -> str:
    match = ARXIV_URL_PATTERN.match(normalize_whitespace(url))
    if match is None:
        raise ValueError("Only arxiv.org abs or pdf URLs are supported.")
    return match.group("id")


def pdf_bytes_to_text(content: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
        handle.write(content)
        handle.flush()
        reader = PdfReader(handle.name)
        pages = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
    return "\n".join(pages)


def download_arxiv_pdf_text(arxiv_id: str, settings: Any) -> str:
    from backend.paper_reader_service import _download_arxiv_pdf

    session_dir = Path(tempfile.mkdtemp(prefix="citation-trace-"))
    timeout = getattr(getattr(settings, "retrieval", None), "request_timeout", 30)
    pdf_path = _download_arxiv_pdf(arxiv_id, session_dir, timeout)
    return pdf_bytes_to_text(pdf_path.read_bytes())
```

Replace `create_session_from_arxiv` with:

```python
def create_session_from_arxiv(url: str, settings: Any, answer_language: str | None = None) -> CitationTraceSession:
    arxiv_id = parse_arxiv_url(url)
    record = fetch_arxiv_record(arxiv_id)
    if record is None:
        raise ValueError("arXiv paper was not found.")
    pdf_text = download_arxiv_pdf_text(record.arxiv_id or arxiv_id, settings)
    target = CitationTracePaperNode(
        paper_id="target",
        source="target",
        source_id=record.arxiv_id or arxiv_id,
        canonical_id=build_canonical_paper_id(
            title=record.title,
            authors=record.authors,
            published_date=record.published_date,
            arxiv_id=record.arxiv_id,
            doi=record.doi,
        ),
        title=record.title,
        abstract=record.summary,
        authors=list(record.authors),
        published_date=record.published_date,
        arxiv_id=record.arxiv_id,
        doi=record.doi,
        external_url=record.external_url,
    )
    session = CitationTraceSession(
        session_id=uuid.uuid4().hex,
        source_type="arxiv",
        source_id=record.arxiv_id or arxiv_id,
        source_url=url,
        target_paper=target,
        answer_language=answer_language or "zh",
        pdf_text=pdf_text,
        reference_entries=extract_reference_entries(pdf_text),
    )
    _SESSION_CACHE[session.session_id] = session
    return session
```

Add file intake:

```python
def create_session_from_pdf_bytes(
    filename: str,
    content: bytes,
    settings: Any,
    answer_language: str | None = None,
) -> CitationTraceSession:
    pdf_text = pdf_bytes_to_text(content)
    title = normalize_whitespace(filename) or "Uploaded PDF"
    target = CitationTracePaperNode(
        paper_id="target",
        source="target",
        source_id=filename,
        canonical_id=f"file:{filename}",
        title=title,
        abstract=pdf_text[:1200],
    )
    session = CitationTraceSession(
        session_id=uuid.uuid4().hex,
        source_type="file",
        source_id=filename,
        source_url=None,
        target_paper=target,
        answer_language=answer_language or "zh",
        pdf_text=pdf_text,
        reference_entries=extract_reference_entries(pdf_text),
    )
    _SESSION_CACHE[session.session_id] = session
    return session
```

- [ ] **Step 4: Add file request schema and route**

In `backend/main.py`, add:

```python
@app.post("/api/citation-trace/session/from-file", response_model=CitationTraceSessionModel)
async def api_citation_trace_session_from_file(
    file: UploadFile = File(...),
    answer_language: str | None = Form(None),
    settings: str | None = Form(None),
) -> CitationTraceSessionModel:
    try:
        parsed_settings = parse_runtime_settings_form(settings)
        with retrieval_runtime_scope(parsed_settings) as (runtime_settings, _sources):
            content = await file.read()
            session = citation_trace_service.create_session_from_pdf_bytes(
                file.filename or "paper.pdf",
                content,
                runtime_settings,
                answer_language,
            )
        return citation_trace_session_to_model(session)
    except Exception as exc:
        raise to_http_detail(exc) from exc
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_citation_trace_service tests.test_citation_trace_api
```

Expected: all tests pass.

- [ ] **Step 6: Commit Task 4**

Run:

```bash
git add backend/citation_trace_service.py backend/main.py backend/schemas.py tests/test_citation_trace_service.py tests/test_citation_trace_api.py
git commit -m "Add citation trace paper intake"
```

Expected: commit succeeds with only these files staged.

---

### Task 5: Implement Two-Round Execution And Synthesis Fallbacks

**Files:**
- Modify: `backend/citation_trace_service.py`
- Modify: `tests/test_citation_trace_service.py`

- [ ] **Step 1: Add failing tests for round summaries and synthesis fallback**

Add to `tests/test_citation_trace_service.py`:

```python
    def test_run_citation_trace_keeps_round_one_when_round_two_seed_fails(self):
        session = cts.CitationTraceSession(
            session_id="run-session",
            source_type="file",
            source_id="paper.pdf",
            source_url=None,
            target_paper=cts.CitationTracePaperNode("target", "target", "paper.pdf", "file:paper.pdf", "Target", abstract="attention method"),
            answer_language="en",
            reference_entries=[
                cts.ReferenceEntry("ref-1", "Good reference. arXiv:1601.00001", arxiv_id="1601.00001", title_hint="Good reference"),
                cts.ReferenceEntry("ref-2", "Bad reference. arXiv:1601.00002", arxiv_id="1601.00002", title_hint="Bad reference"),
            ],
        )
        original_resolve = cts.resolve_reference_to_node
        original_expand = cts.expand_seed_candidates
        try:
            cts.resolve_reference_to_node = lambda reference, settings: cts.CitationTracePaperNode(reference.arxiv_id or reference.reference_id, "arxiv", reference.arxiv_id or reference.reference_id, reference.reference_id, reference.title_hint or "Paper", abstract="attention method")
            def expand(seed, settings):
                if seed.paper_id == "1601.00002":
                    raise RuntimeError("seed failed")
                return [cts.CitationTracePaperNode("prior", "arxiv", "prior", "prior", "Prior", abstract="attention")]
            cts.expand_seed_candidates = expand
            events = list(cts.run_citation_trace_events(session, settings=None))
        finally:
            cts.resolve_reference_to_node = original_resolve
            cts.expand_seed_candidates = original_expand

        self.assertTrue(any(name == "round_summary" and payload["round"] == 1 for name, payload in events))
        self.assertEqual(session.rounds[0].status, "completed")
        self.assertEqual(session.rounds[1].status, "partial")
        self.assertTrue(session.rounds[1].warnings)

    def test_synthesis_failure_leaves_ledger_available(self):
        session = cts.CitationTraceSession(
            session_id="synthesis-fail",
            source_type="file",
            source_id="paper.pdf",
            source_url=None,
            target_paper=cts.CitationTracePaperNode("target", "target", "paper.pdf", "file:paper.pdf", "Target"),
            answer_language="en",
            ledger_entries=[
                cts.CitationTraceLedgerEntry(
                    "entry",
                    cts.CitationTracePaperNode("paper", "arxiv", "paper", "paper", "Paper"),
                    None,
                    1,
                    "retrieved_similar",
                    "medium",
                    0.5,
                    cts.CitationTraceScoreBreakdown(),
                )
            ],
        )
        original = cts.synthesize_final_top5
        try:
            cts.synthesize_final_top5 = lambda session, settings: (_ for _ in ()).throw(RuntimeError("model failed"))
            events = list(cts.run_synthesis_stage(session, settings=None))
        finally:
            cts.synthesize_final_top5 = original

        self.assertEqual(session.final_top5, [])
        self.assertTrue(any(name == "warning" and "model failed" in payload["message"] for name, payload in events))
        self.assertEqual(len(session.ledger_entries), 1)
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
.venv/bin/python -m unittest tests.test_citation_trace_service
```

Expected: fail because two-round execution helpers are incomplete.

- [ ] **Step 3: Add reference resolution and seed expansion seams**

Add these functions to `backend/citation_trace_service.py`:

```python
def resolve_reference_to_node(reference: ReferenceEntry, settings: Any) -> CitationTracePaperNode | None:
    if reference.arxiv_id:
        record = fetch_arxiv_record(reference.arxiv_id)
        if record:
            return CitationTracePaperNode(
                paper_id=record.arxiv_id or reference.arxiv_id,
                source="arxiv",
                source_id=record.source_id,
                canonical_id=build_canonical_paper_id(
                    title=record.title,
                    authors=record.authors,
                    published_date=record.published_date,
                    arxiv_id=record.arxiv_id,
                    doi=record.doi,
                ),
                title=record.title,
                abstract=record.summary,
                authors=list(record.authors),
                published_date=record.published_date,
                arxiv_id=record.arxiv_id,
                doi=record.doi,
                external_url=record.external_url,
            )
    return None


def expand_seed_candidates(seed: CitationTracePaperNode, settings: Any) -> list[CitationTracePaperNode]:
    return []
```

Later tasks can connect `expand_seed_candidates` to local/arXiv/WoS retrieval. This task makes round orchestration and fallback behavior real.

- [ ] **Step 4: Replace `run_citation_trace_events` with round orchestration**

Use this implementation:

```python
def _round_summary_payload(summary: CitationTraceRoundSummary) -> dict[str, Any]:
    return {
        "round": summary.round,
        "status": summary.status,
        "seed_count": summary.seed_count,
        "candidate_count": summary.candidate_count,
        "selected_count": summary.selected_count,
        "warnings": list(summary.warnings),
    }


def run_round_one(session: CitationTraceSession, settings: Any) -> CitationTraceRoundSummary:
    entries: list[CitationTraceLedgerEntry] = []
    warnings: list[str] = []
    for reference in session.reference_entries:
        node = resolve_reference_to_node(reference, settings)
        if node is None:
            _node, entry = build_unresolved_reference_record(reference, seed_paper_id=session.target_paper.paper_id)
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
    entries.sort(key=lambda item: item.score_total, reverse=True)
    selected = entries[:10]
    summary = CitationTraceRoundSummary(
        round=1,
        status="completed" if selected else "partial",
        seed_count=1,
        candidate_count=len(entries),
        selected_count=len(selected),
        ledger_entries=selected,
        summary_text="Round 1 selected explicit references and unresolved reference records.",
        warnings=warnings,
    )
    return summary


def run_round_two(session: CitationTraceSession, settings: Any, round_one: CitationTraceRoundSummary) -> CitationTraceRoundSummary:
    entries: list[CitationTraceLedgerEntry] = []
    warnings: list[str] = []
    seeds = [entry.candidate_paper for entry in round_one.ledger_entries[:10] if entry.candidate_paper.source != "unresolved"]
    for seed in seeds:
        try:
            candidates = expand_seed_candidates(seed, settings)
            entries.extend(select_round_candidates(seed, candidates, round_number=2, limit=3))
        except Exception as exc:
            warnings.append(f"{seed.title}: {exc}")
    status: RoundStatus = "completed"
    if warnings and entries:
        status = "partial"
    elif warnings and not entries:
        status = "failed"
    summary = CitationTraceRoundSummary(
        round=2,
        status=status,
        seed_count=len(seeds),
        candidate_count=len(entries),
        selected_count=len(entries),
        ledger_entries=entries,
        summary_text="Round 2 expanded each resolved round 1 seed independently.",
        warnings=warnings,
    )
    return summary


def synthesize_final_top5(session: CitationTraceSession, settings: Any) -> list[CitationTraceTopPaper]:
    candidates = []
    for index, entry in enumerate(session.ledger_entries[:5], start=1):
        candidates.append(
            CitationTraceTopPaper(
                rank=index,
                paper_id=entry.candidate_paper.paper_id,
                title=entry.candidate_paper.title,
                influence_area="unknown",
                reason=entry.llm_assessment or "Selected from the current evidence ledger.",
                evidence_level=entry.evidence_level,
                is_explicitly_cited=entry.relation_type == "explicit_reference",
                is_exploratory=entry.relation_type != "explicit_reference",
                why_worth_reading="It is one of the strongest currently available provenance candidates.",
                uncertainty="LLM synthesis fallback used until model ranking is configured.",
                supporting_edge_ids=[entry.entry_id],
            )
        )
    return enforce_final_top5_policy(candidates)


def run_synthesis_stage(session: CitationTraceSession, settings: Any) -> Iterator[tuple[str, dict[str, Any]]]:
    yield "stage_start", {"stage": "synthesis", "session_id": session.session_id}
    try:
        session.final_top5 = synthesize_final_top5(session, settings)
    except Exception as exc:
        session.warnings.append(f"Synthesis failed: {exc}")
        yield "warning", {"message": f"Synthesis failed: {exc}"}
        return
    yield "complete", {"session_id": session.session_id, "final_top5_count": len(session.final_top5)}


def run_citation_trace_events(session: CitationTraceSession, settings: Any) -> Iterator[tuple[str, dict[str, Any]]]:
    yield "stage_start", {"stage": "reference_resolution", "session_id": session.session_id}
    round_one = run_round_one(session, settings)
    session.rounds = [round_one]
    session.ledger_entries = list(round_one.ledger_entries)
    yield "round_summary", _round_summary_payload(round_one)
    for entry in round_one.ledger_entries:
        yield "ledger_entry", {"entry_id": entry.entry_id, "round": entry.round, "title": entry.candidate_paper.title}

    yield "stage_start", {"stage": "round_two", "session_id": session.session_id}
    round_two = run_round_two(session, settings, round_one)
    session.rounds.append(round_two)
    session.ledger_entries.extend(round_two.ledger_entries)
    yield "round_summary", _round_summary_payload(round_two)
    for warning in round_two.warnings:
        yield "warning", {"message": warning}

    yield from run_synthesis_stage(session, settings)
```

- [ ] **Step 5: Run service tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_citation_trace_service
```

Expected: all tests pass.

- [ ] **Step 6: Run API tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_citation_trace_api
```

Expected: all tests pass.

- [ ] **Step 7: Commit Task 5**

Run:

```bash
git add backend/citation_trace_service.py tests/test_citation_trace_service.py
git commit -m "Add citation trace execution flow"
```

Expected: commit succeeds with only these files staged.

---

### Task 6: Remove Legacy PST From Search Service And CLI

**Files:**
- Modify: `local_paper_db/app/search_service.py`
- Modify: `local_paper_db/app/search.py`
- Create: `tests/test_citation_trace_cleanup.py`

- [ ] **Step 1: Add failing cleanup tests**

Create `tests/test_citation_trace_cleanup.py`:

```python
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CitationTraceCleanupTest(unittest.TestCase):
    def test_search_service_no_longer_exposes_pst_trace_execution(self):
        text = (ROOT / "local_paper_db/app/search_service.py").read_text()

        self.assertNotIn("TraceExecution", text)
        self.assertNotIn("execute_trace", text)
        self.assertNotIn("stream_trace_answer_tokens", text)
        self.assertNotIn("PST-lite", text)

    def test_cli_no_longer_exposes_trace_flag(self):
        text = (ROOT / "local_paper_db/app/search.py").read_text()

        self.assertNotIn("--trace", text)
        self.assertNotIn("trace_once", text)
        self.assertNotIn("PST", text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run cleanup tests and verify they fail**

Run:

```bash
.venv/bin/python -m unittest tests.test_citation_trace_cleanup
```

Expected: fail because legacy PST text still exists.

- [ ] **Step 3: Remove trace execution dataclass and functions from `search_service.py`**

Remove:

- `TraceExecution`
- `build_trace_retrieval_text`
- `build_trace_rerank_query`
- `build_trace_generation_prompt`
- `execute_trace`
- `stream_trace_answer_tokens`

Keep these if still used by Citation Trace or target selection:

- `TargetPaper`
- `target_paper_from_external_record`
- `resolve_target_paper`
- `fetch_target_paper_by_id`
- `vector_search_prior_work_top_k`
- `collect_prior_work_candidates`
- `rerank_with_api`
- `build_ranked_paper_fallback`

After removal, run:

```bash
rg -n "TraceExecution|execute_trace|stream_trace_answer_tokens|PST-lite" local_paper_db/app/search_service.py
```

Expected: no output.

- [ ] **Step 4: Remove CLI trace mode from `search.py`**

In `local_paper_db/app/search.py`, remove these imports:

```python
TargetPaper
execute_trace
infer_user_language
parse_arxiv_query
resolve_target_paper
stream_trace_answer_tokens
```

Remove:

- `print_target_paper`
- `choose_target_paper`
- `trace_once`
- `--trace`
- `--trace-language`
- the `if args.trace_query:` branch

Run:

```bash
rg -n "trace_once|--trace|PST|execute_trace|stream_trace_answer_tokens" local_paper_db/app/search.py
```

Expected: no output.

- [ ] **Step 5: Run cleanup tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_citation_trace_cleanup
```

Expected: all tests pass.

- [ ] **Step 6: Run existing search-service import smoke check**

Run:

```bash
.venv/bin/python -m py_compile local_paper_db/app/search_service.py local_paper_db/app/search.py
```

Expected: command exits 0.

- [ ] **Step 7: Commit Task 6**

Run:

```bash
git add local_paper_db/app/search_service.py local_paper_db/app/search.py tests/test_citation_trace_cleanup.py
git commit -m "Remove legacy PST trace helpers"
```

Expected: commit succeeds with only these files staged.

---

### Task 7: Add Citation Trace Frontend Page And Remove PST Workspace Mode

**Files:**
- Create: `frontend/src/CitationTracePage.jsx`
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/styles.css`
- Create: `tests/test_citation_trace_frontend.py`

- [ ] **Step 1: Add failing frontend static tests**

Create `tests/test_citation_trace_frontend.py`:

```python
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "frontend/src/App.jsx"
PAGE = ROOT / "frontend/src/CitationTracePage.jsx"


class CitationTraceFrontendTest(unittest.TestCase):
    def test_app_imports_citation_trace_page_and_has_no_pst_mode(self):
        text = APP.read_text()

        self.assertIn("CitationTracePage", text)
        self.assertIn("citationTraceTab", text)
        self.assertNotIn("pstMode", text)
        self.assertNotIn("workspaceMode === \"pst\"", text)
        self.assertNotIn("pst_auto", text)
        self.assertNotIn("/api/trace/", text)

    def test_citation_trace_page_contains_required_sections(self):
        text = PAGE.read_text()

        self.assertIn("/api/citation-trace/session/from-arxiv", text)
        self.assertIn("/api/citation-trace/session/from-file", text)
        self.assertIn("finalTop5", text)
        self.assertIn("evidenceLedger", text)
        self.assertIn("exploratorySources", text)
        self.assertIn("citation_trace_auto", text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run frontend static tests and verify they fail**

Run:

```bash
.venv/bin/python -m unittest tests.test_citation_trace_frontend
```

Expected: fail because the page does not exist and App still contains PST.

- [ ] **Step 3: Create `CitationTracePage.jsx`**

Create `frontend/src/CitationTracePage.jsx`:

```jsx
import { useRef, useState } from "react";
import ProgressTracker from "./ProgressTracker.jsx";

const citationTraceSteps = [
  { key: "load_paper", labelKey: "citationTraceProgressLoad" },
  { key: "reference_resolution", labelKey: "citationTraceProgressReferences" },
  { key: "round_one", labelKey: "citationTraceProgressRoundOne" },
  { key: "round_two", labelKey: "citationTraceProgressRoundTwo" },
  { key: "synthesis", labelKey: "citationTraceProgressSynthesis" },
  { key: "final_top5", labelKey: "citationTraceProgressTop5" }
];

function safeArray(value) {
  return Array.isArray(value) ? value : [];
}

export default function CitationTracePage({
  language,
  t,
  runtimePayload,
  onAssistantAutoReply,
  renderAssistantLayer
}) {
  const [arxivUrl, setArxivUrl] = useState("");
  const [pdfFile, setPdfFile] = useState(null);
  const [session, setSession] = useState(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState({ step: "load_paper", status: "idle", detail: "", updatedAt: null });
  const [selectedEntry, setSelectedEntry] = useState(null);
  const sourceRef = useRef(null);

  const progressSteps = citationTraceSteps.map((step) => ({ key: step.key, label: t(step.labelKey) }));
  const ledgerEntries = safeArray(session?.ledger_entries);
  const finalTop5 = safeArray(session?.final_top5);
  const exploratorySources = ledgerEntries.filter((entry) => entry.relation_type !== "explicit_reference");

  function setProgressState(step, status, detail = "") {
    setProgress({ step, status, detail, updatedAt: new Date().toISOString() });
  }

  async function readJson(response) {
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.detail || t("citationTraceFailed"));
    }
    return data;
  }

  async function createFromArxiv() {
    if (!arxivUrl.trim()) {
      setMessage(t("citationTraceUrlRequired"));
      return;
    }
    setBusy(true);
    setMessage("");
    setProgressState("load_paper", "running", t("citationTraceProgressLoad"));
    try {
      const response = await fetch("/api/citation-trace/session/from-arxiv", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: arxivUrl.trim(), answer_language: language, settings: runtimePayload })
      });
      const data = await readJson(response);
      setSession(data);
      setProgressState("reference_resolution", "ready", t("citationTraceReadyToRun"));
    } catch (error) {
      setMessage(String(error));
      setProgressState("load_paper", "interrupted", String(error));
    } finally {
      setBusy(false);
    }
  }

  async function createFromFile() {
    if (!pdfFile) {
      setMessage(t("citationTraceFileRequired"));
      return;
    }
    setBusy(true);
    setMessage("");
    setProgressState("load_paper", "running", t("citationTraceProgressLoad"));
    const form = new FormData();
    form.append("file", pdfFile);
    form.append("answer_language", language);
    if (runtimePayload) {
      form.append("settings", JSON.stringify(runtimePayload));
    }
    try {
      const response = await fetch("/api/citation-trace/session/from-file", { method: "POST", body: form });
      const data = await readJson(response);
      setSession(data);
      setProgressState("reference_resolution", "ready", t("citationTraceReadyToRun"));
    } catch (error) {
      setMessage(String(error));
      setProgressState("load_paper", "interrupted", String(error));
    } finally {
      setBusy(false);
    }
  }

  function streamTrace() {
    if (!session?.session_id) {
      setMessage(t("citationTraceNoSession"));
      return;
    }
    sourceRef.current?.close();
    setBusy(true);
    setMessage("");
    setProgressState("reference_resolution", "running", t("citationTraceProgressReferences"));
    const source = new EventSource(`/api/citation-trace/session/${session.session_id}/stream`);
    sourceRef.current = source;
    source.addEventListener("stage_start", (event) => {
      const payload = JSON.parse(event.data);
      setProgressState(payload.stage || "reference_resolution", "running", payload.stage || "");
    });
    source.addEventListener("round_summary", (event) => {
      const payload = JSON.parse(event.data);
      setProgressState(payload.round === 1 ? "round_one" : "round_two", payload.status || "completed", `round ${payload.round}`);
      refreshSession(session.session_id).catch((error) => setMessage(String(error)));
    });
    source.addEventListener("ledger_entry", () => {
      refreshSession(session.session_id).catch((error) => setMessage(String(error)));
    });
    source.addEventListener("warning", (event) => {
      const payload = JSON.parse(event.data);
      setMessage(payload.message || t("citationTraceWarning"));
    });
    source.addEventListener("complete", () => {
      source.close();
      setBusy(false);
      setProgressState("final_top5", "completed", t("citationTraceCompleted"));
      refreshSession(session.session_id).then((data) => {
        const answerText = safeArray(data.final_top5).map((item) => `${item.rank}. ${item.title}: ${item.reason}`).join("\n");
        onAssistantAutoReply?.({
          source: "citation_trace_auto",
          message: "",
          answerContext: answerText,
          workflowContext: {
            kind: "citation_trace",
            answer_language: language,
            session_id: data.session_id,
            paper_title: data.target_paper?.title,
            answer_text: answerText,
            metadata: { ledger_count: safeArray(data.ledger_entries).length }
          }
        });
      }).catch((error) => setMessage(String(error)));
    });
    source.addEventListener("error", (event) => {
      source.close();
      setBusy(false);
      setProgressState(progress.step, "interrupted", event.data || t("citationTraceFailed"));
    });
  }

  async function refreshSession(sessionId) {
    const response = await fetch(`/api/citation-trace/session/${sessionId}`);
    const data = await readJson(response);
    setSession(data);
    return data;
  }

  return (
    <div className="search-layout citation-trace-layout">
      <section className="workspace citation-trace-main">
        <div className="section-heading">
          <div>
            <p className="eyebrow">{t("citationTraceTab")}</p>
            <h2>{t("citationTraceTitle")}</h2>
          </div>
          <button onClick={streamTrace} disabled={busy || !session}>
            {busy ? t("working") : t("citationTraceRun")}
          </button>
        </div>

        {message ? <div className="message">{message}</div> : null}

        <ProgressTracker
          title={t("citationTraceProgressTitle")}
          subtitle={t("citationTraceProgressSubtitle")}
          steps={progressSteps}
          currentStep={progress.step}
          status={progress.status}
          statusLabel={t(`progress${progress.status[0]?.toUpperCase() || "I"}${progress.status.slice(1)}`)}
          detail={progress.detail}
          updatedAt={progress.updatedAt}
        />

        <section className="citation-trace-inputs">
          <label>
            {t("citationTraceArxivUrl")}
            <input value={arxivUrl} onChange={(event) => setArxivUrl(event.target.value)} placeholder="https://arxiv.org/abs/1706.03762" />
          </label>
          <button onClick={createFromArxiv} disabled={busy}>{t("citationTraceLoadArxiv")}</button>
          <label>
            {t("citationTracePdfFile")}
            <input type="file" accept="application/pdf" onChange={(event) => setPdfFile(event.target.files?.[0] || null)} />
          </label>
          <button onClick={createFromFile} disabled={busy}>{t("citationTraceLoadPdf")}</button>
        </section>

        <section className="citation-trace-summary">
          <div>
            <h3>{t("finalTop5")}</h3>
            {finalTop5.length ? finalTop5.map((paper) => (
              <article key={paper.paper_id} className="result-card">
                <strong>{paper.rank}. {paper.title}</strong>
                <p>{paper.reason}</p>
                <p className="muted">{paper.evidence_level} · {paper.influence_area}</p>
              </article>
            )) : <p className="muted">{t("citationTraceNoTop5")}</p>}
          </div>
          <div>
            <h3>{t("exploratorySources")}</h3>
            {exploratorySources.length ? exploratorySources.slice(0, 8).map((entry) => (
              <button key={entry.entry_id} className="ledger-row compact" onClick={() => setSelectedEntry(entry)}>
                {entry.candidate_paper.title}
              </button>
            )) : <p className="muted">{t("citationTraceNoExploratory")}</p>}
          </div>
        </section>

        <section>
          <h3>{t("evidenceLedger")}</h3>
          <div className="citation-ledger">
            {ledgerEntries.length ? ledgerEntries.map((entry) => (
              <button key={entry.entry_id} className="ledger-row" onClick={() => setSelectedEntry(entry)}>
                <span>{entry.candidate_paper.title}</span>
                <span>{entry.relation_type}</span>
                <span>{entry.evidence_level}</span>
                <span>{entry.score_total}</span>
              </button>
            )) : <p className="muted">{t("citationTraceNoLedger")}</p>}
          </div>
        </section>
      </section>

      <aside className="assistant-column citation-trace-detail">
        {selectedEntry ? (
          <section className="detail-panel">
            <h3>{selectedEntry.candidate_paper.title}</h3>
            <p>{selectedEntry.candidate_paper.abstract || t("none")}</p>
            <p className="muted">{selectedEntry.reference_text || t("none")}</p>
          </section>
        ) : null}
        {renderAssistantLayer?.()}
      </aside>
    </div>
  );
}
```

- [ ] **Step 4: Modify `App.jsx` imports and tabs**

Add:

```jsx
import CitationTracePage from "./CitationTracePage.jsx";
```

Remove PST workspace state:

- `workspaceMode`
- `traceQuery`
- `resolvedTarget`
- `traceCandidates`
- PST branch in `workspaceProgressByMode`
- `buildPstWorkflowContext`
- `resolveTraceTarget`
- `executeTrace`
- PST mode toggle in the search workspace
- `TargetPaperCard` and `CandidateList` only if no longer used elsewhere

Add translations in both languages:

```jsx
citationTraceTab: "Citation Trace",
citationTraceTitle: "Citation Trace",
citationTraceRun: "Start Trace",
citationTraceArxivUrl: "arXiv URL",
citationTracePdfFile: "PDF File",
citationTraceLoadArxiv: "Load arXiv Paper",
citationTraceLoadPdf: "Load PDF",
citationTraceProgressTitle: "Citation Trace Progress",
citationTraceProgressSubtitle: "Follow reference parsing, two-round expansion, synthesis, and final top 5.",
citationTraceProgressLoad: "Load paper",
citationTraceProgressReferences: "Parse references",
citationTraceProgressRoundOne: "Round 1 top10",
citationTraceProgressRoundTwo: "Round 2 expansion",
citationTraceProgressSynthesis: "Synthesis",
citationTraceProgressTop5: "Final top5",
citationTraceReadyToRun: "Ready to start citation tracing.",
citationTraceCompleted: "Citation trace completed.",
citationTraceFailed: "Citation trace failed.",
citationTraceWarning: "Citation trace warning.",
citationTraceUrlRequired: "Please enter an arXiv URL.",
citationTraceFileRequired: "Please choose a PDF file first.",
citationTraceNoSession: "No citation trace session yet.",
finalTop5: "Final Top5",
evidenceLedger: "Evidence Ledger",
exploratorySources: "Exploratory Sources",
citationTraceNoTop5: "No final top5 yet.",
citationTraceNoExploratory: "No exploratory sources yet.",
citationTraceNoLedger: "No evidence ledger entries yet.",
```

Use these Chinese translations:

```jsx
citationTraceTab: "论文溯源",
citationTraceTitle: "论文溯源",
citationTraceRun: "开始溯源",
citationTraceArxivUrl: "arXiv 链接",
citationTracePdfFile: "PDF 文件",
citationTraceLoadArxiv: "载入 arXiv 论文",
citationTraceLoadPdf: "载入 PDF",
citationTraceProgressTitle: "论文溯源进度",
citationTraceProgressSubtitle: "跟踪引用解析、两轮扩展、综合和最终 Top5。",
citationTraceProgressLoad: "载入论文",
citationTraceProgressReferences: "解析引用",
citationTraceProgressRoundOne: "第一轮 top10",
citationTraceProgressRoundTwo: "第二轮扩展",
citationTraceProgressSynthesis: "综合图谱",
citationTraceProgressTop5: "最终 top5",
citationTraceReadyToRun: "已准备好开始论文溯源。",
citationTraceCompleted: "论文溯源已完成。",
citationTraceFailed: "论文溯源失败。",
citationTraceWarning: "论文溯源警告。",
citationTraceUrlRequired: "请先输入 arXiv 链接。",
citationTraceFileRequired: "请先选择 PDF 文件。",
citationTraceNoSession: "还没有论文溯源会话。",
finalTop5: "最终 Top5",
evidenceLedger: "证据账本",
exploratorySources: "探索性启发源",
citationTraceNoTop5: "还没有最终 Top5。",
citationTraceNoExploratory: "还没有探索性启发源。",
citationTraceNoLedger: "还没有证据账本条目。",
```

Add tab button:

```jsx
<button className={activeTab === "citation_trace" ? "active" : ""} onClick={() => setActiveTab("citation_trace")}>
  {t("citationTraceTab")}
</button>
```

Render page:

```jsx
{activeTab === "citation_trace" ? (
  <CitationTracePage
    language={language}
    t={t}
    runtimePayload={runtimePayload}
    onAssistantAutoReply={setAssistantAutoReply}
    renderAssistantLayer={renderAssistantLayer}
  />
) : null}
```

- [ ] **Step 5: Add minimal styles**

Add to `frontend/src/styles.css`:

```css
.citation-trace-layout {
  align-items: start;
}

.citation-trace-main {
  min-width: 0;
}

.citation-trace-inputs {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) auto minmax(220px, 1fr) auto;
  gap: 12px;
  align-items: end;
}

.citation-trace-summary {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(260px, 0.55fr);
  gap: 16px;
}

.citation-ledger {
  display: grid;
  gap: 8px;
}

.ledger-row {
  width: 100%;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 160px 100px 72px;
  gap: 10px;
  align-items: center;
  text-align: left;
}

.ledger-row.compact {
  grid-template-columns: minmax(0, 1fr);
}

.citation-trace-detail {
  min-width: 0;
}

@media (max-width: 900px) {
  .citation-trace-inputs,
  .citation-trace-summary,
  .ledger-row {
    grid-template-columns: 1fr;
  }
}
```

- [ ] **Step 6: Run frontend static tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_citation_trace_frontend
```

Expected: all tests pass.

- [ ] **Step 7: Run frontend build**

Run:

```bash
cd frontend && npm run build
```

Expected: build exits 0.

- [ ] **Step 8: Commit Task 7**

Run:

```bash
git add frontend/src/App.jsx frontend/src/CitationTracePage.jsx frontend/src/styles.css tests/test_citation_trace_frontend.py
git commit -m "Add citation trace frontend"
```

Expected: commit succeeds with only these files staged.

---

### Task 8: Rename Assistant Workflow Source From PST To Citation Trace

**Files:**
- Modify: `backend/schemas.py`
- Modify: `backend/live2d_service.py`
- Modify: `backend/assistant_memory.py`
- Modify: `tests/test_paper_reader_live2d_behavior.py`
- Modify: `tests/test_citation_trace_frontend.py`

- [ ] **Step 1: Add failing assistant source tests**

Append to `tests/test_citation_trace_cleanup.py`:

```python
    def test_assistant_source_uses_citation_trace_auto_not_pst_auto(self):
        files = [
            ROOT / "backend/schemas.py",
            ROOT / "backend/live2d_service.py",
            ROOT / "backend/assistant_memory.py",
            ROOT / "frontend/src/App.jsx",
            ROOT / "frontend/src/CitationTracePage.jsx",
        ]
        joined = "\n".join(path.read_text() for path in files)

        self.assertIn("citation_trace_auto", joined)
        self.assertNotIn("pst_auto", joined)
        self.assertNotIn("QA / PST", joined)
```

- [ ] **Step 2: Run cleanup tests and verify they fail if `pst_auto` remains**

Run:

```bash
.venv/bin/python -m unittest tests.test_citation_trace_cleanup
```

Expected: fail until all `pst_auto` and user-facing PST text is gone.

- [ ] **Step 3: Update backend assistant source handling**

In `backend/schemas.py`, keep:

```python
source: Literal["user", "qa_auto", "citation_trace_auto"]
```

In `backend/assistant_memory.py`, replace:

```python
if source == "pst_auto":
    return "[PST workflow auto follow-up trigger]"
```

with:

```python
if source == "citation_trace_auto":
    return "[Citation Trace workflow auto follow-up trigger]"
```

In `backend/live2d_service.py`, replace fallback text with Citation Trace wording:

```python
return "I'm here. We can keep talking through your question, or you can run QA / Citation Trace first and I'll help you interpret the result."
```

```python
return "我在呢，可以继续和我聊你的问题，或者先运行一次 QA / 论文溯源，我再帮你解读结果。"
```

Replace behavior rule:

```python
- For automatic QA/Citation Trace follow-ups, do not wait for user input. Send one concise suggestion or clarification.
```

Replace workflow label:

```python
workflow_label = "QA" if source == "qa_auto" else "Citation Trace"
```

- [ ] **Step 4: Update tests that mention `pst_auto`**

In `tests/test_paper_reader_live2d_behavior.py`, replace the assertion with:

```python
self.assertNotIn("pst_auto", app_source)
self.assertIn("citation_trace_auto", app_source)
```

If the file was specifically checking old PST behavior, move the new assertion to `tests/test_citation_trace_cleanup.py` and delete the old assertion.

- [ ] **Step 5: Run assistant and cleanup tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_citation_trace_cleanup tests.test_paper_reader_live2d_behavior
```

Expected: all tests pass.

- [ ] **Step 6: Commit Task 8**

Run:

```bash
git add backend/schemas.py backend/live2d_service.py backend/assistant_memory.py tests/test_citation_trace_cleanup.py tests/test_paper_reader_live2d_behavior.py
git commit -m "Rename assistant trace workflow source"
```

Expected: commit succeeds with only these files staged.

---

### Task 9: Update Documentation And Project Log

**Files:**
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `PROJECT_LOG.md`

- [ ] **Step 1: Add documentation checks**

Append to `tests/test_citation_trace_cleanup.py`:

```python
    def test_readmes_document_citation_trace_not_pst(self):
        readme = (ROOT / "README.md").read_text()
        zh = (ROOT / "README.zh-CN.md").read_text()

        self.assertIn("Citation Trace", readme)
        self.assertIn("论文溯源", zh)
        self.assertNotIn("PST-lite", readme)
        self.assertNotIn("PST-lite", zh)
```

- [ ] **Step 2: Run documentation check and verify it fails**

Run:

```bash
.venv/bin/python -m unittest tests.test_citation_trace_cleanup.CitationTraceCleanupTest.test_readmes_document_citation_trace_not_pst
```

Expected: fail until README files are updated.

- [ ] **Step 3: Update README summaries**

In `README.md`, replace references to trace/PST with Citation Trace. Use this paragraph in the Web Workbench section:

```md
- `Citation Trace`
  Load an arXiv paper or PDF, extract and resolve references, run two-round provenance expansion, inspect an evidence ledger, and review a fallback final top 5 assembled from the current evidence ledger until model ranking is wired in.
```

In `README.zh-CN.md`, use:

```md
- `论文溯源`
  输入 arXiv 链接或上传 PDF，抽取并解析 references，执行两轮溯源扩展，查看证据账本，并在模型排序接入前基于当前证据账本生成兜底最终 Top5。
```

Replace source provenance notes with "search and Citation Trace responses" / "搜索和论文溯源返回结果".

- [ ] **Step 4: Update `PROJECT_LOG.md`**

Run:

```bash
date '+%Y-%m-%d %H:%M'
```

Expected: prints the local timestamp for the log entry.

Add a new top entry with the timestamp returned by the command above. Use this exact summary and file list, and write the verification line from the commands that passed in this implementation run:

- 摘要：用新的 `Citation Trace / 论文溯源` 工作台替代旧 PST-lite，新增引用抽取、两轮溯源扩展、证据账本、基于账本的兜底 Top5 后端/API/前端骨架，并移除旧 `/api/trace/*` 与 `pst_auto` 概念。
- 涉及文件：`backend/citation_trace_service.py`、`backend/main.py`、`backend/schemas.py`、`backend/live2d_service.py`、`backend/assistant_memory.py`、`local_paper_db/app/search_service.py`、`local_paper_db/app/search.py`、`frontend/src/App.jsx`、`frontend/src/CitationTracePage.jsx`、`frontend/src/styles.css`、`README.md`、`README.zh-CN.md`、`tests/test_citation_trace_service.py`、`tests/test_citation_trace_api.py`、`tests/test_citation_trace_frontend.py`、`tests/test_citation_trace_cleanup.py`
- 后续：记录真实 arXiv/PDF 端到端人工验收结果，以及需要继续增强的图谱交互或引用解析能力。

- [ ] **Step 5: Run documentation test**

Run:

```bash
.venv/bin/python -m unittest tests.test_citation_trace_cleanup
```

Expected: all tests pass.

- [ ] **Step 6: Commit Task 9**

Run:

```bash
git add README.md README.zh-CN.md PROJECT_LOG.md tests/test_citation_trace_cleanup.py
git commit -m "Document citation trace workspace"
```

Expected: commit succeeds with only these files staged.

---

### Task 10: Full Verification And Final Cleanup

**Files:**
- Verify all modified files from prior tasks.

- [ ] **Step 1: Run focused Citation Trace tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_citation_trace_service tests.test_citation_trace_api tests.test_citation_trace_frontend tests.test_citation_trace_cleanup
```

Expected: all tests pass.

- [ ] **Step 2: Run existing backend tests**

Run:

```bash
.venv/bin/python -m unittest discover -s tests
```

Expected: all tests pass.

- [ ] **Step 3: Run Python compile checks**

Run:

```bash
.venv/bin/python -m py_compile backend/citation_trace_service.py backend/main.py backend/schemas.py backend/live2d_service.py backend/assistant_memory.py local_paper_db/app/search_service.py local_paper_db/app/search.py
```

Expected: command exits 0.

- [ ] **Step 4: Run frontend build**

Run:

```bash
cd frontend && npm run build
```

Expected: build exits 0.

- [ ] **Step 5: Run diff whitespace check**

Run:

```bash
git diff --check
```

Expected: no output and exit code 0.

- [ ] **Step 6: Search for forbidden legacy PST strings**

Run:

```bash
rg -n "PST|pst_auto|/api/trace|TraceExecution|execute_trace|stream_trace_answer_tokens" backend frontend/src local_paper_db/app tests README.md README.zh-CN.md
```

Expected: no output, except historical mentions inside `docs/superpowers/specs/2026-06-20-citation-trace-design.md` and this plan if the command is widened to `docs/`.

- [ ] **Step 7: Inspect final git status**

Run:

```bash
git status --short
```

Expected: only intentional uncommitted changes remain. If unrelated pre-existing files still appear, leave them unstaged and mention them in the final response.

- [ ] **Step 8: Close verification cleanly**

If Step 5 or Step 6 exposed a regression, return to the task that introduced that file, fix it there, rerun that task's tests, and commit through that task's commit step. If no cleanup was needed, finish with the status report from Step 7.

---

## Self-Review

- Spec coverage: The plan removes old PST routes/UI/source naming, adds `backend/citation_trace_service.py`, adds `/api/citation-trace/*`, adds a standalone `CitationTracePage`, implements references, unresolved entries, two-round summaries, synthesis fallback, evidence ledger, final top5 policy, tests, README updates, and project log.
- Placeholder scan: The plan avoids deferred placeholder language. It contains concrete file paths, test code, implementation snippets, commands, and expected results for each task.
- Type consistency: The core names are consistent across service, schema, API, and frontend: `CitationTraceSession`, `CitationTracePaperNode`, `CitationTraceLedgerEntry`, `CitationTraceTopPaper`, `/api/citation-trace/*`, and `citation_trace_auto`.
