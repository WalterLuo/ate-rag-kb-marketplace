"""Unit tests for evaluation report formatters."""

from __future__ import annotations

from pathlib import Path

from ate_rag_kb.chunking.models import Chunk, ChunkType
from ate_rag_kb.evaluation.formatters import (
    format_json,
    format_markdown,
    write_json,
    write_markdown,
)
from ate_rag_kb.evaluation.models import EvalQuestion, EvalReport, QuestionFailure, QuestionResult


def _make_question_result() -> QuestionResult:
    chunk = Chunk(
        id="c1",
        content="This is a test chunk with enough content to verify truncation behavior.",
        chunk_type=ChunkType.PARAGRAPH,
        source_md="doc1.md",
        platform="TDC",
        doc_title="Test Doc",
        section_title="Section 1",
    )
    question = EvalQuestion(
        id="q1",
        query="How to test?",
        expected_chunk_ids=("c1",),
        expected_source_mds=("doc1.md",),
        category="Test",
    )
    return QuestionResult(
        question=question,
        retrieved_chunks=((chunk, 0.95),),
        hit_at_k={1: 1.0, 3: 1.0},
        recall_at_k={1: 1.0, 3: 1.0},
        mrr_at_k={1: 1.0, 3: 1.0},
        source_precision_at_k={1: 1.0, 3: 1.0},
        latency_ms=42.0,
    )


def _make_question_failure() -> QuestionFailure:
    question = EvalQuestion(id="q2", query="Bad query")
    return QuestionFailure(question=question, error="Connection refused", latency_ms=10.0)


def _make_report() -> EvalReport:
    return EvalReport(
        questions=(_make_question_result().question, _make_question_failure().question),
        results=(_make_question_result(), _make_question_failure()),
        aggregated_metrics={
            "hit_at_k": {1: 0.5, 3: 0.5},
            "recall_at_k": {1: 0.5, 3: 0.5},
            "mrr_at_k": {1: 0.5, 3: 0.5},
            "source_precision_at_k": {1: 0.5, 3: 0.5},
        },
        total_latency_ms=100.0,
        timestamp="2026-05-21T12:00:00Z",
        config_snapshot={"model": "test"},
        failed_count=1,
    )


class TestFormatJson:
    def test_contains_summary(self) -> None:
        report = _make_report()
        data = format_json(report)
        summary = data["summary"]
        assert summary["total_questions"] == 2
        assert summary["successful"] == 1
        assert summary["failed"] == 1
        assert summary["total_latency_ms"] == 100.0

    def test_contains_questions(self) -> None:
        report = _make_report()
        data = format_json(report)
        assert len(data["questions"]) == 2
        assert data["questions"][0]["status"] == "success"
        assert data["questions"][1]["status"] == "failed"

    def test_success_question_has_metrics(self) -> None:
        report = _make_report()
        data = format_json(report)
        q = data["questions"][0]
        assert "metrics" in q
        assert q["metrics"]["hit_at_k"][1] == 1.0

    def test_failure_question_has_error(self) -> None:
        report = _make_report()
        data = format_json(report)
        q = data["questions"][1]
        assert q["error"] == "Connection refused"

    def test_empty_report(self) -> None:
        report = EvalReport(
            questions=(),
            results=(),
            aggregated_metrics={},
            total_latency_ms=0.0,
            timestamp="2026-05-21T12:00:00Z",
            config_snapshot={},
            failed_count=0,
        )
        data = format_json(report)
        assert data["summary"]["total_questions"] == 0
        assert data["summary"]["avg_latency_ms"] == 0.0


class TestWriteJson:
    def test_creates_file(self, tmp_path: Path) -> None:
        report = _make_report()
        path = tmp_path / "report.json"
        write_json(report, path)
        assert path.exists()
        assert "hit_at_k" in path.read_text(encoding="utf-8")


class TestFormatMarkdown:
    def test_contains_header(self) -> None:
        report = _make_report()
        md = format_markdown(report)
        assert "# Retrieval Evaluation Report" in md

    def test_contains_aggregated_metrics(self) -> None:
        report = _make_report()
        md = format_markdown(report)
        assert "## Aggregated Metrics" in md
        assert "hit_at_k" in md

    def test_contains_failures(self) -> None:
        report = _make_report()
        md = format_markdown(report)
        assert "## Failures" in md
        assert "Connection refused" in md

    def test_no_failures_section_when_none(self) -> None:
        report = EvalReport(
            questions=(_make_question_result().question,),
            results=(_make_question_result(),),
            aggregated_metrics={},
            total_latency_ms=10.0,
            timestamp="2026-05-21T12:00:00Z",
            config_snapshot={},
            failed_count=0,
        )
        md = format_markdown(report)
        assert "## Failures" not in md


class TestWriteMarkdown:
    def test_creates_file(self, tmp_path: Path) -> None:
        report = _make_report()
        path = tmp_path / "report.md"
        write_markdown(report, path)
        assert path.exists()
        assert "# Retrieval Evaluation Report" in path.read_text(encoding="utf-8")
