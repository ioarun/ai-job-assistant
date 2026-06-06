import json
import logging
from pathlib import Path

from app.services.retriever import HybridRetriever

log = logging.getLogger(__name__)


def compute_recall_at_k(retrieved_ids: list[str], expected_ids: list[str], k: int) -> float:
    """
    Compute recall@k.

    Recall@k = (number of relevant docs in top-k) / (total relevant docs)
    """
    if not expected_ids:
        return 0.0

    top_k_ids = set(retrieved_ids[:k])
    relevant_count = len(top_k_ids & set(expected_ids))
    return relevant_count / len(expected_ids)


def compute_mrr(retrieved_ids: list[str], expected_ids: list[str]) -> float:
    """
    Compute Mean Reciprocal Rank (MRR).

    MRR = 1 / (rank of first relevant doc) or 0 if no relevant doc found
    """
    expected_set = set(expected_ids)
    for rank, doc_id in enumerate(retrieved_ids):
        if doc_id in expected_set:
            return 1.0 / (rank + 1)
    return 0.0


def load_golden_dataset(path: Path) -> list[dict]:
    """
    Load golden evaluation dataset from JSON.

    Expected format:
    [
        {"query": "...", "expected_doc_ids": ["...", "..."]},
        ...
    ]
    """
    try:
        with open(path) as f:
            dataset = json.load(f)
        log.info("Loaded golden dataset", extra={"path": str(path), "count": len(dataset)})
        return dataset
    except FileNotFoundError:
        log.warning("Golden dataset not found", extra={"path": str(path)})
        return []
    except Exception as e:
        log.error("Failed to load golden dataset", extra={"error": str(e)})
        return []


async def run_eval_suite(
    retriever: HybridRetriever,
    golden_dataset: list[dict],
    k_values: list[int] = None
) -> dict:
    """
    Run full evaluation suite on golden dataset.

    Returns:
        Dict of metrics: {
            "recall@5": float,
            "recall@10": float,
            "mrr": float,
            "eval_count": int
        }
    """
    if k_values is None:
        k_values = [5, 10]

    if not golden_dataset:
        log.warning("No golden dataset provided for evaluation")
        return {}

    metrics = {f"recall@{k}": 0.0 for k in k_values}
    metrics["mrr"] = 0.0
    metrics["eval_count"] = len(golden_dataset)
    metrics["queries_with_results"] = 0

    log.info("Starting retrieval evaluation", extra={"eval_count": len(golden_dataset)})

    for eval_item in golden_dataset:
        query = eval_item.get("query", "")
        expected_ids = eval_item.get("expected_doc_ids", [])

        if not query or not expected_ids:
            log.warning("Skipping eval item with missing query or expected_ids")
            continue

        # Retrieve
        retrieved_chunks = await retriever.retrieve(query, top_k=max(k_values))

        if not retrieved_chunks:
            log.debug("No results retrieved", extra={"query": query})
            continue

        retrieved_ids = [chunk.chunk_id for chunk in retrieved_chunks]
        metrics["queries_with_results"] += 1

        # Compute metrics
        for k in k_values:
            recall_k = compute_recall_at_k(retrieved_ids, expected_ids, k)
            metrics[f"recall@{k}"] += recall_k

        mrr = compute_mrr(retrieved_ids, expected_ids)
        metrics["mrr"] += mrr

    # Average metrics
    if metrics["eval_count"] > 0:
        for k in k_values:
            metrics[f"recall@{k}"] /= metrics["eval_count"]
        metrics["mrr"] /= metrics["eval_count"]

    log.info("Evaluation complete", extra=metrics)

    return metrics
