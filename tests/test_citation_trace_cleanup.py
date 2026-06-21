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
