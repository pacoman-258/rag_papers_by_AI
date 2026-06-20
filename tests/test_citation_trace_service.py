import unittest

from backend import citation_trace_service as cts


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
        self.assertIsNone(entries[2].arxiv_id)

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
            cts.CitationTraceTopPaper(rank=1, paper_id="p1", title="P1", influence_area="method", reason="strong", evidence_level="strong", is_explicitly_cited=True, is_exploratory=False, why_worth_reading="core", uncertainty="", supporting_edge_ids=[]),
            cts.CitationTraceTopPaper(rank=2, paper_id="p2", title="P2", influence_area="theory", reason="weak one", evidence_level="weak", is_explicitly_cited=False, is_exploratory=True, why_worth_reading="explore", uncertainty="weak evidence", supporting_edge_ids=[]),
            cts.CitationTraceTopPaper(rank=3, paper_id="p3", title="P3", influence_area="problem", reason="weak two", evidence_level="weak", is_explicitly_cited=False, is_exploratory=True, why_worth_reading="explore", uncertainty="weak evidence", supporting_edge_ids=[]),
            cts.CitationTraceTopPaper(rank=4, paper_id="p4", title="P4", influence_area="dataset", reason="weak three", evidence_level="weak", is_explicitly_cited=False, is_exploratory=True, why_worth_reading="explore", uncertainty="weak evidence", supporting_edge_ids=[]),
        ]

        trimmed = cts.enforce_final_top5_policy(items)

        self.assertEqual([item.paper_id for item in trimmed], ["p1", "p2", "p3"])
        self.assertLessEqual(sum(1 for item in trimmed if item.is_exploratory and item.evidence_level == "weak"), 2)


if __name__ == "__main__":
    unittest.main()
