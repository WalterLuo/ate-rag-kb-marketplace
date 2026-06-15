"""ATE RAG KB retrieval evaluation system."""

from __future__ import annotations

from ate_rag_kb.evaluation.dataset_loader import DatasetLoader
from ate_rag_kb.evaluation.formatters import (
    format_json,
    format_markdown,
    write_json,
    write_markdown,
)
from ate_rag_kb.evaluation.metrics import hit_at_k, mrr_at_k, recall_at_k, source_precision_at_k
from ate_rag_kb.evaluation.models import EvalQuestion, EvalReport, QuestionFailure, QuestionResult
from ate_rag_kb.evaluation.runner import EvalRunner

__all__ = [
    "DatasetLoader",
    "EvalQuestion",
    "EvalReport",
    "EvalRunner",
    "QuestionFailure",
    "QuestionResult",
    "format_json",
    "format_markdown",
    "hit_at_k",
    "mrr_at_k",
    "recall_at_k",
    "source_precision_at_k",
    "write_json",
    "write_markdown",
]
