"""Unit tests for context compression."""

from __future__ import annotations

from ate_rag_kb.chunking.models import Chunk, ChunkType
from ate_rag_kb.retrieval.compression import ContextCompressor


class TestContextCompressor:
    def test_empty_list_returns_empty(self) -> None:
        comp = ContextCompressor()

        assert comp.compress([]) == []

    def test_deduplication_removes_duplicate_ids(self) -> None:
        comp = ContextCompressor()
        chunks = [
            Chunk(id="a", content="first", chunk_type=ChunkType.PARAGRAPH, source_md="a.md"),
            Chunk(id="a", content="first", chunk_type=ChunkType.PARAGRAPH, source_md="a.md"),
            Chunk(id="b", content="second", chunk_type=ChunkType.PARAGRAPH, source_md="b.md"),
        ]

        result = comp.compress(chunks)

        assert len(result) == 2
        assert {c.id for c in result} == {"a", "b"}

    def test_merge_adjacent_same_source_and_section(self) -> None:
        comp = ContextCompressor()
        chunks = [
            Chunk(
                id="m1",
                content="Hello",
                chunk_type=ChunkType.PARAGRAPH,
                source_md="doc.md",
                section_title="Sec",
                end_line=10,
            ),
            Chunk(
                id="m2",
                content="world",
                chunk_type=ChunkType.PARAGRAPH,
                source_md="doc.md",
                section_title="Sec",
                end_line=20,
            ),
        ]

        result = comp.compress(chunks)

        assert len(result) == 1
        assert result[0].content == "Hello\n\nworld"
        assert result[0].end_line == 20

    def test_merge_skips_different_source(self) -> None:
        comp = ContextCompressor()
        chunks = [
            Chunk(
                id="m1",
                content="Hello",
                chunk_type=ChunkType.PARAGRAPH,
                source_md="a.md",
                section_title="Sec",
            ),
            Chunk(
                id="m2",
                content="world",
                chunk_type=ChunkType.PARAGRAPH,
                source_md="b.md",
                section_title="Sec",
            ),
        ]

        result = comp.compress(chunks)

        assert len(result) == 2

    def test_truncation_respects_max_tokens(self) -> None:
        comp = ContextCompressor(config=None)
        comp.max_tokens = 200  # ~800 chars
        long_text = "a" * 2000
        chunks = [Chunk(id="t1", content=long_text, chunk_type=ChunkType.PARAGRAPH)]

        result = comp.compress(chunks)

        assert len(result) == 1
        assert len(result[0].content) <= 800

    def test_truncation_breaks_when_no_room(self) -> None:
        comp = ContextCompressor()
        comp.max_tokens = 1
        chunks = [
            Chunk(id="t1", content="a" * 100, chunk_type=ChunkType.PARAGRAPH),
            Chunk(id="t2", content="b" * 100, chunk_type=ChunkType.PARAGRAPH),
        ]

        result = comp.compress(chunks)

        assert len(result) <= 1
