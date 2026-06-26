import json
import unittest

from local_paper_db.app import search_service as ss


def _settings() -> ss.RuntimeSettings:
    chat = ss.ChatConfig(provider="ollama", model="review-model", base_url="http://localhost:11434/api")
    return ss.RuntimeSettings(
        query_chat=chat,
        answer_chat=ss.ChatConfig(provider="ollama", model="answer-model", base_url="http://localhost:11434/api"),
        paper_reader_chat=ss.PaperReaderChatConfig(
            provider="ollama",
            model="reader-model",
            base_url="http://localhost:11434/api",
        ),
        paper_reader_translation=ss.ChatConfig(
            provider="ollama",
            model="translator-model",
            base_url="http://localhost:11434/api",
        ),
        citation_trace_main_chat=ss.ChatConfig(
            provider="ollama",
            model="trace-main",
            base_url="http://localhost:11434/api",
        ),
        citation_trace_worker_chat=ss.ChatConfig(
            provider="ollama",
            model="trace-worker",
            base_url="http://localhost:11434/api",
        ),
        embedding=ss.EmbeddingConfig(api_url="http://localhost:11434/api", model="embed-model"),
        retrieval=ss.RetrievalConfig(top_k=10, top_n=5, request_timeout=3, providers={"local": True}),
        rerank=ss.RerankConfig(base_url="https://rerank.example", model="rerank-model", api_key="key"),
    )


def _plan(query: str = "deep learning beginner papers") -> ss.QueryPlan:
    return ss.QueryPlan(
        answer_language="zh",
        intent_summary="Find beginner deep learning papers",
        retrieval_query_en=query,
        keywords_en=["deep learning"],
        search_intent="beginner",
        constraints=ss.RetrievalConstraints(search_intent="beginner"),
        corpus_latest_date="2026-06-26",
    )


def _paper(paper_id: str, title: str, summary: str) -> ss.RankedPaper:
    return ss.RankedPaper(
        id=paper_id,
        source="local",
        source_id=paper_id,
        canonical_id=paper_id,
        title=title,
        text=summary,
        method="Not provided.",
        initial_score=0.8,
        rerank_score=0.9,
        authors=[],
        published_date="2024-01-01",
        primary_category="cs.LG",
        matched_sources=["local"],
    )


def _execution(retrieval_text: str, papers: list[ss.RankedPaper], plan: ss.QueryPlan | None = None) -> ss.SearchExecution:
    resolved_plan = plan or _plan(retrieval_text)
    return ss.SearchExecution(
        original_query="帮我找深度学习入门论文",
        retrieval_text=retrieval_text,
        answer_language="zh",
        query_plan=resolved_plan,
        papers=papers,
        answer_prompt="answer prompt",
        warnings=[],
        applied_constraints=resolved_plan.constraints,
        corpus_latest_date="2026-06-26",
        retrieval_sources=["local"],
        source_freshness={"local": "2026-06-26"},
    )


