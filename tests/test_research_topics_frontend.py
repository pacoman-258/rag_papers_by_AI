import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "frontend/src/App.jsx"
ASSISTANT = ROOT / "frontend/src/Live2DAssistant.jsx"
PAPER_READER = ROOT / "frontend/src/PaperReaderPage.jsx"
TOPICS_PAGE = ROOT / "frontend/src/ResearchTopicsPage.jsx"
CITATION_TRACE = ROOT / "frontend/src/CitationTracePage.jsx"


class ResearchTopicsFrontendTest(unittest.TestCase):
    def test_app_exposes_research_topics_tab_and_assistant_chat_settings(self) -> None:
        text = APP.read_text(encoding="utf-8")

        self.assertIn("ResearchTopicsPage", text)
        self.assertIn("researchTopicsTab", text)
        self.assertIn('activeTab === "research_topics"', text)
        self.assertIn("assistant_chat", text)
        self.assertIn("assistantChatModel", text)

    def test_paper_reader_can_attach_to_topic_and_publish_thread_events(self) -> None:
        text = PAPER_READER.read_text(encoding="utf-8")

        self.assertIn("/api/research-topics", text)
        self.assertIn("attachPaperToResearchTopic", text)
        self.assertIn("currentResearchThread", text)
        self.assertIn("recordResearchThreadEvent", text)
        self.assertIn("paper_reader.progress", text)
        self.assertIn("paper_reader.question", text)

    def test_citation_trace_can_store_action_in_research_thread(self) -> None:
        text = CITATION_TRACE.read_text(encoding="utf-8")

        self.assertIn("researchThread", text)
        self.assertIn("storeCitationTraceAction", text)
        self.assertIn("/citation-trace-actions", text)
        self.assertIn("citation_trace.completed", text)

    def test_assistant_has_quiet_suggestion_tray(self) -> None:
        text = ASSISTANT.read_text(encoding="utf-8")

        self.assertIn("quietSuggestionRefreshToken", text)
        self.assertIn("loadAssistantSuggestions", text)
        self.assertIn("/api/assistant/suggestions", text)
        self.assertIn("assistant-suggestion-tray", text)
        self.assertIn("handleAssistantSuggestionAction", text)
        self.assertIn("/accept", text)
        self.assertIn("/dismiss", text)

    def test_workflows_refresh_quiet_suggestion_cards(self) -> None:
        app_text = APP.read_text(encoding="utf-8")
        paper_reader_text = PAPER_READER.read_text(encoding="utf-8")
        citation_trace_text = CITATION_TRACE.read_text(encoding="utf-8")

        self.assertIn("createSearchSuggestionCards", app_text)
        self.assertIn("/api/assistant/suggestions/search", app_text)
        self.assertIn("setSuggestionRefreshToken", app_text)
        self.assertIn("quietSuggestionRefreshToken", app_text)
        self.assertIn("onSuggestionRefresh", paper_reader_text)
        self.assertIn("/api/assistant/suggestions/thread-open-question", paper_reader_text)
        self.assertIn("onSuggestionRefresh", citation_trace_text)


if __name__ == "__main__":
    unittest.main()
