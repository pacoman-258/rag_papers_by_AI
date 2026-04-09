from __future__ import annotations

import json
import os
import re
from calendar import monthrange
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any, Iterator

import psycopg2
import requests

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


if load_dotenv is not None:
    load_dotenv()


DEFAULT_DB_CONFIG = {
    "dbname": os.getenv("PAPER_DB_NAME", "pacoman"),
    "user": os.getenv("PAPER_DB_USER", "pacoman"),
    "password": os.getenv("PAPER_DB_PASSWORD", "114514"),
    "host": os.getenv("PAPER_DB_HOST", "localhost"),
    "port": os.getenv("PAPER_DB_PORT", "5433"),
}

_PRIMARY_CATEGORY_COLUMN_CACHE: dict[str, bool] = {}


@dataclass(slots=True)
class ChatConfig:
    provider: str
    model: str
    base_url: str | None = None
    api_key: str | None = None


@dataclass(slots=True)
class EmbeddingConfig:
    api_url: str
    model: str


@dataclass(slots=True)
class RetrievalConfig:
    top_k: int
    top_n: int
    request_timeout: int


@dataclass(slots=True)
class RerankConfig:
    base_url: str
    model: str
    api_key: str | None = None


@dataclass(slots=True)
class RuntimeSettings:
    query_chat: ChatConfig
    answer_chat: ChatConfig
    embedding: EmbeddingConfig
    retrieval: RetrievalConfig
    rerank: RerankConfig


@dataclass(slots=True)
class RetrievalConstraints:
    published_after: str | None = None
    published_before: str | None = None
    authors: list[str] = field(default_factory=list)
    primary_categories: list[str] = field(default_factory=list)
    sort_hint: str = "relevance"
    is_implicit_latest: bool = False


@dataclass(slots=True)
class QueryPlan:
    answer_language: str
    intent_summary: str
    retrieval_query_en: str
    keywords_en: list[str]
    constraints: RetrievalConstraints = field(default_factory=RetrievalConstraints)
    corpus_latest_date: str | None = None


@dataclass(slots=True)
class RetrievedPaper:
    id: str
    title: str
    text: str
    method: str
    initial_score: float
    authors: list[str] = field(default_factory=list)
    published_date: str | None = None
    primary_category: str | None = None


@dataclass(slots=True)
class RankedPaper(RetrievedPaper):
    rerank_score: float = 0.0


@dataclass(slots=True)
class SearchExecution:
    original_query: str
    retrieval_text: str
    answer_language: str
    query_plan: QueryPlan | None
    papers: list[RankedPaper]
    answer_prompt: str
    warnings: list[str]
    applied_constraints: RetrievalConstraints
    corpus_latest_date: str | None = None


@dataclass(slots=True)
class TargetPaper:
    id: str
    arxiv_id: str
    title: str
    summary: str
    authors: list[str] = field(default_factory=list)
    published_date: str | None = None
    primary_category: str | None = None


@dataclass(slots=True)
class TraceExecution:
    target_paper: TargetPaper
    retrieval_text: str
    answer_language: str
    papers: list[RankedPaper]
    answer_prompt: str
    warnings: list[str]


def normalize_provider(value: str) -> str:
    provider = value.strip().lower()
    if provider not in {"ollama", "openai_compatible"}:
        raise ValueError(f"Unsupported provider: {value}")
    return provider


def infer_user_language(text: str) -> str:
    return "zh" if re.search(r"[\u4e00-\u9fff]", text) else "en"


def normalize_ollama_api_url(base_url: str | None) -> str:
    normalized = (base_url or "http://localhost:11434/api").rstrip("/")
    if normalized.endswith("/api"):
        return normalized
    return f"{normalized}/api"


def get_env_default_settings() -> RuntimeSettings:
    embedding_api_url = normalize_ollama_api_url(os.getenv("OLLAMA_API_URL", "http://localhost:11434/api"))
    answer_chat = ChatConfig(
        provider=normalize_provider(os.getenv("ANSWER_CHAT_PROVIDER", "ollama")),
        model=os.getenv("ANSWER_CHAT_MODEL", "qwen3:8b"),
        base_url=os.getenv("ANSWER_CHAT_BASE_URL", embedding_api_url),
        api_key=os.getenv("ANSWER_CHAT_API_KEY"),
    )
    query_chat = ChatConfig(
        provider=normalize_provider(os.getenv("QUERY_CHAT_PROVIDER", answer_chat.provider)),
        model=os.getenv("QUERY_CHAT_MODEL", answer_chat.model),
        base_url=os.getenv("QUERY_CHAT_BASE_URL", answer_chat.base_url),
        api_key=os.getenv("QUERY_CHAT_API_KEY", answer_chat.api_key),
    )
    return RuntimeSettings(
        query_chat=query_chat,
        answer_chat=answer_chat,
        embedding=EmbeddingConfig(
            api_url=embedding_api_url,
            model=os.getenv("OLLAMA_EMBED_MODEL", "qwen3-embedding:0.6b"),
        ),
        retrieval=RetrievalConfig(
            top_k=int(os.getenv("TOP_K_RETRIEVAL", "50")),
            top_n=int(os.getenv("TOP_N_RERANK", "10")),
            request_timeout=int(os.getenv("SEARCH_REQUEST_TIMEOUT", "120")),
        ),
        rerank=RerankConfig(
            base_url=os.getenv("RERANK_BASE_URL", "https://api.siliconflow.cn/v1").rstrip("/"),
            model=os.getenv("RERANK_MODEL", "BAAI/bge-reranker-v2-m3"),
            api_key=os.getenv("RERANK_API_KEY"),
        ),
    )


