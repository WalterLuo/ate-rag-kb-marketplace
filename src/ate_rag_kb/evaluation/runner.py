"""Evaluation runner: orchestrates retrieval and metric computation."""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from typing import Any

from ate_rag_kb.chunking.models import Chunk
from ate_rag_kb.evaluation.metrics import (
    hit_at_k,
    mrr_at_k,
    recall_at_k,
    source_precision_at_k,
)
from ate_rag_kb.evaluation.models import (
    EvalQuestion,
    EvalReport,
    QuestionFailure,
    QuestionResult,
)

logger = logging.getLogger(__name__)


def _compute_metrics(
    retrieved: list[tuple[Chunk, float]],
    question: EvalQuestion,
    k_values: Sequence[int],
) -> dict[str, dict[int, float]]:
    """Compute all metrics for a single question at each k."""
    return {
        "hit_at_k": {k: hit_at_k(retrieved, question.expected_chunk_ids, k) for k in k_values},
        "recall_at_k": {
            k: recall_at_k(retrieved, question.expected_chunk_ids, k) for k in k_values
        },
        "mrr_at_k": {k: mrr_at_k(retrieved, question.expected_chunk_ids, k) for k in k_values},
        "source_precision_at_k": {
            k: source_precision_at_k(retrieved, question.expected_source_mds, k)
            for k in k_values
        },
    }


def _aggregate_metrics(
    results: Sequence[QuestionResult],
    k_values: Sequence[int],
) -> dict[str, dict[int, float]]:
    """Average metric values across all successful results."""
    if not results:
        return {}

    aggregated: dict[str, dict[int, float]] = {}
    metric_names = ["hit_at_k", "recall_at_k", "mrr_at_k", "source_precision_at_k"]

    for name in metric_names:
        aggregated[name] = {}
        for k in k_values:
            values = [getattr(r, name)[k] for r in results]
            aggregated[name][k] = sum(values) / len(values)

    return aggregated


class EvalRunner:
    """Orchestrate retrieval evaluation with per-question error isolation."""

    def __init__(self, k_values: Sequence[int] | None = None) -> None:
        self.k_values = list(k_values) if k_values else [1, 3, 5, 10]

    async def run(
        self,
        pipeline: Any,
        questions: Sequence[EvalQuestion],
        config_snapshot: dict[str, Any],
    ) -> EvalReport:
        """Run evaluation and return an immutable report."""
        results: list[QuestionResult | QuestionFailure] = []
        total_start = time.perf_counter()
        max_k = max(self.k_values)

        for question in questions:
            start = time.perf_counter()
            try:
                retrieved: list[tuple[Chunk, float]] = await pipeline.search(
                    question.query,
                    top_k=max_k,
                )
                metrics = _compute_metrics(retrieved, question, self.k_values)
                results.append(
                    QuestionResult(
                        question=question,
                        retrieved_chunks=tuple((c, s) for c, s in retrieved),
                        hit_at_k=metrics["hit_at_k"],
                        recall_at_k=metrics["recall_at_k"],
                        mrr_at_k=metrics["mrr_at_k"],
                        source_precision_at_k=metrics["source_precision_at_k"],
                        latency_ms=round((time.perf_counter() - start) * 1000, 2),
                    )
                )
            except Exception as exc:
                logger.error("Eval failed for %s: %s", question.id, exc)
                results.append(
                    QuestionFailure(
                        question=question,
                        error=str(exc),
                        latency_ms=round((time.perf_counter() - start) * 1000, 2),
                    )
                )

        successful = [r for r in results if isinstance(r, QuestionResult)]
        failed_count = len(results) - len(successful)

        return EvalReport(
            questions=tuple(questions),
            results=tuple(results),
            aggregated_metrics=_aggregate_metrics(successful, self.k_values),
            total_latency_ms=round((time.perf_counter() - total_start) * 1000, 2),
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            config_snapshot=config_snapshot,
            failed_count=failed_count,
        )
