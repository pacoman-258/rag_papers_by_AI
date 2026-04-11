import { useEffect, useMemo, useRef, useState } from "react";

const LIVE2D_SCRIPTS = [
  "/live2d/js/live2dcubismcore.min.js",
  "/live2d/js/live2d.min.js",
  "/live2d/js/pixi.min.js",
  "/live2d/js/index.min.js"
];

const DEFAULT_MOUTH_OPEN_PARAMETER_IDS = ["ParamMouthOpenY", "PARAM_MOUTH_OPEN_Y", "ParamMouthOpenX", "LipSync"];
const DEFAULT_MOUTH_FORM_PARAMETER_IDS = ["ParamMouthForm", "PARAM_MOUTH_FORM"];
const DEFAULT_CONTEXT_LIMIT = 4000;

const copy = {
  en: {
    title: "Live2D Assistant",
    subtitleIdle: "Chatbot mode",
    subtitleLinked: "Linked to latest answer",
    thinking: "Thinking...",
    inputPlaceholder: "Ask the assistant anything",
    send: "Send",
    mute: "Mute",
    unmute: "Unmute",
    collapse: "Collapse",
    expand: "Expand",
    clearContext: "Clear Answer Link",
    linked: "Using latest answer context",
    autoReply: "Auto suggestion from latest answer",
    modelOffline: "Model unavailable",
    assistantOffline: "Assistant unavailable right now.",
    ttsFallback: "TTS unavailable, switched to browser voice."
  },
  zh: {
    title: "Live2D 助手",
    subtitleIdle: "普通聊天模式",
    subtitleLinked: "已关联最近回答",
    thinking: "思考中...",
    inputPlaceholder: "和助手聊点什么吧",
    send: "发送",
    mute: "静音",
    unmute: "取消静音",
    collapse: "收起",
    expand: "展开",
    clearContext: "清除回答关联",
    linked: "当前会参考最近一次回答",
    autoReply: "已根据最新回答自动补充建议",
    modelOffline: "模型未就绪",
    assistantOffline: "助手暂时不可用。",
    ttsFallback: "TTS 不可用，已切换浏览器语音。"
  }
};

const scriptCache = new Map();

function getCopy(language) {
  return copy[language] ?? copy.zh;
}

function isScriptReady(src) {
  if (src.endsWith("/live2dcubismcore.min.js")) {
    return Boolean(window.Live2DCubismCore);
  }
  if (src.endsWith("/pixi.min.js")) {
    return Boolean(window.PIXI?.Application);
  }
  if (src.endsWith("/index.min.js")) {
    return Boolean(window.PIXI?.live2d?.Live2DModel);
  }
  return false;
}

function ensureScript(src) {
  if (scriptCache.has(src)) {
    return scriptCache.get(src);
  }

  const existing = document.querySelector(`script[data-live2d-src="${src}"]`);
  if (existing) {
    if (existing.dataset.live2dLoaded === "true" || isScriptReady(src)) {
      existing.dataset.live2dLoaded = "true";
      const readyPromise = Promise.resolve();
      scriptCache.set(src, readyPromise);
      return readyPromise;
    }
    const promise =
      new Promise((resolve, reject) => {
        existing.addEventListener(
          "load",
          () => {
            existing.dataset.live2dLoaded = "true";
            resolve();
          },
          { once: true }
        );
        existing.addEventListener("error", () => reject(new Error(`Failed to load ${src}`)), { once: true });
      }).catch((error) => {
        scriptCache.delete(src);
        existing.remove();
        throw error;
      });
    scriptCache.set(src, promise);
    return promise;
  }

  const promise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = src;
    script.async = false;
    script.dataset.live2dSrc = src;
    script.onload = () => {
      script.dataset.live2dLoaded = "true";
      resolve();
    };
    script.onerror = () => reject(new Error(`Failed to load ${src}`));
    document.head.appendChild(script);
  }).catch((error) => {
    scriptCache.delete(src);
    document.querySelector(`script[data-live2d-src="${src}"]`)?.remove();
    throw error;
  });
  scriptCache.set(src, promise);
  return promise;
}

