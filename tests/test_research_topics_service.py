import json
import unittest
from unittest.mock import patch

import psycopg2

from backend import research_topics_service as rts


class FakeCursor:
    def __init__(self, rows: list[dict[str, object]] | None = None) -> None:
        self.rows = list(rows or [])
        self.executions: list[tuple[str, tuple[object, ...] | None]] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...] | None = None) -> None:
        self.executions.append((sql, params))

    def fetchone(self) -> dict[str, object]:
        return self.rows.pop(0)


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self.cursor_instance = cursor

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def cursor(self, *args: object, **kwargs: object) -> FakeCursor:
        return self.cursor_instance


class ResearchTopicsServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self._original_use_memory_store = rts.USE_MEMORY_STORE
        rts.USE_MEMORY_STORE = True
        rts._MEMORY_STORE.reset()

    def tearDown(self) -> None:
        rts.USE_MEMORY_STORE = self._original_use_memory_store
        rts._MEMORY_STORE.reset()

    def test_canonical_paper_key_prefers_arxiv_id(self) -> None:
        self.assertEqual(
            rts.canonical_paper_key(
                {
                    "arxiv_id": "https://arxiv.org/abs/1706.03762v7",
                    "title": "Attention Is All You Need",
                }
            ),
            "arxiv:1706.03762",
        )

    def test_same_topic_and_paper_resumes_one_thread(self) -> None:
        topic = rts.create_topic(title="Graph RAG Memory", description="", keywords=["graph rag"])
        first = rts.create_or_resume_thread(
            topic_id=topic["topic_id"],
            paper={
                "arxiv_id": "1706.03762",
                "title": "Attention Is All You Need",
                "source": "arxiv",
            },
            reader_session_id="reader-1",
        )
        second = rts.create_or_resume_thread(
            topic_id=topic["topic_id"],
            paper={
                "arxiv_id": "1706.03762v3",
                "title": "Attention Is All You Need",
                "source": "arxiv",
            },
            reader_session_id="reader-2",
        )

        self.assertEqual(first["thread_id"], second["thread_id"])
        self.assertEqual(first["paper_title"], "Attention Is All You Need")
        self.assertEqual(
            first["paper_metadata"],
            {
                "arxiv_id": "1706.03762",
                "title": "Attention Is All You Need",
                "source": "arxiv",
            },
        )
        self.assertEqual(first["last_page"], 0)
        self.assertEqual(first["progress"], 0.0)
        self.assertEqual(second["paper_title"], first["paper_title"])
        self.assertEqual(second["paper_metadata"], first["paper_metadata"])
        self.assertEqual(second["last_reader_session_id"], "reader-2")
        self.assertEqual(len(rts.list_topic_threads(topic["topic_id"])), 1)

    def test_thread_events_and_trace_actions_are_thread_scoped(self) -> None:
        topic = rts.create_topic(title="Long Context RAG", description="", keywords=[])
        thread = rts.create_or_resume_thread(
            topic_id=topic["topic_id"],
            paper={"title": "Context Windows for RAG", "source_id": "paper-1"},
            reader_session_id="reader-1",
        )

        event = rts.record_thread_event(
            thread_id=thread["thread_id"],
            event_type="paper_reader.question",
            source="user",
            payload={"question": "What is the main bottleneck?"},
        )
        action = rts.record_citation_trace_action(
            thread_id=thread["thread_id"],
            citation_trace_session_id="trace-1",
            target_paper={"title": "Context Windows for RAG"},
            final_top5=[{"title": "Prior Context Paper"}],
            warnings=["weak evidence"],
            assistant_explanation="Treat this as a caveat.",
        )

        detail = rts.get_thread(thread["thread_id"])
        self.assertEqual(event["thread_id"], thread["thread_id"])
        self.assertEqual(action["thread_id"], thread["thread_id"])
        self.assertIn("action_id", action)
        self.assertEqual(detail["citation_trace_actions"][0]["action_id"], action["action_id"])
        self.assertEqual(detail["events"][0]["payload"]["question"], "What is the main bottleneck?")
        self.assertEqual(detail["citation_trace_actions"][0]["warnings"], ["weak evidence"])
        completed_events = [
            event
            for event in detail["events"]
            if event["event_type"] == "citation_trace.completed"
        ]
        self.assertEqual(len(completed_events), 1)
        self.assertEqual(completed_events[0]["payload"]["action_id"], action["action_id"])
        self.assertNotIn("trace_action_id", completed_events[0]["payload"])

    def test_topic_insights_start_as_drafts_until_confirmed(self) -> None:
        topic = rts.create_topic(title="Retrieval Degradation", description="", keywords=[])
        insight = rts.create_topic_insight(
            topic_id=topic["topic_id"],
            kind="caveat",
            text="Author overlap alone is weak evidence.",
            source_refs=[{"source": "citation_trace", "id": "trace-1"}],
        )
        confirmed = rts.confirm_topic_insight(insight["insight_id"])

        self.assertEqual(insight["status"], "draft")
        self.assertEqual(confirmed["status"], "confirmed")


