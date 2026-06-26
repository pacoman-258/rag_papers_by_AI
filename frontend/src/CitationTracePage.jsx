import { useEffect, useRef, useState } from "react";
import ProgressTracker from "./ProgressTracker.jsx";

const CITATION_TRACE_COMPLETED_EVENT = "citation_trace.completed";

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

function toArray(value) {
  return Array.isArray(value) ? value : [];
}

function trimText(value) {
  return String(value || "").trim();
}

function formatScore(value) {
  const score = Number(value);
  return Number.isFinite(score) ? score.toFixed(3) : "-";
}

function scoreBreakdownLabel(key) {
  if (key === "author_overlap") {
    return "author_bonus";
  }
  return key;
}

function entryTitle(entry) {
  return trimText(entry?.candidate_paper?.title) || trimText(entry?.candidate_paper?.canonical_id) || trimText(entry?.entry_id);
}

function paperAuthors(paper, t) {
  const authors = toArray(paper?.authors).map(trimText).filter(Boolean);
  return authors.length ? authors.join(", ") : t("none");
}

function paperSourceLabel(paper, t) {
  const parts = [paper?.source, paper?.source_id || paper?.arxiv_id || paper?.doi].map(trimText).filter(Boolean);
  return parts.length ? parts.join(" / ") : t("none");
}

function stageToProgress(stage) {
  switch (stage) {
    case "reference_resolution":
      return "references";
    case "candidate_recall":
      return "candidate_recall";
    case "worker_assessment":
      return "worker_assessment";
    case "main_ranking":
      return "main_ranking";
    case "round_two":
      return "round_two";
    case "synthesis":
      return "synthesis";
    default:
      return "load";
  }
}

function progressDetailForStep(step, t) {
  switch (step) {
    case "candidate_recall":
      return t("citationTraceProgressCandidateRecall");
    case "worker_assessment":
      return t("citationTraceProgressWorkerAssessment");
    case "main_ranking":
      return t("citationTraceProgressMainRanking");
    case "round_one":
      return t("citationTraceProgressRoundOne");
    case "round_two":
      return t("citationTraceProgressRoundTwo");
    case "synthesis":
      return t("citationTraceProgressSynthesis");
    case "top5":
      return t("citationTraceProgressTop5");
    case "references":
      return t("citationTraceProgressReferences");
    default:
      return t("citationTraceProgressLoad");
  }
}

function parseSseJson(event) {
  try {
    return JSON.parse(event?.data || "{}");
  } catch (_) {
    return null;
  }
}

function buildAssistantAnswerContext(session) {
  const targetTitle = trimText(session?.target_paper?.title) || trimText(session?.source_id);
  const topLines = toArray(session?.final_top5)
    .map((paper) => `${paper.rank || ""}. ${trimText(paper.title)} (${paper.evidence_level || "unknown"})`)
    .filter((line) => line.replace(/^[\d. ]+/, "").trim());
  const warningLines = toArray(session?.warnings).map(trimText).filter(Boolean);
  return [
    targetTitle ? `Citation trace target: ${targetTitle}` : "",
    topLines.length ? `Final top 5:\n${topLines.join("\n")}` : "",
    warningLines.length ? `Warnings:\n${warningLines.join("\n")}` : ""
  ]
    .filter(Boolean)
    .join("\n\n");
}

function buildAssistantWorkflowContext(session, language, answerContext) {
  const topPapers = toArray(session?.final_top5);
  const ledgerEntries = toArray(session?.ledger_entries);
  return {
    kind: "citation_trace",
    answer_language: language || null,
    query: trimText(session?.source_url || session?.source_id || session?.target_paper?.title),
    answer_text: answerContext || null,
    paper_ids: topPapers.map((paper) => trimText(paper.paper_id)).filter(Boolean),
    paper_titles: topPapers.map((paper) => trimText(paper.title)).filter(Boolean),
    target_paper_id: trimText(session?.target_paper?.paper_id || session?.target_paper?.canonical_id) || null,
    metadata: {
      session_id: session?.session_id || null,
      source_type: session?.source_type || null,
      source_id: session?.source_id || null,
      source_url: session?.source_url || null,
      target_paper_title: session?.target_paper?.title || null,
      final_top5_count: topPapers.length,
      ledger_entry_count: ledgerEntries.length
    }
  };
}

