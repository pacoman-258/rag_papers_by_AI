from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PaperReaderLive2DBehaviorTest(unittest.TestCase):
    def test_paper_reader_does_not_schedule_live2d_auto_replies(self) -> None:
        paper_reader_source = (ROOT / "frontend" / "src" / "PaperReaderPage.jsx").read_text(encoding="utf-8")

        self.assertNotIn("onScheduleAssistantAutoReply", paper_reader_source)
        self.assertNotIn("autoReplyKeyRef", paper_reader_source)

    def test_app_keeps_non_paper_reader_auto_replies_available(self) -> None:
        app_source = (ROOT / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")

        self.assertIn("function scheduleAssistantAutoReply", app_source)
        self.assertIn("qa_auto", app_source)
        self.assertIn("pst_auto", app_source)


if __name__ == "__main__":
    unittest.main()