def validate_chat_config(config: ChatConfig, label: str) -> None:
    if config.provider != "openai_compatible":
        return
    missing: list[str] = []
    if not config.model:
        missing.append("model")
    if not config.base_url:
        missing.append("base_url")
    if not config.api_key:
        missing.append("api_key")
    if missing:
        raise RuntimeError(f"Missing {label} settings: {', '.join(missing)}")


def validate_runtime_settings(settings: RuntimeSettings) -> None:
    validate_chat_config(settings.query_chat, "query_chat")
    validate_chat_config(settings.answer_chat, "answer_chat")
    if not settings.embedding.api_url:
        raise RuntimeError("Missing embedding.api_url")
    if not settings.embedding.model:
        raise RuntimeError("Missing embedding.model")
    if settings.retrieval.top_k <= 0 or settings.retrieval.top_n <= 0:
        raise RuntimeError("Retrieval top_k and top_n must be positive.")


def serialize_runtime_settings(settings: RuntimeSettings) -> dict[str, Any]:
    return asdict(settings)


def extract_first_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL)
    if fenced_match:
        return json.loads(fenced_match.group(1))

    decoder = json.JSONDecoder()
    for index, char in enumerate(stripped):
        if char != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise ValueError("No JSON object found in model output.")


def normalize_keyword_list(raw_keywords: Any) -> list[str]:
    if isinstance(raw_keywords, str):
        items = re.split(r"[,\n;]+", raw_keywords)
    elif isinstance(raw_keywords, list):
        items = [str(item) for item in raw_keywords]
    else:
        items = []

    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        keyword = " ".join(item.split()).strip()
        if not keyword:
            continue
        lowered = keyword.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(keyword)
    return normalized


def normalize_name_list(raw_items: Any) -> list[str]:
    if isinstance(raw_items, str):
        items = re.split(r"[,\n;]+", raw_items)
    elif isinstance(raw_items, list):
        items = [str(item) for item in raw_items]
    else:
        items = []

    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = " ".join(item.split()).strip()
        if not value:
            continue
        lowered = value.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(value)
    return normalized


def normalize_category_list(raw_items: Any) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in normalize_name_list(raw_items):
        compact = item.replace(" ", "")
        if "." in compact:
            major, minor = compact.split(".", 1)
            category = f"{major.lower()}.{minor.upper()}"
        else:
            category = compact.lower()
        lowered = category.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(category)
    return normalized


def parse_iso_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    if "T" in text:
        text = text.split("T", 1)[0]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def shift_months(anchor: date, delta_months: int) -> date:
    month_index = anchor.year * 12 + (anchor.month - 1) + delta_months
    year = month_index // 12
    month = month_index % 12 + 1
    day = min(anchor.day, monthrange(year, month)[1])
    return date(year, month, day)


def has_recent_intent(text: str) -> bool:
    lowered = text.lower()
    english_patterns = ("latest", "recent", "newest", "most recent", "current", "up-to-date")
    chinese_patterns = ("最新", "最近", "近期", "近一年", "近两年", "近三年", "近半年")
    return any(pattern in lowered for pattern in english_patterns) or any(pattern in text for pattern in chinese_patterns)


def clone_constraints(constraints: RetrievalConstraints | None) -> RetrievalConstraints:
    if constraints is None:
        return RetrievalConstraints()
    return RetrievalConstraints(
        published_after=constraints.published_after,
        published_before=constraints.published_before,
        authors=list(constraints.authors),
        primary_categories=list(constraints.primary_categories),
        sort_hint=constraints.sort_hint,
        is_implicit_latest=constraints.is_implicit_latest,
    )


def normalize_sort_hint(raw_value: Any, original_query: str) -> str:
    if isinstance(raw_value, str):
        candidate = raw_value.strip().lower()
        if candidate in {"relevance", "latest"}:
            return candidate
    return "latest" if has_recent_intent(original_query) else "relevance"


def format_constraints_summary(constraints: RetrievalConstraints, empty_text: str = "(none)") -> dict[str, str]:
    if constraints.published_after and constraints.published_before:
        time_window = f"{constraints.published_after} to {constraints.published_before}"
    elif constraints.published_after:
        time_window = f"after {constraints.published_after}"
    elif constraints.published_before:
        time_window = f"before {constraints.published_before}"
    else:
        time_window = empty_text

    return {
        "time_window": time_window,
        "authors": ", ".join(constraints.authors) if constraints.authors else empty_text,
        "categories": ", ".join(constraints.primary_categories) if constraints.primary_categories else empty_text,
        "sort_hint": constraints.sort_hint,
    }


def coerce_constraints(raw_constraints: Any, original_query: str, corpus_latest_date: str | None) -> RetrievalConstraints:
    data = raw_constraints if isinstance(raw_constraints, dict) else {}
    published_after = parse_iso_date(data.get("published_after"))
    published_before = parse_iso_date(data.get("published_before"))
    authors = normalize_name_list(data.get("authors"))
    primary_categories = normalize_category_list(data.get("primary_categories"))
    sort_hint = normalize_sort_hint(data.get("sort_hint"), original_query)
    has_explicit_time_range = published_after is not None or published_before is not None
    is_implicit_latest = bool(data.get("is_implicit_latest")) and not has_explicit_time_range

    if not is_implicit_latest and sort_hint == "latest" and has_recent_intent(original_query) and not has_explicit_time_range:
        is_implicit_latest = True

    corpus_date = parse_iso_date(corpus_latest_date)
    if is_implicit_latest and corpus_date is not None:
        published_before = published_before or corpus_date
        published_after = published_after or shift_months(published_before, -12)

    return RetrievalConstraints(
        published_after=published_after.isoformat() if published_after else None,
        published_before=published_before.isoformat() if published_before else None,
        authors=authors,
        primary_categories=primary_categories,
        sort_hint=sort_hint,
        is_implicit_latest=is_implicit_latest,
    )


