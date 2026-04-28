function formatTimeLabel(updatedAt) {
  if (!updatedAt) {
    return "";
  }
  try {
    const date = new Date(updatedAt);
    if (Number.isNaN(date.getTime())) {
      return "";
    }
    return date.toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit"
    });
  } catch (_) {
    return "";
  }
}

function stepVisualState(index, activeIndex, status) {
  if (activeIndex < 0) {
    return "pending";
  }
  if (index < activeIndex) {
    return "complete";
  }
  if (index > activeIndex) {
    return "pending";
  }
  if (status === "interrupted") {
    return "error";
  }
  if (status === "running") {
    return "active";
  }
  if (status === "ready" || status === "completed") {
    return "complete";
  }
  return "active";
}

export default function ProgressTracker({
  title,
  subtitle,
  steps,
  currentStep,
  status,
  statusLabel,
  detail,
  updatedAt
}) {
  const activeIndex = steps.findIndex((step) => step.key === currentStep);
  const updatedLabel = formatTimeLabel(updatedAt);

  return (
    <section className="config-section progress-tracker-card" aria-live="polite">
      <div className="progress-tracker-head">
        <div>
          <h3>{title}</h3>
          {subtitle ? <p className="muted">{subtitle}</p> : null}
        </div>
        <div className={`progress-liveness progress-liveness-${status || "idle"}`}>
          <span className="progress-liveness-dot" aria-hidden="true" />
          <span>{statusLabel}</span>
        </div>
      </div>

      {detail ? <p className="progress-detail">{detail}</p> : null}
      {updatedLabel ? <p className="muted progress-updated-at">{updatedLabel}</p> : null}

      <div className="progress-step-list" role="list">
        {steps.map((step, index) => {
          const visualState = stepVisualState(index, activeIndex, status);
          return (
            <div key={step.key} className={`progress-step progress-step-${visualState}`} role="listitem">
              <div className="progress-step-marker" aria-hidden="true">
                <span className="progress-step-marker-core" />
              </div>
              <div className="progress-step-body">
                <p className="progress-step-title">{step.label}</p>
                {step.description ? <p className="progress-step-description">{step.description}</p> : null}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
