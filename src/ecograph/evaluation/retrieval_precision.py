"""
src/ecograph/evaluation/retrieval_precision.py

GraphRAG retrieval quality benchmark: Precision@k and NDCG@k.

Target from README: Precision@5 > 85%.

A "golden" query set is loaded from data/evaluation/graphrag_golden.json.
Each golden item has:
    query      : str
    relevant_ids : list[str] - doc_ids considered relevant

The benchmark runs each query against the vector store, collects top-k
results, and computes:
    Precision@k = |relevant n retrieved| / k
    NDCG@k      = sum(rel_i / log2(i+2)) / ideal_DCG
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_GOLDEN = Path(__file__).parents[4] / "data" / "evaluation" / "graphrag_golden.json"


# Metrics
# ----------------------------------------------------------------------------


@dataclass
class RetrievalMetrics:
    precision_at_k: float
    ndcg_at_k:      float
    k:              int
    n_queries:      int
    target_met:     bool


def _precision_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    top_k = retrieved[:k]
    hits = sum(1 for doc_id in top_k if doc_id in relevant)
    return hits / k if k > 0 else 0.0


def _dcg_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    score = 0.0
    for i, doc_id in enumerate(retrieved[:k]):
        if doc_id in relevant:
            score += 1.0 / math.log2(i + 2)
    return score


def _ndcg_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    ideal_order = list(relevant)[:k]
    ideal_dcg = sum(1.0 / math.log2(i + 2) for i in range(len(ideal_order)))
    if ideal_dcg == 0:
        return 0.0
    return _dcg_at_k(retrieved, relevant, k) / ideal_dcg


# Benchmark runner
# ----------------------------------------------------------------------------


def run_retrieval_benchmark(
    golden_path: Optional[Path] = None,
    k: int = 5,
    vector_store=None,
) -> RetrievalMetrics:
    """
    Evaluate GraphRAG retrieval precision and NDCG against a golden dataset.

    Parameters
    ----------
    golden_path:
        Path to JSON File with golden queries. Defaults to
        data/evaluation/graphrag_golden.json.
    k:
        Top-k cutoff.
    vector_store:
        IVectorStore instance. Defaults to process singleton.

    Returns
    -------
    RetrievalMetrics
    """
    from ecograph.graphrag.vector_store import get_vector_store

    vs = vector_store or get_vector_store()
    path = golden_path or _DEFAULT_GOLDEN

    if not path.exists():
        logger.warning("Golden file not found at %s - returning zero metrics.", path)
        return RetrievalMetrics(0.0, 0.0, k, 0, False)

    with open(path, encoding="utf-8") as fh:
        golden: list[dict] = json.load(fh)

    if not golden:
        return RetrievalMetrics(0.0, 0.0, k, 0, False)

    precision_scores: list[float] = []
    ndcg_scores: list[float] = []

    for item in golden:
        query = item.get("query", "")
        relevant_ids = set(item.get("relevant_ids", []))

        try:
            results = vs.search(query, top_k=k)
            retrieved = [r["doc_id"] for r in results]
        except Exception as exc:
            logger.warning("Search failed for query '%s': %s", query, exc)
            retrieved = []

        precision_scores.append(_precision_at_k(retrieved, relevant_ids, k))
        ndcg_scores.append(_ndcg_at_k(retrieved, relevant_ids, k))

    n = len(golden)
    avg_precision = sum(precision_scores) / n
    avg_ndcg = sum(ndcg_scores) / n

    met = avg_precision >= 0.85
    if met:
        logger.info("Retrieval benchmark PASSED: Precision@%d=%.3f", k, avg_precision)
    else:
        logger.warning("Retrieval benchmark FAILED: Precision@%d=%.3f (target 0.85)", k, avg_precision)

    return RetrievalMetrics(
        precision_at_k=avg_precision,
        ndcg_at_k=avg_ndcg,
        k=k,
        n_queries=n,
        target_met=met,
    )