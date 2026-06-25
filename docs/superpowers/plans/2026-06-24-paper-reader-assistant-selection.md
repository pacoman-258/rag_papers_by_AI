# Paper Reader Assistant Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Live2D use paper-wide Paper Reader context and allow explicit selection-to-assistant sync.

**Architecture:** Add a backend Paper Reader assistant-context response, fetch and store it in `PaperReaderPage.jsx`, and republish it with an optional manually synced selection. Update Live2D prompt rendering so paper context is whole-paper and selected excerpts are focus hints.

**Tech Stack:** FastAPI, Pydantic, Python unittest, React 18, Vite.

---

### Task 1: Backend Paper-Wide Assistant Context

**Files:**
- Modify: `backend/schemas.py`
- Modify: `backend/paper_reader_service.py`
- Modify: `backend/main.py`
- Test: `tests/test_paper_reader_translation.py`

- [ ] **Step 1: Write failing tests**

Add tests that call `build_assistant_context` on a session with multiple source pages/chunks and assert the returned `answer_context` includes paper-level metadata and multiple page excerpts.

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/bin/python -m unittest tests.test_paper_reader_translation.PaperReaderTranslationTest.test_assistant_context_uses_whole_paper_source_pages`

Expected: failure because the helper does not exist.

- [ ] **Step 3: Implement minimal backend helper and route**

Create `PaperReaderAssistantContextResponse`, `build_assistant_context(session_id)`, and `GET /api/paper-reader/session/{session_id}/assistant-context`.

- [ ] **Step 4: Verify backend tests pass**

Run: `.venv/bin/python -m unittest tests.test_paper_reader_translation.PaperReaderTranslationTest.test_assistant_context_uses_whole_paper_source_pages`

Expected: pass.
### Task 2: Live2D Prompt Context Semantics

**Files:**
- Modify: `backend/live2d_service.py`
- Test: `tests/test_paper_reader_translation.py`

- [ ] **Step 1: Write failing tests**

Add tests asserting Paper Reader prompt rules are not page-local and `_render_paper_reader_context_lines` includes `selected_excerpt` when present in metadata.

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/bin/python -m unittest tests.test_paper_reader_translation.PaperReaderTranslationTest.test_live2d_paper_reader_context_renders_manual_selection_focus`

Expected: failure because selected excerpts are not rendered and prompt still says page-local.

- [ ] **Step 3: Update prompt rendering**

Render selected excerpt details from `workflow_context.metadata.selected_excerpt` and rewrite paper-reader system/user prompts to say whole-paper context with optional selected focus.

- [ ] **Step 4: Verify tests pass**

Run: `.venv/bin/python -m unittest tests.test_paper_reader_translation.PaperReaderTranslationTest.test_live2d_paper_reader_context_renders_manual_selection_focus`

Expected: pass.

### Task 3: Frontend Explicit Selection Sync

**Files:**
- Modify: `frontend/src/PaperReaderPage.jsx`
- Modify: `frontend/src/styles.css`
- Test: `tests/test_paper_reader_live2d_behavior.py`

- [ ] **Step 1: Write failing tests**

Assert the frontend fetches `/assistant-context`, exposes a `syncSelectionToAssistant` action, passes `onSyncSelectionToAssistant` to the selection panel, and no longer publishes `extractAssistantContextText(activePage)` from the active-page effect.

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/bin/python -m unittest tests.test_paper_reader_live2d_behavior`

Expected: failure on missing sync action and assistant-context endpoint usage.

- [ ] **Step 3: Implement frontend state and controls**

Store the fetched paper assistant context, publish it to `onAssistantContextChange`, and add a secondary selection-card button that republishes the same context with `metadata.selected_excerpt`.

- [ ] **Step 4: Verify frontend tests pass**

Run: `.venv/bin/python -m unittest tests.test_paper_reader_live2d_behavior`

Expected: pass.

### Task 4: Final Verification and Log

**Files:**
- Modify: `PROJECT_LOG.md`

- [ ] **Step 1: Update project log**

Add a top entry with summary, touched files, verification commands, and follow-up notes.

- [ ] **Step 2: Run focused backend tests**

Run: `.venv/bin/python -m unittest tests.test_paper_reader_translation tests.test_paper_reader_live2d_behavior`

Expected: pass.

- [ ] **Step 3: Run Python compile check**

Run: `.venv/bin/python -m py_compile backend/schemas.py backend/paper_reader_service.py backend/main.py backend/live2d_service.py tests/test_paper_reader_translation.py tests/test_paper_reader_live2d_behavior.py`

Expected: pass.

- [ ] **Step 4: Run frontend build**

Run: `cd frontend && npm run build`

Expected: pass.
