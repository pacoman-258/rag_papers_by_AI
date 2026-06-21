# Citation Trace Design

## Goal

Build a standalone `Citation Trace / 论文溯源` workspace that replaces the old PST-lite trace feature.

The new workflow is a reference-first, exploration-friendly citation provenance tool. It starts from a user-provided paper, follows explicit references where possible, supplements sparse or unresolved references with retrieval from enabled paper sources, and produces an auditable evidence ledger plus a final top 5 assembled from the current evidence package until model ranking is wired in.

## Product Decisions

- Remove the old PST-lite user-facing feature completely. Do not keep `/api/trace/*` compatibility routes.
- Add one standalone frontend tab: `Citation Trace` in English and `论文溯源` in Chinese.
- Use an evidence-first interface. The evidence ledger is the primary surface; the graph and final top 5 are summary views.
- Allow exploratory candidates, but label them clearly. Do not present inferred influence as confirmed citation.
- Assemble the current final top 5 from the evidence ledger with clear reasons and uncertainty. Low-evidence exploratory entries may appear in the final top 5, but at most two. A later model-ranking pass can replace this fallback once it is wired and tested.

## Architecture

Add `backend/citation_trace_service.py` as the owner of the new workflow:

1. Paper intake from arXiv URL or uploaded PDF.
2. Target metadata and PDF text extraction.
3. Reference section extraction and reference parsing.
4. Round 1 candidate selection from the target paper.
5. Round 2 candidate expansion from the round 1 seeds.
6. Evidence ledger assembly.
7. Evidence-ledger fallback synthesis for possible inspiration sources, provenance narrative, and final top 5; later model ranking can refine this stage.

The service may reuse existing lower-level helpers where they still fit:

- `local_paper_db/app/external_sources.py` for arXiv and WoS metadata lookup.
- `local_paper_db/app/search_service.py` for embeddings, similarity helpers, runtime settings, and chat model calls.
- Selected paper/PDF intake helpers from `backend/paper_reader_service.py`, while keeping reference extraction independent because Paper Reader's reading chunks intentionally stop before References.

Remove or rename old PST-lite concepts from the user-visible API and frontend. This includes `/api/trace/*`, trace schemas, trace sessions, PST tab text, and `pst_auto` workflow context naming.

## Data Model

### Paper Node

Each paper in the trace graph is represented as a node:

- `paper_id`
- `source`: `target`, `arxiv`, `local`, `wos`, or `unresolved`
- `source_id`
- `canonical_id`
- `title`
- `abstract`
- `authors`
- `published_date`
- `keywords`
- `arxiv_id`
- `doi`
- `external_url`

Unresolved references must remain visible as `source = "unresolved"` nodes or ledger entries so users can see what failed to resolve.

### Citation Edge

Each relationship is represented as an edge:

- `edge_id`
- `from_paper_id`
- `to_paper_id`
- `round`: `1` or `2`
- `relation_type`: `explicit_reference`, `retrieved_similar`, or `llm_inferred_influence`
- `evidence_level`: `strong`, `medium`, or `weak`
- `is_main_graph`
- `is_exploratory`
- `influence_area`: `problem`, `method`, `theory`, `experiment`, `dataset`, `evaluation`, `background`, or `unknown`
- `llm_reason`
- `uncertainty`

### Evidence Ledger Entry

The evidence ledger is the main UI record for a candidate relationship:

- `candidate_paper`
- `seed_paper`
- `round`
- `relation_type`
- `score_total`
- `score_breakdown.abstract_similarity`
- `score_breakdown.title_overlap`
- `score_breakdown.keyword_overlap`
- `score_breakdown.author_overlap`
- `score_breakdown.date_plausibility`
- `score_breakdown.reference_match`
- `reference_text`
- `metadata_evidence`
- `llm_assessment`
- `warnings`

`score_total` is for audit and sorting support. It does not directly determine the final top 5.

### Round Summary

Each round writes a displayable summary:

- `round`
- `status`: `pending`, `running`, `completed`, `partial`, or `failed`
- `seed_count`
- `candidate_count`
- `selected_count`
- `ledger_entries`
- `summary_text`
- `warnings`

Round 1 must be useful on its own. If round 2 or final synthesis fails, the first round result remains visible.

### Final Top 5

The current final top 5 is assembled from the evidence package:

- `rank`
- `paper_id`
- `title`
- `influence_area`
- `reason`
- `evidence_level`
- `is_explicitly_cited`
- `is_exploratory`
- `why_worth_reading`
- `uncertainty`
- `supporting_edge_ids`

