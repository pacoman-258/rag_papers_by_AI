import unittest
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from backend import paper_reader_service as prs
from tests.test_paper_reader_translation import _session, _settings


class _FakeMediaBox:
    width = 612
    height = 792


class _FakePdfPage:
    mediabox = _FakeMediaBox()

    def extract_text(self, *args, **kwargs):
        visitor_text = kwargs.get("visitor_text")
        if visitor_text is not None:
            visitor_text("1 Introduction", None, [1, 0, 0, 1, 108, 710], {"/BaseFont": "/NimbusRomNo9L-Medi"}, 11.9552)
            visitor_text("Recurrent neural networks are sequence models.", None, [1, 0, 0, 1, 108, 685], {"/BaseFont": "/NimbusRomNo9L-Regu"}, 9.9626)
        return "1 Introduction\nRecurrent neural networks are sequence models."


class PaperReaderSourceLayoutTest(unittest.TestCase):
    def test_pdf_source_layout_preserves_positions_and_font_weight(self):
        page = prs._extract_pdf_source_page_layout(_FakePdfPage(), 2)

        self.assertEqual(page.page_number, 2)
        self.assertEqual(page.width, 612)
        self.assertEqual(page.height, 792)
        self.assertEqual(page.spans[0].text, "1 Introduction")
        self.assertAlmostEqual(page.spans[0].x, 108)
        self.assertAlmostEqual(page.spans[0].y, 82)
        self.assertAlmostEqual(page.spans[0].font_size, 11.9552)
        self.assertEqual(page.spans[0].font_weight, "700")
        self.assertEqual(page.spans[1].font_weight, "400")

    def test_session_pdf_path_is_exposed_for_native_pdf_rendering(self):
        settings = _settings()
        session = _session(settings)

        with unittest.mock.patch.dict(prs._SESSION_CACHE, {session.session_id: session}, clear=True):
            pdf_path = prs.get_session_pdf_path(session.session_id)

        self.assertEqual(pdf_path, session.pdf_path)

    def test_build_session_does_not_generate_deep_reading_page(self):
        settings = _settings()
        chunk = prs.PaperReaderChunk(
            chunk_id="c-abstract",
            text="We propose a simple network architecture based solely on attention.",
            section_title="Abstract",
            subsection_title=None,
            reading_focus_key="problem_and_claim",
            reading_focus_title="Problem and claim",
            page_start=1,
            page_end=1,
            token_estimate=20,
        )
        plan = prs.PaperReaderPagePlan(
            page_index=0,
            title="Abstract",
            focus_key="problem_and_claim",
            focus_title="Problem and claim",
            section_title="Abstract",
            subsection_title=None,
            source_section_titles=["Abstract"],
            chunk_ids=[chunk.chunk_id],
            page_start=1,
            page_end=1,
            estimated_tokens=20,
        )

        with unittest.mock.patch.object(prs, "_extract_pdf_pages", return_value=[(1, chunk.text)]):
            with unittest.mock.patch.object(prs, "_build_blocks", return_value=[{"text": chunk.text}]):
                with unittest.mock.patch.object(prs, "_chunk_blocks", return_value=[chunk]):
                    with unittest.mock.patch.object(prs, "_resolve_discipline", return_value=("general", "auto")):
                        with unittest.mock.patch.object(prs, "_assign_reading_focuses", return_value=[chunk]):
                            with unittest.mock.patch.object(prs, "_pack_chunks_into_pages", return_value=[plan]):
                                with unittest.mock.patch.object(prs, "_build_quick_story_plan", return_value=None):
                                    with unittest.mock.patch.object(prs, "_build_paper_index_tree", return_value=None):
                                        with unittest.mock.patch.object(prs, "_generate_page_content_internal") as generate:
                                            session = prs._build_session(
                                                source_type="file",
                                                source_url=None,
                                                source_id="paper.pdf",
                                                pdf_path=Path("/tmp/paper.pdf"),
                                                settings=settings,
                                                reader_mode="standard",
                                                discipline="general",
                                            )

        generate.assert_not_called()
        self.assertEqual(session.page_statuses, {0: "ready"})

    def test_single_source_page_pdf_is_exposed_for_selectable_overlay_viewer(self):
        source_pdf = Path("/tmp/paper-reader-single-page-test.pdf")
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        writer.add_blank_page(width=612, height=792)
        with source_pdf.open("wb") as handle:
            writer.write(handle)
        settings = _settings()
        session = _session(settings)
        session.pdf_path = source_pdf

        with unittest.mock.patch.dict(prs._SESSION_CACHE, {session.session_id: session}, clear=True):
            page_pdf_path = prs.get_source_page_pdf_path(session.session_id, 2)

        self.assertTrue(page_pdf_path.exists())
        rendered_reader = PdfReader(str(page_pdf_path))
        self.assertEqual(len(rendered_reader.pages), 1)
        self.assertEqual(float(rendered_reader.pages[0].mediabox.width), 612)

    def test_frontend_pdf_reader_keeps_selectable_page_layer(self):
        frontend_source = Path(__file__).resolve().parents[1] / "frontend" / "src" / "PaperReaderPage.jsx"
        source = frontend_source.read_text(encoding="utf-8")

        self.assertIn("reader-pdf-page-text-layer", source)
        self.assertIn("sourcePagePdfUrl", source)
        self.assertIn("onMouseUp={onMouseUp}", source)

    def test_frontend_pdf_reader_has_zoom_controls(self):
        frontend_source = Path(__file__).resolve().parents[1] / "frontend" / "src" / "PaperReaderPage.jsx"
        style_source = Path(__file__).resolve().parents[1] / "frontend" / "src" / "styles.css"

        source = frontend_source.read_text(encoding="utf-8")
        styles = style_source.read_text(encoding="utf-8")

        self.assertIn("pdfZoom", source)
        self.assertIn("reader-pdf-zoom-controls", source)
        self.assertIn("onZoomIn", source)
        self.assertIn("--reader-pdf-zoom", styles)


if __name__ == "__main__":
    unittest.main()
