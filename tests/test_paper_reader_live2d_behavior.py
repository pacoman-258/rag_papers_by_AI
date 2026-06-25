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
        self.assertNotIn("pst" + "_auto", app_source)
        self.assertIn("citation_trace_auto", app_source)

    def test_paper_reader_syncs_whole_paper_context_not_active_page_context(self) -> None:
        paper_reader_source = (ROOT / "frontend" / "src" / "PaperReaderPage.jsx").read_text(encoding="utf-8")

        self.assertIn("/assistant-context", paper_reader_source)
        self.assertIn("fetchAssistantContext", paper_reader_source)
        self.assertIn("paperAssistantContext", paper_reader_source)
        self.assertIn("syncSelectionToAssistant", paper_reader_source)
        self.assertIn("onSyncSelectionToAssistant", paper_reader_source)
        self.assertIn("selected_excerpt", paper_reader_source)
        self.assertNotIn("const answerContext = extractAssistantContextText(activePage);", paper_reader_source)
        self.assertNotIn("buildPaperReaderWorkflowContext({\n      session,\n      page: activePage", paper_reader_source)

    def test_live2d_request_packages_conversation_context_with_workflow_context(self) -> None:
        assistant_source = (ROOT / "frontend" / "src" / "Live2DAssistant.jsx").read_text(encoding="utf-8")

        self.assertIn("function enrichWorkflowContextWithConversation", assistant_source)
        self.assertIn("conversation_context", assistant_source)
        self.assertIn("recent_messages", assistant_source)
        self.assertIn("current_user_message", assistant_source)
        self.assertIn("resolvedWorkflowContextWithConversation", assistant_source)
        self.assertIn("workflow_context: resolvedWorkflowContextWithConversation", assistant_source)


if __name__ == "__main__":
    unittest.main()
