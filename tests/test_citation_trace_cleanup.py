import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CitationTraceCleanupTest(unittest.TestCase):
    def test_search_service_no_longer_exposes_pst_trace_execution(self):
        text = (ROOT / "local_paper_db/app/search_service.py").read_text()

        self.assertNotIn("Trace" + "Execution", text)
        self.assertNotIn("execute" + "_trace", text)
        self.assertNotIn("stream_trace" + "_answer_tokens", text)
        self.assertNotIn("P" + "ST-lite", text)

    def test_cli_no_longer_exposes_trace_flag(self):
        text = (ROOT / "local_paper_db/app/search.py").read_text()

        self.assertNotIn("--trace", text)
        self.assertNotIn("trace_once", text)
        self.assertNotIn("P" + "ST", text)

    def test_assistant_source_uses_citation_trace_auto_not_legacy_trace_source(self):
        files = [
            ROOT / "backend/schemas.py",
            ROOT / "backend/live2d_service.py",
            ROOT / "backend/assistant_memory.py",
            ROOT / "frontend/src/App.jsx",
            ROOT / "frontend/src/CitationTracePage.jsx",
        ]
        legacy_trace_source = "pst" + "_auto"
        legacy_workflow_label = "QA / " + "P" + "ST"

        for path in files:
            with self.subTest(path=str(path.relative_to(ROOT))):
                self.assertIn("citation_trace_auto", path.read_text())

        live2d_source = (ROOT / "backend/live2d_service.py").read_text()
        self.assertIn('source == "citation_trace_auto"', live2d_source)

        joined = "\n".join(path.read_text() for path in files)
        self.assertNotIn(legacy_trace_source, joined)
        self.assertNotIn(legacy_workflow_label, joined)

    def test_readmes_document_citation_trace_not_pst(self):
        readme = (ROOT / "README.md").read_text()
        zh = (ROOT / "README.zh-CN.md").read_text()

        self.assertIn("Citation Trace", readme)
        self.assertIn("论文溯源", zh)
        self.assertNotIn("P" + "ST-lite", readme)
        self.assertNotIn("P" + "ST-lite", zh)


if __name__ == "__main__":
    unittest.main()
