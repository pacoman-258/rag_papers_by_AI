from __future__ import annotations

import ast
import json
import math
import re
import tempfile
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import requests
from pypdf import PdfReader, PdfWriter

from backend.schemas import (
    PaperReaderBlackboardNotesModel,
    PaperReaderCitationModel,
    PaperReaderChatRequest,
    PaperReaderChatResponse,
    PaperReaderChunkModel,
    PaperReaderCheckpointModel,
    PaperReaderDisciplineGuideModel,
    PaperReaderDisciplineGuidePanelModel,
    PaperReaderGlossaryTermModel,
    PaperReaderInsightModel,
    PaperReaderIndexNodeModel,
    PaperReaderPageContentModel,
    PaperReaderPageManifestModel,
    PaperReaderReadingBlockModel,
    PaperReaderReadingHintModel,
    PaperReaderSectionModel,
    PaperReaderSelectionTranslateRequest,
    PaperReaderSelectionTranslateResponse,
    PaperReaderSessionModel,
    PaperReaderSelectedNodeModel,
    PaperReaderSourcePageModel,
    PaperReaderSourcePagesResponse,
    PaperReaderSourceSectionModel,
    PaperReaderSourceTextSpanModel,
    PaperReaderStoryStageModel,
    PaperReaderStructuredStatusModel,
    PaperReaderStructuredTextModel,
)
from local_paper_db.app.external_sources import fetch_arxiv_record
from local_paper_db.app.search_service import (
    ChatConfig,
    RuntimeSettings,
    chat_completion,
    cosine_similarity,
    extract_arxiv_base_id,
    extract_first_json_object,
    get_embedding,
    infer_user_language,
    normalize_whitespace,
    stream_chat_tokens,
)