Each item must explain why the paper is worth reading. Low-evidence exploratory entries are allowed, but at most two can appear in the final top 5.

## Execution Flow

### 1. Intake

The user provides an arXiv URL or uploads a PDF. For arXiv input, fetch metadata through the arXiv source and download the PDF. For PDF input, extract PDF metadata and first-page text, and warn when title, authors, or date cannot be determined confidently.

### 2. Reference Extraction

Locate the References or Bibliography section in PDF text and extract reference entries. Resolution priority:

1. arXiv ID.
2. DOI.
3. Title, author, and year.
4. Raw reference text as unresolved.

If references are sparse or cannot be resolved, continue with exploration mode and clearly warn that explicit citation evidence is limited.

### 3. Round 1

Use the target paper as the seed. Score explicit references and supplement with retrieval candidates from enabled providers when references are unresolved or too sparse. Build round 1 ledger entries and select up to 10 candidates with audit-ready metadata about how each selected paper may have inspired the target.

If fewer than 10 usable candidates exist, use all available candidates.

### 4. Round 2

Use the round 1 top 10 as seeds. For each seed, repeat candidate selection and keep up to 3 selected candidates. Each seed is independent: failure for one seed does not fail the whole round.

### 5. Synthesis

Read the round 1 top 10, round 2 candidates, and evidence ledger. The current fallback outputs:

- High-confidence main graph.
- Exploratory possible inspiration sources.
- Natural-language provenance chain.
- Final top 5 ordered from the evidence ledger, with evidence level and uncertainty.

### 6. Progress Events

Expose progress with SSE events:

- `stage_start`
- `reference_resolved`
- `round_summary`
- `ledger_entry`
- `synthesis_token`
- `warning`
- `complete`
- `error`

The frontend should show partial results as soon as they are available.

## Error Handling

- arXiv, WoS, or local source failure: record a warning and continue with remaining sources.
- Reference parse failure: preserve the raw entry as unresolved.
- Round 2 partial failure: keep round 1 and all successful round 2 seed results.
- Synthesis failure: show the evidence ledger and algorithmic candidates, and mark final top 5 as unavailable.
- Complete reference failure: continue in exploration mode, with a clear warning that explicit citation evidence is missing.

## Frontend

Add a standalone `Citation Trace / 论文溯源` tab.

The first version has these sections:

1. Input area: arXiv URL, PDF upload, output language, provider toggles, and one run button.
2. Progress rail: `Load paper`, `Parse references`, `Round 1 top10`, `Round 2 expansion`, `Synthesis`, `Final top5`.
3. Summary area: final top 5, main graph summary, and exploratory inspiration sources.
4. Evidence ledger: the primary table/list view with relation type, evidence level, score breakdown, assessment, and warnings.
5. Detail panel: selected entry metadata, original reference text, abstract, score breakdown, reason, uncertainty, and external links.

The first version should keep graph rendering modest. A chain list or lightweight graph summary is enough until the evidence ledger is stable.

Live2D workflow context should use a new source name such as `citation_trace_auto`. The assistant may explain current evidence, but must not turn exploratory or inferred relationships into confirmed citations.

## API Shape

Recommended route family:

- `POST /api/citation-trace/session/from-arxiv`
- `POST /api/citation-trace/session/from-file`
- `GET /api/citation-trace/session/{session_id}`
- `POST /api/citation-trace/session/{session_id}/execute`
- `GET /api/citation-trace/session/{session_id}/stream`

The old `/api/trace/*` routes should be removed.

## Tests

Add focused backend tests for:

- Reference extraction from PDF text.
- arXiv ID, DOI, and title-year reference resolution.
- Unresolved references staying visible.
- Round 1 using all candidates when fewer than 10 exist.
- Round 2 keeping at most 3 candidates per seed.
- Final top 5 containing at most two low-evidence exploratory entries.
- Synthesis failure still returning the evidence ledger.

Add API tests for:

- The new citation trace route family.
- SSE progress event names.
- Old `/api/trace/*` routes no longer existing.

Add frontend checks for:

- Old PST tab text and `pst_auto` no longer appearing in user-facing code.
- `Citation Trace / 论文溯源` tab exists.
- Evidence ledger, final top 5, and exploratory sources sections exist.
- `npm run build` passes.

Update README, README.zh-CN, and PROJECT_LOG when implementing the feature.
