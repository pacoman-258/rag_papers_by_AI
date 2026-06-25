import { useEffect, useMemo, useRef, useState } from "react";

const copy = {
  en: {
    title: "Research Profile",
    description: "Manage the assistant's cautious inferences about your research direction, next topics, and reading preferences.",
    refresh: "Refresh",
    loading: "Loading profile...",
    empty: "No stable research profile yet.",
    needsMemory: "Connect the assistant memory database to start building a profile.",
    unavailable: "Research profile is unavailable right now.",
    disabled: "Research profile is disabled in runtime settings.",
    evidence: "Evidence",
    pin: "Pin",
    pinned: "Pinned",
    delete: "Delete",
    actionUnavailable: "Memory actions are unavailable on the current backend.",
    kind: {
      expertise_signal: "Professional Direction",
      research_direction: "Possible Next Direction",
      reading_preference: "Reading Preference"
    }
  },
  zh: {
    title: "研究画像",
    description: "管理小助手基于论文阅读行为谨慎推测出的专业方向、后续研究方向和阅读偏好。",
    refresh: "刷新画像",
    loading: "正在加载画像...",
    empty: "还没有稳定的研究画像。",
    needsMemory: "连接长期记忆库后会开始积累画像。",
    unavailable: "研究画像暂时不可用。",
    disabled: "运行配置中未启用研究画像。",
    evidence: "证据",
    pin: "置顶",
    pinned: "已置顶",
    delete: "删除",
    actionUnavailable: "当前后端暂不支持记忆操作。",
    kind: {
      expertise_signal: "专业方向",
      research_direction: "后续方向",
      reading_preference: "阅读偏好"
    }
  }
};

