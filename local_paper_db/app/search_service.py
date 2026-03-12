from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
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
class QueryPlan:
    answer_language: str
    intent_summary: str
    retrieval_query_en: str
    keywords_en: list[str]


@dataclass(slots=True)
class RetrievedPaper:
    id: str
    title: str
    text: str
    method: str
    initial_score: float


@dataclass(slots=True)
class RankedPaper(RetrievedPaper):
    rerank_score: float


@dataclass(slots=True)
class SearchExecution:
    original_query: str
    retrieval_text: str
    answer_language: str
    query_plan: QueryPlan | None
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


def coerce_query_plan(raw_data: dict[str, Any], original_query: str) -> QueryPlan:
    answer_language = str(raw_data.get("answer_language", "")).strip().lower()
    if answer_language not in {"zh", "en"}:
        answer_language = infer_user_language(original_query)

    intent_summary = " ".join(str(raw_data.get("intent_summary", "")).split()).strip()
    if not intent_summary:
        intent_summary = original_query

    retrieval_query_en = " ".join(str(raw_data.get("retrieval_query_en", "")).split()).strip()
    if not retrieval_query_en:
        retrieval_query_en = original_query

    return QueryPlan(
        answer_language=answer_language,
        intent_summary=intent_summary,
        retrieval_query_en=retrieval_query_en,
        keywords_en=normalize_keyword_list(raw_data.get("keywords_en")),
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
        json={"model": settings.embedding.model, "prompt": text.replace('\n', ' ')},
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


def build_planning_messages(
    original_query: str,
    previous_plan: QueryPlan | None = None,
    user_feedback: str | None = None,
) -> list[dict[str, str]]:
    system_prompt = """
You optimize user questions for semantic retrieval over an English arXiv paper database about Retrieval-Augmented Generation.
Return only one JSON object with the following fields:
- answer_language: "zh" or "en"
- intent_summary: a brief summary of the user's actual need
- retrieval_query_en: one concise English retrieval sentence for vector search
- keywords_en: an array of English keywords or short phrases

Rules:
- The database is English, so retrieval_query_en and keywords_en must be English.
- Preserve the user's technical meaning.
- Prefer concise, research-oriented wording.
- Do not output markdown, explanations, or code fences unless absolutely necessary.
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


def plan_query(original_query: str, settings: RuntimeSettings) -> QueryPlan:
    content = chat_completion(
        build_planning_messages(original_query),
        settings.query_chat,
        settings.retrieval.request_timeout,
    )
    return coerce_query_plan(extract_first_json_object(content), original_query)


def revise_query_plan(
    original_query: str,
    previous_plan: QueryPlan,
    feedback: str,
    settings: RuntimeSettings,
) -> QueryPlan:
    content = chat_completion(
        build_planning_messages(original_query, previous_plan=previous_plan, user_feedback=feedback),
        settings.query_chat,
        settings.retrieval.request_timeout,
    )
    return coerce_query_plan(extract_first_json_object(content), original_query)


def build_retrieval_text(plan: QueryPlan) -> str:
    if not plan.keywords_en:
        return plan.retrieval_query_en
    return f"{plan.retrieval_query_en}; keywords: {', '.join(plan.keywords_en)}"


def vector_search_top_k(
    query_vec: list[float],
    limit: int,
    db_config: dict[str, str] | None = None,
) -> list[RetrievedPaper]:
    sql = """
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
            1 - (e.embedding <=> %s::vector) AS similarity
        FROM papers_embeddings AS e
        JOIN papers_meta AS m ON e.paper_id = m.id
        ORDER BY e.embedding <=> %s::vector
        LIMIT %s;
    """
    conn = psycopg2.connect(**(db_config or DEFAULT_DB_CONFIG))
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (query_vec, query_vec, limit))
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
        )
        for row in rows
    ]


def build_rerank_document(paper: RetrievedPaper) -> str:
    return f"Title: {paper.title}\nSummary: {paper.text}\nMethod: {paper.method}"


def rerank_with_api(query: str, docs: list[RetrievedPaper], settings: RuntimeSettings) -> list[RankedPaper]:
    if not settings.rerank.api_key:
        raise RuntimeError("RERANK_API_KEY is not set.")
    payload = {
        "model": settings.rerank.model,
        "query": query,
        "documents": [build_rerank_document(doc) for doc in docs],
        "top_n": settings.retrieval.top_n,
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
                rerank_score=float(item.get("relevance_score", 0.0)),
            )
        )
    if not ranked_docs:
        raise RuntimeError("Rerank API did not return valid document indices.")
    return ranked_docs


def build_generation_prompt(
    user_query: str,
    answer_language: str,
    papers: list[RankedPaper],
    query_plan: QueryPlan | None,
) -> str:
    paper_blocks = []
    for index, paper in enumerate(papers, start=1):
        paper_blocks.append(
            "\n".join(
                [
                    f"[Paper {index}]",
                    f"Title: {paper.title}",
                    f"Summary: {paper.text}",
                    f"Method: {paper.method}",
                ]
            )
        )
    language_instruction = "Reply in Chinese." if answer_language == "zh" else "Reply in English."
    intent_summary = query_plan.intent_summary if query_plan is not None else user_query
    joined_blocks = "\n\n".join(paper_blocks)
    return f"""You are a research assistant for arXiv papers about Retrieval-Augmented Generation.
Use only the provided papers to answer the question.
If the evidence is insufficient, say so clearly.
Cite evidence using labels like [Paper 1].
{language_instruction}

User question:
{user_query}

Search intent summary:
{intent_summary}

Selected papers:

{joined_blocks}
"""


def execute_search(
    original_query: str,
    retrieval_text: str,
    query_plan: QueryPlan | None,
    settings: RuntimeSettings,
    db_config: dict[str, str] | None = None,
) -> SearchExecution:
    answer_language = query_plan.answer_language if query_plan is not None else infer_user_language(original_query)
    query_vec = get_embedding(retrieval_text, settings)
    coarse_results = vector_search_top_k(query_vec, settings.retrieval.top_k, db_config=db_config)
    if not coarse_results:
        raise RuntimeError("No relevant papers found.")
    warnings: list[str] = []
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
                rerank_score=doc.initial_score,
            )
            for doc in coarse_results[: settings.retrieval.top_n]
        ]
    prompt = build_generation_prompt(original_query, answer_language, papers, query_plan)
    return SearchExecution(
        original_query=original_query,
        retrieval_text=retrieval_text,
        answer_language=answer_language,
        query_plan=query_plan,
        papers=papers,
        answer_prompt=prompt,
        warnings=warnings,
    )


def stream_answer_tokens(execution: SearchExecution, settings: RuntimeSettings) -> Iterator[str]:
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
    finally:
        conn.close()
    return {"paper_count": paper_count, "embedding_count": embedding_count}