class ResearchTopicsDurableStoreTest(unittest.TestCase):
    def test_schema_sql_contains_research_topic_tables(self) -> None:
        sql = rts.research_topics_schema_sql()

        self.assertIn("CREATE TABLE IF NOT EXISTS research_topics", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS paper_reading_threads", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS paper_reading_thread_events", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS citation_trace_actions", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS topic_insights", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS assistant_suggestions", sql)
        self.assertIn("UNIQUE (topic_id, paper_key)", sql)

    def test_service_can_force_memory_store_for_tests_and_degraded_mode(self) -> None:
        rts._MEMORY_STORE.reset()
        original = rts.USE_MEMORY_STORE
        try:
            rts.USE_MEMORY_STORE = True
            topic = rts.create_topic(title="Fallback Topic", description="", keywords=[])
            self.assertEqual(topic["title"], "Fallback Topic")
            self.assertEqual(rts.list_topics()[0]["topic_id"], topic["topic_id"])
        finally:
            rts.USE_MEMORY_STORE = original

    def test_db_failure_switches_to_memory_mode_for_consistent_degraded_session(self) -> None:
        rts._MEMORY_STORE.reset()
        original = rts.USE_MEMORY_STORE
        try:
            rts.USE_MEMORY_STORE = False
            with patch(
                "backend.research_topics_service._db_create_topic",
                side_effect=psycopg2.OperationalError("db down"),
            ):
                topic = rts.create_topic(title="Degraded Topic", description="", keywords=[])

            self.assertTrue(rts.USE_MEMORY_STORE)
            self.assertEqual(rts.get_topic(topic["topic_id"])["title"], "Degraded Topic")
        finally:
            rts.USE_MEMORY_STORE = original
            rts._MEMORY_STORE.reset()

    def test_runtime_error_does_not_trigger_degraded_memory_mode(self) -> None:
        original = rts.USE_MEMORY_STORE
        try:
            rts.USE_MEMORY_STORE = False
            with patch(
                "backend.research_topics_service._db_create_topic",
                side_effect=RuntimeError("programmer error"),
            ):
                with self.assertRaises(RuntimeError):
                    rts.create_topic(title="Should Not Fallback", description="", keywords=[])

            self.assertFalse(rts.USE_MEMORY_STORE)
        finally:
            rts.USE_MEMORY_STORE = original
            rts._MEMORY_STORE.reset()

    def test_db_row_mappers_decode_json_strings_to_public_shapes(self) -> None:
        topic = rts._topic_from_row(
            {
                "topic_id": "topic_1",
                "title": "Mapper Topic",
                "description": "",
                "keywords": json.dumps(["rag", "memory"]),
                "status": "active",
                "created_from": "manual",
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
        )
        thread = rts._thread_from_row(
            {
                "thread_id": "thread_1",
                "topic_id": "topic_1",
                "paper_key": "arxiv:1706.03762",
                "paper_title": "Attention Is All You Need",
                "paper_metadata": json.dumps({"title": "Attention Is All You Need", "source": "arxiv"}),
                "last_page": 3,
                "progress": 0.5,
                "status": "reading",
                "last_reader_session_id": "reader-1",
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
        )
        event = rts._thread_event_from_row(
            {
                "event_id": "event_1",
                "thread_id": "thread_1",
                "topic_id": "topic_1",
                "event_type": "paper_reader.question",
                "source": "user",
                "payload": json.dumps({"question": "What changed?"}),
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        )
        action = rts._trace_action_from_row(
            {
                "action_id": "trace_action_1",
                "thread_id": "thread_1",
                "topic_id": "topic_1",
                "citation_trace_session_id": "trace-1",
                "target_paper": json.dumps({"title": "Target Paper"}),
                "final_top5": json.dumps([{"title": "Related Paper"}]),
                "warnings": json.dumps(["weak evidence"]),
                "assistant_explanation": "Treat this as a caveat.",
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        )
        insight = rts._insight_from_row(
            {
                "insight_id": "insight_1",
                "topic_id": "topic_1",
                "kind": "caveat",
                "text": "Author overlap alone is weak evidence.",
                "source_refs": json.dumps([{"source": "citation_trace", "id": "trace-1"}]),
                "status": "draft",
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
        )

        self.assertEqual(topic["keywords"], ["rag", "memory"])
        self.assertIn("paper_title", thread)
        self.assertEqual(thread["paper_metadata"]["source"], "arxiv")
        self.assertEqual(thread["last_page"], 3)
        self.assertEqual(thread["progress"], 0.5)
        self.assertEqual(event["payload"]["question"], "What changed?")
        self.assertIn("action_id", action)
        self.assertEqual(action["final_top5"][0]["title"], "Related Paper")
        self.assertEqual(action["warnings"], ["weak evidence"])
        self.assertIn("source_refs", insight)
        self.assertEqual(insight["source_refs"][0]["id"], "trace-1")

    def test_db_create_topic_inserts_and_maps_returned_row(self) -> None:
        cursor = FakeCursor(
            [
                {
                    "topic_id": "topic_db",
                    "title": "DB Topic",
                    "description": "Durable",
                    "keywords": ["rag"],
                    "status": "active",
                    "created_from": "manual",
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "updated_at": "2026-01-01T00:00:00+00:00",
                }
            ]
        )

        with patch("backend.research_topics_service.ensure_research_topics_schema"), patch(
            "backend.research_topics_service._connect",
            return_value=FakeConnection(cursor),
        ), patch("backend.research_topics_service._new_id", return_value="topic_db"):
            topic = rts._db_create_topic(
                title=" DB Topic ",
                description="Durable",
                keywords=["rag"],
            )

        insert_sql, insert_params = cursor.executions[0]
        self.assertIn("INSERT INTO research_topics", insert_sql)
        self.assertEqual(insert_params[0], "topic_db")
        self.assertEqual(insert_params[1], "DB Topic")
        self.assertEqual(json.loads(insert_params[3]), ["rag"])
        self.assertEqual(topic["topic_id"], "topic_db")
        self.assertEqual(topic["keywords"], ["rag"])

    def test_db_create_or_resume_thread_uses_topic_paper_upsert_and_maps_thread(self) -> None:
        cursor = FakeCursor(
            [
                {
                    "topic_id": "topic_db",
                    "title": "DB Topic",
                    "description": "",
                    "keywords": [],
                    "status": "active",
                    "created_from": "manual",
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "updated_at": "2026-01-01T00:00:00+00:00",
                },
                {
                    "thread_id": "thread_db",
                    "topic_id": "topic_db",
                    "paper_key": "arxiv:1706.03762",
                    "paper_title": "Attention Is All You Need",
                    "paper_metadata": {"arxiv_id": "1706.03762", "title": "Attention Is All You Need"},
                    "last_page": 0,
                    "progress": 0.0,
                    "status": "reading",
                    "last_reader_session_id": "reader-1",
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "updated_at": "2026-01-01T00:00:00+00:00",
                },
            ]
        )

        with patch("backend.research_topics_service.ensure_research_topics_schema"), patch(
            "backend.research_topics_service._connect",
            return_value=FakeConnection(cursor),
        ), patch("backend.research_topics_service._new_id", return_value="thread_db"):
            thread = rts._db_create_or_resume_thread(
                topic_id="topic_db",
                paper={"arxiv_id": "1706.03762", "title": "Attention Is All You Need"},
                reader_session_id="reader-1",
            )

        upsert_sql, upsert_params = cursor.executions[1]
        self.assertIn("INSERT INTO paper_reading_threads", upsert_sql)
        self.assertIn("ON CONFLICT (topic_id, paper_key)", upsert_sql)
        self.assertEqual(upsert_params[0], "thread_db")
        self.assertEqual(upsert_params[1], "topic_db")
        self.assertEqual(upsert_params[2], "arxiv:1706.03762")
        self.assertEqual(json.loads(upsert_params[4])["title"], "Attention Is All You Need")
        self.assertEqual(thread["thread_id"], "thread_db")
        self.assertEqual(thread["paper_title"], "Attention Is All You Need")
        self.assertEqual(thread["progress"], 0.0)

    def test_db_record_citation_trace_action_inserts_action_and_completed_event(self) -> None:
        cursor = FakeCursor(
            [
                {
                    "thread_id": "thread_db",
                    "topic_id": "topic_db",
                    "paper_key": "source:paper-1",
                    "paper_title": "Thread Paper",
                    "paper_metadata": {},
                    "last_page": 0,
                    "progress": 0.0,
                    "status": "reading",
                    "last_reader_session_id": "reader-1",
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "updated_at": "2026-01-01T00:00:00+00:00",
                },
                {
                    "action_id": "trace_action_db",
                    "thread_id": "thread_db",
                    "topic_id": "topic_db",
                    "citation_trace_session_id": "trace-1",
                    "target_paper": {"title": "Target Paper"},
                    "final_top5": [{"title": "Related Paper"}],
                    "warnings": ["weak evidence"],
                    "assistant_explanation": "Treat this as a caveat.",
                    "created_at": "2026-01-01T00:00:00+00:00",
                },
                {
                    "event_id": "event_db",
                    "thread_id": "thread_db",
                    "topic_id": "topic_db",
                    "event_type": "citation_trace.completed",
                    "source": "citation_trace",
                    "payload": {
                        "citation_trace_session_id": "trace-1",
                        "action_id": "trace_action_db",
                    },
                    "created_at": "2026-01-01T00:00:00+00:00",
                },
            ]
        )

        with patch("backend.research_topics_service.ensure_research_topics_schema"), patch(
            "backend.research_topics_service._connect",
            return_value=FakeConnection(cursor),
        ), patch("backend.research_topics_service._new_id", side_effect=["trace_action_db", "event_db"]):
            action = rts._db_record_citation_trace_action(
                thread_id="thread_db",
                citation_trace_session_id="trace-1",
                target_paper={"title": "Target Paper"},
                final_top5=[{"title": "Related Paper"}],
                warnings=["weak evidence"],
                assistant_explanation="Treat this as a caveat.",
            )

        action_sql, action_params = cursor.executions[1]
        event_sql, event_params = cursor.executions[2]
        self.assertIn("INSERT INTO citation_trace_actions", action_sql)
        self.assertEqual(action_params[0], "trace_action_db")
        self.assertEqual(json.loads(action_params[4])["title"], "Target Paper")
        self.assertIn("INSERT INTO paper_reading_thread_events", event_sql)
        self.assertEqual(event_params[3], "citation_trace.completed")
        self.assertEqual(json.loads(event_params[5])["action_id"], "trace_action_db")
        self.assertEqual(action["action_id"], "trace_action_db")
        self.assertEqual(action["final_top5"][0]["title"], "Related Paper")


class ResearchTopicSuggestionTest(unittest.TestCase):
    def setUp(self) -> None:
        self._original_use_memory_store = rts.USE_MEMORY_STORE
        rts.USE_MEMORY_STORE = True
        rts._MEMORY_STORE.reset()

    def tearDown(self) -> None:
        rts.USE_MEMORY_STORE = self._original_use_memory_store
        rts._MEMORY_STORE.reset()

    def test_search_suggestion_is_recommendation_only(self) -> None:
        topic = rts.create_topic(title="Graph RAG", description="", keywords=["graph rag"])
        suggestion = rts.create_search_recommendation(
            query="graph rag memory",
            paper={"title": "Graph RAG Memory", "arxiv_id": "2401.00001"},
            topic_candidates=[topic],
        )

        self.assertEqual(suggestion["source_workflow"], "search")
        self.assertEqual(suggestion["recommended_action"], "open_in_topic")
        self.assertEqual(suggestion["status"], "pending")
        self.assertEqual(rts.list_topic_threads(topic["topic_id"]), [])

    def test_accept_search_suggestion_does_not_write_topic_records(self) -> None:
        topic = rts.create_topic(title="Graph RAG", description="", keywords=["graph rag"])
        suggestion = rts.create_search_recommendation(
            query="graph rag memory",
            paper={"title": "Graph RAG Memory", "arxiv_id": "2401.00001"},
            topic_candidates=[topic],
        )
        accepted = rts.accept_suggestion(suggestion["suggestion_id"])

        self.assertEqual(accepted["status"], "accepted")
        self.assertEqual(rts.list_topic_threads(topic["topic_id"]), [])

    def test_paper_reader_suggestion_can_save_open_question_after_thread_exists(self) -> None:
        topic = rts.create_topic(title="Graph RAG", description="", keywords=[])
        thread = rts.create_or_resume_thread(
            topic_id=topic["topic_id"],
            paper={"title": "Graph RAG Memory", "arxiv_id": "2401.00001"},
            reader_session_id="reader-1",
        )
        suggestion = rts.create_thread_open_question_suggestion(
            thread_id=thread["thread_id"],
            question="Does graph structure reduce retrieval drift?",
        )
        accepted = rts.accept_suggestion(suggestion["suggestion_id"])

        self.assertEqual(accepted["status"], "accepted")
        detail = rts.get_thread(thread["thread_id"])
        self.assertEqual(detail["events"][-1]["event_type"], "paper_reader.open_question")
        self.assertEqual(detail["events"][-1]["payload"]["question"], "Does graph structure reduce retrieval drift?")


if __name__ == "__main__":
    unittest.main()
