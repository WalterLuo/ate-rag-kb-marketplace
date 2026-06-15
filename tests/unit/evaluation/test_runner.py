"""Unit tests for evaluation runner."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from ate_rag_kb.chunking.models import Chunk, ChunkType
from ate_rag_kb.evaluation.models import EvalQuestion, QuestionFailure, QuestionResult
from ate_rag_kb.evaluation.runner import EvalRunner


def _make_chunk(cid: str, source_md: str = "doc.md") -> Chunk:
    return Chunk(
        id=cid,
        content="test",
        chunk_type=ChunkType.PARAGRAPH,
        source_md=source_md,
    )


class TestEvalRunner:
    @pytest.mark.asyncio
    async def test_successful_run(self) -> None:
        pipeline = AsyncMock()
        pipeline.search.return_value = [
            (_make_chunk("c1"), 0.9),
            (_make_chunk("c2"), 0.8),
        ]

        question = EvalQuestion(
            id="q1",
            query="test",
            expected_chunk_ids=("c1",),
            expected_source_mds=("doc.md",),
        )

        runner = EvalRunner(k_values=[1, 2])
        report = await runner.run(pipeline, [question], config_snapshot={"model": "test"})

        assert report.failed_count == 0
        assert len(report.results) == 1
        result = report.results[0]
        assert isinstance(result, QuestionResult)
        assert result.hit_at_k[1] == 1.0
        assert result.hit_at_k[2] == 1.0
        assert result.recall_at_k[1] == 1.0
        assert result.mrr_at_k[1] == 1.0
        assert result.source_precision_at_k[1] == 1.0
        assert report.aggregated_metrics["hit_at_k"][1] == 1.0

    @pytest.mark.asyncio
    async def test_failed_question_isolated(self) -> None:
        pipeline = AsyncMock()
        pipeline.search.side_effect = [RuntimeError("boom")]

        question = EvalQuestion(id="q1", query="test")
        runner = EvalRunner(k_values=[1])
        report = await runner.run(pipeline, [question], config_snapshot={})

        assert report.failed_count == 1
        result = report.results[0]
        assert isinstance(result, QuestionFailure)
        assert result.error == "boom"
        assert report.aggregated_metrics == {}

    @pytest.mark.asyncio
    async def test_mixed_success_and_failure(self) -> None:
        pipeline = AsyncMock()
        pipeline.search.side_effect = [
            [(_make_chunk("c1"), 0.9)],
            RuntimeError("fail"),
        ]

        q1 = EvalQuestion(id="q1", query="ok", expected_chunk_ids=("c1",))
        q2 = EvalQuestion(id="q2", query="bad")
        runner = EvalRunner(k_values=[1])
        report = await runner.run(pipeline, [q1, q2], config_snapshot={})

        assert report.failed_count == 1
        assert len(report.results) == 2
        assert isinstance(report.results[0], QuestionResult)
        assert isinstance(report.results[1], QuestionFailure)
        assert report.aggregated_metrics["hit_at_k"][1] == 1.0

    @pytest.mark.asyncio
    async def test_default_k_values(self) -> None:
        pipeline = AsyncMock()
        pipeline.search.return_value = []
        runner = EvalRunner()
        report = await runner.run(pipeline, [], config_snapshot={})
        assert runner.k_values == [1, 3, 5, 10]
        assert report.aggregated_metrics == {}

    @pytest.mark.asyncio
    async def test_latency_recorded(self) -> None:
        pipeline = AsyncMock()
        pipeline.search.return_value = []
        question = EvalQuestion(id="q1", query="test")
        runner = EvalRunner(k_values=[1])
        report = await runner.run(pipeline, [question], config_snapshot={})
        result = report.results[0]
        assert isinstance(result, QuestionResult)
        assert result.latency_ms >= 0
        assert report.total_latency_ms >= 0