function TargetSummary({ session, t }) {
  const paper = session?.target_paper;
  if (!session || !paper) {
    return (
      <section className="citation-trace-summary">
        <p className="muted">{t("citationTraceNoSession")}</p>
      </section>
    );
  }
  return (
    <section className="citation-trace-summary">
      <div>
        <h3>{paper.title || session.source_id || t("citationTraceTitle")}</h3>
        <p className="muted">{paper.abstract || session.source_url || session.source_id || t("none")}</p>
      </div>
      <div className="tag-list">
        <span className="tag">{`${t("status")}: ${session.status || t("idle")}`}</span>
        <span className="tag">{`${t("source")}: ${paperSourceLabel(paper, t)}`}</span>
        {paper.published_date ? <span className="tag">{`${t("publishedDate")}: ${paper.published_date}`}</span> : null}
        {paper.external_url ? (
          <a className="tag" href={paper.external_url} target="_blank" rel="noreferrer">
            {t("openSource")}
          </a>
        ) : null}
      </div>
    </section>
  );
}

function FinalTop5({ papers, t }) {
  if (!papers.length) {
    return <p className="muted">{t("citationTraceNoTop5")}</p>;
  }
  return (
    <div className="paper-list">
      {papers.map((paper) => (
        <article key={`${paper.rank}-${paper.paper_id}`} className="paper-card">
          <h4>
            {paper.rank}. {paper.title}
          </h4>
          <div className="tag-list">
            <span className="tag">{paper.evidence_level}</span>
            {paper.is_explicitly_cited ? <span className="tag">explicit</span> : null}
            {paper.is_exploratory ? <span className="tag">exploratory</span> : null}
          </div>
          {paper.influence_area ? (
            <p>
              <strong>{t("method")}:</strong> {paper.influence_area}
            </p>
          ) : null}
          {paper.reason ? <p>{paper.reason}</p> : null}
          {paper.why_worth_reading ? <p className="muted">{paper.why_worth_reading}</p> : null}
          {paper.uncertainty ? <p className="muted">{paper.uncertainty}</p> : null}
        </article>
      ))}
    </div>
  );
}

function LedgerList({ entries, selectedEntryId, onSelect, t, compact = false }) {
  if (!entries.length) {
    return <p className="muted">{compact ? t("citationTraceNoExploratory") : t("citationTraceNoLedger")}</p>;
  }
  return (
    <div className="citation-ledger">
      {entries.map((entry) => (
        <button
          key={entry.entry_id}
          type="button"
          className={`ledger-row${compact ? " compact" : ""}${selectedEntryId === entry.entry_id ? " selected" : ""}`}
          onClick={() => onSelect(entry.entry_id)}
        >
          <span>
            <strong>{entryTitle(entry)}</strong>
            <small>{entry.relation_type || t("none")}</small>
          </span>
          <span className="tag-list">
            <span className="tag">{`R${entry.round || "-"}`}</span>
            <span className="tag">{entry.evidence_level || t("none")}</span>
            <span className="tag">{formatScore(entry.score_total)}</span>
          </span>
        </button>
      ))}
    </div>
  );
}