def coerce_query_plan(
    raw_data: dict[str, Any],
    original_query: str,
    corpus_latest_date: str | None = None,
) -> QueryPlan:
    answer_language = str(raw_data.get("answer_language", "")).strip().lower()
    if answer_language not in {"zh", "en"}:
        answer_language = infer_user_language(original_query)

    intent_summary = " ".join(str(raw_data.get("intent_summary", "")).split()).strip()
    if not intent_summary:
        intent_summary = original_query

    retrieval_query_en = " ".join(str(raw_data.get("retrieval_query_en", "")).split()).strip()
    if not retrieval_query_en:
        retrieval_query_en = original_query

    resolved_corpus_latest_date = (
        parse_iso_date(raw_data.get("corpus_latest_date")).isoformat()
        if parse_iso_date(raw_data.get("corpus_latest_date"))
        else corpus_latest_date
    )

    return QueryPlan(
        answer_language=answer_language,
        intent_summary=intent_summary,
        retrieval_query_en=retrieval_query_en,
        keywords_en=normalize_keyword_list(raw_data.get("keywords_en")),
        constraints=coerce_constraints(raw_data.get("constraints"), original_query, resolved_corpus_latest_date),
        corpus_latest_date=resolved_corpus_latest_date,
    )


def normalize_openai_message_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                text = part.get("text") or part.get("content")
            else:
                text = getattr(part, "text", None)
            if text:
                parts.append(str(text))
        return "".join(parts)
    return ""


def create_openai_client(config: ChatConfig, timeout: int):
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("openai package is required for openai_compatible provider.") from exc

    return OpenAI(base_url=config.base_url, api_key=config.api_key, timeout=timeout)


