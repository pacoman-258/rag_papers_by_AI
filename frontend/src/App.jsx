import { Component, useEffect, useMemo, useRef, useState } from "react";
import CitationTracePage from "./CitationTracePage.jsx";
import PaperReaderPage from "./PaperReaderPage.jsx";
import ProgressTracker from "./ProgressTracker.jsx";
import ResearchProfilePage from "./ResearchProfilePage.jsx";
import ResearchTopicsPage from "./ResearchTopicsPage.jsx";

const translations = {
  en: {
    appTitle: "FastAPI + React Workbench",
    searchTab: "Search Workspace",
    citationTraceTab: "Citation Trace",
    paperReaderTab: "Paper Reader",
    researchTopicsTab: "Research Topics",
    researchProfileTab: "Research Profile",
    ingestTab: "Ingest Manager",
    settingsTab: "Settings",
    qaMode: "QA",
    saveDefaults: "Save Defaults",
    defaultsSaved: "Defaults saved.",
    settingsTitle: "Model & Runtime Settings",
    settingsDescription: "Manage model providers, retrieval sources, API endpoints, and saved credentials.",
    loading: "Loading...",
    progressIdle: "Idle",
    progressRunning: "Running",
    progressReady: "Ready",
    progressCompleted: "Completed",
    progressInterrupted: "Interrupted",
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
    assistantChatModel: "Assistant Chat",
    paperReaderChatModel: "Paper Reader Chat",
    paperReaderTranslationModel: "PDF Selection Translation",
    citationTraceMainModel: "Citation Trace Main Model",
    citationTraceWorkerModel: "Citation Trace Worker Model",
    embedding: "Embedding",
    ollamaApiUrl: "Ollama API URL",
    embeddingModel: "Embedding Model",
    retrievalProviders: "Retrieval Providers",
    retrievalProvidersDescription: "Choose which paper sources can participate in planning, search, and trace requests.",
    localProvider: "Local",
    arxivProvider: "arXiv",
    wosProvider: "Web of Science",
    localProviderDescription: "Use the indexed local corpus.",
    arxivProviderDescription: "Query the arXiv API.",
    wosProviderDescription: "Query the Web of Science API.",
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
    retrievalSources: "Retrieval Sources",
    source: "Source",
    sourceFreshness: "Source Freshness",
    matchedSources: "Matched Sources",
    openSource: "Open Source Page",
    readPaper: "Read This Paper",
    none: "(none)",
    useRewrite: "Use Rewrite",
    useOriginal: "Use Original",
    improvePrompt: "Tell the model what to improve",
    improvePlaceholder: "For example: narrow it to cs.IR, or focus on the latest 12 months.",
    improveRewrite: "Improve Rewrite",
    topPapers: "Top Papers",
    answerStream: "Answer Stream",
    answerPlaceholder: "The answer will stream here.",
    globalSelectionTranslation: "Selection Translation",
    globalSelectionTranslationHeading: "Translation card",
    globalSelectionTranslationEmpty: "Select text on this page to translate it.",
    globalSelectionTranslationRunning: "Translating",
    selectedOriginalLabel: "Selected text",
    translationOnlyLabel: "Translation",
    translateSelectionButton: "Translate selection",
    databaseOverview: "Local Database Overview",
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
    fetchModels: "Fetch Models",
    loadingModels: "Loading models...",
    fetchedModels: "Fetched models",
    showModelList: "Show model list",
    hideModelList: "Hide model list",
    selectModel: "Select model",
    language: "Language",
    appliedConstraints: "Applied Constraints",
    implicitLatest: "Implicit latest window",
    publishedDate: "Published",
    primaryCategory: "Primary Category",
    summary: "Summary",
    workspaceProgressTitle: "Workspace Progress",
    workspaceProgressSubtitle: "Follow the current pipeline stage and whether the process is still alive.",
    qaProgressPlan: "Draft query plan",
    qaProgressReview: "Confirm rewrite",
    qaProgressSearch: "Retrieve papers",
    qaProgressAnswer: "Stream answer",
    citationTraceTitle: "Citation Trace",
    citationTraceRun: "Run Citation Trace",
    citationTraceArxivUrl: "arXiv URL",
    citationTracePdfFile: "PDF File",
    citationTraceLoadArxiv: "Load arXiv Paper",
    citationTraceLoadPdf: "Load PDF",
    citationTraceProgressTitle: "Citation Trace Progress",
    citationTraceProgressSubtitle: "Track source loading, Top 15 recall, LLM assessment, and final ranking.",
    citationTraceProgressLoad: "Load source",
    citationTraceProgressReferences: "Resolve references",
    citationTraceProgressCandidateRecall: "Recall Top 15 candidates",
    citationTraceProgressWorkerAssessment: "Analyze Top 15 candidates",
    citationTraceProgressMainRanking: "Rank final Top 5",
    citationTraceProgressRoundOne: "Recall Top 15 candidates",
    citationTraceProgressRoundTwo: "Explore related sources",
    citationTraceProgressSynthesis: "Rank final Top 5",
    citationTraceProgressTop5: "Finalize top 5",
    citationTraceCandidateTop15: "Top 15 Candidates",
    citationTraceReferenceText: "Original Reference Snippet",
    citationTraceReadyToRun: "Load a paper to start citation tracing.",
    citationTraceCompleted: "Citation trace completed.",
    citationTraceFailed: "Citation trace failed.",
    citationTraceWarning: "Warning",
    citationTraceUrlRequired: "Please enter an arXiv URL.",
    citationTraceFileRequired: "Please choose a PDF file first.",
    citationTraceNoSession: "No citation trace session yet.",
    finalTop5: "Final Top 5",
    evidenceLedger: "Evidence Ledger",
    exploratorySources: "Exploratory Sources",
    citationTraceNoTop5: "No final top 5 yet.",
    citationTraceNoExploratory: "No exploratory sources yet.",
    citationTraceNoLedger: "No evidence ledger entries yet.",
    paperReaderMaxContextTokens: "Max Context Tokens",
    paperReaderTitle: "Paper Reader",
    paperReaderDescription: "Load one arXiv paper or local PDF, then read the original PDF directly with navigation and selected-text translation.",
    paperReaderProgressTitle: "Paper Reader Progress",
    paperReaderProgressSubtitle: "Track PDF loading and page-map parsing.",
    paperReaderProgressLoad: "Load source",
    paperReaderProgressPaginate: "Build paper map and pages",
    paperReaderProgressPage: "Open PDF page",
    paperReaderProgressChat: "Ask this paper",
    paperReaderArxivUrl: "arXiv URL",
    paperReaderPdfFile: "PDF File",
    paperReaderLoadArxiv: "Load arXiv Paper",
    paperReaderLoadPdf: "Load PDF",
    paperReaderSelectedFile: "No PDF selected yet.",
    paperReaderEmpty: "Load one paper to start dynamic reading.",
    paperReaderSummary: "Reading Summary",
    paperReaderCitations: "Citations",
    paperReaderPreviousPage: "Previous Page",
    paperReaderNextPage: "Next Page",
    paperReaderPageLabel: "Page",
    paperReaderPageCount: "Pages",
    paperReaderCurrentPage: "Current Page",
    paperReaderCurrentStatus: "Status",
    paperReaderSessionId: "Session",
    paperReaderLoading: "Preparing paper reader session...",
    paperReaderLoadFail: "Failed to load the paper reader session.",
    paperReaderFetchFail: "Failed to fetch the paper reader session.",
    paperReaderPageLoadFail: "Failed to load the requested page.",
    paperReaderChatTitle: "Ask This Paper",
    paperReaderQuestionTitle: "Question",
    paperReaderQuestionPlaceholder: "Ask about this paper's assumptions, method, experiment design, or limitations.",
    paperReaderAsk: "Ask",
    paperReaderChatFail: "Failed to query the current paper.",
    paperReaderNoSession: "No paper reader session yet.",
    paperReaderNoContent: "No parsed content available yet.",
    paperReaderQueued: "Queued",
    paperReaderGenerating: "Generating",
    paperReaderReady: "Ready",
    paperReaderError: "Error",
    paperReaderInvalidUrl: "Please enter a valid arXiv URL.",
    paperReaderFileRequired: "Please choose a PDF file first."
  },
  zh: {
    appTitle: "FastAPI + React 可视化工作台",
    searchTab: "搜索工作台",
    citationTraceTab: "引用溯源",
    paperReaderTab: "论文精读",
    researchTopicsTab: "课题档案",
    researchProfileTab: "研究画像",
    ingestTab: "入库管理",
    settingsTab: "设置",
    qaMode: "QA",
    saveDefaults: "保存默认配置",
    defaultsSaved: "默认配置已保存。",
    settingsTitle: "模型与运行配置",
    settingsDescription: "统一管理模型提供方、检索来源、接口地址、检索默认值和已保存凭据。",
    loading: "加载中...",
    progressIdle: "空闲",
    progressRunning: "运行中",
    progressReady: "已就绪",
    progressCompleted: "已完成",
    progressInterrupted: "已中断",
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
    assistantChatModel: "小助手模型",
    paperReaderChatModel: "论文精读解析模型",
    paperReaderTranslationModel: "原文卡片翻译模型",
    citationTraceMainModel: "引用溯源主模型",
    citationTraceWorkerModel: "引用溯源副模型",
    embedding: "Embedding",
    ollamaApiUrl: "Ollama API 地址",
    embeddingModel: "Embedding 模型",
    retrievalProviders: "检索提供方",
    retrievalProvidersDescription: "选择哪些论文来源可以参与规划、检索和 trace 请求。",
    localProvider: "本地库",
    arxivProvider: "arXiv",
    wosProvider: "Web of Science",
    localProviderDescription: "使用已索引的本地语料库。",
    arxivProviderDescription: "查询 arXiv API。",
    wosProviderDescription: "查询 Web of Science API。",
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
    retrievalSources: "检索来源",
    source: "来源",
    sourceFreshness: "来源新鲜度",
    matchedSources: "命中来源",
    openSource: "打开来源页面",
    readPaper: "精读这篇",
    none: "（无）",
    useRewrite: "使用改写结果",
    useOriginal: "直接用原句",
    improvePrompt: "告诉模型还需要怎么改",
    improvePlaceholder: "例如：限定成 cs.IR，或者更关注最近 12 个月。",
    improveRewrite: "继续优化改写",
    topPapers: "命中论文",
    answerStream: "回答流",
    answerPlaceholder: "最终回答会显示在这里。",
    globalSelectionTranslation: "选区翻译",
    globalSelectionTranslationHeading: "翻译卡片",
    globalSelectionTranslationEmpty: "选中页面文字后可翻译。",
    globalSelectionTranslationRunning: "翻译中",
    selectedOriginalLabel: "选中文本",
    translationOnlyLabel: "译文",
    translateSelectionButton: "翻译选区",
    databaseOverview: "本地数据库概览",
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
    fetchModels: "拉取模型列表",
    loadingModels: "正在拉取模型...",
    fetchedModels: "已拉取模型",
    showModelList: "展开模型列表",
    hideModelList: "收起模型列表",
    selectModel: "选择模型",
    language: "语言",
    appliedConstraints: "实际使用的约束",
    implicitLatest: "隐式最新时间窗",
    publishedDate: "发布日期",
    primaryCategory: "主分类",
    summary: "摘要",
    workspaceProgressTitle: "工作台进度",
    workspaceProgressSubtitle: "显示当前流程走到哪一步，并用可视化状态标记进程是否仍在存活。",
    qaProgressPlan: "生成检索改写方案",
    qaProgressReview: "确认改写结果",
    qaProgressSearch: "检索候选论文",
    qaProgressAnswer: "流式生成回答",
    citationTraceTitle: "引用溯源",
    citationTraceRun: "运行引用溯源",
    citationTraceArxivUrl: "arXiv 链接",
    citationTracePdfFile: "PDF 文件",
    citationTraceLoadArxiv: "载入 arXiv 论文",
    citationTraceLoadPdf: "载入 PDF",
    citationTraceProgressTitle: "引用溯源进度",
    citationTraceProgressSubtitle: "跟踪论文载入、Top15 候选召回、LLM 评审和最终排序。",
    citationTraceProgressLoad: "载入来源",
    citationTraceProgressReferences: "解析参考文献",
    citationTraceProgressCandidateRecall: "召回 Top15 候选",
    citationTraceProgressWorkerAssessment: "分析 Top15 候选",
    citationTraceProgressMainRanking: "排序最终 Top5",
    citationTraceProgressRoundOne: "召回 Top15 候选",
    citationTraceProgressRoundTwo: "探索相关来源",
    citationTraceProgressSynthesis: "排序最终 Top5",
    citationTraceProgressTop5: "生成 Top 5",
    citationTraceCandidateTop15: "Top15 候选",
    citationTraceReferenceText: "原始参考文献片段",
    citationTraceReadyToRun: "载入一篇论文即可开始引用溯源。",
    citationTraceCompleted: "引用溯源已完成。",
    citationTraceFailed: "引用溯源失败。",
    citationTraceWarning: "提醒",
    citationTraceUrlRequired: "请先输入 arXiv 链接。",
    citationTraceFileRequired: "请先选择一个 PDF 文件。",
    citationTraceNoSession: "当前还没有引用溯源会话。",
    finalTop5: "最终 Top 5",
    evidenceLedger: "证据账本",
    exploratorySources: "探索来源",
    citationTraceNoTop5: "还没有最终 Top 5。",
    citationTraceNoExploratory: "还没有探索来源。",
    citationTraceNoLedger: "还没有证据账本记录。",
    paperReaderMaxContextTokens: "最大上下文 Token",
    paperReaderTitle: "论文精读",
    paperReaderDescription: "输入 arXiv 链接或上传本地 PDF，直接阅读原生 PDF，并使用导航与选区翻译。",
    paperReaderProgressTitle: "论文精读进度",
    paperReaderProgressSubtitle: "跟踪 PDF 载入和论文页段解析。",
    paperReaderProgressLoad: "载入论文来源",
    paperReaderProgressPaginate: "构建论文地图与分页",
    paperReaderProgressPage: "打开 PDF 页",
    paperReaderProgressChat: "围绕论文追问",
    paperReaderArxivUrl: "arXiv 链接",
    paperReaderPdfFile: "PDF 文件",
    paperReaderLoadArxiv: "载入 arXiv 论文",
    paperReaderLoadPdf: "载入 PDF",
    paperReaderSelectedFile: "尚未选择 PDF 文件。",
    paperReaderEmpty: "请先加载一篇论文开始精读。",
    paperReaderSummary: "本页精读摘要",
    paperReaderCitations: "引用依据",
    paperReaderPreviousPage: "上一页",
    paperReaderNextPage: "下一页",
    paperReaderPageLabel: "页",
    paperReaderPageCount: "总页数",
    paperReaderCurrentPage: "当前页",
    paperReaderCurrentStatus: "当前状态",
    paperReaderSessionId: "会话 ID",
    paperReaderLoading: "正在准备论文精读会话...",
    paperReaderLoadFail: "载入论文精读会话失败。",
    paperReaderFetchFail: "获取论文精读会话失败。",
    paperReaderPageLoadFail: "加载当前分页失败。",
    paperReaderChatTitle: "围绕这篇论文继续追问",
    paperReaderQuestionTitle: "问题",
    paperReaderQuestionPlaceholder: "可以继续追问这篇论文的假设、方法、实验设计或局限。",
    paperReaderAsk: "提问",
    paperReaderChatFail: "围绕当前论文追问失败。",
    paperReaderNoSession: "当前还没有论文精读会话。",
    paperReaderNoContent: "当前还没有可显示的解析内容。",
    paperReaderQueued: "排队中",
    paperReaderGenerating: "生成中",
    paperReaderReady: "已就绪",
    paperReaderError: "错误",
    paperReaderInvalidUrl: "请输入有效的 arXiv 链接。",
    paperReaderFileRequired: "请先选择一个 PDF 文件。"
  }
};