function EntryDetail({ entry, t }) {
  if (!entry) {
    return (
      <section className="citation-trace-detail">
        <p className="muted">{t("citationTraceNoLedger")}</p>
      </section>
    );
  }
  const paper = entry.candidate_paper || {};
  const scoreBreakdown = Object.entries(entry.score_breakdown || {});
  const metadataEvidence = toArray(entry.metadata_evidence).map(trimText).filter(Boolean);
  const warnings = toArray(entry.warnings).map(trimText).filter(Boolean);
  return (
    <section className="citation-trace-detail">
      <h3>{entryTitle(entry)}</h3>
      <div className="tag-list">
        <span className="tag">{entry.relation_type || t("none")}</span>
        <span className="tag">{entry.evidence_level || t("none")}</span>
        <span className="tag">{formatScore(entry.score_total)}</span>
      </div>
      <div className="detail-grid">
        <div>
          <strong>{t("source")}</strong>
          <p>{paperSourceLabel(paper, t)}</p>
        </div>
        <div>
          <strong>{t("publishedDate")}</strong>
          <p>{paper.published_date || t("none")}</p>
        </div>
        <div>
          <strong>{t("authors")}</strong>
          <p>{paperAuthors(paper, t)}</p>
        </div>
        <div>
          <strong>{t("evidenceLedger")}</strong>
          <p>{entry.entry_id || t("none")}</p>
        </div>
      </div>
      {paper.abstract ? <p>{paper.abstract}</p> : null}
      {entry.reference_text ? (
        <div>
          <strong>{t("citationTraceReferenceText")}</strong>
          <p>{entry.reference_text}</p>
        </div>
      ) : null}
      {metadataEvidence.length ? (
        <div>
          <strong>{t("appliedConstraints")}</strong>
          <ul>
            {metadataEvidence.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {entry.llm_assessment ? <p className="muted">{entry.llm_assessment}</p> : null}
      {scoreBreakdown.length ? (
        <div className="detail-grid">
          {scoreBreakdown.map(([key, value]) => (
            <div key={key}>
              <strong>{scoreBreakdownLabel(key)}</strong>
              <p>{formatScore(value)}</p>
            </div>
          ))}
        </div>
      ) : null}
      {warnings.length ? (
        <div className="warning-box">
          {warnings.map((warning) => (
            <div key={warning}>{warning}</div>
          ))}
        </div>
      ) : null}
    </section>
  );
}

export default function CitationTracePage({
  language,
  t,
  runtimePayload,
  onAssistantAutoReply,
  renderAssistantLayer,
  onSuggestionRefresh,
  researchThread = null
}) {
  const [arxivUrl, setArxivUrl] = useState("");
  const [pdfFile, setPdfFile] = useState(null);
  const [session, setSession] = useState(null);
  const [selectedEntryId, setSelectedEntryId] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [warnings, setWarnings] = useState([]);
  const [progress, setProgress] = useState({
    step: "load",
    status: "idle",
    detail: "",
    updatedAt: null
  });
  const sourceRef = useRef(null);
  const completedSessionRef = useRef("");
  const progressStepRef = useRef("load");

  useEffect(() => {
    return () => {
      sourceRef.current?.close();
    };
  }, []);

  const progressStatusLabels = {
    idle: t("progressIdle"),
    running: t("progressRunning"),
    ready: t("progressReady"),
    completed: t("progressCompleted"),
    interrupted: t("progressInterrupted")
  };
  const progressSteps = [
    { key: "load", label: t("citationTraceProgressLoad") },
    { key: "references", label: t("citationTraceProgressReferences") },
    { key: "candidate_recall", label: t("citationTraceProgressCandidateRecall") },
    { key: "worker_assessment", label: t("citationTraceProgressWorkerAssessment") },
    { key: "main_ranking", label: t("citationTraceProgressMainRanking") },
    { key: "top5", label: t("citationTraceProgressTop5") }
  ];
  const finalTop5 = toArray(session?.final_top5);
  const evidenceLedger = toArray(session?.ledger_entries);
  const exploratorySources = evidenceLedger.filter((entry) => entry.relation_type !== "explicit_reference");
  const selectedEntry = evidenceLedger.find((entry) => entry.entry_id === selectedEntryId) || evidenceLedger[0] || null;

  function updateProgress(step, status, detail = "") {
    progressStepRef.current = step;
    setProgress({
      step,
      status,
      detail,
      updatedAt: new Date().toISOString()
    });
  }

  function resetRun() {
    sourceRef.current?.close();
    completedSessionRef.current = "";
    setSession(null);
    setSelectedEntryId("");
    setWarnings([]);
    setMessage("");
  }

  async function fetchSession(sessionId) {
    const response = await fetch(`/api/citation-trace/session/${encodeURIComponent(sessionId)}`);
    const data = await readJsonWithDetailFallback(response);
    if (!response.ok) {
      throw new Error(data.detail || t("citationTraceFailed"));
    }
    setSession(data);
    return data;
  }

  function sendAssistantAutoReply(nextSession) {
    if (!nextSession?.session_id || completedSessionRef.current === nextSession.session_id) {
      return;
    }
    const answerContext = buildAssistantAnswerContext(nextSession);
    if (!answerContext) {
      return;
    }
    completedSessionRef.current = nextSession.session_id;
    onAssistantAutoReply?.({
      id: `citation_trace_auto-${Date.now()}`,
      source: "citation_trace_auto",
      answerContext,
      workflowContext: buildAssistantWorkflowContext(nextSession, language, answerContext)
    });
  }

  async function storeCitationTraceAction(nextSession) {
    if (!researchThread?.thread_id || !nextSession?.session_id) {
      return null;
    }
    const response = await fetch(
      `/api/research-topics/threads/${encodeURIComponent(researchThread.thread_id)}/citation-trace-actions`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          citation_trace_session_id: nextSession.session_id,
          target_paper: nextSession.target_paper || {},
          final_top5: nextSession.final_top5 || [],
          warnings: nextSession.warnings || [],
          assistant_explanation: buildAssistantAnswerContext(nextSession)
        })
      }
    );
    const payload = await readJsonWithDetailFallback(response);
    if (!response.ok) {
      throw new Error(payload.detail || `Citation Trace action save failed (HTTP ${response.status})`);
    }
    return payload;
  }

  function startStream(sessionId) {
    sourceRef.current?.close();
    updateProgress("references", "running", t("citationTraceProgressReferences"));
    const source = new EventSource(`/api/citation-trace/session/${encodeURIComponent(sessionId)}/stream`);
    sourceRef.current = source;
    let streamSettled = false;

    function failStream(detail = t("citationTraceFailed")) {
      if (streamSettled) {
        return;
      }
      streamSettled = true;
      source.close();
      setBusy(false);
      setMessage(detail);
      updateProgress(progressStepRef.current, "interrupted", detail);
    }

    function readSsePayload(event) {
      const payload = parseSseJson(event);
      if (payload === null) {
        failStream(t("citationTraceFailed"));
        return null;
      }
      return payload;
    }

    source.addEventListener("stage_start", (event) => {
      const payload = readSsePayload(event);
      if (!payload) {
        return;
      }
      const step = stageToProgress(payload.stage);
      updateProgress(step, "running", progressDetailForStep(step, t));
    });
    source.addEventListener("round_summary", (event) => {
      const payload = readSsePayload(event);
      if (!payload) {
        return;
      }
      if (payload.round === 1) {
        updateProgress("candidate_recall", "completed", payload.summary_text || t("citationTraceProgressCandidateRecall"));
      } else if (payload.round === 2) {
        updateProgress("round_two", "completed", payload.summary_text || t("citationTraceProgressRoundTwo"));
      }
    });
    source.addEventListener("ledger_entry", (event) => {
      const payload = readSsePayload(event);
      if (!payload) {
        return;
      }
      updateProgress(payload.round === 2 ? "round_two" : "candidate_recall", "running", payload.title || t("evidenceLedger"));
    });
    source.addEventListener("worker_assessment_complete", (event) => {
      const payload = readSsePayload(event);
      if (!payload) {
        return;
      }
      updateProgress("worker_assessment", "completed", `${t("citationTraceCandidateTop15")}: ${payload.candidate_count ?? 0}`);
    });
    source.addEventListener("warning", (event) => {
      const payload = readSsePayload(event);
      if (!payload) {
        return;
      }
      const warning = trimText(payload.message);
      if (warning) {
        setWarnings((current) => [...current, warning]);
      }
    });
    source.addEventListener("synthesis_complete", (event) => {
      const payload = readSsePayload(event);
      if (!payload) {
        return;
      }
      updateProgress("top5", "running", `${t("finalTop5")}: ${payload.final_top5_count ?? 0}`);
    });
    source.addEventListener("complete", async (event) => {
      const payload = readSsePayload(event);
      if (!payload) {
        return;
      }
      streamSettled = true;
      source.close();
      try {
        const nextSession = await fetchSession(payload.session_id || sessionId);
        const completed = payload.status !== "failed";
        updateProgress("top5", completed ? "completed" : "interrupted", completed ? t("citationTraceCompleted") : t("citationTraceFailed"));
        if (completed && researchThread?.thread_id) {
          try {
            await storeCitationTraceAction(nextSession);
            onSuggestionRefresh?.();
          } catch (error) {
            setWarnings((current) => [...current, `${CITATION_TRACE_COMPLETED_EVENT}: ${String(error)}`]);
          }
        }
        if (completed) {
          onSuggestionRefresh?.();
        }
        sendAssistantAutoReply(nextSession);
      } catch (error) {
        setMessage(String(error));
        updateProgress("top5", "interrupted", String(error));
      } finally {
        setBusy(false);
      }
    });
    source.addEventListener("error", (event) => {
      if (streamSettled) {
        return;
      }
      const payload = parseSseJson(event);
      failStream(payload?.message || t("citationTraceFailed"));
    });
    source.onerror = () => {
      if (!streamSettled && !completedSessionRef.current) {
        failStream(t("citationTraceFailed"));
      }
    };
  }

  async function createFromArxiv() {
    const url = trimText(arxivUrl);
    if (!url) {
      setMessage(t("citationTraceUrlRequired"));
      return;
    }
    resetRun();
    setBusy(true);
    updateProgress("load", "running", t("citationTraceProgressLoad"));
    try {
      const response = await fetch("/api/citation-trace/session/from-arxiv", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url,
          answer_language: language,
          settings: runtimePayload
        })
      });
      const data = await readJsonWithDetailFallback(response);
      if (!response.ok) {
        throw new Error(data.detail || t("citationTraceFailed"));
      }
      setSession(data);
      startStream(data.session_id);
    } catch (error) {
      setBusy(false);
      setMessage(String(error));
      updateProgress("load", "interrupted", String(error));
    }
  }

  async function createFromFile() {
    if (!pdfFile) {
      setMessage(t("citationTraceFileRequired"));
      return;
    }
    resetRun();
    setBusy(true);
    updateProgress("load", "running", t("citationTraceProgressLoad"));
    const formData = new FormData();
    formData.append("file", pdfFile);
    formData.append("answer_language", language);
    if (runtimePayload) {
      formData.append("settings", JSON.stringify(runtimePayload));
    }
    try {
      const response = await fetch("/api/citation-trace/session/from-file", {
        method: "POST",
        body: formData
      });
      const data = await readJsonWithDetailFallback(response);
      if (!response.ok) {
        throw new Error(data.detail || t("citationTraceFailed"));
      }
      setSession(data);
      startStream(data.session_id);
    } catch (error) {
      setBusy(false);
      setMessage(String(error));
      updateProgress("load", "interrupted", String(error));
    }
  }

  return (
    <div className="citation-trace-layout">
      <main className="citation-trace-main">
        <section className="config-section">
          <div className="paper-reader-hero">
            <div>
              <h3>{t("citationTraceTitle")}</h3>
              <p className="muted">{t("citationTraceReadyToRun")}</p>
            </div>
            {session?.session_id ? <span className="tag">{session.session_id}</span> : null}
          </div>
          <div className="citation-trace-inputs">
            <label>
              {t("citationTraceArxivUrl")}
              <input value={arxivUrl} onChange={(event) => setArxivUrl(event.target.value)} placeholder="https://arxiv.org/abs/1706.03762" />
            </label>
            <div>
              <button type="button" onClick={createFromArxiv} disabled={busy}>
                {busy ? t("working") : t("citationTraceLoadArxiv")}
              </button>
            </div>
            <label>
              {t("citationTracePdfFile")}
              <input type="file" accept="application/pdf,.pdf" onChange={(event) => setPdfFile(event.target.files?.[0] || null)} />
            </label>
            <div>
              <button type="button" className="secondary" onClick={createFromFile} disabled={busy}>
                {busy ? t("working") : t("citationTraceLoadPdf")}
              </button>
            </div>
          </div>
        </section>

        <ProgressTracker
          title={t("citationTraceProgressTitle")}
          subtitle={t("citationTraceProgressSubtitle")}
          steps={progressSteps}
          currentStep={progress.step}
          status={progress.status}
          statusLabel={progressStatusLabels[progress.status] || t("progressIdle")}
          detail={progress.detail}
          updatedAt={progress.updatedAt}
        />

        {message ? <div className="message">{message}</div> : null}
        {warnings.length || session?.warnings?.length ? (
          <div className="warning-box">
            {[...warnings, ...toArray(session?.warnings)].map((warning, index) => (
              <div key={`${index}-${warning}`}>{`${t("citationTraceWarning")}: ${warning}`}</div>
            ))}
          </div>
        ) : null}

        <TargetSummary session={session} t={t} />

        <section>
          <h3>{t("citationTraceCandidateTop15")}</h3>
          <LedgerList entries={evidenceLedger.slice(0, 15)} selectedEntryId={selectedEntry?.entry_id || ""} onSelect={setSelectedEntryId} t={t} />
        </section>

        <section>
          <h3>{t("finalTop5")}</h3>
          <FinalTop5 papers={finalTop5} t={t} />
        </section>

        <section>
          <h3>{t("exploratorySources")}</h3>
          <LedgerList entries={exploratorySources} selectedEntryId={selectedEntry?.entry_id || ""} onSelect={setSelectedEntryId} t={t} compact />
        </section>

        <section>
          <h3>{t("evidenceLedger")}</h3>
          <LedgerList entries={evidenceLedger} selectedEntryId={selectedEntry?.entry_id || ""} onSelect={setSelectedEntryId} t={t} />
        </section>

        <EntryDetail entry={selectedEntry} t={t} />
      </main>

      <aside className="assistant-column">
        {renderAssistantLayer?.()}
      </aside>
    </div>
  );
}
