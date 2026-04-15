from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import requests

try:
    import arxiv
except ImportError:  # pragma: no cover
    arxiv = None


_CACHE: dict[str, tuple[float, Any]] = {}
_ARXIV_ID_PATTERN = re.compile(r"^(?:arxiv:)?(?P<base>\d{4}\.\d{4,5})(?:v(?P<version>\d+))?$", re.IGNORECASE)
_ARXIV_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "based",
    "for",
    "from",
    "how",
    "in",
    "into",
    "latest",
    "methods",
    "most",
    "new",
    "newest",
    "of",
    "on",
    "paper",
    "papers",
    "recent",
    "review",
    "reviews",
    "study",
    "survey",
    "surveys",
    "the",
    "to",
    "up",
    "with",
}


@dataclass(slots=True)
class ExternalPaperRecord:
    source: str
    source_id: str
    title: str
    summary: str
    authors: list[str] = field(default_factory=list)
    published_date: str | None = None
    primary_category: str | None = None
    external_url: str | None = None
    arxiv_id: str | None = None
    doi: str | None = None


def _cache_get(key: str) -> Any | None:
    payload = _CACHE.get(key)
    if payload is None:
        return None
    expires_at, value = payload
    if expires_at < time.time():
        _CACHE.pop(key, None)
        return None
    return value


def _cache_set(key: str, value: Any, ttl_seconds: int) -> Any:
    _CACHE[key] = (time.time() + ttl_seconds, value)
    return value


def _normalize_whitespace(text: str) -> str:
    return " ".join(str(text or "").split()).strip()


def _escape_quoted(text: str) -> str:
    return _normalize_whitespace(text).replace('"', "")


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def enabled_external_sources() -> list[str]:
    raw = os.getenv("RETRIEVAL_ENABLED_SOURCES", "local,arxiv")
    allowed = {"arxiv", "wos"}
    seen: set[str] = set()
    resolved: list[str] = []
    for item in re.split(r"[,\s]+", raw):
        value = item.strip().lower()
        if not value or value not in allowed or value in seen:
            continue
        seen.add(value)
        resolved.append(value)
    return resolved


def source_freshness() -> dict[str, str | None]:
    freshness: dict[str, str | None] = {}
    today = _today_iso()
    if "arxiv" in enabled_external_sources():
        freshness["arxiv"] = today
    if "wos" in enabled_external_sources():
        freshness["wos"] = today
    return freshness


def _constraints_window(constraints: Any) -> tuple[str | None, str | None]:
    published_after = getattr(constraints, "published_after", None)
    published_before = getattr(constraints, "published_before", None)
    return published_after, published_before


def _extract_keyword_terms(retrieval_text: str) -> list[str]:
    content, _, raw_keywords = str(retrieval_text or "").partition("; keywords:")
    phrases: list[str] = []
    if raw_keywords.strip():
        phrases.extend(_normalize_whitespace(item) for item in raw_keywords.split(","))
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9.+_-]{1,}", content)
    for token in tokens:
        normalized = token.strip().lower()
        if normalized in _ARXIV_STOPWORDS or len(normalized) < 3:
            continue
        phrases.append(normalized)

    seen: set[str] = set()
    terms: list[str] = []
    for item in phrases:
        normalized = _normalize_whitespace(item)
        if not normalized:
            continue
        lowered = normalized.casefold()
        if lowered in seen:
            continue
        seen.add(lowered)
        terms.append(normalized)
    return terms[:8]


def _build_arxiv_query(retrieval_text: str, constraints: Any) -> str:
    query_parts: list[str] = []
    terms = _extract_keyword_terms(retrieval_text)
    if terms:
        token_query = " OR ".join(
            f'all:"{_escape_quoted(term)}"' if " " in term else f"all:{_escape_quoted(term)}"
            for term in terms
        )
        query_parts.append(f"({token_query})")

    authors = list(getattr(constraints, "authors", []) or [])
    for author in authors[:3]:
        query_parts.append(f'au:"{_escape_quoted(author)}"')

    categories = list(getattr(constraints, "primary_categories", []) or [])
    for category in categories[:3]:
        query_parts.append(f"cat:{_escape_quoted(category)}")

    published_after, published_before = _constraints_window(constraints)
    if published_after or published_before:
        start = str((published_after or "1990-01-01")).replace("-", "") + "0000"
        end = str((published_before or _today_iso())).replace("-", "") + "2359"
        query_parts.append(f"submittedDate:[{start} TO {end}]")

    return " AND ".join(part for part in query_parts if part) or "cat:cs"


def _build_wos_topic_query(retrieval_text: str, constraints: Any, *, title_only: bool = False) -> str:
    content = _normalize_whitespace(str(retrieval_text or "").split("; keywords:", 1)[0])
    field = "TI" if title_only else "TS"
    query_parts = [f'{field}=("{_escape_quoted(content[:240])}")'] if content else []

    authors = list(getattr(constraints, "authors", []) or [])
    for author in authors[:3]:
        query_parts.append(f'AU=("{_escape_quoted(author)}")')

    published_after, published_before = _constraints_window(constraints)
    year_after = str(published_after or "")[:4]
    year_before = str(published_before or "")[:4]
    if year_after and year_before:
        query_parts.append(f"PY=({year_after}-{year_before})")
    elif year_after:
        query_parts.append(f"PY=({year_after}-{datetime.now(timezone.utc).year})")
    elif year_before:
        query_parts.append(f"PY=(1900-{year_before})")

    return " AND ".join(query_parts) if query_parts else 'TS=("computer science")'


