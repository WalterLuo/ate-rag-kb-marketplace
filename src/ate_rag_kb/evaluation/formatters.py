"""Output formatters for evaluation reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ate_rag_kb.evaluation.models import EvalReport, QuestionFailure, QuestionResult


def _truncate(text: str, max_len: int = 300) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len].rsplit(" ", 1)[0] + " ..."


def format_json(report: EvalReport) -> dict[str, Any]:
    """Convert an EvalReport into a plain dict suitable for JSON serialization."""
    questions: list[dict[str, Any]] = []
    for result in report.results:
        if isinstance(result, QuestionFailure):
            questions.append(
                {
                    "id": result.question.id,
                    "query": result.question.query,
                    "category": result.question.category,
                    "status": "failed",
                    "error": result.error,
                    "latency_ms": result.latency_ms,
                }
            )
        else:
            top_results = []
            for chunk, score in result.retrieved_chunks:
                top_results.append(
                    {
                        "score": round(float(score), 6),
                        "chunk_type": chunk.chunk_type.value,
                        "platform": chunk.platform,
                        "doc_title": chunk.doc_title,
                        "section_title": chunk.section_title,
                        "source_md": chunk.source_md,
                        "content_preview": _truncate(chunk.content, 400),
                    }
                )
            questions.append(
                {
                    "id": result.question.id,
                    "query": result.question.query,
                    "category": result.question.category,
                    "status": "success",
                    "latency_ms": result.latency_ms,
                    "metrics": {
                        "hit_at_k": {k: round(v, 4) for k, v in result.hit_at_k.items()},
                        "recall_at_k": {k: round(v, 4) for k, v in result.recall_at_k.items()},
                        "mrr_at_k": {k: round(v, 4) for k, v in result.mrr_at_k.items()},
                        "source_precision_at_k": {
                            k: round(v, 4) for k, v in result.source_precision_at_k.items()
                        },
                    },
                    "top_results": top_results,
                }
            )

    aggregated = {}
    for metric_name, values in report.aggregated_metrics.items():
        aggregated[metric_name] = {k: round(v, 4) for k, v in values.items()}

    return {
        "summary": {
            "total_questions": len(report.questions),
            "successful": len(report.questions) - report.failed_count,
            "failed": report.failed_count,
            "total_latency_ms": report.total_latency_ms,
            "avg_latency_ms": (
                round(report.total_latency_ms / len(report.questions), 2)
                if report.questions
                else 0.0
            ),
            "aggregated_metrics": aggregated,
        },
        "config_snapshot": report.config_snapshot,
        "timestamp": report.timestamp,
        "questions": questions,
    }


def write_json(report: EvalReport, path: Path) -> None:
    """Serialize report to indented JSON."""
    data = format_json(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def format_markdown(report: EvalReport) -> str:
    """Render a concise Markdown summary of the report."""
    lines: list[str] = [
        "# Retrieval Evaluation Report",
        "",
        f"- **Timestamp:** {report.timestamp}",
        f"- **Total Questions:** {len(report.questions)}",
        f"- **Successful:** {len(report.questions) - report.failed_count}",
        f"- **Failed:** {report.failed_count}",
        f"- **Total Latency:** {report.total_latency_ms} ms",
        "",
        "## Aggregated Metrics",
        "",
    ]

    for metric_name, values in report.aggregated_metrics.items():
        lines.append(f"### {metric_name}")
        for k in sorted(values):
            lines.append(f"- @ {k}: {round(values[k], 4)}")
        lines.append("")

    if report.failed_count:
        lines.append("## Failures")
        lines.append("")
        for result in report.results:
            if isinstance(result, QuestionFailure):
                lines.append(f"- **{result.question.id}**: {result.error}")
        lines.append("")

    lines.append("## Per-Question Results")
    lines.append("")
    for result in report.results:
        if isinstance(result, QuestionResult):
            lines.append(f"### {result.question.id} — {result.question.query}")
            lines.append(f"- Latency: {result.latency_ms} ms")
            for metric_name in ["hit_at_k", "recall_at_k", "mrr_at_k", "source_precision_at_k"]:
                values = getattr(result, metric_name)
                vals = ", ".join(f"@{k}={round(values[k], 4)}" for k in sorted(values))
                lines.append(f"- {metric_name}: {vals}")
            lines.append("")

    return "\n".join(lines)


def write_markdown(report: EvalReport, path: Path) -> None:
    """Write Markdown report to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_markdown(report), encoding="utf-8")
