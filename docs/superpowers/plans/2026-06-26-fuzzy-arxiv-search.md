# Fuzzy arXiv Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve vague learning and authority-seeking paper queries without changing the normal search path.

**Architecture:** Add a small `search_intent` field to query plans, derive conservative fallbacks from the original query, and use intent-specific arXiv expansion plus lightweight result boosting before the existing reranker. Normal, latest, local, WOS, and rerank fallback behavior remain compatible.

**Tech Stack:** Python dataclasses, Pydantic schemas, FastAPI search API, arXiv adapter, unittest.

---

### Task 1: Search Intent Model

**Files:**
- Modify: `local_paper_db/app/search_service.py`
- Modify: `backend/schemas.py`
- Test: `tests/test_fuzzy_arxiv_search.py`

- [x] **Step 1: Write failing tests**

```python
def test_coerce_query_plan_detects_beginner_intent_when_model_omits_it(self):
    plan = ss.coerce_query_plan(
        {"answer_language": "zh", "intent_summary": "Find beginner deep learning papers", "retrieval_query_en": "beginner deep learning papers", "keywords_en": ["deep learning"]},
        "帮我找到关于深度学习的一些入门论文",
        "2026-06-26",
    )
    self.assertEqual(plan.search_intent, "beginner")
```

Run: `.venv/bin/python -m unittest tests.test_fuzzy_arxiv_search.FuzzyArxivSearchTest.test_coerce_query_plan_detects_beginner_intent_when_model_omits_it`
Expected: FAIL because `QueryPlan` has no `search_intent`.

- [x] **Step 2: Implement minimal model support**

Add `search_intent: str = "normal"` to `QueryPlan`, add `search_intent` to `QueryPlanModel`, and normalize allowed values to `normal`, `beginner`, `learning_path`, `canonical`, `latest`, `prior_work`.

- [x] **Step 3: Run focused tests**

Run: `.venv/bin/python -m unittest tests.test_fuzzy_arxiv_search.FuzzyArxivSearchTest.test_coerce_query_plan_detects_beginner_intent_when_model_omits_it`
Expected: PASS.

### Task 2: arXiv Intent Expansion

**Files:**
- Modify: `local_paper_db/app/external_sources.py`
- Modify: `local_paper_db/app/search_service.py`
- Test: `tests/test_fuzzy_arxiv_search.py`

- [x] **Step 1: Write failing tests**

```python
def test_beginner_arxiv_queries_add_survey_and_tutorial_tracks(self):
    constraints = ss.RetrievalConstraints(search_intent="beginner")
    queries = external_sources.build_arxiv_search_queries("deep learning; keywords: deep learning", constraints)
    self.assertGreaterEqual(len(queries), 2)
    self.assertTrue(any("survey" in query.lower() for query in queries))
    self.assertTrue(any("tutorial" in query.lower() or "overview" in query.lower() for query in queries))

def test_normal_arxiv_query_stays_single_track(self):
    constraints = ss.RetrievalConstraints()
    queries = external_sources.build_arxiv_search_queries("graph neural networks; keywords: graph neural networks", constraints)
    self.assertEqual(len(queries), 1)
```

Run: `.venv/bin/python -m unittest tests.test_fuzzy_arxiv_search.FuzzyArxivSearchTest.test_beginner_arxiv_queries_add_survey_and_tutorial_tracks tests.test_fuzzy_arxiv_search.FuzzyArxivSearchTest.test_normal_arxiv_query_stays_single_track`
Expected: FAIL because `build_arxiv_search_queries` does not exist.

- [x] **Step 2: Implement minimal expansion**

Expose `build_arxiv_search_queries(retrieval_text, constraints)`. Keep normal/latest as one query. For `beginner`, `learning_path`, and `canonical`, generate two to four arXiv queries by appending intent phrases while preserving author, category, and date constraints.

- [x] **Step 3: Run focused tests**

Run: `.venv/bin/python -m unittest tests.test_fuzzy_arxiv_search.FuzzyArxivSearchTest.test_beginner_arxiv_queries_add_survey_and_tutorial_tracks tests.test_fuzzy_arxiv_search.FuzzyArxivSearchTest.test_normal_arxiv_query_stays_single_track`
Expected: PASS.

### Task 3: Intent-Aware Candidate Ranking

**Files:**
- Modify: `local_paper_db/app/search_service.py`
- Test: `tests/test_fuzzy_arxiv_search.py`

- [x] **Step 1: Write failing tests**

```python
def test_beginner_sort_prefers_survey_candidate_without_hiding_similarity(self):
    constraints = ss.RetrievalConstraints(search_intent="beginner")
    papers = [
        self.paper("specific", "A Niche Deep Learning Optimization Trick", 0.80),
        self.paper("survey", "A Survey of Deep Learning", 0.75),
    ]
    sorted_papers = ss.sort_retrieved_papers(papers, constraints)
    self.assertEqual(sorted_papers[0].id, "survey")

def test_normal_sort_remains_similarity_ordered(self):
    papers = [
        self.paper("lower", "A Survey of Deep Learning", 0.75),
        self.paper("higher", "A Niche Deep Learning Optimization Trick", 0.80),
    ]
    sorted_papers = ss.sort_retrieved_papers(papers, ss.RetrievalConstraints())
    self.assertEqual(sorted_papers[0].id, "higher")
```

Run: `.venv/bin/python -m unittest tests.test_fuzzy_arxiv_search.FuzzyArxivSearchTest.test_beginner_sort_prefers_survey_candidate_without_hiding_similarity tests.test_fuzzy_arxiv_search.FuzzyArxivSearchTest.test_normal_sort_remains_similarity_ordered`
Expected: beginner test FAILS with existing similarity-only sorting; normal test PASSES.

- [x] **Step 2: Implement minimal boost**

Add small intent boosts in `sort_retrieved_papers` for `beginner`, `learning_path`, and `canonical`. Keep latest sorting by date first. Store boosts only in sorting keys, not in `initial_score`, so existing score display remains honest.

- [x] **Step 3: Run focused tests**

Run: `.venv/bin/python -m unittest tests.test_fuzzy_arxiv_search`
Expected: PASS.

### Task 4: Documentation And Verification

**Files:**
- Modify: `README.zh-CN.md`
- Modify: `README.md`
- Modify: `PROJECT_LOG.md`

- [x] **Step 1: Document behavior**

Add one short paragraph explaining that vague beginner, learning-path, and canonical paper requests use intent-aware arXiv expansion while preserving existing provider fallbacks.

- [x] **Step 2: Run compatibility checks**

Run:
`.venv/bin/python -m unittest tests.test_fuzzy_arxiv_search`
`.venv/bin/python -m py_compile local_paper_db/app/search_service.py local_paper_db/app/external_sources.py backend/schemas.py tests/test_fuzzy_arxiv_search.py`
`git diff --check -- local_paper_db/app/search_service.py local_paper_db/app/external_sources.py backend/schemas.py tests/test_fuzzy_arxiv_search.py README.md README.zh-CN.md PROJECT_LOG.md docs/superpowers/plans/2026-06-26-fuzzy-arxiv-search.md`

Expected: all commands pass.
