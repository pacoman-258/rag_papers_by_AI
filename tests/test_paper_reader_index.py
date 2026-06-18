import unittest
from pathlib import Path

from backend import paper_reader_service as prs


class PaperReaderIndexTreeTest(unittest.TestCase):
    def test_builds_section_tree_with_page_links(self):
        chunks = [
            prs.PaperReaderChunk(
                chunk_id="c-abstract",
                text="We introduce a retrieval method for reading papers.",
                section_title="Abstract",
                subsection_title=None,
                reading_focus_key="core_question",
                reading_focus_title="Core question",
                page_start=1,
                page_end=1,
                token_estimate=20,
            ),
            prs.PaperReaderChunk(
                chunk_id="c-method",
                text="The method builds a document tree before retrieval.",
                section_title="Method",
                subsection_title="Tree construction",
                reading_focus_key="method_or_mechanism",
                reading_focus_title="Method or mechanism",
                page_start=2,
                page_end=3,
                token_estimate=28,
            ),
            prs.PaperReaderChunk(
                chunk_id="c-exp",
                text="Experiments compare the tree-guided reader with flat chunking.",
                section_title="Experiments",
                subsection_title=None,
                reading_focus_key="evidence_or_experiments",
                reading_focus_title="Evidence or experiments",
                page_start=4,
                page_end=5,
                token_estimate=30,
            ),
        ]
        pages = [
            prs.PaperReaderPagePlan(
                page_index=0,
                title="Core question",
                focus_key="core_question",
                focus_title="Core question",
                section_title="Core question",
                subsection_title=None,
                source_section_titles=["Abstract"],
                chunk_ids=["c-abstract"],
                page_start=1,
                page_end=1,
                estimated_tokens=20,
            ),
            prs.PaperReaderPagePlan(
                page_index=1,
                title="Method or mechanism",
                focus_key="method_or_mechanism",
                focus_title="Method or mechanism",
                section_title="Method or mechanism",
                subsection_title=None,
                source_section_titles=["Method - Tree construction"],
                chunk_ids=["c-method"],
                page_start=2,
                page_end=3,
                estimated_tokens=28,
            ),
        ]

        index_tree = prs._build_paper_index_tree(chunks, pages)

        self.assertEqual(index_tree.title, "Paper Map")
        section_titles = [node.title for node in index_tree.children]
        self.assertEqual(section_titles, ["Abstract", "Method", "Experiments"])
        method_node = index_tree.children[1]
        self.assertEqual(method_node.page_indices, [1])
        self.assertEqual(method_node.chunk_ids, ["c-method"])
        self.assertEqual(method_node.children[0].title, "Tree construction")
        self.assertEqual(method_node.children[0].page_start, 2)
        self.assertEqual(method_node.children[0].page_end, 3)

    def test_page_model_serializes_reading_blocks_from_plan_chunks(self):
        chunks = [
            prs.PaperReaderChunk(
                chunk_id="c-intro",
                text="The Transformer is based solely on attention mechanisms.",
                section_title="Abstract",
                subsection_title=None,
                reading_focus_key="quick_story",
                reading_focus_title="Quick story",
                page_start=1,
                page_end=1,
                token_estimate=12,
            ),
            prs.PaperReaderChunk(
                chunk_id="c-attention",
                text="Self-attention relates different positions of a single sequence.",
                section_title="Model Architecture",
                subsection_title="Attention",
                reading_focus_key="quick_story",
                reading_focus_title="Quick story",
                page_start=3,
                page_end=3,
                token_estimate=14,
            ),
        ]
        plan = prs.PaperReaderPagePlan(
            page_index=0,
            title="Quick story",
            focus_key="quick_story",
            focus_title="Quick story",
            section_title="Quick story",
            subsection_title=None,
            source_section_titles=["Abstract", "Model Architecture - Attention"],
            chunk_ids=["c-intro", "c-attention"],
            page_start=1,
            page_end=3,
            estimated_tokens=26,
        )
        session = prs.PaperReaderSession(
            session_id="session-1",
            source_type="file",
            source_url=None,
            source_id="attention.pdf",
            paper_title="Attention Is All You Need",
            authors=[],
            published_date=None,
            answer_language="zh",
            reader_mode="guided",
            discipline="science_engineering",
            discipline_source="manual",
            pdf_path=Path("/tmp/attention.pdf"),
            max_context_tokens=8192,
            reserved_output_tokens=1024,
            reserved_scaffold_tokens=1200,
            page_input_budget=5968,
            settings=None,
            chunks=chunks,
            pages=[plan],
            page_statuses={0: "ready"},
        )

        content = prs._build_page_placeholder(session, plan, status="ready")
        model = prs.page_content_to_model(content)

        self.assertEqual([block.chunk_id for block in model.reading_blocks], ["c-intro", "c-attention"])
        self.assertEqual(model.reading_blocks[0].source_label, "Abstract")
        self.assertEqual(model.reading_blocks[0].original_en, chunks[0].text)
        self.assertEqual(model.reading_blocks[0].page_start, 1)
        self.assertEqual(model.reading_blocks[1].source_label, "Model Architecture - Attention")
        self.assertIsNone(model.reading_blocks[1].display_text)

    def test_page_model_does_not_use_insight_summary_as_reading_block_translation(self):
        original = "The encoder maps an input sequence of symbol representations to continuous representations."
        localized = "编码器会把输入符号序列映射成连续向量表示，供解码器逐步生成输出。"
        content = prs.PaperReaderPageContent(
            page_index=2,
            title="Method or mechanism",
            status="ready",
            page_overview=prs.PaperReaderStructuredTextModel(
                original_en="The Transformer follows this overall architecture.",
                explanation="本页解释 Transformer 的整体编码器-解码器结构。",
                display_text="Original (EN): The Transformer follows this overall architecture.\n中文解读: 本页解释 Transformer 的整体编码器-解码器结构。",
            ),
            insights=[
                prs.PaperReaderInsightModel(
                    insight_id="2-1",
                    title="Encoder mapping",
                    kind="method",
                    summary=prs.PaperReaderStructuredTextModel(
                        original_en=original,
                        explanation=localized,
                        display_text=f"Original (EN): {original} | 中文解读: {localized}",
                    ),
                    source_chunk_ids=["c-encoder"],
                    source_section_labels=["Model Architecture"],
                )
            ],
            reading_blocks=[
                prs.PaperReaderReadingBlockModel(
                    chunk_id="c-encoder",
                    source_label="Model Architecture",
                    page_start=2,
                    page_end=2,
                    original_en=original,
                    explanation=None,
                    display_text=original,
                )
            ],
            chunk_ids=["c-encoder"],
            page_start=2,
            page_end=2,
        )

        model = prs.page_content_to_model(content)

        self.assertEqual(model.reading_blocks[0].original_en, original)
        self.assertIsNone(model.reading_blocks[0].explanation)
        self.assertIsNone(model.reading_blocks[0].display_text)

    def test_page_model_does_not_reuse_page_or_section_summary_for_reading_blocks(self):
        original = "Provided proper attribution is provided, Google hereby grants permission to reproduce the tables."
        content = prs.PaperReaderPageContent(
            page_index=0,
            title="Quick story",
            status="ready",
            page_overview=prs.PaperReaderStructuredTextModel(
                original_en="Most competitive neural sequence transduction models have an encoder-decoder structure.",
                explanation="本文提出了一个基于编码器-解码器结构的序列转换模型。",
                display_text="Original (EN): Most competitive neural sequence transduction models have an encoder-decoder structure.\n中文解读: 本文提出了一个基于编码器-解码器结构的序列转换模型。",
            ),
            insights=[
                prs.PaperReaderInsightModel(
                    insight_id="0-1",
                    title="提出的方法",
                    kind="method",
                    summary=prs.PaperReaderStructuredTextModel(
                        original_en="Most competitive neural sequence transduction models have an encoder-decoder structure.",
                        explanation="编码器-解码器结合自注意力机制构成了本文的核心创新。",
                        display_text="Original (EN): Most competitive neural sequence transduction models have an encoder-decoder structure. | 中文解读: 编码器-解码器结合自注意力机制构成了本文的核心创新。",
                    ),
                    source_chunk_ids=[],
                    source_section_labels=["Abstract"],
                )
            ],
            reading_blocks=[
                prs.PaperReaderReadingBlockModel(
                    chunk_id="c-copyright",
                    source_label="Abstract",
                    page_start=1,
                    page_end=1,
                    original_en=original,
                    explanation=None,
                    display_text=None,
                )
            ],
            chunk_ids=["c-copyright"],
            page_start=1,
            page_end=1,
        )

        model = prs.page_content_to_model(content)

        self.assertEqual(model.reading_blocks[0].original_en, original)
        self.assertIsNone(model.reading_blocks[0].explanation)
        self.assertIsNone(model.reading_blocks[0].display_text)


if __name__ == "__main__":
    unittest.main()
