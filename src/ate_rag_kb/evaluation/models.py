"""Data models for the retrieval evaluation system."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ate_rag_kb.chunking.models import Chunk


@dataclass(frozen=True)
class EvalQuestion:
    """A single evaluation question with ground-truth annotations."""

    id: str
    query: str
    expected_chunk_ids: tuple[str, ...] = ()
    expected_source_mds: tuple[str, ...] = ()
    category: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class QuestionResult:
    """Successful evaluation result for a single question."""

    question: EvalQuestion
    retrieved_chunks: tuple[tuple[Chunk, float], ...]
    hit_at_k: dict[int, float]
    recall_at_k: dict[int, float]
    mrr_at_k: dict[int, float]
    source_precision_at_k: dict[int, float]
    latency_ms: float


@dataclass(frozen=True)
class QuestionFailure:
    """Failed evaluation attempt for a single question."""

    question: EvalQuestion
    error: str
    latency_ms: float


@dataclass(frozen=True)
class EvalReport:
    """Aggregated evaluation report across all questions."""

    questions: tuple[EvalQuestion, ...]
    results: tuple[QuestionResult | QuestionFailure, ...]
    aggregated_metrics: dict[str, dict[int, float]]
    total_latency_ms: float
    timestamp: str
    config_snapshot: dict[str, Any]
    failed_count: int
