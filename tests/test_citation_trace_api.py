import unittest

from fastapi.testclient import TestClient

from backend.main import app
from backend import citation_trace_service as cts


class CitationTraceApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def tearDown(self):
        cts._SESSION_CACHE.clear()

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
            target_paper=cts.CitationTracePaperNode(
                "target",
                "target",
                "1706.03762",
                "arxiv:1706.03762",
                "Attention",
            ),
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
