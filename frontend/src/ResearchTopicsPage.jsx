import { useEffect, useState } from "react";

const copy = {
  en: {
    title: "Research Topics",
    empty: "No topics yet. The assistant will suggest creating or linking topics when paper reading starts.",
    refresh: "Refresh",
    threads: "Paper Reading Threads",
    insights: "Insights and Caveats",
    suggestions: "Suggestion Cards",
    noThreads: "No paper reading threads yet.",
    noInsights: "No insights saved yet.",
    noSuggestions: "No pending suggestions.",
    updated: "Updated",
    status: "Status"
  },
  zh: {
    title: "课题档案",
    empty: "还没有课题。小助手会在精读开始时建议创建或关联课题。",
    refresh: "刷新",
    threads: "论文精读线程",
    insights: "阶段结论与疑点",
    suggestions: "建议卡",
    noThreads: "还没有论文精读线程。",
    noInsights: "还没有沉淀的阶段结论。",
    noSuggestions: "暂无待处理建议。",
    updated: "更新于",
    status: "状态"
  }
};

function getCopy(language) {
  return copy[language] || copy.zh;
}

async function readJson(response) {
  const text = await response.text();
  if (!text) {
    return {};
  }
  try {
    return JSON.parse(text);
  } catch (_) {
    return { detail: text };
  }
}

function formatDate(value) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return date.toLocaleString();
}

export default function ResearchTopicsPage({ language }) {
  const text = getCopy(language);
  const [topics, setTopics] = useState([]);
  const [selectedTopicId, setSelectedTopicId] = useState("");
  const [selectedTopic, setSelectedTopic] = useState(null);
  const [suggestions, setSuggestions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function loadTopicDetail(topicId) {
    if (!topicId) {
      setSelectedTopic(null);
      return;
    }
    const response = await fetch(`/api/research-topics/${encodeURIComponent(topicId)}`);
    const payload = await readJson(response);
    if (!response.ok) {
      throw new Error(payload.detail || `Topic detail failed (HTTP ${response.status})`);
    }
    setSelectedTopic(payload);
  }

  async function loadTopics() {
    setLoading(true);
    setError("");
    try {
      const [topicsResponse, suggestionsResponse] = await Promise.all([
        fetch("/api/research-topics"),
        fetch("/api/assistant/suggestions")
      ]);
      const topicsPayload = await readJson(topicsResponse);
      const suggestionsPayload = await readJson(suggestionsResponse);
      if (!topicsResponse.ok) {
        throw new Error(topicsPayload.detail || `Topics failed (HTTP ${topicsResponse.status})`);
      }
      if (!suggestionsResponse.ok) {
        throw new Error(suggestionsPayload.detail || `Suggestions failed (HTTP ${suggestionsResponse.status})`);
      }

      const items = Array.isArray(topicsPayload.items) ? topicsPayload.items : [];
      const pendingSuggestions = Array.isArray(suggestionsPayload.items) ? suggestionsPayload.items : [];
      const nextSelectedId = items.some((topic) => topic.topic_id === selectedTopicId)
        ? selectedTopicId
        : items[0]?.topic_id || "";

      setTopics(items);
      setSuggestions(pendingSuggestions);
      setSelectedTopicId(nextSelectedId);
      if (nextSelectedId) {
        await loadTopicDetail(nextSelectedId);
      } else {
        setSelectedTopic(null);
      }
    } catch (loadError) {
      setError(String(loadError));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadTopics();
  }, []);

  useEffect(() => {
    if (!selectedTopicId) {
      return;
    }
    void loadTopicDetail(selectedTopicId).catch((detailError) => setError(String(detailError)));
  }, [selectedTopicId]);

  const threads = Array.isArray(selectedTopic?.threads) ? selectedTopic.threads : [];
  const insights = Array.isArray(selectedTopic?.insights) ? selectedTopic.insights : [];

  return (
    <main className="research-topics-page">
      <section className="research-topics-sidebar">
        <div className="research-topics-section-head">
          <h2>{text.title}</h2>
          <button type="button" onClick={() => void loadTopics()} disabled={loading}>
            {text.refresh}
          </button>
        </div>

        {topics.length ? (
          <div className="topic-list">
            {topics.map((topic) => (
              <button
                type="button"
                key={topic.topic_id}
                className={selectedTopicId === topic.topic_id ? "topic-list-item active" : "topic-list-item"}
                onClick={() => setSelectedTopicId(topic.topic_id)}
              >
                <span>{topic.title}</span>
                <small>{(topic.keywords || []).join(", ") || formatDate(topic.updated_at)}</small>
              </button>
            ))}
          </div>
        ) : (
          <p className="muted">{text.empty}</p>
        )}
      </section>

      <section className="research-topics-main">
        {error ? <div className="warning-box">{error}</div> : null}

        <header className="research-topics-detail-head">
          <div>
            <h3>{selectedTopic?.title || text.title}</h3>
            {selectedTopic?.description ? <p className="muted">{selectedTopic.description}</p> : null}
          </div>
          {selectedTopic?.updated_at ? (
            <span className="topic-meta">
              {text.updated}: {formatDate(selectedTopic.updated_at)}
            </span>
          ) : null}
        </header>

        <section className="topic-section">
          <h4>{text.threads}</h4>
          {threads.length ? (
            threads.map((thread) => (
              <article className="topic-thread-row" key={thread.thread_id}>
                <div>
                  <strong>{thread.paper_title}</strong>
                  <p className="muted">{thread.paper_key}</p>
                </div>
                <span className="topic-meta">
                  {text.status}: {thread.status}
                </span>
              </article>
            ))
          ) : (
            <p className="muted">{text.noThreads}</p>
          )}
        </section>

        <section className="topic-section">
          <h4>{text.insights}</h4>
          {insights.length ? (
            insights.map((insight) => (
              <article className="topic-insight-row" key={insight.insight_id}>
                <strong>{insight.kind}</strong>
                <p>{insight.text}</p>
              </article>
            ))
          ) : (
            <p className="muted">{text.noInsights}</p>
          )}
        </section>

        <section className="topic-section">
          <h4>{text.suggestions}</h4>
          {suggestions.length ? (
            suggestions.map((suggestion) => (
              <article className="assistant-suggestion-card" key={suggestion.suggestion_id}>
                <strong>{suggestion.recommended_action}</strong>
                <p>{suggestion.summary}</p>
              </article>
            ))
          ) : (
            <p className="muted">{text.noSuggestions}</p>
          )}
        </section>
      </section>
    </main>
  );
}