const assistantLayerCopy = {
  en: {
    title: "Assistant layer offline",
    body: "The main workspace is still available.",
    retry: "Reload Assistant"
  },
  zh: {
    title: "助手层暂时离线",
    body: "主工作台仍可正常使用。",
    retry: "重新加载助手"
  }
};

const ASSISTANT_SESSION_STORAGE_KEY = "live2d_assistant_session_id";

function getAssistantLayerCopy(language) {
  return assistantLayerCopy[language] ?? assistantLayerCopy.zh;
}

function buildEmptyModelCatalog() {
  return {
    models: [],
    loading: false,
    error: "",
    fetched: false
  };
}

function buildInitialModelCatalogs() {
  return {
    query_chat: buildEmptyModelCatalog(),
    answer_chat: buildEmptyModelCatalog(),
    assistant_chat: buildEmptyModelCatalog(),
    paper_reader_chat: buildEmptyModelCatalog(),
    paper_reader_translation: buildEmptyModelCatalog(),
    citation_trace_main_chat: buildEmptyModelCatalog(),
    citation_trace_worker_chat: buildEmptyModelCatalog(),
    embedding: buildEmptyModelCatalog()
  };
}

function formatFetchedModelsLabel(language, count) {
  return language === "zh" ? `已拉取模型：${count}` : `Fetched models: ${count}`;
}

class AssistantErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error("Assistant layer crashed", error, info);
  }

  componentDidUpdate(prevProps) {
    if (this.state.error && prevProps.resetKey !== this.props.resetKey) {
      this.setState({ error: null });
    }
  }

  handleRetry = () => {
    this.setState({ error: null });
    this.props.onRetry?.();
  };

  render() {
    if (this.state.error) {
      return this.props.renderFallback({
        error: this.state.error,
        retry: this.handleRetry
      });
    }
    return this.props.children;
  }
}

function AssistantLayerFallback({ language, onRetry, details = "" }) {
  const copy = getAssistantLayerCopy(language);
  return (
    <aside className="assistant-fallback-shell" role="status" aria-live="polite">
      <p className="assistant-fallback-title">{copy.title}</p>
      <p className="assistant-fallback-body">{copy.body}</p>
      {details ? <p className="assistant-fallback-body muted">{details}</p> : null}
      <button type="button" onClick={onRetry}>
        {copy.retry}
      </button>
    </aside>
  );
}

function AssistantLayerContent({
  AssistantComponent,
  language,
  autoReply,
  linkedContext,
  assistantSessionId,
  onAssistantSessionIdChange,
  quietSuggestionRefreshToken
}) {
  const [latestAutoContext, setLatestAutoContext] = useState({
    answerContext: null,
    workflowContext: null
  });

  useEffect(() => {
    const trimmed = String(linkedContext?.answerContext || "").trim();
    const workflowContext =
      linkedContext?.workflowContext && typeof linkedContext.workflowContext === "object" && !Array.isArray(linkedContext.workflowContext)
        ? linkedContext.workflowContext
        : null;
    if (!trimmed && !workflowContext) {
      return;
    }
    setLatestAutoContext({
      answerContext: trimmed || null,
      workflowContext
    });
  }, [linkedContext]);

  useEffect(() => {
    const trimmed = String(autoReply?.answerContext || "").trim();
    const workflowContext =
      autoReply?.workflowContext && typeof autoReply.workflowContext === "object" && !Array.isArray(autoReply.workflowContext)
        ? autoReply.workflowContext
        : null;
    if (!trimmed && !workflowContext) {
      return;
    }
    setLatestAutoContext({
      answerContext: trimmed || null,
      workflowContext
    });
  }, [autoReply]);

  return (
    <AssistantComponent
      language={language}
      autoReply={autoReply}
      latestAnswerContext={latestAutoContext.answerContext}
      latestWorkflowContext={latestAutoContext.workflowContext}
      assistantSessionId={assistantSessionId}
      onAssistantSessionIdChange={onAssistantSessionIdChange}
      quietSuggestionRefreshToken={quietSuggestionRefreshToken}
      onClearAnswerContext={() =>
        setLatestAutoContext({
          answerContext: null,
          workflowContext: null
        })
      }
    />
  );
}

