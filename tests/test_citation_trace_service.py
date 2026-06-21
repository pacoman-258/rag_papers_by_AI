from io import BytesIO
from types import SimpleNamespace
import unittest

from pypdf import PdfWriter

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
        cts._SESSION_SETTINGS_CACHE.clear()

    def _blank_pdf_bytes(self):
        buffer = BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=72, height=72)
        writer.write(buffer)
        return buffer.getvalue()

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

    def test_create_session_from_arxiv_accepts_supported_url_with_trailing_slash(self):
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
            cts.download_arxiv_pdf_text = lambda arxiv_id, settings: "References\n[1] Prior Work."
            session = cts.create_session_from_arxiv(
                "https://arxiv.org/abs/1706.03762/",
                settings=None,
                answer_language="en",
            )
        finally:
            cts.fetch_arxiv_record = original_fetch
            cts.download_arxiv_pdf_text = original_download

        self.assertEqual(session.source_id, "1706.03762")
        self.assertEqual(session.target_paper.canonical_id, "arxiv:1706.03762")

    def test_create_session_from_arxiv_uses_unique_session_ids_for_same_paper(self):
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

        settings_one = object()
        settings_two = object()
        original_fetch = cts.fetch_arxiv_record
        original_download = cts.download_arxiv_pdf_text
        try:
            cts.fetch_arxiv_record = lambda arxiv_id: Record()
            cts.download_arxiv_pdf_text = lambda arxiv_id, settings: "References\n[1] Prior Work."
            first = cts.create_session_from_arxiv(
                "https://arxiv.org/abs/1706.03762",
                settings=settings_one,
                answer_language="en",
            )
            second = cts.create_session_from_arxiv(
                "https://arxiv.org/abs/1706.03762",
                settings=settings_two,
                answer_language="zh",
            )
        finally:
            cts.fetch_arxiv_record = original_fetch
            cts.download_arxiv_pdf_text = original_download

        self.assertNotEqual(first.session_id, second.session_id)
        self.assertIs(cts.get_session(first.session_id), first)
        self.assertIs(cts.get_session(second.session_id), second)
        self.assertIs(cts.get_cached_session_settings(first.session_id), settings_one)
        self.assertIs(cts.get_cached_session_settings(second.session_id), settings_two)

    def test_create_session_from_pdf_bytes_rejects_empty_invalid_and_textless_pdf(self):
        cases = (
            ("empty.pdf", b"", "empty"),
            ("fake.pdf", b"%PDF fake", "valid PDF"),
            ("blank.pdf", self._blank_pdf_bytes(), "extractable text"),
        )
        for filename, content, expected_message in cases:
            with self.subTest(filename=filename):
                with self.assertRaisesRegex(ValueError, expected_message):
                    cts.create_session_from_pdf_bytes(filename, content, settings=None, answer_language="en")
                self.assertEqual(cts._SESSION_CACHE, {})

    def test_create_session_from_pdf_bytes_uses_safe_basename_for_uploaded_filename(self):
        original = cts.pdf_bytes_to_text
        try:
            cts.pdf_bytes_to_text = lambda content: "Paper body with extractable text."
            for raw_filename, expected in (
                ("..\\secret.pdf", "secret.pdf"),
                ("C:\\tmp\\paper.pdf", "paper.pdf"),
                ("../nested/local.pdf", "local.pdf"),
            ):
                with self.subTest(raw_filename=raw_filename):
                    session = cts.create_session_from_pdf_bytes(
                        raw_filename,
                        b"ignored",
                        settings=None,
                        answer_language="en",
                    )
                    self.assertEqual(session.source_id, expected)
                    self.assertEqual(session.target_paper.title, expected)
                    self.assertEqual(session.target_paper.canonical_id, f"file:{expected}")
        finally:
            cts.pdf_bytes_to_text = original

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

    def test_expand_seed_candidates_uses_prior_work_search_results(self):
        seed = cts.CitationTracePaperNode(
            paper_id="seed",
            source="arxiv",
            source_id="1706.03762",
            canonical_id="arxiv:1706.03762",
            title="Attention Is All You Need",
            abstract="Transformer attention for translation.",
            authors=["Ashish Vaswani"],
            published_date="2017-06-12",
            keywords=["cs.CL"],
            arxiv_id="1706.03762",
            external_url="https://arxiv.org/abs/1706.03762",
        )
        settings = object()
        captured = {}
        original_get_embedding = cts.get_embedding
        original_collect = cts.collect_prior_work_candidates
        try:
            def get_embedding(text, runtime_settings):
                captured["embedding_text"] = text
                return [0.1, 0.2]

            cts.get_embedding = get_embedding

            def collect(query_vec, target_paper, runtime_settings):
                captured["query_vec"] = query_vec
                captured["target_paper"] = target_paper
                captured["settings"] = runtime_settings
                return SimpleNamespace(
                    papers=[
                        SimpleNamespace(
                            id="arxiv:1601.00001",
                            source="arxiv",
                            source_id="1601.00001",
                            canonical_id="arxiv:1601.00001",
                            title="Prior Attention Work",
                            text="Earlier attention mechanisms.",
                            authors=["D. Author"],
                            published_date="2016-01-01",
                            primary_category="cs.CL",
                            external_url="https://arxiv.org/abs/1601.00001",
                            arxiv_id="1601.00001",
                        )
                    ],
                )

            cts.collect_prior_work_candidates = collect

            candidates = cts.expand_seed_candidates(seed, settings)
        finally:
            cts.get_embedding = original_get_embedding
            cts.collect_prior_work_candidates = original_collect

        self.assertIn("Attention Is All You Need", captured["embedding_text"])
        self.assertEqual(captured["query_vec"], [0.1, 0.2])
        self.assertIs(captured["settings"], settings)
        self.assertEqual(captured["target_paper"].title, "Attention Is All You Need")
        self.assertEqual([candidate.paper_id for candidate in candidates], ["arxiv:1601.00001"])
        self.assertEqual(candidates[0].source, "arxiv")
        self.assertEqual(candidates[0].abstract, "Earlier attention mechanisms.")

    def test_run_citation_trace_keeps_round_one_when_round_two_seed_fails(self):
        session = cts.CitationTraceSession(
            session_id="run-session",
            source_type="file",
            source_id="paper.pdf",
            source_url=None,
            target_paper=cts.CitationTracePaperNode(
                "target",
                "target",
                "paper.pdf",
                "file:paper.pdf",
                "Target",
                abstract="attention method",
            ),
            answer_language="en",
            reference_entries=[
                cts.ReferenceEntry(
                    "ref-1",
                    "Good reference. arXiv:1601.00001",
                    arxiv_id="1601.00001",
                    title_hint="Good reference",
                ),
                cts.ReferenceEntry(
                    "ref-2",
                    "Bad reference. arXiv:1601.00002",
                    arxiv_id="1601.00002",
                    title_hint="Bad reference",
                ),
            ],
        )
        original_resolve = cts.resolve_reference_to_node
        original_expand = cts.expand_seed_candidates
        try:
            cts.resolve_reference_to_node = lambda reference, settings: cts.CitationTracePaperNode(
                reference.arxiv_id or reference.reference_id,
                "arxiv",
                reference.arxiv_id or reference.reference_id,
                reference.reference_id,
                reference.title_hint or "Paper",
                abstract="attention method",
                arxiv_id=reference.arxiv_id,
            )

            def expand(seed, settings):
                if seed.paper_id == "1601.00002":
                    raise RuntimeError("seed failed")
                return [
                    cts.CitationTracePaperNode(
                        "prior",
                        "arxiv",
                        "prior",
                        "prior",
                        "Prior",
                        abstract="attention",
                    )
                ]

            cts.expand_seed_candidates = expand
            events = list(cts.run_citation_trace_events(session, settings=None))
        finally:
            cts.resolve_reference_to_node = original_resolve
            cts.expand_seed_candidates = original_expand

        self.assertTrue(any(name == "round_summary" and payload["round"] == 1 for name, payload in events))
        self.assertEqual(session.rounds[0].status, "completed")
        self.assertEqual(session.rounds[1].status, "partial")
        self.assertTrue(session.rounds[1].warnings)
        self.assertGreaterEqual(len(session.ledger_entries), 2)
        self.assertTrue(any(name == "complete" for name, _payload in events))

    def test_synthesis_failure_leaves_ledger_available(self):
        session = cts.CitationTraceSession(
            session_id="synthesis-fail",
            source_type="file",
            source_id="paper.pdf",
            source_url=None,
            target_paper=cts.CitationTracePaperNode("target", "target", "paper.pdf", "file:paper.pdf", "Target"),
            answer_language="en",
            ledger_entries=[
                cts.CitationTraceLedgerEntry(
                    "entry",
                    cts.CitationTracePaperNode("paper", "arxiv", "paper", "paper", "Paper"),
                    None,
                    1,
                    "retrieved_similar",
                    "medium",
                    0.5,
                    cts.CitationTraceScoreBreakdown(),
                )
            ],
        )
        original = cts.synthesize_final_top5
        try:
            cts.synthesize_final_top5 = lambda session, settings: (_ for _ in ()).throw(RuntimeError("model failed"))
            events = list(cts.run_synthesis_stage(session, settings=None))
        finally:
            cts.synthesize_final_top5 = original

        self.assertEqual(session.final_top5, [])
        self.assertTrue(any(name == "warning" and "model failed" in payload["message"] for name, payload in events))
        self.assertEqual(len(session.ledger_entries), 1)

    def test_run_citation_trace_marks_empty_reference_run_partial(self):
        session = cts.CitationTraceSession(
            session_id="empty-run",
            source_type="file",
            source_id="paper.pdf",
            source_url=None,
            target_paper=cts.CitationTracePaperNode("target", "target", "paper.pdf", "file:paper.pdf", "Target"),
            answer_language="en",
        )

        events = list(cts.run_citation_trace_events(session, settings=None))
        complete_payload = [payload for name, payload in events if name == "complete"][-1]

        self.assertEqual(session.rounds[0].status, "partial")
        self.assertEqual(session.status, "partial")
        self.assertEqual(complete_payload["status"], "partial")

    def test_run_round_one_uses_extraction_order_for_unresolved_ties(self):
        references = [
            cts.ReferenceEntry(
                reference_id=f"ref-{99 - index:02d}",
                raw_text=f"Reference {index}.",
                raw_label=f"[{index}]",
                title_hint=f"Reference {index}",
            )
            for index in range(1, 13)
        ]
        session = cts.CitationTraceSession(
            session_id="tie-run",
            source_type="file",
            source_id="paper.pdf",
            source_url=None,
            target_paper=cts.CitationTracePaperNode("target", "target", "paper.pdf", "file:paper.pdf", "Target"),
            answer_language="en",
            reference_entries=references,
        )

        summary = cts.run_round_one(session, settings=None)

        self.assertEqual([entry.reference_text for entry in summary.ledger_entries], [
            f"Reference {index}." for index in range(1, 11)
        ])

    def test_rerun_citation_trace_clears_stale_warnings(self):
        session = cts.CitationTraceSession(
            session_id="rerun",
            source_type="file",
            source_id="paper.pdf",
            source_url=None,
            target_paper=cts.CitationTracePaperNode("target", "target", "paper.pdf", "file:paper.pdf", "Target"),
            answer_language="en",
            reference_entries=[
                cts.ReferenceEntry("ref-1", "Good reference. arXiv:1601.00001", arxiv_id="1601.00001")
            ],
            warnings=["Synthesis failed: previous run"],
        )
        original_resolve = cts.resolve_reference_to_node
        original_expand = cts.expand_seed_candidates
        try:
            cts.resolve_reference_to_node = lambda reference, settings: cts.CitationTracePaperNode(
                "1601.00001",
                "arxiv",
                "1601.00001",
                "arxiv:1601.00001",
                "Good reference",
                arxiv_id="1601.00001",
            )
            cts.expand_seed_candidates = lambda seed, settings: []
            list(cts.run_citation_trace_events(session, settings=None))
        finally:
            cts.resolve_reference_to_node = original_resolve
            cts.expand_seed_candidates = original_expand

        self.assertEqual(session.warnings, [])
        self.assertEqual(session.status, "completed")


if __name__ == "__main__":
    unittest.main()
