import { useEffect, useMemo, useRef, useState } from "react";
import ProgressTracker from "./ProgressTracker.jsx";

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

function isPlainObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function looksLikeStructuredText(text) {
  const normalized = String(text || "").trim();
  if (!normalized || (normalized[0] !== "{" && normalized[0] !== "[")) {
    return false;
  }
  try {
    const parsed = JSON.parse(normalized);
    return isPlainObject(parsed) || Array.isArray(parsed);
  } catch (_) {
    return false;
  }
}

function sanitizeText(value) {
  if (value === 0 || value === false) {
    return String(value);
  }
  if (typeof value === "string") {
    const text = value.trim();
    if (!text || looksLikeStructuredText(text)) {
      return "";
    }
    return text;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return "";
}

function firstNonEmpty(...values) {
  for (const value of values) {
    if (Array.isArray(value)) {
      const nested = firstNonEmpty(...value);
      if (nested || nested === 0 || nested === false) {
        return nested;
      }
      continue;
    }
    if (isPlainObject(value)) {
      continue;
    }
    if (value === 0) {
      return 0;
    }
    if (value === false) {
      return false;
    }
    const text = sanitizeText(value);
    if (text) {
      return text;
    }
  }
  return "";
}

function toNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function normalizeStatus(value) {
  const status = String(value || "").trim().toLowerCase();
  if (["queued", "generating", "ready", "error"].includes(status)) {
    return status;
  }
  return status || "queued";
}

const PAPER_READER_DISCIPLINE_OPTIONS = [
  { value: "auto", zh: "自动识别", en: "Auto detect" },
  { value: "general", zh: "通用论文", en: "General" },
  { value: "science_engineering", zh: "科学/工程论文", en: "Science / engineering" },
  { value: "mathematics", zh: "数学文章", en: "Mathematics" },
  { value: "medicine_biology", zh: "医学/生物文章", en: "Medicine / biology" },
  { value: "economics_social_science", zh: "经济/社会科学文章", en: "Economics / social science" },
  { value: "philosophy_humanities", zh: "哲学/人文文章", en: "Philosophy / humanities" },
  { value: "policy_law", zh: "政策/法律文章", en: "Policy / law" }
];

function normalizeDiscipline(value, fallback = "general") {
  const normalized = String(value || "").trim().toLowerCase().replaceAll("-", "_").replaceAll(" ", "_");
  return PAPER_READER_DISCIPLINE_OPTIONS.some((option) => option.value === normalized) ? normalized : fallback;
}

function getDisciplineLabel(value, language) {
  const normalized = normalizeDiscipline(value, "general");
  const option = PAPER_READER_DISCIPLINE_OPTIONS.find((item) => item.value === normalized);
  return option ? option[language === "zh" ? "zh" : "en"] : normalized;
}

function getDisciplineSourceLabel(source, language) {
  const normalized = String(source || "").trim().toLowerCase();
  if (language === "zh") {
    return normalized === "manual" ? "手动选择" : "自动识别";
  }
  return normalized === "manual" ? "manual" : "auto detected";
}

function toArray(raw) {
  if (Array.isArray(raw)) {
    return raw;
  }
  if (typeof raw === "string" && looksLikeStructuredText(raw)) {
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        return parsed;
      }
      if (isPlainObject(parsed)) {
        return toArray(parsed.items || parsed.cards || parsed.list);
      }
    } catch (_) {
      return [];
    }
  }
  if (isPlainObject(raw)) {
    return toArray(raw.items || raw.cards || raw.list);
  }
  return [];
}

function splitListText(text) {
  return String(text || "")
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .split("\n")
    .map((item) => item.replace(/^\s*(?:[-*]|\d+[.)])\s*/, "").trim())
    .filter(Boolean);
}

function normalizeList(raw) {
  const items = toArray(raw);
  if (items.length) {
    return items
      .flatMap((item) => {
        if (typeof item === "string") {
          return splitListText(sanitizeText(item));
        }
        if (!isPlainObject(item)) {
          return splitListText(sanitizeText(item));
        }
        return splitListText(
          firstNonEmpty(item.text, item.summary, item.content, item.note, item.label, item.title, item.value)
        );
      })
      .filter(Boolean);
  }
  const text = sanitizeText(raw);
  return text ? splitListText(text) : [];
}

function normalizeCitations(raw) {
  return toArray(raw)
    .map((item, index) => {
      if (typeof item === "string") {
        const text = sanitizeText(item);
        return text
          ? {
              chunk_id: "",
              label: text,
              text,
              excerpt: "",
              section_title: "",
              subsection_title: "",
              page_start: null,
              page_end: null,
              score: null,
              index
            }
          : null;
      }
      if (!isPlainObject(item)) {
        return null;
      }
      return {
        chunk_id: firstNonEmpty(item.chunk_id, item.chunkId),
        label: firstNonEmpty(
          item.label,
          item.title,
          item.section_title,
          item.sectionTitle,
          item.chunk_id,
          item.chunkId,
          `citation-${index + 1}`
        ),
        text: firstNonEmpty(item.text, item.excerpt, item.summary, item.content, item.note, item.label, item.title),
        excerpt: firstNonEmpty(item.excerpt, item.text, item.content),
        section_title: firstNonEmpty(item.section_title, item.sectionTitle, item.section, item.chapter),
        subsection_title: firstNonEmpty(item.subsection_title, item.subsectionTitle, item.subsection),
        page_start: item.page_start ?? item.pageStart ?? item.start_page ?? item.startPage ?? null,
        page_end: item.page_end ?? item.pageEnd ?? item.end_page ?? item.endPage ?? null,
        score: typeof item.score === "number" ? item.score : null
      };
    })
    .filter(Boolean);
}

function normalizeSections(raw) {
  return toArray(raw)
    .map((item, index) => {
      if (typeof item === "string") {
        const text = sanitizeText(item);
        return text ? { title: `Section ${index + 1}`, text, bullets: [], citations: [] } : null;
      }
      if (!isPlainObject(item)) {
        return null;
      }
      return {
        title: firstNonEmpty(item.title, item.heading, item.section_title, item.sectionTitle, item.name, `Section ${index + 1}`),
        text: firstNonEmpty(item.text, item.summary, item.content, item.body, item.note),
        bullets: normalizeList(item.bullets || item.points || item.key_points || item.keyPoints || item.highlights),
        citations: normalizeCitations(
          item.citations || item.references || item.supporting_citations || item.supportingCitations
        )
      };
    })
    .filter(Boolean);
}

function hasCjkCharacters(text) {
  return /[\u3400-\u9fff]/.test(String(text || ""));
}

function splitReaderContent(raw) {
  const text = sanitizeText(raw);
  if (!text) {
    return { original: "", explanation: "" };
  }

  const normalized = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n").trim();
  const inlineParts = normalized.split(/\s+\|\s+/).map((part) => part.trim()).filter(Boolean);
  if (inlineParts.length > 1) {
    const originalPart = inlineParts.find((part) => /^Original\s*\(EN\)\s*:/i.test(part)) || inlineParts[0];
    const explanationParts = inlineParts.filter((part) => part !== originalPart);
    return {
      original: originalPart.replace(/^Original\s*\(EN\)\s*:\s*/i, "").trim(),
      explanation: explanationParts.map((part) => part.replace(/^[^:]+:\s*/, "").trim()).join(" ").trim()
    };
  }

  const lines = normalized.split("\n").map((line) => line.trim()).filter(Boolean);
  const originalLines = [];
  const explanationLines = [];
  let explanationStarted = false;

  lines.forEach((line) => {
    if (/^Original\s*\(EN\)\s*:/i.test(line)) {
      originalLines.push(line.replace(/^Original\s*\(EN\)\s*:\s*/i, "").trim());
      return;
    }
    if (/^[^:]{2,40}:\s*/.test(line)) {
      explanationLines.push(line.replace(/^[^:]+:\s*/, "").trim());
      explanationStarted = true;
      return;
    }
    if (!originalLines.length && !explanationStarted && !hasCjkCharacters(line)) {
      originalLines.push(line);
      return;
    }
    explanationLines.push(line);
  });

  const original = originalLines.join(" ").trim();
  const explanation = explanationLines.join(" ").trim();

  if (!original && !explanation) {
    return hasCjkCharacters(normalized) ? { original: "", explanation: normalized } : { original: normalized, explanation: "" };
  }
  if (!original && explanation && !hasCjkCharacters(explanation)) {
    return { original: explanation, explanation: "" };
  }
  return { original, explanation };
}

function normalizeStructuredText(raw) {
  if (typeof raw === "string") {
    const pair = splitReaderContent(raw);
    const original = firstNonEmpty(pair.original);
    const explanation = firstNonEmpty(pair.explanation);
    const displayText = firstNonEmpty(explanation, original, sanitizeText(raw));
    if (!original && !explanation && !displayText) {
      return null;
    }
    return {
      original_en: original,
      explanation,
      display_text: displayText
    };
  }
  if (!isPlainObject(raw)) {
    return null;
  }
  const pair = splitReaderContent(
    firstNonEmpty(
      raw.display_text,
      raw.displayText,
      raw.text,
      raw.content,
      raw.summary,
      raw.message,
      raw.body
    )
  );
  const original = firstNonEmpty(
    raw.original_en,
    raw.originalEn,
    raw.original_text,
    raw.originalText,
    raw.original_excerpt,
    raw.originalExcerpt,
    raw.original,
    raw.quote,
    pair.original
  );
  const explanation = firstNonEmpty(
    raw.explanation,
    raw.localized_explanation,
    raw.localizedExplanation,
    raw.translation,
    raw.interpretation,
    pair.explanation
  );
  const displayText = firstNonEmpty(raw.display_text, raw.displayText, explanation, original, pair.explanation, pair.original);
  if (!original && !explanation && !displayText) {
    return null;
  }
  return {
    original_en: original,
    explanation,
    display_text: displayText
  };
}

function sameNormalizedReadingText(left, right) {
  const leftKey = sanitizeText(left).toLocaleLowerCase();
  const rightKey = sanitizeText(right).toLocaleLowerCase();
  return Boolean(leftKey && rightKey && leftKey === rightKey);
}

function localizedReadingText(value, original) {
  const text = sanitizeText(value);
  if (!text || sameNormalizedReadingText(text, original)) {
    return "";
  }
  return text;
}

function normalizeReadingBlocks(raw) {
  return toArray(raw)
    .map((item, index) => {
      if (typeof item === "string") {
        const text = sanitizeText(item);
        return text
          ? {
              chunk_id: `reading-block-${index + 1}`,
              source_label: `Section ${index + 1}`,
              page_start: null,
              page_end: null,
              original_en: text,
              explanation: "",
              display_text: ""
            }
          : null;
      }
      if (!isPlainObject(item)) {
        return null;
      }
      const original = firstNonEmpty(
        item.original_en,
        item.originalEn,
        item.original_text,
        item.originalText,
        item.text,
        item.content
      );
      const explanation = localizedReadingText(
        firstNonEmpty(item.explanation, item.translation, item.localized_explanation, item.localizedExplanation),
        original
      );
      const displayText = localizedReadingText(firstNonEmpty(item.display_text, item.displayText), original) || explanation;
      const chunkId = firstNonEmpty(item.chunk_id, item.chunkId, item.id, `reading-block-${index + 1}`);
      if (!original && !displayText) {
        return null;
      }
      return {
        chunk_id: chunkId,
        source_label: firstNonEmpty(item.source_label, item.sourceLabel, item.label, item.section_title, item.sectionTitle, `Section ${index + 1}`),
        page_start: item.page_start ?? item.pageStart ?? null,
        page_end: item.page_end ?? item.pageEnd ?? null,
        original_en: original || displayText,
        explanation,
        display_text: displayText
      };
    })
    .filter(Boolean);
}

function normalizeStructuredStatus(raw) {
  if (!isPlainObject(raw)) {
    return {
      state: "pending",
      format: "insight_cards_v1",
      message: "",
      repair_attempted: false
    };
  }
  const state = String(raw.state || "").trim().toLowerCase();
  return {
    state: ["pending", "ready", "repaired", "failed"].includes(state) ? state : "pending",
    format: firstNonEmpty(raw.format, raw.version, "insight_cards_v1"),
    message: firstNonEmpty(raw.message, raw.detail),
    repair_attempted: Boolean(raw.repair_attempted ?? raw.repairAttempted)
  };
}

function normalizeSourceSections(raw) {
  return toArray(raw)
    .map((item) => {
      if (!isPlainObject(item)) {
        return null;
      }
      const title = firstNonEmpty(item.title, item.section_title, item.sectionTitle);
      const subsectionTitle = firstNonEmpty(item.subsection_title, item.subsectionTitle, item.subsection);
      const label = firstNonEmpty(item.label, [title, subsectionTitle].filter(Boolean).join(" - "));
      if (!label) {
        return null;
      }
      return {
        title,
        subsection_title: subsectionTitle,
        label,
        page_start: item.page_start ?? item.pageStart ?? null,
        page_end: item.page_end ?? item.pageEnd ?? null,
        chunk_ids: toArray(item.chunk_ids || item.chunkIds)
          .map((chunkId) => sanitizeText(chunkId))
          .filter(Boolean)
      };
    })
    .filter(Boolean);
}

