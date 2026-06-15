"""Unit tests for MCP context builder."""

from __future__ import annotations

from ate_rag_kb.chunking.models import Chunk, ChunkType
from ate_rag_kb.mcp.context_builder import (
    _chunk_to_mcp,
    build_context_package,
    build_sources_summary,
    compute_confidence,
)
from ate_rag_kb.mcp.models import McpChunkResult


class TestContextBuilder:
    def _make_chunk(
        self,
        chunk_id: str = "c1",
        content: str = "hello world",
        score: float = 0.9,
        source_md: str = "doc.md",
        doc_title: str = "Doc",
        section_title: str = "Sec",
        platform: str = "TDC",
        start_line: int = 1,
        end_line: int = 5,
    ) -> Chunk:
        return Chunk(
            id=chunk_id,
            content=content,
            chunk_type=ChunkType.PARAGRAPH,
            source_md=source_md,
            doc_title=doc_title,
            section_title=section_title,
            platform=platform,
            start_line=start_line,
            end_line=end_line,
            score=score,
        )

    def test_chunk_to_mcp(self) -> None:
        chunk = self._make_chunk()
        result = _chunk_to_mcp(chunk, score=0.85, is_expanded=True)

        assert isinstance(result, McpChunkResult)
        assert result.id == "c1"
        assert result.score == 0.85
        assert result.is_expanded is True
        assert result.source_md == "doc.md"
        assert result.doc_title == "Doc"
        assert result.section_title == "Sec"
        assert result.start_line == 1
        assert result.end_line == 5
        assert result.platform == "TDC"

    def test_build_context_package(self) -> None:
        chunks = [
            (self._make_chunk(chunk_id="c1", content="First chunk."), 0.9),
            (self._make_chunk(chunk_id="c2", content="Second chunk."), 0.8),
        ]
        package = build_context_package(chunks)

        assert "[1]" in package.text
        assert "[2]" in package.text
        assert "First chunk." in package.text
        assert "Second chunk." in package.text
        assert len(package.citation_map) == 2
        assert package.citation_map[0]["chunk_id"] == "c1"
        assert package.citation_map[1]["chunk_id"] == "c2"
        assert package.token_estimate > 0

    def test_build_context_package_respects_max_tokens(self) -> None:
        long_content = "word " * 2000  # ~8000 chars
        chunks = [
            (self._make_chunk(chunk_id="c1", content=long_content), 0.9),
            (self._make_chunk(chunk_id="c2", content=long_content), 0.8),
        ]
        package = build_context_package(chunks, max_tokens=100)

        # Should stop early due to token budget
        assert len(package.citation_map) == 1
        assert package.citation_map[0]["chunk_id"] == "c1"

    def test_build_sources_summary(self) -> None:
        chunks = [
            McpChunkResult(id="c1", content="a", score=0.9, source_md="a.md"),
            McpChunkResult(id="c2", content="b", score=0.8, source_md="a.md"),
            McpChunkResult(id="c3", content="c", score=0.7, source_md="b.md"),
        ]
        sources = build_sources_summary(chunks)

        assert len(sources) == 2
        assert sources[0]["source_md"] == "a.md"
        assert sources[0]["chunk_count"] == 2
        assert sources[0]["top_score"] == 0.9
        assert sources[1]["source_md"] == "b.md"
        assert sources[1]["chunk_count"] == 1

    def test_compute_confidence_high(self) -> None:
        chunks = [
            McpChunkResult(id="c1", content="a", score=0.9, source_md="x.md"),
            McpChunkResult(id="c2", content="b", score=0.7, source_md="x.md"),
            McpChunkResult(id="c3", content="c", score=0.6, source_md="x.md"),
        ]
        assert compute_confidence(chunks) == "high"

    def test_compute_confidence_medium(self) -> None:
        chunks = [
            McpChunkResult(id="c1", content="a", score=0.6, source_md="x.md"),
        ]
        assert compute_confidence(chunks) == "medium"

    def test_compute_confidence_low(self) -> None:
        chunks = [
            McpChunkResult(id="c1", content="a", score=0.3, source_md="x.md"),
        ]
        assert compute_confidence(chunks) == "low"

    def test_compute_confidence_empty(self) -> None:
        assert compute_confidence([]) == "low"