def chat_completion(messages: list[dict[str, str]], config: ChatConfig, timeout: int) -> str:
    if config.provider == "ollama":
        ollama_base_url = normalize_ollama_api_url(config.base_url or get_env_default_settings().embedding.api_url)
        response = requests.post(
            f"{ollama_base_url}/chat",
            json={"model": config.model, "messages": messages, "stream": False},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            raise RuntimeError(payload["error"])
        content = payload.get("message", {}).get("content", "")
        if not content:
            raise RuntimeError("Ollama returned an empty chat response.")
        return content

    client = create_openai_client(config, timeout)
    response = client.chat.completions.create(
        model=config.model,
        messages=messages,
        temperature=0.2,
        stream=False,
    )
    if not response.choices:
        raise RuntimeError("Chat API returned no choices.")
    content = normalize_openai_message_content(response.choices[0].message.content)
    if not content:
        raise RuntimeError("Chat API returned an empty response.")
    return content


def stream_chat_tokens(
    messages: list[dict[str, str]],
    config: ChatConfig,
    timeout: int,
    ollama_api_url: str,
) -> Iterator[str]:
    if config.provider == "ollama":
        ollama_base_url = normalize_ollama_api_url(config.base_url or ollama_api_url)
        with requests.post(
            f"{ollama_base_url}/chat",
            json={"model": config.model, "messages": messages, "stream": True},
            stream=True,
            timeout=timeout,
        ) as response:
            response.raise_for_status()
            for raw_line in response.iter_lines():
                if not raw_line:
                    continue
                chunk = json.loads(raw_line)
                if chunk.get("error"):
                    raise RuntimeError(chunk["error"])
                content = chunk.get("message", {}).get("content", "")
                if content:
                    yield content
        return

    client = create_openai_client(config, timeout)
    stream = client.chat.completions.create(
        model=config.model,
        messages=messages,
        temperature=0.2,
        stream=True,
    )
    for chunk in stream:
        if not chunk.choices:
            continue
        content = normalize_openai_message_content(getattr(chunk.choices[0].delta, "content", ""))
        if content:
            yield content


def get_embedding(text: str, settings: RuntimeSettings) -> list[float]:
    if not text.strip():
        raise ValueError("Query text is empty.")
    embedding_api_url = normalize_ollama_api_url(settings.embedding.api_url)
    response = requests.post(
        f"{embedding_api_url}/embeddings",
        json={"model": settings.embedding.model, "prompt": text.replace("\n", " ")},
        timeout=settings.retrieval.request_timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("error"):
        raise RuntimeError(payload["error"])
    embedding = payload.get("embedding")
    if not embedding:
        raise RuntimeError("Embedding API returned no vector.")
    return embedding


def get_db_signature(db_config: dict[str, str] | None = None) -> str:
    config = db_config or DEFAULT_DB_CONFIG
    return "|".join(str(config[key]) for key in ("host", "port", "dbname", "user"))


def has_primary_category_column(db_config: dict[str, str] | None = None) -> bool:
    signature = get_db_signature(db_config)
    cached = _PRIMARY_CATEGORY_COLUMN_CACHE.get(signature)
    if cached is not None:
        return cached

    conn = psycopg2.connect(**(db_config or DEFAULT_DB_CONFIG))
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'papers_meta'
                    AND column_name = 'primary_category'
                );
                """
            )
            exists = bool(cursor.fetchone()[0])
    finally:
        conn.close()

    _PRIMARY_CATEGORY_COLUMN_CACHE[signature] = exists
    return exists


def get_primary_category_sql(db_config: dict[str, str] | None = None) -> str:
    if has_primary_category_column(db_config):
        return "COALESCE(NULLIF(m.primary_category, ''), m.extracted_insights->>'primary_category')"
    return "(m.extracted_insights->>'primary_category')"


def get_corpus_latest_date(db_config: dict[str, str] | None = None) -> str | None:
    conn = psycopg2.connect(**(db_config or DEFAULT_DB_CONFIG))
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT MAX(published_date) FROM papers_meta;")
            latest = cursor.fetchone()[0]
    finally:
        conn.close()
    return latest.isoformat() if latest else None


def safe_get_corpus_latest_date(db_config: dict[str, str] | None = None) -> str | None:
    try:
        return get_corpus_latest_date(db_config)
    except Exception:
        return None


ARXIV_QUERY_PATTERN = re.compile(r"^(?:arxiv:)?(?P<base>\d{4}\.\d{4,5})(?:v(?P<version>\d+))?$", re.IGNORECASE)


def has_recent_intent(text: str) -> bool:
    lowered = text.lower()
    english_patterns = ("latest", "recent", "newest", "most recent", "current", "up-to-date")
    chinese_patterns = ("最新", "最近", "近期", "近一年", "近两年", "近三年", "近半年")
    return any(pattern in lowered for pattern in english_patterns) or any(pattern in text for pattern in chinese_patterns)


def normalize_whitespace(text: str) -> str:
    return " ".join(text.split()).strip()


def parse_arxiv_query(query: str) -> tuple[str, int | None] | None:
    match = ARXIV_QUERY_PATTERN.match(query.strip())
    if match is None:
        return None
    version = match.group("version")
    return match.group("base"), int(version) if version is not None else None


def extract_arxiv_base_id(arxiv_id: str | None) -> str | None:
    if not arxiv_id:
        return None
    parsed = parse_arxiv_query(arxiv_id.strip())
    if parsed is not None:
        return parsed[0]
    return arxiv_id.strip().split("v", 1)[0]


def build_target_paper_select_sql(db_config: dict[str, str] | None = None) -> str:
    category_sql = get_primary_category_sql(db_config)
    return f"""
        SELECT
            m.id,
            m.arxiv_id,
            m.title,
            COALESCE(
                m.extracted_insights->>'summary',
                m.extracted_insights->>'summary_for_embedding',
                m.title
            ) AS summary_text,
            COALESCE(m.authors, ARRAY[]::text[]),
            m.published_date,
            {category_sql} AS primary_category
        FROM papers_meta AS m
    """


def target_paper_from_row(row: tuple[Any, ...]) -> TargetPaper:
    return TargetPaper(
        id=str(row[0]),
        arxiv_id=row[1],
        title=row[2],
        summary=row[3] or row[2] or "",
        authors=list(row[4] or []),
        published_date=row[5].isoformat() if row[5] else None,
        primary_category=row[6] or None,
    )


def fetch_target_papers(sql_suffix: str, params: tuple[Any, ...], db_config: dict[str, str] | None = None) -> list[TargetPaper]:
    conn = psycopg2.connect(**(db_config or DEFAULT_DB_CONFIG))
    try:
        with conn.cursor() as cursor:
            cursor.execute(build_target_paper_select_sql(db_config) + "\n" + sql_suffix, params)
            rows = cursor.fetchall()
    finally:
        conn.close()
    return [target_paper_from_row(row) for row in rows]


def fetch_target_paper_by_id(paper_id: str, db_config: dict[str, str] | None = None) -> TargetPaper | None:
    papers = fetch_target_papers("WHERE m.id = %s::uuid LIMIT 1", (paper_id,), db_config=db_config)
    return papers[0] if papers else None


def find_target_candidates(query: str, limit: int = 5, db_config: dict[str, str] | None = None) -> list[TargetPaper]:
    normalized_query = normalize_whitespace(query)
    if not normalized_query:
        return []

    arxiv_parts = parse_arxiv_query(normalized_query)
    if arxiv_parts is not None:
        base_id, version = arxiv_parts
        if version is not None:
            exact = fetch_target_papers(
                "WHERE lower(m.arxiv_id) = lower(%s) LIMIT 1",
                (normalized_query,),
                db_config=db_config,
            )
            if exact:
                return exact
        return fetch_target_papers(
            """
            WHERE lower(split_part(m.arxiv_id, 'v', 1)) = lower(%s)
            ORDER BY
                COALESCE((regexp_match(lower(m.arxiv_id), 'v([0-9]+)$'))[1]::int, 0) DESC,
                m.published_date DESC NULLS LAST
            LIMIT %s
            """,
            (base_id, limit),
            db_config=db_config,
        )

    exact_title_matches = fetch_target_papers(
        """
        WHERE lower(m.title) = lower(%s)
        ORDER BY m.published_date DESC NULLS LAST, m.id
        LIMIT %s
        """,
        (normalized_query, limit),
        db_config=db_config,
    )
    if exact_title_matches:
        return exact_title_matches

    like_query = f"%{normalized_query}%"
    return fetch_target_papers(
        """
        WHERE m.title ILIKE %s
        ORDER BY
            CASE
                WHEN lower(m.title) LIKE lower(%s) || '%%' THEN 0
                ELSE 1
            END,
            m.published_date DESC NULLS LAST,
            m.id
        LIMIT %s
        """,
        (like_query, normalized_query, limit),
        db_config=db_config,
    )


def resolve_target_paper(
    query: str,
    db_config: dict[str, str] | None = None,
) -> tuple[str, TargetPaper | None, list[TargetPaper], str | None]:
    normalized_query = normalize_whitespace(query)
    if not normalized_query:
        return "not_found", None, [], "Target paper query is empty."

    arxiv_parts = parse_arxiv_query(normalized_query)
    candidates = find_target_candidates(normalized_query, db_config=db_config)
    if not candidates:
        return "not_found", None, [], "No target paper was found for the given arXiv ID or title."

    if arxiv_parts is not None:
        return "resolved", candidates[0], candidates, None

    exact_matches = [paper for paper in candidates if paper.title.casefold() == normalized_query.casefold()]
    if len(exact_matches) == 1:
        return "resolved", exact_matches[0], exact_matches, None
    if len(exact_matches) > 1:
        return "ambiguous", None, exact_matches[:5], "Multiple papers share this title. Please choose the target paper."

    return "ambiguous", None, candidates[:5], "Multiple similar titles were found. Please choose the target paper."


def build_planning_messages(
    original_query: str,
    corpus_latest_date: str | None,
    previous_plan: QueryPlan | None = None,
    user_feedback: str | None = None,
) -> list[dict[str, str]]:
    system_prompt = f"""
You optimize user questions for semantic retrieval over an English arXiv paper database about Retrieval-Augmented Generation.
Return only one JSON object with this exact shape:
{{
  "answer_language": "zh" or "en",
  "intent_summary": "brief summary",
  "retrieval_query_en": "one concise English retrieval sentence",
  "keywords_en": ["keyword 1", "keyword 2"],
  "constraints": {{
    "published_after": "YYYY-MM-DD or null",
    "published_before": "YYYY-MM-DD or null",
    "authors": ["full author name"],
    "primary_categories": ["cs.CL"],
    "sort_hint": "relevance" or "latest",
    "is_implicit_latest": true or false
  }}
}}

Rules:
- The paper database is English. retrieval_query_en and keywords_en must be English.
- Preserve the user's technical meaning.
- Only add author filters if the user explicitly names an author.
- Only add category filters if the user explicitly names arXiv categories or clearly implies a primary category.
- If the user gives an absolute date or year range, convert it to absolute ISO dates.
- If the user gives a relative time like "last 6 months" or "近一年", convert it to absolute ISO dates relative to the corpus latest date.
- If the user asks for "latest" or "recent" without a concrete window, use a 12-month window ending at the corpus latest date, set sort_hint to "latest", and set is_implicit_latest to true.
- If you cannot determine a time range, keep the published_* fields null.
- If corpus latest date is unknown, keep time fields null unless the user gave absolute dates.
- Do not output markdown, explanations, or code fences.

Corpus latest indexed publication date: {corpus_latest_date or "unknown"}
""".strip()

    user_sections = [f"Original user question:\n{original_query}"]
    if previous_plan is not None:
        user_sections.append(
            "Previous query plan JSON:\n" + json.dumps(asdict(previous_plan), ensure_ascii=False, indent=2)
        )
    if user_feedback:
        user_sections.append(f"User feedback for improvement:\n{user_feedback}")
    user_sections.append("Return only the JSON object.")
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "\n\n".join(user_sections)},
    ]


def build_planning_messages(
    original_query: str,
    corpus_latest_date: str | None,
    previous_plan: QueryPlan | None = None,
    user_feedback: str | None = None,
) -> list[dict[str, str]]:
    system_prompt = f"""
You optimize user questions for semantic retrieval over an English arXiv paper database about Retrieval-Augmented Generation.
Return only one JSON object with this exact shape:
{{
  "answer_language": "zh" or "en",
  "intent_summary": "brief summary",
  "retrieval_query_en": "one concise English retrieval sentence",
  "keywords_en": ["keyword 1", "keyword 2"],
  "constraints": {{
    "published_after": "YYYY-MM-DD or null",
    "published_before": "YYYY-MM-DD or null",
    "authors": ["full author name"],
    "primary_categories": ["cs.CL"],
    "sort_hint": "relevance" or "latest",
    "is_implicit_latest": true or false
  }}
}}

Rules:
- The paper database is English. retrieval_query_en and keywords_en must be English.
- Preserve the user's technical meaning.
- Only add author filters if the user explicitly names an author.
- Only add category filters if the user explicitly names arXiv categories or clearly implies a primary category.
- If the user gives an absolute date or year range, convert it to absolute ISO dates.
- If the user gives a relative time like "last 6 months" or "近一年", convert it to absolute ISO dates relative to the corpus latest date.
- If the user asks for "latest" or "recent" without a concrete window, use a 12-month window ending at the corpus latest date, set sort_hint to "latest", and set is_implicit_latest to true.
- If you cannot determine a time range, keep the published_* fields null.
- If corpus latest date is unknown, keep time fields null unless the user gave absolute dates.
- Do not output markdown, explanations, or code fences.

Corpus latest indexed publication date: {corpus_latest_date or "unknown"}
""".strip()

    user_sections = [f"Original user question:\n{original_query}"]
    if previous_plan is not None:
        user_sections.append(
            "Previous query plan JSON:\n" + json.dumps(asdict(previous_plan), ensure_ascii=False, indent=2)
        )
    if user_feedback:
        user_sections.append(f"User feedback for improvement:\n{user_feedback}")
    user_sections.append("Return only the JSON object.")
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "\n\n".join(user_sections)},
    ]


def plan_query(
    original_query: str,
    settings: RuntimeSettings,
    db_config: dict[str, str] | None = None,
) -> QueryPlan:
    corpus_latest_date = safe_get_corpus_latest_date(db_config)
    content = chat_completion(
        build_planning_messages(original_query, corpus_latest_date),
        settings.query_chat,
        settings.retrieval.request_timeout,
    )
    return coerce_query_plan(extract_first_json_object(content), original_query, corpus_latest_date)


def revise_query_plan(
    original_query: str,
    previous_plan: QueryPlan,
    feedback: str,
    settings: RuntimeSettings,
    db_config: dict[str, str] | None = None,
) -> QueryPlan:
    corpus_latest_date = previous_plan.corpus_latest_date or safe_get_corpus_latest_date(db_config)
    content = chat_completion(
        build_planning_messages(
            original_query,
            corpus_latest_date,
            previous_plan=previous_plan,
            user_feedback=feedback,
        ),
        settings.query_chat,
        settings.retrieval.request_timeout,
    )
    return coerce_query_plan(extract_first_json_object(content), original_query, corpus_latest_date)


def build_retrieval_text(plan: QueryPlan) -> str:
    if not plan.keywords_en:
        return plan.retrieval_query_en
    return f"{plan.retrieval_query_en}; keywords: {', '.join(plan.keywords_en)}"


def build_trace_retrieval_text(target_paper: TargetPaper) -> str:
    summary = normalize_whitespace(target_paper.summary)
    if summary:
        return f"{target_paper.title}. {summary}"
    return target_paper.title


def build_trace_rerank_query(target_paper: TargetPaper) -> str:
    return (
        "Most important prior papers for this target paper. "
        "Focus on foundational methods, problem framing, and techniques the target paper likely builds on.\n"
        f"Target paper title: {target_paper.title}\n"
        f"Target paper published date: {target_paper.published_date or 'Unknown'}\n"
        f"Target paper category: {target_paper.primary_category or 'Unknown'}\n"
        f"Target paper summary: {target_paper.summary}"
    )


def embedding_to_vector_literal(query_vec: list[float]) -> str:
    return json.dumps(query_vec, separators=(",", ":"))


def vector_search_top_k(
    query_vec: list[float],
    limit: int,
    constraints: RetrievalConstraints | None = None,
    db_config: dict[str, str] | None = None,
) -> list[RetrievedPaper]:
    active_constraints = clone_constraints(constraints)
    category_sql = get_primary_category_sql(db_config)
    where_clauses: list[str] = []
    params: list[Any] = [embedding_to_vector_literal(query_vec)]

    if active_constraints.published_after:
        where_clauses.append("m.published_date >= %s")
        params.append(active_constraints.published_after)
    if active_constraints.published_before:
        where_clauses.append("m.published_date <= %s")
        params.append(active_constraints.published_before)
    if active_constraints.primary_categories:
        where_clauses.append(f"{category_sql} = ANY(%s)")
        params.append(active_constraints.primary_categories)
    if active_constraints.authors:
        author_values = [author.lower().strip() for author in active_constraints.authors]
        where_clauses.append(
            """
            EXISTS (
                SELECT 1
                FROM unnest(COALESCE(m.authors, ARRAY[]::text[])) AS author_name
                WHERE lower(trim(author_name)) = ANY(%s)
            )
            """
        )
        params.append(author_values)

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(clause.strip() for clause in where_clauses)

    sql = f"""
        SELECT
            m.id,
            m.title,
            COALESCE(
                m.extracted_insights->>'summary_for_embedding',
                m.extracted_insights->>'summary',
                m.title
            ) AS summary_text,
            COALESCE(
                m.extracted_insights->>'methodology',
                m.extracted_insights->>'summary',
                ''
            ) AS methodology_text,
            1 - (e.embedding <=> %s::vector) AS similarity,
            COALESCE(m.authors, ARRAY[]::text[]),
            m.published_date,
            {category_sql} AS primary_category
        FROM papers_embeddings AS e
        JOIN papers_meta AS m ON e.paper_id = m.id
        {where_sql}
        ORDER BY e.embedding <=> %s::vector
        LIMIT %s;
    """
    params.extend([embedding_to_vector_literal(query_vec), limit])

    conn = psycopg2.connect(**(db_config or DEFAULT_DB_CONFIG))
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
    finally:
        conn.close()

    papers: list[RetrievedPaper] = []
    for row in rows:
        papers.append(
            RetrievedPaper(
                id=str(row[0]),
                title=row[1],
                text=row[2] or row[1] or "No summary available.",
                method=row[3] or "Not provided.",
                initial_score=float(row[4]),
                authors=list(row[5] or []),
                published_date=row[6].isoformat() if row[6] else None,
                primary_category=row[7] or None,
            )
        )
    return papers


def vector_search_prior_work_top_k(
    query_vec: list[float],
    target_paper: TargetPaper,
    limit: int,
    db_config: dict[str, str] | None = None,
) -> list[RetrievedPaper]:
    target_date = parse_iso_date(target_paper.published_date)
    if target_date is None:
        raise RuntimeError("Target paper is missing a valid published_date.")

    target_base_id = extract_arxiv_base_id(target_paper.arxiv_id)
    category_sql = get_primary_category_sql(db_config)
    sql = f"""
        SELECT
            m.id,
            m.title,
            COALESCE(
                m.extracted_insights->>'summary_for_embedding',
                m.extracted_insights->>'summary',
                m.title
            ) AS summary_text,
            COALESCE(
                m.extracted_insights->>'methodology',
                m.extracted_insights->>'summary',
                ''
            ) AS methodology_text,
            1 - (e.embedding <=> %s::vector) AS similarity,
            COALESCE(m.authors, ARRAY[]::text[]),
            m.published_date,
            {category_sql} AS primary_category
        FROM papers_embeddings AS e
        JOIN papers_meta AS m ON e.paper_id = m.id
        WHERE
            m.id <> %s::uuid
            AND m.published_date < %s
            AND lower(split_part(m.arxiv_id, 'v', 1)) <> lower(%s)
        ORDER BY e.embedding <=> %s::vector
        LIMIT %s;
    """
    params = (
        embedding_to_vector_literal(query_vec),
        target_paper.id,
        target_date.isoformat(),
        target_base_id or "",
        embedding_to_vector_literal(query_vec),
        limit,
    )

    conn = psycopg2.connect(**(db_config or DEFAULT_DB_CONFIG))
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
    finally:
        conn.close()

    return [
        RetrievedPaper(
            id=str(row[0]),
            title=row[1],
            text=row[2] or row[1] or "No summary available.",
            method=row[3] or "Not provided.",
            initial_score=float(row[4]),
            authors=list(row[5] or []),
            published_date=row[6].isoformat() if row[6] else None,
            primary_category=row[7] or None,
        )
        for row in rows
    ]


def build_rerank_document(paper: RetrievedPaper) -> str:
    authors_text = ", ".join(paper.authors) if paper.authors else "Unknown"
    return "\n".join(
        [
            f"Title: {paper.title}",
            f"Published date: {paper.published_date or 'Unknown'}",
            f"Primary category: {paper.primary_category or 'Unknown'}",
            f"Authors: {authors_text}",
            f"Summary: {paper.text}",
            f"Method: {paper.method}",
        ]
    )


def rerank_with_api(query: str, docs: list[RetrievedPaper], settings: RuntimeSettings) -> list[RankedPaper]:
    if not settings.rerank.api_key:
        raise RuntimeError("RERANK_API_KEY is not set.")

    payload = {
        "model": settings.rerank.model,
        "query": query,
        "documents": [build_rerank_document(doc) for doc in docs],
        "top_n": min(settings.retrieval.top_n, len(docs)),
        "return_documents": False,
    }
    response = requests.post(
        f"{settings.rerank.base_url}/rerank",
        headers={
            "Authorization": f"Bearer {settings.rerank.api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=settings.retrieval.request_timeout,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("error"):
        raise RuntimeError(str(data["error"]))
    results = data.get("results")
    if not results:
        raise RuntimeError("Rerank API returned no results.")

    ranked_docs: list[RankedPaper] = []
    for item in results:
        index = item.get("index")
        if not isinstance(index, int) or not (0 <= index < len(docs)):
            continue
        source = docs[index]
        ranked_docs.append(
            RankedPaper(
                id=source.id,
                title=source.title,
                text=source.text,
                method=source.method,
                initial_score=source.initial_score,
                authors=list(source.authors),
                published_date=source.published_date,
                primary_category=source.primary_category,
                rerank_score=float(item.get("relevance_score", 0.0)),
            )
        )
    if not ranked_docs:
        raise RuntimeError("Rerank API did not return valid document indices.")
    return ranked_docs


def ensure_constraints_for_execution(
    query_plan: QueryPlan | None,
    original_query: str,
    corpus_latest_date: str | None,
) -> RetrievalConstraints:
    if query_plan is None:
        return RetrievalConstraints()
    return coerce_constraints(asdict(query_plan.constraints), original_query, corpus_latest_date)


def widen_implicit_latest_constraints(
    constraints: RetrievalConstraints,
    corpus_latest_date: str | None,
    months: int,
) -> RetrievalConstraints | None:
    if not constraints.is_implicit_latest:
        return None
    corpus_date = parse_iso_date(corpus_latest_date or constraints.published_before)
    if corpus_date is None:
        return None
    widened = clone_constraints(constraints)
    widened.published_before = corpus_date.isoformat()
    widened.published_after = shift_months(corpus_date, -months).isoformat()
    return widened


def build_generation_prompt(
    user_query: str,
    answer_language: str,
    papers: list[RankedPaper],
    query_plan: QueryPlan | None,
    applied_constraints: RetrievalConstraints,
    corpus_latest_date: str | None,
) -> str:
    constraint_summary = format_constraints_summary(applied_constraints, empty_text="none")
    paper_blocks: list[str] = []
    for index, paper in enumerate(papers, start=1):
        authors_text = ", ".join(paper.authors) if paper.authors else "Unknown"
        paper_blocks.append(
            "\n".join(
                [
                    f"[Paper {index}]",
                    f"Title: {paper.title}",
                    f"Published date: {paper.published_date or 'Unknown'}",
                    f"Primary category: {paper.primary_category or 'Unknown'}",
                    f"Authors: {authors_text}",
                    f"Summary: {paper.text}",
                    f"Method: {paper.method}",
                ]
            )
        )

    language_instruction = "Reply in Chinese." if answer_language == "zh" else "Reply in English."
    intent_summary = query_plan.intent_summary if query_plan is not None else user_query
    latest_instruction = ""
    if applied_constraints.sort_hint == "latest":
        latest_instruction = (
            "If you describe recent progress, make it explicit that the answer is based on the indexed corpus "
            f"up to {corpus_latest_date or 'the latest available date'}.\n"
        )

    joined_blocks = "\n\n".join(paper_blocks)
    return f"""You are a research assistant for arXiv papers about Retrieval-Augmented Generation.
Use only the provided papers to answer the question.
If the evidence is insufficient, say so clearly.
Cite evidence using labels like [Paper 1].
{language_instruction}
{latest_instruction}Applied retrieval constraints:
- time window: {constraint_summary['time_window']}
- authors: {constraint_summary['authors']}
- primary categories: {constraint_summary['categories']}
- sort hint: {constraint_summary['sort_hint']}
- corpus latest indexed publication date: {corpus_latest_date or 'unknown'}

User question:
{user_query}

Search intent summary:
{intent_summary}

Selected papers:

{joined_blocks}
"""


def build_trace_generation_prompt(
    target_paper: TargetPaper,
    answer_language: str,
    papers: list[RankedPaper],
) -> str:
    language_instruction = "Reply in Chinese." if answer_language == "zh" else "Reply in English."
    candidate_blocks: list[str] = []
    for index, paper in enumerate(papers, start=1):
        authors_text = ", ".join(paper.authors) if paper.authors else "Unknown"
        candidate_blocks.append(
            "\n".join(
                [
                    f"[Paper {index}]",
                    f"Title: {paper.title}",
                    f"Published date: {paper.published_date or 'Unknown'}",
                    f"Primary category: {paper.primary_category or 'Unknown'}",
                    f"Authors: {authors_text}",
                    f"Summary: {paper.text}",
                    f"Method: {paper.method}",
                ]
            )
        )

    return f"""You are a research assistant performing PST-lite prior-work tracing.
This task returns candidate precursor papers, not verified citations.
Use only the candidate papers provided below.
For each candidate paper, explain in 1-2 sentences why it is likely important prior work for the target paper.
If the evidence is uncertain, explicitly say that the uncertainty comes from the lack of explicit reference/citation data.
Use labels like [Paper 1].
{language_instruction}

Target paper:
Title: {target_paper.title}
arXiv ID: {target_paper.arxiv_id}
Published date: {target_paper.published_date or 'Unknown'}
Primary category: {target_paper.primary_category or 'Unknown'}
Authors: {", ".join(target_paper.authors) if target_paper.authors else 'Unknown'}
Summary: {target_paper.summary}

Candidate prior papers:

{chr(10).join(candidate_blocks)}
"""


def execute_trace(
    target_paper: TargetPaper,
    settings: RuntimeSettings,
    answer_language: str = "zh",
    db_config: dict[str, str] | None = None,
) -> TraceExecution:
    retrieval_text = build_trace_retrieval_text(target_paper)
    query_vec = get_embedding(retrieval_text, settings)
    coarse_results = vector_search_prior_work_top_k(
        query_vec,
        target_paper=target_paper,
        limit=settings.retrieval.top_k,
        db_config=db_config,
    )
    if not coarse_results:
        raise RuntimeError("No prior paper candidates were found before the target paper's publication date.")

    warnings: list[str] = []
    rerank_query = build_trace_rerank_query(target_paper)
    try:
        papers = rerank_with_api(rerank_query, coarse_results, settings)
    except Exception as exc:
        warnings.append(f"Rerank fallback used: {exc}")
        papers = [
            RankedPaper(
                id=doc.id,
                title=doc.title,
                text=doc.text,
                method=doc.method,
                initial_score=doc.initial_score,
                authors=list(doc.authors),
                published_date=doc.published_date,
                primary_category=doc.primary_category,
                rerank_score=doc.initial_score,
            )
            for doc in coarse_results[: settings.retrieval.top_n]
        ]

    prompt = build_trace_generation_prompt(target_paper, answer_language, papers)
    return TraceExecution(
        target_paper=target_paper,
        retrieval_text=retrieval_text,
        answer_language=answer_language,
        papers=papers,
        answer_prompt=prompt,
        warnings=warnings,
    )


def execute_search(
    original_query: str,
    retrieval_text: str,
    query_plan: QueryPlan | None,
    settings: RuntimeSettings,
    db_config: dict[str, str] | None = None,
) -> SearchExecution:
    answer_language = query_plan.answer_language if query_plan is not None else infer_user_language(original_query)
    corpus_latest_date = (
        query_plan.corpus_latest_date if query_plan and query_plan.corpus_latest_date else safe_get_corpus_latest_date(db_config)
    )
    applied_constraints = ensure_constraints_for_execution(query_plan, original_query, corpus_latest_date)
    query_vec = get_embedding(retrieval_text, settings)

    warnings: list[str] = []
    coarse_results = vector_search_top_k(
        query_vec,
        settings.retrieval.top_k,
        constraints=applied_constraints,
        db_config=db_config,
    )

    if len(coarse_results) < settings.retrieval.top_n and applied_constraints.is_implicit_latest:
        widened_constraints = widen_implicit_latest_constraints(applied_constraints, corpus_latest_date, months=24)
        if widened_constraints is not None:
            widened_results = vector_search_top_k(
                query_vec,
                settings.retrieval.top_k,
                constraints=widened_constraints,
                db_config=db_config,
            )
            if len(widened_results) > len(coarse_results):
                warnings.append(
                    "Too few papers matched the implicit latest window, so the time range was widened from 12 months to 24 months."
                )
                coarse_results = widened_results
                applied_constraints = widened_constraints

    if not coarse_results:
        raise RuntimeError("No relevant papers found after applying the current constraints.")

    try:
        papers = rerank_with_api(retrieval_text, coarse_results, settings)
    except Exception as exc:
        warnings.append(f"Rerank fallback used: {exc}")
        papers = [
            RankedPaper(
                id=doc.id,
                title=doc.title,
                text=doc.text,
                method=doc.method,
                initial_score=doc.initial_score,
                authors=list(doc.authors),
                published_date=doc.published_date,
                primary_category=doc.primary_category,
                rerank_score=doc.initial_score,
            )
            for doc in coarse_results[: settings.retrieval.top_n]
        ]

    prompt = build_generation_prompt(
        original_query,
        answer_language,
        papers,
        query_plan,
        applied_constraints,
        corpus_latest_date,
    )
    return SearchExecution(
        original_query=original_query,
        retrieval_text=retrieval_text,
        answer_language=answer_language,
        query_plan=query_plan,
        papers=papers,
        answer_prompt=prompt,
        warnings=warnings,
        applied_constraints=applied_constraints,
        corpus_latest_date=corpus_latest_date,
    )


def stream_answer_tokens(execution: SearchExecution, settings: RuntimeSettings) -> Iterator[str]:
    yield from stream_chat_tokens(
        [{"role": "user", "content": execution.answer_prompt}],
        settings.answer_chat,
        settings.retrieval.request_timeout,
        settings.embedding.api_url,
    )


def stream_trace_answer_tokens(execution: TraceExecution, settings: RuntimeSettings) -> Iterator[str]:
    yield from stream_chat_tokens(
        [{"role": "user", "content": execution.answer_prompt}],
        settings.answer_chat,
        settings.retrieval.request_timeout,
        settings.embedding.api_url,
    )


def get_database_overview(db_config: dict[str, str] | None = None) -> dict[str, Any]:
    conn = psycopg2.connect(**(db_config or DEFAULT_DB_CONFIG))
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM papers_meta;")
            paper_count = int(cursor.fetchone()[0])
            cursor.execute("SELECT COUNT(*) FROM papers_embeddings;")
            embedding_count = int(cursor.fetchone()[0])
            cursor.execute("SELECT MAX(published_date) FROM papers_meta;")
            latest_published_date = cursor.fetchone()[0]
    finally:
        conn.close()

    return {
        "paper_count": paper_count,
        "embedding_count": embedding_count,
        "latest_published_date": latest_published_date.isoformat() if latest_published_date else None,
    }
