import { useEffect, useMemo, useRef, useState } from "react";

const translations = {
  en: {
    appTitle: "FastAPI + React Workbench",
    searchTab: "Search Workspace",
    ingestTab: "Ingest Manager",
    saveDefaults: "Save Defaults",
    defaultsSaved: "Defaults saved.",
    loading: "Loading...",
    noLogs: "No logs yet.",
    noPapers: "No papers selected yet.",
    vector: "Vector",
    rerank: "Rerank",
    method: "Method",
    provider: "Provider",
    model: "Model",
    baseUrl: "Base URL",
    apiKey: "API Key",
    storedKeyPresent: "Stored key present",
    yes: "yes",
    no: "no",
    clearStoredKey: "Clear stored key",
    keepStoredKey: "Keep stored key",
    queryChat: "Query Chat",
    answerChat: "Answer Chat",
    embedding: "Embedding",
    ollamaApiUrl: "Ollama API URL",
    embeddingModel: "Embedding Model",
    rerankRetrieval: "Rerank + Retrieval",
    rerankBaseUrl: "Rerank Base URL",
    rerankModel: "Rerank Model",
    rerankApiKey: "Rerank API Key",
    topK: "Top K",
    topN: "Top N",
    timeout: "Timeout",
    researchQuestion: "Research Question",
    questionPlaceholder: "Ask about a topic, author, category, or recent trend.",
    generateQueryPlan: "Generate Query Plan",
    working: "Working...",
    rewriteConfirmation: "Rewrite Confirmation",
    original: "Original",
    intentSummary: "Intent Summary",
    retrievalQuery: "Retrieval Query",
    keywords: "Keywords",
    timeWindow: "Time Window",
    authors: "Authors",
    categories: "Categories",
    sortHint: "Sort Hint",
    corpusLatestDate: "Corpus Latest Date",
    none: "(none)",
    useRewrite: "Use Rewrite",
    useOriginal: "Use Original",
    improvePrompt: "Tell the model what to improve",
    improvePlaceholder: "For example: narrow it to cs.IR, or focus on the latest 12 months.",
    improveRewrite: "Improve Rewrite",
    topPapers: "Top Papers",
    answerStream: "Answer Stream",
    answerPlaceholder: "The answer will stream here.",
    databaseOverview: "Database Overview",
    papers: "Papers",
    embeddings: "Embeddings",
    latestIndexedDate: "Latest Indexed Date",
    startIngest: "Start Ingest",
    status: "Status",
    idle: "idle",
    pleaseEnterQuestion: "Please enter a question.",
    failedSaveDefaults: "Failed to save defaults.",
    failedGeneratePlan: "Failed to generate a query plan.",
    failedRefinePlan: "Failed to refine the query plan.",
    failedExecuteSearch: "Failed to execute search.",
    answerStreamFailed: "Answer stream failed.",
    failedStartIngest: "Failed to start ingest.",
    optionalOllamaBaseUrl: "Optional Ollama base URL",
    openaiBaseUrl: "https://api.example.com/v1",
    keepStoredKeyPlaceholder: "Leave blank to keep the stored key",
    language: "Language",
    appliedConstraints: "Applied Constraints",
    implicitLatest: "Implicit latest window",
    publishedDate: "Published",
    primaryCategory: "Primary Category"
  },
  zh: {
    appTitle: "FastAPI + React 可视化工作台",
    searchTab: "搜索工作台",
    ingestTab: "入库管理",
    saveDefaults: "保存默认配置",
    defaultsSaved: "默认配置已保存。",
    loading: "加载中...",
    noLogs: "暂时还没有日志。",
    noPapers: "还没有选中的论文。",
    vector: "向量分",
    rerank: "重排分",
    method: "方法",
    provider: "提供方式",
    model: "模型",
    baseUrl: "接口地址",
    apiKey: "API Key",
    storedKeyPresent: "已保存密钥",
    yes: "是",
    no: "否",
    clearStoredKey: "清除已保存密钥",
    keepStoredKey: "保留已保存密钥",
    queryChat: "Query Rewrite 模型",
    answerChat: "最终回答模型",
    embedding: "Embedding",
    ollamaApiUrl: "Ollama API 地址",
    embeddingModel: "Embedding 模型",
    rerankRetrieval: "重排与检索",
    rerankBaseUrl: "重排接口地址",
    rerankModel: "重排模型",
    rerankApiKey: "重排 API Key",
    topK: "粗排 Top K",
    topN: "精排 Top N",
    timeout: "超时",
    researchQuestion: "研究问题",
    questionPlaceholder: "输入主题、作者、分类，或者“最新的 XX 研究进展”这类问题。",
    generateQueryPlan: "生成查询改写方案",
    working: "处理中...",
    rewriteConfirmation: "改写确认",
    original: "原始问题",
    intentSummary: "意图摘要",
    retrievalQuery: "检索语句",
    keywords: "关键词",
    timeWindow: "时间范围",
    authors: "作者",
    categories: "分类",
    sortHint: "排序偏好",
    corpusLatestDate: "语料库最新日期",
    none: "（无）",
    useRewrite: "使用改写结果",
    useOriginal: "直接用原句",
    improvePrompt: "告诉模型还需要怎么改",
    improvePlaceholder: "例如：限定成 cs.IR，或者更关注最近 12 个月。",
    improveRewrite: "继续优化改写",
    topPapers: "命中论文",
    answerStream: "回答流",
    answerPlaceholder: "最终回答会显示在这里。",
    databaseOverview: "数据库概览",
    papers: "论文数",
    embeddings: "向量数",
    latestIndexedDate: "最新入库日期",
    startIngest: "开始入库",
    status: "状态",
    idle: "空闲",
    pleaseEnterQuestion: "请先输入问题。",
    failedSaveDefaults: "保存默认配置失败。",
    failedGeneratePlan: "生成查询改写失败。",
    failedRefinePlan: "优化查询改写失败。",
    failedExecuteSearch: "执行搜索失败。",
    answerStreamFailed: "回答流失败。",
    failedStartIngest: "启动入库失败。",
    optionalOllamaBaseUrl: "可选的 Ollama 接口地址",
    openaiBaseUrl: "https://api.example.com/v1",
    keepStoredKeyPlaceholder: "留空表示继续使用已保存密钥",
    language: "语言",
    appliedConstraints: "实际使用的约束",
    implicitLatest: "隐式最新时间窗",
    publishedDate: "发布日期",
    primaryCategory: "主分类"
  }
};