def _coerce_arxiv_record(result: Any) -> ExternalPaperRecord:
    short_id = result.get_short_id()
    published = result.published.strftime("%Y-%m-%d") if getattr(result, "published", None) else None
    return ExternalPaperRecord(
        source="arxiv",
        source_id=short_id,
        title=_normalize_whitespace(result.title),
        summary=_normalize_whitespace(result.summary),
        authors=[_normalize_whitespace(author.name) for author in getattr(result, "authors", [])],
        published_date=published,
        primary_category=getattr(result, "primary_category", None),
        external_url=getattr(result, "entry_id", None),
        arxiv_id=short_id,
    )


def _arxiv_client() -> Any:
    if arxiv is None:  # pragma: no cover
        raise RuntimeError("arxiv package is not installed.")
    return arxiv.Client(page_size=100, delay_seconds=3.0, num_retries=2)


def search_arxiv_records(retrieval_text: str, constraints: Any, *, limit: int) -> list[ExternalPaperRecord]:
    cache_key = "arxiv:search:" + json.dumps(
        {
            "query": retrieval_text,
            "limit": limit,
            "authors": list(getattr(constraints, "authors", []) or []),
            "categories": list(getattr(constraints, "primary_categories", []) or []),
            "after": getattr(constraints, "published_after", None),
            "before": getattr(constraints, "published_before", None),
            "sort_hint": getattr(constraints, "sort_hint", None),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    query = _build_arxiv_query(retrieval_text, constraints)
    sort_by = arxiv.SortCriterion.SubmittedDate if getattr(constraints, "sort_hint", "") == "latest" else arxiv.SortCriterion.Relevance
    search = arxiv.Search(
        query=query,
        max_results=max(1, limit),
        sort_by=sort_by,
        sort_order=arxiv.SortOrder.Descending,
    )
    results = [_coerce_arxiv_record(item) for item in _arxiv_client().results(search)]
    return _cache_set(cache_key, results[:limit], ttl_seconds=600)


def _parse_arxiv_id(query: str) -> str | None:
    match = _ARXIV_ID_PATTERN.match(_normalize_whitespace(query))
    if match is None:
        return None
    version = match.group("version")
    base = match.group("base")
    return f"{base}v{version}" if version else base


def fetch_arxiv_record(arxiv_id: str) -> ExternalPaperRecord | None:
    normalized = _normalize_whitespace(arxiv_id)
    if not normalized:
        return None
    cache_key = f"arxiv:record:{normalized}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    search = arxiv.Search(id_list=[normalized], max_results=1)
    results = [_coerce_arxiv_record(item) for item in _arxiv_client().results(search)]
    record = results[0] if results else None
    return _cache_set(cache_key, record, ttl_seconds=600)


def resolve_arxiv_candidates(query: str, *, limit: int) -> list[ExternalPaperRecord]:
    normalized = _normalize_whitespace(query)
    if not normalized:
        return []
    arxiv_id = _parse_arxiv_id(normalized)
    if arxiv_id:
        record = fetch_arxiv_record(arxiv_id)
        return [record] if record is not None else []

    title_query = f'ti:"{_escape_quoted(normalized[:240])}"'
    results = [_coerce_arxiv_record(item) for item in _arxiv_client().results(arxiv.Search(query=title_query, max_results=max(1, limit)))]
    if results:
        return results[:limit]
    fallback_query = f'all:"{_escape_quoted(normalized[:240])}"'
    fallback = [_coerce_arxiv_record(item) for item in _arxiv_client().results(arxiv.Search(query=fallback_query, max_results=max(1, limit)))]
    return fallback[:limit]


def _wos_headers(api_key: str) -> dict[str, str]:
    return {
        "X-ApiKey": api_key,
        "Accept": "application/json",
    }


def _wos_base_url() -> str:
    return os.getenv("WOS_API_BASE_URL", "https://api.clarivate.com/apis/wos-starter/v1").rstrip("/")


def _wos_timeout() -> int:
    return int(os.getenv("WOS_SEARCH_TIMEOUT", "15"))


def _extract_nested_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = _normalize_whitespace(value)
        return [text] if text else []
    if isinstance(value, dict):
        values: list[str] = []
        for item in value.values():
            values.extend(_extract_nested_strings(item))
        return values
    if isinstance(value, list):
        values: list[str] = []
        for item in value:
            values.extend(_extract_nested_strings(item))
        return values
    return []


def _extract_first_string(item: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str):
            text = _normalize_whitespace(value)
            if text:
                return text
        if isinstance(value, (dict, list)):
            values = _extract_nested_strings(value)
            if values:
                return values[0]
    return None


def _coerce_wos_hit(item: dict[str, Any]) -> ExternalPaperRecord | None:
    uid = _extract_first_string(item, "uid", "UID", "id")
    title = _extract_first_string(item, "title", "titles", "documentTitle", "names")
    if not uid or not title:
        return None

    authors_payload = item.get("names") or item.get("authors") or item.get("contributors") or []
    authors = _extract_nested_strings(authors_payload)[:8]
    summary = _extract_first_string(item, "abstract", "abstracts", "summary", "description") or title
    publish_year = _extract_first_string(item, "publishYear", "year", "published", "publicationDate")
    published_date = None
    if publish_year:
        year_match = re.search(r"(19|20)\d{2}", publish_year)
        if year_match:
            published_date = f"{year_match.group(0)}-01-01"
    doi = _extract_first_string(item, "doi", "identifiers", "identifier")
    external_url = _extract_first_string(item, "links", "url", "recordLink", "source")
    primary_category = _extract_first_string(item, "sourceTypes", "categories", "topics", "source")
    return ExternalPaperRecord(
        source="wos",
        source_id=uid,
        title=title,
        summary=summary,
        authors=authors,
        published_date=published_date,
        primary_category=primary_category,
        external_url=external_url,
        doi=doi,
    )


def _extract_wos_hits(payload: Any) -> list[ExternalPaperRecord]:
    hits: list[ExternalPaperRecord] = []
    if isinstance(payload, dict) and isinstance(payload.get("hits"), list):
        for item in payload["hits"]:
            if isinstance(item, dict):
                hit = _coerce_wos_hit(item)
                if hit is not None:
                    hits.append(hit)
        return hits

    data = payload.get("Data") if isinstance(payload, dict) else None
    records = (((data or {}).get("Records") or {}).get("records") or {}).get("REC") if isinstance(data, dict) else None
    if isinstance(records, list):
        for item in records:
            if isinstance(item, dict):
                hit = _coerce_wos_hit(item)
                if hit is not None:
                    hits.append(hit)
    elif isinstance(records, dict):
        hit = _coerce_wos_hit(records)
        if hit is not None:
            hits.append(hit)
    return hits


def search_wos_records(retrieval_text: str, constraints: Any, *, limit: int) -> list[ExternalPaperRecord]:
    api_key = os.getenv("WOS_API_KEY")
    if not api_key:
        raise RuntimeError("WOS_API_KEY is not set.")

    max_results = max(1, min(limit, int(os.getenv("WOS_SEARCH_MAX_RESULTS", "10"))))
    query = _build_wos_topic_query(retrieval_text, constraints)
    cache_key = "wos:search:" + json.dumps({"query": query, "limit": max_results}, sort_keys=True)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    response = requests.get(
        f"{_wos_base_url()}/documents",
        headers=_wos_headers(api_key),
        params={
            "q": query,
            "limit": max_results,
            "page": 1,
            "db": os.getenv("WOS_DATABASE", "WOS"),
        },
        timeout=_wos_timeout(),
    )
    response.raise_for_status()
    results = _extract_wos_hits(response.json())[:max_results]
    return _cache_set(cache_key, results, ttl_seconds=600)


def fetch_wos_record(uid: str) -> ExternalPaperRecord | None:
    normalized = _normalize_whitespace(uid)
    if not normalized:
        return None
    api_key = os.getenv("WOS_API_KEY")
    if not api_key:
        raise RuntimeError("WOS_API_KEY is not set.")

    cache_key = f"wos:record:{normalized}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    response = requests.get(
        f"{_wos_base_url()}/documents/{normalized}",
        headers=_wos_headers(api_key),
        params={"db": os.getenv("WOS_DATABASE", "WOS")},
        timeout=_wos_timeout(),
    )
    response.raise_for_status()
    payload = response.json()
    hits = _extract_wos_hits(payload)
    record = hits[0] if hits else (_coerce_wos_hit(payload) if isinstance(payload, dict) else None)
    return _cache_set(cache_key, record, ttl_seconds=600)


def resolve_wos_candidates(query: str, *, limit: int) -> list[ExternalPaperRecord]:
    normalized = _normalize_whitespace(query)
    if not normalized:
        return []
    topic_query = _build_wos_topic_query(normalized, constraints=None, title_only=True)
    api_key = os.getenv("WOS_API_KEY")
    if not api_key:
        raise RuntimeError("WOS_API_KEY is not set.")

    max_results = max(1, min(limit, int(os.getenv("WOS_SEARCH_MAX_RESULTS", "10"))))
    cache_key = "wos:resolve:" + json.dumps({"query": topic_query, "limit": max_results}, sort_keys=True)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    response = requests.get(
        f"{_wos_base_url()}/documents",
        headers=_wos_headers(api_key),
        params={
            "q": topic_query,
            "limit": max_results,
            "page": 1,
            "db": os.getenv("WOS_DATABASE", "WOS"),
        },
        timeout=_wos_timeout(),
    )
    response.raise_for_status()
    results = _extract_wos_hits(response.json())[:max_results]
    return _cache_set(cache_key, results, ttl_seconds=600)
