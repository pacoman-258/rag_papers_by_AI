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
        self.assertNotIn('workspaceMode === "pst"', text)
        self.assertNotIn("pst" + "_auto", text)
        self.assertNotIn("/api/" + "trace/", text)

    def test_app_exposes_citation_trace_model_settings(self):
        text = APP.read_text()

        self.assertIn("citation_trace_main_chat", text)
        self.assertIn("citation_trace_worker_chat", text)
        self.assertIn("citationTraceMainModel", text)
        self.assertIn("citationTraceWorkerModel", text)

    def test_citation_trace_page_contains_required_sections(self):
        text = PAGE.read_text()

        self.assertIn("/api/citation-trace/session/from-arxiv", text)
        self.assertIn("/api/citation-trace/session/from-file", text)
        self.assertIn("finalTop5", text)
        self.assertIn("evidenceLedger", text)
        self.assertIn("exploratorySources", text)
        self.assertIn("citation_trace_auto", text)
        self.assertIn("parseSseJson", text)
        self.assertIn("progressStepRef", text)
        self.assertIn("candidate_recall", text)
        self.assertIn("worker_assessment", text)
        self.assertIn("main_ranking", text)
        self.assertIn("citationTraceCandidateTop15", text)
        self.assertIn("citationTraceReferenceText", APP.read_text())
        self.assertIn("citationTraceReferenceText", text)
        self.assertIn("author_bonus", text)


if __name__ == "__main__":
    unittest.main()
