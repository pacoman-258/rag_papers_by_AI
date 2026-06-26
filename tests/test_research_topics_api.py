import unittest

from fastapi.testclient import TestClient

from backend.main import app
from backend import research_topics_service as rts


class ResearchTopicsApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self._original_use_memory_store = rts.USE_MEMORY_STORE
        rts.USE_MEMORY_STORE = True
        rts._MEMORY_STORE.reset()

    def tearDown(self) -> None:
        rts.USE_MEMORY_STORE = self._original_use_memory_store
        rts._MEMORY_STORE.reset()

    def test_create_topic_and_attach_paper_thread(self) -> None:
        topic_response = self.client.post(
            "/api/research-topics",
            json={
                "title": "Graph RAG Memory",
                "description": "Long-term graph memory",
                "keywords": ["graph rag"],
            },
        )
        self.assertEqual(topic_response.status_code, 200)
        topic = topic_response.json()

        thread_response = self.client.post(
            f"/api/research-topics/{topic['topic_id']}/papers",
            json={
                "paper": {
                    "title": "Attention Is All You Need",
                    "arxiv_id": "1706.03762",
                    "source": "arxiv",
                },
                "reader_session_id": "reader-1",
            },
        )
        self.assertEqual(thread_response.status_code, 200)
        first_thread = thread_response.json()

        second_response = self.client.post(
            f"/api/research-topics/{topic['topic_id']}/papers",
            json={
                "paper": {
                    "title": "Attention Is All You Need",
                    "arxiv_id": "1706.03762v2",
                    "source": "arxiv",
                },
                "reader_session_id": "reader-2",
            },
        )
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(first_thread["thread_id"], second_response.json()["thread_id"])

    def test_thread_event_and_trace_action_routes(self) -> None:
        topic = rts.create_topic(title="Citation Evidence", description="", keywords=[])
        thread = rts.create_or_resume_thread(
            topic_id=topic["topic_id"],
            paper={"title": "Citation Paper", "source_id": "paper-1"},
            reader_session_id="reader-1",
        )

        event_response = self.client.post(
            f"/api/research-topics/threads/{thread['thread_id']}/events",
            json={
                "event_type": "paper_reader.progress",
                "source": "paper_reader",
                "payload": {"last_page": 4},
            },
        )
        self.assertEqual(event_response.status_code, 200)

        action_response = self.client.post(
            f"/api/research-topics/threads/{thread['thread_id']}/citation-trace-actions",
            json={
                "citation_trace_session_id": "trace-1",
                "target_paper": {"title": "Citation Paper"},
                "final_top5": [{"title": "Prior Work"}],
                "warnings": ["weak evidence"],
                "assistant_explanation": "Save as caveat.",
            },
        )
        self.assertEqual(action_response.status_code, 200)

        detail_response = self.client.get(
            f"/api/research-topics/{topic['topic_id']}/threads/{thread['thread_id']}"
        )
        self.assertEqual(detail_response.status_code, 200)
        detail = detail_response.json()
        self.assertEqual(detail["events"][0]["payload"]["last_page"], 4)
        self.assertEqual(detail["citation_trace_actions"][0]["citation_trace_session_id"], "trace-1")

    def test_search_suggestion_route_does_not_write_topic_records(self) -> None:
        topic = rts.create_topic(title="Graph RAG", description="", keywords=["graph rag"])
        response = self.client.post(
            "/api/assistant/suggestions/search",
            json={
                "query": "graph rag memory",
                "paper": {"title": "Graph RAG Memory", "arxiv_id": "2401.00001"},
                "topic_candidates": [topic],
            },
        )
        self.assertEqual(response.status_code, 200)
        suggestion = response.json()

        accept_response = self.client.post(f"/api/assistant/suggestions/{suggestion['suggestion_id']}/accept")
        self.assertEqual(accept_response.status_code, 200)
        self.assertEqual(rts.list_topic_threads(topic["topic_id"]), [])

    def test_thread_open_question_suggestion_route_records_on_accept(self) -> None:
        topic = rts.create_topic(title="Reading Questions", description="", keywords=[])
        thread = rts.create_or_resume_thread(
            topic_id=topic["topic_id"],
            paper={"title": "Question Paper", "source_id": "question-paper"},
            reader_session_id="reader-1",
        )

        response = self.client.post(
            "/api/assistant/suggestions/thread-open-question",
            json={"thread_id": thread["thread_id"], "question": "Which assumption is weakest?"},
        )
        self.assertEqual(response.status_code, 200)
        suggestion = response.json()
        self.assertEqual(suggestion["recommended_action"], "save_open_question")
        self.assertEqual(suggestion["target_thread_id"], thread["thread_id"])

        accept_response = self.client.post(f"/api/assistant/suggestions/{suggestion['suggestion_id']}/accept")
        self.assertEqual(accept_response.status_code, 200)
        events = rts.get_thread(thread["thread_id"])["events"]
        self.assertEqual(events[0]["event_type"], "paper_reader.open_question")
        self.assertEqual(events[0]["payload"]["question"], "Which assumption is weakest?")


if __name__ == "__main__":
    unittest.main()
