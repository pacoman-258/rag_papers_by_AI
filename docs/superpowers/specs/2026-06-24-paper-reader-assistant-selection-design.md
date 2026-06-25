# Paper Reader Assistant Selection Design

## Goal

Paper Reader should give the Live2D assistant a paper-wide reading context, while letting the user explicitly decide when a PDF text selection becomes an assistant focus.

## Current Behavior

Paper Reader silently publishes the active page as the assistant context when the page is ready. PDF selections are only used by the selection translation card. The Live2D prompt also describes Paper Reader as page-local, so replies are biased toward the current page even when the user expects paper-level help.

## Design

Add a Paper Reader assistant-context API that returns a compact paper-wide context derived from the session title, metadata, paper map, chunks, and extracted source pages. The frontend fetches this context after a session is available and publishes it to `onAssistantContextChange`; it no longer builds the default assistant context from the active page.

Selections remain local until the user clicks a new `Sync to assistant` action in the selection card. That action republishes the paper-wide context with `workflow_context.metadata.selected_excerpt`, including the selected text, source page numbers, and timestamp. Clearing or changing the raw browser selection does not silently change assistant context. Loading another paper resets the linked assistant context.

The Live2D prompt renders the selected excerpt separately from the whole-paper context and treats it as the immediate focus when present. Paper Reader rules are updated from page-local wording to whole-paper wording, with a guard that the assistant must not invent claims outside provided context.

Live2D also packages recent assistant conversation into `workflow_context.metadata.conversation_context` before each chat request. The package includes the recent user/assistant turns and the current user message, so Paper Reader replies can connect the paper context, the synced selection, and the ongoing dialogue.

## Testing

Backend tests cover the paper-wide assistant context builder, selected excerpt rendering, and conversation-context rendering. Frontend source tests cover the new context endpoint usage, removal of page-local default context publishing, explicit selection sync control, and request-time packaging of conversation context.