class SearchRelevanceReviewTest(unittest.TestCase):
    def test_review_prompt_only_includes_top_three_ranked_paper_summaries(self):
        execution = _execution(
            "deep learning",
            [
                _paper("p1", "Paper One", "First summary"),
                _paper("p2", "Paper Two", "Second summary"),
                _paper("p3", "Paper Three", "Third summary"),
                _paper("p4", "Paper Four", "Fourth summary"),
            ],
        )

        messages = ss.build_search_review_messages(execution)
        joined = "\n".join(message["content"] for message in messages)

        self.assertIn("[Paper 1]", joined)
        self.assertIn("[Paper 3]", joined)
        self.assertIn("Third summary", joined)
        self.assertNotIn("[Paper 4]", joined)
        self.assertNotIn("Fourth summary", joined)

    def test_execute_search_with_review_rewrites_and_retries_when_top_results_mismatch(self):
        settings = _settings()
        calls: list[str] = []
        reviews = [
            {
                "needs_retry": True,
                "reason": "Top papers are about graph databases, not beginner deep learning.",
                "revised_query_plan": {
                    "answer_language": "zh",
                    "intent_summary": "Find beginner deep learning survey papers",
                    "retrieval_query_en": "beginner deep learning survey papers",
                    "keywords_en": ["deep learning", "survey"],
                    "search_intent": "beginner",
                    "constraints": {"primary_categories": ["cs.LG"], "sort_hint": "relevance"},
                },
            },
            {"needs_retry": False, "reason": "Top papers now match the beginner deep learning request."},
        ]

        def fake_execute_search(original_query, retrieval_text, query_plan, settings, db_config=None):
            calls.append(retrieval_text)
            if len(calls) == 1:
                return _execution(retrieval_text, [_paper("bad", "Graph Database Indexes", "Graph storage systems.")], query_plan)
            return _execution(retrieval_text, [_paper("good", "A Survey of Deep Learning", "Deep learning overview.")], query_plan)

        def fake_chat_completion(messages, config, timeout):
            return json.dumps(reviews.pop(0))

        original_execute = ss.execute_search
        original_chat = ss.chat_completion
        try:
            ss.execute_search = fake_execute_search
            ss.chat_completion = fake_chat_completion

            execution = ss.execute_search_with_review(
                "帮我找深度学习入门论文",
                "graph database papers",
                _plan("graph database papers"),
                settings,
            )
        finally:
            ss.execute_search = original_execute
            ss.chat_completion = original_chat

        self.assertEqual(calls, ["graph database papers", "beginner deep learning survey papers; keywords: deep learning, survey"])
        self.assertEqual(execution.papers[0].id, "good")
        self.assertTrue(any("Relevance review retry 1" in warning for warning in execution.warnings))

    def test_execute_search_with_review_accepts_matching_results_without_retry(self):
        settings = _settings()
        calls: list[str] = []

        def fake_execute_search(original_query, retrieval_text, query_plan, settings, db_config=None):
            calls.append(retrieval_text)
            return _execution(retrieval_text, [_paper("good", "A Survey of Deep Learning", "Deep learning overview.")], query_plan)

        def fake_chat_completion(messages, config, timeout):
            return json.dumps({"needs_retry": False, "reason": "The top papers match the request."})

        original_execute = ss.execute_search
        original_chat = ss.chat_completion
        try:
            ss.execute_search = fake_execute_search
            ss.chat_completion = fake_chat_completion

            execution = ss.execute_search_with_review("帮我找深度学习入门论文", "deep learning survey", _plan(), settings)
        finally:
            ss.execute_search = original_execute
            ss.chat_completion = original_chat

        self.assertEqual(calls, ["deep learning survey"])
        self.assertEqual(execution.papers[0].id, "good")
        self.assertFalse(any("Relevance review retry" in warning for warning in execution.warnings))

    def test_review_decision_treats_string_false_as_no_retry(self):
        execution = _execution(
            "deep learning survey",
            [_paper("good", "A Survey of Deep Learning", "Deep learning overview.")],
        )

        decision = ss.coerce_search_review_decision(
            {
                "needs_retry": "false",
                "reason": "Top papers match.",
                "revised_query_plan": {
                    "answer_language": "zh",
                    "intent_summary": "Should be ignored",
                    "retrieval_query_en": "unneeded retry",
                    "keywords_en": ["retry"],
                },
            },
            execution,
        )

        self.assertFalse(decision.needs_retry)
        self.assertIsNone(decision.revised_query_plan)

    def test_execute_search_with_review_caps_retries_at_three(self):
        settings = _settings()
        calls: list[str] = []

        def fake_execute_search(original_query, retrieval_text, query_plan, settings, db_config=None):
            calls.append(retrieval_text)
            return _execution(retrieval_text, [_paper(f"p{len(calls)}", "Wrong Topic", "Still off topic.")], query_plan)

        def fake_chat_completion(messages, config, timeout):
            attempt = len(calls)
            return json.dumps(
                {
                    "needs_retry": True,
                    "reason": "Still mismatched.",
                    "revised_query_plan": {
                        "answer_language": "zh",
                        "intent_summary": "Retry search",
                        "retrieval_query_en": f"retry query {attempt}",
                        "keywords_en": [f"retry {attempt}"],
                        "constraints": {"sort_hint": "relevance"},
                    },
                }
            )

        original_execute = ss.execute_search
        original_chat = ss.chat_completion
        try:
            ss.execute_search = fake_execute_search
            ss.chat_completion = fake_chat_completion

            execution = ss.execute_search_with_review("帮我找深度学习入门论文", "wrong query", _plan("wrong query"), settings)
        finally:
            ss.execute_search = original_execute
            ss.chat_completion = original_chat

        self.assertEqual(len(calls), 4)
        self.assertEqual(calls[0], "wrong query")
        self.assertTrue(any("Relevance review retry limit reached after 3 retries" in warning for warning in execution.warnings))


if __name__ == "__main__":
    unittest.main()
