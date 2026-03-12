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
    build_retrieval_text,
    execute_search,
    get_env_default_settings,
    plan_query,
    revise_query_plan,
    stream_answer_tokens,
    validate_runtime_settings,
)


def print_query_plan(original_query: str, plan: QueryPlan) -> None:
    print("\n[Confirmation] Query rewrite candidate")
    print("=" * 60)
    print(f"Original question: {original_query}")
    print(f"Intent summary: {plan.intent_summary}")
    print(f"Retrieval query: {plan.retrieval_query_en}")
    print("Keywords: " + (", ".join(plan.keywords_en) if plan.keywords_en else "(none)"))
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
            return original_query, None

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
            return original_query, None
        print("[Confirmation] Invalid choice. Please enter 1, 2, or 3.")


def print_selected_papers(papers: list[RankedPaper]) -> None:
    print("\n[Rerank] Selected papers")
    for index, paper in enumerate(papers, start=1):
        print(
            f"{index}. [rerank={paper.rerank_score:.4f} | vector={paper.initial_score:.4f}] "
            f"{paper.title}"
        )


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
    print_selected_papers(execution.papers)

    print("\n[Generation] Answer")
    print("=" * 60)
    for token in stream_answer_tokens(execution, settings):
        print(token, end="", flush=True)
    print("\n" + "=" * 60)
    print(f"\nElapsed: {time.time() - started_at:.2f}s")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search the local arXiv RAG paper database from the terminal."
    )
    parser.add_argument("query", nargs="?", help="Optional query. If omitted, interactive mode starts.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
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