async function ensureLive2DScripts() {
  for (const src of LIVE2D_SCRIPTS) {
    await ensureScript(src);
  }
}

function trimAnswerContext(text) {
  const value = String(text || "").trim();
  if (!value) {
    return null;
  }
  if (value.length <= DEFAULT_CONTEXT_LIMIT) {
    return value;
  }
  return `${value.slice(0, DEFAULT_CONTEXT_LIMIT).trimEnd()}...`;
}

function normalizeExpressionName(name) {
  return String(name || "")
    .toLowerCase()
    .replace(/[\s_-]+/g, "");
}

function useIsMobile() {
  const [isMobile, setIsMobile] = useState(() => window.innerWidth <= 900);

  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth <= 900);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  return isMobile;
}

function buildHistoryPayload(messages) {
  return messages.slice(-10).map((item) => ({ role: item.role, text: item.text }));
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

export default function Live2DAssistant({
  language,
  autoReply,
  latestAnswerContext,
  onClearAnswerContext
}) {
  const t = getCopy(language);
  const isMobile = useIsMobile();
  const stageRef = useRef(null);
  const canvasMountRef = useRef(null);
  const panelLogRef = useRef(null);
  const pixiAppRef = useRef(null);
  const live2dModelRef = useRef(null);
  const activeAudioRef = useRef(null);
  const audioCtxRef = useRef(null);
  const analyserRef = useRef(null);
  const mediaSourceRef = useRef(null);
  const lipSyncRafRef = useRef(0);
  const lastAutoReplyIdRef = useRef(null);
  const activeAudioUrlRef = useRef("");
  const mountedRef = useRef(false);
  const browserUtteranceRef = useRef(null);
  const browserSpeechOwnedRef = useRef(false);

  const [collapsed, setCollapsed] = useState(() => window.innerWidth <= 900);
  const [bootstrap, setBootstrap] = useState(null);
  const [modelReady, setModelReady] = useState(false);
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [muted, setMuted] = useState(false);
  const [error, setError] = useState("");
  const [scriptsReady, setScriptsReady] = useState(false);

  const linkedAnswerContext = useMemo(() => trimAnswerContext(latestAnswerContext), [latestAnswerContext]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    setCollapsed(isMobile);
  }, [isMobile]);

  useEffect(() => {
    let cancelled = false;
    ensureLive2DScripts()
      .then(() => {
        if (!cancelled) {
          setScriptsReady(true);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(String(err));
        }
      });

    fetch("/api/live2d/bootstrap")
      .then(async (response) => {
        const payload = await readJsonWithDetailFallback(response);
        if (!response.ok) {
          throw new Error(payload.detail || `HTTP ${response.status}`);
        }
        return payload;
      })
      .then((payload) => {
        if (!cancelled) {
          setBootstrap(payload);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(String(err));
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!panelLogRef.current) {
      return;
    }
    panelLogRef.current.scrollTop = panelLogRef.current.scrollHeight;
  }, [messages, busy]);

  useEffect(() => {
    if (collapsed) {
      if (mountedRef.current) {
        setModelReady(false);
      }
      return undefined;
    }

    if (!bootstrap || !scriptsReady || !stageRef.current || !canvasMountRef.current) {
      return undefined;
    }

    let disposed = false;
    let onResize = null;

    async function setupModel() {
      const host = canvasMountRef.current;
      if (!host || !window.PIXI?.Application || !window.PIXI?.live2d?.Live2DModel) {
        setError(t.modelOffline);
        return;
      }

      const app = new window.PIXI.Application({
        resizeTo: host,
        autoStart: true,
        backgroundAlpha: 0,
        antialias: true
      });
      host.appendChild(app.view);
      pixiAppRef.current = app;

      const model = await window.PIXI.live2d.Live2DModel.from(bootstrap.model_url);
      if (disposed) {
        try {
          model.destroy();
        } catch (_) {
          // ignore cleanup failures
        }
        app.destroy(true);
        return;
      }

      live2dModelRef.current = model;
      app.stage.addChild(model);
      model.scale.set(1);

      const applyTransform = () => {
        if (!pixiAppRef.current || !live2dModelRef.current) {
          return;
        }
        const rendererWidth = pixiAppRef.current.renderer.width;
        const rendererHeight = pixiAppRef.current.renderer.height;
        live2dModelRef.current.scale.set(1);
        const fitScaleX = (rendererWidth * 0.78) / Math.max(1, live2dModelRef.current.width);
        const fitScaleY = (rendererHeight * 0.95) / Math.max(1, live2dModelRef.current.height);
        const resolvedScale = Math.max(0.08, Math.min(fitScaleX, fitScaleY, 1.25));
        live2dModelRef.current.scale.set(resolvedScale);
        live2dModelRef.current.x = (rendererWidth - live2dModelRef.current.width) / 2;
        live2dModelRef.current.y = rendererHeight - live2dModelRef.current.height;
      };

      onResize = () => window.requestAnimationFrame(applyTransform);
      window.addEventListener("resize", onResize);
      applyTransform();

      app.stage.interactive = true;
      if ("eventMode" in app.stage) {
        app.stage.eventMode = "static";
      }
      app.stage.on("pointermove", (event) => {
        const point = event?.global;
        if (point && typeof model.focus === "function") {
          model.focus(point.x, point.y);
        }
      });

      const defaultExpression = bootstrap.default_expression;
      if (defaultExpression && typeof model.expression === "function") {
        try {
          model.expression(defaultExpression);
        } catch (_) {
          // ignore unsupported expression
        }
      }

      setModelReady(true);
    }

    setupModel().catch((err) => {
      if (!disposed && mountedRef.current) {
        setError(String(err));
        setModelReady(false);
      }
    });

    return () => {
      disposed = true;
      if (mountedRef.current) {
        setModelReady(false);
      }
      if (onResize) {
        window.removeEventListener("resize", onResize);
      }
      stopPlayback();
      closeAudioContext();
      if (pixiAppRef.current) {
        const view = pixiAppRef.current.view;
        try {
          pixiAppRef.current.destroy(true);
        } catch (_) {
          // ignore destroy failures
        }
        if (view?.parentNode) {
          try {
            view.parentNode.removeChild(view);
          } catch (_) {
            // ignore detach failures
          }
        }
      }
      pixiAppRef.current = null;
      live2dModelRef.current = null;
    };
  }, [bootstrap, collapsed, scriptsReady, t.modelOffline]);

  useEffect(() => {
    if (!autoReply || !autoReply.id || autoReply.id === lastAutoReplyIdRef.current) {
      return;
    }
    lastAutoReplyIdRef.current = autoReply.id;
    setCollapsed(false);
    void requestAssistantReply({
      source: autoReply.source,
      message: "",
      answerContext: autoReply.answerContext,
      isAutomatic: true
    });
  }, [autoReply]);

  function resolveExpressionName(name) {
    const candidate = String(name || "").trim();
    const available = Array.isArray(bootstrap?.available_expressions) ? bootstrap.available_expressions : [];
    if (!candidate || !available.length) {
      return "";
    }
    if (available.includes(candidate)) {
      return candidate;
    }
    const normalized = normalizeExpressionName(candidate);
    return available.find((item) => normalizeExpressionName(item) === normalized) || "";
  }

  function triggerExpressionSafe(name) {
    const expression = resolveExpressionName(name);
    if (!expression || !live2dModelRef.current || typeof live2dModelRef.current.expression !== "function") {
      return;
    }
    try {
      live2dModelRef.current.expression(expression);
    } catch (_) {
      // ignore invalid expression switches
    }
  }

  function setMouthOpen(value) {
    const core = live2dModelRef.current?.internalModel?.coreModel;
    if (!core) {
      return;
    }
    const mouthValue = Math.max(0, Math.min(1, Number(value) || 0));
    for (const parameterId of DEFAULT_MOUTH_OPEN_PARAMETER_IDS) {
      try {
        if (typeof core.setParameterValueById === "function") {
          core.setParameterValueById(parameterId, mouthValue, 0.8);
        } else if (typeof core.addParameterValueById === "function") {
          core.addParameterValueById(parameterId, mouthValue * 0.65, 0.8);
        }
      } catch (_) {
        // ignore missing mouth-open parameters
      }
    }
    for (const parameterId of DEFAULT_MOUTH_FORM_PARAMETER_IDS) {
      try {
        if (typeof core.setParameterValueById === "function") {
          core.setParameterValueById(parameterId, (mouthValue - 0.5) * 0.35, 0.35);
        } else if (typeof core.addParameterValueById === "function") {
          core.addParameterValueById(parameterId, (mouthValue - 0.5) * 0.15, 0.35);
        }
      } catch (_) {
        // ignore missing mouth-form parameters
      }
    }
  }

  function stopLipSyncLoop() {
    if (lipSyncRafRef.current) {
      cancelAnimationFrame(lipSyncRafRef.current);
      lipSyncRafRef.current = 0;
    }
    setMouthOpen(0);
  }

  function releaseActiveAudioUrl() {
    if (!activeAudioUrlRef.current) {
      return;
    }
    URL.revokeObjectURL(activeAudioUrlRef.current);
    activeAudioUrlRef.current = "";
  }

  function stopPlayback() {
    stopLipSyncLoop();
    if (browserSpeechOwnedRef.current && "speechSynthesis" in window) {
      try {
        window.speechSynthesis.cancel();
      } catch (_) {
        // ignore cancel failures
      }
    }
    browserUtteranceRef.current = null;
    browserSpeechOwnedRef.current = false;
    if (activeAudioRef.current) {
      try {
        activeAudioRef.current.pause();
      } catch (_) {
        // ignore pause failures
      }
      activeAudioRef.current.src = "";
      activeAudioRef.current = null;
    }
    releaseActiveAudioUrl();
    if (mediaSourceRef.current) {
      try {
        mediaSourceRef.current.disconnect();
      } catch (_) {
        // ignore disconnect failures
      }
      mediaSourceRef.current = null;
    }
  }

  function closeAudioContext() {
    analyserRef.current = null;
    if (mediaSourceRef.current) {
      try {
        mediaSourceRef.current.disconnect();
      } catch (_) {
        // ignore disconnect failures
      }
      mediaSourceRef.current = null;
    }
    if (audioCtxRef.current && typeof audioCtxRef.current.close === "function" && audioCtxRef.current.state !== "closed") {
      audioCtxRef.current.close().catch(() => {});
    }
    audioCtxRef.current = null;
  }

  function startLipSync(audio) {
    try {
      if (!audioCtxRef.current || audioCtxRef.current.state === "closed") {
        audioCtxRef.current = new (window.AudioContext || window.webkitAudioContext)();
      }
      if (audioCtxRef.current.state === "suspended") {
        audioCtxRef.current.resume().catch(() => {});
      }
      if (mediaSourceRef.current) {
        try {
          mediaSourceRef.current.disconnect();
        } catch (_) {
          // ignore reconnect failures
        }
        mediaSourceRef.current = null;
      }

      analyserRef.current = audioCtxRef.current.createAnalyser();
      analyserRef.current.fftSize = 2048;
      mediaSourceRef.current = audioCtxRef.current.createMediaElementSource(audio);
      mediaSourceRef.current.connect(analyserRef.current);
      analyserRef.current.connect(audioCtxRef.current.destination);
    } catch (_) {
      return;
    }

    const data = new Uint8Array(analyserRef.current.fftSize);
    const tick = () => {
      if (!analyserRef.current || audio.paused || audio.ended) {
        stopLipSyncLoop();
        return;
      }
      analyserRef.current.getByteTimeDomainData(data);
      let sum = 0;
      for (let index = 0; index < data.length; index += 1) {
        const sample = (data[index] - 128) / 128;
        sum += sample * sample;
      }
      const rms = Math.sqrt(sum / data.length);
      const mouth = Math.max(0, Math.min(1, rms * 6.2));
      setMouthOpen(mouth);
      lipSyncRafRef.current = requestAnimationFrame(tick);
    };

    tick();
  }

  function browserSpeak(text) {
    if (!("speechSynthesis" in window) || !window.SpeechSynthesisUtterance) {
      return Promise.resolve();
    }
    if (window.speechSynthesis.speaking || window.speechSynthesis.pending) {
      return Promise.resolve();
    }

    return new Promise((resolve) => {
      try {
        const utterance = new SpeechSynthesisUtterance(text);
        browserUtteranceRef.current = utterance;
        browserSpeechOwnedRef.current = true;
        utterance.lang = language === "zh" ? "zh-CN" : "en-US";
        utterance.rate = 1;
        utterance.onstart = () => {
          let mouthValue = 0.15;
          const tick = () => {
            if (browserUtteranceRef.current !== utterance) {
              stopLipSyncLoop();
              return;
            }
            mouthValue = mouthValue > 0.55 ? 0.1 : 0.75;
            setMouthOpen(mouthValue);
            lipSyncRafRef.current = requestAnimationFrame(tick);
          };
          tick();
        };
        utterance.onend = () => {
          if (browserUtteranceRef.current === utterance) {
            browserUtteranceRef.current = null;
          }
          browserSpeechOwnedRef.current = false;
          stopLipSyncLoop();
          resolve();
        };
        utterance.onerror = () => {
          if (browserUtteranceRef.current === utterance) {
            browserUtteranceRef.current = null;
          }
          browserSpeechOwnedRef.current = false;
          stopLipSyncLoop();
          resolve();
        };
        window.speechSynthesis.speak(utterance);
      } catch (_) {
        browserSpeechOwnedRef.current = false;
        stopLipSyncLoop();
        resolve();
      }
    });
  }

  async function speakText(text) {
    const content = String(text || "").trim();
    if (!content || muted) {
      return;
    }

    if (!bootstrap?.tts_enabled) {
      await browserSpeak(content);
      return;
    }

    try {
      const response = await fetch("/api/live2d/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: content,
          voice: bootstrap.default_voice,
          rate: "+0%"
        })
      });
      const payload = await readJsonWithDetailFallback(response);
      if (!response.ok) {
        throw new Error(payload.detail || `HTTP ${response.status}`);
      }
      const audioResponse = await fetch(payload.audio_url);
      if (!audioResponse.ok) {
        throw new Error(`HTTP ${audioResponse.status}`);
      }

      const audioBlob = await audioResponse.blob();
      const objectUrl = URL.createObjectURL(audioBlob);
      stopPlayback();

      const audio = new Audio(objectUrl);
      activeAudioRef.current = audio;
      activeAudioUrlRef.current = objectUrl;
      await new Promise((resolve, reject) => {
        audio.addEventListener(
          "ended",
          () => {
            stopLipSyncLoop();
            activeAudioRef.current = null;
            releaseActiveAudioUrl();
            resolve();
          },
          { once: true }
        );
        audio.addEventListener(
          "error",
          () => {
            stopLipSyncLoop();
            activeAudioRef.current = null;
            releaseActiveAudioUrl();
            reject(new Error("audio playback failed"));
          },
          { once: true }
        );
        audio
          .play()
          .then(() => startLipSync(audio))
          .catch(reject);
      });
    } catch (_) {
      if (mountedRef.current) {
        setError(t.ttsFallback);
      }
      await browserSpeak(content);
    }
  }

  async function requestAssistantReply({ source, message, answerContext, isAutomatic = false }) {
    const trimmedMessage = String(message || "").trim();
    const resolvedContext = trimAnswerContext(answerContext ?? linkedAnswerContext);
    const history = buildHistoryPayload(messages);

    if (source === "user" && !trimmedMessage) {
      return;
    }

    if (source === "user") {
      setMessages((current) => [...current, { role: "user", text: trimmedMessage, source: "manual" }]);
      setDraft("");
    }

    setBusy(true);
    setError("");

    try {
      const response = await fetch("/api/live2d/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source,
          message: trimmedMessage,
          history,
          answer_context: resolvedContext
        })
      });
      const payload = await readJsonWithDetailFallback(response);
      if (!response.ok) {
        throw new Error(payload.detail || `HTTP ${response.status}`);
      }
      triggerExpressionSafe(payload.expression);
      if (mountedRef.current) {
        setMessages((current) => [
          ...current,
          {
            role: "assistant",
            text: payload.reply_text,
            source,
            isAutomatic
          }
        ]);
      }
      await speakText(payload.speak_text || payload.reply_text);
    } catch (err) {
      if (mountedRef.current) {
        setError(String(err));
        setMessages((current) => [
          ...current,
          {
            role: "assistant",
            text: t.assistantOffline,
            source: "error",
            isAutomatic: false
          }
        ]);
      }
    } finally {
      if (mountedRef.current) {
        setBusy(false);
      }
    }
  }

  function handleSubmit(event) {
    event.preventDefault();
    void requestAssistantReply({
      source: "user",
      message: draft,
      answerContext: linkedAnswerContext,
      isAutomatic: false
    });
  }

  return (
    <aside className={`assistant-shell${collapsed ? " is-collapsed" : ""}`}>
      {collapsed ? (
        <button type="button" className="assistant-expand-pill" onClick={() => setCollapsed(false)}>
          {t.expand}
        </button>
      ) : (
        <>
          <div className="assistant-stage-card">
            <div className="assistant-stage-frame" ref={stageRef}>
              <div className="assistant-stage-canvas" ref={canvasMountRef} />
              {!modelReady ? <div className="assistant-stage-placeholder">{t.modelOffline}</div> : null}
            </div>
          </div>

          <div className="assistant-panel">
            <div className="assistant-panel-head">
              <div>
                <p className="assistant-kicker">{t.title}</p>
                <p className="assistant-subtitle">{linkedAnswerContext ? t.subtitleLinked : t.subtitleIdle}</p>
              </div>
              <div className="assistant-head-actions">
                {linkedAnswerContext ? (
                  <button type="button" className="secondary" onClick={onClearAnswerContext}>
                    {t.clearContext}
                  </button>
                ) : null}
                <button type="button" className="secondary" onClick={() => setMuted((current) => !current)}>
                  {muted ? t.unmute : t.mute}
                </button>
                <button type="button" className="secondary" onClick={() => setCollapsed(true)}>
                  {t.collapse}
                </button>
              </div>
            </div>

            {linkedAnswerContext ? <div className="assistant-context-chip">{t.linked}</div> : null}

            <div ref={panelLogRef} className="assistant-log">
              {messages.length === 0 ? (
                <p className="muted">{t.subtitleIdle}</p>
              ) : (
                messages.map((item, index) => (
                  <article
                    key={`${item.role}-${index}-${item.text}`}
                    className={`assistant-message assistant-message-${item.role}`}
                  >
                    <p>{item.text}</p>
                    {item.isAutomatic ? (
                      <span className="assistant-message-tag">{t.autoReply}</span>
                    ) : null}
                  </article>
                ))
              )}
              {busy ? <p className="muted">{t.thinking}</p> : null}
            </div>

            <form className="assistant-composer" onSubmit={handleSubmit}>
              <textarea
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                rows={3}
                placeholder={t.inputPlaceholder}
              />
              <button type="submit" disabled={busy || !draft.trim()}>
                {t.send}
              </button>
            </form>

            {error ? <div className="assistant-error">{error}</div> : null}
          </div>
        </>
      )}
    </aside>
  );
}