DEFAULT_MAX_CONTEXT_TOKENS = 8192
DEFAULT_TARGET_PAGE_TOKENS = 6000
DEFAULT_TARGET_CHUNK_TOKENS = 1800
DISCIPLINES = {
    "general",
    "science_engineering",
    "mathematics",
    "medicine_biology",
    "economics_social_science",
    "philosophy_humanities",
    "policy_law",
}
DISCIPLINE_READING_FOCUS_ORDERS: dict[str, tuple[tuple[str, str], ...]] = {
    "general": (
        ("quick_story", "Quick Story"),
        ("core_question", "Core question"),
        ("method_or_mechanism", "Method or mechanism"),
        ("evidence_or_experiments", "Evidence or experiments"),
        ("conclusion", "Conclusion"),
        ("open_questions_or_limitations", "Open questions or limitations"),
    ),
    "science_engineering": (
        ("problem_and_claim", "Problem and claim"),
        ("method_or_system", "Method or system"),
        ("experiments_and_results", "Experiments and results"),
        ("conclusion_and_limits", "Conclusion and limits"),
    ),
    "mathematics": (
        ("statement_to_prove", "Statement to prove"),
        ("definitions_and_setup", "Definitions and setup"),
        ("proof_strategy", "Proof strategy"),
        ("key_proof_steps", "Key proof steps"),
        ("implications_and_open_problems", "Implications and open problems"),
    ),
    "medicine_biology": (
        ("mechanism_or_intervention", "Mechanism or intervention"),
        ("study_design_and_evidence_level", "Study design and evidence level"),
        ("measurement_and_mechanism", "Measurement and mechanism"),
        ("results_and_evidence_strength", "Results and evidence strength"),
        ("limitations_and_safety", "Limitations and safety"),
    ),
    "economics_social_science": (
        ("explanation_or_hypothesis", "Explanation or hypothesis"),
        ("data_and_identification", "Data and identification"),
        ("causal_evidence_and_robustness", "Causal evidence and robustness"),
        ("implications", "Implications"),
        ("threats_to_validity", "Threats to validity"),
    ),
    "philosophy_humanities": (
        ("question_and_context", "Question and context"),
        ("concept_definitions", "Concept definitions"),
        ("argument_structure", "Argument structure"),
        ("evidence_and_interpretation", "Evidence and interpretation"),
        ("objections_and_stakes", "Objections and stakes"),
    ),
    "policy_law": (
        ("practical_problem", "Practical problem"),
        ("rules_and_institutions", "Rules and institutions"),
        ("interests_and_tradeoffs", "Interests and trade-offs"),
        ("consequences_and_enforcement", "Consequences and enforcement"),
        ("risks_and_open_issues", "Risks and open issues"),
    ),
}
READING_FOCUS_ORDER = DISCIPLINE_READING_FOCUS_ORDERS["general"]
DISCIPLINE_DISPLAY_NAMES = {
    "general": "General",
    "science_engineering": "Science / engineering",
    "mathematics": "Mathematics",
    "medicine_biology": "Medicine / biology",
    "economics_social_science": "Economics / social science",
    "philosophy_humanities": "Philosophy / humanities",
    "policy_law": "Policy / law",
}
DISCIPLINE_PROMPT_GUIDANCE = {
    "general": "Explain the paper by identifying the core question, method or mechanism, evidence, conclusion, and limitations.",
    "science_engineering": "Prioritize the proposed method or system, the problem it solves, the experimental setup, and whether results prove the method effective.",
    "mathematics": "Prioritize the statement to prove, definitions, theorem dependencies, proof strategy, inference steps, and possible gaps in reasoning. Do not invent experiments.",
    "medicine_biology": "Prioritize the mechanism or intervention, study design, measurement, evidence strength, uncertainty, safety, and biological or clinical limitations.",
    "economics_social_science": "Prioritize the explanation or hypothesis, data source, identification strategy, causal claims, robustness, and threats to validity.",
    "philosophy_humanities": "Prioritize the question being answered, concept definitions, argument structure, interpretive evidence, objections, and whether the argument holds.",
    "policy_law": "Prioritize the practical problem, rules and institutions, stakeholder interests, trade-offs, consequences, enforcement, and legal or policy risks.",
}
DISCIPLINE_GUIDE_PANEL_TEMPLATES: dict[str, tuple[tuple[str, str], ...]] = {
    "general": (
        ("question", "Core question"),
        ("approach", "Approach or mechanism"),
        ("evidence", "Evidence check"),
        ("limits", "Limits and next questions"),
    ),
    "science_engineering": (
        ("problem", "Problem"),
        ("method", "Method or mechanism"),
        ("experiment", "Experiment design"),
        ("validity", "Effectiveness judgment"),
    ),
    "mathematics": (
        ("statement", "Statement to prove"),
        ("definitions", "Key definitions"),
        ("proof_route", "Proof route"),
        ("reasoning_risks", "Reasoning pitfalls"),
    ),
    "medicine_biology": (
        ("mechanism", "Mechanism or intervention"),
        ("design", "Study design"),
        ("evidence_strength", "Evidence strength"),
        ("safety_limits", "Safety and limitations"),
    ),
    "economics_social_science": (
        ("hypothesis", "Explanation or hypothesis"),
        ("data", "Data source"),
        ("identification", "Identification strategy"),
        ("causal_reliability", "Causal reliability"),
    ),
    "philosophy_humanities": (
        ("question", "Question in context"),
        ("concepts", "Concept definitions"),
        ("argument", "Argument chain"),
        ("objections", "Objections and tensions"),
    ),
    "policy_law": (
        ("problem", "Practical problem"),
        ("rules", "Rules and institutions"),
        ("tradeoffs", "Interests and trade-offs"),
        ("consequences", "Consequences and enforcement"),
    ),
}
DISCIPLINE_CATEGORY_PREFIXES = {
    "mathematics": ("math.",),
    "medicine_biology": ("q-bio.",),
    "economics_social_science": ("econ.", "q-fin."),
    "science_engineering": (
        "cs.",
        "eess.",
        "physics.",
        "astro-ph.",
        "cond-mat.",
        "gr-qc",
        "hep-",
        "nlin.",
        "nucl-",
        "quant-ph",
        "stat.ml",
    ),
}
DISCIPLINE_DETECTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "mathematics": (
        "theorem",
        "lemma",
        "proof",
        "corollary",
        "definition",
        "proposition",
        "conjecture",
        "manifold",
        "algebra",
        "topology",
    ),
    "medicine_biology": (
        "clinical",
        "trial",
        "patient",
        "patients",
        "biomarker",
        "intervention",
        "treatment",
        "gene",
        "protein",
        "cell",
        "survival",
        "safety",
        "disease",
    ),
    "economics_social_science": (
        "causal",
        "identification",
        "instrumental",
        "variables",
        "panel data",
        "survey",
        "regression",
        "robustness",
        "policy effect",
        "econometric",
        "social",
    ),
    "philosophy_humanities": (
        "philosophy",
        "concept",
        "argument",
        "objection",
        "ontology",
        "epistemology",
        "ethics",
        "interpretation",
        "hermeneutic",
        "history",
        "literary",
    ),
    "policy_law": (
        "law",
        "legal",
        "statute",
        "court",
        "courts",
        "regulation",
        "compliance",
        "enforcement",
        "rights",
        "liability",
        "governance",
    ),
    "science_engineering": (
        "algorithm",
        "architecture",
        "system",
        "model",
        "benchmark",
        "experiment",
        "evaluation",
        "dataset",
        "sensor",
        "engineering",
        "physics",
    ),
}
FOCUS_KEYWORDS: dict[str, tuple[str, ...]] = {
    "core_question": ("abstract", "introduction", "background", "motivation", "problem", "overview", "preliminar", "related work"),
    "method_or_mechanism": ("method", "approach", "model", "architecture", "algorithm", "framework", "training", "implementation", "mechanism"),
    "evidence_or_experiments": ("experiment", "evaluation", "result", "analysis", "ablation", "benchmark", "dataset", "performance", "case study"),
    "conclusion": ("conclusion", "conclusions", "closing", "final remarks", "summary"),
    "open_questions_or_limitations": ("limitation", "limitations", "future work", "open question", "discussion", "failure", "risk", "ethic", "societal impact"),
    "problem_and_claim": ("abstract", "introduction", "problem", "challenge", "claim", "motivation"),
    "method_or_system": ("method", "system", "architecture", "algorithm", "framework", "implementation", "model"),
    "experiments_and_results": ("experiment", "evaluation", "result", "benchmark", "ablation", "performance", "dataset"),
    "conclusion_and_limits": ("conclusion", "limitation", "future work", "discussion", "risk"),
    "statement_to_prove": ("theorem", "lemma", "proposition", "corollary", "conjecture", "we prove", "main result"),
    "definitions_and_setup": ("definition", "notation", "preliminar", "setup", "assumption", "let ", "denote"),
    "proof_strategy": ("proof", "strategy", "it suffices", "sketch", "induction", "contradiction", "construction"),
    "key_proof_steps": ("proof", "lemma", "case", "therefore", "hence", "implies", "bound", "estimate"),
    "implications_and_open_problems": ("corollary", "remark", "application", "open problem", "future", "conclusion", "discussion"),
    "mechanism_or_intervention": ("mechanism", "intervention", "treatment", "pathway", "therapy", "gene", "protein", "cell"),
    "study_design_and_evidence_level": ("study design", "randomized", "cohort", "case-control", "trial", "sample", "patients", "control group"),
    "measurement_and_mechanism": ("measurement", "assay", "biomarker", "endpoint", "expression", "dose", "observed"),
    "results_and_evidence_strength": ("result", "significant", "confidence", "survival", "response", "effect size", "evidence"),
    "limitations_and_safety": ("limitation", "adverse", "safety", "bias", "confound", "risk", "future"),
    "explanation_or_hypothesis": ("hypothesis", "explain", "theory", "mechanism", "introduction", "motivation"),
    "data_and_identification": ("data", "dataset", "identification", "instrument", "panel", "survey", "sample"),
    "causal_evidence_and_robustness": ("causal", "robustness", "regression", "estimate", "counterfactual", "placebo"),
    "implications": ("implication", "policy", "welfare", "effect", "conclusion"),
    "threats_to_validity": ("threat", "validity", "limitation", "bias", "confound", "endogeneity"),
    "question_and_context": ("question", "context", "background", "tradition", "problem", "debate"),
    "concept_definitions": ("concept", "definition", "meaning", "term", "distinction", "category"),
    "argument_structure": ("argument", "claim", "premise", "therefore", "because", "reason"),
    "evidence_and_interpretation": ("evidence", "interpretation", "text", "case", "example", "reading"),
    "objections_and_stakes": ("objection", "reply", "critique", "tension", "stakes", "implication"),
    "practical_problem": ("problem", "public", "practical", "policy", "need", "challenge"),
    "rules_and_institutions": ("rule", "law", "statute", "court", "institution", "regulation", "doctrine"),
    "interests_and_tradeoffs": ("interest", "stakeholder", "trade-off", "tradeoff", "benefit", "cost", "rights"),
    "consequences_and_enforcement": ("consequence", "enforcement", "compliance", "implementation", "effect"),
    "risks_and_open_issues": ("risk", "limitation", "uncertainty", "open issue", "challenge", "future"),
}
COMMON_SECTION_HEADINGS = {
    "abstract",
    "introduction",
    "background",
    "related work",
    "method",
    "methods",
    "approach",
    "model",
    "experiments",
    "experiment",
    "results",
    "discussion",
    "conclusion",
    "conclusions",
    "limitations",
    "appendix",
}
TERMINAL_SECTION_HEADINGS = {
    "references",
    "bibliography",
}
ARXIV_URL_PATTERN = re.compile(
    r"^https?://(?:www\.)?arxiv\.org/(?P<kind>abs|pdf)/(?P<id>\d{4}\.\d{4,5}(?:v\d+)?)(?:\.pdf)?/?$",
    re.IGNORECASE,
)
NUMBERED_HEADING_PATTERN = re.compile(r"^(?P<num>\d+(?:\.\d+)*)\s*[.)]?\s+(?P<title>.+)$")
ROMAN_HEADING_PATTERN = re.compile(r"^(?P<num>[ivxlcdm]+)\.?\s+(?P<title>.+)$", re.IGNORECASE)
CHUNK_SPLIT_SENTENCE_PATTERN = re.compile(r"(?<=[。！？!?】【。.])\s+")
CORE_QUESTION_KEYWORDS = (
    "abstract",
    "introduction",
    "background",
    "motivation",
    "problem",
    "overview",
    "preliminar",
    "related work",
)
METHOD_KEYWORDS = (
    "method",
    "approach",
    "model",
    "architecture",
    "algorithm",
    "framework",
    "training",
    "implementation",
    "inference",
    "optimization",
)
EVIDENCE_KEYWORDS = (
    "experiment",
    "evaluation",
    "result",
    "analysis",
    "ablation",
    "benchmark",
    "dataset",
    "performance",
    "case study",
)
CONCLUSION_KEYWORDS = (
    "conclusion",
    "conclusions",
    "closing",
    "final remarks",
    "summary",
)
OPEN_QUESTION_KEYWORDS = (
    "limitation",
    "limitations",
    "future work",
    "open question",
    "discussion",
    "failure",
    "risk",
    "ethic",
    "societal impact",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_paper_reader_chat_config(settings: RuntimeSettings) -> ChatConfig:
    config = settings.paper_reader_chat
    return ChatConfig(
        provider=config.provider,
        model=config.model,
        base_url=config.base_url,
        api_key=config.api_key,
    )


def _default_paper_reader_translation_config(settings: RuntimeSettings) -> ChatConfig:
    config = settings.paper_reader_translation
    return ChatConfig(
        provider=config.provider,
        model=config.model,
        base_url=config.base_url,
        api_key=config.api_key,
    )


def _normalize_title(title: str | None, fallback: str) -> str:
    normalized = normalize_whitespace(str(title or "")).strip()
    return normalized or fallback


def _count_tokens(text: str) -> int:
    if not text.strip():
        return 0
    total = 0
    ascii_run = 0
    for char in text:
        if "\u4e00" <= char <= "\u9fff":
            if ascii_run:
                total += math.ceil(ascii_run / 4)
                ascii_run = 0
            total += 1
            continue
        if char.isspace():
            ascii_run += 1
            continue
        ascii_run += 1
    if ascii_run:
        total += math.ceil(ascii_run / 4)
    return max(total, 1)


def _compute_budget(max_context_tokens: int) -> tuple[int, int, int]:
    reserved_output_tokens = max(1024, math.floor(max_context_tokens * 0.2))
    reserved_scaffold_tokens = 1200
    page_input_budget = max_context_tokens - reserved_output_tokens - reserved_scaffold_tokens
    return reserved_output_tokens, reserved_scaffold_tokens, page_input_budget


def _compute_target_page_budget(page_input_budget: int) -> int:
    return max(1, min(page_input_budget, DEFAULT_TARGET_PAGE_TOKENS))


def _compute_target_chunk_budget(page_input_budget: int) -> int:
    return max(1, min(page_input_budget, DEFAULT_TARGET_CHUNK_TOKENS))


def _normalize_answer_language(value: str | None, fallback_text: str = "") -> str:
    normalized = normalize_whitespace(str(value or "")).strip().lower()
    if normalized in {"zh", "en"}:
        return normalized
    inferred = infer_user_language(fallback_text or "")
    return "zh" if inferred == "zh" else "en"


def _normalize_reader_mode(value: str | None) -> str:
    normalized = normalize_whitespace(str(value or "")).strip().lower()
    return normalized if normalized in {"guided", "standard"} else "guided"


def _normalize_discipline_request(value: str | None) -> str:
    normalized = normalize_whitespace(str(value or "")).strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in DISCIPLINES or normalized == "auto":
        return normalized
    return "auto"


def _normalize_discipline(value: str | None) -> str:
    normalized = _normalize_discipline_request(value)
    return normalized if normalized in DISCIPLINES else "general"


def _reading_focus_order_for_discipline(discipline: str | None) -> tuple[tuple[str, str], ...]:
    return DISCIPLINE_READING_FOCUS_ORDERS.get(_normalize_discipline(discipline), READING_FOCUS_ORDER)


def _discipline_display_name(discipline: str | None) -> str:
    return DISCIPLINE_DISPLAY_NAMES.get(_normalize_discipline(discipline), DISCIPLINE_DISPLAY_NAMES["general"])


def _discipline_prompt_guidance(discipline: str | None) -> str:
    return DISCIPLINE_PROMPT_GUIDANCE.get(_normalize_discipline(discipline), DISCIPLINE_PROMPT_GUIDANCE["general"])


def _discipline_guide_title(discipline: str | None, answer_language: str) -> str:
    normalized = _normalize_discipline(discipline)
    if answer_language == "zh":
        return {
            "general": "通用论文讲解",
            "science_engineering": "科学/工程论文讲解",
            "mathematics": "数学证明讲解",
            "medicine_biology": "医学/生物论文讲解",
            "economics_social_science": "经济/社会科学论文讲解",
            "philosophy_humanities": "哲学/人文论文讲解",
            "policy_law": "政策/法律论文讲解",
        }.get(normalized, "通用论文讲解")
    return f"{_discipline_display_name(normalized)} reading guide"


def _score_keyword_hits(text: str, keywords: tuple[str, ...]) -> int:
    lowered = text.casefold()
    return sum(1 for keyword in keywords if keyword.casefold() in lowered)


def _discipline_from_primary_category(primary_category: str | None) -> str | None:
    normalized = normalize_whitespace(primary_category or "").casefold()
    if not normalized:
        return None
    for discipline, prefixes in DISCIPLINE_CATEGORY_PREFIXES.items():
        if any(normalized.startswith(prefix) for prefix in prefixes):
            return discipline
    return None


def _resolve_discipline(
    requested: str | None,
    *,
    primary_category: str | None,
    title: str,
    abstract: str,
    chunks: list["PaperReaderChunk"],
) -> tuple[str, str]:
    normalized_request = _normalize_discipline_request(requested)
    if normalized_request in DISCIPLINES:
        return normalized_request, "manual"

    category_match = _discipline_from_primary_category(primary_category)
    if category_match is not None:
        return category_match, "auto"

    chunk_text = " ".join(
        " ".join(part for part in (chunk.section_title, chunk.subsection_title or "", chunk.text[:900]) if part)
        for chunk in chunks[:8]
    )
    evidence_text = " ".join(part for part in (title, abstract, chunk_text) if normalize_whitespace(part))
    scores = {
        discipline: _score_keyword_hits(evidence_text, keywords)
        for discipline, keywords in DISCIPLINE_DETECTION_KEYWORDS.items()
    }
    best_discipline, best_score = max(scores.items(), key=lambda item: item[1])
    if best_score >= 2:
        return best_discipline, "auto"
    return "general", "auto"


def _reader_explanation_label(answer_language: str) -> str:
    return "中文解读" if answer_language == "zh" else "Explanation (EN)"


def _reader_explanation_language(answer_language: str) -> str:
    return "Simplified Chinese" if answer_language == "zh" else "English"


def _clip_original_excerpt(text: str, max_length: int = 220) -> str:
    normalized = normalize_whitespace(text)
    if not normalized:
        return ""
    if len(normalized) <= max_length:
        return normalized
    return normalized[:max_length].rstrip() + "..."


def _normalize_multiline_text(text: str | None) -> str:
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [normalize_whitespace(line) for line in raw.split("\n")]
    normalized_lines = [line for line in lines if line]
    return "\n".join(normalized_lines).strip()


def _contains_any_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.casefold()
    return any(keyword in lowered for keyword in keywords)


def _reading_focus_title(focus_key: str) -> str:
    for focus_order in DISCIPLINE_READING_FOCUS_ORDERS.values():
        for key, title in focus_order:
            if key == focus_key:
                return title
    return "Evidence or experiments"


def _story_stage_for_focus(focus_key: str, answer_language: str) -> PaperReaderStoryStageModel:
    zh_map = {
        "quick_story": ("quick_story", "5 分钟速读", "先用一条短线索了解论文讲了什么，再决定是否继续精读。"),
        "core_question": ("problem_enters", "问题出场", "弄清论文到底想解决什么问题，以及为什么这个问题值得做。"),
        "method_or_mechanism": ("method_enters", "方法登场", "把作者的方法拆成输入、关键机制和输出。"),
        "evidence_or_experiments": ("evidence_checks", "证据验证", "看实验、指标和对比是否真的支持作者的主张。"),
        "conclusion": ("takeaway_closes", "结论收束", "提炼这篇论文真正留下来的结论。"),
        "open_questions_or_limitations": ("limits_open", "局限追问", "识别还没解决的问题、风险和后续研究空间。"),
    }
    en_map = {
        "quick_story": ("quick_story", "5-minute quick story", "Use a short storyline to decide whether to continue deep reading."),
        "core_question": ("problem_enters", "Problem enters", "Understand what problem the paper tackles and why it matters."),
        "method_or_mechanism": ("method_enters", "Method enters", "Turn the method into inputs, mechanisms, and outputs."),
        "evidence_or_experiments": ("evidence_checks", "Evidence checks", "Inspect whether experiments and metrics support the claim."),
        "conclusion": ("takeaway_closes", "Takeaway closes", "Extract the conclusion the paper actually earns."),
        "open_questions_or_limitations": ("limits_open", "Limits open", "Find remaining risks, caveats, and next research questions."),
    }
    key, title, description = (zh_map if answer_language == "zh" else en_map).get(
        focus_key,
        ("reading_stage", _reading_focus_title(focus_key), None),
    )
    return PaperReaderStoryStageModel(key=key, title=title, description=description)


def _default_reading_hints(plan: PaperReaderPagePlan, answer_language: str) -> list[PaperReaderReadingHintModel]:
    if answer_language == "zh":
        labels = {
            "must_know": ("先抓住本页主张。", "这是继续读后面页面的最低理解成本。"),
            "skim": ("细节公式和实现参数可以先略读。", "新手第一遍先理解逻辑链，不必卡在每个符号上。"),
            "advanced": ("进阶时再检查假设、消融和失败案例。", "这些信息适合第二遍用来判断论文可靠性。"),
        }
    else:
        labels = {
            "must_know": ("Capture the page's main claim first.", "This is the minimum context needed for the next page."),
            "skim": ("Skim formulas and implementation constants on the first pass.", "Beginners should first understand the logic chain."),
            "advanced": ("Return later for assumptions, ablations, and failure cases.", "These details help judge reliability on a second pass."),
        }
    return [
        PaperReaderReadingHintModel(kind=kind, text=text, reason=reason)
        for kind, (text, reason) in labels.items()
    ]


def _default_checkpoints(
    plan: PaperReaderPagePlan,
    answer_language: str,
    overview: PaperReaderStructuredTextModel | None,
) -> list[PaperReaderCheckpointModel]:
    answer = overview.explanation if overview is not None and overview.explanation else (
        overview.display_text if overview is not None and overview.display_text else plan.focus_title
    )
    if answer_language == "zh":
        return [
            PaperReaderCheckpointModel(
                question=f"读完这一页后，你能用一句话说出“{plan.focus_title}”讲了什么吗？",
                answer=answer,
                review_hint="回看本页导读和第一张 insight card。",
                source_page_index=plan.page_index,
            )
        ]
    return [
        PaperReaderCheckpointModel(
            question=f"After this page, can you state what '{plan.focus_title}' is about in one sentence?",
            answer=answer,
            review_hint="Review the page overview and the first insight card.",
            source_page_index=plan.page_index,
        )
    ]


def _fallback_section_titles_for_plan(plan: PaperReaderPagePlan) -> tuple[str, str]:
    if plan.focus_key == "quick_story":
        return plan.focus_title, "Fast orientation"
    if plan.focus_key == "open_questions_or_limitations":
        return plan.focus_title, "Questions or caveats"
    if plan.focus_key == "conclusion":
        return plan.focus_title, "Takeaways"
    return plan.focus_title, "Supporting details"


def _format_reader_block_text(original_excerpt: str, explanation_text: str, answer_language: str) -> str:
    explanation_label = _reader_explanation_label(answer_language)
    original_line = f"Original (EN): {_clip_original_excerpt(original_excerpt) or '(missing)'}"
    explanation_line = f"{explanation_label}: {normalize_whitespace(explanation_text) or '(missing)'}"
    return f"{original_line}\n{explanation_line}"


def _format_reader_inline_item(original_excerpt: str, explanation_text: str, answer_language: str) -> str:
    explanation_label = _reader_explanation_label(answer_language)
    return (
        f"Original (EN): {_clip_original_excerpt(original_excerpt) or '(missing)'}"
        f" | {explanation_label}: {normalize_whitespace(explanation_text) or '(missing)'}"
    )


def _ensure_reader_block_text(text: str | None, answer_language: str, fallback_original: str) -> str | None:
    normalized = _normalize_multiline_text(text)
    if not normalized:
        return None
    explanation_label = _reader_explanation_label(answer_language)
    if "Original (EN):" in normalized and explanation_label in normalized:
        return normalized
    return _format_reader_block_text(fallback_original, normalized, answer_language)


def _ensure_reader_inline_item(text: str | None, answer_language: str, fallback_original: str) -> str | None:
    normalized = normalize_whitespace(text or "")
    if not normalized:
        return None
    explanation_label = _reader_explanation_label(answer_language)
    if "Original (EN):" in normalized and explanation_label in normalized:
        return normalized
    return _format_reader_inline_item(fallback_original, normalized, answer_language)


def _parse_reader_block_parts(text: str | None, answer_language: str) -> tuple[str | None, str | None]:
    normalized = _normalize_multiline_text(text)
    if not normalized:
        return None, None
    explanation_label = _reader_explanation_label(answer_language)
    original: str | None = None
    explanation_lines: list[str] = []
    capture_explanation = False
    for raw_line in normalized.split("\n"):
        line = raw_line.strip()
        if line.startswith("Original (EN):"):
            original = normalize_whitespace(line.partition(":")[2])
            capture_explanation = False
            continue
        if line.startswith(f"{explanation_label}:"):
            explanation_lines = [normalize_whitespace(line.partition(":")[2])]
            capture_explanation = True
            continue
        if capture_explanation:
            extra = normalize_whitespace(line)
            if extra:
                explanation_lines.append(extra)
    explanation = "\n".join(line for line in explanation_lines if line).strip() or None
    return original or None, explanation


def _parse_reader_inline_parts(text: str | None, answer_language: str) -> tuple[str | None, str | None]:
    normalized = normalize_whitespace(text or "")
    if not normalized:
        return None, None
    explanation_label = _reader_explanation_label(answer_language)
    original: str | None = None
    explanation: str | None = None
    for part in (item.strip() for item in normalized.split("|")):
        if part.startswith("Original (EN):"):
            original = normalize_whitespace(part.partition(":")[2]) or None
        elif part.startswith(f"{explanation_label}:"):
            explanation = normalize_whitespace(part.partition(":")[2]) or None
    return original, explanation


def _build_structured_text(
    *,
    original_en: str | None,
    explanation: str | None,
    answer_language: str,
    inline: bool = False,
) -> PaperReaderStructuredTextModel | None:
    normalized_original = normalize_whitespace(original_en or "")
    normalized_explanation = _normalize_multiline_text(explanation) if not inline else normalize_whitespace(explanation or "")
    if not normalized_original and not normalized_explanation:
        return None
    display_text = (
        _format_reader_inline_item(normalized_original, normalized_explanation, answer_language)
        if inline
        else _format_reader_block_text(normalized_original, normalized_explanation, answer_language)
    )
    return PaperReaderStructuredTextModel(
        original_en=normalized_original or None,
        explanation=normalized_explanation or None,
        display_text=display_text,
    )


def _coerce_structured_block(
    value: Any,
    answer_language: str,
    fallback_original: str,
) -> PaperReaderStructuredTextModel | None:
    if value is None:
        return None
    original: str | None = None
    explanation: str | None = None
    display_text: str | None = None
    if isinstance(value, dict):
        original = normalize_whitespace(
            value.get("original_en")
            or value.get("original")
            or value.get("quote")
            or value.get("source_text")
            or ""
        ) or None
        display_candidates = (
            value.get("display_text"),
            value.get("displayText"),
            value.get("formatted_text"),
            value.get("formattedText"),
        )
        for candidate in display_candidates:
            display_text = _normalize_multiline_text(candidate)
            if display_text:
                break
        explanation_candidates = (
            value.get("explanation"),
            value.get("interpretation"),
            value.get("analysis"),
            value.get("note"),
        )
        for candidate in explanation_candidates:
            explanation = _normalize_multiline_text(candidate)
            if explanation:
                break
        if not explanation:
            freeform = _normalize_multiline_text(value.get("text") or value.get("body") or value.get("content") or value.get("summary"))
            if freeform:
                if "Original (EN):" in freeform:
                    display_text = display_text or freeform
                else:
                    explanation = freeform
    else:
        display_text = _normalize_multiline_text(value)

    if display_text and (not original or not explanation):
        parsed_original, parsed_explanation = _parse_reader_block_parts(display_text, answer_language)
        original = original or parsed_original
        explanation = explanation or parsed_explanation
    if not explanation and display_text and "Original (EN):" not in display_text:
        explanation = display_text
    if not original:
        original = fallback_original
    return _build_structured_text(
        original_en=original,
        explanation=explanation,
        answer_language=answer_language,
    )


def _coerce_structured_inline(
    value: Any,
    answer_language: str,
    fallback_original: str,
) -> PaperReaderStructuredTextModel | None:
    if value is None:
        return None
    original: str | None = None
    explanation: str | None = None
    display_text: str | None = None
    if isinstance(value, dict):
        original = normalize_whitespace(
            value.get("original_en")
            or value.get("original")
            or value.get("quote")
            or value.get("source_text")
            or ""
        ) or None
        display_candidates = (
            value.get("display_text"),
            value.get("displayText"),
            value.get("formatted_text"),
            value.get("formattedText"),
        )
        for candidate in display_candidates:
            display_text = normalize_whitespace(candidate or "")
            if display_text:
                break
        explanation_candidates = (
            value.get("explanation"),
            value.get("interpretation"),
            value.get("analysis"),
            value.get("note"),
            value.get("text"),
            value.get("body"),
            value.get("content"),
            value.get("summary"),
        )
        for candidate in explanation_candidates:
            explanation = normalize_whitespace(candidate or "")
            if explanation:
                break
    else:
        display_text = normalize_whitespace(value or "")

    if display_text and (not original or not explanation):
        parsed_original, parsed_explanation = _parse_reader_inline_parts(display_text, answer_language)
        original = original or parsed_original
        explanation = explanation or parsed_explanation
    if not explanation and display_text and "Original (EN):" not in display_text:
        explanation = display_text
    if not original:
        original = fallback_original
    return _build_structured_text(
        original_en=original,
        explanation=explanation,
        answer_language=answer_language,
        inline=True,
    )


def _structured_text_exact_key(value: PaperReaderStructuredTextModel | None) -> str:
    if value is None:
        return ""
    return normalize_whitespace(value.display_text or value.explanation or value.original_en or "").casefold()


def _structured_text_exact_keys(value: PaperReaderStructuredTextModel | None) -> set[str]:
    if value is None:
        return set()
    return {
        key
        for key in (
            normalize_whitespace(value.display_text or "").casefold(),
            normalize_whitespace(value.explanation or "").casefold(),
            normalize_whitespace(value.original_en or "").casefold(),
        )
        if key
    }


def _coerce_why_it_matters_blocks(
    item: dict[str, Any],
    answer_language: str,
    fallback_original: str,
    summary_block: PaperReaderStructuredTextModel | None,
    evidence_blocks: list[PaperReaderStructuredTextModel],
) -> list[PaperReaderStructuredTextModel]:
    raw_value = None
    for key in (
        "why_it_matters",
        "whyItMatters",
        "significance",
        "importance",
        "takeaway",
        "takeaways",
        "relevance",
    ):
        candidate = item.get(key)
        if candidate is not None:
            raw_value = candidate
            break
    duplicate_keys = set()
    duplicate_keys.update(_structured_text_exact_keys(summary_block))
    for block in evidence_blocks:
        duplicate_keys.update(_structured_text_exact_keys(block))
    blocks: list[PaperReaderStructuredTextModel] = []
    seen: set[str] = set()
    candidates = raw_value if isinstance(raw_value, list) else [raw_value] if raw_value is not None else []
    for candidate in candidates[:2]:
        block = _coerce_structured_inline(candidate, answer_language, fallback_original)
        key = _structured_text_exact_key(block)
        block_keys = _structured_text_exact_keys(block)
        if not block or not key or block_keys.intersection(duplicate_keys) or key in seen:
            continue
        seen.add(key)
        blocks.append(block)
    return blocks


def _strip_code_fence(text: str) -> str:
    normalized = str(text or "").strip()
    if "```" not in normalized:
        return normalized
    fenced = re.search(r"```(?:json)?\s*(.*?)```", normalized, re.IGNORECASE | re.DOTALL)
    if fenced is not None:
        return fenced.group(1).strip()
    return normalized.replace("```", "").strip()


def _parse_json_object(raw_text: str) -> dict[str, Any] | None:
    with suppress(Exception):
        parsed = extract_first_json_object(raw_text)
        if isinstance(parsed, dict):
            return parsed
    with suppress(Exception):
        parsed = json.loads(raw_text)
        if isinstance(parsed, dict):
            return parsed
    return None


def _repair_json_object(raw_text: str) -> dict[str, Any] | None:
    candidate = _strip_code_fence(raw_text).strip()
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start >= 0 and end > start:
        candidate = candidate[start : end + 1]
    candidate = candidate.translate(
        str.maketrans(
            {
                "“": '"',
                "”": '"',
                "‘": "'",
                "’": "'",
            }
        )
    )
    candidate = re.sub(r",(\s*[}\]])", r"\1", candidate)
    repaired = _parse_json_object(candidate)
    if repaired is not None:
        return repaired
    with suppress(Exception):
        literal = ast.literal_eval(candidate)
        if isinstance(literal, dict):
            reparsed = json.loads(json.dumps(literal, ensure_ascii=False))
            if isinstance(reparsed, dict):
                return reparsed
    return None


def _extract_structured_json_object(raw_text: str) -> tuple[dict[str, Any] | None, bool]:
    direct = _parse_json_object(raw_text)
    if direct is not None:
        return direct, False
    if not str(raw_text or "").strip():
        return None, False
    repaired = _repair_json_object(raw_text)
    if repaired is not None:
        return repaired, True
    return None, True


def _split_sentences(text: str) -> list[str]:
    normalized = normalize_whitespace(text)
    if not normalized:
        return []
    parts = [part.strip() for part in CHUNK_SPLIT_SENTENCE_PATTERN.split(normalized) if part.strip()]
    return parts or [normalized]


def _split_long_text(text: str, budget: int) -> list[str]:
    sentences = _split_sentences(text)
    if not sentences:
        return []

    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for sentence in sentences:
        sentence_tokens = _count_tokens(sentence)
        if sentence_tokens > budget:
            if current:
                chunks.append(" ".join(current).strip())
                current = []
                current_tokens = 0
            window_chars = max(512, budget * 4)
            for start in range(0, len(sentence), window_chars):
                piece = sentence[start : start + window_chars].strip()
                if piece:
                    chunks.append(piece)
            continue
        if current and current_tokens + sentence_tokens > budget:
            chunks.append(" ".join(current).strip())
            current = [sentence]
            current_tokens = sentence_tokens
            continue
        current.append(sentence)
        current_tokens += sentence_tokens
    if current:
        chunks.append(" ".join(current).strip())
    return [chunk for chunk in chunks if chunk.strip()]


def _heading_from_line(line: str, has_section: bool) -> tuple[int, str] | None:
    normalized = normalize_whitespace(line)
    if not normalized or len(normalized) > 160:
        return None
    lowered = normalized.casefold().strip(":")
    if lowered in TERMINAL_SECTION_HEADINGS:
        return 1, normalized
    if lowered in COMMON_SECTION_HEADINGS:
        return 1, normalized

    numbered = NUMBERED_HEADING_PATTERN.match(normalized)
    if numbered is not None:
        depth = numbered.group("num").count(".") + 1
        title = normalize_whitespace(numbered.group("title"))
        return max(1, min(depth, 3)), title

    roman = ROMAN_HEADING_PATTERN.match(normalized)
    if roman is not None and len(normalized.split()) <= 12:
        return 1, normalize_whitespace(roman.group("title"))

    words = normalized.split()
    if len(words) <= 12 and normalized[-1] not in ".:;,":
        alpha_words = [word for word in words if any(ch.isalpha() for ch in word)]
        if alpha_words and sum(word[0].isupper() for word in alpha_words) >= max(1, len(alpha_words) - 1):
            if has_section or len(words) <= 8:
                return 1, normalized
    return None


def _extract_pdf_pages(pdf_path: Path) -> list[tuple[int, str]]:
    reader = PdfReader(str(pdf_path))
    pages: list[tuple[int, str]] = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        pages.append((index, text))
    return pages


def _pdf_font_weight(font_name: str) -> str:
    normalized = normalize_whitespace(font_name).casefold()
    if any(marker in normalized for marker in ("bold", "medi", "demi", "black")):
        return "700"
    return "400"


def _pdf_font_style(font_name: str) -> str:
    normalized = normalize_whitespace(font_name).casefold()
    if any(marker in normalized for marker in ("italic", "oblique", "ital", "cmmi")):
        return "italic"
    return "normal"


def _extract_pdf_source_page_layout(page: Any, page_number: int) -> PaperReaderSourcePageModel:
    width = float(getattr(page.mediabox, "width", 0) or 0)
    height = float(getattr(page.mediabox, "height", 0) or 0)
    spans: list[PaperReaderSourceTextSpanModel] = []

    def visitor_text(text: Any, _cm: Any, tm: Any, font_dict: Any, font_size: Any) -> None:
        raw_text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
        if not normalize_whitespace(raw_text):
            return
        font_name = str((font_dict or {}).get("/BaseFont") or "")
        try:
            x = float(tm[4])
            baseline_y = float(tm[5])
            resolved_font_size = float(font_size)
        except Exception:
            return
        y = max(0.0, height - baseline_y) if height else max(0.0, baseline_y)
        line_height = max(resolved_font_size * 1.15, resolved_font_size)
        for offset, line in enumerate(raw_text.split("\n")):
            normalized_line = normalize_whitespace(line)
            if not normalized_line:
                continue
            spans.append(
                PaperReaderSourceTextSpanModel(
                    text=normalized_line,
                    x=max(0.0, x),
                    y=max(0.0, y + offset * line_height),
                    font_size=max(1.0, resolved_font_size),
                    font_weight=_pdf_font_weight(font_name),
                    font_style=_pdf_font_style(font_name),
                )
            )

    plain_text = ""
    try:
        plain_text = page.extract_text(visitor_text=visitor_text) or ""
    except Exception:
        plain_text = ""
    if not plain_text:
        with suppress(Exception):
            plain_text = page.extract_text(extraction_mode="layout") or ""

    return PaperReaderSourcePageModel(
        page_number=page_number,
        text=_normalize_multiline_text(plain_text),
        width=width or None,
        height=height or None,
        spans=spans,
    )


def _parse_arxiv_url(url: str) -> str:
    normalized = normalize_whitespace(url)
    match = ARXIV_URL_PATTERN.match(normalized)
    if match is None:
        raise ValueError("Only arxiv.org/abs or arxiv.org/pdf URLs are supported.")
    arxiv_id = match.group("id")
    base_id = extract_arxiv_base_id(arxiv_id) or arxiv_id
    return base_id


def _download_arxiv_pdf(arxiv_id: str, session_dir: Path, timeout: int) -> Path:
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    response = requests.get(
        pdf_url,
        timeout=timeout,
        headers={"User-Agent": "arxiv-paper-rag/1.0"},
    )
    response.raise_for_status()
    pdf_path = session_dir / f"{arxiv_id.replace('/', '_')}.pdf"
    pdf_path.write_bytes(response.content)
    return pdf_path


def _section_label(section_title: str | None, subsection_title: str | None) -> str:
    section = normalize_whitespace(section_title or "Untitled")
    if subsection_title:
        subsection = normalize_whitespace(subsection_title)
        return f"{section} - {subsection}"
    return section


@dataclass(slots=True)
class PaperReaderChunk:
    chunk_id: str
    text: str
    section_title: str
    subsection_title: str | None
    reading_focus_key: str
    reading_focus_title: str
    page_start: int
    page_end: int
    token_estimate: int
    embedding: list[float] | None = None


@dataclass(slots=True)
class PaperReaderPagePlan:
    page_index: int
    title: str
    focus_key: str
    focus_title: str
    section_title: str
    subsection_title: str | None
    source_section_titles: list[str] = field(default_factory=list)
    chunk_ids: list[str] = field(default_factory=list)
    source_node_ids: list[str] = field(default_factory=list)
    page_start: int = 0
    page_end: int = 0
    estimated_tokens: int = 0


@dataclass(slots=True)
class PaperReaderIndexNode:
    node_id: str
    title: str
    summary: str | None = None
    reading_focus_key: str | None = None
    page_start: int = 0
    page_end: int = 0
    page_indices: list[int] = field(default_factory=list)
    chunk_ids: list[str] = field(default_factory=list)
    children: list["PaperReaderIndexNode"] = field(default_factory=list)


@dataclass(slots=True)
class PaperReaderPageContent:
    page_index: int
    title: str
    status: str = "queued"
    coverage: str | None = None
    page_overview: PaperReaderStructuredTextModel | None = None
    insights: list[PaperReaderInsightModel] = field(default_factory=list)
    structured_status: PaperReaderStructuredStatusModel = field(default_factory=PaperReaderStructuredStatusModel)
    reading_blocks: list[PaperReaderReadingBlockModel] = field(default_factory=list)
    source_sections: list[PaperReaderSourceSectionModel] = field(default_factory=list)
    mentor_script: list[PaperReaderStructuredTextModel] = field(default_factory=list)
    blackboard_notes: PaperReaderBlackboardNotesModel | None = None
    discipline_guide: PaperReaderDisciplineGuideModel | None = None
    story_stage: PaperReaderStoryStageModel | None = None
    glossary_terms: list[PaperReaderGlossaryTermModel] = field(default_factory=list)
    reading_hints: list[PaperReaderReadingHintModel] = field(default_factory=list)
    checkpoints: list[PaperReaderCheckpointModel] = field(default_factory=list)
    summary: str | None = None
    sections: list[PaperReaderSectionModel] = field(default_factory=list)
    key_points: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    citations: list[PaperReaderCitationModel] = field(default_factory=list)
    chunk_ids: list[str] = field(default_factory=list)
    source_node_ids: list[str] = field(default_factory=list)
    estimated_tokens: int = 0
    page_start: int = 0
    page_end: int = 0
    generated_at: str | None = None
    error_message: str | None = None


@dataclass(slots=True)
class PaperReaderSession:
    session_id: str
    source_type: str
    source_url: str | None
    source_id: str | None
    paper_title: str
    authors: list[str]
    published_date: str | None
    answer_language: str
    reader_mode: str
    discipline: str
    discipline_source: str
    pdf_path: Path
    max_context_tokens: int
    reserved_output_tokens: int
    reserved_scaffold_tokens: int
    page_input_budget: int
    settings: RuntimeSettings
    current_page_index: int = 0
    session_status: str = "active"
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    chunks: list[PaperReaderChunk] = field(default_factory=list)
    pages: list[PaperReaderPagePlan] = field(default_factory=list)
    source_pages: list[tuple[int, str]] = field(default_factory=list)
    source_page_layouts: dict[int, PaperReaderSourcePageModel] = field(default_factory=dict)
    source_page_pdf_paths: dict[int, Path] = field(default_factory=dict)
    index_tree: PaperReaderIndexNode | None = None
    index_status: str = "fallback"
    page_contents: dict[int, PaperReaderPageContent] = field(default_factory=dict)
    page_statuses: dict[int, str] = field(default_factory=dict)


_SESSION_LOCK = threading.RLock()
_SESSION_CACHE: dict[str, PaperReaderSession] = {}
_PAGE_TASKS: dict[tuple[str, int], Future[Any]] = {}
_PAGE_EXECUTOR = ThreadPoolExecutor(max_workers=max(2, (threading.active_count() or 2)))


def _get_session(session_id: str) -> PaperReaderSession:
    session = _SESSION_CACHE.get(session_id)
    if session is None:
        raise KeyError("Paper reader session not found.")
    return session


def _touch_session(session: PaperReaderSession) -> None:
    session.updated_at = _now_iso()


def _session_title_from_pdf(pdf_path: Path, fallback: str) -> str:
    try:
        reader = PdfReader(str(pdf_path))
        metadata = reader.metadata
        title = getattr(metadata, "title", None) if metadata is not None else None
        return _normalize_title(title, fallback)
    except Exception:
        return fallback


def _build_blocks(pages: list[tuple[int, str]]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    current_section = "Abstract"
    current_subsection: str | None = None
    seen_section = False
    stop_after_references = False

    for page_number, page_text in pages:
        if stop_after_references:
            break

        lines = page_text.splitlines()
        paragraph_lines: list[str] = []

        def flush_paragraph() -> None:
            nonlocal paragraph_lines
            if not paragraph_lines:
                return
            paragraph_text = normalize_whitespace(" ".join(paragraph_lines))
            paragraph_lines = []
            if not paragraph_text:
                return
            block = {
                "text": paragraph_text,
                "section_title": current_section,
                "subsection_title": current_subsection,
                "page_start": page_number,
                "page_end": page_number,
            }
            blocks.append(block)

        for line in lines:
            stripped = line.strip()
            if not stripped:
                flush_paragraph()
                continue

            heading = _heading_from_line(stripped, seen_section)
            if heading is not None:
                flush_paragraph()
                level, heading_text = heading
                seen_section = True
                if heading_text.casefold() in TERMINAL_SECTION_HEADINGS:
                    stop_after_references = True
                    break
                if level <= 1:
                    current_section = _normalize_title(heading_text, current_section)
                    current_subsection = None
                else:
                    current_subsection = _normalize_title(heading_text, current_subsection or heading_text)
                continue

            paragraph_lines.append(stripped)

        flush_paragraph()

    return blocks


def _chunk_blocks(blocks: list[dict[str, Any]], budget: int) -> list[PaperReaderChunk]:
    chunks: list[PaperReaderChunk] = []
    for block in blocks:
        text = normalize_whitespace(block["text"])
        if not text:
            continue
        pieces = [text] if _count_tokens(text) <= budget else _split_long_text(text, budget)
        for piece in pieces:
            token_estimate = _count_tokens(piece)
            focus_key = "evidence_or_experiments"
            focus_title = _reading_focus_title(focus_key)
            chunks.append(
                PaperReaderChunk(
                    chunk_id=uuid.uuid4().hex,
                    text=piece,
                    section_title=block["section_title"],
                    subsection_title=block["subsection_title"],
                    reading_focus_key=focus_key,
                    reading_focus_title=focus_title,
                    page_start=int(block["page_start"]),
                    page_end=int(block["page_end"]),
                    token_estimate=token_estimate,
                )
            )
    return chunks


def _classify_reading_focus(
    chunk: PaperReaderChunk,
    index: int,
    total_chunks: int,
    discipline: str,
) -> tuple[str, str]:
    heading_text = " ".join(
        part for part in (chunk.section_title, chunk.subsection_title or "") if normalize_whitespace(part)
    ).casefold()
    content_text = normalize_whitespace(chunk.text).casefold()[:1200]
    position_ratio = (index + 1) / max(total_chunks, 1)
    route = [item for item in _reading_focus_order_for_discipline(discipline) if item[0] != "quick_story"]
    if not route:
        route = [item for item in READING_FOCUS_ORDER if item[0] != "quick_story"]

    scored: list[tuple[int, int, str, str]] = []
    for order_index, (focus_key, focus_title) in enumerate(route):
        keywords = FOCUS_KEYWORDS.get(focus_key, ())
        heading_score = _score_keyword_hits(heading_text, keywords) * 3
        content_score = _score_keyword_hits(content_text, keywords)
        scored.append((heading_score + content_score, -order_index, focus_key, focus_title))
    best_score, _negative_index, best_key, best_title = max(scored, key=lambda item: item[:2])
    if best_score > 0:
        return best_key, best_title

    fallback_index = min(len(route) - 1, max(0, int(position_ratio * len(route))))
    if position_ratio <= 0.22:
        fallback_index = 0
    elif position_ratio >= 0.88:
        fallback_index = len(route) - 1
    focus_key, focus_title = route[fallback_index]
    return focus_key, focus_title


def _assign_reading_focuses(chunks: list[PaperReaderChunk], discipline: str) -> list[PaperReaderChunk]:
    total_chunks = len(chunks)
    for index, chunk in enumerate(chunks):
        focus_key, focus_title = _classify_reading_focus(chunk, index, total_chunks, discipline)
        chunk.reading_focus_key = focus_key
        chunk.reading_focus_title = focus_title
    return chunks


def _make_page_title(title: str, page_count: int, index: int) -> str:
    if page_count <= 1:
        return title
    return f"{title} ({index + 1}/{page_count})"


def _pack_chunks_into_pages(chunks: list[PaperReaderChunk], budget: int, discipline: str = "general") -> list[PaperReaderPagePlan]:
    pages: list[PaperReaderPagePlan] = []
    focus_order = _reading_focus_order_for_discipline(discipline)
    focus_buckets: dict[str, list[PaperReaderChunk]] = {key: [] for key, _ in focus_order}
    for chunk in chunks:
        focus_buckets.setdefault(chunk.reading_focus_key, []).append(chunk)

    for focus_key, focus_title in focus_order:
        if focus_key == "quick_story":
            continue
        focus_chunks = focus_buckets.get(focus_key) or []
        if not focus_chunks:
            continue

        current: list[PaperReaderChunk] = []
        current_tokens = 0
        current_source_section: str | None = None

        def flush_page() -> None:
            nonlocal current, current_tokens, current_source_section
            if not current:
                return
            source_section_titles = list(
                dict.fromkeys(_section_label(chunk.section_title, chunk.subsection_title) for chunk in current)
            )
            pages.append(
                PaperReaderPagePlan(
                    page_index=len(pages),
                    title=focus_title,
                    focus_key=focus_key,
                    focus_title=focus_title,
                    section_title=focus_title,
                    subsection_title=None,
                    source_section_titles=source_section_titles,
                    chunk_ids=[chunk.chunk_id for chunk in current],
                    page_start=min(chunk.page_start for chunk in current),
                    page_end=max(chunk.page_end for chunk in current),
                    estimated_tokens=current_tokens,
                )
            )
            current = []
            current_tokens = 0
            current_source_section = None

        for chunk in focus_chunks:
            semantic_boundary = (
                current
                and _section_label(chunk.section_title, chunk.subsection_title) != current_source_section
                and current_tokens >= max(1, budget // 2)
            )
            if current and (current_tokens + chunk.token_estimate > budget or semantic_boundary):
                flush_page()
            current.append(chunk)
            current_tokens += chunk.token_estimate
            current_source_section = _section_label(chunk.section_title, chunk.subsection_title)

        flush_page()

    title_groups: dict[str, list[PaperReaderPagePlan]] = {}
    for page in pages:
        title_groups.setdefault(page.focus_title, []).append(page)
    for focus_title, group in title_groups.items():
        if len(group) <= 1:
            continue
        for index, page in enumerate(group):
            page.title = _make_page_title(focus_title, len(group), index)

    for index, page in enumerate(pages):
        page.page_index = index

    return pages


def _build_quick_story_plan(
    chunks: list[PaperReaderChunk],
    budget: int,
    discipline: str = "general",
) -> PaperReaderPagePlan | None:
    selected: list[PaperReaderChunk] = []
    selected_ids: set[str] = set()
    current_tokens = 0
    for focus_key, _focus_title in _reading_focus_order_for_discipline(discipline):
        if focus_key == "quick_story":
            continue
        for chunk in chunks:
            if chunk.reading_focus_key != focus_key or chunk.chunk_id in selected_ids:
                continue
            if selected and current_tokens + chunk.token_estimate > budget:
                break
            selected.append(chunk)
            selected_ids.add(chunk.chunk_id)
            current_tokens += chunk.token_estimate
            break
    if not selected and chunks:
        selected = chunks[:1]
        current_tokens = selected[0].token_estimate
    if not selected:
        return None
    return PaperReaderPagePlan(
        page_index=0,
        title="Quick Story",
        focus_key="quick_story",
        focus_title="Quick Story",
        section_title="Quick Story",
        subsection_title=None,
        source_section_titles=list(dict.fromkeys(_section_label(chunk.section_title, chunk.subsection_title) for chunk in selected)),
        chunk_ids=[chunk.chunk_id for chunk in selected],
        page_start=min(chunk.page_start for chunk in selected),
        page_end=max(chunk.page_end for chunk in selected),
        estimated_tokens=current_tokens,
    )


def _node_id_from_parts(*parts: str | None) -> str:
    raw = "-".join(normalize_whitespace(part or "") for part in parts if normalize_whitespace(part or ""))
    slug = re.sub(r"[^a-z0-9]+", "-", raw.casefold()).strip("-")
    return slug[:80] or uuid.uuid4().hex[:12]


def _short_node_summary(chunks: list[PaperReaderChunk], max_length: int = 260) -> str | None:
    for chunk in chunks:
        text = normalize_whitespace(chunk.text)
        if not text:
            continue
        sentence = _split_sentences(text[: max_length * 2])
        summary = sentence[0] if sentence else text
        return summary[:max_length].strip()
    return None


def _extend_unique(target: list[str], values: list[str]) -> None:
    for value in values:
        if value not in target:
            target.append(value)


def _build_paper_index_tree(chunks: list[PaperReaderChunk], pages: list[PaperReaderPagePlan]) -> PaperReaderIndexNode:
    root = PaperReaderIndexNode(node_id="paper-map", title="Paper Map")
    section_nodes: dict[str, PaperReaderIndexNode] = {}
    subsection_nodes: dict[tuple[str, str], PaperReaderIndexNode] = {}
    chunk_to_node_ids: dict[str, list[str]] = {}

    for chunk in chunks:
        section_title = _normalize_title(chunk.section_title, "Untitled")
        section_key = section_title.casefold()
        section_node = section_nodes.get(section_key)
        if section_node is None:
            section_node = PaperReaderIndexNode(
                node_id=_node_id_from_parts("section", str(len(section_nodes) + 1), section_title),
                title=section_title,
                reading_focus_key=chunk.reading_focus_key,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
            )
            section_nodes[section_key] = section_node
            root.children.append(section_node)
        section_node.page_start = min(section_node.page_start or chunk.page_start, chunk.page_start)
        section_node.page_end = max(section_node.page_end or chunk.page_end, chunk.page_end)
        section_node.reading_focus_key = section_node.reading_focus_key or chunk.reading_focus_key
        if chunk.chunk_id not in section_node.chunk_ids:
            section_node.chunk_ids.append(chunk.chunk_id)

        if chunk.subsection_title:
            subsection_title = _normalize_title(chunk.subsection_title, chunk.subsection_title)
            subsection_key = (section_key, subsection_title.casefold())
            leaf_node = subsection_nodes.get(subsection_key)
            if leaf_node is None:
                leaf_node = PaperReaderIndexNode(
                    node_id=_node_id_from_parts(section_node.node_id, "sub", str(len(section_node.children) + 1), subsection_title),
                    title=subsection_title,
                    reading_focus_key=chunk.reading_focus_key,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                )
                subsection_nodes[subsection_key] = leaf_node
                section_node.children.append(leaf_node)
            leaf_node.page_start = min(leaf_node.page_start or chunk.page_start, chunk.page_start)
            leaf_node.page_end = max(leaf_node.page_end or chunk.page_end, chunk.page_end)
            leaf_node.reading_focus_key = leaf_node.reading_focus_key or chunk.reading_focus_key
            if chunk.chunk_id not in leaf_node.chunk_ids:
                leaf_node.chunk_ids.append(chunk.chunk_id)
            chunk_to_node_ids[chunk.chunk_id] = [leaf_node.node_id, section_node.node_id]
        else:
            chunk_to_node_ids[chunk.chunk_id] = [section_node.node_id]

    node_lookup = {node.node_id: node for node in _iter_index_nodes(root)}
    for node in node_lookup.values():
        if node.node_id == root.node_id:
            continue
        node.summary = _short_node_summary([chunk for chunk in chunks if chunk.chunk_id in set(node.chunk_ids)])

    for page in pages:
        source_node_ids: list[str] = []
        for chunk_id in page.chunk_ids:
            _extend_unique(source_node_ids, chunk_to_node_ids.get(chunk_id, []))
        page.source_node_ids = source_node_ids
        for node_id in source_node_ids:
            node = node_lookup.get(node_id)
            if node is not None and page.page_index not in node.page_indices:
                node.page_indices.append(page.page_index)

    if chunks:
        root.page_start = min(chunk.page_start for chunk in chunks)
        root.page_end = max(chunk.page_end for chunk in chunks)
        root.chunk_ids = [chunk.chunk_id for chunk in chunks]
        root.summary = _short_node_summary(chunks)
    root.page_indices = [page.page_index for page in pages]
    return root


def _iter_index_nodes(root: PaperReaderIndexNode | None) -> Iterator[PaperReaderIndexNode]:
    if root is None:
        return
    yield root
    for child in root.children:
        yield from _iter_index_nodes(child)


def _index_node_to_model(node: PaperReaderIndexNode) -> PaperReaderIndexNodeModel:
    return PaperReaderIndexNodeModel(
        node_id=node.node_id,
        title=node.title,
        summary=node.summary,
        reading_focus_key=node.reading_focus_key,
        page_start=node.page_start,
        page_end=node.page_end,
        page_indices=list(node.page_indices),
        chunk_ids=list(node.chunk_ids),
        children=[_index_node_to_model(child) for child in node.children],
    )


def _selected_node_to_model(node: PaperReaderIndexNode, reason: str | None = None) -> PaperReaderSelectedNodeModel:
    return PaperReaderSelectedNodeModel(
        node_id=node.node_id,
        title=node.title,
        summary=node.summary,
        page_start=node.page_start,
        page_end=node.page_end,
        page_indices=list(node.page_indices),
        reason=reason,
    )


def _index_nodes_for_chunks(
    session: PaperReaderSession,
    chunks: list[PaperReaderChunk],
    *,
    limit: int = 4,
) -> list[PaperReaderSelectedNodeModel]:
    if session.index_tree is None:
        return []
    chunk_ids = {chunk.chunk_id for chunk in chunks}
    selected: list[PaperReaderSelectedNodeModel] = []
    seen: set[str] = set()
    for node in _iter_index_nodes(session.index_tree):
        if node.node_id == "paper-map" or node.node_id in seen:
            continue
        if chunk_ids.intersection(node.chunk_ids):
            selected.append(_selected_node_to_model(node, "matched evidence chunks"))
            seen.add(node.node_id)
        if len(selected) >= limit:
            break
    return selected


def _chunks_for_plan(session: PaperReaderSession, plan: PaperReaderPagePlan) -> list[PaperReaderChunk]:
    chunk_map = {chunk.chunk_id: chunk for chunk in session.chunks}
    return [chunk_map[chunk_id] for chunk_id in plan.chunk_ids if chunk_id in chunk_map]


def _format_page_input(session: PaperReaderSession, plan: PaperReaderPagePlan) -> str:
    chunks = _chunks_for_plan(session, plan)
    parts = []
    for chunk in chunks:
        heading = _section_label(chunk.section_title, chunk.subsection_title)
        parts.append(f"[{heading} | pages {chunk.page_start}-{chunk.page_end}]\n{chunk.text}")
    return "\n\n".join(parts).strip()


def _coerce_int(value: Any, fallback: int) -> int:
    with suppress(Exception):
        return int(value)
    return fallback


def _build_source_sections(session: PaperReaderSession, plan: PaperReaderPagePlan) -> list[PaperReaderSourceSectionModel]:
    source_sections: list[PaperReaderSourceSectionModel] = []
    index_by_key: dict[tuple[str, str | None], int] = {}
    for chunk in _chunks_for_plan(session, plan):
        key = (chunk.section_title, chunk.subsection_title)
        existing_index = index_by_key.get(key)
        if existing_index is None:
            index_by_key[key] = len(source_sections)
            source_sections.append(
                PaperReaderSourceSectionModel(
                    title=chunk.section_title,
                    subsection_title=chunk.subsection_title,
                    label=_section_label(chunk.section_title, chunk.subsection_title),
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    chunk_ids=[chunk.chunk_id],
                )
            )
            continue
        existing = source_sections[existing_index]
        if chunk.chunk_id not in existing.chunk_ids:
            existing.chunk_ids.append(chunk.chunk_id)
        existing.page_start = min(existing.page_start, chunk.page_start)
        existing.page_end = max(existing.page_end, chunk.page_end)
    return source_sections


def _build_reading_blocks(
    session: PaperReaderSession,
    plan: PaperReaderPagePlan,
    raw_blocks: Any = None,
) -> list[PaperReaderReadingBlockModel]:
    raw_by_chunk_id: dict[str, dict[str, Any]] = {}
    for raw_block in raw_blocks if isinstance(raw_blocks, list) else []:
        if not isinstance(raw_block, dict):
            continue
        chunk_id = str(raw_block.get("chunk_id") or raw_block.get("chunkId") or "").strip()
        if not chunk_id:
            continue
        raw_by_chunk_id[chunk_id] = raw_block

    blocks: list[PaperReaderReadingBlockModel] = []
    for chunk in _chunks_for_plan(session, plan):
        original = normalize_whitespace(chunk.text)
        if not original:
            continue
        source_label = _section_label(chunk.section_title, chunk.subsection_title)
        raw_block = raw_by_chunk_id.get(chunk.chunk_id, {})
        raw_display_text = _normalize_multiline_text(raw_block.get("display_text") or raw_block.get("displayText"))
        _, parsed_display_explanation = _parse_reader_block_parts(raw_display_text, session.answer_language)
        explanation = _clean_reading_block_localized_text(
            raw_block.get("explanation")
            or raw_block.get("translation")
            or raw_block.get("localized_explanation")
            or raw_block.get("localizedExplanation")
            or parsed_display_explanation,
            original,
        )
        display_text = _clean_reading_block_localized_text(raw_display_text, original) or explanation
        blocks.append(
            PaperReaderReadingBlockModel(
                chunk_id=chunk.chunk_id,
                source_label=source_label,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                original_en=original,
                explanation=explanation,
                display_text=display_text,
            )
        )
    return blocks


def _same_normalized_text(left: str | None, right: str | None) -> bool:
    left_key = normalize_whitespace(left or "").casefold()
    right_key = normalize_whitespace(right or "").casefold()
    return bool(left_key and right_key and left_key == right_key)


def _clean_reading_block_localized_text(value: Any, original: str) -> str | None:
    text = _normalize_multiline_text(value)
    if not text or _same_normalized_text(text, original):
        return None
    return text


def _localized_reading_blocks(
    blocks: list[PaperReaderReadingBlockModel],
) -> list[PaperReaderReadingBlockModel]:
    localized_blocks: list[PaperReaderReadingBlockModel] = []
    for block in blocks:
        explanation = _clean_reading_block_localized_text(block.explanation, block.original_en)
        display_text = _clean_reading_block_localized_text(block.display_text, block.original_en)
        localized_text = explanation or display_text
        localized_blocks.append(
            PaperReaderReadingBlockModel(
                chunk_id=block.chunk_id,
                source_label=block.source_label,
                page_start=block.page_start,
                page_end=block.page_end,
                original_en=block.original_en,
                explanation=localized_text,
                display_text=localized_text,
            )
        )
    return localized_blocks


def _reading_block_needs_translation(block: PaperReaderReadingBlockModel) -> bool:
    if not normalize_whitespace(block.original_en):
        return False
    return not (
        _clean_reading_block_localized_text(block.explanation, block.original_en)
        or _clean_reading_block_localized_text(block.display_text, block.original_en)
    )


def _build_reading_block_translation_messages(
    blocks: list[PaperReaderReadingBlockModel],
    answer_language: str,
) -> list[dict[str, str]]:
    explanation_language = _reader_explanation_language(answer_language)
    chunks = [
        {
            "chunk_id": block.chunk_id,
            "source_label": block.source_label,
            "page_start": block.page_start,
            "page_end": block.page_end,
            "original_en": block.original_en,
        }
        for block in blocks
    ]
    prompt = (
        "You translate source cards for a paper reader.\n"
        "Return a single JSON object only with key translations.\n"
        "translations must be an array with exactly one item per supplied chunk_id, in the same order.\n"
        "Each item must include chunk_id and explanation.\n"
        f"Write every explanation in {explanation_language}.\n"
        "Translate or explain the literal supplied original_en chunk only; do not summarize the whole page.\n"
        "If a chunk is metadata, attribution, copyright, a table row, or a formula fragment, explain that literal content.\n"
        "Do not invent paper claims that are not present in the chunk.\n"
        "Do not return the original English text as the explanation; if the target language is English, paraphrase it plainly.\n"
        f"Chunks: {json.dumps(chunks, ensure_ascii=False)}"
    )
    return [{"role": "user", "content": prompt}]


def _extract_reading_block_translation_map(
    raw_text: str,
    blocks: list[PaperReaderReadingBlockModel],
) -> dict[str, str]:
    parsed, _repair_attempted = _extract_structured_json_object(raw_text)
    if parsed is None:
        return {}
    raw_items = parsed.get("translations")
    if not isinstance(raw_items, list):
        raw_items = parsed.get("reading_blocks") or parsed.get("readingBlocks")
    if not isinstance(raw_items, list):
        return {}

    original_by_id = {block.chunk_id: block.original_en for block in blocks}
    translations: dict[str, str] = {}
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        chunk_id = str(item.get("chunk_id") or item.get("chunkId") or "").strip()
        original = original_by_id.get(chunk_id)
        if not chunk_id or not original:
            continue
        raw_explanation = (
            item.get("explanation")
            or item.get("translation")
            or item.get("localized_explanation")
            or item.get("localizedExplanation")
            or item.get("display_text")
            or item.get("displayText")
        )
        explanation = _clean_reading_block_localized_text(raw_explanation, original)
        if explanation:
            translations[chunk_id] = explanation
    return translations


def _build_selected_text_translation_messages(text: str, answer_language: str) -> list[dict[str, str]]:
    target_language = _reader_explanation_language(answer_language)
    prompt = (
        "You translate selected source text from a PDF paper reader.\n"
        "Translate only the selected text into the target language.\n"
        "Do not explain, summarize, annotate, add citations, or discuss the paper.\n"
        "Return a single JSON object only with key translation.\n"
        f"Target language: {target_language}.\n"
        f"Selected text: {json.dumps(text, ensure_ascii=False)}"
    )
    return [{"role": "user", "content": prompt}]


def _extract_selected_text_translation(raw_text: str) -> str:
    parsed, _repair_attempted = _extract_structured_json_object(raw_text)
    if isinstance(parsed, dict):
        for key in ("translation", "translated_text", "translatedText", "text"):
            translated = _normalize_multiline_text(parsed.get(key))
            if translated:
                return translated
    return _normalize_multiline_text(raw_text)


def google_translate_text(text: str, target_language: str, timeout: int = 20) -> str:
    source_text = _normalize_multiline_text(text)
    if not source_text:
        return ""

    target = "zh" if target_language == "zh" else "en"
    try:
        response = requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params={
                "client": "gtx",
                "sl": "auto",
                "tl": target,
                "dt": "t",
                "q": source_text,
            },
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"Google Translate request failed: {exc}") from exc

    payload = response.json()
    if not isinstance(payload, list) or not payload:
        return ""
    translated_parts: list[str] = []
    for item in payload[0] or []:
        if isinstance(item, list) and item:
            translated = _normalize_multiline_text(item[0])
            if translated:
                translated_parts.append(translated)
    return _normalize_multiline_text("".join(translated_parts))


def translate_selected_text(
    session_id: str,
    request: PaperReaderSelectionTranslateRequest,
    settings: RuntimeSettings,
) -> PaperReaderSelectionTranslateResponse:
    source_text = _normalize_multiline_text(request.text)
    if not source_text:
        raise ValueError("Selected text is empty.")

    with _SESSION_LOCK:
        session = _get_session(session_id)
        answer_language = _normalize_answer_language(request.answer_language, session.paper_title) or session.answer_language
        _touch_session(session)

    translation_config = _default_paper_reader_translation_config(settings)
    if translation_config.provider == "google_translate":
        translation = google_translate_text(source_text, answer_language, timeout=settings.retrieval.request_timeout)
    else:
        messages = _build_selected_text_translation_messages(source_text, answer_language)
        raw_text = chat_completion(messages, translation_config, settings.retrieval.request_timeout)
        translation = _extract_selected_text_translation(raw_text)
    if not translation:
        raise RuntimeError("Selected text translation returned no content.")
    return PaperReaderSelectionTranslateResponse(
        session_id=session_id,
        source_text=source_text,
        translation=translation,
    )


def _fill_missing_reading_block_translations(
    session: PaperReaderSession,
    content: PaperReaderPageContent,
    settings: RuntimeSettings,
) -> PaperReaderPageContent:
    if content.status != "ready":
        return content
    missing_blocks = [block for block in content.reading_blocks if _reading_block_needs_translation(block)]
    if not missing_blocks:
        return content

    translation_config = _default_paper_reader_translation_config(settings)
    if translation_config.provider == "google_translate":
        translations = {}
        try:
            for block in missing_blocks:
                translated = google_translate_text(
                    block.original_en,
                    session.answer_language,
                    timeout=settings.retrieval.request_timeout,
                )
                cleaned = _clean_reading_block_localized_text(translated, block.original_en)
                if cleaned:
                    translations[block.chunk_id] = cleaned
        except Exception:
            return content
    else:
        messages = _build_reading_block_translation_messages(missing_blocks, session.answer_language)
        try:
            raw_text = chat_completion(messages, translation_config, settings.retrieval.request_timeout)
            translations = _extract_reading_block_translation_map(raw_text, missing_blocks)
        except Exception:
            return content

    if not translations:
        return content
    for block in content.reading_blocks:
        translated = translations.get(block.chunk_id)
        if translated and _reading_block_needs_translation(block):
            block.explanation = translated
            block.display_text = translated
    return content


def _default_coverage_text(plan: PaperReaderPagePlan, source_sections: list[PaperReaderSourceSectionModel]) -> str | None:
    labels = [section.label for section in source_sections if section.label]
    if labels:
        return ", ".join(labels[:4])
    if plan.source_section_titles:
        return ", ".join(plan.source_section_titles[:4])
    return None


def _safe_page_error_message(answer_language: str) -> str:
    if answer_language == "zh":
        return "当前页的结构化 insight card 生成失败，请重试本页。"
    return "The page could not be converted into structured insight cards. Please retry this page."


def _safe_chat_error_message(answer_language: str) -> str:
    if answer_language == "zh":
        return "我没能把当前页证据整理成可靠的结构化回答，请在本页重试这个问题。"
    return "I could not format a reliable answer from the current page evidence. Please retry this question on this page."


def _build_page_messages(session: PaperReaderSession, plan: PaperReaderPagePlan) -> list[dict[str, str]]:
    page_text = _format_page_input(session, plan)
    answer_language = session.answer_language
    explanation_language = _reader_explanation_language(session.answer_language)
    guided_mode = session.reader_mode == "guided"
    metadata = {
        "session_id": session.session_id,
        "paper_title": session.paper_title,
        "source_type": session.source_type,
        "source_id": session.source_id,
        "page_index": plan.page_index,
        "page_title": plan.title,
        "page_range": [plan.page_start, plan.page_end],
        "reading_focus_title": plan.focus_title,
        "covered_source_sections": list(plan.source_section_titles),
        "source_node_ids": list(plan.source_node_ids),
        "answer_language": answer_language,
        "reader_mode": session.reader_mode,
        "discipline": _normalize_discipline(session.discipline),
        "discipline_source": session.discipline_source,
    }
    discipline_guidance = _discipline_prompt_guidance(session.discipline)
    guided_requirements = ""
    if guided_mode:
        quick_story_line = (
            "For Quick Story, create a five-minute beginner orientation using this paper's discipline-specific reading priorities.\n"
            if plan.focus_key == "quick_story"
            else ""
        )
        guided_requirements = (
            "Guided beginner fields are required: story_stage, mentor_script, discipline_guide, glossary_terms, reading_hints, checkpoints.\n"
            "story_stage must be an object with keys: key, title, description.\n"
            "mentor_script must contain 2 to 4 short items using original_en and explanation; write like a calm research mentor.\n"
            f"{_discipline_guide_requirement_text(session.discipline, answer_language)}\n"
            "glossary_terms must contain up to 5 objects with term, explanation, source, chunk_id; source is paper or background.\n"
            "reading_hints must contain objects with kind must_know, skim, or advanced plus text and reason.\n"
            "checkpoints must contain 2 to 3 objects with question, answer, review_hint.\n"
            "Separate paper-grounded claims from background explanations; mark background glossary items with source=background.\n"
            f"{quick_story_line}"
        )
    prompt = (
        "You are generating one reading page for a paper reader.\n"
        "Return a single JSON object only.\n"
        "Required top-level keys: page_title, coverage, page_overview, insights, citations.\n"
        "Do not translate full source chunks or produce reading_blocks; source-card translations are handled by a separate translation API.\n"
        "This paper reader paginates the full paper by document-level reading focus buckets.\n"
        f"This page belongs to the focus bucket: {plan.focus_title}.\n"
        f"Paper discipline: {_normalize_discipline(session.discipline)} ({_discipline_display_name(session.discipline)}).\n"
        f"Discipline reading rule: {discipline_guidance}\n"
        "Do not rebuild the full paper route inside this one page.\n"
        "page_overview must be an object with keys: original_en, explanation.\n"
        "insights must contain 1 to 3 insight cards for the current page only.\n"
        "Each insight item must have: title, kind, summary, evidence, source_chunk_ids, and may include why_it_matters.\n"
        "summary must be an object with keys: original_en, explanation.\n"
        "evidence must be an array of 0 to 3 objects, and each object must also use: original_en, explanation.\n"
        "why_it_matters may be an array of 0 to 2 objects using original_en and explanation; explain why this insight is worth reading next.\n"
        "why_it_matters must not repeat the summary or evidence text, and must not quote evidence again.\n"
        "Keep page_overview concise: at most 2 sentences per field.\n"
        "Keep each explanation concise: at most 2 sentences.\n"
        "Use only one short original_en excerpt for page_overview and one short original_en excerpt per insight summary.\n"
        "Do not serialize nested JSON as strings inside any field.\n"
        "source_chunk_ids must reference only chunk_id values from the supplied chunks.\n"
        "Each citation must include chunk_id, section_title, subsection_title, page_start, page_end, excerpt.\n"
        f"{guided_requirements}"
        f"Strict language rule: keep every original_en field in English, and every explanation field in {explanation_language}.\n"
        "Do not return legacy free-text sections, markdown, or commentary outside the JSON object.\n"
        f"Metadata: {json.dumps(metadata, ensure_ascii=False)}\n"
        f"Chunks:\n{page_text}"
    )
    return [{"role": "user", "content": prompt}]


def _build_chat_messages(
    session: PaperReaderSession,
    plan: PaperReaderPagePlan,
    request: PaperReaderChatRequest,
    selected_chunks: list[PaperReaderChunk],
    selected_nodes: list[PaperReaderSelectedNodeModel] | None = None,
) -> list[dict[str, str]]:
    answer_language = _normalize_answer_language(request.answer_language, session.paper_title) or session.answer_language
    explanation_label = _reader_explanation_label(answer_language)
    explanation_language = _reader_explanation_language(answer_language)
    history_lines = [f"{item.role}: {item.text}" for item in request.history if item.text.strip()]
    chunk_lines = []
    for chunk in selected_chunks:
        title = _section_label(chunk.section_title, chunk.subsection_title)
        chunk_lines.append(
            f"[{chunk.chunk_id} | {title} | pages {chunk.page_start}-{chunk.page_end}]\n{chunk.text}"
        )
    node_lines = []
    for node in selected_nodes or []:
        node_lines.append(
            f"[{node.node_id} | {node.title} | pages {node.page_start}-{node.page_end}]\n{node.summary or ''}"
        )
    requested_discipline = _normalize_discipline_request(request.discipline)
    chat_discipline = requested_discipline if requested_discipline in DISCIPLINES else session.discipline
    prompt = (
        "You answer questions about a single paper using only the supplied chunks.\n"
        "Return a JSON object with the keys: answer_text, citations, used_chunks.\n"
        f"Paper discipline: {_normalize_discipline(chat_discipline)} ({_discipline_display_name(chat_discipline)}).\n"
        f"Use this discipline-specific reading rule: {_discipline_prompt_guidance(chat_discipline)}\n"
        "Each citation must include chunk_id, section_title, subsection_title, page_start, page_end, excerpt.\n"
        "Each used_chunk must include chunk_id, section_title, subsection_title, page_start, page_end, text, token_estimate, score.\n"
        f"Strict language rule: keep the original evidence in English, and explain it only in {explanation_language}.\n"
        "The answer_text must follow this format for every major point:\n"
        "Original (EN): <short verbatim or tightly grounded English snippet from the supplied chunks>\n"
        f"{explanation_label}: <grounded explanation in {explanation_language}>\n"
        "If you need multiple points, separate them with blank lines and repeat the same format for each point.\n"
        "Do not add explanations in any other language.\n"
        f"Paper title: {session.paper_title}\n"
        f"Current page: {plan.page_index} - {plan.title}\n"
        f"Paper map nodes:\n{chr(10).join(node_lines) if node_lines else '(none)'}\n"
        f"Conversation history:\n{chr(10).join(history_lines) if history_lines else '(none)'}\n"
        f"Question:\n{request.message.strip()}\n"
        f"Relevant chunks:\n{chr(10).join(chunk_lines)}"
    )
    return [{"role": "user", "content": prompt}]


def _ensure_chunk_embedding(chunk: PaperReaderChunk, settings: RuntimeSettings) -> list[float]:
    if chunk.embedding is not None:
        return chunk.embedding
    chunk.embedding = get_embedding(chunk.text, settings)
    return chunk.embedding


def _select_chat_chunks(
    session: PaperReaderSession,
    page_index: int,
    request: PaperReaderChatRequest,
    settings: RuntimeSettings,
) -> tuple[PaperReaderPagePlan, list[PaperReaderChunk], list[PaperReaderSelectedNodeModel]]:
    if page_index < 0 or page_index >= len(session.pages):
        raise IndexError("Requested page is out of range.")
    plan = session.pages[page_index]
    page_chunk_ids = set(plan.chunk_ids)
    current_page_chunks = [chunk for chunk in session.chunks if chunk.chunk_id in page_chunk_ids]
    query_text = request.message.strip()
    if request.history:
        history_tail = " ".join(item.text for item in request.history[-3:] if item.text.strip())
        query_text = f"{history_tail} {query_text}".strip()
    query_vec = get_embedding(query_text, settings)

    scored: list[tuple[float, PaperReaderChunk]] = []
    for chunk in session.chunks:
        embedding = _ensure_chunk_embedding(chunk, settings)
        score = cosine_similarity(query_vec, embedding)
        if chunk.chunk_id in page_chunk_ids:
            score += 0.15
        if chunk.reading_focus_key == plan.focus_key:
            score += 0.08
        if _section_label(chunk.section_title, chunk.subsection_title) in plan.source_section_titles:
            score += 0.05
        scored.append((score, chunk))
    scored.sort(key=lambda item: item[0], reverse=True)

    page_candidates = [item for item in scored if item[1].chunk_id in page_chunk_ids][:6]
    global_candidates = [item for item in scored if item[1].chunk_id not in {chunk.chunk_id for _, chunk in page_candidates}][:6]
    selected = [chunk for _, chunk in page_candidates + global_candidates]

    if not selected:
        selected = current_page_chunks[:4] or session.chunks[:4]
    selected_nodes = _index_nodes_for_chunks(session, selected)
    return plan, selected, selected_nodes


def _normalize_chunk_id_list(raw_value: Any, allowed_chunk_ids: set[str]) -> list[str]:
    if isinstance(raw_value, str):
        candidates = [part.strip() for part in raw_value.split(",")]
    elif isinstance(raw_value, list):
        candidates = [str(item or "").strip() for item in raw_value]
    else:
        candidates = []
    chunk_ids: list[str] = []
    for chunk_id in candidates:
        if chunk_id and chunk_id in allowed_chunk_ids and chunk_id not in chunk_ids:
            chunk_ids.append(chunk_id)
    return chunk_ids


def _infer_insight_kind(raw_kind: Any, title: str, plan: PaperReaderPagePlan) -> str:
    candidate = normalize_whitespace(raw_kind or "").casefold().replace(" ", "_")
    if candidate:
        return candidate
    hint_text = f"{title} {plan.focus_key} {plan.focus_title}".casefold()
    if "limit" in hint_text or "open_question" in hint_text or "caveat" in hint_text:
        return "limitation"
    if "question" in hint_text:
        return "question"
    if "method" in hint_text or "mechanism" in hint_text or "approach" in hint_text:
        return "method"
    if "evidence" in hint_text or "experiment" in hint_text or "result" in hint_text:
        return "evidence"
    if "conclusion" in hint_text or "takeaway" in hint_text:
        return "takeaway"
    return "insight"


def _coerce_page_citations(
    raw_value: Any,
    plan: PaperReaderPagePlan,
    chunk_lookup: dict[str, PaperReaderChunk],
) -> list[PaperReaderCitationModel]:
    citations: list[PaperReaderCitationModel] = []
    raw_citations = raw_value if isinstance(raw_value, list) else []
    for item in raw_citations:
        if not isinstance(item, dict):
            continue
        chunk_id = str(item.get("chunk_id") or "").strip()
        chunk = chunk_lookup.get(chunk_id)
        citations.append(
            PaperReaderCitationModel(
                chunk_id=chunk.chunk_id if chunk is not None else (chunk_id or uuid.uuid4().hex),
                section_title=_normalize_title(
                    item.get("section_title"),
                    chunk.section_title if chunk is not None else plan.section_title,
                ),
                subsection_title=(str(item.get("subsection_title")).strip() or None)
                if item.get("subsection_title") is not None
                else (chunk.subsection_title if chunk is not None else None),
                page_start=_coerce_int(item.get("page_start"), chunk.page_start if chunk is not None else plan.page_start),
                page_end=_coerce_int(item.get("page_end"), chunk.page_end if chunk is not None else plan.page_end),
                excerpt=(str(item.get("excerpt")).strip() or None)
                if item.get("excerpt") is not None
                else (chunk.text[:240] if chunk is not None else None),
                score=float(item["score"]) if isinstance(item.get("score"), (float, int)) else None,
            )
        )
    return citations


def _coerce_string_items(raw_value: Any, *, limit: int = 5) -> list[str]:
    if isinstance(raw_value, str):
        candidates = [raw_value]
    elif isinstance(raw_value, list):
        candidates = raw_value
    else:
        candidates = []
    items: list[str] = []
    for item in candidates:
        if isinstance(item, dict):
            text = normalize_whitespace(
                item.get("text")
                or item.get("title")
                or item.get("summary")
                or item.get("explanation")
                or item.get("takeaway")
                or ""
            )
        else:
            text = normalize_whitespace(str(item or ""))
        if text and text not in items:
            items.append(text)
        if len(items) >= limit:
            break
    return items


def _coerce_mentor_script(raw_value: Any, answer_language: str, fallback_original: str) -> list[PaperReaderStructuredTextModel]:
    raw_items = raw_value if isinstance(raw_value, list) else []
    script = [
        item
        for raw_item in raw_items[:4]
        if (item := _coerce_structured_inline(raw_item, answer_language, fallback_original)) is not None
    ]
    return script


def _coerce_blackboard_notes(raw_value: Any, parsed: dict[str, Any]) -> PaperReaderBlackboardNotesModel | None:
    source = raw_value if isinstance(raw_value, dict) else {}
    core_concepts = _coerce_string_items(source.get("core_concepts") or source.get("concepts"), limit=5)
    method_steps = _coerce_string_items(source.get("method_steps") or source.get("steps"), limit=5)
    experiment_takeaways = _coerce_string_items(
        source.get("experiment_takeaways") or source.get("evidence") or source.get("results"),
        limit=5,
    )
    takeaway = normalize_whitespace(source.get("takeaway") or source.get("summary") or "")
    if not core_concepts:
        core_concepts = _coerce_string_items(parsed.get("key_points"), limit=3)
    if not takeaway:
        takeaway = normalize_whitespace(parsed.get("coverage") or "")
    if not (core_concepts or method_steps or experiment_takeaways or takeaway):
        return None
    return PaperReaderBlackboardNotesModel(
        core_concepts=core_concepts,
        method_steps=method_steps,
        experiment_takeaways=experiment_takeaways,
        takeaway=takeaway or None,
    )


def _discipline_guide_requirement_text(discipline: str, answer_language: str) -> str:
    panel_lines = [
        f"- {key}: {title}"
        for key, title in DISCIPLINE_GUIDE_PANEL_TEMPLATES.get(
            _normalize_discipline(discipline),
            DISCIPLINE_GUIDE_PANEL_TEMPLATES["general"],
        )
    ]
    language_hint = "Simplified Chinese" if answer_language == "zh" else "English"
    return (
        "discipline_guide is required for the guided teaching panels.\n"
        "discipline_guide must be an object with keys: discipline, title, panels.\n"
        "discipline_guide.panels must contain discipline-specific explanation panels; each panel has key, title, items, takeaway.\n"
        f"Use discipline={_normalize_discipline(discipline)}. Write panel title/items/takeaway in {language_hint}.\n"
        "Expected panel intentions:\n" + "\n".join(panel_lines) + "\n"
        "Use discipline_guide as the only guided teaching panel schema."
    )


def _coerce_discipline_guide(
    raw_value: Any,
    discipline: str,
    answer_language: str,
) -> PaperReaderDisciplineGuideModel | None:
    if not isinstance(raw_value, dict):
        return None
    normalized_discipline = _normalize_discipline(raw_value.get("discipline") or discipline)
    title = _normalize_title(raw_value.get("title"), _discipline_guide_title(normalized_discipline, answer_language))
    raw_panels = raw_value.get("panels") if isinstance(raw_value.get("panels"), list) else []
    panels: list[PaperReaderDisciplineGuidePanelModel] = []
    for index, item in enumerate(raw_panels[:6]):
        if not isinstance(item, dict):
            continue
        key = normalize_whitespace(item.get("key") or item.get("id") or f"panel_{index + 1}").casefold()
        key = re.sub(r"[^a-z0-9_]+", "_", key).strip("_") or f"panel_{index + 1}"
        panel_title = _normalize_title(item.get("title"), key.replace("_", " ").title())
        items = _coerce_string_items(item.get("items") or item.get("bullets") or item.get("points"), limit=5)
        takeaway = normalize_whitespace(item.get("takeaway") or item.get("summary") or "")
        if not (items or takeaway):
            continue
        panels.append(
            PaperReaderDisciplineGuidePanelModel(
                key=key,
                title=panel_title,
                items=items,
                takeaway=takeaway or None,
            )
        )
    if not panels:
        return None
    return PaperReaderDisciplineGuideModel(
        discipline=normalized_discipline,
        title=title,
        panels=panels,
    )


def _synthesize_discipline_guide(
    session: PaperReaderSession,
    plan: PaperReaderPagePlan,
    overview: PaperReaderStructuredTextModel | None,
    insights: list[PaperReaderInsightModel],
) -> PaperReaderDisciplineGuideModel:
    discipline = _normalize_discipline(session.discipline)
    source_items: list[str] = []
    if overview is not None:
        source_items.append(overview.explanation or overview.display_text or overview.original_en or "")
    for insight in insights:
        if insight.summary is not None:
            source_items.append(insight.summary.explanation or insight.summary.display_text or insight.summary.original_en or "")
        source_items.extend(item.explanation or item.display_text or item.original_en or "" for item in insight.evidence[:2])
    source_items = [item for item in dict.fromkeys(normalize_whitespace(item) for item in source_items) if item]
    if not source_items:
        source_items = [plan.focus_title]

    panels: list[PaperReaderDisciplineGuidePanelModel] = []
    for index, (key, title) in enumerate(
        DISCIPLINE_GUIDE_PANEL_TEMPLATES.get(discipline, DISCIPLINE_GUIDE_PANEL_TEMPLATES["general"])
    ):
        item = source_items[min(index, len(source_items) - 1)]
        panels.append(
            PaperReaderDisciplineGuidePanelModel(
                key=key,
                title=title,
                items=[item],
                takeaway=item if index == 0 else None,
            )
        )
    return PaperReaderDisciplineGuideModel(
        discipline=discipline,
        title=_discipline_guide_title(discipline, session.answer_language),
        panels=panels,
    )


def _coerce_glossary_terms(
    raw_value: Any,
    citations: list[PaperReaderCitationModel],
    chunk_lookup: dict[str, PaperReaderChunk],
) -> list[PaperReaderGlossaryTermModel]:
    raw_terms = raw_value if isinstance(raw_value, list) else []
    citation_by_chunk = {citation.chunk_id: citation for citation in citations}
    terms: list[PaperReaderGlossaryTermModel] = []
    for item in raw_terms[:8]:
        if not isinstance(item, dict):
            continue
        term = normalize_whitespace(item.get("term") or item.get("name") or item.get("symbol") or "")
        explanation = normalize_whitespace(
            item.get("explanation") or item.get("meaning") or item.get("description") or item.get("text") or ""
        )
        if not term or not explanation:
            continue
        source = normalize_whitespace(item.get("source") or "").casefold()
        source_kind = "background" if source == "background" or bool(item.get("background")) else "paper"
        chunk_id = normalize_whitespace(item.get("chunk_id") or item.get("source_chunk_id") or "")
        citation = citation_by_chunk.get(chunk_id)
        if citation is None and chunk_id in chunk_lookup:
            citation = _chunk_to_citation(chunk_lookup[chunk_id])
        if citation is None and source_kind == "paper" and citations:
            citation = citations[0]
        terms.append(
            PaperReaderGlossaryTermModel(
                term=term,
                explanation=explanation,
                source=source_kind,
                citation=citation,
            )
        )
    return terms


def _coerce_reading_hints(raw_value: Any) -> list[PaperReaderReadingHintModel]:
    raw_hints = raw_value if isinstance(raw_value, list) else []
    allowed = {"must_know", "skim", "advanced"}
    hints: list[PaperReaderReadingHintModel] = []
    for item in raw_hints[:6]:
        if isinstance(item, dict):
            kind = normalize_whitespace(item.get("kind") or item.get("type") or "").casefold().replace("-", "_").replace(" ", "_")
            text = normalize_whitespace(item.get("text") or item.get("title") or item.get("summary") or "")
            reason = normalize_whitespace(item.get("reason") or item.get("why") or "")
        else:
            kind = "must_know"
            text = normalize_whitespace(str(item or ""))
            reason = ""
        if kind in {"required", "important", "beginner"}:
            kind = "must_know"
        if kind in {"skip", "optional"}:
            kind = "skim"
        if kind not in allowed:
            kind = "must_know"
        if text:
            hints.append(PaperReaderReadingHintModel(kind=kind, text=text, reason=reason or None))
    return hints


def _coerce_checkpoints(raw_value: Any, page_index: int) -> list[PaperReaderCheckpointModel]:
    raw_checkpoints = raw_value if isinstance(raw_value, list) else []
    checkpoints: list[PaperReaderCheckpointModel] = []
    for item in raw_checkpoints[:3]:
        if not isinstance(item, dict):
            continue
        question = normalize_whitespace(item.get("question") or item.get("prompt") or "")
        answer = normalize_whitespace(item.get("answer") or item.get("reference_answer") or item.get("solution") or "")
        review_hint = normalize_whitespace(item.get("review_hint") or item.get("hint") or item.get("look_back") or "")
        if question and answer:
            checkpoints.append(
                PaperReaderCheckpointModel(
                    question=question,
                    answer=answer,
                    review_hint=review_hint or None,
                    source_page_index=_coerce_int(item.get("source_page_index"), page_index),
                )
            )
    return checkpoints


def _build_sections_from_insights(insights: list[PaperReaderInsightModel]) -> list[PaperReaderSectionModel]:
    sections: list[PaperReaderSectionModel] = []
    for insight in insights:
        bullets = [item.display_text for item in insight.evidence if item.display_text]
        text = insight.summary.display_text if insight.summary is not None else None
        if not text and not bullets:
            continue
        sections.append(PaperReaderSectionModel(title=insight.title, text=text, bullets=bullets))
    return sections


def _collect_limitation_items(insights: list[PaperReaderInsightModel]) -> list[str]:
    limitation_items: list[str] = []
    for insight in insights:
        kind = insight.kind.casefold()
        if any(token in kind for token in ("limit", "question", "caveat", "risk", "failure")):
            if insight.summary is not None and insight.summary.display_text:
                limitation_items.append(insight.summary.display_text)
            limitation_items.extend(item.display_text for item in insight.evidence if item.display_text)
    return limitation_items


def _build_page_placeholder(
    session: PaperReaderSession,
    plan: PaperReaderPagePlan,
    *,
    status: str,
    message: str | None = None,
    repair_attempted: bool = False,
) -> PaperReaderPageContent:
    source_sections = _build_source_sections(session, plan)
    reading_blocks = _build_reading_blocks(session, plan)
    structured_state = "failed" if status == "error" else "pending"
    return PaperReaderPageContent(
        page_index=plan.page_index,
        title=plan.title,
        status=status,
        coverage=_default_coverage_text(plan, source_sections),
        structured_status=PaperReaderStructuredStatusModel(
            state=structured_state,
            message=message,
            repair_attempted=repair_attempted,
        ),
        reading_blocks=reading_blocks,
        source_sections=source_sections,
        story_stage=_story_stage_for_focus(plan.focus_key, session.answer_language) if session.reader_mode == "guided" else None,
        chunk_ids=list(plan.chunk_ids),
        source_node_ids=list(plan.source_node_ids),
        estimated_tokens=plan.estimated_tokens,
        page_start=plan.page_start,
        page_end=plan.page_end,
        error_message=message if status == "error" else None,
    )


def _page_content_from_output(
    session: PaperReaderSession,
    plan: PaperReaderPagePlan,
    raw_text: str,
) -> PaperReaderPageContent:
    fallback_title = plan.title
    chunk_lookup = {chunk.chunk_id: chunk for chunk in session.chunks}
    allowed_chunk_ids = set(plan.chunk_ids)
    source_sections = _build_source_sections(session, plan)
    source_section_lookup = {section.label: section for section in source_sections}
    reading_blocks = _build_reading_blocks(session, plan)
    fallback_original = ""
    for chunk_id in plan.chunk_ids:
        chunk = chunk_lookup.get(chunk_id)
        if chunk is not None:
            fallback_original = _clip_original_excerpt(chunk.text)
            break
    parsed, repair_attempted = _extract_structured_json_object(raw_text)
    if parsed is None:
        return _build_page_placeholder(
            session,
            plan,
            status="error",
            message=_safe_page_error_message(session.answer_language),
            repair_attempted=repair_attempted,
        )
    citations = _coerce_page_citations(parsed.get("citations"), plan, chunk_lookup)
    citation_lookup = {citation.chunk_id: citation for citation in citations}

    overview = _coerce_structured_block(
        parsed.get("page_overview") or parsed.get("overview") or parsed.get("summary"),
        session.answer_language,
        fallback_original,
    )

    raw_insights = parsed.get("insights") if isinstance(parsed.get("insights"), list) else []
    insights: list[PaperReaderInsightModel] = []
    for index, item in enumerate(raw_insights):
        if not isinstance(item, dict):
            continue
        title = _normalize_title(item.get("title"), f"Insight {index + 1}")
        summary_block = _coerce_structured_block(
            item.get("summary") or item.get("insight") or item.get("text"),
            session.answer_language,
            fallback_original,
        )
        evidence_blocks = [
            evidence_block
            for evidence_item in (
                item.get("evidence")
                if isinstance(item.get("evidence"), list)
                else item.get("bullets")
                if isinstance(item.get("bullets"), list)
                else item.get("supporting_points")
                if isinstance(item.get("supporting_points"), list)
                else []
            )[:3]
            if (evidence_block := _coerce_structured_inline(evidence_item, session.answer_language, fallback_original))
        ]
        why_it_matters_blocks = _coerce_why_it_matters_blocks(
            item,
            session.answer_language,
            fallback_original,
            summary_block,
            evidence_blocks,
        )
        source_chunk_ids = _normalize_chunk_id_list(
            item.get("source_chunk_ids") or item.get("chunk_ids") or item.get("citation_chunk_ids"),
            allowed_chunk_ids,
        )
        if not source_chunk_ids and citations:
            source_chunk_ids = [citation.chunk_id for citation in citations[:2] if citation.chunk_id in allowed_chunk_ids]
        source_section_labels = [
            _section_label(chunk_lookup[chunk_id].section_title, chunk_lookup[chunk_id].subsection_title)
            for chunk_id in source_chunk_ids
            if chunk_id in chunk_lookup
        ]
        if not source_section_labels:
            raw_labels = item.get("source_section_labels") if isinstance(item.get("source_section_labels"), list) else []
            source_section_labels = [normalize_whitespace(label) for label in raw_labels if normalize_whitespace(label)]
        insight_citations = [citation_lookup[chunk_id] for chunk_id in source_chunk_ids if chunk_id in citation_lookup]
        if not insight_citations:
            insight_citations = [_chunk_to_citation(chunk_lookup[chunk_id]) for chunk_id in source_chunk_ids if chunk_id in chunk_lookup]
        if not summary_block and not evidence_blocks:
            continue
        insights.append(
            PaperReaderInsightModel(
                insight_id=f"{plan.page_index}-{index + 1}",
                title=title,
                kind=_infer_insight_kind(item.get("kind"), title, plan),
                summary=summary_block,
                evidence=evidence_blocks,
                why_it_matters=why_it_matters_blocks,
                source_chunk_ids=source_chunk_ids,
                source_section_labels=list(dict.fromkeys(source_section_labels)),
                citations=insight_citations,
            )
        )
        if len(insights) >= 3:
            break

    if not insights:
        raw_sections = parsed.get("sections") if isinstance(parsed.get("sections"), list) else []
        for index, item in enumerate(raw_sections[:3]):
            if not isinstance(item, dict):
                continue
            title = _normalize_title(item.get("title"), f"Insight {index + 1}")
            summary_block = _coerce_structured_block(item.get("text") or item.get("summary"), session.answer_language, fallback_original)
            evidence_blocks = [
                evidence_block
                for bullet in (item.get("bullets") if isinstance(item.get("bullets"), list) else [])[:3]
                if (evidence_block := _coerce_structured_inline(bullet, session.answer_language, fallback_original))
            ]
            why_it_matters_blocks = _coerce_why_it_matters_blocks(
                item,
                session.answer_language,
                fallback_original,
                summary_block,
                evidence_blocks,
            )
            if not summary_block and not evidence_blocks:
                continue
            insights.append(
                PaperReaderInsightModel(
                    insight_id=f"{plan.page_index}-legacy-{index + 1}",
                    title=title,
                    kind=_infer_insight_kind(None, title, plan),
                    summary=summary_block,
                    evidence=evidence_blocks,
                    why_it_matters=why_it_matters_blocks,
                    source_chunk_ids=[],
                    source_section_labels=[section.label for section in source_sections[:2]],
                    citations=citations[:2],
                )
            )

    key_point_items = parsed.get("key_points") if isinstance(parsed.get("key_points"), list) else []
    limitation_items = parsed.get("limitations") if isinstance(parsed.get("limitations"), list) else []

    if not insights:
        synthesized_summary = _coerce_structured_block(parsed.get("summary"), session.answer_language, fallback_original)
        synthesized_evidence = [
            evidence_block
            for item in (key_point_items or limitation_items)[:3]
            if (evidence_block := _coerce_structured_inline(item, session.answer_language, fallback_original))
        ]
        if synthesized_summary is not None or synthesized_evidence:
            insights.append(
                PaperReaderInsightModel(
                    insight_id=f"{plan.page_index}-fallback-1",
                    title=plan.focus_title,
                    kind=_infer_insight_kind(None, plan.focus_title, plan),
                    summary=synthesized_summary,
                    evidence=synthesized_evidence,
                    source_chunk_ids=[],
                    source_section_labels=[section.label for section in source_sections[:2]],
                    citations=citations[:2],
                )
            )

    if overview is None and insights:
        overview = insights[0].summary

    if overview is None or not insights:
        return _build_page_placeholder(
            session,
            plan,
            status="error",
            message=_safe_page_error_message(session.answer_language),
            repair_attempted=repair_attempted,
        )

    if not citations:
        citations = [_chunk_to_citation(chunk_lookup[chunk_id]) for chunk_id in plan.chunk_ids[:4] if chunk_id in chunk_lookup]

    parsed_stage = parsed.get("story_stage") if isinstance(parsed.get("story_stage"), dict) else {}
    story_stage = None
    if session.reader_mode == "guided":
        default_stage = _story_stage_for_focus(plan.focus_key, session.answer_language)
        story_stage = PaperReaderStoryStageModel(
            key=normalize_whitespace(parsed_stage.get("key") or default_stage.key),
            title=_normalize_title(parsed_stage.get("title"), default_stage.title),
            description=normalize_whitespace(parsed_stage.get("description") or default_stage.description or "") or None,
        )
    mentor_script = (
        _coerce_mentor_script(parsed.get("mentor_script"), session.answer_language, fallback_original)
        if session.reader_mode == "guided"
        else []
    )
    discipline_guide = (
        _coerce_discipline_guide(
            parsed.get("discipline_guide") or parsed.get("disciplineGuide"),
            session.discipline,
            session.answer_language,
        )
        if session.reader_mode == "guided"
        else None
    )
    blackboard_notes = None
    glossary_terms = (
        _coerce_glossary_terms(parsed.get("glossary_terms"), citations, chunk_lookup)
        if session.reader_mode == "guided"
        else []
    )
    reading_hints = _coerce_reading_hints(parsed.get("reading_hints")) if session.reader_mode == "guided" else []
    checkpoints = _coerce_checkpoints(parsed.get("checkpoints"), plan.page_index) if session.reader_mode == "guided" else []

    sections = _build_sections_from_insights(insights)
    key_points = [insight.summary.display_text for insight in insights if insight.summary is not None and insight.summary.display_text]
    key_points.extend(
        item.display_text
        for item in (
            _coerce_structured_inline(value, session.answer_language, fallback_original) for value in key_point_items[:3]
        )
        if item is not None and item.display_text
    )
    key_points = list(dict.fromkeys(key_points))
    limitations = _collect_limitation_items(insights)
    limitations.extend(
        item.display_text
        for item in (
            _coerce_structured_inline(value, session.answer_language, fallback_original) for value in limitation_items[:3]
        )
        if item is not None and item.display_text
    )
    limitations = list(dict.fromkeys(limitations))
    if session.reader_mode == "guided":
        if not mentor_script and overview is not None:
            mentor_script = [overview]
        if discipline_guide is None:
            discipline_guide = _synthesize_discipline_guide(session, plan, overview, insights)
        if not reading_hints:
            reading_hints = _default_reading_hints(plan, session.answer_language)
        if not checkpoints:
            checkpoints = _default_checkpoints(plan, session.answer_language, overview)
    reading_blocks = _localized_reading_blocks(reading_blocks)
    coverage = normalize_whitespace(parsed.get("coverage") or "") or _default_coverage_text(plan, source_sections)
    title = _normalize_title(parsed.get("page_title"), fallback_title)
    return PaperReaderPageContent(
        page_index=plan.page_index,
        title=title,
        status="ready",
        coverage=coverage or None,
        page_overview=overview,
        insights=insights,
        structured_status=PaperReaderStructuredStatusModel(
            state="repaired" if repair_attempted else "ready",
            repair_attempted=repair_attempted,
            message=None,
        ),
        reading_blocks=reading_blocks,
        source_sections=source_sections,
        mentor_script=mentor_script,
        blackboard_notes=blackboard_notes,
        discipline_guide=discipline_guide,
        story_stage=story_stage,
        glossary_terms=glossary_terms,
        reading_hints=reading_hints,
        checkpoints=checkpoints,
        summary=overview.display_text,
        sections=sections,
        key_points=key_points,
        limitations=limitations,
        citations=citations,
        chunk_ids=list(plan.chunk_ids),
        source_node_ids=list(plan.source_node_ids),
        estimated_tokens=plan.estimated_tokens,
        page_start=plan.page_start,
        page_end=plan.page_end,
        generated_at=_now_iso(),
    )


def _store_page_content(session: PaperReaderSession, content: PaperReaderPageContent) -> PaperReaderPageContent:
    session.page_contents[content.page_index] = content
    session.page_statuses[content.page_index] = content.status
    session.current_page_index = content.page_index
    _touch_session(session)
    return content


def _generate_page_content_internal(
    session_id: str,
    page_index: int,
    settings: RuntimeSettings,
    *,
    stream: bool = False,
) -> PaperReaderPageContent | Iterator[str]:
    with _SESSION_LOCK:
        session = _get_session(session_id)
        if page_index < 0 or page_index >= len(session.pages):
            raise IndexError("Requested page is out of range.")
        plan = session.pages[page_index]
        existing = session.page_contents.get(page_index)
        if existing is not None and existing.status == "ready":
            if stream:
                def ready_stream() -> Iterator[str]:
                    yield json.dumps(page_content_to_model(existing).model_dump(), ensure_ascii=False)

                return ready_stream()
            return existing
        status = session.page_statuses.get(page_index)
        if status == "generating":
            if stream:
                def waiting_stream() -> Iterator[str]:
                    while True:
                        with _SESSION_LOCK:
                            current = session.page_contents.get(page_index)
                            current_status = session.page_statuses.get(page_index, "queued")
                        if current is not None and current_status == "ready":
                            yield json.dumps(page_content_to_model(current).model_dump(), ensure_ascii=False)
                            return
                        if current_status == "error":
                            yield json.dumps(
                                {
                                    "status": "error",
                                    "page_index": page_index,
                                    "message": current.error_message if current else "page generation failed",
                                },
                                ensure_ascii=False,
                            )
                            return
                        time.sleep(0.2)

                return waiting_stream()
            return session.page_contents.get(page_index) or PaperReaderPageContent(
                page_index=page_index,
                title=plan.title,
                status="generating",
                story_stage=_story_stage_for_focus(plan.focus_key, session.answer_language) if session.reader_mode == "guided" else None,
                estimated_tokens=plan.estimated_tokens,
                page_start=plan.page_start,
                page_end=plan.page_end,
                chunk_ids=list(plan.chunk_ids),
                source_node_ids=list(plan.source_node_ids),
            )
        session.page_statuses[page_index] = "generating"
        _touch_session(session)

    chat_config = _default_paper_reader_chat_config(settings)
    messages = _build_page_messages(session, plan)

    if stream:
        def event_stream() -> Iterator[str]:
            collected: list[str] = []
            try:
                for token in stream_chat_tokens(messages, chat_config, settings.retrieval.request_timeout, settings.embedding.api_url):
                    collected.append(token)
                    yield token
                content = _page_content_from_output(session, plan, "".join(collected))
                content = _fill_missing_reading_block_translations(session, content, settings)
                with _SESSION_LOCK:
                    _store_page_content(session, content)
                    if page_index + 1 < len(session.pages):
                        _schedule_prefetch(session.session_id, page_index + 1, settings)
                yield json.dumps({"status": "complete", "page_index": page_index, "title": content.title}, ensure_ascii=False)
            except Exception as exc:
                error_content = PaperReaderPageContent(
                    page_index=page_index,
                    title=plan.title,
                    status="error",
                    story_stage=_story_stage_for_focus(plan.focus_key, session.answer_language) if session.reader_mode == "guided" else None,
                    estimated_tokens=plan.estimated_tokens,
                    page_start=plan.page_start,
                    page_end=plan.page_end,
                    chunk_ids=list(plan.chunk_ids),
                    source_node_ids=list(plan.source_node_ids),
                    error_message=str(exc),
                )
                with _SESSION_LOCK:
                    _store_page_content(session, error_content)
                yield json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False)

        return event_stream()

    try:
        raw_text = chat_completion(messages, chat_config, settings.retrieval.request_timeout)
        content = _page_content_from_output(session, plan, raw_text)
        content = _fill_missing_reading_block_translations(session, content, settings)
    except Exception as exc:
        content = PaperReaderPageContent(
            page_index=page_index,
            title=plan.title,
            status="error",
            story_stage=_story_stage_for_focus(plan.focus_key, session.answer_language) if session.reader_mode == "guided" else None,
            estimated_tokens=plan.estimated_tokens,
            page_start=plan.page_start,
            page_end=plan.page_end,
            chunk_ids=list(plan.chunk_ids),
            source_node_ids=list(plan.source_node_ids),
            error_message=str(exc),
        )
    with _SESSION_LOCK:
        _store_page_content(session, content)
        if content.status == "ready" and page_index + 1 < len(session.pages):
            _schedule_prefetch(session.session_id, page_index + 1, settings)
    return content


def _prefetch_page(session_id: str, page_index: int, settings: RuntimeSettings) -> None:
    with suppress(Exception):
        _generate_page_content_internal(session_id, page_index, settings, stream=False)


def _schedule_prefetch(session_id: str, page_index: int, settings: RuntimeSettings) -> None:
    key = (session_id, page_index)
    if key in _PAGE_TASKS:
        return
    _PAGE_TASKS[key] = _PAGE_EXECUTOR.submit(_prefetch_page, session_id, page_index, settings)


def _build_session(
    *,
    source_type: str,
    source_url: str | None,
    source_id: str | None,
    pdf_path: Path,
    settings: RuntimeSettings,
    answer_language: str | None = None,
    reader_mode: str | None = None,
    discipline: str | None = None,
    record: Any | None = None,
) -> PaperReaderSession:
    max_context_tokens = DEFAULT_MAX_CONTEXT_TOKENS
    reserved_output_tokens, reserved_scaffold_tokens, page_input_budget = _compute_budget(max_context_tokens)
    if page_input_budget <= 0:
        raise RuntimeError("Paper reader page budget is too small for the configured page budget.")
    target_page_budget = _compute_target_page_budget(page_input_budget)
    target_chunk_budget = _compute_target_chunk_budget(page_input_budget)

    pages = _extract_pdf_pages(pdf_path)
    if not pages:
        raise RuntimeError("PDF text extraction failed or returned no pages.")

    title_hint = None
    abstract_hint = ""
    primary_category: str | None = None
    authors: list[str] = []
    published_date: str | None = None
    if record is not None:
        title_hint = getattr(record, "title", None)
        abstract_hint = normalize_whitespace(getattr(record, "summary", "") or "")
        primary_category = getattr(record, "primary_category", None)
        authors = list(getattr(record, "authors", []) or [])
        published_date = getattr(record, "published_date", None)
        source_id = getattr(record, "arxiv_id", None) or source_id
    paper_title = _normalize_title(title_hint, _session_title_from_pdf(pdf_path, pdf_path.stem))
    resolved_answer_language = _normalize_answer_language(answer_language, paper_title)
    resolved_reader_mode = _normalize_reader_mode(reader_mode)

    blocks = _build_blocks(pages)
    if not blocks:
        raise RuntimeError("No extractable text was found in the PDF. OCR is not supported.")

    raw_chunks = _chunk_blocks(blocks, target_chunk_budget)
    resolved_discipline, discipline_source = _resolve_discipline(
        discipline,
        primary_category=primary_category,
        title=paper_title,
        abstract=abstract_hint,
        chunks=raw_chunks,
    )
    chunks = _assign_reading_focuses(raw_chunks, resolved_discipline)
    if not chunks:
        raise RuntimeError("Failed to build readable chunks from the PDF text.")

    page_plans = _pack_chunks_into_pages(chunks, target_page_budget, resolved_discipline)
    if resolved_reader_mode == "guided":
        quick_story_plan = _build_quick_story_plan(chunks, target_page_budget, resolved_discipline)
        if quick_story_plan is not None:
            page_plans = [quick_story_plan, *page_plans]
            for index, plan in enumerate(page_plans):
                plan.page_index = index
    if not page_plans:
        raise RuntimeError("Failed to build page plans for the paper.")

    index_tree: PaperReaderIndexNode | None = None
    index_status = "fallback"
    try:
        index_tree = _build_paper_index_tree(chunks, page_plans)
        index_status = "ready"
    except Exception:
        index_tree = None

    session = PaperReaderSession(
        session_id=uuid.uuid4().hex,
        source_type=source_type,
        source_url=source_url,
        source_id=source_id,
        paper_title=paper_title,
        authors=authors,
        published_date=published_date,
        answer_language=resolved_answer_language,
        reader_mode=resolved_reader_mode,
        discipline=resolved_discipline,
        discipline_source=discipline_source,
        pdf_path=pdf_path,
        max_context_tokens=max_context_tokens,
        reserved_output_tokens=reserved_output_tokens,
        reserved_scaffold_tokens=reserved_scaffold_tokens,
        page_input_budget=page_input_budget,
        settings=settings,
        chunks=chunks,
        pages=page_plans,
        source_pages=pages,
        index_tree=index_tree,
        index_status=index_status,
        page_statuses={plan.page_index: "ready" for plan in page_plans},
    )
    with _SESSION_LOCK:
        _SESSION_CACHE[session.session_id] = session

    return session


def create_session_from_arxiv(
    url: str,
    settings: RuntimeSettings,
    *,
    answer_language: str | None = None,
    reader_mode: str | None = None,
    discipline: str | None = None,
) -> PaperReaderSession:
    arxiv_id = _parse_arxiv_url(url)
    record = fetch_arxiv_record(arxiv_id)
    if record is None:
        raise RuntimeError("Unable to resolve the requested arXiv paper.")
    session_dir = Path(tempfile.mkdtemp(prefix="paper-reader-"))
    pdf_path = _download_arxiv_pdf(record.arxiv_id or arxiv_id, session_dir, settings.retrieval.request_timeout)
    return _build_session(
        source_type="arxiv",
        source_url=url,
        source_id=record.arxiv_id or arxiv_id,
        pdf_path=pdf_path,
        settings=settings,
        answer_language=answer_language,
        reader_mode=reader_mode,
        discipline=discipline,
        record=record,
    )


def create_session_from_pdf_bytes(
    pdf_bytes: bytes,
    filename: str,
    settings: RuntimeSettings,
    *,
    answer_language: str | None = None,
    reader_mode: str | None = None,
    discipline: str | None = None,
) -> PaperReaderSession:
    if not pdf_bytes:
        raise RuntimeError("Uploaded PDF is empty.")
    if len(pdf_bytes) > 50 * 1024 * 1024:
        raise RuntimeError("Uploaded PDF is too large. The current limit is 50 MB.")
    suffix = ".pdf" if filename.lower().endswith(".pdf") else Path(filename).suffix or ".pdf"
    session_dir = Path(tempfile.mkdtemp(prefix="paper-reader-"))
    pdf_path = session_dir / f"{uuid.uuid4().hex}{suffix}"
    pdf_path.write_bytes(pdf_bytes)
    return _build_session(
        source_type="file",
        source_url=None,
        source_id=filename,
        pdf_path=pdf_path,
        settings=settings,
        answer_language=answer_language,
        reader_mode=reader_mode,
        discipline=discipline,
        record=None,
    )


def get_session(session_id: str) -> PaperReaderSession:
    with _SESSION_LOCK:
        return _get_session(session_id)


def get_session_settings(session_id: str) -> RuntimeSettings:
    with _SESSION_LOCK:
        session = _get_session(session_id)
        return session.settings


def get_session_pdf_path(session_id: str) -> Path:
    with _SESSION_LOCK:
        session = _get_session(session_id)
        _touch_session(session)
        return session.pdf_path


def get_source_page_pdf_path(session_id: str, page_number: int) -> Path:
    with _SESSION_LOCK:
        session = _get_session(session_id)
        resolved_page_number = max(1, int(page_number))
        cached_path = session.source_page_pdf_paths.get(resolved_page_number)
        if cached_path is not None and cached_path.exists():
            _touch_session(session)
            return cached_path

        reader = PdfReader(str(session.pdf_path))
        if resolved_page_number < 1 or resolved_page_number > len(reader.pages):
            raise IndexError("Requested PDF source page is out of range.")
        output_dir = session.pdf_path.parent / "source-page-pdfs"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"page-{resolved_page_number}.pdf"
        writer = PdfWriter()
        writer.add_page(reader.pages[resolved_page_number - 1])
        with output_path.open("wb") as handle:
            writer.write(handle)
        session.source_page_pdf_paths[resolved_page_number] = output_path
        _touch_session(session)
        return output_path


def get_source_pages_for_reader_page(session_id: str, page_index: int) -> PaperReaderSourcePagesResponse:
    with _SESSION_LOCK:
        session = _get_session(session_id)
        if page_index < 0 or page_index >= len(session.pages):
            raise IndexError("Requested page is out of range.")
        plan = session.pages[page_index]
        source_pages = session.source_pages or _extract_pdf_pages(session.pdf_path)
        if not session.source_pages:
            session.source_pages = source_pages
        page_start = plan.page_start or 1
        page_end = plan.page_end or page_start
        selected_page_numbers = [page_number for page_number, _text in source_pages if page_start <= page_number <= page_end]
        missing_layouts = [page_number for page_number in selected_page_numbers if page_number not in session.source_page_layouts]
        if missing_layouts:
            with suppress(Exception):
                reader = PdfReader(str(session.pdf_path))
                for page_number in missing_layouts:
                    if page_number < 1 or page_number > len(reader.pages):
                        continue
                    session.source_page_layouts[page_number] = _extract_pdf_source_page_layout(reader.pages[page_number - 1], page_number)
        text_by_page = {page_number: text for page_number, text in source_pages}
        selected_pages: list[PaperReaderSourcePageModel] = []
        for page_number in selected_page_numbers:
            layout_page = session.source_page_layouts.get(page_number)
            if layout_page is not None:
                if not layout_page.text:
                    layout_page.text = _normalize_multiline_text(text_by_page.get(page_number, ""))
                selected_pages.append(layout_page)
            else:
                selected_pages.append(
                    PaperReaderSourcePageModel(
                        page_number=page_number,
                        text=_normalize_multiline_text(text_by_page.get(page_number, "")),
                    )
                )
        _touch_session(session)

    return PaperReaderSourcePagesResponse(
        session_id=session_id,
        reader_page_index=page_index,
        page_start=page_start,
        page_end=page_end,
        pages=selected_pages,
    )


def get_page_content(session_id: str, page_index: int) -> PaperReaderPageContent:
    with _SESSION_LOCK:
        session = _get_session(session_id)
        if page_index < 0 or page_index >= len(session.pages):
            raise IndexError("Requested page is out of range.")
        content = session.page_contents.get(page_index)
        if content is None:
            plan = session.pages[page_index]
            return PaperReaderPageContent(
                page_index=plan.page_index,
                title=plan.title,
                status=session.page_statuses.get(page_index, "queued"),
                story_stage=_story_stage_for_focus(plan.focus_key, session.answer_language) if session.reader_mode == "guided" else None,
                estimated_tokens=plan.estimated_tokens,
                page_start=plan.page_start,
                page_end=plan.page_end,
                chunk_ids=list(plan.chunk_ids),
                source_node_ids=list(plan.source_node_ids),
            )
        session.current_page_index = page_index
        _touch_session(session)
        return content


def stream_page_content_tokens(session_id: str, page_index: int, settings: RuntimeSettings) -> Iterator[str]:
    result = _generate_page_content_internal(session_id, page_index, settings, stream=True)
    if isinstance(result, Iterator):
        yield from result
    elif isinstance(result, PaperReaderPageContent):
        yield json.dumps(page_content_to_model(result).model_dump(), ensure_ascii=False)


def _chunk_to_model(chunk: PaperReaderChunk, score: float | None = None) -> PaperReaderChunkModel:
    return PaperReaderChunkModel(
        chunk_id=chunk.chunk_id,
        section_title=chunk.section_title,
        subsection_title=chunk.subsection_title,
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        text=chunk.text,
        token_estimate=chunk.token_estimate,
        score=score,
    )


def _chunk_to_citation(chunk: PaperReaderChunk, score: float | None = None) -> PaperReaderCitationModel:
    return PaperReaderCitationModel(
        chunk_id=chunk.chunk_id,
        section_title=chunk.section_title,
        subsection_title=chunk.subsection_title,
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        excerpt=chunk.text[:240],
        score=score,
    )


def chat_with_paper(
    session_id: str,
    request: PaperReaderChatRequest,
    settings: RuntimeSettings,
) -> PaperReaderChatResponse:
    with _SESSION_LOCK:
        session = _get_session(session_id)
        page_index = request.page_index if request.page_index is not None else session.current_page_index
        plan, selected_chunks, selected_nodes = _select_chat_chunks(session, page_index, request, settings)
        session.current_page_index = page_index
        _touch_session(session)

    chat_config = _default_paper_reader_chat_config(settings)
    messages = _build_chat_messages(session, plan, request, selected_chunks, selected_nodes)
    raw_text = chat_completion(messages, chat_config, settings.retrieval.request_timeout)
    answer_language = _normalize_answer_language(request.answer_language, session.paper_title) or session.answer_language
    fallback_original = _clip_original_excerpt(selected_chunks[0].text) if selected_chunks else ""

    parsed, _repair_attempted = _extract_structured_json_object(raw_text)
    if parsed is None:
        parsed = {}

    answer_text = _ensure_reader_block_text(parsed.get("answer_text"), answer_language, fallback_original)
    if not answer_text:
        answer_text = _ensure_reader_block_text(_safe_chat_error_message(answer_language), answer_language, fallback_original) or ""
    citations = []
    raw_citations = parsed.get("citations") if isinstance(parsed.get("citations"), list) else []
    citation_lookup = {chunk.chunk_id: chunk for chunk in selected_chunks}
    for item in raw_citations:
        if not isinstance(item, dict):
            continue
        chunk_id = str(item.get("chunk_id") or "").strip()
        chunk = citation_lookup.get(chunk_id)
        citations.append(
            PaperReaderCitationModel(
                chunk_id=chunk_id or uuid.uuid4().hex,
                section_title=_normalize_title(item.get("section_title"), chunk.section_title if chunk else plan.section_title),
                subsection_title=(str(item.get("subsection_title")).strip() or None)
                if item.get("subsection_title") is not None
                else (chunk.subsection_title if chunk else None),
                page_start=int(item.get("page_start") or (chunk.page_start if chunk else plan.page_start)),
                page_end=int(item.get("page_end") or (chunk.page_end if chunk else plan.page_end)),
                excerpt=(str(item.get("excerpt")).strip() or None) if item.get("excerpt") is not None else (chunk.text[:240] if chunk else None),
                score=float(item["score"]) if isinstance(item.get("score"), (float, int)) else None,
            )
        )
    if not citations:
        citations = [_chunk_to_citation(chunk) for chunk in selected_chunks[:4]]

    used_chunks_raw = parsed.get("used_chunks") if isinstance(parsed.get("used_chunks"), list) else []
    used_chunks: list[PaperReaderChunkModel] = []
    used_lookup = {chunk.chunk_id: chunk for chunk in selected_chunks}
    for item in used_chunks_raw:
        if not isinstance(item, dict):
            continue
        chunk_id = str(item.get("chunk_id") or "").strip()
        chunk = used_lookup.get(chunk_id)
        if chunk is None:
            continue
        used_chunks.append(
            PaperReaderChunkModel(
                chunk_id=chunk.chunk_id,
                section_title=chunk.section_title,
                subsection_title=chunk.subsection_title,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                text=chunk.text,
                token_estimate=chunk.token_estimate,
                score=float(item["score"]) if isinstance(item.get("score"), (float, int)) else None,
            )
        )
    if not used_chunks:
        used_chunks = [_chunk_to_model(chunk) for chunk in selected_chunks[:6]]

    return PaperReaderChatResponse(
        session_id=session_id,
        page_index=plan.page_index,
        page_title=plan.title,
        answer_text=answer_text,
        citations=citations,
        used_chunks=used_chunks,
        selected_nodes=selected_nodes,
    )


def session_to_model(session: PaperReaderSession) -> PaperReaderSessionModel:
    pages = [
        PaperReaderPageManifestModel(
            page_index=plan.page_index,
            title=plan.title,
            status=session.page_statuses.get(plan.page_index, "queued"),
            estimated_tokens=plan.estimated_tokens,
            chunk_count=len(plan.chunk_ids),
            page_start=plan.page_start,
            page_end=plan.page_end,
            source_node_ids=list(plan.source_node_ids),
        )
        for plan in session.pages
    ]
    return PaperReaderSessionModel(
        session_id=session.session_id,
        source_type=session.source_type,
        source_url=session.source_url,
        source_id=session.source_id,
        paper_title=session.paper_title,
        authors=list(session.authors),
        published_date=session.published_date,
        answer_language=_normalize_answer_language(session.answer_language, session.paper_title),
        reader_mode=_normalize_reader_mode(session.reader_mode),
        discipline=_normalize_discipline(session.discipline),
        discipline_source="manual" if session.discipline_source == "manual" else "auto",
        max_context_tokens=session.max_context_tokens,
        page_input_budget=session.page_input_budget,
        current_page_index=session.current_page_index,
        page_count=len(session.pages),
        session_status=session.session_status,
        pages=pages,
        index_status="ready" if session.index_tree is not None and session.index_status == "ready" else "fallback",
        index_tree=_index_node_to_model(session.index_tree) if session.index_tree is not None else None,
    )


def page_content_to_model(content: PaperReaderPageContent) -> PaperReaderPageContentModel:
    return PaperReaderPageContentModel(
        page_index=content.page_index,
        title=content.title,
        status=content.status,
        coverage=content.coverage,
        page_overview=content.page_overview,
        insights=list(content.insights),
        structured_status=content.structured_status,
        reading_blocks=_localized_reading_blocks(list(content.reading_blocks)),
        source_sections=list(content.source_sections),
        mentor_script=list(content.mentor_script),
        blackboard_notes=content.blackboard_notes,
        discipline_guide=content.discipline_guide,
        story_stage=content.story_stage,
        glossary_terms=list(content.glossary_terms),
        reading_hints=list(content.reading_hints),
        checkpoints=list(content.checkpoints),
        summary=content.summary,
        sections=list(content.sections),
        key_points=list(content.key_points),
        limitations=list(content.limitations),
        citations=list(content.citations),
        chunk_ids=list(content.chunk_ids),
        source_node_ids=list(content.source_node_ids),
        estimated_tokens=content.estimated_tokens,
        page_start=content.page_start,
        page_end=content.page_end,
        generated_at=content.generated_at,
        error=content.error_message,
    )
