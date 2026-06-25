import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "frontend/src/App.jsx"
ASSISTANT = ROOT / "frontend/src/Live2DAssistant.jsx"
PROFILE_PAGE = ROOT / "frontend/src/ResearchProfilePage.jsx"


class ResearchProfileFrontendTest(unittest.TestCase):
    def test_research_profile_management_lives_outside_live2d_panel(self) -> None:
        assistant_source = ASSISTANT.read_text(encoding="utf-8")

        self.assertNotIn("assistant-profile-panel", assistant_source)
        self.assertNotIn("/api/live2d/research-profile", assistant_source)

        app_source = APP.read_text(encoding="utf-8")
        self.assertIn("ResearchProfilePage", app_source)
        self.assertIn("researchProfileTab", app_source)
        self.assertIn('activeTab === "research_profile"', app_source)

        page_source = PROFILE_PAGE.read_text(encoding="utf-8")
        self.assertIn("/api/live2d/research-profile", page_source)
        self.assertIn("/api/live2d/research-profile/refresh", page_source)
        self.assertIn("/api/live2d/memory/", page_source)
        self.assertIn("/pin", page_source)
        self.assertIn('"DELETE"', page_source)


if __name__ == "__main__":
    unittest.main()
