import unittest

from backend import main as backend_main
from backend.schemas import QueryPlanModel, RetrievalConstraintsModel
from local_paper_db.app import external_sources
from local_paper_db.app import search_service as ss


class FuzzyArxivSearchTest(unittest.TestCase):
    def paper(self, paper_id: str, title: str, score: float) -> ss.RetrievedPaper:
        return ss.RetrievedPaper(
            id=paper_id,
            source="arxiv",
            source_id=paper_id,
            canonical_id=paper_id,
            title=title,
            text=title,
            method="Not provided.",
            initial_score=score,
            authors=[],
            published_date="2024-01-01",
            primary_category="cs.LG",
            external_url=f"https://arxiv.org/abs/{paper_id}",
            arxiv_id=paper_id,
            matched_sources=["arxiv"],
        )

    def test_coerce_query_plan_detects_beginner_intent_when_model_omits_it(self):
        plan = ss.coerce_query_plan(
            {
                "answer_language": "zh",
                "intent_summary": "Find beginner deep learning papers",
                "retrieval_query_en": "beginner deep learning papers",
                "keywords_en": ["deep learning"],
            },
            "帮我找到关于深度学习的一些入门论文",
            "2026-06-26",
        )

        self.assertEqual(plan.search_intent, "beginner")

    def test_coerce_query_plan_keeps_explicit_latest_intent(self):
        plan = ss.coerce_query_plan(
            {
                "answer_language": "zh",
                "intent_summary": "Find recent graph retrieval papers",
                "retrieval_query_en": "recent graph retrieval papers",
                "keywords_en": ["graph retrieval"],
                "search_intent": "latest",
                "constraints": {"sort_hint": "latest", "is_implicit_latest": True},
            },
            "最近一年 graph retrieval 有哪些论文",
            "2026-06-26",
        )

        self.assertEqual(plan.search_intent, "latest")
        self.assertEqual(plan.constraints.sort_hint, "latest")

    def test_coerce_query_plan_accepts_nested_search_intent_for_compatibility(self):
        plan = ss.coerce_query_plan(
            {
                "answer_language": "zh",
                "intent_summary": "Find papers",
                "retrieval_query_en": "large language model papers",
                "keywords_en": ["large language models"],
                "constraints": {"search_intent": "canonical"},
            },
            "找一些大模型论文",
            "2026-06-26",
        )

        self.assertEqual(plan.search_intent, "canonical")
        self.assertEqual(plan.constraints.search_intent, "canonical")

    def test_query_plan_model_accepts_nested_search_intent_for_compatibility(self):
        model = QueryPlanModel(
            answer_language="zh",
            intent_summary="Find papers",
            retrieval_query_en="large language model papers",
            keywords_en=["large language models"],
            constraints=RetrievalConstraintsModel(search_intent="canonical"),
        )

        plan = backend_main.query_plan_model_to_dataclass(model)

        self.assertIsNotNone(plan)
        self.assertEqual(plan.search_intent, "canonical")
        self.assertEqual(plan.constraints.search_intent, "canonical")

    def test_beginner_arxiv_queries_add_survey_and_tutorial_tracks(self):
        constraints = ss.RetrievalConstraints(search_intent="beginner")

        queries = external_sources.build_arxiv_search_queries(
            "deep learning; keywords: deep learning",
            constraints,
        )

        self.assertGreaterEqual(len(queries), 2)
        self.assertTrue(any("survey" in query.lower() for query in queries))
        self.assertTrue(any("tutorial" in query.lower() or "overview" in query.lower() for query in queries))

    def test_canonical_arxiv_queries_add_foundational_tracks(self):
        constraints = ss.RetrievalConstraints(search_intent="canonical")

        queries = external_sources.build_arxiv_search_queries(
            "large language models; keywords: transformer, language model pretraining",
            constraints,
        )

        self.assertGreaterEqual(len(queries), 2)
        self.assertTrue(any("foundational" in query.lower() or "landmark" in query.lower() for query in queries))

    def test_normal_arxiv_query_stays_single_track(self):
        constraints = ss.RetrievalConstraints()

        queries = external_sources.build_arxiv_search_queries(
            "graph neural networks; keywords: graph neural networks",
            constraints,
        )

        self.assertEqual(len(queries), 1)

    def test_beginner_sort_prefers_survey_candidate_without_hiding_similarity(self):
        constraints = ss.RetrievalConstraints(search_intent="beginner")
        papers = [
            self.paper("specific", "A Niche Deep Learning Optimization Trick", 0.80),
            self.paper("survey", "A Survey of Deep Learning", 0.75),
        ]

        sorted_papers = ss.sort_retrieved_papers(papers, constraints)

        self.assertEqual(sorted_papers[0].id, "survey")
        self.assertEqual(sorted_papers[0].initial_score, 0.75)

    def test_normal_sort_remains_similarity_ordered(self):
        papers = [
            self.paper("lower", "A Survey of Deep Learning", 0.75),
            self.paper("higher", "A Niche Deep Learning Optimization Trick", 0.80),
        ]

        sorted_papers = ss.sort_retrieved_papers(papers, ss.RetrievalConstraints())

        self.assertEqual(sorted_papers[0].id, "higher")


if __name__ == "__main__":
    unittest.main()
