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

function firstSentence(text, maxLength = 180) {
  const normalized = sanitizeText(text);
  if (!normalized) {
    return "";
  }
  const first = normalized.split(/(?<=[。！？.!?])\s+/)[0] || normalized;
  return first.length > maxLength ? `${first.slice(0, maxLength).trim()}...` : first;
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
        contentPair.explanation,
        contentPair.original
      );
      return explanation ? { original, explanation } : null;
    })
    .filter(Boolean);
}

function ensureWhyItems(items, explanationText) {
  if (items?.length) {
    return items;
  }
  const fallback = firstSentence(explanationText);
  return fallback ? [{ original: "", explanation: fallback }] : [];
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
      why_it_matters: ensureWhyItems(fallback.why_it_matters || [], explanationText),
      citations: fallback.citations || [],
      supporting_points: fallback.supporting_points || [],
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
  const whyItems = normalizeWhyItems(
    raw.why_it_matters ||
      raw.whyItMatters ||
      raw.significance ||
      raw.importance ||
      raw.takeaway ||
      raw.takeaways ||
      raw.relevance ||
      raw.notes
  );

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

  const derivedWhyItems = evidenceBlocks
    .map((block) => ({
      original: firstNonEmpty(block?.original_en),
      explanation: firstNonEmpty(block?.explanation, block?.display_text)
    }))
    .filter((item) => item.explanation);
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
    why_it_matters: ensureWhyItems(
      whyItems.length ? whyItems : derivedWhyItems.length ? derivedWhyItems : fallback.why_it_matters || [],
      explanationText
    ),
    citations: citations.length ? citations : fallback.citations || [],
    supporting_points: supportingPoints.length ? supportingPoints : fallback.supporting_points || [],
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
  const sharedWhyItems = [...normalizeWhyItems(keyPoints), ...normalizeWhyItems(limitations)];
  const citationFallbackText = firstNonEmpty(
    citations.map((citation) => firstNonEmpty(citation.excerpt, citation.text))
  );

  const sectionCards = sections
    .map((section, index) => {
      const pair = splitReaderContent(section.text);
      const sectionWhy = normalizeWhyItems(section.bullets);
      const sectionCitations = section.citations?.length ? section.citations : citations;
      const originalText = firstNonEmpty(
        pair.original,
        sectionCitations.map((citation) => firstNonEmpty(citation.excerpt, citation.text)),
        summaryPair.original,
        citationFallbackText
      );
      const explanationText = firstNonEmpty(pair.explanation, summaryPair.explanation, summaryPair.original);
      if (!originalText && !explanationText && !sectionWhy.length) {
        return null;
      }
      return {
        id: `page-${pageIndex}-section-${index}`,
        title: firstNonEmpty(section.title, `Insight ${index + 1}`),
        eyebrow: index === 0 ? firstNonEmpty(bucketLabel) : "",
        original_text: originalText,
        explanation_text: explanationText,
        why_it_matters: ensureWhyItems(sectionWhy.length ? sectionWhy : sharedWhyItems.slice(0, 2), explanationText),
        citations: sectionCitations.slice(0, 4),
        supporting_points: section.bullets?.slice(0, 3) || [],
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
      why_it_matters: ensureWhyItems(sharedWhyItems.slice(0, 2), leadExplanation || leadOriginal),
      citations: citations.slice(0, 4),
      supporting_points: [...normalizeList(keyPoints), ...normalizeList(limitations)].slice(0, 3),
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
        why_it_matters: ensureWhyItems(sharedWhyItems.slice(0, 2), explanationText),
        citations: citations.slice(0, 4),
        supporting_points: [],
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
    const fallbackWhy = [...normalizeWhyItems(keyPoints), ...normalizeWhyItems(limitations)].slice(0, 2);
    const normalized = structuredInsights
      .map((item, index) =>
        normalizeInsightCard(item, index, {
          id: `page-${pageIndex}-structured-${index}`,
          title: `${stripPageCountSuffix(title) || "Insight"} ${index + 1}`,
          eyebrow: bucketLabel,
          original_text: summaryPair.original,
          explanation_text: summaryPair.explanation,
          why_it_matters: fallbackWhy,
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
    source_sections: update.source_sections?.length ? update.source_sections : base.source_sections || [],
    page_overview: update.page_overview || base.page_overview || null,
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
    source_sections: sourceSections,
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
    max_context_tokens: toNumber(raw.max_context_tokens ?? raw.maxContextTokens ?? 0, 0),
    page_input_budget: toNumber(raw.page_input_budget ?? raw.pageInputBudget ?? 0, 0),
    current_page_index: toNumber(raw.current_page_index ?? raw.currentPageIndex ?? raw.page_index ?? 0, 0),
    page_count: toNumber(raw.page_count ?? raw.pageCount ?? pagesRaw.length, pagesRaw.length),
    pages: pagesRaw
      .map((page, index) => normalizePageEntry(page, index))
      .filter(Boolean)
      .sort((left, right) => left.page_index - right.page_index),
    current_page: normalizePageEntry(raw.current_page || raw.currentPage || raw.page || raw.page_content, raw.current_page_index ?? 0)
  };
}

function normalizeChatResponse(raw) {
  return {
    reply_text: firstNonEmpty(raw?.reply_text, raw?.answer, raw?.answer_text, raw?.content),
    speak_text: firstNonEmpty(raw?.speak_text, raw?.reply_text, raw?.answer, raw?.answer_text, raw?.content),
    session_id: firstNonEmpty(raw?.session_id, raw?.sessionId),
    expression: firstNonEmpty(raw?.expression, raw?.face, raw?.emotion),
    memory_used: Boolean(raw?.memory_used),
    memory_notice: firstNonEmpty(raw?.memory_notice, raw?.memoryNotice),
    used_memory_items: Array.isArray(raw?.used_memory_items) ? raw.used_memory_items : Array.isArray(raw?.usedMemoryItems) ? raw.usedMemoryItems : [],
    citations: normalizeCitations(raw?.citations),
    used_chunks: Array.isArray(raw?.used_chunks) ? raw.used_chunks : Array.isArray(raw?.usedChunks) ? raw.usedChunks : []
  };
}

function extractAssistantContextText(page) {
  return firstNonEmpty(
    page?.page_overview?.display_text,
    page?.page_overview?.explanation,
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
    page_index: pageIndex,
    page_title: page?.title || null,
    latest_page_summary: extractAssistantContextText(page) || null,
    latest_answer_text: firstNonEmpty(answerText),
    question: String(question || "").trim() || null
  };
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
      navigationTitle: "阅读导航",
      bucketLabel: "Bucket",
      pageWord: t("paperReaderPageLabel"),
      partWord: "分片",
      sourcePages: "原始页码",
      originalLabel: "Original (EN)",
      explanationLabel: "页面语言解读",
      whyLabel: "Why it matters",
      citationsLabel: t("paperReaderCitations"),
      noOriginal: "暂无可展示的英文原文片段。",
      noExplanation: "当前还没有可展示的页面解读。",
      noInsights: "当前页还没有结构化 insight cards。",
      pagesShort: "页",
      overviewTitle: "本页导读",
      sourceSectionsTitle: "覆盖章节",
      evidenceLabel: "证据线索",
      structuredFailureTitle: "本页结构化解析失败",
      structuredFailureBody: "我没有展示原始模型文本，而是保留了安全失败态。你可以重试本页，或跳到下一页继续阅读。",
      pageFocusLabel: "当前阅读焦点"
    };
  }
  return {
    navigationTitle: "Reading Navigation",
    bucketLabel: "Bucket",
    pageWord: t("paperReaderPageLabel"),
    partWord: "Part",
    sourcePages: "Source pages",
    originalLabel: "Original (EN)",
    explanationLabel: "Page-language reading",
    whyLabel: "Why it matters",
    citationsLabel: t("paperReaderCitations"),
    noOriginal: "No grounded English excerpt yet.",
    noExplanation: "No page interpretation yet.",
    noInsights: "No structured insight cards for this page yet.",
    pagesShort: "pp.",
    overviewTitle: "Page overview",
    sourceSectionsTitle: "Covered sections",
    evidenceLabel: "Evidence trail",
    structuredFailureTitle: "Structured page parsing failed",
    structuredFailureBody:
      "Raw model output is intentionally hidden here. Retry this page, or continue to the next page while the reader keeps the safe failure state.",
    pageFocusLabel: "Current focus"
  };
}

function buildPageBuckets(pages) {
  const buckets = [];
  const bucketMap = new Map();

  pages.forEach((page) => {
    const label = firstNonEmpty(page.bucket_label, stripPageCountSuffix(page.title), page.coverage, `Page ${page.page_index + 1}`);
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

export default function PaperReaderPage({
  language,
  t,
  settings,
  runtimePayload,
  renderAssistantLayer,
  onScheduleAssistantAutoReply
}) {
  const paperReaderConfig = settings?.paper_reader_chat || {};
  const [arxivUrl, setArxivUrl] = useState("");
  const [pdfFile, setPdfFile] = useState(null);
  const [session, setSession] = useState(null);
  const [pagesByIndex, setPagesByIndex] = useState({});
  const [activePageIndex, setActivePageIndex] = useState(0);
  const [chatDraft, setChatDraft] = useState("");
  const [chatMessages, setChatMessages] = useState([]);
  const [sessionBusy, setSessionBusy] = useState(false);
  const [pageBusyMap, setPageBusyMap] = useState({});
  const [chatBusy, setChatBusy] = useState(false);
  const [bannerMessage, setBannerMessage] = useState("");
  const [bannerError, setBannerError] = useState("");
  const [readerProgress, setReaderProgress] = useState({
    step: "load",
    status: "idle",
    detail: "",
    updatedAt: null
  });
  const streamRefs = useRef(new Map());
  const pollRefs = useRef(new Map());
  const autoReplyKeyRef = useRef("");
  const activeRequestRef = useRef(0);
  const fileInputRef = useRef(null);

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
      { key: "page", label: t("paperReaderProgressPage") },
      { key: "chat", label: t("paperReaderProgressChat") }
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
  const pageBuckets = useMemo(() => buildPageBuckets(pageEntries), [pageEntries]);
  const activeStructuredState = activePage?.structured_status?.state || "pending";
  const activeStructuredMessage = firstNonEmpty(activePage?.structured_status?.message, activePage?.error);
  const activeOverview = activePage?.page_overview || null;
  const activeSourceSections = activePage?.source_sections || [];
  const activeInsights = activePage?.insights || [];
  const activeTitle = firstNonEmpty(activePage?.title, `${t("paperReaderPageLabel")} ${activePageIndex + 1}`);
  const activeTitleBase = stripPageCountSuffix(activeTitle) || activeTitle;
  const activeTitleCounter = extractPageCounter(activeTitle);

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
    if (autoReplyKeyRef.current === cacheKey) {
      return;
    }
    autoReplyKeyRef.current = cacheKey;
    onScheduleAssistantAutoReply?.({
      source: "qa_auto",
      answerContext: extractAssistantContextText(activePage),
      workflowContext
    });
  }, [activePage, currentPageStatus, language, onScheduleAssistantAutoReply, session]);

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
    setChatMessages([]);
    setChatDraft("");
    setBannerMessage("");
    setBannerError("");
    setPageBusyMap({});
    setReaderProgress({
      step: "load",
      status: "idle",
      detail: "",
      updatedAt: null
    });
    autoReplyKeyRef.current = "";
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
            scheduleAssistantForPage(page, "");
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
              scheduleAssistantForPage(page, "");
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
        scheduleAssistantForPage(existing, "");
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
          scheduleAssistantForPage(snapshot, "");
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

  function scheduleAssistantForPage(page, answerText) {
    if (!page || !session?.session_id || typeof onScheduleAssistantAutoReply !== "function") {
      return;
    }
    const cacheKey = `${session.session_id}:page:${page.page_index}:${page.status}:${
      answerText || page.page_overview?.display_text || page.summary || page.text || ""
    }`;
    if (autoReplyKeyRef.current === cacheKey) {
      return;
    }
    autoReplyKeyRef.current = cacheKey;
    onScheduleAssistantAutoReply({
      source: "qa_auto",
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

  async function handleLoadArxiv(event) {
    event.preventDefault();
    const url = String(arxivUrl || "").trim();
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
    if (session?.session_id) {
      setSession((current) => (current ? { ...current, current_page_index: normalizedIndex } : current));
      void ensurePageReady(normalizedIndex, { sessionId: session?.session_id });
    }
  }

  async function handleAskPaper(event) {
    event.preventDefault();
    const sessionId = session?.session_id;
    if (!sessionId) {
      setBannerError(t("paperReaderNoSession"));
      return;
    }
    const message = String(chatDraft || "").trim();
    if (!message) {
      return;
    }
    setChatBusy(true);
    setBannerError("");
    updateReaderProgress("chat", "running", t("paperReaderProgressChat"));
    setChatMessages((current) => [...current, { role: "user", text: message }]);
    setChatDraft("");
    try {
      const response = await fetch(`/api/paper-reader/session/${encodeURIComponent(sessionId)}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message,
          history: chatMessages.slice(-10).map((entry) => ({ role: entry.role, text: entry.text })),
          page_index: activePageIndex,
          answer_language: language,
          settings: runtimePayload
        })
      });
      const payload = await readJsonWithDetailFallback(response);
      if (!response.ok) {
        throw new Error(payload.detail || `${t("paperReaderChatFail")} (HTTP ${response.status})`);
      }
      const normalized = normalizeChatResponse(payload);
      const answerText = firstNonEmpty(normalized.reply_text, t("paperReaderNoContent"));
      setChatMessages((current) => [
        ...current,
        {
          role: "assistant",
          text: answerText,
          citations: normalized.citations,
          usedChunks: normalized.used_chunks
        }
      ]);
      if (normalized.citations.length || normalized.used_chunks.length) {
        setBannerMessage("");
      }
      const page = activePage || pagesByIndex[activePageIndex] || null;
      onScheduleAssistantAutoReply?.({
        source: "qa_auto",
        answerContext: answerText,
        workflowContext: buildPaperReaderWorkflowContext({
          session,
          page,
          answerText,
          question: message,
          language
        })
      });
      if (normalized.session_id && normalized.session_id !== session.session_id) {
        setSession((current) => (current ? { ...current, session_id: normalized.session_id } : current));
      }
      updateReaderProgress("chat", "completed", t("paperReaderProgressChat"));
    } catch (error) {
      setBannerError(String(error));
      updateReaderProgress("chat", "interrupted", String(error));
      setChatMessages((current) => [
        ...current,
        {
          role: "assistant",
          text: String(error)
        }
      ]);
    } finally {
      setChatBusy(false);
    }
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

  return (
    <div className="paper-reader-layout">
      <section className="paper-reader-main">
        <section className="workspace paper-reader-hero">
          <div>
            <p className="eyebrow">paper-reader</p>
            <h2>{t("paperReaderTitle")}</h2>
            <p className="muted">{t("paperReaderDescription")}</p>
          </div>
          <div className="paper-reader-summary">
            <span className="reader-status-chip">{readerModelSummary}</span>
            <span className="reader-status-chip">{manifestSummary}</span>
          </div>
        </section>

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

        <section className="workspace paper-reader-entry">
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

          {bannerMessage ? <div className="message">{bannerMessage}</div> : null}
          {bannerError ? <div className="warning-box">{bannerError}</div> : null}
        </section>

        {!session ? (
          <section className="workspace paper-reader-empty-state">
            <p className="muted">{t("paperReaderEmpty")}</p>
          </section>
        ) : (
          <>
            <div className="paper-reader-reader-shell">
              <section className="workspace paper-reader-outline-card">
                <div className="paper-reader-outline-head">
                  <p className="eyebrow">{copy.navigationTitle}</p>
                  <h3>{firstNonEmpty(session.paper_title, t("paperReaderTitle"))}</h3>
                  <p className="muted">
                    {t("paperReaderSessionId")}: {session.session_id || t("none")}
                  </p>
                  <p className="muted">
                    {firstNonEmpty(session.arxiv_id, session.file_name, session.source || t("none"))}
                  </p>
                  <div className="paper-reader-outline-meta">
                    <span className="reader-status-chip">{`${t("paperReaderPageCount")}: ${pageCount || "-"}`}</span>
                    <span className="reader-status-chip">{`${t("paperReaderCurrentStatus")}: ${getStatusLabel(currentPageStatus, t)}`}</span>
                  </div>
                </div>

                <div className="paper-reader-outline-groups">
                  {pageBuckets.length ? (
                    pageBuckets.map((bucket) => (
                      <section key={bucket.key} className="paper-reader-outline-group">
                        <div className="paper-reader-outline-group-head">
                          <span className="paper-reader-outline-label">{copy.bucketLabel}</span>
                          <h4>{bucket.label}</h4>
                        </div>
                        <div className="paper-reader-outline-list">
                          {bucket.pages.map((page) => (
                            <button
                              key={page.page_index}
                              type="button"
                              className={`reader-page-pill${page.page_index === activePageIndex ? " active" : ""}`}
                              onClick={() => goToPage(page.page_index)}
                            >
                              <span className="reader-page-pill-title">
                                {stripPageCountSuffix(page.title || `${t("paperReaderPageLabel")} ${page.page_index + 1}`)}
                              </span>
                              <span className="reader-page-pill-meta">
                                <span className="reader-page-pill-status">{getStatusLabel(page.status, t)}</span>
                                {extractPageCounter(page.title) ? (
                                  <span className="reader-page-pill-counter">{extractPageCounter(page.title)}</span>
                                ) : null}
                              </span>
                            </button>
                          ))}
                        </div>
                      </section>
                    ))
                  ) : (
                    <p className="muted">{t("paperReaderNoContent")}</p>
                  )}
                </div>
              </section>

              <div className="paper-reader-reading-column">
                <section className="workspace paper-reader-page-card paper-reader-page-card-refined">
                  <div className="paper-reader-meta-bar">
                    <div className="paper-reader-meta-copy">
                      <p className="eyebrow">{copy.pageFocusLabel}</p>
                      <h3>{activeTitleBase}</h3>
                      <p className="muted">
                        {t("paperReaderCurrentPage")}: {activePageIndex + 1}
                        {pageCount ? ` / ${pageCount}` : ""}
                        {activeTitleCounter ? ` · ${activeTitleCounter}` : ""}
                      </p>
                    </div>
                    <div className="paper-reader-meta-chips">
                      <span className="reader-status-chip">{firstNonEmpty(activePage?.bucket_label, deriveBucketLabel(activePage), activeTitleBase)}</span>
                      <span className="reader-status-chip">{getStatusLabel(activePage?.status || "queued", t)}</span>
                      <span className={`reader-status-chip reader-status-chip-structured reader-status-chip-${activeStructuredState}`}>
                        {getStructuredStatusLabel(activeStructuredState, language)}
                      </span>
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
                    <section className="reader-overview-card">
                      <div className="reader-block-head">
                        <div>
                          <p className="reader-block-label">{copy.overviewTitle}</p>
                          <h4>{activeTitleBase}</h4>
                        </div>
                        {activeOverview.display_text ? <p className="muted reader-overview-summary">{activeOverview.display_text}</p> : null}
                      </div>
                      <div className="reader-tone-stack">
                        <div className="reader-tone-card reader-tone-original">
                          <span className="reader-tone-label">{copy.originalLabel}</span>
                          <p>{firstNonEmpty(activeOverview.original_en, copy.noOriginal)}</p>
                        </div>
                        <div className="reader-tone-card reader-tone-explanation">
                          <span className="reader-tone-label">{copy.explanationLabel}</span>
                          <p>{firstNonEmpty(activeOverview.explanation, activeOverview.display_text, copy.noExplanation)}</p>
                        </div>
                      </div>
                    </section>
                  ) : null}

                  {activeSourceSections.length ? (
                    <section className="reader-source-section-block">
                      <p className="reader-block-label">{copy.sourceSectionsTitle}</p>
                      <div className="reader-source-chip-list">
                        {activeSourceSections.map((section, index) => (
                          <span key={`${section.label}-${index}`} className="reader-source-chip">
                            <span>{section.label}</span>
                            {formatPageRange(section.page_start, section.page_end, copy) ? (
                              <small>{formatPageRange(section.page_start, section.page_end, copy)}</small>
                            ) : null}
                          </span>
                        ))}
                      </div>
                    </section>
                  ) : null}

                  <div className="reader-insight-grid">
                    {activeInsights.length ? (
                      activeInsights.map((card, index) => (
                        <article key={card.id || `${activePageIndex}-${index}`} className="reader-insight-card">
                          <div className="reader-insight-head">
                            <div>
                              {firstNonEmpty(card.eyebrow, card.source_section_labels?.[0]) ? (
                                <p className="reader-insight-eyebrow">{firstNonEmpty(card.eyebrow, card.source_section_labels?.[0])}</p>
                              ) : null}
                              <h4>{card.title}</h4>
                            </div>
                            {card.source_section_labels?.length ? (
                              <div className="reader-inline-chip-list">
                                {card.source_section_labels.slice(0, 2).map((label) => (
                                  <span key={label} className="reader-inline-chip">
                                    {label}
                                  </span>
                                ))}
                              </div>
                            ) : null}
                          </div>

                          <div className="reader-tone-stack reader-tone-stack-tight">
                            <div className="reader-tone-card reader-tone-original">
                              <span className="reader-tone-label">{copy.originalLabel}</span>
                              <p>{firstNonEmpty(card.original_text, copy.noOriginal)}</p>
                            </div>
                            <div className="reader-tone-card reader-tone-explanation">
                              <span className="reader-tone-label">{copy.explanationLabel}</span>
                              <p>{firstNonEmpty(card.explanation_text, copy.noExplanation)}</p>
                            </div>
                          </div>

                          <div className="reader-insight-footer">
                            {card.supporting_points?.length ? (
                              <div className="reader-support-list">
                                <p className="reader-block-label">{copy.evidenceLabel}</p>
                                {card.supporting_points.slice(0, 3).map((item, itemIndex) => (
                                  <p key={`${card.id || index}-support-${itemIndex}`} className="reader-support-item">
                                    {item}
                                  </p>
                                ))}
                              </div>
                            ) : null}

                            {card.why_it_matters?.length ? (
                              <div className="reader-why-stack">
                                <p className="reader-block-label">{copy.whyLabel}</p>
                                {card.why_it_matters.slice(0, 2).map((item, itemIndex) => (
                                  <div key={`${card.id || index}-why-${itemIndex}`} className="reader-why-item">
                                    <p>{firstNonEmpty(item.explanation, item.original)}</p>
                                  </div>
                                ))}
                              </div>
                            ) : null}

                            {card.citations?.length ? (
                              <div className="reader-citation-list">
                                {card.citations.slice(0, 4).map((citation, citationIndex) => (
                                  <span key={`${card.id || index}-citation-${citationIndex}`} className="reader-citation-chip">
                                    {formatCitationLabel(citation, copy, citationIndex)}
                                  </span>
                                ))}
                              </div>
                            ) : null}
                          </div>
                        </article>
                      ))
                    ) : activePage?.status === "ready" && activeStructuredState !== "failed" ? (
                      <div className="reader-structured-empty">
                        <p>{copy.noInsights}</p>
                      </div>
                    ) : null}
                  </div>

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

                <section className="workspace paper-reader-chat-card">
                  <div className="paper-reader-chat-head">
                    <div>
                      <h3>{t("paperReaderChatTitle")}</h3>
                      <p className="muted">{activeTitleBase}</p>
                    </div>
                    <span className="reader-status-chip">{getStatusLabel(activePage?.status || "queued", t)}</span>
                  </div>
                  <form className="reader-chat-composer" onSubmit={handleAskPaper}>
                    <label>
                      {t("paperReaderQuestionTitle")}
                      <textarea
                        value={chatDraft}
                        onChange={(event) => setChatDraft(event.target.value)}
                        rows={4}
                        placeholder={t("paperReaderQuestionPlaceholder")}
                      />
                    </label>
                    <button type="submit" disabled={chatBusy || !chatDraft.trim() || !session?.session_id}>
                      {chatBusy ? t("working") : t("paperReaderAsk")}
                    </button>
                  </form>

                  <div className="reader-chat-thread">
                    {chatMessages.length ? (
                      chatMessages.map((entry, index) => (
                        <article key={`${entry.role}-${index}-${entry.text}`} className={`reader-chat-message reader-chat-message-${entry.role}`}>
                          <p>{entry.text}</p>
                          {entry.citations?.length ? (
                            <div className="tag-list">
                              {entry.citations.map((citation, citationIndex) => (
                                <span key={`${citation.label || "citation"}-${citationIndex}`} className="tag">
                                  {formatCitationLabel(citation, copy, citationIndex)}
                                </span>
                              ))}
                            </div>
                          ) : null}
                          {entry.usedChunks?.length ? <p className="muted">{`${entry.usedChunks.length} chunks`}</p> : null}
                        </article>
                      ))
                    ) : (
                      <p className="muted">{t("paperReaderNoContent")}</p>
                    )}
                  </div>
                </section>
              </div>
            </div>
          </>
        )}
      </section>

      <aside className="assistant-column">{renderAssistantLayer?.() || null}</aside>
    </div>
  );
}
