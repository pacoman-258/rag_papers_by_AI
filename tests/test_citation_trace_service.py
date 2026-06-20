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


if __name__ == "__main__":
    unittest.main()
