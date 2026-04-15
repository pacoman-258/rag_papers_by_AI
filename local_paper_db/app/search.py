from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from local_paper_db.app.search_service import (
    QueryPlan,
    RankedPaper,
    TargetPaper,
    build_retrieval_text,
    execute_search,
    execute_trace,
    format_constraints_summary,
    get_env_default_settings,
    infer_user_language,
    parse_arxiv_query,
    plan_query,
    resolve_target_paper,
    revise_query_plan,
    stream_answer_tokens,
    stream_trace_answer_tokens,
    validate_runtime_settings,
)


def print_query_plan(original_query: str, plan: QueryPlan) -> None:
    constraint_summary = format_constraints_summary(plan.constraints)
    print("\n[Confirmation] Query rewrite candidate")
    print("=" * 60)
    print(f"Original question: {original_query}")
    print(f"Intent summary: {plan.intent_summary}")
    print(f"Retrieval query: {plan.retrieval_query_en}")
    print("Keywords: " + (", ".join(plan.keywords_en) if plan.keywords_en else "(none)"))
    print(f"Time window: {constraint_summary['time_window']}")
    print(f"Authors: {constraint_summary['authors']}")
    print(f"Categories: {constraint_summary['categories']}")
    print(f"Sort hint: {constraint_summary['sort_hint']}")
    print(f"Corpus latest date: {plan.corpus_latest_date or '(unknown)'}")
    print("=" * 60)


def confirm_query_plan(original_query: str, initial_plan: QueryPlan, settings) -> tuple[str, QueryPlan | None]:
    current_plan = initial_plan
    while True:
        print_query_plan(original_query, current_plan)
        print("1. Use the optimized query")
        print("2. Tell the model what to improve")
        print("3. Use the original question")

        try:
            choice = input("Choose 1, 2, or 3: ").strip()
        except EOFError:
            print("\n[Confirmation] No input available. Falling back to the original question.")
            return original_query, current_plan

        if choice == "1":
            return build_retrieval_text(current_plan), current_plan
        if choice == "2":
            feedback = input("Describe what should be improved: ").strip()
            if not feedback:
                print("[Confirmation] Feedback cannot be empty.")
                continue
            print("[Planning] Revising the query plan...")
            try:
                current_plan = revise_query_plan(original_query, current_plan, feedback, settings)
            except Exception as exc:
                print(f"[Planning] Rewrite revision failed. Keeping the current candidate. {exc}")
            continue
        if choice == "3":
            return original_query, current_plan
        print("[Confirmation] Invalid choice. Please enter 1, 2, or 3.")


def print_selected_papers(papers: list[RankedPaper]) -> None:
    print("\n[Rerank] Selected papers")
    for index, paper in enumerate(papers, start=1):
        meta_bits = []
        if paper.source:
            meta_bits.append(f"source={paper.source}")
        if paper.published_date:
            meta_bits.append(paper.published_date)
        if paper.primary_category:
            meta_bits.append(paper.primary_category)
        print(
            f"{index}. [rerank={paper.rerank_score:.4f} | vector={paper.initial_score:.4f}] "
            f"{paper.title}"
        )
        if meta_bits:
            print("   " + " | ".join(meta_bits))


def print_target_paper(target_paper: TargetPaper) -> None:
    print("\n[Target Paper]")
    print("=" * 60)
    print(f"Title: {target_paper.title}")
    print(f"Source: {target_paper.source}")
    print(f"arXiv ID: {target_paper.arxiv_id or 'Unknown'}")
    print(f"Published date: {target_paper.published_date or 'Unknown'}")
    print(f"Primary category: {target_paper.primary_category or 'Unknown'}")
    print(f"Authors: {', '.join(target_paper.authors) if target_paper.authors else 'Unknown'}")
    print(f"Summary: {target_paper.summary}")
    print("=" * 60)


