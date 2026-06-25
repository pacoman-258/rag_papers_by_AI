import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "frontend/src/App.jsx"


class GlobalSelectionTranslationFrontendTest(unittest.TestCase):
    def test_app_exposes_global_selection_translation_card_outside_paper_reader(self):
        text = APP.read_text(encoding="utf-8")

        self.assertIn("GlobalSelectionTranslationPanel", text)
        self.assertIn("/api/translate-selection", text)
        self.assertIn('activeTab !== "paper_reader"', text)
        self.assertIn("selectionchange", text)
        self.assertIn("globalSelectionTranslation", text)


if __name__ == "__main__":
    unittest.main()