function normalizeIndexNode(raw) {
  if (!isPlainObject(raw)) {
    return null;
  }
  const nodeId = firstNonEmpty(raw.node_id, raw.nodeId, raw.id, raw.key);
  const title = firstNonEmpty(raw.title, raw.label, raw.name);
  if (!nodeId || !title) {
    return null;
  }
  const children = toArray(raw.children || raw.nodes || raw.items)
    .map((item) => normalizeIndexNode(item))
    .filter(Boolean);
  return {
    node_id: nodeId,
    title,
    summary: firstNonEmpty(raw.summary, raw.description, raw.text),
    reading_focus_key: firstNonEmpty(raw.reading_focus_key, raw.readingFocusKey, raw.focus_key, raw.focusKey),
    page_start: raw.page_start ?? raw.pageStart ?? null,
    page_end: raw.page_end ?? raw.pageEnd ?? null,
    page_indices: toArray(raw.page_indices || raw.pageIndices)
      .map((item) => toNumber(item, null))
      .filter((item) => item != null),
    chunk_ids: toArray(raw.chunk_ids || raw.chunkIds)
      .map((item) => sanitizeText(item))
      .filter(Boolean),
    children
  };
}

function flattenIndexNodes(root) {
  if (!root) {
    return [];
  }
  return [root, ...toArray(root.children).flatMap((child) => flattenIndexNodes(child))];
}

function normalizeSelectedNodes(raw) {
  return toArray(raw)
    .map((item) => {
      if (!isPlainObject(item)) {
        return null;
      }
      const nodeId = firstNonEmpty(item.node_id, item.nodeId, item.id);
      const title = firstNonEmpty(item.title, item.label, item.name);
      if (!nodeId || !title) {
        return null;
      }
      return {
        node_id: nodeId,
        title,
        summary: firstNonEmpty(item.summary, item.description),
        page_start: item.page_start ?? item.pageStart ?? null,
        page_end: item.page_end ?? item.pageEnd ?? null,
        page_indices: toArray(item.page_indices || item.pageIndices)
          .map((value) => toNumber(value, null))
          .filter((value) => value != null),
        reason: firstNonEmpty(item.reason, item.why)
      };
    })
    .filter(Boolean);
}

function normalizeStoryStage(raw) {
  if (!isPlainObject(raw)) {
    return null;
  }
  const title = firstNonEmpty(raw.title, raw.name, raw.label);
  if (!title) {
    return null;
  }
  return {
    key: firstNonEmpty(raw.key, raw.id, "reading_stage"),
    title,
    description: firstNonEmpty(raw.description, raw.summary, raw.text)
  };
}

function normalizeBlackboardNotes(raw) {
  if (!isPlainObject(raw)) {
    return null;
  }
  const notes = {
    core_concepts: normalizeList(raw.core_concepts || raw.coreConcepts || raw.concepts),
    method_steps: normalizeList(raw.method_steps || raw.methodSteps || raw.steps),
    experiment_takeaways: normalizeList(raw.experiment_takeaways || raw.experimentTakeaways || raw.results || raw.evidence),
    takeaway: firstNonEmpty(raw.takeaway, raw.summary, raw.text)
  };
  if (
    !notes.core_concepts.length &&
    !notes.method_steps.length &&
    !notes.experiment_takeaways.length &&
    !notes.takeaway
  ) {
    return null;
  }
  return notes;
}

function normalizeDisciplineGuide(raw) {
  if (!isPlainObject(raw)) {
    return null;
  }
  const discipline = normalizeDiscipline(raw.discipline, "general");
  const panels = toArray(raw.panels || raw.sections || raw.items)
    .map((item, index) => {
      if (!isPlainObject(item)) {
        const text = sanitizeText(item);
        return text
          ? {
              key: `panel_${index + 1}`,
              title: `Panel ${index + 1}`,
              items: [text],
              takeaway: ""
            }
          : null;
      }
      const title = firstNonEmpty(item.title, item.label, item.name, `Panel ${index + 1}`);
      const items = normalizeList(item.items || item.points || item.bullets || item.children);
      const takeaway = firstNonEmpty(item.takeaway, item.summary, item.text);
      if (!title || (!items.length && !takeaway)) {
        return null;
      }
      return {
        key: firstNonEmpty(item.key, item.id, `panel_${index + 1}`),
        title,
        items,
        takeaway
      };
    })
    .filter(Boolean);
  if (!panels.length) {
    return null;
  }
  return {
    discipline,
    title: firstNonEmpty(raw.title, raw.heading, getDisciplineLabel(discipline, "en")),
    panels
  };
}

function normalizeGlossaryTerms(raw) {
  return toArray(raw)
    .map((item) => {
      if (!isPlainObject(item)) {
        return null;
      }
      const term = firstNonEmpty(item.term, item.name, item.symbol);
      const explanation = firstNonEmpty(item.explanation, item.meaning, item.description, item.text);
      if (!term || !explanation) {
        return null;
      }
      return {
        term,
        explanation,
        source: firstNonEmpty(item.source, item.background ? "background" : "paper"),
        citation: normalizeCitations(item.citation ? [item.citation] : item.citations)[0] || null
      };
    })
    .filter(Boolean);
}

function normalizeReadingHints(raw) {
  return toArray(raw)
    .map((item) => {
      if (typeof item === "string") {
        const text = sanitizeText(item);
        return text ? { kind: "must_know", text, reason: "" } : null;
      }
      if (!isPlainObject(item)) {
        return null;
      }
      const text = firstNonEmpty(item.text, item.title, item.summary);
      if (!text) {
        return null;
      }
      const kind = firstNonEmpty(item.kind, item.type, "must_know").replaceAll("-", "_");
      return {
        kind: ["must_know", "skim", "advanced"].includes(kind) ? kind : "must_know",
        text,
        reason: firstNonEmpty(item.reason, item.why, item.description)
      };
    })
    .filter(Boolean);
}

function normalizeCheckpoints(raw) {
  return toArray(raw)
    .map((item, index) => {
      if (!isPlainObject(item)) {
        return null;
      }
      const question = firstNonEmpty(item.question, item.prompt);
      const answer = firstNonEmpty(item.answer, item.reference_answer, item.referenceAnswer, item.solution);
      if (!question || !answer) {
        return null;
      }
      return {
        id: firstNonEmpty(item.id, `checkpoint-${index + 1}`),
        question,
        answer,
        review_hint: firstNonEmpty(item.review_hint, item.reviewHint, item.hint, item.look_back, item.lookBack),
        source_page_index: item.source_page_index ?? item.sourcePageIndex ?? null
      };
    })
    .filter(Boolean);
}

function firstSentence(text, maxLength = 180) {
  const normalized = sanitizeText(text);
  if (!normalized) {
    return "";
  }
  const first = normalized.split(/(?<=[。！？.!?])\s+/)[0] || normalized;
  return first.length > maxLength ? `${first.slice(0, maxLength).trim()}...` : first;
}

function exactTextKey(value) {
  return sanitizeText(value).replace(/\s+/g, " ").trim().toLowerCase();
}

function normalizeWhyItems(raw) {
  const items = toArray(raw);
  const source = items.length ? items : normalizeList(raw);
  return source
    .map((item) => {
      if (typeof item === "string") {
        const pair = splitReaderContent(item);
        const explanation = firstNonEmpty(pair.explanation, pair.original);
        return explanation ? { original: pair.original, explanation } : null;
      }
      if (!isPlainObject(item)) {
        return null;
      }
      const contentPair = splitReaderContent(firstNonEmpty(item.content, item.body, item.message));
      const original = firstNonEmpty(
        item.original_text,
        item.originalText,
        item.original_excerpt,
        item.originalExcerpt,
        item.original,
        item.quote,
        item.excerpt,
        contentPair.original
      );
      const explanation = firstNonEmpty(
        item.explanation,
        item.interpretation,
        item.description,
        item.summary,
        item.text,
        item.note,
        item.reason,
        item.display_text,
        item.displayText,
        contentPair.explanation,
        contentPair.original
      );
      return explanation ? { original, explanation } : null;
    })
    .filter(Boolean);
}

function dedupeWhyItems(items, duplicateCandidates = []) {
  const duplicateKeys = new Set(duplicateCandidates.map((item) => exactTextKey(item)).filter(Boolean));
  const seen = new Set();
  return toArray(items)
    .filter(Boolean)
    .filter((item) => {
      const key = exactTextKey(firstNonEmpty(item.explanation, item.original));
      if (!key || duplicateKeys.has(key) || seen.has(key)) {
        return false;
      }
      seen.add(key);
      return true;
    });
}

function cleanWhyItems(items, duplicateCandidates = []) {
  return dedupeWhyItems(normalizeWhyItems(items), duplicateCandidates).slice(0, 2);
}

function evidenceDuplicateCandidates({ originalText, explanationText, summaryBlock, evidenceBlocks, supportingPoints }) {
  return [
    originalText,
    explanationText,
    summaryBlock?.original_en,
    summaryBlock?.explanation,
    summaryBlock?.display_text,
    ...toArray(evidenceBlocks).flatMap((block) => [block?.original_en, block?.explanation, block?.display_text]),
    ...toArray(supportingPoints)
  ];
}

function BilingualReaderBlock({ block, original, explanation, copy, compact = false }) {
  const originalText = firstNonEmpty(original, block?.original_en, copy.noOriginal);
  const explanationText = firstNonEmpty(explanation, block?.explanation, block?.display_text, copy.noExplanation);
  return (
    <div className={`reader-bilingual-block${compact ? " reader-bilingual-block-compact" : ""}`}>
      <div className="reader-bilingual-primary">
        <span className="reader-tone-label">{copy.explanationLabel}</span>
        <p>{explanationText}</p>
      </div>
      <details className="reader-original-disclosure">
        <summary>{copy.showOriginalLabel}</summary>
        <p>{originalText}</p>
      </details>
    </div>
  );
}