def choose_target_paper(candidates: list[TargetPaper]) -> TargetPaper | None:
    print("\n[Target Selection] Multiple candidate papers were found.")
    for index, candidate in enumerate(candidates, start=1):
        print(f"{index}. {candidate.title} | {candidate.arxiv_id} | {candidate.published_date or 'Unknown'}")
    try:
        choice = input("Choose a paper number (or press Enter to cancel): ").strip()
    except EOFError:
        print()
        return None
    if not choice:
        return None
    if not choice.isdigit():
        print("[Target Selection] Invalid choice.")
        return None
    selected_index = int(choice) - 1
    if not (0 <= selected_index < len(candidates)):
        print("[Target Selection] Invalid choice.")
        return None
    return candidates[selected_index]


def search_once(query: str) -> None:
    settings = get_env_default_settings()
    validate_runtime_settings(settings)

    started_at = time.time()
    query_plan = None
    retrieval_text = query

    print(f"[Planning] Using query chat provider: {settings.query_chat.provider} / {settings.query_chat.model}")
    try:
        candidate_plan = plan_query(query, settings)
        retrieval_text, query_plan = confirm_query_plan(query, candidate_plan, settings)
    except Exception as exc:
        print(f"[Planning] Query rewrite failed. Falling back to the original question. {exc}")

    print(f"[Retrieval] Embedding query with model: {settings.embedding.model}")
    execution = execute_search(query, retrieval_text, query_plan, settings)
    applied_summary = format_constraints_summary(execution.applied_constraints)
    print("[Retrieval] Applied constraints")
    print(
        "   time={time} | authors={authors} | categories={categories} | corpus_latest={latest}".format(
            time=applied_summary["time_window"],
            authors=applied_summary["authors"],
            categories=applied_summary["categories"],
            latest=execution.corpus_latest_date or "(unknown)",
        )
    )
    for warning in execution.warnings:
        print(f"[Warning] {warning}")
    print_selected_papers(execution.papers)

    print("\n[Generation] Answer")
    print("=" * 60)
    for token in stream_answer_tokens(execution, settings):
        print(token, end="", flush=True)
    print("\n" + "=" * 60)
    print(f"\nElapsed: {time.time() - started_at:.2f}s")


def trace_once(target_query: str, answer_language: str | None = None) -> None:
    settings = get_env_default_settings()
    validate_runtime_settings(settings)

    started_at = time.time()
    status, resolved_target, candidates, message = resolve_target_paper(target_query)
    if status == "not_found":
        raise RuntimeError(message or "Target paper not found.")

    target_paper = resolved_target
    if status == "ambiguous":
        target_paper = choose_target_paper(candidates)
        if target_paper is None:
            raise RuntimeError("Target paper selection was cancelled.")

    if target_paper is None:
        raise RuntimeError("Failed to resolve the target paper.")

    if answer_language is not None:
        answer_lang = answer_language
    else:
        answer_lang = "zh" if parse_arxiv_query(target_query) is not None else infer_user_language(target_query)
    print_target_paper(target_paper)
    execution = execute_trace(target_paper=target_paper, settings=settings, answer_language=answer_lang)
    for warning in execution.warnings:
        print(f"[Warning] {warning}")
    print_selected_papers(execution.papers)

    print("\n[PST] Candidate Prior Papers")
    print("=" * 60)
    for token in stream_trace_answer_tokens(execution, settings):
        print(token, end="", flush=True)
    print("\n" + "=" * 60)
    print(f"\nElapsed: {time.time() - started_at:.2f}s")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search the local arXiv RAG paper database from the terminal."
    )
    parser.add_argument("query", nargs="?", help="Optional search query. If omitted, interactive mode starts.")
    parser.add_argument("--trace", dest="trace_query", help="Trace likely precursor papers for a target paper.")
    parser.add_argument("--trace-language", choices=["zh", "en"], help="Answer language for --trace mode.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.trace_query:
            trace_once(args.trace_query, answer_language=args.trace_language)
            return 0

        if args.query:
            search_once(args.query)
            return 0

        while True:
            try:
                query = input("\nEnter your question (q to quit): ").strip()
            except EOFError:
                print()
                return 0

            if query.lower() == "q":
                return 0
            if not query:
                continue

            try:
                search_once(query)
            except KeyboardInterrupt:
                print("\nInterrupted.")
            except Exception as exc:
                print(f"Search failed: {exc}")
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    except Exception as exc:
        print(f"Startup failed: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
