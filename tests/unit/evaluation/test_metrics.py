"""Unit tests for retrieval evaluation metrics."""

from __future__ import annotations

import pytest

from ate_rag_kb.chunking.models import Chunk, ChunkType
from ate_rag_kb.evaluation.metrics import (
    hit_at_k,
    mrr_at_k,
    recall_at_k,
    source_precision_at_k,
)


def _chunks(*ids: str) -> list[tuple[Chunk, float]]:
    return [(Chunk(id=cid, content="test", chunk_type=ChunkType.PARAGRAPH), 0.5) for cid in ids]


class TestHitAtK:
    def test_perfect_hit(self) -> None:
        retrieved = _chunks("a", "b", "c")
        assert hit_at_k(retrieved, ["b"], 3) == 1.0

    def test_no_hit(self) -> None:
        retrieved = _chunks("a", "b", "c")
        assert hit_at_k(retrieved, ["d"], 3) == 0.0

    def test_hit_only_in_top_k(self) -> None:
        retrieved = _chunks("a", "b", "c", "d")
        assert hit_at_k(retrieved, ["d"], 3) == 0.0
        assert hit_at_k(retrieved, ["d"], 4) == 1.0

    def test_empty_expected(self) -> None:
        retrieved = _chunks("a", "b")
        assert hit_at_k(retrieved, [], 2) == 0.0

    def test_k_zero(self) -> None:
        retrieved = _chunks("a", "b")
        assert hit_at_k(retrieved, ["a"], 0) == 0.0

    def test_multiple_expected_one_hit(self) -> None:
        retrieved = _chunks("a", "b", "c")
        assert hit_at_k(retrieved, ["b", "d"], 3) == 1.0


class TestRecallAtK:
    def test_perfect_recall(self) -> None:
        retrieved = _chunks("a", "b", "c")
        assert recall_at_k(retrieved, ["a", "b"], 3) == 1.0

    def test_partial_recall(self) -> None:
        retrieved = _chunks("a", "b", "c")
        assert recall_at_k(retrieved, ["a", "d"], 3) == 0.5

    def test_no_recall(self) -> None:
        retrieved = _chunks("a", "b", "c")
        assert recall_at_k(retrieved, ["d", "e"], 3) == 0.0

    def test_empty_expected(self) -> None:
        retrieved = _chunks("a", "b")
        assert recall_at_k(retrieved, [], 2) == 0.0

    def test_k_limits_scope(self) -> None:
        retrieved = _chunks("a", "b", "c", "d")
        assert recall_at_k(retrieved, ["a", "d"], 2) == 0.5


class TestMrrAtK:
    def test_first_rank(self) -> None:
        retrieved = _chunks("a", "b", "c")
        assert mrr_at_k(retrieved, ["a"], 3) == 1.0

    def test_second_rank(self) -> None:
        retrieved = _chunks("a", "b", "c")
        assert mrr_at_k(retrieved, ["b"], 3) == 0.5

    def test_no_match(self) -> None:
        retrieved = _chunks("a", "b", "c")
        assert mrr_at_k(retrieved, ["d"], 3) == 0.0

    def test_k_limits_scope(self) -> None:
        retrieved = _chunks("a", "b", "c")
        assert mrr_at_k(retrieved, ["c"], 2) == 0.0
        assert mrr_at_k(retrieved, ["c"], 3) == pytest.approx(1 / 3)

    def test_empty_expected(self) -> None:
        retrieved = _chunks("a", "b")
        assert mrr_at_k(retrieved, [], 2) == 0.0


class TestSourcePrecisionAtK:
    def test_perfect_precision(self) -> None:
        chunk1 = Chunk(id="c1", content="x", chunk_type=ChunkType.PARAGRAPH, source_md="doc1.md")
        chunk2 = Chunk(id="c2", content="y", chunk_type=ChunkType.PARAGRAPH, source_md="doc1.md")
        retrieved = [(chunk1, 0.5), (chunk2, 0.4)]
        assert source_precision_at_k(retrieved, ["doc1.md"], 2) == 1.0

    def test_partial_precision(self) -> None:
        chunk1 = Chunk(id="c1", content="x", chunk_type=ChunkType.PARAGRAPH, source_md="doc1.md")
        chunk2 = Chunk(id="c2", content="y", chunk_type=ChunkType.PARAGRAPH, source_md="doc2.md")
        retrieved = [(chunk1, 0.5), (chunk2, 0.4)]
        assert source_precision_at_k(retrieved, ["doc1.md"], 2) == 0.5

    def test_no_match(self) -> None:
        chunk1 = Chunk(id="c1", content="x", chunk_type=ChunkType.PARAGRAPH, source_md="doc2.md")
        retrieved = [(chunk1, 0.5)]
        assert source_precision_at_k(retrieved, ["doc1.md"], 1) == 0.0

    def test_empty_expected(self) -> None:
        retrieved = _chunks("a")
        assert source_precision_at_k(retrieved, [], 1) == 0.0

    def test_k_zero(self) -> None:
        chunk1 = Chunk(id="c1", content="x", chunk_type=ChunkType.PARAGRAPH, source_md="doc1.md")
        retrieved = [(chunk1, 0.5)]
        assert source_precision_at_k(retrieved, ["doc1.md"], 0) == 0.0
