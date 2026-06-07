#!/usr/bin/env python3
"""
Phase B retrieval-quality gate.

Loads the golden dataset, runs the hybrid retriever over each query, and
reports recall@5, recall@10, and MRR. Exits non-zero if recall@5 falls below
the baseline threshold — so this can be used directly as a CI gate later.

Prerequisite: the resume referenced by the golden set must already be indexed
(see scripts/index_resume.py).

Usage:
    python -m evals.run_retrieval_eval
    python -m evals.run_retrieval_eval --baseline 0.6 --dataset evals/datasets/retrieval_golden.json
"""
import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.observability.langfuse_client import shutdown_langfuse
from app.services.eval_retrieval import load_golden_dataset, run_eval_suite
from app.services.retriever import get_retriever
from app.services.vector_store import get_collection_size

# Baseline recall@5 the retriever must meet for Phase B's "Done when" gate.
DEFAULT_BASELINE_RECALL_AT_5 = 0.6


async def evaluate(dataset_path: Path, baseline: float) -> int:
    log = logging.getLogger(__name__)
    settings = get_settings()

    # Guard: empty collection means the resume was never indexed.
    size = await get_collection_size(settings.chroma_collection_name)
    if size == 0:
        log.error(
            "Chroma collection '%s' is empty — index a resume first "
            "(python -m scripts.index_resume <pdf>).",
            settings.chroma_collection_name,
        )
        return 2

    golden = load_golden_dataset(dataset_path)
    if not golden:
        log.error("Golden dataset is empty or missing: %s", dataset_path)
        return 2

    retriever = await get_retriever()
    metrics = await run_eval_suite(retriever, golden, k_values=[5, 10])

    recall_5 = metrics.get("recall@5", 0.0)
    passed = recall_5 >= baseline

    print("\n" + "=" * 60)
    print("Retrieval Evaluation")
    print(f"  collection:          {settings.chroma_collection_name} ({size} docs)")
    print(f"  dataset:             {dataset_path} ({metrics.get('eval_count', 0)} queries)")
    print(f"  queries w/ results:  {metrics.get('queries_with_results', 0)}")
    print("  " + "-" * 40)
    print(f"  recall@5:            {recall_5:.3f}   (baseline {baseline:.2f})")
    print(f"  recall@10:           {metrics.get('recall@10', 0.0):.3f}")
    print(f"  MRR:                 {metrics.get('mrr', 0.0):.3f}")
    print("  " + "-" * 40)
    print(f"  RESULT:              {'PASS ✅' if passed else 'FAIL ❌'}")
    print("=" * 60)

    return 0 if passed else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the retrieval-quality eval gate.")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("evals/datasets/retrieval_golden.json"),
        help="Path to the golden dataset JSON",
    )
    parser.add_argument(
        "--baseline",
        type=float,
        default=DEFAULT_BASELINE_RECALL_AT_5,
        help="Minimum recall@5 required to pass",
    )
    args = parser.parse_args()

    configure_logging()
    try:
        exit_code = asyncio.run(evaluate(args.dataset, args.baseline))
    finally:
        shutdown_langfuse()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