function IsolatedAssistantLayer({
  language,
  autoReply,
  linkedContext,
  assistantSessionId,
  onAssistantSessionIdChange,
  quietSuggestionRefreshToken
}) {
  const [instanceKey, setInstanceKey] = useState(0);
  const [AssistantComponent, setAssistantComponent] = useState(null);
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setAssistantComponent(null);
    setLoadError("");
    import("./Live2DAssistant.jsx")
      .then((module) => {
        if (!cancelled) {
          setAssistantComponent(() => module.default);
        }
      })
      .catch((error) => {
        console.error("Assistant module load failed", error);
        if (!cancelled) {
          setLoadError(String(error));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [instanceKey]);

  if (loadError) {
    return (
      <AssistantLayerFallback
        language={language}
        onRetry={() => setInstanceKey((current) => current + 1)}
        details={loadError}
      />
    );
  }

  if (!AssistantComponent) {
    return null;
  }

  try {
    return (
      <AssistantErrorBoundary
        resetKey={`${language}-${instanceKey}-${autoReply?.id || "idle"}`}
        onRetry={() => setInstanceKey((current) => current + 1)}
        renderFallback={({ retry, error }) => (
          <AssistantLayerFallback language={language} onRetry={retry} details={String(error || "")} />
        )}
      >
        <AssistantLayerContent
          key={instanceKey}
          AssistantComponent={AssistantComponent}
          language={language}
          autoReply={autoReply}
          linkedContext={linkedContext}
          assistantSessionId={assistantSessionId}
          onAssistantSessionIdChange={onAssistantSessionIdChange}
          quietSuggestionRefreshToken={quietSuggestionRefreshToken}
        />
      </AssistantErrorBoundary>
    );
  } catch (error) {
    console.error("Assistant portal render failed", error);
    return (
      <AssistantLayerFallback
        language={language}
        onRetry={() => setInstanceKey((current) => current + 1)}
        details={String(error)}
      />
    );
  }
}

function getInitialLanguage() {
  const saved = window.localStorage.getItem("app_language");
  if (saved === "zh" || saved === "en") {
    return saved;
  }
  return navigator.language.toLowerCase().startsWith("zh") ? "zh" : "en";
}

function buildDefaultState(config) {
  const assistantConfig = config.assistant_chat || config.answer_chat;
  const translationConfig = config.paper_reader_translation || config.paper_reader_chat;
  const citationTraceMainConfig = config.citation_trace_main_chat || config.answer_chat;
  const citationTraceWorkerConfig = config.citation_trace_worker_chat || config.paper_reader_chat;
  return {
    query_chat: { ...config.query_chat, api_key: "", clear_api_key: false },
    answer_chat: { ...config.answer_chat, api_key: "", clear_api_key: false },
    assistant_chat: { ...assistantConfig, api_key: "", clear_api_key: false },
    paper_reader_chat: { ...config.paper_reader_chat, api_key: "", clear_api_key: false },
    paper_reader_translation: { ...translationConfig, api_key: "", clear_api_key: false },
    citation_trace_main_chat: { ...citationTraceMainConfig, api_key: "", clear_api_key: false },
    citation_trace_worker_chat: { ...citationTraceWorkerConfig, api_key: "", clear_api_key: false },
    embedding: { ...config.embedding },
    retrieval: {
      ...config.retrieval,
      providers: {
        local: config.retrieval?.providers?.local ?? true,
        arxiv: config.retrieval?.providers?.arxiv ?? true,
        wos: config.retrieval?.providers?.wos ?? false
      }
    },
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
    assistant_chat: {
      provider: settings.assistant_chat.provider,
      model: settings.assistant_chat.model,
      base_url: settings.assistant_chat.base_url || null,
      api_key: settings.assistant_chat.api_key || null,
      clear_api_key: settings.assistant_chat.clear_api_key
    },
    paper_reader_chat: {
      provider: settings.paper_reader_chat.provider,
      model: settings.paper_reader_chat.model,
      base_url: settings.paper_reader_chat.base_url || null,
      api_key: settings.paper_reader_chat.api_key || null,
      clear_api_key: settings.paper_reader_chat.clear_api_key,
      max_context_tokens: Number(settings.paper_reader_chat.max_context_tokens)
    },
    paper_reader_translation: {
      provider: settings.paper_reader_translation.provider,
      model: settings.paper_reader_translation.model,
      base_url: settings.paper_reader_translation.base_url || null,
      api_key: settings.paper_reader_translation.api_key || null,
      clear_api_key: settings.paper_reader_translation.clear_api_key
    },
    citation_trace_main_chat: {
      provider: settings.citation_trace_main_chat.provider,
      model: settings.citation_trace_main_chat.model,
      base_url: settings.citation_trace_main_chat.base_url || null,
      api_key: settings.citation_trace_main_chat.api_key || null,
      clear_api_key: settings.citation_trace_main_chat.clear_api_key
    },
    citation_trace_worker_chat: {
      provider: settings.citation_trace_worker_chat.provider,
      model: settings.citation_trace_worker_chat.model,
      base_url: settings.citation_trace_worker_chat.base_url || null,
      api_key: settings.citation_trace_worker_chat.api_key || null,
      clear_api_key: settings.citation_trace_worker_chat.clear_api_key
    },
    embedding: {
      api_url: settings.embedding.api_url,
      model: settings.embedding.model
    },
    retrieval: {
      top_k: Number(settings.retrieval.top_k),
      top_n: Number(settings.retrieval.top_n),
      request_timeout: Number(settings.retrieval.request_timeout),
      providers: {
        local: Boolean(settings.retrieval.providers?.local),
        arxiv: Boolean(settings.retrieval.providers?.arxiv),
        wos: Boolean(settings.retrieval.providers?.wos)
      }
    },
    rerank: {
      base_url: settings.rerank.base_url,
      model: settings.rerank.model,
      api_key: settings.rerank.api_key || null,
      clear_api_key: settings.rerank.clear_api_key
    }
  };
}

function readJsonWithDetailFallback(response) {
  return response.text().then((text) => {
    if (!text) {
      return {};
    }
    try {
      return JSON.parse(text);
    } catch (_) {
      return { detail: text };
    }
  });
}

function firstNonEmpty(...values) {
  for (const value of values) {
    const text = String(value ?? "").trim();
    if (text) {
      return text;
    }
  }
  return "";
}

function clipDisplayText(text, maxLength = 520) {
  const normalized = String(text || "").replace(/\s+/g, " ").trim();
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, maxLength).trim()}...`;
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

function trimAssistantAnswerContext(text) {
  const value = String(text || "").trim();
  if (!value) {
    return null;
  }
  if (value.length <= 4000) {
    return value;
  }
  return `${value.slice(0, 4000).trimEnd()}...`;
}

function createAssistantSessionId() {
  if (typeof window !== "undefined" && window.crypto?.randomUUID) {
    return `sess-${window.crypto.randomUUID()}`;
  }
  return `sess-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
}

function getOrCreateAssistantSessionId() {
  if (typeof window === "undefined") {
    return createAssistantSessionId();
  }
  const saved = String(window.localStorage.getItem(ASSISTANT_SESSION_STORAGE_KEY) || "").trim();
  if (saved) {
    return saved;
  }
  const generated = createAssistantSessionId();
  window.localStorage.setItem(ASSISTANT_SESSION_STORAGE_KEY, generated);
  return generated;
}

function normalizeAssistantPaperRefs(papers) {
  const list = Array.isArray(papers) ? papers : [];
  return {
    paper_ids: list.map((paper) => String(paper?.id || "").trim()).filter(Boolean),
    paper_titles: list.map((paper) => String(paper?.title || "").trim()).filter(Boolean)
  };
}

function buildQaWorkflowContext({
  question,
  retrievalText,
  answerText,
  answerLanguage,
  papers,
  appliedConstraints,
  corpusLatestDate,
  searchId,
  retrievalSources,
  sourceFreshness
}) {
  const { paper_ids, paper_titles } = normalizeAssistantPaperRefs(papers);
  return {
    kind: "qa",
    answer_language: answerLanguage || null,
    query: String(question || "").trim(),
    answer_text: trimAssistantAnswerContext(answerText),
    paper_ids,
    paper_titles,
    applied_constraints: appliedConstraints || null,
    metadata: {
      retrieval_text: String(retrievalText || "").trim() || null,
      corpus_latest_date: corpusLatestDate || null,
      search_id: searchId || null,
      retrieval_sources: Array.isArray(retrievalSources) ? retrievalSources : [],
      source_freshness: sourceFreshness || {}
    }
  };
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

function ConstraintBlock({ constraints, corpusLatestDate, retrievalSources, sourceFreshness, t }) {
  const authors = constraints?.authors?.length ? constraints.authors.join(", ") : t("none");
  const categories = constraints?.primary_categories?.length ? constraints.primary_categories.join(", ") : t("none");
  const sources = retrievalSources?.length ? retrievalSources.join(", ") : t("none");
  const freshnessEntries = sourceFreshness
    ? Object.entries(sourceFreshness)
        .filter(([, value]) => Boolean(value))
        .map(([key, value]) => `${key}: ${value}`)
    : [];
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
      <div>
        <strong>{t("retrievalSources")}</strong>
        <p>{sources}</p>
      </div>
      <div>
        <strong>{t("sourceFreshness")}</strong>
        <p>{freshnessEntries.length ? freshnessEntries.join(" | ") : t("none")}</p>
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

function buildPaperReaderUrl(paper) {
  if (paper?.external_url && /arxiv\.org\/(abs|pdf)\//i.test(paper.external_url)) {
    return paper.external_url;
  }
  if (paper?.arxiv_id) {
    return `https://arxiv.org/abs/${String(paper.arxiv_id).replace(/^arxiv:/i, "")}`;
  }
  return "";
}

function PaperList({ papers, t, onReadPaper }) {
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
            {paper.source ? <span className="tag">{`${t("source")}: ${paper.source}`}</span> : null}
            {paper.matched_sources?.length ? <span className="tag">{`${t("matchedSources")}: ${paper.matched_sources.join(", ")}`}</span> : null}
            {paper.published_date ? <span className="tag">{`${t("publishedDate")}: ${paper.published_date}`}</span> : null}
            {paper.primary_category ? <span className="tag">{`${t("primaryCategory")}: ${paper.primary_category}`}</span> : null}
            {paper.authors?.length ? <span className="tag">{`${t("authors")}: ${paper.authors.join(", ")}`}</span> : null}
          </div>
          <p>{paper.text}</p>
          <p className="muted">
            {t("method")}: {paper.method}
          </p>
          {paper.external_url ? (
            <p className="paper-card-actions">
              <a href={paper.external_url} target="_blank" rel="noreferrer">
                {t("openSource")}
              </a>
              {buildPaperReaderUrl(paper) ? (
                <button type="button" className="secondary" onClick={() => onReadPaper?.(buildPaperReaderUrl(paper))}>
                  {t("readPaper")}
                </button>
              ) : null}
            </p>
          ) : buildPaperReaderUrl(paper) ? (
            <p className="paper-card-actions">
              <button type="button" className="secondary" onClick={() => onReadPaper?.(buildPaperReaderUrl(paper))}>
                {t("readPaper")}
              </button>
            </p>
          ) : null}
        </article>
      ))}
    </div>
  );
}