function getInitialLanguage() {
  const saved = window.localStorage.getItem("app_language");
  if (saved === "zh" || saved === "en") {
    return saved;
  }
  return navigator.language.toLowerCase().startsWith("zh") ? "zh" : "en";
}

function buildDefaultState(config) {
  return {
    query_chat: { ...config.query_chat, api_key: "", clear_api_key: false },
    answer_chat: { ...config.answer_chat, api_key: "", clear_api_key: false },
    embedding: { ...config.embedding },
    retrieval: { ...config.retrieval },
    rerank: { ...config.rerank, api_key: "", clear_api_key: false }
  };
}

function buildRuntimeRequest(settings) {
  return {
    query_chat: {
      provider: settings.query_chat.provider,
      model: settings.query_chat.model,
      base_url: settings.query_chat.base_url || null,
      api_key: settings.query_chat.api_key || null,
      clear_api_key: settings.query_chat.clear_api_key
    },
    answer_chat: {
      provider: settings.answer_chat.provider,
      model: settings.answer_chat.model,
      base_url: settings.answer_chat.base_url || null,
      api_key: settings.answer_chat.api_key || null,
      clear_api_key: settings.answer_chat.clear_api_key
    },
    embedding: {
      api_url: settings.embedding.api_url,
      model: settings.embedding.model
    },
    retrieval: {
      top_k: Number(settings.retrieval.top_k),
      top_n: Number(settings.retrieval.top_n),
      request_timeout: Number(settings.retrieval.request_timeout)
    },
    rerank: {
      base_url: settings.rerank.base_url,
      model: settings.rerank.model,
      api_key: settings.rerank.api_key || null,
      clear_api_key: settings.rerank.clear_api_key
    }
  };
}

function buildRetrievalText(plan) {
  if (!plan) {
    return "";
  }
  if (!plan.keywords_en?.length) {
    return plan.retrieval_query_en;
  }
  return `${plan.retrieval_query_en}; keywords: ${plan.keywords_en.join(", ")}`;
}