function scrollToReaderModule(moduleId) {
  const target = document.getElementById(moduleId);
  if (target) {
    target.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function stripPageCountSuffix(title) {
  const text = sanitizeText(title);
  if (!text) {
    return "";
  }
  return text.replace(/\s*\(\d+\s*\/\s*\d+\)\s*$/, "").trim();
}

function extractPageCounter(title) {
  const text = sanitizeText(title);
  if (!text) {
    return "";
  }
  const match = text.match(/\((\d+)\s*\/\s*(\d+)\)\s*$/);
  return match ? `${match[1]}/${match[2]}` : "";
}

function normalizeCoverage(...values) {
  for (const value of values) {
    if (Array.isArray(value) && value.length >= 2) {
      const start = sanitizeText(value[0]);
      const end = sanitizeText(value[1]);
      if (start || end) {
        return [start, end].filter(Boolean).join("-");
      }
    }
    if (isPlainObject(value)) {
      const start = value.page_start ?? value.pageStart ?? value.start ?? value.from ?? null;
      const end = value.page_end ?? value.pageEnd ?? value.end ?? value.to ?? null;
      if (start != null || end != null) {
        return `${start ?? "?"}-${end ?? "?"}`;
      }
      continue;
    }
    const text = sanitizeText(value);
    if (text) {
      return text;
    }
  }
  return "";
}

function deriveBucketLabel(pageLike) {
  const explicit = firstNonEmpty(
    pageLike?.bucket_label,
    pageLike?.bucketLabel,
    pageLike?.bucket_title,
    pageLike?.bucketTitle,
    pageLike?.focus_title,
    pageLike?.focusTitle,
    pageLike?.reading_focus_title,
    pageLike?.readingFocusTitle,
    pageLike?.group_title,
    pageLike?.groupTitle
  );
  if (explicit) {
    return explicit;
  }
  return firstNonEmpty(stripPageCountSuffix(pageLike?.title), pageLike?.coverage);
}

function normalizeInsightCard(raw, index, fallback = {}) {
  if (typeof raw === "string") {
    const pair = splitReaderContent(raw);
    const originalText = firstNonEmpty(pair.original, fallback.original_text);
    const explanationText = firstNonEmpty(pair.explanation, fallback.explanation_text);
    if (!originalText && !explanationText) {
      return null;
    }
    return {
      id: firstNonEmpty(fallback.id, `insight-${index + 1}`),
      title: firstNonEmpty(fallback.title, `Insight ${index + 1}`),
      eyebrow: firstNonEmpty(fallback.eyebrow),
      original_text: originalText,
      explanation_text: explanationText,
      why_it_matters: cleanWhyItems(fallback.why_it_matters || [], [originalText, explanationText]),
      citations: fallback.citations || [],
      supporting_points: fallback.supporting_points || [],
      source_chunk_ids: fallback.source_chunk_ids || [],
      source_section_labels: fallback.source_section_labels || []
    };
  }
  if (!isPlainObject(raw)) {
    return null;
  }

  const summaryBlock = normalizeStructuredText(raw.summary);
  const evidenceBlocks = toArray(raw.evidence).map((item) => normalizeStructuredText(item)).filter(Boolean);
  const contentPair = splitReaderContent(firstNonEmpty(raw.content, raw.body, raw.message));
  const textPair = splitReaderContent(firstNonEmpty(raw.text, raw.summary, raw.note, raw.analysis, raw.description));
  const citations = normalizeCitations(
    raw.citations || raw.references || raw.supporting_citations || raw.supportingCitations || raw.sources
  );
  const sourceSectionLabels = toArray(raw.source_section_labels || raw.sourceSectionLabels)
    .map((item) => sanitizeText(item))
    .filter(Boolean);
  const sourceChunkIds = toArray(raw.source_chunk_ids || raw.sourceChunkIds || raw.chunk_ids || raw.chunkIds)
    .map((item) => sanitizeText(item))
    .filter(Boolean);
  const rawWhyItems =
    raw.why_it_matters ||
      raw.whyItMatters ||
      raw.significance ||
      raw.importance ||
      raw.takeaway ||
      raw.takeaways ||
      raw.relevance ||
      raw.notes;

  const originalText = firstNonEmpty(
    raw.original_text,
    raw.originalText,
    raw.original_excerpt,
    raw.originalExcerpt,
    raw.original,
    raw.quote,
    raw.evidence,
    raw.excerpt,
    raw.source_text,
    raw.sourceText,
    raw.english_text,
    raw.englishText,
    raw.english,
    summaryBlock?.original_en,
    evidenceBlocks.map((block) => block?.original_en),
    contentPair.original,
    textPair.original,
    fallback.original_text
  );
  const explanationText = firstNonEmpty(
    raw.explanation,
    raw.interpretation,
    raw.localized_explanation,
    raw.localizedExplanation,
    raw.translation,
    raw.analysis,
    raw.page_language_explanation,
    raw.pageLanguageExplanation,
    raw.page_language_text,
    raw.pageLanguageText,
    raw.summary_text,
    raw.summaryText,
    summaryBlock?.explanation,
    summaryBlock?.display_text,
    evidenceBlocks.map((block) => firstNonEmpty(block?.explanation, block?.display_text)),
    textPair.explanation,
    contentPair.explanation,
    textPair.original,
    fallback.explanation_text
  );

  if (!originalText && !explanationText) {
    return null;
  }

  const supportingPoints = evidenceBlocks
    .map((block) => firstNonEmpty(block?.explanation, block?.display_text, block?.original_en))
    .filter(Boolean)
    .slice(0, 3);

  return {
    id: firstNonEmpty(raw.id, raw.card_id, raw.cardId, raw.key, fallback.id, `insight-${index + 1}`),
    title: firstNonEmpty(raw.title, raw.heading, raw.label, raw.name, fallback.title, `Insight ${index + 1}`),
    eyebrow: firstNonEmpty(
      raw.eyebrow,
      raw.kind,
      raw.category,
      raw.topic,
      raw.bucket,
      raw.bucket_title,
      raw.bucketTitle,
      fallback.eyebrow
    ),
    original_text: originalText,
    explanation_text: explanationText,
    why_it_matters: cleanWhyItems(rawWhyItems || fallback.why_it_matters || [], evidenceDuplicateCandidates({
      originalText,
      explanationText,
      summaryBlock,
      evidenceBlocks,
      supportingPoints
    })),
    citations: citations.length ? citations : fallback.citations || [],
    supporting_points: supportingPoints.length ? supportingPoints : fallback.supporting_points || [],
    source_chunk_ids: sourceChunkIds.length ? sourceChunkIds : fallback.source_chunk_ids || [],
    source_section_labels: sourceSectionLabels.length ? sourceSectionLabels : fallback.source_section_labels || []
  };
}

function buildLegacyInsightCards({
  pageIndex,
  title,
  bucketLabel,
  summary,
  text,
  sections,
  keyPoints,
  limitations,
  citations
}) {
  const summaryPair = splitReaderContent(firstNonEmpty(summary, text));
  const citationFallbackText = firstNonEmpty(
    citations.map((citation) => firstNonEmpty(citation.excerpt, citation.text))
  );

  const sectionCards = sections
    .map((section, index) => {
      const pair = splitReaderContent(section.text);
      const sectionCitations = section.citations?.length ? section.citations : citations;
      const originalText = firstNonEmpty(
        pair.original,
        sectionCitations.map((citation) => firstNonEmpty(citation.excerpt, citation.text)),
        summaryPair.original,
        citationFallbackText
      );
      const explanationText = firstNonEmpty(pair.explanation, summaryPair.explanation, summaryPair.original);
      if (!originalText && !explanationText) {
        return null;
      }
      return {
        id: `page-${pageIndex}-section-${index}`,
        title: firstNonEmpty(section.title, `Insight ${index + 1}`),
        eyebrow: index === 0 ? firstNonEmpty(bucketLabel) : "",
        original_text: originalText,
        explanation_text: explanationText,
        why_it_matters: [],
        citations: sectionCitations.slice(0, 4),
        supporting_points: section.bullets?.slice(0, 3) || [],
        source_chunk_ids: [],
        source_section_labels: [section.title].filter(Boolean)
      };
    })
    .filter(Boolean);

  if (sectionCards.length) {
    return sectionCards.slice(0, 4);
  }

  const cards = [];
  const leadOriginal = firstNonEmpty(summaryPair.original, citationFallbackText);
  const leadExplanation = firstNonEmpty(summaryPair.explanation, hasCjkCharacters(summaryPair.original) ? summaryPair.original : "");

  if (leadOriginal || leadExplanation) {
    cards.push({
      id: `page-${pageIndex}-summary`,
      title: firstNonEmpty(bucketLabel, stripPageCountSuffix(title), `Insight ${pageIndex + 1}`),
      eyebrow: "",
      original_text: leadOriginal,
      explanation_text: leadExplanation,
      why_it_matters: [],
      citations: citations.slice(0, 4),
      supporting_points: [...normalizeList(keyPoints), ...normalizeList(limitations)].slice(0, 3),
      source_chunk_ids: [],
      source_section_labels: [bucketLabel].filter(Boolean)
    });
  }

  if (!cards.length) {
    [...normalizeList(keyPoints), ...normalizeList(limitations)].slice(0, 3).forEach((item, index) => {
      const pair = splitReaderContent(item);
      const originalText = firstNonEmpty(pair.original, leadOriginal, citationFallbackText);
      const explanationText = firstNonEmpty(pair.explanation, pair.original, leadExplanation);
      if (!originalText && !explanationText) {
        return;
      }
      cards.push({
        id: `page-${pageIndex}-point-${index}`,
        title: `${stripPageCountSuffix(title) || "Insight"} ${index + 1}`,
        eyebrow: firstNonEmpty(bucketLabel),
        original_text: originalText,
        explanation_text: explanationText,
        why_it_matters: [],
        citations: citations.slice(0, 4),
        supporting_points: [],
        source_chunk_ids: [],
        source_section_labels: [bucketLabel].filter(Boolean)
      });
    });
  }

  return cards.slice(0, 4);
}

function normalizeInsightCards({
  raw,
  nestedContent,
  pageIndex,
  title,
  bucketLabel,
  summary,
  text,
  sections,
  keyPoints,
  limitations,
  citations
}) {
  const structuredInsights = toArray(
    raw.insights ||
      raw.insight_cards ||
      raw.insightCards ||
      raw.cards ||
      raw.reader_cards ||
      raw.readerCards ||
      nestedContent?.insights ||
      nestedContent?.insight_cards ||
      nestedContent?.insightCards ||
      nestedContent?.cards ||
      nestedContent?.reader_cards ||
      nestedContent?.readerCards
  );

  if (structuredInsights.length) {
    const summaryPair = splitReaderContent(firstNonEmpty(summary, text));
    const normalized = structuredInsights
      .map((item, index) =>
        normalizeInsightCard(item, index, {
          id: `page-${pageIndex}-structured-${index}`,
          title: `${stripPageCountSuffix(title) || "Insight"} ${index + 1}`,
          eyebrow: bucketLabel,
          original_text: summaryPair.original,
          explanation_text: summaryPair.explanation,
          why_it_matters: [],
          citations: citations.slice(0, 4)
        })
      )
      .filter(Boolean);
    if (normalized.length) {
      return normalized.slice(0, 4);
    }
  }

  return buildLegacyInsightCards({
    pageIndex,
    title,
    bucketLabel,
    summary,
    text,
    sections,
    keyPoints,
    limitations,
    citations
  });
}

function mergePageEntry(base, update) {
  if (!base) {
    return update;
  }
  if (!update) {
    return base;
  }
  return {
    ...base,
    ...update,
    sections: update.sections?.length ? update.sections : base.sections || [],
    bullets: update.bullets?.length ? update.bullets : base.bullets || [],
    key_points: update.key_points?.length ? update.key_points : base.key_points || [],
    limitations: update.limitations?.length ? update.limitations : base.limitations || [],
    insights: update.insights?.length ? update.insights : base.insights || [],
    citations: update.citations?.length ? update.citations : base.citations || [],
    reading_blocks: update.reading_blocks?.length ? update.reading_blocks : base.reading_blocks || [],
    source_sections: update.source_sections?.length ? update.source_sections : base.source_sections || [],
    source_node_ids: update.source_node_ids?.length ? update.source_node_ids : base.source_node_ids || [],
    page_overview: update.page_overview || base.page_overview || null,
    mentor_script: update.mentor_script?.length ? update.mentor_script : base.mentor_script || [],
    blackboard_notes: update.blackboard_notes || base.blackboard_notes || null,
    discipline_guide: update.discipline_guide || base.discipline_guide || null,
    story_stage: update.story_stage || base.story_stage || null,
    glossary_terms: update.glossary_terms?.length ? update.glossary_terms : base.glossary_terms || [],
    reading_hints: update.reading_hints?.length ? update.reading_hints : base.reading_hints || [],
    checkpoints: update.checkpoints?.length ? update.checkpoints : base.checkpoints || [],
    structured_status:
      update.structured_status?.state && update.structured_status.state !== "pending"
        ? update.structured_status
        : base.structured_status || normalizeStructuredStatus(null),
    text: update.text || base.text || "",
    summary: update.summary || base.summary || "",
    bucket_label: update.bucket_label || base.bucket_label || ""
  };
}

function normalizePageEntry(raw, fallbackIndex = 0) {
  if (!raw) {
    return null;
  }
  if (typeof raw === "string") {
    const text = sanitizeText(raw);
    return text
      ? {
          page_index: fallbackIndex,
          title: `Page ${fallbackIndex + 1}`,
          status: "ready",
          summary: text,
          text,
          sections: [],
          bullets: [],
          key_points: [],
          limitations: [],
          insights: buildLegacyInsightCards({
            pageIndex: fallbackIndex,
            title: `Page ${fallbackIndex + 1}`,
            bucketLabel: "",
            summary: text,
            text,
            sections: [],
            keyPoints: [],
            limitations: [],
            citations: []
          }),
          citations: [],
          reading_blocks: [
            {
              chunk_id: `page-${fallbackIndex}-text`,
              source_label: `Page ${fallbackIndex + 1}`,
              page_start: null,
              page_end: null,
              original_en: text,
              explanation: "",
              display_text: ""
            }
          ],
          error: ""
        }
      : null;
  }
  if (!isPlainObject(raw)) {
    return null;
  }

  const nestedContent = isPlainObject(raw.content) ? raw.content : null;

  const pageIndex = toNumber(
    raw.page_index ?? raw.pageIndex ?? raw.index ?? nestedContent?.page_index ?? nestedContent?.pageIndex ?? fallbackIndex,
    fallbackIndex
  );
  const title = firstNonEmpty(
    raw.title,
    raw.page_title,
    raw.pageTitle,
    raw.section_title,
    raw.sectionTitle,
    nestedContent?.title,
    nestedContent?.page_title,
    nestedContent?.pageTitle,
    `Page ${pageIndex + 1}`
  );
  const sections = normalizeSections(raw.sections || raw.blocks || nestedContent?.sections || nestedContent?.blocks);
  const bullets = normalizeList(raw.bullets || raw.points || raw.key_points || raw.highlights || nestedContent?.bullets);
  const keyPoints = normalizeList(
    raw.key_points || raw.keyPoints || raw.highlights || nestedContent?.key_points || nestedContent?.keyPoints
  );
  const limitations = normalizeList(raw.limitations || raw.caveats || nestedContent?.limitations || nestedContent?.caveats);
  const citations = normalizeCitations(raw.citations || raw.references || nestedContent?.citations);
  const pageOverview =
    normalizeStructuredText(raw.page_overview || raw.pageOverview || nestedContent?.page_overview || nestedContent?.pageOverview) ||
    normalizeStructuredText(raw.summary || raw.page_summary || raw.pageSummary || raw.overview || nestedContent?.summary);
  const structuredStatus = normalizeStructuredStatus(
    raw.structured_status || raw.structuredStatus || nestedContent?.structured_status || nestedContent?.structuredStatus
  );
  const sourceSections = normalizeSourceSections(
    raw.source_sections || raw.sourceSections || nestedContent?.source_sections || nestedContent?.sourceSections
  );
  const readingBlocks = normalizeReadingBlocks(
    raw.reading_blocks || raw.readingBlocks || nestedContent?.reading_blocks || nestedContent?.readingBlocks
  );
  const mentorScript = toArray(raw.mentor_script || raw.mentorScript || nestedContent?.mentor_script || nestedContent?.mentorScript)
    .map((item) => normalizeStructuredText(item))
    .filter(Boolean);
  const blackboardNotes = normalizeBlackboardNotes(
    raw.blackboard_notes || raw.blackboardNotes || nestedContent?.blackboard_notes || nestedContent?.blackboardNotes
  );
  const disciplineGuide = normalizeDisciplineGuide(
    raw.discipline_guide || raw.disciplineGuide || nestedContent?.discipline_guide || nestedContent?.disciplineGuide
  );
  const storyStage = normalizeStoryStage(raw.story_stage || raw.storyStage || nestedContent?.story_stage || nestedContent?.storyStage);
  const glossaryTerms = normalizeGlossaryTerms(
    raw.glossary_terms || raw.glossaryTerms || nestedContent?.glossary_terms || nestedContent?.glossaryTerms
  );
  const readingHints = normalizeReadingHints(
    raw.reading_hints || raw.readingHints || nestedContent?.reading_hints || nestedContent?.readingHints
  );
  const checkpoints = normalizeCheckpoints(
    raw.checkpoints || raw.quiz || nestedContent?.checkpoints || nestedContent?.quiz
  );
  const sourceNodeIds = toArray(raw.source_node_ids || raw.sourceNodeIds || nestedContent?.source_node_ids || nestedContent?.sourceNodeIds)
    .map((item) => sanitizeText(item))
    .filter(Boolean);
  const summary = firstNonEmpty(
    pageOverview?.display_text,
    raw.summary,
    raw.page_summary,
    raw.pageSummary,
    nestedContent?.summary,
    nestedContent?.page_summary,
    raw.overview,
    raw.text,
    nestedContent?.text,
    sections[0]?.text
  );
  const text = firstNonEmpty(raw.text, nestedContent?.text, raw.body, raw.content, summary);
  const bucketLabel = firstNonEmpty(deriveBucketLabel(raw), deriveBucketLabel(nestedContent), stripPageCountSuffix(title));
  const coverage = normalizeCoverage(raw.coverage, raw.scope, raw.page_range, raw.pageRange, nestedContent?.coverage);
  const insights = normalizeInsightCards({
    raw,
    nestedContent,
    pageIndex,
    title,
    bucketLabel,
    summary,
    text,
    sections,
    keyPoints,
    limitations,
    citations
  });

  return {
    page_index: pageIndex,
    title,
    status: normalizeStatus(raw.status ?? raw.state ?? nestedContent?.status),
    summary,
    text,
    coverage,
    bucket_label: bucketLabel,
    page_overview: pageOverview,
    structured_status: structuredStatus,
    reading_blocks: readingBlocks.length
      ? readingBlocks
      : text
        ? [
            {
              chunk_id: `page-${pageIndex}-text`,
              source_label: firstNonEmpty(raw.section_title, raw.sectionTitle, nestedContent?.section_title, nestedContent?.sectionTitle, title),
              page_start: raw.page_start ?? raw.pageStart ?? nestedContent?.page_start ?? nestedContent?.pageStart ?? null,
              page_end: raw.page_end ?? raw.pageEnd ?? nestedContent?.page_end ?? nestedContent?.pageEnd ?? null,
              original_en: text,
              explanation: "",
              display_text: ""
            }
          ]
        : [],
    source_sections: sourceSections,
    source_node_ids: sourceNodeIds,
    mentor_script: mentorScript,
    blackboard_notes: blackboardNotes,
    discipline_guide: disciplineGuide,
    story_stage: storyStage,
    glossary_terms: glossaryTerms,
    reading_hints: readingHints,
    checkpoints,
    section_title: firstNonEmpty(raw.section_title, raw.sectionTitle, nestedContent?.section_title, nestedContent?.sectionTitle),
    page_start: raw.page_start ?? raw.pageStart ?? nestedContent?.page_start ?? nestedContent?.pageStart ?? null,
    page_end: raw.page_end ?? raw.pageEnd ?? nestedContent?.page_end ?? nestedContent?.pageEnd ?? null,
    estimated_tokens:
      raw.estimated_tokens ?? raw.estimatedTokens ?? nestedContent?.estimated_tokens ?? nestedContent?.estimatedTokens ?? 0,
    chunk_count: raw.chunk_count ?? raw.chunkCount ?? nestedContent?.chunk_count ?? nestedContent?.chunkCount ?? 0,
    sections,
    bullets,
    key_points: keyPoints,
    limitations,
    insights,
    citations,
    error: firstNonEmpty(raw.error, raw.detail, structuredStatus.message, nestedContent?.error),
    raw
  };
}

function normalizeSession(raw) {
  if (!raw || typeof raw !== "object") {
    return null;
  }
  const pagesRaw = Array.isArray(raw.pages)
    ? raw.pages
    : Array.isArray(raw.page_manifest)
      ? raw.page_manifest
      : Array.isArray(raw.page_list)
        ? raw.page_list
        : [];
  const indexTree = normalizeIndexNode(raw.index_tree || raw.indexTree || raw.paper_map || raw.paperMap);
  return {
    session_id: firstNonEmpty(raw.session_id, raw.sessionId, raw.id),
    status: normalizeStatus(raw.session_status ?? raw.status ?? raw.state),
    source: firstNonEmpty(raw.source, raw.source_type, raw.input_source),
    source_type: firstNonEmpty(raw.source_type, raw.sourceType),
    source_url: firstNonEmpty(raw.source_url, raw.sourceUrl),
    paper_title: firstNonEmpty(raw.paper_title, raw.paperTitle, raw.title),
    arxiv_id: firstNonEmpty(raw.arxiv_id, raw.arxivId, raw.source_type === "arxiv" ? raw.source_id : ""),
    file_name: firstNonEmpty(raw.file_name, raw.fileName, raw.filename, raw.source_type === "file" ? raw.source_id : ""),
    authors: Array.isArray(raw.authors) ? raw.authors.map((item) => sanitizeText(item)).filter(Boolean) : [],
    published_date: firstNonEmpty(raw.published_date, raw.publishedDate),
    answer_language: firstNonEmpty(raw.answer_language, raw.answerLanguage),
    reader_mode: firstNonEmpty(raw.reader_mode, raw.readerMode, "guided"),
    discipline: normalizeDiscipline(raw.discipline ?? raw.paper_discipline ?? raw.paperDiscipline, "general"),
    discipline_source: firstNonEmpty(raw.discipline_source, raw.disciplineSource, "auto"),
    max_context_tokens: toNumber(raw.max_context_tokens ?? raw.maxContextTokens ?? 0, 0),
    page_input_budget: toNumber(raw.page_input_budget ?? raw.pageInputBudget ?? 0, 0),
    current_page_index: toNumber(raw.current_page_index ?? raw.currentPageIndex ?? raw.page_index ?? 0, 0),
    page_count: toNumber(raw.page_count ?? raw.pageCount ?? pagesRaw.length, pagesRaw.length),
    index_status: firstNonEmpty(raw.index_status, raw.indexStatus, indexTree ? "ready" : "fallback"),
    index_tree: indexTree,
    pages: pagesRaw
      .map((page, index) => normalizePageEntry(page, index))
      .filter(Boolean)
      .sort((left, right) => left.page_index - right.page_index),
    current_page: normalizePageEntry(raw.current_page || raw.currentPage || raw.page || raw.page_content, raw.current_page_index ?? 0)
  };
}

function extractAssistantContextText(page) {
  return firstNonEmpty(
    page?.reading_blocks
      ?.map((block) =>
        [
          block.source_label,
          formatPageRange(block.page_start, block.page_end, { sourcePages: "pages" }),
          block.original_en,
          block.explanation
        ]
          .filter(Boolean)
          .join("\n")
      )
      .filter(Boolean)
      .join("\n\n"),
    page?.page_overview?.display_text,
    page?.page_overview?.explanation,
    page?.mentor_script?.map((item) => firstNonEmpty(item.explanation, item.display_text, item.original_en)).join("\n"),
    page?.discipline_guide?.panels
      ?.map((panel) => [panel.title, ...(panel.items || []), panel.takeaway].filter(Boolean).join("\n"))
      .filter(Boolean)
      .join("\n\n"),
    page?.blackboard_notes?.takeaway,
    page?.glossary_terms?.map((item) => `${item.term}: ${item.explanation}`).join("\n"),
    page?.insights
      ?.map((card) =>
        [
          card.title,
          card.original_text,
          card.explanation_text,
          card.supporting_points?.join(" "),
          card.why_it_matters?.map((item) => item.explanation).join(" ")
        ]
          .filter(Boolean)
          .join("\n")
      )
      .filter(Boolean)
      .join("\n\n"),
    page?.summary,
    page?.text,
    page?.body,
    page?.sections?.map((section) => section.text).filter(Boolean).join("\n\n"),
    page?.citations?.map((citation) => citation.text || citation.excerpt).filter(Boolean).join("\n")
  );
}

function buildPaperReaderWorkflowContext({ session, page, answerText, question, language }) {
  const pageIndex = toNumber(page?.page_index ?? session?.current_page_index ?? 0, 0);
  return {
    kind: "paper_reader",
    session_id: session?.session_id || null,
    source: session?.source || null,
    paper_title: session?.paper_title || null,
    arxiv_id: session?.arxiv_id || null,
    answer_language: session?.answer_language || language || null,
    page_language: language || null,
    reader_mode: session?.reader_mode || null,
    discipline: session?.discipline || null,
    discipline_source: session?.discipline_source || null,
    page_index: pageIndex,
    page_title: page?.title || null,
    page_count: session?.page_count || null,
    story_stage: page?.story_stage || null,
    discipline_guide: page?.discipline_guide || null,
    blackboard_notes: page?.blackboard_notes || null,
    glossary_terms: page?.glossary_terms || [],
    checkpoint_status: page?.checkpoints?.length ? "available" : "none",
    latest_page_summary: extractAssistantContextText(page) || null,
    latest_answer_text: firstNonEmpty(answerText),
    question: String(question || "").trim() || null,
    metadata: {
      reading_blocks: toArray(page?.reading_blocks)
        .slice(0, 8)
        .map((block) => ({
          chunk_id: block.chunk_id,
          source_label: block.source_label,
          page_start: block.page_start,
          page_end: block.page_end,
          original_en: firstNonEmpty(block.original_en).slice(0, 1200),
          explanation: firstNonEmpty(block.explanation, block.display_text).slice(0, 800)
        }))
    }
  };
}

function localizeReaderLabel(value, language) {
  const text = sanitizeText(value);
  if (!text || language !== "zh") {
    return text;
  }
  const normalized = stripPageCountSuffix(text).toLowerCase();
  const suffix = extractPageCounter(text);
  const map = {
    "quick story": "速读页",
    "core question": "核心问题",
    "method or mechanism": "方法机制",
    "evidence or experiments": "实验证据",
    "conclusion": "结论收束",
    "open questions or limitations": "局限与开放问题",
    "problem and claim": "问题与主张",
    "method or system": "方法或系统",
    "experiments and results": "实验与结果",
    "conclusion and limits": "结论与局限",
    "statement to prove": "目标命题",
    "definitions and setup": "定义与设定",
    "proof strategy": "证明路线",
    "key proof steps": "关键证明步骤",
    "implications and open problems": "推论与开放问题",
    "mechanism or intervention": "机制或干预",
    "study design and evidence level": "研究设计与证据等级",
    "measurement and mechanism": "测量与机制",
    "results and evidence strength": "结果与证据强度",
    "limitations and safety": "局限与安全性",
    "explanation or hypothesis": "解释或假设",
    "data and identification": "数据与识别",
    "causal evidence and robustness": "因果证据与稳健性",
    implications: "影响与含义",
    "threats to validity": "有效性威胁",
    "question and context": "问题与语境",
    "concept definitions": "概念界定",
    "argument structure": "论证结构",
    "evidence and interpretation": "证据与阐释",
    "objections and stakes": "反驳与利害关系",
    "practical problem": "现实问题",
    "rules and institutions": "规则与制度",
    "interests and trade-offs": "利益与权衡",
    "consequences and enforcement": "后果与执行",
    "risks and open issues": "风险与开放问题",
    insight: "精读卡",
    claim: "主张",
    method: "方法",
    evidence: "证据",
    takeaway: "结论",
    limitation: "局限",
    question: "问题"
  };
  const localized = map[normalized] || text;
  return suffix && localized !== text ? `${localized} (${suffix})` : localized;
}

function getStatusLabel(status, t) {
  const labelMap = {
    queued: t("paperReaderQueued"),
    generating: t("paperReaderGenerating"),
    ready: t("paperReaderReady"),
    error: t("paperReaderError")
  };
  return labelMap[status] || status || t("paperReaderQueued");
}

function getStructuredStatusLabel(state, language) {
  if (language === "zh") {
    const map = {
      pending: "结构化待生成",
      ready: "结构化已就绪",
      repaired: "结构修复后可读",
      failed: "结构化失败"
    };
    return map[state] || "结构化待生成";
  }
  const map = {
    pending: "Structured pending",
    ready: "Structured ready",
    repaired: "Structured after repair",
    failed: "Structured failed"
  };
  return map[state] || "Structured pending";
}

function getPaperReaderCopy(language, t) {
  if (language === "zh") {
    return {
      productEyebrow: "论文精读",
      navigationTitle: "阅读导航",
      bucketLabel: "阅读焦点",
      paperMapTitle: "论文地图",
      paperMapSubtitle: "按原文章节建立学习路线，先看全局，再进入具体阅读页。",
      paperMapFallback: "这篇论文暂时只有阅读页导航，还没有可展示的结构地图。",
      mapNodePages: "原文页",
      mapNodeReaderPages: "阅读页",
      evidenceNodesLabel: "证据节点",
      focusCardsLabel: "精读卡",
      usedChunksLabel: "证据片段",
      pageWord: t("paperReaderPageLabel"),
      partWord: "分片",
      sourcePages: "原始页码",
      originalLabel: "英文原文",
      explanationLabel: "页面语言解读",
      showOriginalLabel: "展开英文原文",
      whyLabel: "为什么重要",
      citationsLabel: t("paperReaderCitations"),
      noOriginal: "暂无可展示的英文原文片段。",
      noExplanation: "当前还没有可展示的页面解读。",
      noInsights: "当前页还没有结构化精读卡。",
      pagesShort: "页",
      overviewTitle: "本页导读",
      sourceSectionsTitle: "覆盖章节",
      readingBlocksTitle: "论文原文与解读",
      rightCardsTitle: "学科讲解卡片",
      cardHoverHint: "悬停卡片会高亮对应原文，点击可跳转。",
      evidenceLabel: "证据线索",
      structuredFailureTitle: "本页结构化解析失败",
      structuredFailureBody: "我没有展示原始模型文本，而是保留了安全失败态。你可以重试本页，或跳到下一页继续阅读。",
      pageFocusLabel: "当前阅读焦点",
      disciplineLabel: "讲解学科",
      disciplineHelp: "自动识别会根据 arXiv 分类、标题摘要和正文线索选择阅读路线。",
      disciplineGuideTitle: "学科讲解面板",
      disciplineSourceAuto: "自动识别",
      disciplineSourceManual: "手动选择",
      guidedMode: "陪读模式",
      standardMode: "标准模式",
      mentorTitle: "导师讲解流",
      blackboardTitle: "黑板笔记",
      glossaryTitle: "术语降维",
      hintsTitle: "阅读提示",
      checkpointsTitle: "读完这一页我应该会什么",
      exportNotes: "导出研究笔记",
      paperSourceLabel: "论文证据",
      backgroundSourceLabel: "背景解释",
      quickStoryHint: "速读页会先帮你用 5 分钟判断这篇论文值不值得继续精读。"
    };
  }
  return {
    productEyebrow: "Paper Reader",
    navigationTitle: "Reading Navigation",
    bucketLabel: "Reading focus",
    paperMapTitle: "Paper Map",
    paperMapSubtitle: "A source-structure route for reading the paper from the whole to the parts.",
    paperMapFallback: "This session has reading pages, but no structure map yet.",
    mapNodePages: "Source pages",
    mapNodeReaderPages: "Reader pages",
    evidenceNodesLabel: "Evidence nodes",
    focusCardsLabel: "Insight cards",
    usedChunksLabel: "Evidence chunks",
    pageWord: t("paperReaderPageLabel"),
    partWord: "Part",
    sourcePages: "Source pages",
    originalLabel: "Original (EN)",
    explanationLabel: "Page-language reading",
    showOriginalLabel: "Show English original",
    whyLabel: "Why it matters",
    citationsLabel: t("paperReaderCitations"),
    noOriginal: "No grounded English excerpt yet.",
    noExplanation: "No page interpretation yet.",
    noInsights: "No structured insight cards for this page yet.",
    pagesShort: "pp.",
    overviewTitle: "Page overview",
    sourceSectionsTitle: "Covered sections",
    readingBlocksTitle: "Original and reading translation",
    rightCardsTitle: "Discipline cards",
    cardHoverHint: "Hover a card to highlight the matching original text; click to jump.",
    evidenceLabel: "Evidence trail",
    structuredFailureTitle: "Structured page parsing failed",
    structuredFailureBody:
      "Raw model output is intentionally hidden here. Retry this page, or continue to the next page while the reader keeps the safe failure state.",
      pageFocusLabel: "Current focus",
      disciplineLabel: "Discipline",
      disciplineHelp: "Auto detection chooses a reading route from arXiv category, title, abstract, and paper text cues.",
      disciplineGuideTitle: "Discipline guide",
      disciplineSourceAuto: "auto detected",
      disciplineSourceManual: "manual",
      guidedMode: "Guided mode",
    standardMode: "Standard mode",
    mentorTitle: "Mentor walkthrough",
    blackboardTitle: "Blackboard notes",
    glossaryTitle: "Terms made easier",
    hintsTitle: "Reading hints",
    checkpointsTitle: "What should I know after this page?",
    exportNotes: "Export research notes",
    paperSourceLabel: "Paper evidence",
    backgroundSourceLabel: "Background explanation",
    quickStoryHint: "Quick Story gives you a five-minute sense of whether to keep reading deeply."
  };
}

function buildPageBuckets(pages, language) {
  const buckets = [];
  const bucketMap = new Map();

  pages.forEach((page) => {
    const label = localizeReaderLabel(
      firstNonEmpty(page.bucket_label, stripPageCountSuffix(page.title), page.coverage, `Page ${page.page_index + 1}`),
      language
    );
    if (!bucketMap.has(label)) {
      const bucket = {
        key: `${label}-${buckets.length}`,
        label,
        pages: []
      };
      bucketMap.set(label, bucket);
      buckets.push(bucket);
    }
    bucketMap.get(label).pages.push(page);
  });

  return buckets;
}

function formatPageRange(start, end, copy) {
  if (start == null && end == null) {
    return "";
  }
  if (start != null && end != null) {
    return `${copy.sourcePages}: ${start}-${end}`;
  }
  return `${copy.sourcePages}: ${start ?? end}`;
}

function PaperMapTree({ root, pages, activePageIndex, activeSourceNodeIds, onGoToPage, copy, language }) {
  if (!root?.children?.length) {
    return (
      <section className="reader-map-panel">
        <div className="reader-map-head">
          <p className="reader-block-label">{copy.paperMapTitle}</p>
          <p className="muted">{copy.paperMapFallback}</p>
        </div>
      </section>
    );
  }
  const pageLookup = new Map(toArray(pages).map((page) => [page.page_index, page]));
  const nodeCount = Math.max(0, flattenIndexNodes(root).length - 1);

  function renderNode(node, depth = 0) {
    const pageIndices = toArray(node.page_indices).filter((pageIndex) => pageLookup.has(pageIndex));
    const active = activeSourceNodeIds.has(node.node_id) || pageIndices.includes(activePageIndex);
    return (
      <li key={node.node_id} className={`reader-map-node${active ? " active" : ""}`} style={{ "--reader-map-depth": depth }}>
        <div className="reader-map-node-main">
          <div>
            <strong>{node.title}</strong>
            <small>{formatPageRange(node.page_start, node.page_end, copy)}</small>
          </div>
          {pageIndices.length ? (
            <div className="reader-map-page-links" aria-label={copy.mapNodeReaderPages}>
              {pageIndices.slice(0, 4).map((pageIndex) => (
                <button
                  key={`${node.node_id}-${pageIndex}`}
                  type="button"
                  className={`reader-map-page-link${pageIndex === activePageIndex ? " active" : ""}`}
                  onClick={() => onGoToPage(pageIndex)}
                  title={localizeReaderLabel(pageLookup.get(pageIndex)?.title || `${copy.pageWord} ${pageIndex + 1}`, language)}
                >
                  {pageIndex + 1}
                </button>
              ))}
            </div>
          ) : null}
        </div>
        {node.children?.length ? <ul>{node.children.map((child) => renderNode(child, depth + 1))}</ul> : null}
      </li>
    );
  }

  return (
    <section className="reader-map-panel">
      <div className="reader-map-head">
        <div>
          <p className="reader-block-label">{copy.paperMapTitle}</p>
          <p className="muted">{copy.paperMapSubtitle}</p>
        </div>
        <span className="reader-status-chip">{nodeCount}</span>
      </div>
      <ul className="reader-map-tree">{root.children.map((node) => renderNode(node))}</ul>
    </section>
  );
}

function safeDomId(value, fallback = "item") {
  const text = String(value || "").trim().replace(/[^a-zA-Z0-9_-]+/g, "-").replace(/^-+|-+$/g, "");
  return text || fallback;
}

function readingBlockElementId(chunkId) {
  return `reader-source-${safeDomId(chunkId, "block")}`;
}

function sourceIdsFromLabels(labels, sourceSections) {
  const normalizedLabels = new Set(toArray(labels).map((label) => sanitizeText(label).toLowerCase()).filter(Boolean));
  if (!normalizedLabels.size) {
    return [];
  }
  return toArray(sourceSections)
    .filter((section) => normalizedLabels.has(sanitizeText(section.label).toLowerCase()))
    .flatMap((section) => section.chunk_ids || section.chunkIds || [])
    .map((item) => sanitizeText(item))
    .filter(Boolean);
}

function resolveCardSourceIds({ explicitIds = [], labels = [], index = 0, readingBlocks = [], sourceSections = [] }) {
  const ids = [
    ...toArray(explicitIds).map((item) => sanitizeText(item)),
    ...sourceIdsFromLabels(labels, sourceSections)
  ].filter(Boolean);
  if (!ids.length && sourceSections[index]?.chunk_ids?.length) {
    ids.push(...sourceSections[index].chunk_ids.map((item) => sanitizeText(item)).filter(Boolean));
  }
  if (!ids.length && readingBlocks[index]?.chunk_id) {
    ids.push(readingBlocks[index].chunk_id);
  }
  return [...new Set(ids)];
}

function buildDisciplineCards({ page, readingBlocks, sourceSections, language, copy }) {
  const cards = [];
  const guidePanels = page?.discipline_guide?.panels || [];
  guidePanels.forEach((panel, index) => {
    cards.push({
      id: `guide-${panel.key || index}`,
      eyebrow: copy.disciplineGuideTitle,
      title: panel.title,
      body: panel.takeaway,
      items: panel.items || [],
      sourceIds: resolveCardSourceIds({ index, readingBlocks, sourceSections })
    });
  });

  (page?.insights || []).forEach((insight, index) => {
    cards.push({
      id: `insight-${insight.id || index}`,
      eyebrow: firstNonEmpty(localizeReaderLabel(insight.eyebrow, language), copy.focusCardsLabel),
      title: insight.title,
      body: firstNonEmpty(insight.explanation_text, insight.original_text),
      items: insight.supporting_points || [],
      sourceIds: resolveCardSourceIds({
        explicitIds: insight.source_chunk_ids,
        labels: insight.source_section_labels,
        index,
        readingBlocks,
        sourceSections
      })
    });
  });

  (page?.glossary_terms || []).slice(0, 4).forEach((term, index) => {
    cards.push({
      id: `term-${term.term}-${index}`,
      eyebrow: term.source === "background" ? copy.backgroundSourceLabel : copy.paperSourceLabel,
      title: term.term,
      body: term.explanation,
      items: [],
      sourceIds: resolveCardSourceIds({
        labels: term.citation?.section_title ? [term.citation.section_title] : [],
        index,
        readingBlocks,
        sourceSections
      })
    });
  });

  (page?.reading_hints || []).slice(0, 3).forEach((hint, index) => {
    cards.push({
      id: `hint-${hint.kind}-${index}`,
      eyebrow: copy.hintsTitle,
      title: hint.kind === "skim" ? (language === "zh" ? "可以先略读" : "Skim first") : hint.kind === "advanced" ? (language === "zh" ? "进阶再看" : "Advanced") : (language === "zh" ? "新手必懂" : "Must know"),
      body: hint.text,
      items: hint.reason ? [hint.reason] : [],
      sourceIds: resolveCardSourceIds({ index, readingBlocks, sourceSections })
    });
  });

  (page?.checkpoints || []).slice(0, 2).forEach((checkpoint, index) => {
    cards.push({
      id: `checkpoint-${checkpoint.id || index}`,
      eyebrow: copy.checkpointsTitle,
      title: checkpoint.question,
      body: checkpoint.answer,
      items: checkpoint.review_hint ? [checkpoint.review_hint] : [],
      sourceIds: resolveCardSourceIds({ index, readingBlocks, sourceSections })
    });
  });

  return cards.filter((card) => card.title || card.body).slice(0, 10);
}

function ReadingBlocks({ blocks, activeSourceId, copy }) {
  if (!blocks?.length) {
    return (
      <section className="reader-reading-blocks reader-module-section" id="reader-module-reading-blocks">
        <div className="reader-structured-empty">
          <p>{copy.noOriginal}</p>
        </div>
      </section>
    );
  }
  return (
    <section className="reader-reading-blocks reader-module-section" id="reader-module-reading-blocks">
      <div className="reader-block-head">
        <div>
          <p className="reader-block-label">{copy.readingBlocksTitle}</p>
        </div>
      </div>
      <div className="reader-reading-block-list">
        {blocks.map((block, index) => {
          const active = activeSourceId && block.chunk_id === activeSourceId;
          const pageRange = formatPageRange(block.page_start, block.page_end, copy);
          return (
            <article
              key={`${block.chunk_id}-${index}`}
              id={readingBlockElementId(block.chunk_id)}
              className={`reader-reading-block${active ? " active" : ""}`}
            >
              <div className="reader-reading-block-meta">
                <span>{block.source_label}</span>
                {pageRange ? <small>{pageRange}</small> : null}
              </div>
              <div className="reader-original-panel">
                <span className="reader-tone-label">{copy.originalLabel}</span>
                <p>{block.original_en}</p>
              </div>
              <div className="reader-translation-panel">
                <span className="reader-tone-label">{copy.explanationLabel}</span>
                <p>{firstNonEmpty(block.explanation, block.display_text, copy.noExplanation)}</p>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function DisciplineCards({ cards, activeSourceId, onActivate, onClear, onOpen, copy }) {
  return (
    <section className="workspace paper-reader-discipline-cards">
      <div className="reader-card-column-head">
        <div>
          <p className="reader-block-label">{copy.rightCardsTitle}</p>
          <p className="muted">{copy.cardHoverHint}</p>
        </div>
      </div>
      <div className="reader-side-card-list">
        {cards.length ? (
          cards.map((card) => {
            const active = activeSourceId && card.sourceIds?.includes(activeSourceId);
            return (
              <article
                key={card.id}
                className={`reader-side-card${active ? " active" : ""}`}
                tabIndex={0}
                onMouseEnter={() => onActivate(card)}
                onMouseLeave={onClear}
                onFocus={() => onActivate(card)}
                onBlur={onClear}
                onClick={() => onOpen(card)}
              >
                {card.eyebrow ? <p className="reader-insight-eyebrow">{card.eyebrow}</p> : null}
                <h4>{card.title}</h4>
                {card.body ? <p>{card.body}</p> : null}
                {card.items?.length ? (
                  <ul>
                    {card.items.slice(0, 3).map((item, index) => (
                      <li key={`${card.id}-item-${index}`}>{item}</li>
                    ))}
                  </ul>
                ) : null}
              </article>
            );
          })
        ) : (
          <div className="reader-structured-empty">
            <p>{copy.noInsights}</p>
          </div>
        )}
      </div>
    </section>
  );
}

function buildReaderModuleAnchors({
  page,
  insights,
  sourceSections,
  mentorScript,
  disciplineGuide,
  glossaryTerms,
  readingHints,
  checkpoints,
  copy
}) {
  if (!page) {
    return [];
  }
  const hasEvidence = toArray(insights).some(
    (card) => card.supporting_points?.length || card.citations?.length || card.source_section_labels?.length
  );
  const hasWhy = toArray(insights).some((card) => card.why_it_matters?.length);
  return [
    page.page_overview ? { id: "reader-module-overview", label: copy.overviewTitle } : null,
    mentorScript?.length ? { id: "reader-module-mentor", label: copy.mentorTitle } : null,
    disciplineGuide?.panels?.length ? { id: "reader-module-discipline-guide", label: copy.disciplineGuideTitle } : null,
    sourceSections?.length ? { id: "reader-module-sources", label: copy.sourceSectionsTitle } : null,
    glossaryTerms?.length || readingHints?.length ? { id: "reader-module-guidance", label: copy.hintsTitle } : null,
    insights?.length ? { id: "reader-module-insights", label: copy.focusCardsLabel } : null,
    hasEvidence ? { id: "reader-module-evidence", label: copy.evidenceLabel } : null,
    hasWhy ? { id: "reader-module-why", label: copy.whyLabel } : null,
    checkpoints?.length ? { id: "reader-module-checkpoints", label: copy.checkpointsTitle } : null
  ].filter(Boolean);
}

function isTypingTarget(target) {
  if (!target) {
    return false;
  }
  const tagName = String(target.tagName || "").toLowerCase();
  return (
    tagName === "input" ||
    tagName === "textarea" ||
    tagName === "select" ||
    target.isContentEditable ||
    Boolean(target.closest?.("[contenteditable='true']"))
  );
}

function formatCitationLabel(citation, copy, index) {
  const parts = [
    firstNonEmpty(citation.label, citation.section_title, citation.chunk_id, `citation-${index + 1}`),
    firstNonEmpty(citation.subsection_title),
    citation.page_start != null || citation.page_end != null
      ? `${copy.pagesShort} ${citation.page_start ?? "?"}-${citation.page_end ?? "?"}`
      : ""
  ].filter(Boolean);
  return parts.join(" · ");
}

function buildResearchNoteMarkdown({ session, pages, language }) {
  const lines = [];
  const title = firstNonEmpty(session?.paper_title, language === "zh" ? "论文精读笔记" : "Paper Reader Notes");
  lines.push(`# ${title}`);
  lines.push("");
  if (session?.arxiv_id) {
    lines.push(`- arXiv: ${session.arxiv_id}`);
  }
  if (session?.file_name) {
    lines.push(`- PDF: ${session.file_name}`);
  }
  lines.push(`- Reader mode: ${session?.reader_mode || "guided"}`);
  if (session?.discipline) {
    lines.push(`- Discipline: ${getDisciplineLabel(session.discipline, language)} (${getDisciplineSourceLabel(session.discipline_source, language)})`);
  }
  lines.push("");
  pages.forEach((page) => {
    lines.push(`## ${page.title || `Page ${page.page_index + 1}`}`);
    if (page.story_stage?.title) {
      lines.push(`Stage: ${page.story_stage.title}`);
      lines.push("");
    }
    if (page.page_overview?.display_text) {
      lines.push(page.page_overview.display_text);
      lines.push("");
    }
    if (page.discipline_guide?.panels?.length) {
      lines.push(language === "zh" ? "### 学科讲解面板" : "### Discipline guide");
      page.discipline_guide.panels.forEach((panel) => {
        lines.push(`#### ${panel.title}`);
        (panel.items || []).filter(Boolean).forEach((item) => lines.push(`- ${item}`));
        if (panel.takeaway) {
          lines.push(`- ${panel.takeaway}`);
        }
      });
      lines.push("");
    }
    if (page.insights?.length) {
      lines.push(language === "zh" ? "### 精读卡" : "### Insight cards");
      page.insights.forEach((insight) => {
        lines.push(`- ${insight.title}: ${firstNonEmpty(insight.explanation_text, insight.original_text)}`);
      });
      lines.push("");
    }
    if (page.glossary_terms?.length) {
      lines.push(language === "zh" ? "### 术语表" : "### Glossary");
      page.glossary_terms.forEach((term) => lines.push(`- **${term.term}**: ${term.explanation}`));
      lines.push("");
    }
  });
  return lines.join("\n").trim() + "\n";
}

export default function PaperReaderPage({
  language,
  t,
  settings,
  runtimePayload,
  initialArxivUrl = "",
  onInitialArxivUrlConsumed,
  renderAssistantLayer,
  onAssistantContextChange
}) {
  const paperReaderConfig = settings?.paper_reader_chat || {};
  const [arxivUrl, setArxivUrl] = useState("");
  const [pdfFile, setPdfFile] = useState(null);
  const [readerMode, setReaderMode] = useState("guided");
  const [discipline, setDiscipline] = useState("auto");
  const [session, setSession] = useState(null);
  const [pagesByIndex, setPagesByIndex] = useState({});
  const [activePageIndex, setActivePageIndex] = useState(0);
  const [sessionBusy, setSessionBusy] = useState(false);
  const [pageBusyMap, setPageBusyMap] = useState({});
  const [bannerMessage, setBannerMessage] = useState("");
  const [bannerError, setBannerError] = useState("");
  const [readerProgress, setReaderProgress] = useState({
    step: "load",
    status: "idle",
    detail: "",
    updatedAt: null
  });
  const [activeModuleId, setActiveModuleId] = useState("");
  const [activeSourceId, setActiveSourceId] = useState("");
  const streamRefs = useRef(new Map());
  const pollRefs = useRef(new Map());
  const assistantContextKeyRef = useRef("");
  const activeRequestRef = useRef(0);
  const autoLoadUrlRef = useRef("");
  const fileInputRef = useRef(null);
  const pageCardRef = useRef(null);

  const pageEntries = useMemo(() => {
    const manifest = Array.isArray(session?.pages) ? session.pages : [];
    const map = pagesByIndex || {};
    const merged = manifest.length ? manifest : Object.values(map);
    return merged
      .map((page, index) => mergePageEntry(page, map[page?.page_index ?? index]))
      .filter(Boolean)
      .sort((left, right) => left.page_index - right.page_index);
  }, [pagesByIndex, session?.pages]);

  const pageCount = session?.page_count || pageEntries.length || 0;
  const activePage =
    pageEntries.find((page) => page.page_index === activePageIndex) ||
    pagesByIndex[activePageIndex] ||
    session?.current_page ||
    null;
  const currentPageStatus = activePage?.status || (session ? "queued" : "idle");
  const readerBudget = Number(paperReaderConfig.max_context_tokens || 0);
  const readerModelSummary = useMemo(() => {
    const provider = firstNonEmpty(paperReaderConfig.provider, t("none"));
    const model = firstNonEmpty(paperReaderConfig.model, t("none"));
    const budget = readerBudget > 0 ? readerBudget : t("none");
    return `${provider} / ${model} · ${budget}`;
  }, [paperReaderConfig.model, paperReaderConfig.provider, readerBudget, t]);
  const readerProgressSteps = useMemo(
    () => [
      { key: "load", label: t("paperReaderProgressLoad") },
      { key: "paginate", label: t("paperReaderProgressPaginate") },
      { key: "page", label: t("paperReaderProgressPage") }
    ],
    [t]
  );
  const readerStatusLabels = useMemo(
    () => ({
      idle: t("progressIdle"),
      running: t("progressRunning"),
      ready: t("progressReady"),
      completed: t("progressCompleted"),
      interrupted: t("progressInterrupted")
    }),
    [t]
  );
  const copy = useMemo(() => getPaperReaderCopy(language, t), [language, t]);
  const pageBuckets = useMemo(() => buildPageBuckets(pageEntries, language), [pageEntries, language]);
  const activeStructuredState = activePage?.structured_status?.state || "pending";
  const activeStructuredMessage = firstNonEmpty(activePage?.structured_status?.message, activePage?.error);
  const activeOverview = activePage?.page_overview || null;
  const activeReadingBlocks = activePage?.reading_blocks || [];
  const activeSourceSections = activePage?.source_sections || [];
  const indexTree = session?.index_tree || null;
  const activeSourceNodeIds = useMemo(() => new Set(activePage?.source_node_ids || []), [activePage?.source_node_ids]);
  const activeInsights = activePage?.insights || [];
  const firstEvidenceInsightIndex = activeInsights.findIndex(
    (card) => card.supporting_points?.length || card.citations?.length || card.source_section_labels?.length
  );
  const firstWhyInsightIndex = activeInsights.findIndex((card) => card.why_it_matters?.length);
  const activeMentorScript = activePage?.mentor_script || [];
  const activeDisciplineGuide = activePage?.discipline_guide || null;
  const activeStoryStage = activePage?.story_stage || null;
  const activeGlossaryTerms = activePage?.glossary_terms || [];
  const activeReadingHints = activePage?.reading_hints || [];
  const activeCheckpoints = activePage?.checkpoints || [];
  const activeDisciplineCards = useMemo(
    () =>
      buildDisciplineCards({
        page: activePage,
        readingBlocks: activeReadingBlocks,
        sourceSections: activeSourceSections,
        language,
        copy
      }),
    [activePage, activeReadingBlocks, activeSourceSections, copy, language]
  );
  const activeTitle = firstNonEmpty(activePage?.title, `${t("paperReaderPageLabel")} ${activePageIndex + 1}`);
  const activeTitleBase = localizeReaderLabel(stripPageCountSuffix(activeTitle) || activeTitle, language);
  const activeTitleCounter = extractPageCounter(activeTitle);
  const pageModuleAnchors = useMemo(
    () =>
      buildReaderModuleAnchors({
        page: activePage,
        insights: activeInsights,
        sourceSections: activeSourceSections,
        mentorScript: activeMentorScript,
        disciplineGuide: activeDisciplineGuide,
        glossaryTerms: activeGlossaryTerms,
        readingHints: activeReadingHints,
        checkpoints: activeCheckpoints,
        copy
      }),
    [
      activePage,
      activeInsights,
      activeSourceSections,
      activeMentorScript,
      activeDisciplineGuide,
      activeGlossaryTerms,
      activeReadingHints,
      activeCheckpoints,
      copy
    ]
  );

  useEffect(() => {
    const url = String(initialArxivUrl || "").trim();
    if (!url || autoLoadUrlRef.current === url) {
      return;
    }
    autoLoadUrlRef.current = url;
    setArxivUrl(url);
    void loadArxivUrl(url).finally(() => {
      onInitialArxivUrlConsumed?.();
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialArxivUrl]);

  useEffect(() => {
    return () => {
      streamRefs.current.forEach((source) => {
        try {
          source.close();
        } catch (_) {
          // ignore cleanup failures
        }
      });
      streamRefs.current.clear();
      pollRefs.current.forEach((timerId) => window.clearInterval(timerId));
      pollRefs.current.clear();
    };
  }, []);

  useEffect(() => {
    if (!session?.session_id) {
      return;
    }
    const targetIndex = toNumber(session.current_page_index ?? 0, 0);
    if (targetIndex !== activePageIndex) {
      setActivePageIndex(targetIndex);
    }
    void ensurePageReady(targetIndex, { sessionId: session.session_id });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.session_id, session?.current_page_index, session?.pages?.length]);

  useEffect(() => {
    if (!session?.session_id || !activePage || currentPageStatus !== "ready") {
      return;
    }
    const answerContext = extractAssistantContextText(activePage);
    const workflowContext = buildPaperReaderWorkflowContext({
      session,
      page: activePage,
      answerText: "",
      question: "",
      language
    });
    const cacheKey = `${session.session_id}:page:${activePage.page_index}:${
      activePage.page_overview?.display_text || activePage.summary || activePage.text || ""
    }`;
    if (assistantContextKeyRef.current === cacheKey) {
      return;
    }
    assistantContextKeyRef.current = cacheKey;
    onAssistantContextChange?.({
      answerContext,
      workflowContext
    });
  }, [activePage, currentPageStatus, language, onAssistantContextChange, session]);

  useEffect(() => {
    setActiveModuleId(pageModuleAnchors[0]?.id || "");
  }, [activePageIndex, pageModuleAnchors]);

  useEffect(() => {
    if (!pageModuleAnchors.length || typeof IntersectionObserver === "undefined") {
      return undefined;
    }
    const elements = pageModuleAnchors.map((anchor) => document.getElementById(anchor.id)).filter(Boolean);
    if (!elements.length) {
      return undefined;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((left, right) => left.boundingClientRect.top - right.boundingClientRect.top)[0];
        if (visible?.target?.id) {
          setActiveModuleId(visible.target.id);
        }
      },
      {
        root: null,
        rootMargin: "-18% 0px -64% 0px",
        threshold: [0.01, 0.2, 0.5]
      }
    );
    elements.forEach((element) => observer.observe(element));
    return () => observer.disconnect();
  }, [activePageIndex, pageModuleAnchors]);

  useEffect(() => {
    function handleKeyDown(event) {
      if (isTypingTarget(event.target) || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) {
        return;
      }
      if (event.key === "ArrowLeft" && activePageIndex > 0) {
        event.preventDefault();
        goToPage(activePageIndex - 1);
      }
      if (event.key === "ArrowRight" && (!pageCount || activePageIndex < pageCount - 1)) {
        event.preventDefault();
        goToPage(activePageIndex + 1);
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [activePageIndex, pageCount, session?.session_id]);

  function updateReaderProgress(step, status, detail = "") {
    setReaderProgress({
      step,
      status,
      detail,
      updatedAt: new Date().toISOString()
    });
  }

  function resetReaderState() {
    streamRefs.current.forEach((source) => {
      try {
        source.close();
      } catch (_) {
        // ignore cleanup failures
      }
    });
    streamRefs.current.clear();
    pollRefs.current.forEach((timerId) => window.clearInterval(timerId));
    pollRefs.current.clear();
    setSession(null);
    setPagesByIndex({});
    setActivePageIndex(0);
    setBannerMessage("");
    setBannerError("");
    setPageBusyMap({});
    setReaderProgress({
      step: "load",
      status: "idle",
      detail: "",
      updatedAt: null
    });
    assistantContextKeyRef.current = "";
    onAssistantContextChange?.({
      answerContext: null,
      workflowContext: null
    });
  }

  function upsertPage(page) {
    if (!page) {
      return;
    }
    setPagesByIndex((current) => {
      const previous = current[page.page_index];
      const nextPage = mergePageEntry(previous, page);
      return {
        ...current,
        [page.page_index]: nextPage
      };
    });
    if (session?.session_id) {
      setSession((current) => {
        if (!current) {
          return current;
        }
        const nextPages = Array.isArray(current.pages) ? [...current.pages] : [];
        const existingIndex = nextPages.findIndex((item) => item.page_index === page.page_index);
        if (existingIndex >= 0) {
          nextPages[existingIndex] = mergePageEntry(nextPages[existingIndex], page);
        } else {
          nextPages.push(page);
          nextPages.sort((left, right) => left.page_index - right.page_index);
        }
        return {
          ...current,
          pages: nextPages,
          page_count: Math.max(current.page_count || 0, nextPages.length),
          current_page:
            current.current_page?.page_index === page.page_index
              ? mergePageEntry(current.current_page, page)
              : current.current_page
        };
      });
    }
  }

  function setPageBusy(pageIndex, busy) {
    setPageBusyMap((current) => {
      const next = { ...current };
      if (busy) {
        next[pageIndex] = true;
      } else {
        delete next[pageIndex];
      }
      return next;
    });
  }

  function stopPageWatch(pageIndex) {
    const source = streamRefs.current.get(pageIndex);
    if (source) {
      try {
        source.close();
      } catch (_) {
        // ignore cleanup failures
      }
    }
    streamRefs.current.delete(pageIndex);
    const timerId = pollRefs.current.get(pageIndex);
    if (timerId) {
      window.clearInterval(timerId);
    }
    pollRefs.current.delete(pageIndex);
    setPageBusy(pageIndex, false);
  }

  async function fetchSessionState(sessionId) {
    const response = await fetch(`/api/paper-reader/session/${encodeURIComponent(sessionId)}`);
    const payload = await readJsonWithDetailFallback(response);
    if (!response.ok) {
      throw new Error(payload.detail || `${t("paperReaderFetchFail")} (HTTP ${response.status})`);
    }
    const normalized = normalizeSession(payload);
    if (!normalized) {
      throw new Error(t("paperReaderFetchFail"));
    }
    setSession(normalized);
    normalized.pages.forEach((page) => upsertPage(page));
    if (normalized.current_page) {
      upsertPage(normalized.current_page);
    }
    return normalized;
  }

  async function fetchPageSnapshot(sessionId, pageIndex) {
    const response = await fetch(
      `/api/paper-reader/session/${encodeURIComponent(sessionId)}/pages/${encodeURIComponent(pageIndex)}`
    );
    const payload = await readJsonWithDetailFallback(response);
    if (!response.ok) {
      throw new Error(payload.detail || `${t("paperReaderPageLoadFail")} (HTTP ${response.status})`);
    }
    const page = normalizePageEntry(payload?.page || payload?.current_page || payload?.content || payload, pageIndex);
    if (page) {
      upsertPage(page);
    }
    return page;
  }

  function watchPage(sessionId, pageIndex, { prefetch = false } = {}) {
    if (!sessionId && !session?.session_id) {
      return;
    }
    const resolvedSessionId = sessionId || session.session_id;
    const existing = streamRefs.current.get(pageIndex);
    if (existing) {
      return;
    }
    setPageBusy(pageIndex, true);
    updateReaderProgress("page", "running", `${t("paperReaderProgressPage")} ${pageIndex + 1}`);
    const streamUrl = `/api/paper-reader/session/${encodeURIComponent(resolvedSessionId)}/pages/${encodeURIComponent(
      pageIndex
    )}/stream`;
    const source = new EventSource(streamUrl);
    streamRefs.current.set(pageIndex, source);

    const finalize = async () => {
      try {
        const page = await fetchPageSnapshot(resolvedSessionId, pageIndex);
        if (page?.status === "ready" || page?.status === "error") {
          stopPageWatch(pageIndex);
          updateReaderProgress(
            "page",
            page.status === "ready" ? "ready" : "interrupted",
            page.status === "ready"
              ? `${t("paperReaderProgressPage")} ${page.page_index + 1}`
              : page.error || t("paperReaderPageLoadFail")
          );
          if (!prefetch && page?.status === "ready" && activePageIndex === pageIndex) {
            publishAssistantContextForPage(page, "");
            prefetchNextPage(pageIndex);
          }
        }
      } catch (error) {
        if (String(error || "").includes("HTTP 404")) {
          return;
        }
        setBannerError(String(error));
        updateReaderProgress("page", "interrupted", String(error));
        stopPageWatch(pageIndex);
      }
    };

    source.addEventListener("message", async (event) => {
      if (!event?.data) {
        return;
      }
      try {
        const payload = JSON.parse(event.data);
        const page = normalizePageEntry(
          payload?.page || payload?.current_page || payload?.content || payload?.page_content || payload,
          pageIndex
        );
        if (page) {
          upsertPage(page);
          if (page.status === "ready" || page.status === "error") {
            stopPageWatch(pageIndex);
            updateReaderProgress(
              "page",
              page.status === "ready" ? "ready" : "interrupted",
              page.status === "ready"
                ? `${t("paperReaderProgressPage")} ${page.page_index + 1}`
                : page.error || t("paperReaderPageLoadFail")
            );
            if (!prefetch && page.status === "ready" && activePageIndex === pageIndex) {
              publishAssistantContextForPage(page, "");
              prefetchNextPage(pageIndex);
            }
          }
        }
        if (payload?.status === "ready" || payload?.status === "error" || payload?.done) {
          await finalize();
        }
      } catch (_) {
        // ignore malformed stream payloads and keep polling
      }
    });

    source.addEventListener("complete", () => {
      void finalize();
    });
    source.addEventListener("error", () => {
      void finalize();
    });

    const timerId = window.setInterval(() => {
      void finalize();
    }, prefetch ? 2000 : 1200);
    pollRefs.current.set(pageIndex, timerId);
  }

  async function ensurePageReady(pageIndex, { prefetch = false, sessionId = null } = {}) {
    const resolvedSessionId = sessionId || session?.session_id;
    if (!resolvedSessionId) {
      return;
    }
    const normalizedIndex = Math.max(0, toNumber(pageIndex, 0));
    const existing = pagesByIndex[normalizedIndex] || session?.pages?.find((page) => page.page_index === normalizedIndex);
    if (existing?.status === "ready") {
      updateReaderProgress("page", "ready", `${t("paperReaderProgressPage")} ${normalizedIndex + 1}`);
      if (!prefetch && normalizedIndex === activePageIndex) {
        publishAssistantContextForPage(existing, "");
        prefetchNextPage(normalizedIndex);
      }
      return;
    }
    if (existing?.status === "error") {
      updateReaderProgress("page", "interrupted", existing.error || t("paperReaderPageLoadFail"));
      return;
    }

    try {
      const snapshot = await fetchPageSnapshot(resolvedSessionId, normalizedIndex);
      if (snapshot?.status === "ready") {
        updateReaderProgress("page", "ready", `${t("paperReaderProgressPage")} ${snapshot.page_index + 1}`);
        if (!prefetch && normalizedIndex === activePageIndex) {
          publishAssistantContextForPage(snapshot, "");
          prefetchNextPage(normalizedIndex);
        }
        return;
      }
      if (snapshot?.status === "error") {
        updateReaderProgress("page", "interrupted", snapshot.error || t("paperReaderPageLoadFail"));
        return;
      }
    } catch (error) {
      setBannerError(String(error));
      updateReaderProgress("page", "interrupted", String(error));
      return;
    }

    watchPage(resolvedSessionId, normalizedIndex, { prefetch });
  }

  function prefetchNextPage(pageIndex) {
    if (!session?.session_id) {
      return;
    }
    const nextIndex = pageIndex + 1;
    if (pageCount && nextIndex >= pageCount) {
      return;
    }
    void ensurePageReady(nextIndex, { prefetch: true });
  }

  function publishAssistantContextForPage(page, answerText) {
    if (!page || !session?.session_id || typeof onAssistantContextChange !== "function") {
      return;
    }
    const cacheKey = `${session.session_id}:page:${page.page_index}:${page.status}:${
      answerText || page.page_overview?.display_text || page.summary || page.text || ""
    }`;
    if (assistantContextKeyRef.current === cacheKey) {
      return;
    }
    assistantContextKeyRef.current = cacheKey;
    onAssistantContextChange({
      answerContext: firstNonEmpty(answerText, extractAssistantContextText(page)),
      workflowContext: buildPaperReaderWorkflowContext({
        session,
        page,
        answerText,
        question: "",
        language
      })
    });
  }

  async function loadArxivUrl(rawUrl) {
    const url = String(rawUrl || "").trim();
    if (!url) {
      setBannerError(t("paperReaderInvalidUrl"));
      return;
    }
    setSessionBusy(true);
    setBannerMessage("");
    setBannerError("");
    updateReaderProgress("load", "running", t("paperReaderProgressLoad"));
    activeRequestRef.current += 1;
    const requestId = activeRequestRef.current;
    try {
      const response = await fetch("/api/paper-reader/session/from-arxiv", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url,
          answer_language: language,
          reader_mode: readerMode,
          discipline,
          settings: runtimePayload
        })
      });
      const payload = await readJsonWithDetailFallback(response);
      if (!response.ok) {
        throw new Error(payload.detail || `${t("paperReaderLoadFail")} (HTTP ${response.status})`);
      }
      if (requestId !== activeRequestRef.current) {
        return;
      }
      resetReaderState();
      const normalized = normalizeSession(payload);
      if (!normalized) {
        throw new Error(t("paperReaderLoadFail"));
      }
      setSession(normalized);
      setReaderMode(normalized.reader_mode || readerMode);
      setDiscipline(normalized.discipline_source === "manual" ? normalized.discipline : "auto");
      normalized.pages.forEach((page) => upsertPage(page));
      if (normalized.current_page) {
        upsertPage(normalized.current_page);
      }
      updateReaderProgress("paginate", "ready", t("paperReaderProgressPaginate"));
      setBannerMessage(
        firstNonEmpty(
          payload.message,
          normalized.paper_title,
          normalized.arxiv_id ? `${normalized.arxiv_id}` : t("paperReaderLoading")
        )
      );
      const startIndex = normalized.current_page_index || 0;
      setActivePageIndex(startIndex);
      void ensurePageReady(startIndex, { sessionId: normalized.session_id });
    } catch (error) {
      setBannerError(String(error));
      updateReaderProgress("load", "interrupted", String(error));
    } finally {
      if (requestId === activeRequestRef.current) {
        setSessionBusy(false);
      }
    }
  }

  async function handleLoadArxiv(event) {
    event.preventDefault();
    await loadArxivUrl(arxivUrl);
  }

  async function handleLoadPdf(event) {
    event.preventDefault();
    const file = pdfFile || fileInputRef.current?.files?.[0];
    if (!file) {
      setBannerError(t("paperReaderFileRequired"));
      return;
    }
    setSessionBusy(true);
    setBannerMessage("");
    setBannerError("");
    updateReaderProgress("load", "running", t("paperReaderProgressLoad"));
    activeRequestRef.current += 1;
    const requestId = activeRequestRef.current;
    try {
      const formData = new FormData();
      formData.append("pdf", file);
      formData.append("answer_language", language);
      formData.append("reader_mode", readerMode);
      formData.append("discipline", discipline);
      formData.append("settings", JSON.stringify(runtimePayload || {}));
      const response = await fetch("/api/paper-reader/session/from-file", {
        method: "POST",
        body: formData
      });
      const payload = await readJsonWithDetailFallback(response);
      if (!response.ok) {
        throw new Error(payload.detail || `${t("paperReaderLoadFail")} (HTTP ${response.status})`);
      }
      if (requestId !== activeRequestRef.current) {
        return;
      }
      resetReaderState();
      const normalized = normalizeSession(payload);
      if (!normalized) {
        throw new Error(t("paperReaderLoadFail"));
      }
      setSession(normalized);
      setReaderMode(normalized.reader_mode || readerMode);
      setDiscipline(normalized.discipline_source === "manual" ? normalized.discipline : "auto");
      normalized.pages.forEach((page) => upsertPage(page));
      if (normalized.current_page) {
        upsertPage(normalized.current_page);
      }
      updateReaderProgress("paginate", "ready", t("paperReaderProgressPaginate"));
      setBannerMessage(firstNonEmpty(payload.message, file.name, t("paperReaderLoading")));
      const startIndex = normalized.current_page_index || 0;
      setActivePageIndex(startIndex);
      void ensurePageReady(startIndex, { sessionId: normalized.session_id });
    } catch (error) {
      setBannerError(String(error));
      updateReaderProgress("load", "interrupted", String(error));
    } finally {
      if (requestId === activeRequestRef.current) {
        setSessionBusy(false);
      }
    }
  }

  function goToPage(pageIndex) {
    const normalizedIndex = Math.max(0, toNumber(pageIndex, 0));
    setActivePageIndex(normalizedIndex);
    setActiveSourceId("");
    if (session?.session_id) {
      setSession((current) => (current ? { ...current, current_page_index: normalizedIndex } : current));
      void ensurePageReady(normalizedIndex, { sessionId: session?.session_id });
    }
  }

  function activateDisciplineCard(card) {
    const nextSourceId = card?.sourceIds?.[0] || "";
    setActiveSourceId(nextSourceId);
  }

  function openDisciplineCard(card) {
    const sourceId = card?.sourceIds?.[0] || "";
    if (!sourceId) {
      return;
    }
    setActiveSourceId(sourceId);
    const target = document.getElementById(readingBlockElementId(sourceId));
    target?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function exportResearchNotes() {
    if (!session) {
      return;
    }
    const markdown = buildResearchNoteMarkdown({ session, pages: pageEntries, language });
    const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    const safeTitle = firstNonEmpty(session.paper_title, "paper-reader-notes")
      .replace(/[^\w.-]+/g, "-")
      .replace(/-+/g, "-")
      .slice(0, 80);
    link.href = url;
    link.download = `${safeTitle || "paper-reader-notes"}.md`;
    link.click();
    URL.revokeObjectURL(url);
  }

  const manifestSummary = useMemo(() => {
    if (!session) {
      return t("paperReaderNoSession");
    }
    const title = firstNonEmpty(session.paper_title, t("paperReaderNoContent"));
    const source = firstNonEmpty(
      session.source,
      session.arxiv_id ? "arXiv" : session.file_name ? "PDF" : t("none")
    );
    return `${title} · ${source}`;
  }, [session, t]);

  const hasSession = Boolean(session?.session_id);
  const shouldShowProgressTracker =
    !hasSession || readerProgress.status === "running" || readerProgress.status === "interrupted" || readerProgress.status === "failed";

  const renderReaderModeControls = () => (
    <div className="reader-mode-row">
      <div>
        <p className="eyebrow">{copy.guidedMode}</p>
        <p className="muted">{readerMode === "guided" ? copy.quickStoryHint : copy.standardMode}</p>
      </div>
      <div className="lang-switch" aria-label={copy.guidedMode}>
        <button type="button" className={readerMode === "guided" ? "active" : "secondary"} onClick={() => setReaderMode("guided")}>
          {copy.guidedMode}
        </button>
        <button type="button" className={readerMode === "standard" ? "active" : "secondary"} onClick={() => setReaderMode("standard")}>
          {copy.standardMode}
        </button>
      </div>
    </div>
  );

  const renderDisciplineControls = () => (
    <div className="reader-mode-row reader-discipline-row">
      <div>
        <p className="eyebrow">{copy.disciplineLabel}</p>
        <p className="muted">{copy.disciplineHelp}</p>
      </div>
      <label className="reader-discipline-select">
        <span>{copy.disciplineLabel}</span>
        <select value={discipline} onChange={(event) => setDiscipline(normalizeDiscipline(event.target.value, "auto"))}>
          {PAPER_READER_DISCIPLINE_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option[language === "zh" ? "zh" : "en"]}
            </option>
          ))}
        </select>
      </label>
    </div>
  );

  const renderPaperLoader = () => (
    <div className="paper-reader-entry-grid">
      <form className="paper-reader-input-card" onSubmit={handleLoadArxiv}>
        <h3>{t("paperReaderArxivUrl")}</h3>
        <label>
          {t("paperReaderArxivUrl")}
          <input
            value={arxivUrl}
            onChange={(event) => setArxivUrl(event.target.value)}
            placeholder="https://arxiv.org/abs/..."
          />
        </label>
        <button type="submit" disabled={sessionBusy}>
          {sessionBusy ? t("working") : t("paperReaderLoadArxiv")}
        </button>
      </form>

      <form className="paper-reader-input-card" onSubmit={handleLoadPdf}>
        <h3>{t("paperReaderPdfFile")}</h3>
        <label>
          {t("paperReaderPdfFile")}
          <input
            ref={fileInputRef}
            type="file"
            accept="application/pdf,.pdf"
            onChange={(event) => setPdfFile(event.target.files?.[0] || null)}
          />
        </label>
        <div className="field-action-row">
          <button type="submit" disabled={sessionBusy || !pdfFile}>
            {sessionBusy ? t("working") : t("paperReaderLoadPdf")}
          </button>
          {pdfFile ? <span className="muted">{pdfFile.name}</span> : <span className="muted">{t("paperReaderSelectedFile")}</span>}
        </div>
      </form>
    </div>
  );

  return (
    <div className="paper-reader-layout paper-reader-layout-redesigned">
      <aside className="assistant-column paper-reader-assistant-column">{renderAssistantLayer?.() || null}</aside>

      <section className="paper-reader-main">
        <section className="workspace paper-reader-hero">
          <div>
            <p className="eyebrow">{copy.productEyebrow}</p>
            <h2>{t("paperReaderTitle")}</h2>
            <p className="muted">{t("paperReaderDescription")}</p>
          </div>
          <div className="paper-reader-summary">
            <span className="reader-status-chip">{readerModelSummary}</span>
            <span className="reader-status-chip">{manifestSummary}</span>
            {session?.discipline ? (
              <span className="reader-status-chip">
                {copy.disciplineLabel}: {getDisciplineLabel(session.discipline, language)} (
                {getDisciplineSourceLabel(session.discipline_source, language)})
              </span>
            ) : null}
          </div>
        </section>

        {shouldShowProgressTracker ? (
          <ProgressTracker
            title={t("paperReaderProgressTitle")}
            subtitle={t("paperReaderProgressSubtitle")}
            steps={readerProgressSteps}
            currentStep={readerProgress.step}
            status={readerProgress.status}
            statusLabel={readerStatusLabels[readerProgress.status] || t("progressIdle")}
            detail={readerProgress.detail}
            updatedAt={readerProgress.updatedAt}
          />
        ) : null}

        <section className={`workspace paper-reader-entry${hasSession ? " paper-reader-entry-compact" : ""}`}>
          {!hasSession ? (
            <>
              {renderReaderModeControls()}
              {renderDisciplineControls()}
              {renderPaperLoader()}
            </>
          ) : (
            <details className="paper-reader-load-drawer">
              <summary>
                <span>{language === "zh" ? "载入另一篇论文" : "Load another paper"}</span>
                <small>
                  {readerMode === "guided" ? copy.quickStoryHint : copy.standardMode} ·{" "}
                  {discipline === "auto" ? getDisciplineLabel("auto", language) : getDisciplineLabel(discipline, language)}
                </small>
              </summary>
              <div className="paper-reader-load-drawer-body">
                {renderReaderModeControls()}
                {renderDisciplineControls()}
                {renderPaperLoader()}
              </div>
            </details>
          )}

          {bannerMessage ? <div className="message">{bannerMessage}</div> : null}
          {bannerError ? <div className="warning-box">{bannerError}</div> : null}
        </section>

        {!session ? (
          <section className="workspace paper-reader-empty-state">
            <p className="muted">{t("paperReaderEmpty")}</p>
          </section>
        ) : (
          <div className="paper-reader-reader-shell">
            <div className="paper-reader-reading-column">
              <section className="workspace paper-reader-page-card paper-reader-page-card-refined" ref={pageCardRef}>
                <div className="paper-reader-meta-bar">
                  <div className="paper-reader-meta-copy">
                    <p className="eyebrow">{copy.pageFocusLabel}</p>
                    <h3>{activeTitleBase}</h3>
                    <div className="reader-current-page-line">
                      <p className="muted">
                        {t("paperReaderCurrentPage")}: {activePageIndex + 1}
                        {pageCount ? ` / ${pageCount}` : ""}
                        {activeTitleCounter ? ` · ${activeTitleCounter}` : ""}
                      </p>
                      <div className="reader-page-icon-nav" aria-label={t("paperReaderCurrentPage")}>
                        <button
                          type="button"
                          className="reader-icon-button"
                          onClick={() => goToPage(activePageIndex - 1)}
                          disabled={activePageIndex <= 0}
                          aria-label={t("paperReaderPreviousPage")}
                        >
                          ‹
                        </button>
                        <button
                          type="button"
                          className="reader-icon-button"
                          onClick={() => goToPage(activePageIndex + 1)}
                          disabled={pageCount ? activePageIndex >= pageCount - 1 : false}
                          aria-label={t("paperReaderNextPage")}
                        >
                          ›
                        </button>
                      </div>
                    </div>
                  </div>
                  <div className="paper-reader-meta-chips">
                    <span className="reader-status-chip">
                      {localizeReaderLabel(firstNonEmpty(activePage?.bucket_label, deriveBucketLabel(activePage), activeTitleBase), language)}
                    </span>
                    <span className="reader-status-chip">{getStatusLabel(activePage?.status || "queued", t)}</span>
                    <span className={`reader-status-chip reader-status-chip-structured reader-status-chip-${activeStructuredState}`}>
                      {getStructuredStatusLabel(activeStructuredState, language)}
                    </span>
                    {activeStoryStage ? <span className="reader-status-chip">{activeStoryStage.title}</span> : null}
                    {session?.discipline ? <span className="reader-status-chip">{getDisciplineLabel(session.discipline, language)}</span> : null}
                    {activePage?.coverage ? <span className="reader-status-chip">{activePage.coverage}</span> : null}
                  </div>
                </div>

                {activePage?.status === "error" && activeStructuredState !== "failed" ? (
                  <div className="warning-box">{activePage.error || t("paperReaderPageLoadFail")}</div>
                ) : null}

                {activePage?.status === "generating" || pageBusyMap[activePageIndex] ? (
                  <div className="reader-loading-state">
                    <span className="progress-liveness progress-liveness-running">
                      <span className="progress-liveness-dot" aria-hidden="true" />
                      <span>{t("loading")}</span>
                    </span>
                  </div>
                ) : null}

                {activeStructuredState === "failed" ? (
                  <section className="reader-structured-failure">
                    <h4>{copy.structuredFailureTitle}</h4>
                    <p>{activeStructuredMessage || copy.structuredFailureBody}</p>
                  </section>
                ) : null}

                {activeOverview ? (
                  <section className="reader-overview-card reader-module-section" id="reader-module-overview">
                    <div className="reader-block-head">
                      <div>
                        <p className="reader-block-label">{copy.overviewTitle}</p>
                        <h4>{activeTitleBase}</h4>
                      </div>
                      {activeOverview.display_text ? <p className="muted reader-overview-summary">{activeOverview.display_text}</p> : null}
                    </div>
                    <BilingualReaderBlock block={activeOverview} copy={copy} />
                  </section>
                ) : null}

                <ReadingBlocks blocks={activeReadingBlocks} activeSourceId={activeSourceId} copy={copy} />

                <div className="reader-navigation">
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => goToPage(activePageIndex - 1)}
                    disabled={activePageIndex <= 0}
                  >
                    {t("paperReaderPreviousPage")}
                  </button>
                  <button
                    type="button"
                    onClick={() => goToPage(activePageIndex + 1)}
                    disabled={pageCount ? activePageIndex >= pageCount - 1 : false}
                  >
                    {t("paperReaderNextPage")}
                  </button>
                </div>
              </section>
            </div>

            <aside className="paper-reader-card-column">
              <section className="workspace paper-reader-session-card">
                <div>
                  <p className="eyebrow">{copy.navigationTitle}</p>
                  <h3>{firstNonEmpty(session.paper_title, t("paperReaderTitle"))}</h3>
                  <p className="muted">
                    {t("paperReaderSessionId")}: {session.session_id || t("none")}
                  </p>
                  <p className="muted">{firstNonEmpty(session.arxiv_id, session.file_name, session.source || t("none"))}</p>
                </div>
                <div className="paper-reader-outline-meta">
                  <span className="reader-status-chip">{`${t("paperReaderPageCount")}: ${pageCount || "-"}`}</span>
                  <span className="reader-status-chip">{`${t("paperReaderCurrentStatus")}: ${getStatusLabel(currentPageStatus, t)}`}</span>
                  <span className="reader-status-chip">{`${copy.disciplineLabel}: ${getDisciplineLabel(session.discipline, language)}`}</span>
                </div>
                <div className="paper-reader-page-jump-list">
                  {pageEntries.map((page) => (
                    <button
                      key={page.page_index}
                      type="button"
                      className={`reader-page-subanchor${page.page_index === activePageIndex ? " active" : ""}`}
                      onClick={() => goToPage(page.page_index)}
                    >
                      {page.page_index + 1}
                    </button>
                  ))}
                </div>
                {activeSourceSections.length ? (
                  <div className="reader-source-chip-list">
                    {activeSourceSections.slice(0, 4).map((section, index) => (
                      <span key={`${section.label}-${index}`} className="reader-source-chip">
                        <span>{section.label}</span>
                        {formatPageRange(section.page_start, section.page_end, copy) ? (
                          <small>{formatPageRange(section.page_start, section.page_end, copy)}</small>
                        ) : null}
                      </span>
                    ))}
                  </div>
                ) : null}
                <button type="button" className="secondary" onClick={exportResearchNotes} disabled={!pageEntries.length}>
                  {copy.exportNotes}
                </button>
              </section>

              <DisciplineCards
                cards={activeDisciplineCards}
                activeSourceId={activeSourceId}
                onActivate={activateDisciplineCard}
                onClear={() => setActiveSourceId("")}
                onOpen={openDisciplineCard}
                copy={copy}
              />
            </aside>
          </div>
        )}
      </section>
    </div>
  );
}