function ModelSelectorField({ listId, value, onChange, models, loading, error, onFetch, t, language }) {
  const [expanded, setExpanded] = useState(false);
  const hasModels = models.length > 0;

  useEffect(() => {
    if (!hasModels) {
      setExpanded(false);
    }
  }, [hasModels]);

  function selectModel(model) {
    onChange(model);
    setExpanded(false);
  }

  return (
    <div className="model-selector-group">
      <label>
        {t("model")}
        <input list={listId} value={value} onChange={(event) => onChange(event.target.value)} />
      </label>
      <datalist id={listId}>
        {models.map((model) => (
          <option key={model} value={model} />
        ))}
      </datalist>
      <div className="field-action-row">
        <button type="button" className="secondary" onClick={onFetch} disabled={loading}>
          {loading ? t("loadingModels") : t("fetchModels")}
        </button>
        {hasModels ? (
          <button
            type="button"
            className="secondary model-list-toggle"
            onClick={() => setExpanded((current) => !current)}
            aria-expanded={expanded}
            aria-controls={`${listId}-model-list`}
          >
            {expanded ? t("hideModelList") : t("showModelList")}
          </button>
        ) : null}
        {hasModels ? <span className="muted">{formatFetchedModelsLabel(language, models.length)}</span> : null}
      </div>
      {hasModels && expanded ? (
        <div id={`${listId}-model-list`} className="model-option-list" role="listbox" aria-label={t("fetchedModels")}>
          {models.map((model) => (
            <button
              key={model}
              type="button"
              className={`model-option${model === value ? " active" : ""}`}
              onClick={() => selectModel(model)}
              role="option"
              aria-selected={model === value}
              title={model}
            >
              <span>{model}</span>
              <small>{t("selectModel")}</small>
            </button>
          ))}
        </div>
      ) : null}
      {error ? <p className="field-error">{error}</p> : null}
    </div>
  );
}

function ChatConfigSection({
  title,
  config,
  onChange,
  t,
  language,
  providerOptions,
  modelCatalog,
  onFetchModels,
  modelListId,
  showApiKeyStatus = true,
  children = null
}) {
  const usesGoogleTranslate = config.provider === "google_translate";

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
      {usesGoogleTranslate ? null : (
        <>
          <ModelSelectorField
            listId={modelListId}
            value={config.model}
            onChange={(value) => onChange("model", value)}
            models={modelCatalog.models}
            loading={modelCatalog.loading}
            error={modelCatalog.error}
            onFetch={onFetchModels}
            t={t}
            language={language}
          />
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
        </>
      )}
      {children}
    </section>
  );
}

function GlobalSelectionTranslationPanel({ selection, translationState, t, onTranslate }) {
  const hasSelection = Boolean(selection?.text);
  const translating = translationState.status === "running";
  const translatedText = translationState.translation || "";

  return (
    <section className="workspace paper-reader-selection-card global-selection-translation-card">
      <div className="reader-selection-card-head">
        <p className="eyebrow">{t("globalSelectionTranslation")}</p>
        <h3>{t("globalSelectionTranslationHeading")}</h3>
      </div>
      {hasSelection ? (
        <div className="reader-selected-excerpt">
          <span className="reader-tone-label">{t("selectedOriginalLabel")}</span>
          <p>{clipDisplayText(selection.text)}</p>
        </div>
      ) : (
        <p className="muted">{t("globalSelectionTranslationEmpty")}</p>
      )}
      {translationState.error ? <div className="warning-box">{translationState.error}</div> : null}
      {translating ? (
        <div className="reader-loading-state reader-selection-loading">
          <span className="progress-liveness progress-liveness-running">
            <span className="progress-liveness-dot" aria-hidden="true" />
            <span>{t("globalSelectionTranslationRunning")}</span>
          </span>
        </div>
      ) : null}
      {translatedText ? (
        <div className="reader-selection-translation">
          <span className="reader-tone-label">{t("translationOnlyLabel")}</span>
          <p>{translatedText}</p>
        </div>
      ) : null}
      <div className="reader-selection-actions">
        <button type="button" onClick={onTranslate} disabled={!hasSelection || translating}>
          {translating ? t("globalSelectionTranslationRunning") : t("translateSelectionButton")}
        </button>
      </div>
    </section>
  );
}