function formatTimeWindow(constraints, t) {
  if (!constraints) {
    return t("none");
  }
  if (constraints.published_after && constraints.published_before) {
    return `${constraints.published_after} ~ ${constraints.published_before}`;
  }
  if (constraints.published_after) {
    return `>= ${constraints.published_after}`;
  }
  if (constraints.published_before) {
    return `<= ${constraints.published_before}`;
  }
  return t("none");
}

function ConstraintBlock({ constraints, corpusLatestDate, t }) {
  const authors = constraints?.authors?.length ? constraints.authors.join(", ") : t("none");
  const categories = constraints?.primary_categories?.length ? constraints.primary_categories.join(", ") : t("none");
  return (
    <div className="detail-grid">
      <div>
        <strong>{t("timeWindow")}</strong>
        <p>{formatTimeWindow(constraints, t)}</p>
      </div>
      <div>
        <strong>{t("authors")}</strong>
        <p>{authors}</p>
      </div>
      <div>
        <strong>{t("categories")}</strong>
        <p>{categories}</p>
      </div>
      <div>
        <strong>{t("sortHint")}</strong>
        <p>{constraints?.sort_hint || "relevance"}</p>
      </div>
      <div>
        <strong>{t("corpusLatestDate")}</strong>
        <p>{corpusLatestDate || t("none")}</p>
      </div>
      <div>
        <strong>{t("implicitLatest")}</strong>
        <p>{constraints?.is_implicit_latest ? t("yes") : t("no")}</p>
      </div>
    </div>
  );
}

function EventLog({ lines, t }) {
  return (
    <div className="log-panel">
      {lines.length === 0 ? <p className="muted">{t("noLogs")}</p> : null}
      {lines.map((line, index) => (
        <div key={`${index}-${line}`}>{line}</div>
      ))}
    </div>
  );
}

function PaperList({ papers, t }) {
  if (!papers.length) {
    return <p className="muted">{t("noPapers")}</p>;
  }

  return (
    <div className="paper-list">
      {papers.map((paper, index) => (
        <article key={`${paper.id}-${index}`} className="paper-card">
          <h4>
            {index + 1}. {paper.title}
          </h4>
          <p className="paper-score">
            {t("vector")}: {paper.initial_score.toFixed(4)} | {t("rerank")}: {paper.rerank_score.toFixed(4)}
          </p>
          <div className="tag-list">
            {paper.published_date ? <span className="tag">{`${t("publishedDate")}: ${paper.published_date}`}</span> : null}
            {paper.primary_category ? (
              <span className="tag">{`${t("primaryCategory")}: ${paper.primary_category}`}</span>
            ) : null}
            {paper.authors?.length ? <span className="tag">{`${t("authors")}: ${paper.authors.join(", ")}`}</span> : null}
          </div>
          <p>{paper.text}</p>
          <p className="muted">
            {t("method")}: {paper.method}
          </p>
        </article>
      ))}
    </div>
  );
}

function ChatConfigSection({ title, config, onChange, t, providerOptions, showApiKeyStatus = true }) {
  return (
    <section className="config-section">
      <h3>{title}</h3>
      <label>
        {t("provider")}
        <select value={config.provider} onChange={(event) => onChange("provider", event.target.value)}>
          {providerOptions.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("model")}
        <input value={config.model} onChange={(event) => onChange("model", event.target.value)} />
      </label>
      <label>
        {t("baseUrl")}
        <input
          value={config.base_url || ""}
          onChange={(event) => onChange("base_url", event.target.value)}
          placeholder={config.provider === "ollama" ? t("optionalOllamaBaseUrl") : t("openaiBaseUrl")}
        />
      </label>
      <label>
        {t("apiKey")}
        <input
          type="password"
          value={config.api_key || ""}
          onChange={(event) => onChange("api_key", event.target.value)}
          placeholder={t("keepStoredKeyPlaceholder")}
        />
      </label>
      {showApiKeyStatus ? (
        <p className="muted">
          {t("storedKeyPresent")}: {config.has_api_key ? t("yes") : t("no")}
        </p>
      ) : null}
      <button type="button" className="secondary" onClick={() => onChange("clear_api_key", !config.clear_api_key)}>
        {config.clear_api_key ? t("keepStoredKey") : t("clearStoredKey")}
      </button>
    </section>
  );
}

