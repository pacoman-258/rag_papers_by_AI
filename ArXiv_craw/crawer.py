from __future__ import annotations

import json
import re
from pathlib import Path

import arxiv


KEYWORD = "Retrieval Augmented Generation"
CATEGORY = "cs.CL"
MAX_RESULTS = 100
SAVE_DIR = Path("./arxiv_papers_rag")


def sanitize_filename(filename: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", filename)


def to_portable_relative_path(path: Path) -> str:
    return path.as_posix()


def run_downloader() -> None:
    SAVE_DIR.mkdir(parents=True, exist_ok=True)

    client = arxiv.Client(page_size=100, delay_seconds=3.0, num_retries=3)
    search = arxiv.Search(
        query=f'cat:{CATEGORY} AND all:"{KEYWORD}"',
        max_results=MAX_RESULTS,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending,
    )

    print(f"Starting search: {search.query}")
    results = list(client.results(search))
    print(f"Found {len(results)} papers. Processing downloads...")

    metadata_list: list[dict[str, object]] = []
    for result in results:
        paper_id = result.get_short_id()
        publish_date = result.published.strftime("%Y-%m-%d")
        safe_title = sanitize_filename(result.title)
        pdf_filename = f"[{publish_date}] {safe_title}.pdf"
        pdf_path = SAVE_DIR / pdf_filename

        print(f"Processing: {result.title}")
        if pdf_path.exists():
            print("  -> Skipped (already downloaded)")
            continue

        try:
            result.download_pdf(dirpath=str(SAVE_DIR), filename=pdf_filename)
        except Exception as exc:  # pragma: no cover
            print(f"  -> Download failed: {exc}")
            continue

        metadata_list.append(
            {
                "arxiv_id": paper_id,
                "title": result.title,
                "published_date": publish_date,
                "authors": [author.name for author in result.authors],
                "summary": result.summary.replace("\n", " "),
                "pdf_local_path": to_portable_relative_path(pdf_path),
                "url": result.entry_id,
                "primary_category": result.primary_category,
            }
        )
        print("  -> Download completed")

    json_path = SAVE_DIR / "metadata_log.jsonl"
    with json_path.open("a", encoding="utf-8") as handle:
        for metadata in metadata_list:
            handle.write(json.dumps(metadata, ensure_ascii=False) + "\n")

    print(f"\nAll done. Metadata saved to {json_path.as_posix()}")


if __name__ == "__main__":
    run_downloader()