function RetrievalProviderSection({ providers, onChange, t }) {
  const providerItems = [
    {
      key: "local",
      label: t("localProvider"),
      description: t("localProviderDescription")
    },
    {
      key: "arxiv",
      label: t("arxivProvider"),
      description: t("arxivProviderDescription")
    },
    {
      key: "wos",
      label: t("wosProvider"),
      description: t("wosProviderDescription")
    }
  ];

  return (
    <section className="config-section">
      <h3>{t("retrievalProviders")}</h3>
      <p className="muted">{t("retrievalProvidersDescription")}</p>
      <div className="provider-toggle-grid">
        {providerItems.map((item) => (
          <label key={item.key} className="provider-toggle-item">
            <span className="provider-toggle-row">
              <input
                type="checkbox"
                checked={Boolean(providers?.[item.key])}
                onChange={(event) =>
                  onChange("providers", {
                    ...(providers || {}),
                    [item.key]: event.target.checked
                  })
                }
              />
              <span className="provider-toggle-title">{item.label}</span>
            </span>
            <span className="muted">{item.description}</span>
          </label>
        ))}
      </div>
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
  const [assistantAutoReply, setAssistantAutoReply] = useState(null);
  const [assistantLinkedContext, setAssistantLinkedContext] = useState({
    answerContext: null,
    workflowContext: null
  });
  const [suggestionRefreshToken, setSuggestionRefreshToken] = useState(0);
  const [assistantSessionId, setAssistantSessionId] = useState(getOrCreateAssistantSessionId);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [workspaceProgress, setWorkspaceProgress] = useState({
    step: "plan",
    status: "idle",
    detail: "",
    updatedAt: null
  });
  const [modelCatalogs, setModelCatalogs] = useState(buildInitialModelCatalogs);
  const [appliedConstraints, setAppliedConstraints] = useState(null);
  const [corpusLatestDate, setCorpusLatestDate] = useState(null);
  const [retrievalSources, setRetrievalSources] = useState([]);
  const [sourceFreshness, setSourceFreshness] = useState({});
  const [ingestStatus, setIngestStatus] = useState(null);
  const [ingestLogs, setIngestLogs] = useState([]);
  const [pendingPaperReaderUrl, setPendingPaperReaderUrl] = useState("");
  const [globalSelection, setGlobalSelection] = useState({ text: "" });
  const [globalSelectionTranslation, setGlobalSelectionTranslation] = useState({
    status: "idle",
    sourceText: "",
    translation: "",
    error: ""
  });
  const answerSourceRef = useRef(null);
  const answerBufferRef = useRef("");
  const ingestSourceRef = useRef(null);
  const globalSelectionRequestRef = useRef(0);

  const t = (key) => translations[language][key] ?? key;
  const providerOptions = useMemo(
    () => [
      { value: "ollama", label: "Ollama" },
      { value: "openai_compatible", label: language === "zh" ? "OpenAI 兼容 API" : "OpenAI Compatible API" }
    ],
    [language]
  );
  const translationProviderOptions = useMemo(
    () => [
      ...providerOptions,
      { value: "google_translate", label: language === "zh" ? "Google 翻译" : "Google Translate" }
    ],
    [language, providerOptions]
  );
  const runtimePayload = useMemo(() => (settings ? buildRuntimeRequest(settings) : null), [settings]);
  const workspaceProgressSteps = useMemo(() => {
    return [
      { key: "plan", label: t("qaProgressPlan") },
      { key: "review", label: t("qaProgressReview") },
      { key: "search", label: t("qaProgressSearch") },
      { key: "answer", label: t("qaProgressAnswer") }
    ];
  }, [t]);
  const progressStatusLabels = useMemo(
    () => ({
      idle: t("progressIdle"),
      running: t("progressRunning"),
      ready: t("progressReady"),
      completed: t("progressCompleted"),
      interrupted: t("progressInterrupted")
    }),
    [t]
  );

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

  useEffect(() => {
    if (activeTab === "paper_reader") {
      setGlobalSelection({ text: "" });
      setGlobalSelectionTranslation({ status: "idle", sourceText: "", translation: "", error: "" });
      return undefined;
    }

    function selectionStartsInEditable(selection) {
      const node = selection?.anchorNode;
      const element = node?.nodeType === Node.ELEMENT_NODE ? node : node?.parentElement;
      return Boolean(element?.closest?.("input, textarea, select, [contenteditable='true']"));
    }

    function captureGlobalSelection() {
      const selection = window.getSelection?.();
      const text = String(selection?.toString?.() || "").replace(/\s+/g, " ").trim();
      if (!text || selectionStartsInEditable(selection)) {
        return;
      }
      if (globalSelection.text === text) {
        return;
      }
      setGlobalSelection({ text });
      setGlobalSelectionTranslation({ status: "idle", sourceText: text, translation: "", error: "" });
    }

    document.addEventListener("selectionchange", captureGlobalSelection);
    window.addEventListener("mouseup", captureGlobalSelection);
    window.addEventListener("keyup", captureGlobalSelection);
    return () => {
      document.removeEventListener("selectionchange", captureGlobalSelection);
      window.removeEventListener("mouseup", captureGlobalSelection);
      window.removeEventListener("keyup", captureGlobalSelection);
    };
  }, [activeTab, globalSelection.text]);

  function updateWorkspaceProgress(step, status, detail = "") {
    setWorkspaceProgress({
      step,
      status,
      detail,
      updatedAt: new Date().toISOString()
    });
  }

  async function loadConfig() {
    const response = await fetch("/api/config");
    const data = await readJsonWithDetailFallback(response);
    if (!response.ok) {
      throw new Error(data.detail || `HTTP ${response.status}`);
    }
    setSettings(buildDefaultState(data));
    setModelCatalogs(buildInitialModelCatalogs());
  }

  async function loadIngestStatus() {
    const response = await fetch("/api/ingest/status");
    const data = await readJsonWithDetailFallback(response);
    if (!response.ok) {
      throw new Error(data.detail || `HTTP ${response.status}`);
    }
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
    if (
      (section === "query_chat" ||
        section === "answer_chat" ||
        section === "assistant_chat" ||
        section === "paper_reader_chat" ||
        section === "paper_reader_translation" ||
        section === "citation_trace_main_chat" ||
        section === "citation_trace_worker_chat") &&
      ["provider", "base_url", "api_key", "clear_api_key"].includes(key)
    ) {
      setModelCatalogs((current) => ({
        ...current,
        [section]: buildEmptyModelCatalog()
      }));
    }
    if (section === "embedding" && key === "api_url") {
      setModelCatalogs((current) => ({
        ...current,
        embedding: buildEmptyModelCatalog()
      }));
    }
  }

  function resetSearchOutputs() {
    setPapers([]);
    setWarnings([]);
    setAnswer("");
    setAppliedConstraints(null);
    setCorpusLatestDate(null);
    setRetrievalSources([]);
    setSourceFreshness({});
    answerBufferRef.current = "";
    answerSourceRef.current?.close();
  }

  function setAssistantSessionIdWithPersistence(nextSessionId) {
    const trimmed = String(nextSessionId || "").trim();
    if (!trimmed) {
      return;
    }
    setAssistantSessionId(trimmed);
    window.localStorage.setItem(ASSISTANT_SESSION_STORAGE_KEY, trimmed);
  }

  function scheduleAssistantAutoReply({ source, answerContext, workflowContext = null }) {
    const trimmed = trimAssistantAnswerContext(answerContext);
    if (!trimmed) {
      return;
    }
    setAssistantLinkedContext({
      answerContext: trimmed,
      workflowContext
    });
    setAssistantAutoReply({
      id: `${source}-${Date.now()}`,
      source,
      answerContext: trimmed,
      workflowContext
    });
  }

  function scheduleCitationTraceAssistantAutoReply(payload) {
    scheduleAssistantAutoReply({
      source: "citation_trace_auto",
      answerContext: payload?.answerContext,
      workflowContext: payload?.workflowContext || null
    });
  }

  function updateAssistantLinkedContext(context) {
    const trimmed = trimAssistantAnswerContext(context?.answerContext);
    const workflowContext =
      context?.workflowContext && typeof context.workflowContext === "object" && !Array.isArray(context.workflowContext)
        ? context.workflowContext
        : null;
    setAssistantLinkedContext({
      answerContext: trimmed || null,
      workflowContext
    });
  }

  function refreshQuietSuggestions() {
    setSuggestionRefreshToken(Date.now());
  }

  function renderAssistantLayer() {
    return (
      <IsolatedAssistantLayer
        language={language}
        autoReply={assistantAutoReply}
        linkedContext={assistantLinkedContext}
        assistantSessionId={assistantSessionId}
        onAssistantSessionIdChange={setAssistantSessionIdWithPersistence}
        quietSuggestionRefreshToken={suggestionRefreshToken}
      />
    );
  }

  async function saveDefaults() {
    setMessage("");
    const response = await fetch("/api/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(runtimePayload)
    });
    const data = await readJsonWithDetailFallback(response);
    if (!response.ok) {
      throw new Error(data.detail || t("failedSaveDefaults"));
    }
    setSettings(buildDefaultState(data));
    setModelCatalogs(buildInitialModelCatalogs());
    setMessage(t("defaultsSaved"));
  }

  function buildModelListPayload(section) {
    if (section === "embedding") {
      return {
        provider: "ollama",
        base_url: settings.embedding.api_url || null,
        api_key: null,
        clear_api_key: false,
        kind: "embedding"
      };
    }

    return {
      provider: settings[section].provider,
      base_url: settings[section].base_url || null,
      api_key: settings[section].api_key || null,
      clear_api_key: settings[section].clear_api_key,
      kind: "chat"
    };
  }

  async function fetchAvailableModels(section) {
    setModelCatalogs((current) => ({
      ...current,
      [section]: {
        ...current[section],
        loading: true,
        error: ""
      }
    }));

    try {
      const response = await fetch("/api/models/list", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildModelListPayload(section))
      });
      const data = await readJsonWithDetailFallback(response);
      if (!response.ok) {
        throw new Error(data.detail || `HTTP ${response.status}`);
      }
      setModelCatalogs((current) => ({
        ...current,
        [section]: {
          models: Array.isArray(data.models) ? data.models : [],
          loading: false,
          error: "",
          fetched: true
        }
      }));
    } catch (error) {
      setModelCatalogs((current) => ({
        ...current,
        [section]: {
          ...current[section],
          loading: false,
          error: String(error),
          fetched: false
        }
      }));
    }
  }

  async function requestPlan() {
    if (!question.trim()) {
      setMessage(t("pleaseEnterQuestion"));
      return;
    }
    setBusy(true);
    setMessage("");
    updateWorkspaceProgress("plan", "running", t("qaProgressPlan"));
    try {
      const response = await fetch("/api/search/plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, settings: runtimePayload })
      });
      const data = await readJsonWithDetailFallback(response);
      if (!response.ok) {
        throw new Error(data.detail || t("failedGeneratePlan"));
      }
      setQueryPlan(data);
      resetSearchOutputs();
      setCorpusLatestDate(data.corpus_latest_date || null);
      updateWorkspaceProgress("review", "ready", t("qaProgressReview"));
    } catch (error) {
      setMessage(String(error));
      updateWorkspaceProgress("plan", "interrupted", String(error));
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
    updateWorkspaceProgress("plan", "running", t("qaProgressPlan"));
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
      const data = await readJsonWithDetailFallback(response);
      if (!response.ok) {
        throw new Error(data.detail || t("failedRefinePlan"));
      }
      setQueryPlan(data);
      setFeedback("");
      setCorpusLatestDate(data.corpus_latest_date || null);
      updateWorkspaceProgress("review", "ready", t("qaProgressReview"));
    } catch (error) {
      setMessage(String(error));
      updateWorkspaceProgress("plan", "interrupted", String(error));
    } finally {
      setBusy(false);
    }
  }

  function streamFrom(path, autoReplySource, buildWorkflowContext) {
    answerSourceRef.current?.close();
    answerBufferRef.current = "";
    updateWorkspaceProgress("answer", "running", t("qaProgressAnswer"));
    const source = new EventSource(path);
    answerSourceRef.current = source;
    source.onopen = () => {
      updateWorkspaceProgress("answer", "running", t("qaProgressAnswer"));
    };
    source.addEventListener("token", (event) => {
      const payload = JSON.parse(event.data);
      answerBufferRef.current += payload.content;
      setAnswer(answerBufferRef.current);
    });
    source.addEventListener("complete", () => {
      if (autoReplySource) {
        let workflowContext = null;
        if (typeof buildWorkflowContext === "function") {
          try {
            workflowContext = buildWorkflowContext(answerBufferRef.current);
          } catch (_) {
            workflowContext = null;
          }
        }
        scheduleAssistantAutoReply({
          source: autoReplySource,
          answerContext: answerBufferRef.current,
          workflowContext
        });
      }
      updateWorkspaceProgress("answer", "completed", t("qaProgressAnswer"));
      source.close();
    });
    source.onerror = () => {
      source.close();
      setMessage(t("answerStreamFailed"));
      updateWorkspaceProgress("answer", "interrupted", t("answerStreamFailed"));
    };
  }

  async function createSearchSuggestionCards({ query, papers }) {
    const topPapers = (Array.isArray(papers) ? papers : []).slice(0, 3);
    if (!topPapers.length) {
      return;
    }
    try {
      await Promise.all(
        topPapers.map(async (paper) => {
          const response = await fetch("/api/assistant/suggestions/search", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              query,
              paper,
              topic_candidates: []
            })
          });
          const payload = await readJsonWithDetailFallback(response);
          if (!response.ok) {
            throw new Error(payload.detail || `Suggestion failed (HTTP ${response.status})`);
          }
        })
      );
      refreshQuietSuggestions();
    } catch (error) {
      console.warn("Search suggestion cards failed", error);
    }
  }

  async function executeSearch(retrievalText, confirmedPlan) {
    setBusy(true);
    setMessage("");
    setAnswer("");
    updateWorkspaceProgress("search", "running", t("qaProgressSearch"));
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
      const data = await readJsonWithDetailFallback(response);
      if (!response.ok) {
        throw new Error(data.detail || t("failedExecuteSearch"));
      }
      setPapers(data.papers);
      setWarnings(data.warnings || []);
      setAppliedConstraints(data.applied_constraints || null);
      setCorpusLatestDate(data.corpus_latest_date || null);
      setRetrievalSources(data.retrieval_sources || []);
      setSourceFreshness(data.source_freshness || {});
      void createSearchSuggestionCards({
        query: question,
        papers: data.papers
      });
      streamFrom(
        `/api/search/${data.search_id}/answer/stream`,
        "qa_auto",
        (answerText) =>
          buildQaWorkflowContext({
            question,
            retrievalText,
            answerText,
            answerLanguage: language,
            papers: data.papers,
            appliedConstraints: data.applied_constraints || null,
            corpusLatestDate: data.corpus_latest_date || null,
            searchId: data.search_id,
            retrievalSources: data.retrieval_sources || [],
            sourceFreshness: data.source_freshness || {}
          })
      );
    } catch (error) {
      setMessage(String(error));
      updateWorkspaceProgress("search", "interrupted", String(error));
    } finally {
      setBusy(false);
    }
  }

  function openPaperReaderFromSearch(url) {
    const resolvedUrl = String(url || "").trim();
    if (!resolvedUrl) {
      return;
    }
    setPendingPaperReaderUrl(resolvedUrl);
    setActiveTab("paper_reader");
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
    const data = await readJsonWithDetailFallback(response);
    if (!response.ok) {
      throw new Error(data.detail || t("failedStartIngest"));
    }
    setIngestStatus(data);
    setIngestLogs([]);
    startIngestStream(data.job_id);
  }

  async function translateGlobalSelection() {
    const sourceText = String(globalSelection.text || "").trim();
    if (!sourceText || globalSelectionTranslation.status === "running") {
      return;
    }
    globalSelectionRequestRef.current += 1;
    const requestId = globalSelectionRequestRef.current;
    setGlobalSelectionTranslation({
      status: "running",
      sourceText,
      translation: "",
      error: ""
    });
    try {
      const response = await fetch("/api/translate-selection", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: sourceText,
          answer_language: language,
          settings: runtimePayload
        })
      });
      const payload = await readJsonWithDetailFallback(response);
      if (!response.ok) {
        throw new Error(payload.detail || `${t("globalSelectionTranslationRunning")} (HTTP ${response.status})`);
      }
      if (requestId !== globalSelectionRequestRef.current) {
        return;
      }
      setGlobalSelectionTranslation({
        status: "ready",
        sourceText: firstNonEmpty(payload.source_text, payload.sourceText, sourceText),
        translation: firstNonEmpty(payload.translation, payload.text),
        error: ""
      });
    } catch (error) {
      if (requestId !== globalSelectionRequestRef.current) {
        return;
      }
      setGlobalSelectionTranslation({
        status: "error",
        sourceText,
        translation: "",
        error: String(error)
      });
    }
  }

  if (!settings) {
    return (
      <div className="page">
        <p>{t("loading")}</p>
      </div>
    );
  }

  const showGlobalSelectionTranslation = activeTab !== "paper_reader";

  return (
    <div className="page">
      <header className="hero">
        <div>
          <p className="eyebrow">arxiv-paper-rag</p>
          <h1>{t("appTitle")}</h1>
        </div>
        <div className="header-actions">
          <div className="lang-switch" aria-label={t("language")}>
            <button type="button" className={language === "en" ? "active" : "secondary"} onClick={() => setLanguage("en")}>
              EN
            </button>
            <button type="button" className={language === "zh" ? "active" : "secondary"} onClick={() => setLanguage("zh")}>
              中文
            </button>
          </div>
          <div className="tab-row">
            <button className={activeTab === "search" ? "active" : ""} onClick={() => setActiveTab("search")}>
              {t("searchTab")}
            </button>
            <button className={activeTab === "citation_trace" ? "active" : ""} onClick={() => setActiveTab("citation_trace")}>
              {t("citationTraceTab")}
            </button>
            <button className={activeTab === "paper_reader" ? "active" : ""} onClick={() => setActiveTab("paper_reader")}>
              {t("paperReaderTab")}
            </button>
            <button
              className={activeTab === "research_topics" ? "active" : ""}
              onClick={() => setActiveTab("research_topics")}
            >
              {t("researchTopicsTab")}
            </button>
            <button
              className={activeTab === "research_profile" ? "active" : ""}
              onClick={() => setActiveTab("research_profile")}
            >
              {t("researchProfileTab")}
            </button>
            <button className={activeTab === "ingest" ? "active" : ""} onClick={() => setActiveTab("ingest")}>
              {t("ingestTab")}
            </button>
            <button className={activeTab === "settings" ? "active" : ""} onClick={() => setActiveTab("settings")}>
              {t("settingsTab")}
            </button>
          </div>
        </div>
      </header>

      {message ? <div className="message">{message}</div> : null}
      {activeTab === "search" ? (
        <div className="search-layout">
          <section className="workspace search-main">
            <ProgressTracker
              title={t("workspaceProgressTitle")}
              subtitle={t("workspaceProgressSubtitle")}
              steps={workspaceProgressSteps}
              currentStep={workspaceProgress.step}
              status={workspaceProgress.status}
              statusLabel={progressStatusLabels[workspaceProgress.status] || t("progressIdle")}
              detail={workspaceProgress.detail}
              updatedAt={workspaceProgress.updatedAt}
            />

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
                  retrievalSources={retrievalSources}
                  sourceFreshness={sourceFreshness}
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
                <ConstraintBlock
                  constraints={appliedConstraints}
                  corpusLatestDate={corpusLatestDate}
                  retrievalSources={retrievalSources}
                  sourceFreshness={sourceFreshness}
                  t={t}
                />
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
              <PaperList papers={papers} t={t} onReadPaper={openPaperReaderFromSearch} />
            </section>

            <section>
              <h3>{t("answerStream")}</h3>
              <div className="answer-box">{answer || <span className="muted">{t("answerPlaceholder")}</span>}</div>
            </section>
          </section>

          <aside className="assistant-column">
            {renderAssistantLayer()}
          </aside>
        </div>
      ) : null}

      {activeTab === "citation_trace" ? (
        <CitationTracePage
          language={language}
          t={t}
          runtimePayload={runtimePayload}
          onAssistantAutoReply={scheduleCitationTraceAssistantAutoReply}
          renderAssistantLayer={renderAssistantLayer}
          onSuggestionRefresh={refreshQuietSuggestions}
        />
      ) : null}

      {activeTab === "paper_reader" ? (
        <PaperReaderPage
          language={language}
          t={t}
          settings={settings}
          runtimePayload={runtimePayload}
          initialArxivUrl={pendingPaperReaderUrl}
          onInitialArxivUrlConsumed={() => setPendingPaperReaderUrl("")}
          renderAssistantLayer={renderAssistantLayer}
          onAssistantContextChange={updateAssistantLinkedContext}
          onSuggestionRefresh={refreshQuietSuggestions}
        />
      ) : null}

      {activeTab === "research_topics" ? <ResearchTopicsPage language={language} /> : null}

      {activeTab === "research_profile" ? (
        <ResearchProfilePage
          language={language}
          assistantSessionId={assistantSessionId}
          onAssistantSessionIdChange={setAssistantSessionId}
        />
      ) : null}

      {activeTab === "ingest" ? (
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
      ) : null}

      {activeTab === "settings" ? (
        <section className="settings-page">
          <div className="settings-page-head config-section">
            <div>
              <h3>{t("settingsTitle")}</h3>
              <p className="muted">{t("settingsDescription")}</p>
            </div>
            <button onClick={() => saveDefaults().catch((error) => setMessage(String(error)))}>{t("saveDefaults")}</button>
          </div>

          <section className="settings-grid">
            <ChatConfigSection
              title={t("queryChat")}
              config={settings.query_chat}
              onChange={(key, value) => updateNested("query_chat", key, value)}
              t={t}
              language={language}
              providerOptions={providerOptions}
              modelCatalog={modelCatalogs.query_chat}
              onFetchModels={() => fetchAvailableModels("query_chat")}
              modelListId="query-chat-models"
            />
            <ChatConfigSection
              title={t("answerChat")}
              config={settings.answer_chat}
              onChange={(key, value) => updateNested("answer_chat", key, value)}
              t={t}
              language={language}
              providerOptions={providerOptions}
              modelCatalog={modelCatalogs.answer_chat}
              onFetchModels={() => fetchAvailableModels("answer_chat")}
              modelListId="answer-chat-models"
            />
            <ChatConfigSection
              title={t("assistantChatModel")}
              config={settings.assistant_chat}
              onChange={(key, value) => updateNested("assistant_chat", key, value)}
              t={t}
              language={language}
              providerOptions={providerOptions}
              modelCatalog={modelCatalogs.assistant_chat}
              onFetchModels={() => fetchAvailableModels("assistant_chat")}
              modelListId="assistant-chat-models"
            />
            <ChatConfigSection
              title={t("paperReaderTranslationModel")}
              config={settings.paper_reader_translation}
              onChange={(key, value) => updateNested("paper_reader_translation", key, value)}
              t={t}
              language={language}
              providerOptions={translationProviderOptions}
              modelCatalog={modelCatalogs.paper_reader_translation}
              onFetchModels={() => fetchAvailableModels("paper_reader_translation")}
              modelListId="paper-reader-translation-models"
            />
            <ChatConfigSection
              title={t("citationTraceMainModel")}
              config={settings.citation_trace_main_chat}
              onChange={(key, value) => updateNested("citation_trace_main_chat", key, value)}
              t={t}
              language={language}
              providerOptions={providerOptions}
              modelCatalog={modelCatalogs.citation_trace_main_chat}
              onFetchModels={() => fetchAvailableModels("citation_trace_main_chat")}
              modelListId="citation-trace-main-models"
            />
            <ChatConfigSection
              title={t("citationTraceWorkerModel")}
              config={settings.citation_trace_worker_chat}
              onChange={(key, value) => updateNested("citation_trace_worker_chat", key, value)}
              t={t}
              language={language}
              providerOptions={providerOptions}
              modelCatalog={modelCatalogs.citation_trace_worker_chat}
              onFetchModels={() => fetchAvailableModels("citation_trace_worker_chat")}
              modelListId="citation-trace-worker-models"
            />
            <section className="config-section">
              <h3>{t("embedding")}</h3>
              <label>
                {t("ollamaApiUrl")}
                <input value={settings.embedding.api_url} onChange={(event) => updateNested("embedding", "api_url", event.target.value)} />
              </label>
              <ModelSelectorField
                listId="embedding-models"
                value={settings.embedding.model}
                onChange={(value) => updateNested("embedding", "model", value)}
                models={modelCatalogs.embedding.models}
                loading={modelCatalogs.embedding.loading}
                error={modelCatalogs.embedding.error}
                onFetch={() => fetchAvailableModels("embedding")}
                t={t}
                language={language}
              />
            </section>
            <section className="config-section">
              <h3>{t("rerankRetrieval")}</h3>
              <label>
                {t("rerankBaseUrl")}
                <input value={settings.rerank.base_url} onChange={(event) => updateNested("rerank", "base_url", event.target.value)} />
              </label>
              <label>
                {t("rerankModel")}
                <input value={settings.rerank.model} onChange={(event) => updateNested("rerank", "model", event.target.value)} />
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
              <button type="button" className="secondary" onClick={() => updateNested("rerank", "clear_api_key", !settings.rerank.clear_api_key)}>
                {settings.rerank.clear_api_key ? t("keepStoredKey") : t("clearStoredKey")}
              </button>
              <label>
                {t("topK")}
                <input type="number" value={settings.retrieval.top_k} onChange={(event) => updateNested("retrieval", "top_k", event.target.value)} />
              </label>
              <label>
                {t("topN")}
                <input type="number" value={settings.retrieval.top_n} onChange={(event) => updateNested("retrieval", "top_n", event.target.value)} />
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
            <RetrievalProviderSection
              providers={settings.retrieval.providers}
              onChange={(key, value) => updateNested("retrieval", key, value)}
              t={t}
            />
          </section>
        </section>
      ) : null}
      {showGlobalSelectionTranslation ? (
        <GlobalSelectionTranslationPanel
          selection={globalSelection}
          translationState={globalSelectionTranslation}
          t={t}
          onTranslate={translateGlobalSelection}
        />
      ) : null}
    </div>
  );
}
