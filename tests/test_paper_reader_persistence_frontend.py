import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "frontend/src/App.jsx"
PAPER_READER = ROOT / "frontend/src/PaperReaderPage.jsx"


class PaperReaderPersistenceFrontendTest(unittest.TestCase):
    def test_app_keeps_paper_reader_mounted_when_other_tabs_are_active(self) -> None:
        source = APP.read_text(encoding="utf-8")

        self.assertTrue(
            'hidden={activeTab !== "paper_reader"}' in source,
            "PaperReaderPage should stay mounted and be hidden when another tab is active.",
        )
        self.assertFalse(
            '{activeTab === "paper_reader" ? (\n        <PaperReaderPage' in source,
            "PaperReaderPage should not be guarded by conditional rendering that unmounts it.",
        )

    def test_paper_reader_session_only_has_explicit_end_reading_reset(self) -> None:
        source = PAPER_READER.read_text(encoding="utf-8")

        self.assertTrue("function endReadingSession()" in source)
        self.assertTrue("onClick={endReadingSession}" in source)
        self.assertTrue('t("paperReaderEndReading")' in source)
        self.assertTrue("resetReaderState();" in source)

    def test_hidden_paper_reader_does_not_mount_assistant_or_shortcuts(self) -> None:
        app_source = APP.read_text(encoding="utf-8")
        reader_source = PAPER_READER.read_text(encoding="utf-8")

        self.assertTrue('isActive={activeTab === "paper_reader"}' in app_source)
        self.assertTrue("isActive = true" in reader_source)
        self.assertTrue("isActive ? renderAssistantLayer?.() || null : null" in reader_source)
        self.assertTrue("if (!isActive) {" in reader_source)

    def test_consumed_initial_arxiv_url_can_be_loaded_again_later(self) -> None:
        source = PAPER_READER.read_text(encoding="utf-8")

        self.assertTrue('autoLoadUrlRef.current = "";' in source)


if __name__ == "__main__":
    unittest.main()