export default function App() {
  const [language, setLanguage] = useState(getInitialLanguage);
  const [activeTab, setActiveTab] = useState("search");
  const [settings, setSettings] = useState(null);
  const [question, setQuestion] = useState("");
  const [queryPlan, setQueryPlan] = useState(null);
  const [feedback, setFeedback] = useState("");
  const [papers, setPapers] = useState([]);
  const [warnings, setWarnings] = useState([]);
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [appliedConstraints, setAppliedConstraints] = useState(null);
  const [corpusLatestDate, setCorpusLatestDate] = useState(null);
  const [ingestStatus, setIngestStatus] = useState(null);
  const [ingestLogs, setIngestLogs] = useState([]);
  const answerSourceRef = useRef(null);
  const ingestSourceRef = useRef(null);

  const t = (key) => translations[language][key] ?? key;
  const providerOptions = useMemo(
    () => [
      { value: "ollama", label: "Ollama" },
      { value: "openai_compatible", label: language === "zh" ? "OpenAI 兼容 API" : "OpenAI Compatible API" }
    ],
    [language]
  );
  const runtimePayload = useMemo(() => (settings ? buildRuntimeRequest(settings) : null), [settings]);

  useEffect(() => {
    window.localStorage.setItem("app_language", language);
    document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
    document.title = language === "zh" ? "arxiv-paper-rag 工作台" : "arxiv-paper-rag Workbench";
  }, [language]);

  useEffect(() => {
    loadConfig().catch((error) => setMessage(String(error)));
    loadIngestStatus().catch((error) => setMessage(String(error)));
    return () => {
      answerSourceRef.current?.close();
      ingestSourceRef.current?.close();
    };
  }, []);

  async function loadConfig() {
    const response = await fetch("/api/config");
    const data = await response.json();
    setSettings(buildDefaultState(data));
  }

  async function loadIngestStatus() {
    const response = await fetch("/api/ingest/status");
    const data = await response.json();
    setIngestStatus(data);
    setIngestLogs(data.recent_logs || []);
    if (data.job_id && data.status === "running") {
      startIngestStream(data.job_id);
    }
  }

  function updateNested(section, key, value) {
    setSettings((current) => ({
      ...current,
      [section]: { ...current[section], [key]: value }
    }));
  }

  async function saveDefaults() {
    setMessage("");
    const response = await fetch("/api/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(runtimePayload)
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || t("failedSaveDefaults"));
    }
    setSettings(buildDefaultState(data));
    setMessage(t("defaultsSaved"));
  }

  async function requestPlan() {
    if (!question.trim()) {
      setMessage(t("pleaseEnterQuestion"));
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch("/api/search/plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, settings: runtimePayload })
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || t("failedGeneratePlan"));
      }
      setQueryPlan(data);
      setPapers([]);
      setWarnings([]);
      setAnswer("");
      setAppliedConstraints(null);
      setCorpusLatestDate(data.corpus_latest_date || null);
    } catch (error) {
      setMessage(String(error));
    } finally {
      setBusy(false);
    }
  }

  async function refinePlan() {
    if (!queryPlan || !feedback.trim()) {
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch("/api/search/plan/refine", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question,
          previous_plan: queryPlan,
          feedback,
          settings: runtimePayload
        })
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || t("failedRefinePlan"));
      }
      setQueryPlan(data);
      setFeedback("");
      setCorpusLatestDate(data.corpus_latest_date || null);
    } catch (error) {
      setMessage(String(error));
    } finally {
      setBusy(false);
    }
  }

  function streamAnswer(searchId) {
    answerSourceRef.current?.close();
    const source = new EventSource(`/api/search/${searchId}/answer/stream`);
    answerSourceRef.current = source;
    source.addEventListener("token", (event) => {
      const payload = JSON.parse(event.data);
      setAnswer((current) => current + payload.content);
    });
    source.addEventListener("complete", () => {
      source.close();
    });
    source.onerror = () => {
      source.close();
      setMessage(t("answerStreamFailed"));
    };
  }

  async function executeSearch(retrievalText, confirmedPlan) {
    setBusy(true);
    setMessage("");
    setAnswer("");
    try {
      const response = await fetch("/api/search/execute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question,
          retrieval_text: retrievalText,
          query_plan: confirmedPlan,
          settings: runtimePayload
        })
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || t("failedExecuteSearch"));
      }
      setPapers(data.papers);
      setWarnings(data.warnings || []);
      setAppliedConstraints(data.applied_constraints || null);
      setCorpusLatestDate(data.corpus_latest_date || null);
      streamAnswer(data.search_id);
    } catch (error) {
      setMessage(String(error));
    } finally {
      setBusy(false);
    }
  }

  function startIngestStream(jobId) {
    ingestSourceRef.current?.close();
    const source = new EventSource(`/api/ingest/${jobId}/logs/stream`);
    ingestSourceRef.current = source;
    source.addEventListener("log", (event) => {
      const payload = JSON.parse(event.data);
      setIngestLogs((current) => [...current, payload.line]);
    });
    source.addEventListener("status", (event) => {
      const payload = JSON.parse(event.data);
      setIngestStatus((current) => (current ? { ...current, status: payload.status } : current));
    });
    source.addEventListener("complete", (event) => {
      const payload = JSON.parse(event.data);
      setIngestStatus((current) =>
        current ? { ...current, status: payload.status, return_code: payload.return_code } : current
      );
      source.close();
      loadIngestStatus().catch((error) => setMessage(String(error)));
    });
    source.onerror = () => {
      source.close();
    };
  }

  async function startIngest() {
    setMessage("");
    const response = await fetch("/api/ingest/run", { method: "POST" });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || t("failedStartIngest"));
    }
    setIngestStatus(data);
    setIngestLogs([]);
    startIngestStream(data.job_id);
  }

  if (!settings) {
    return (
      <div className="page">
        <p>{t("loading")}</p>
      </div>
    );
  }

  return (
    <div className="page">
      <header className="hero">
        <div>
          <p className="eyebrow">arxiv-paper-rag</p>
          <h1>{t("appTitle")}</h1>
        </div>
        <div className="header-actions">
          <div className="lang-switch" aria-label={t("language")}>
            <button
              type="button"
              className={language === "en" ? "active" : "secondary"}
              onClick={() => setLanguage("en")}
            >
              EN
            </button>
            <button
              type="button"
              className={language === "zh" ? "active" : "secondary"}
              onClick={() => setLanguage("zh")}
            >
              中文
            </button>
          </div>
          <div className="tab-row">
            <button className={activeTab === "search" ? "active" : ""} onClick={() => setActiveTab("search")}>
              {t("searchTab")}
            </button>
            <button className={activeTab === "ingest" ? "active" : ""} onClick={() => setActiveTab("ingest")}>
              {t("ingestTab")}
            </button>
          </div>
        </div>
      </header>

      {message ? <div className="message">{message}</div> : null}

      <section className="settings-grid">
        <ChatConfigSection
          title={t("queryChat")}
          config={settings.query_chat}
          onChange={(key, value) => updateNested("query_chat", key, value)}
          t={t}
          providerOptions={providerOptions}
        />
        <ChatConfigSection
          title={t("answerChat")}
          config={settings.answer_chat}
          onChange={(key, value) => updateNested("answer_chat", key, value)}
          t={t}
          providerOptions={providerOptions}
        />
        <section className="config-section">
          <h3>{t("embedding")}</h3>
          <label>
            {t("ollamaApiUrl")}
            <input
              value={settings.embedding.api_url}
              onChange={(event) => updateNested("embedding", "api_url", event.target.value)}
            />
          </label>
          <label>
            {t("embeddingModel")}
            <input
              value={settings.embedding.model}
              onChange={(event) => updateNested("embedding", "model", event.target.value)}
            />
          </label>
        </section>
        <section className="config-section">
          <h3>{t("rerankRetrieval")}</h3>
          <label>
            {t("rerankBaseUrl")}
            <input
              value={settings.rerank.base_url}
              onChange={(event) => updateNested("rerank", "base_url", event.target.value)}
            />
          </label>
          <label>
            {t("rerankModel")}
            <input
              value={settings.rerank.model}
              onChange={(event) => updateNested("rerank", "model", event.target.value)}
            />
          </label>
          <label>
            {t("rerankApiKey")}
            <input
              type="password"
              value={settings.rerank.api_key || ""}
              onChange={(event) => updateNested("rerank", "api_key", event.target.value)}
              placeholder={t("keepStoredKeyPlaceholder")}
            />
          </label>
          <p className="muted">
            {t("storedKeyPresent")}: {settings.rerank.has_api_key ? t("yes") : t("no")}
          </p>
          <button
            type="button"
            className="secondary"
            onClick={() => updateNested("rerank", "clear_api_key", !settings.rerank.clear_api_key)}
          >
            {settings.rerank.clear_api_key ? t("keepStoredKey") : t("clearStoredKey")}
          </button>
          <label>
            {t("topK")}
            <input
              type="number"
              value={settings.retrieval.top_k}
              onChange={(event) => updateNested("retrieval", "top_k", event.target.value)}
            />
          </label>
          <label>
            {t("topN")}
            <input
              type="number"
              value={settings.retrieval.top_n}
              onChange={(event) => updateNested("retrieval", "top_n", event.target.value)}
            />
          </label>
          <label>
            {t("timeout")}
            <input
              type="number"
              value={settings.retrieval.request_timeout}
              onChange={(event) => updateNested("retrieval", "request_timeout", event.target.value)}
            />
          </label>
        </section>
      </section>

      <div className="toolbar">
        <button onClick={() => saveDefaults().catch((error) => setMessage(String(error)))}>{t("saveDefaults")}</button>
      </div>

      {activeTab === "search" ? (
        <section className="workspace">
          <div className="question-box">
            <label>
              {t("researchQuestion")}
              <textarea
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                rows={4}
                placeholder={t("questionPlaceholder")}
              />
            </label>
            <button onClick={requestPlan} disabled={busy}>
              {busy ? t("working") : t("generateQueryPlan")}
            </button>
          </div>
          {queryPlan ? (
            <section className="rewrite-card">
              <h3>{t("rewriteConfirmation")}</h3>
              <p>
                <strong>{t("original")}:</strong> {question}
              </p>
              <p>
                <strong>{t("intentSummary")}:</strong> {queryPlan.intent_summary}
              </p>
              <p>
                <strong>{t("retrievalQuery")}:</strong> {queryPlan.retrieval_query_en}
              </p>
              <p>
                <strong>{t("keywords")}:</strong> {queryPlan.keywords_en.join(", ") || t("none")}
              </p>
              <ConstraintBlock
                constraints={queryPlan.constraints}
                corpusLatestDate={queryPlan.corpus_latest_date}
                t={t}
              />
              <div className="action-row">
                <button onClick={() => executeSearch(buildRetrievalText(queryPlan), queryPlan)} disabled={busy}>
                  {t("useRewrite")}
                </button>
                <button className="secondary" onClick={() => executeSearch(question, queryPlan)} disabled={busy}>
                  {t("useOriginal")}
                </button>
              </div>
              <label>
                {t("improvePrompt")}
                <textarea
                  value={feedback}
                  onChange={(event) => setFeedback(event.target.value)}
                  rows={3}
                  placeholder={t("improvePlaceholder")}
                />
              </label>
              <button className="secondary" onClick={refinePlan} disabled={busy || !feedback.trim()}>
                {t("improveRewrite")}
              </button>
            </section>
          ) : null}

          {appliedConstraints ? (
            <section>
              <h3>{t("appliedConstraints")}</h3>
              <ConstraintBlock constraints={appliedConstraints} corpusLatestDate={corpusLatestDate} t={t} />
            </section>
          ) : null}

          {warnings.length ? (
            <div className="warning-box">
              {warnings.map((warning) => (
                <div key={warning}>{warning}</div>
              ))}
            </div>
          ) : null}

          <section>
            <h3>{t("topPapers")}</h3>
            <PaperList papers={papers} t={t} />
          </section>

          <section>
            <h3>{t("answerStream")}</h3>
            <div className="answer-box">{answer || <span className="muted">{t("answerPlaceholder")}</span>}</div>
          </section>
        </section>
      ) : (
        <section className="workspace">
          <div className="ingest-head">
            <div>
              <h3>{t("databaseOverview")}</h3>
              <p className="muted">
                {t("papers")}: {ingestStatus?.database_overview?.paper_count ?? "-"} | {t("embeddings")}:{" "}
                {ingestStatus?.database_overview?.embedding_count ?? "-"}
              </p>
              <p className="muted">
                {t("latestIndexedDate")}: {ingestStatus?.database_overview?.latest_published_date || t("none")}
              </p>
            </div>
            <button onClick={() => startIngest().catch((error) => setMessage(String(error)))}>
              {t("startIngest")}
            </button>
          </div>
          <p>
            {t("status")}: <strong>{ingestStatus?.status || t("idle")}</strong>
          </p>
          <EventLog lines={ingestLogs} t={t} />
        </section>
      )}
    </div>
  );
}