function getCopy(language) {
  return copy[language] ?? copy.zh;
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

function normalizeResearchProfileItems(items) {
  if (!Array.isArray(items)) {
    return [];
  }
  return items
    .map((item, index) => {
      if (!item || typeof item !== "object") {
        return null;
      }
      const memoryId = String(item.memory_id ?? item.memoryId ?? item.id ?? "").trim();
      const kind = String(item.kind ?? item.node_type ?? "expertise_signal").trim();
      const label = String(item.label ?? item.summary ?? item.text ?? "").trim();
      const evidence = Array.isArray(item.evidence)
        ? item.evidence.map((entry) => String(entry || "").trim()).filter(Boolean).slice(0, 6)
        : [];
      if (!memoryId || !label) {
        return null;
      }
      return {
        memoryId,
        kind,
        label,
        evidence,
        confidence: typeof item.confidence === "number" ? item.confidence : null,
        pinned: Boolean(item.pinned),
        key: `${memoryId}-${kind}-${index}`
      };
    })
    .filter(Boolean);
}

function groupProfileItems(items) {
  return items.reduce((groups, item) => {
    const key = item.kind || "expertise_signal";
    return { ...groups, [key]: [...(groups[key] || []), item] };
  }, {});
}

export default function ResearchProfilePage({ language, assistantSessionId, onAssistantSessionIdChange }) {
  const t = getCopy(language);
  const mountedRef = useRef(false);
  const [profile, setProfile] = useState({
    enabled: true,
    available: true,
    notice: "",
    items: [],
    loading: false,
    error: ""
  });
  const [actionBusyMap, setActionBusyMap] = useState({});

  const groupedItems = useMemo(() => groupProfileItems(profile.items), [profile.items]);
  const sectionKinds = ["expertise_signal", "research_direction", "reading_preference"];

  async function loadProfile({ refresh = false } = {}) {
    const resolvedSessionId = String(assistantSessionId || "").trim();
    if (!resolvedSessionId) {
      return;
    }
    setProfile((current) => ({ ...current, loading: true, error: "" }));
    try {
      const url = refresh
        ? "/api/live2d/research-profile/refresh"
        : `/api/live2d/research-profile?session_id=${encodeURIComponent(resolvedSessionId)}`;
      const response = await fetch(url, {
        method: refresh ? "POST" : "GET",
        headers: refresh ? { "Content-Type": "application/json" } : undefined,
        body: refresh ? JSON.stringify({ session_id: resolvedSessionId }) : undefined
      });
      const payload = await readJsonWithDetailFallback(response);
      if (!response.ok) {
        throw new Error(payload.detail || `HTTP ${response.status}`);
      }
      if (!mountedRef.current) {
        return;
      }
      setProfile({
        enabled: payload.enabled !== false,
        available: payload.available !== false,
        notice: String(payload.notice || "").trim(),
        items: normalizeResearchProfileItems(payload.items),
        loading: false,
        error: ""
      });
    } catch (err) {
      if (mountedRef.current) {
        setProfile((current) => ({
          ...current,
          available: true,
          notice: "",
          loading: false,
          error: String(err || t.unavailable)
        }));
      }
    }
  }

  function updateProfileItems(memoryId, updater) {
    if (!memoryId) {
      return;
    }
    setProfile((current) => ({
      ...current,
      items: current.items.map((item) => (item.memoryId === memoryId ? updater(item) : item)).filter(Boolean)
    }));
  }

  async function handleMemoryAction(profileItem, action) {
    const memoryId = String(profileItem?.memoryId || "").trim();
    if (!memoryId) {
      return;
    }
    setProfile((current) => ({ ...current, error: "" }));
    setActionBusyMap((current) => ({ ...current, [memoryId]: action }));
    try {
      const sessionQuery = assistantSessionId
        ? `?session_id=${encodeURIComponent(String(assistantSessionId).trim())}`
        : "";
      const url =
        action === "pin"
          ? `/api/live2d/memory/${encodeURIComponent(memoryId)}/pin${sessionQuery}`
          : `/api/live2d/memory/${encodeURIComponent(memoryId)}${sessionQuery}`;
      const response = await fetch(url, {
        method: action === "pin" ? "POST" : "DELETE",
        headers: action === "pin" ? { "Content-Type": "application/json" } : undefined,
        body: action === "pin" ? JSON.stringify({ pinned: true }) : undefined
      });
      const payload = await readJsonWithDetailFallback(response);
      if (!response.ok) {
        if (response.status === 404 || response.status === 405) {
          throw new Error(t.actionUnavailable);
        }
        throw new Error(payload.detail || `HTTP ${response.status}`);
      }
      const nextSessionId = String(payload.session_id || "").trim();
      if (nextSessionId && typeof onAssistantSessionIdChange === "function") {
        onAssistantSessionIdChange(nextSessionId);
      }
      if (action === "pin") {
        updateProfileItems(memoryId, (item) => ({ ...item, pinned: true }));
      } else {
        updateProfileItems(memoryId, () => null);
      }
    } catch (err) {
      if (mountedRef.current) {
        setProfile((current) => ({ ...current, error: String(err || t.unavailable) }));
      }
    } finally {
      if (mountedRef.current) {
        setActionBusyMap((current) => {
          const next = { ...current };
          delete next[memoryId];
          return next;
        });
      }
    }
  }

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    void loadProfile();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assistantSessionId]);

  const emptyMessage = !profile.available
    ? profile.notice || t.needsMemory
    : profile.enabled
      ? t.empty
      : t.disabled;

  return (
    <section className="workspace research-profile-page">
      <div className="research-profile-head">
        <div>
          <h3>{t.title}</h3>
          <p className="muted">{t.description}</p>
        </div>
        <button type="button" onClick={() => void loadProfile({ refresh: true })} disabled={profile.loading || !assistantSessionId}>
          {profile.loading ? t.loading : t.refresh}
        </button>
      </div>

      {profile.error ? <div className="warning-box">{profile.error}</div> : null}

      {profile.items.length ? (
        <div className="research-profile-grid">
          {sectionKinds.map((kind) => {
            const items = groupedItems[kind] || [];
            return (
              <section key={kind} className="research-profile-section">
                <div className="research-profile-section-head">
                  <h4>{t.kind[kind]}</h4>
                  <span>{items.length}</span>
                </div>
                {items.length ? (
                  <div className="research-profile-list">
                    {items.map((item) => {
                      const actionBusy = actionBusyMap[item.memoryId];
                      const confidenceText =
                        typeof item.confidence === "number" ? `${Math.round(item.confidence * 100)}%` : "";
                      return (
                        <article key={item.key} className="research-profile-item">
                          <div className="research-profile-item-head">
                            {confidenceText ? <span>{confidenceText}</span> : <span>{t.kind[item.kind] || item.kind}</span>}
                            {item.pinned ? <strong>{t.pinned}</strong> : null}
                          </div>
                          <p>{item.label}</p>
                          {item.evidence.length ? (
                            <p className="research-profile-evidence">
                              {t.evidence}: {item.evidence.join(" / ")}
                            </p>
                          ) : null}
                          <div className="assistant-memory-item-actions">
                            <button
                              type="button"
                              className="secondary"
                              onClick={() => void handleMemoryAction(item, "pin")}
                              disabled={Boolean(actionBusy) || item.pinned}
                            >
                              {item.pinned ? t.pinned : t.pin}
                            </button>
                            <button
                              type="button"
                              className="secondary"
                              onClick={() => void handleMemoryAction(item, "delete")}
                              disabled={Boolean(actionBusy)}
                            >
                              {t.delete}
                            </button>
                          </div>
                        </article>
                      );
                    })}
                  </div>
                ) : (
                  <p className="research-profile-empty">{t.empty}</p>
                )}
              </section>
            );
          })}
        </div>
      ) : (
        <p className="research-profile-empty">{profile.loading ? t.loading : emptyMessage}</p>
      )}
    </section>
  );
}
