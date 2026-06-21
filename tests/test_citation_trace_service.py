import unittest

from backend import citation_trace_service as cts


def _top_paper(
    rank,
    paper_id,
    *,
    evidence_level="strong",
    is_exploratory=False,
    is_explicitly_cited=True,
):
    return cts.CitationTraceTopPaper(
        rank=rank,
        paper_id=paper_id,
        title=paper_id.upper(),
        influence_area="method",
        reason=f"{paper_id} reason",
        evidence_level=evidence_level,
        is_explicitly_cited=is_explicitly_cited,
        is_exploratory=is_exploratory,
        why_worth_reading=f"{paper_id} reading",
        uncertainty="weak evidence" if evidence_level == "weak" else "",
        supporting_edge_ids=[],
    )


class CitationTraceServiceTest(unittest.TestCase):
    def tearDown(self):
        cts._SESSION_CACHE.clear()

    def test_extract_reference_entries_from_references_section(self):
        text = """
        Abstract
        We study useful things.

        References
        [1] Ashish Vaswani, Noam Shazeer. Attention Is All You Need. arXiv:1706.03762, 2017.
        [2] D. Bahdanau, K. Cho, Y. Bengio. Neural Machine Translation by Jointly Learning to Align and Translate. 2015.
        [3] J. Doe. An Unresolved Report. Technical memo.
        Appendix
        Extra material.
        """

        entries = cts.extract_reference_entries(text)

        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0].raw_label, "[1]")
        self.assertIn("Attention Is All You Need", entries[0].raw_text)
        self.assertEqual(entries[0].arxiv_id, "1706.03762")
        self.assertIn("Bahdanau", entries[1].raw_text)
        self.assertIn("Neural Machine Translation", entries[1].title_hint)
        self.assertIsNone(entries[2].arxiv_id)

    def test_extract_reference_entries_stops_at_numbered_or_plural_next_sections(self):
        for heading, trailing_text in (
            ("6 Acknowledgements", "We thank careful reviewers."),
            ("Supplementary Materials", "Extra experiment tables."),
        ):
            with self.subTest(heading=heading):
                text = f"""
                Abstract
                We study useful things.

                References
                [1] A. Example. First Useful Paper. 2020.
                [2] B. Example. Last Useful Paper. 2021.
                {heading}
                {trailing_text}
                """

                entries = cts.extract_reference_entries(text)

                self.assertEqual(len(entries), 2)
                self.assertEqual(entries[-1].raw_label, "[2]")
                self.assertIn("Last Useful Paper", entries[-1].raw_text)
                self.assertNotIn(trailing_text, entries[-1].raw_text)

    def test_extract_reference_entries_keeps_year_continuation_lines(self):
        text = """
        Abstract
        We study useful things.

        References
        [1] First Paper. Important Work.
        2017. pages 1-2.
        [2] Second Paper. Another Work.
        """

        entries = cts.extract_reference_entries(text)

        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].raw_label, "[1]")
        self.assertIn("2017. pages 1-2.", entries[0].raw_text)
        self.assertEqual(entries[1].raw_label, "[2]")

    def test_create_session_from_arxiv_uses_resolved_metadata(self):
        class Record:
            arxiv_id = "1706.03762"
            source = "arxiv"
            source_id = "1706.03762"
            title = "Attention Is All You Need"
            summary = "Transformer architecture."
            authors = ["Ashish Vaswani"]
            published_date = "2017-06-12"
            primary_category = "cs.CL"
            external_url = "https://arxiv.org/abs/1706.03762"
            doi = None

        original_fetch = cts.fetch_arxiv_record
        original_download = cts.download_arxiv_pdf_text
        try:
            cts.fetch_arxiv_record = lambda arxiv_id: Record()
            cts.download_arxiv_pdf_text = (
                lambda arxiv_id, settings: "References\n[1] Prior Work. arXiv:1601.00001"
            )
            session = cts.create_session_from_arxiv(
                "https://arxiv.org/pdf/1706.03762v7.pdf",
                settings=None,
                answer_language="en",
            )
        finally:
            cts.fetch_arxiv_record = original_fetch
            cts.download_arxiv_pdf_text = original_download

        self.assertEqual(session.target_paper.title, "Attention Is All You Need")
        self.assertEqual(session.target_paper.abstract, "Transformer architecture.")
        self.assertEqual(session.target_paper.source_id, "1706.03762")
        self.assertEqual(session.target_paper.canonical_id, "arxiv:1706.03762")
        self.assertEqual(session.pdf_text, "References\n[1] Prior Work. arXiv:1601.00001")
        self.assertEqual(len(session.reference_entries), 1)
        self.assertEqual(session.reference_entries[0].arxiv_id, "1601.00001")
        self.assertEqual(session.final_top5, [])
        self.assertIs(cts.get_session(session.session_id), session)

    def test_unresolved_reference_stays_visible_as_node_and_ledger_entry(self):
        reference = cts.ReferenceEntry(
            reference_id="ref-1",
            raw_text="J. Doe. An Unresolved Report. Technical memo.",
            raw_label=None,
            arxiv_id=None,
            doi=None,
            year=None,
            title_hint="An Unresolved Report",
        )

        node, entry = cts.build_unresolved_reference_record(reference, seed_paper_id="target")

        self.assertEqual(node.source, "unresolved")
        self.assertEqual(node.title, "An Unresolved Report")
        self.assertEqual(entry.relation_type, "explicit_reference")
        self.assertEqual(entry.evidence_level, "weak")
        self.assertIn("Unresolved reference", entry.warnings)

    def test_final_top5_limits_low_evidence_exploratory_entries_to_two(self):
        items = [
            _top_paper(7, "p7"),
            _top_paper(4, "p4", evidence_level="weak", is_exploratory=True, is_explicitly_cited=False),
            _top_paper(2, "p2", evidence_level="weak", is_exploratory=True, is_explicitly_cited=False),
            _top_paper(1, "p1"),
            _top_paper(6, "p6"),
            _top_paper(3, "p3", evidence_level="weak", is_exploratory=True, is_explicitly_cited=False),
            _top_paper(5, "p5"),
        ]

        trimmed = cts.enforce_final_top5_policy(items)

        self.assertEqual([item.paper_id for item in trimmed], ["p1", "p2", "p3", "p5", "p6"])
        self.assertEqual([item.rank for item in trimmed], [1, 2, 3, 4, 5])
        self.assertEqual(len(trimmed), 5)
        self.assertLessEqual(sum(1 for item in trimmed if item.is_exploratory and item.evidence_level == "weak"), 2)

    def test_score_candidate_marks_explicit_reference_as_strong_when_metadata_matches(self):
        seed = cts.CitationTracePaperNode(
            paper_id="target",
            source="target",
            source_id="target",
            canonical_id="target",
            title="Transformer Translation",
            abstract="Attention models improve neural machine translation.",
            authors=["Ashish Vaswani", "Noam Shazeer"],
            published_date="2017-06-01",
            keywords=["attention", "translation"],
        )
        candidate = cts.CitationTracePaperNode(
            paper_id="paper-1",
            source="arxiv",
            source_id="1706.03762",
            canonical_id="arxiv:1706.03762",
            title="Attention Is All You Need",
            abstract="The Transformer relies entirely on attention mechanisms for translation.",
            authors=["Ashish Vaswani", "Noam Shazeer"],
            published_date="2017-05-01",
            keywords=["attention", "translation"],
            arxiv_id="1706.03762",
        )

        entry = cts.score_candidate_relationship(
            seed,
            candidate,
            round_number=1,
            relation_type="explicit_reference",
            reference_text="Attention Is All You Need. arXiv:1706.03762",
        )

        self.assertEqual(entry.evidence_level, "strong")
        self.assertGreater(entry.score_total, 0.7)
        self.assertEqual(entry.score_breakdown.reference_match, 1.0)

    def test_score_candidate_promotes_sparse_exact_arxiv_reference_match(self):
        seed = cts.CitationTracePaperNode("target", "target", "target", "target", "Target")
        candidate = cts.CitationTracePaperNode(
            paper_id="paper-1",
            source="arxiv",
            source_id="1706.03762",
            canonical_id="arxiv:1706.03762",
            title="",
            arxiv_id="1706.03762",
        )

        entry = cts.score_candidate_relationship(
            seed,
            candidate,
            round_number=1,
            relation_type="explicit_reference",
            reference_text="Unknown Authors. Sparse Reference. arXiv:1706.03762.",
        )

        self.assertEqual(entry.evidence_level, "strong")
        self.assertGreater(entry.score_total, 0.7)
        self.assertEqual(entry.score_breakdown.reference_match, 1.0)

    def test_score_candidate_does_not_mark_unmatched_explicit_reference_as_metadata_match(self):
        seed = cts.CitationTracePaperNode("target", "target", "target", "target", "Target")
        candidate = cts.CitationTracePaperNode(
            paper_id="paper-1",
            source="arxiv",
            source_id="1706.03762",
            canonical_id="arxiv:1706.03762",
            title="",
            arxiv_id="1706.03762",
        )

        entry = cts.score_candidate_relationship(
            seed,
            candidate,
            round_number=1,
            relation_type="explicit_reference",
            reference_text="Unknown Authors. Different Sparse Reference. arXiv:1901.00001.",
        )

        self.assertEqual(entry.score_breakdown.reference_match, 0.0)
        self.assertNotEqual(entry.evidence_level, "strong")

    def test_select_round_candidates_uses_all_when_fewer_than_limit(self):
        seed = cts.CitationTracePaperNode("target", "target", "target", "target", "Target")
        candidates = [
            cts.CitationTracePaperNode("p1", "arxiv", "p1", "p1", "First", abstract="alpha"),
            cts.CitationTracePaperNode("p2", "arxiv", "p2", "p2", "Second", abstract="beta"),
        ]

        selected = cts.select_round_candidates(seed, candidates, round_number=1, limit=10)

        self.assertEqual([entry.candidate_paper.paper_id for entry in selected], ["p1", "p2"])

    def test_select_round_candidates_caps_round_two_at_three_per_seed(self):
        seed = cts.CitationTracePaperNode("seed", "arxiv", "seed", "seed", "Seed")
        candidates = [
            cts.CitationTracePaperNode(
                f"p{index}",
                "arxiv",
                f"p{index}",
                f"p{index}",
                f"Paper {index}",
                abstract="shared method",
            )
            for index in range(5)
        ]

        selected = cts.select_round_candidates(seed, candidates, round_number=2, limit=3)

        self.assertEqual(len(selected), 3)
        self.assertTrue(all(entry.round == 2 for entry in selected))

    def test_select_round_candidates_uses_deterministic_tie_break_before_limit(self):
        seed = cts.CitationTracePaperNode("seed", "arxiv", "seed", "seed", "Seed")
        candidates = [
            cts.CitationTracePaperNode("p3", "arxiv", "p3", "p3", "Paper", abstract="shared method"),
            cts.CitationTracePaperNode("p1", "arxiv", "p1", "p1", "Paper", abstract="shared method"),
            cts.CitationTracePaperNode("p2", "arxiv", "p2", "p2", "Paper", abstract="shared method"),
        ]

        selected = cts.select_round_candidates(seed, candidates, round_number=2, limit=2)

        self.assertEqual([entry.candidate_paper.paper_id for entry in selected], ["p1", "p2"])


if __name__ == "__main__":
    unittest.main()
