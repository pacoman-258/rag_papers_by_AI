# Research Topics Assistant Design

## Goal

Make the Live2D assistant the research secretary and personalized mentor layer for the platform, centered on topic projects and paper reading threads.

A research topic is the top-level project. A paper reading thread is the smallest durable research unit inside a topic. Search can recommend what to read next, but search never writes topic records by itself. Durable topic records begin when the user starts or resumes Paper Reader work for a paper inside a topic.

## Current Behavior

The assistant currently acts as a linked-context explainer. Search, Citation Trace, and Paper Reader can publish `answer_context` and `workflow_context` to the assistant. Paper Reader already sends a compact whole-paper context, selected excerpts can be synced manually, and assistant memory can infer cautious research profile signals.

This is useful, but it is still mostly session-local. The assistant does not yet maintain topic projects, paper-level reading threads, thread history, or durable research actions. Live2D chat also uses the general answer model configuration, so assistant behavior cannot be tuned separately from final QA answers.

## Product Model

The platform should behave like a research workspace with topic projects:

- `ResearchTopic` is like a ChatGPT project for one research direction.
- `PaperReadingThread` is like a conversation inside that project, scoped to one paper.
- A single topic and paper pair has only one continuing reading thread.
- Paper Reader is the entry point for durable topic records.
- Citation Trace is stored as a research action inside the current paper reading thread.
- Search only produces recommendations, such as "open this paper in topic X" or "start a new topic from this paper."

The assistant can generate dynamic suggestion cards while search, Paper Reader, or Citation Trace is running or after they complete. These cards must not interrupt the main workflow. They appear quietly in the assistant panel or topic side area, with only lightweight highlighting for high-value suggestions.

## Core Entities

### ResearchTopic

Stores a topic project:

- `topic_id`
- `title`
- `description`
- `keywords`
- `status`: `active`, `paused`, or `archived`
- `created_from`: manual creation or confirmed assistant suggestion
- `created_at`
- `updated_at`

Creating or merging topics requires user confirmation.

### PaperReadingThread

Stores the durable paper-level thread inside a topic:

- `thread_id`
- `topic_id`
- `paper_key`: canonical arXiv ID when available, otherwise a normalized external ID or title hash
- `paper_title`
- `paper_metadata`
- `status`: `queued`, `reading`, `read`, or `skipped`
- `last_page`
- `progress`
- `last_reader_session_id`
- `created_at`
- `updated_at`

The unique logical key is `(topic_id, paper_key)`. Reopening the same paper in the same topic resumes the existing thread instead of creating a duplicate.

### ThreadEvent

Stores the timeline of a paper reading thread:

- `event_id`
- `thread_id`
- `event_type`
- `source`: `paper_reader`, `assistant`, `citation_trace`, or `user`
- `payload`
- `created_at`

Thread events include reading progress changes, selected excerpts, user questions, assistant replies, open questions, and linked research actions.

### CitationTraceAction

Stores one Citation Trace run as an action in a paper reading thread:

- `action_id`
- `thread_id`
- `citation_trace_session_id`
- `target_paper`
- `candidate_summary`
- `final_top5`
- `warnings`
- `assistant_explanation`
- `created_at`

Citation Trace results are evidence records, not automatic topic conclusions. Weak or ambiguous trace results should be saved as caveats or open questions unless the user confirms a stronger interpretation.

### TopicInsight

Stores topic-level research notes derived from one or more paper threads:

- `insight_id`
- `topic_id`
- `kind`: `conclusion`, `evidence`, `caveat`, `contradiction`, or `open_question`
- `status`: `draft` or `confirmed`
- `text`
- `source_refs`
- `created_at`
- `updated_at`

High-risk insights, such as conclusions, evidence judgments, caveats, and contradictions, must be shown as drafts and require user confirmation before becoming confirmed topic knowledge.

### AssistantSuggestion

Stores or exposes dynamic suggestion cards:

- `suggestion_id`
- `source_workflow`: `search`, `paper_reader`, or `citation_trace`
- `source_stage`: `running` or `completed`
- `risk_level`: `low`, `medium`, or `high`
- `target_topic_candidates`
- `target_thread_id`
- `summary`
- `recommended_action`
- `status`: `pending`, `accepted`, `dismissed`, or `expired`
- `created_at`

Search suggestions are recommendation-only and do not write topic records. Paper Reader and Citation Trace suggestions can write low-risk thread records automatically only after a paper is already attached to a topic.

## Assistant Model Configuration

Add a dedicated assistant model configuration named `assistant_chat`.

It should mirror the existing chat configuration shape:

- `provider`
- `model`
- `base_url`
- `api_key`
- `clear_api_key`
- `max_context_tokens` if the implementation keeps a context budget for assistant prompts

Settings UI should expose this as a separate assistant section. API keys remain write-only: responses return `has_api_key`, never the secret. Existing installs should fall back to `answer_chat` until `assistant_chat` is configured, so the upgrade does not break current assistant chat.

Live2D chat and suggestion-card generation should use `assistant_chat`. Search answer generation, Paper Reader chat, translation, and Citation Trace model calls keep their current dedicated configurations.

## Workflow Rules

### Search

Search can publish transient research events and suggestion cards, but it cannot mutate topics.

Allowed search suggestions:

- recommend opening a paper in Paper Reader under an existing topic
- recommend creating a topic from a paper or query, with confirmation
- recommend refining search terms
- recommend comparing several candidate papers before choosing one to read

Disallowed search behavior:

- auto-create topics
- auto-add papers to topic records
- auto-write topic insights

### Paper Reader

Paper Reader is the durable record entry point.

When a paper is opened, the user can attach it to an existing topic or accept an assistant suggestion to create a topic. After attachment, the platform creates or resumes the unique `PaperReadingThread` for that topic and paper.

Low-risk automatic records:

- reading progress
- last read page
- user questions
- assistant answers
- selected excerpts explicitly synced to the assistant
- thread-level open questions drafted from user questions or selected excerpts

Confirmation required:

- new topic creation
- moving a paper thread between topics
- topic-level conclusions
- evidence judgments
- caveats or contradictions promoted to topic insights

### Citation Trace

Citation Trace can run from a paper reading thread. Its run is stored as a `CitationTraceAction` inside the thread.

During a trace, suggestion cards can warn about weak evidence, topic mismatch, or likely caveats. After completion, the assistant can suggest saving results as thread evidence, caveats, or open questions. Confirmed topic-level insights still require user approval.

## UI Design

### Assistant Panel

The assistant panel keeps the chat and adds a quiet suggestion-card area. It should show only the most relevant 2 to 4 cards for the current workflow.

Cards should not open modals, steal focus, or block typing. They can offer compact actions such as:

- `Open in topic`
- `Create topic`
- `Resume reading thread`
- `Save as open question`
- `Draft topic insight`
- `Dismiss`

### Research Topics Page

Add a top-level `Research Topics` or `课题档案` tab.

The page should show:

- topic list and status
- selected topic overview
- paper reading threads
- reading progress
- thread history
- open questions
- Citation Trace actions
- draft and confirmed topic insights
- pending suggestions for the selected topic

This page is the full management surface. The assistant panel remains the lightweight entry point.

### Paper Reader

Paper Reader should show the current topic and reading thread state near the paper header. If no topic is attached, it can show assistant suggestions without forcing the user to choose immediately.

When the user attaches the paper to a topic, the reader begins durable thread recording.

### Search Workspace

Search can show assistant recommendations after or during search, but these are next-step recommendations only. The most important action is opening a selected paper in Paper Reader under a topic.

## Backend Shape

Add a focused service boundary, for example `backend/research_topics_service.py`, rather than adding the new behavior directly to `backend/main.py`.

Likely API groups:

- `GET /api/research-topics`
- `POST /api/research-topics`
- `GET /api/research-topics/{topic_id}`
- `POST /api/research-topics/{topic_id}/papers`
- `GET /api/research-topics/{topic_id}/threads/{thread_id}`
- `POST /api/research-topics/threads/{thread_id}/events`
- `POST /api/research-topics/threads/{thread_id}/citation-trace-actions`
- `GET /api/assistant/suggestions`
- `POST /api/assistant/suggestions/{suggestion_id}/accept`
- `POST /api/assistant/suggestions/{suggestion_id}/dismiss`

The implementation can store topic data in the same PostgreSQL-backed application database used by local retrieval and assistant memory, with schema creation guarded by an `ensure_research_topics_schema` helper. If the database is unavailable, the assistant should still chat and show transient suggestions, while durable topic records degrade with a clear notice.

## Suggestion Generation

Use a rule-first strategy:

- rules create obvious suggestions, such as resume an existing thread or attach a Paper Reader session to the current topic
- LLM calls create only the suggestions that require synthesis, such as draft insights or caveat wording
- suggestion payloads store sources so every accepted write can be traced back to a search, paper thread, selection, or trace action

This keeps the assistant useful without making every workflow step dependent on model calls.

## Safety And Trust

The assistant must not invent papers, citations, experiments, or conclusions. Topic records should preserve provenance for accepted suggestions.

Write policy:

- Search: no durable topic writes.
- Paper Reader low-risk thread events: automatic after topic attachment.
- Topic creation and paper attachment: explicit user action or accepted suggestion.
- Topic insights: draft first, confirmation required.
- Citation Trace results: saved as action records; conclusions require confirmation.

## Testing

Backend tests should cover:

- `assistant_chat` config serialization and write-only API key behavior
- Live2D chat using `assistant_chat` with fallback to `answer_chat`
- unique `(topic_id, paper_key)` thread behavior
- search suggestions not mutating topic records
- Paper Reader creating or resuming a thread after topic attachment
- low-risk thread event writes
- TopicInsight confirmation requirements
- Citation Trace actions stored under a paper reading thread

Frontend tests should cover:

- settings page exposes assistant model configuration
- topic archive tab renders topic list, paper threads, open questions, insights, and suggestions
- assistant suggestion cards are quiet and non-blocking
- Search recommendations open Paper Reader instead of writing topic state
- Paper Reader shows topic/thread attachment state
- Citation Trace action is visible inside the paper reading thread history

## Migration

Existing assistant memory and research profile data remain unchanged. Topic archives start empty until the user creates or confirms topics. Existing Paper Reader sessions do not need to be migrated; only new or explicitly attached sessions become durable paper reading threads.

The `assistant_chat` config should default to `answer_chat` behavior when unset, so existing installs keep working.
