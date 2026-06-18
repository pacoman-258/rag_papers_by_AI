import json
import unittest
from pathlib import Path

from backend import paper_reader_service as prs


def _chunk(
    chunk_id: str,
    text: str,
    section_title: str = "Introduction",
    focus_key: str = "core_question",
    focus_title: str = "Core question",
) -> prs.PaperReaderChunk:
    return prs.PaperReaderChunk(
        chunk_id=chunk_id,
        text=text,
        section_title=section_title,
        subsection_title=None,
        reading_focus_key=focus_key,
        reading_focus_title=focus_title,
        page_start=1,
        page_end=1,
        token_estimate=20,
    )


def _plan(focus_key: str = "proof_strategy", focus_title: str = "Proof strategy") -> prs.PaperReaderPagePlan:
    return prs.PaperReaderPagePlan(
        page_index=0,
        title=focus_title,
        focus_key=focus_key,
        focus_title=focus_title,
        section_title=focus_title,
        subsection_title=None,
        source_section_titles=["Proof"],
        chunk_ids=["c-proof"],
        page_start=1,
        page_end=1,
        estimated_tokens=20,
    )


def _session(discipline: str = "mathematics") -> prs.PaperReaderSession:
    return prs.PaperReaderSession(
        session_id="session-1",
        source_type="file",
        source_url=None,
        source_id="paper.pdf",
        paper_title="A proof of a useful theorem",
        authors=[],
        published_date=None,
        answer_language="zh",
        reader_mode="guided",
        discipline=discipline,
        discipline_source="manual",
        pdf_path=Path("/tmp/paper.pdf"),
        max_context_tokens=8192,
        reserved_output_tokens=1024,
        reserved_scaffold_tokens=1200,
        page_input_budget=5968,
        settings=None,
        chunks=[_chunk("c-proof", "We prove Theorem 1 by induction after defining a compactness invariant.", "Proof")],
        pages=[_plan()],
        page_statuses={0: "queued"},
    )


class PaperReaderDisciplineTest(unittest.TestCase):
    def test_manual_discipline_overrides_category(self):
        discipline, source = prs._resolve_discipline(
            requested="mathematics",
            primary_category="cs.CL",
            title="A neural retrieval system",
            abstract="We evaluate an engineering method.",
            chunks=[],
        )

        self.assertEqual(discipline, "mathematics")
        self.assertEqual(source, "manual")

    def test_arxiv_math_category_resolves_to_mathematics(self):
        discipline, source = prs._resolve_discipline(
            requested="auto",
            primary_category="math.NT",
            title="On prime gaps",
            abstract="We prove a theorem about primes.",
            chunks=[],
        )

        self.assertEqual(discipline, "mathematics")
        self.assertEqual(source, "auto")

    def test_keyword_detection_handles_non_arxiv_disciplines(self):
        cases = [
            (
                "medicine_biology",
                "A randomized clinical trial of a biomarker intervention in patients",
                "The study measures survival, safety, gene expression, and treatment response.",
            ),
            (
                "economics_social_science",
                "An instrumental variables estimate of policy effects",
                "We use panel data, identification, robustness checks, and causal inference.",
            ),
            (
                "policy_law",
                "A statutory framework for platform regulation",
                "The article analyzes courts, compliance, enforcement, rights, and legal rules.",
            ),
        ]

        for expected, title, abstract in cases:
            with self.subTest(expected=expected):
                discipline, source = prs._resolve_discipline(
                    requested="auto",
                    primary_category=None,
                    title=title,
                    abstract=abstract,
                    chunks=[],
                )
                self.assertEqual(discipline, expected)
                self.assertEqual(source, "auto")

    def test_unknown_discipline_falls_back_to_general(self):
        discipline, source = prs._resolve_discipline(
            requested="auto",
            primary_category=None,
            title="Notes on a small topic",
            abstract="This paper discusses several observations.",
            chunks=[],
        )

        self.assertEqual(discipline, "general")
        self.assertEqual(source, "auto")

    def test_mathematics_route_avoids_engineering_experiment_focus(self):
        route = prs._reading_focus_order_for_discipline("mathematics")
        titles = [title for _key, title in route]

        self.assertIn("Proof strategy", titles)
        self.assertNotIn("Evidence or experiments", titles)

    def test_page_prompt_requests_discipline_guide_instead_of_blackboard_notes(self):
        session = _session("mathematics")
        prompt = prs._build_page_messages(session, session.pages[0])[0]["content"]

        self.assertIn("discipline_guide", prompt)
        self.assertIn("mathematics", prompt)
        self.assertIn("Proof strategy", prompt)
        self.assertNotIn("blackboard_notes", prompt)
        self.assertNotIn("core_concepts", prompt)
        self.assertNotIn("method_steps", prompt)
        self.assertNotIn("experiment_takeaways", prompt)

    def test_page_output_parses_discipline_guide_panels(self):
        session = _session("mathematics")
        raw = {
            "page_title": "Proof strategy",
            "coverage": "Proof",
            "page_overview": {
                "original_en": "We prove Theorem 1 by induction.",
                "explanation": "这一页说明证明主线。",
            },
            "insights": [
                {
                    "title": "Induction skeleton",
                    "kind": "proof",
                    "summary": {
                        "original_en": "The proof proceeds by induction.",
                        "explanation": "作者先建立归纳框架。",
                    },
                    "evidence": [],
                    "source_chunk_ids": ["c-proof"],
                }
            ],
            "citations": [
                {
                    "chunk_id": "c-proof",
                    "section_title": "Proof",
                    "subsection_title": None,
                    "page_start": 1,
                    "page_end": 1,
                    "excerpt": "The proof proceeds by induction.",
                }
            ],
            "discipline_guide": {
                "discipline": "mathematics",
                "title": "数学证明讲解",
                "panels": [
                    {
                        "key": "statement",
                        "title": "目标命题",
                        "items": ["Theorem 1"],
                        "takeaway": "先确认要证明什么。",
                    }
                ],
            },
        }

        content = prs._page_content_from_output(session, session.pages[0], json.dumps(raw))

        self.assertEqual(content.discipline_guide.discipline, "mathematics")
        self.assertEqual(content.discipline_guide.panels[0].title, "目标命题")
        self.assertEqual(content.discipline_guide.panels[0].items, ["Theorem 1"])

    def test_page_output_synthesizes_missing_discipline_guide(self):
        session = _session("mathematics")
        raw = {
            "page_title": "Proof strategy",
            "coverage": "Proof",
            "page_overview": {
                "original_en": "We prove Theorem 1 by induction.",
                "explanation": "这一页说明证明主线。",
            },
            "insights": [
                {
                    "title": "Induction skeleton",
                    "kind": "proof",
                    "summary": {
                        "original_en": "The proof proceeds by induction.",
                        "explanation": "作者先建立归纳框架。",
                    },
                    "evidence": [],
                    "source_chunk_ids": ["c-proof"],
                }
            ],
            "citations": [],
        }

        content = prs._page_content_from_output(session, session.pages[0], json.dumps(raw))

        self.assertEqual(content.discipline_guide.discipline, "mathematics")
        self.assertTrue(content.discipline_guide.panels)
        self.assertTrue(content.discipline_guide.panels[0].items)


if __name__ == "__main__":
    unittest.main()
