"""Unit tests for hierarchical chunking strategy."""

from __future__ import annotations

import pytest

from ate_rag_kb.chunking.models import ChunkType
from ate_rag_kb.chunking.strategies import HierarchicalChunker


class TestHierarchicalChunker:
    @pytest.fixture
    def chunker(self) -> HierarchicalChunker:
        return HierarchicalChunker()

    def test_chunk_empty_document(self, chunker: HierarchicalChunker) -> None:
        result = chunker.chunk("", metadata={"doc_title": "Empty"})

        assert len(result) == 2
        assert result[0].chunk_type == ChunkType.DOCUMENT
        assert result[1].chunk_type == ChunkType.SECTION

    def test_chunk_with_headings(self, chunker: HierarchicalChunker) -> None:
        text = "# Title\n\nIntro paragraph.\n\n## Section A\n\nContent A.\n\n## Section B\n\nContent B."
        result = chunker.chunk(text, metadata={"doc_title": "Test"})

        sections = [c for c in result if c.chunk_type in (ChunkType.SECTION, ChunkType.SUBSECTION)]
        assert len(sections) == 3  # h1 Title + h2 Section A + h2 Section B
        assert any("Section A" in c.content for c in sections)
        assert any("Section B" in c.content for c in sections)

    def test_parent_linking(self, chunker: HierarchicalChunker) -> None:
        text = "# Doc\n\n## Sec 1\n\nBody."
        result = chunker.chunk(text, metadata={"doc_title": "Doc"})

        doc_chunk = next(c for c in result if c.chunk_type == ChunkType.DOCUMENT)
        sec_chunk = next(c for c in result if c.chunk_type == ChunkType.SECTION)

        assert sec_chunk.parent_id == doc_chunk.id
        assert sec_chunk.id in doc_chunk.child_ids

    def test_code_block_extraction(self, chunker: HierarchicalChunker) -> None:
        text = "```python\nprint('hello')\n```"
        result = chunker.chunk(text, metadata={"doc_title": "Code"})

        code_chunks = [c for c in result if c.chunk_type == ChunkType.CODE_BLOCK]
        assert len(code_chunks) == 1
        assert "print('hello')" in code_chunks[0].content
        assert code_chunks[0].code_blocks[0]["language"] == "python"

    def test_table_extraction(self, chunker: HierarchicalChunker) -> None:
        text = "| Name | Value |\n|------|-------|\n| A | 1 |\n| B | 2 |"
        result = chunker.chunk(text, metadata={"doc_title": "Table"})

        table_chunks = [c for c in result if c.chunk_type == ChunkType.TABLE]
        assert len(table_chunks) == 1
        assert table_chunks[0].tables[0]["headers"] == ["Name", "Value"]
        assert len(table_chunks[0].tables[0]["rows"]) == 2

    def test_image_extraction(self, chunker: HierarchicalChunker) -> None:
        text = "![Alt text](path/to/image.png)"
        result = chunker.chunk(text, metadata={"doc_title": "Image"})

        img_chunks = [c for c in result if c.chunk_type == ChunkType.IMAGE]
        assert len(img_chunks) == 1
        assert img_chunks[0].images[0]["path"] == "path/to/image.png"
        assert img_chunks[0].images[0]["alt"] == "Alt text"

    def test_deterministic_ids(self, chunker: HierarchicalChunker) -> None:
        text = "# Title\n\nBody."
        meta = {"doc_title": "Doc", "source_md": "doc.md"}

        r1 = chunker.chunk(text, meta)
        r2 = chunker.chunk(text, meta)

        ids1 = {c.id for c in r1}
        ids2 = {c.id for c in r2}
        assert ids1 == ids2

    def test_sibling_linking(self, chunker: HierarchicalChunker) -> None:
        text = "# Doc\n\n## Sec 1\n\nA.\n\n## Sec 2\n\nB."
        result = chunker.chunk(text, metadata={"doc_title": "Doc"})

        sections = [c for c in result if c.chunk_type == ChunkType.SECTION]
        assert len(sections) == 3  # h1 Doc + h2 Sec 1 + h2 Sec 2

        # The two h2 sections are siblings under the h1
        h2_sections = [c for c in sections if c.heading_level == 2]
        assert len(h2_sections) == 2
        s1, s2 = h2_sections
        assert s2.id in s1.sibling_ids
        assert s1.id in s2.sibling_ids

    def test_document_chunk_respects_config_max_length(self) -> None:
        from ate_rag_kb.utils.config import Config

        config = Config({
            "chunking": {
                "strategies": {
                    "document": {"max_length": 50, "overlap": 0},
                }
            }
        })
        chunker = HierarchicalChunker(config)
        long_text = "A" * 200
        result = chunker.chunk(long_text, metadata={"doc_title": "Long"})

        doc_chunk = next(c for c in result if c.chunk_type == ChunkType.DOCUMENT)
        assert len(doc_chunk.content) <= 50

    def test_section_chunk_respects_config_max_length(self) -> None:
        from ate_rag_kb.utils.config import Config

        config = Config({
            "chunking": {
                "strategies": {
                    "section": {"max_length": 30, "overlap": 0},
                }
            }
        })
        chunker = HierarchicalChunker(config)
        text = "# Title\n\n" + "B" * 100
        result = chunker.chunk(text, metadata={"doc_title": "LongSec"})

        sec_chunk = next(c for c in result if c.chunk_type == ChunkType.SECTION)
        assert len(sec_chunk.content) <= 30

    def test_default_limits_without_config(self) -> None:
        chunker = HierarchicalChunker()
        assert chunker._get_limit(ChunkType.DOCUMENT) == (8000, 200)
        assert chunker._get_limit(ChunkType.SECTION) == (4000, 100)
        assert chunker._get_limit(ChunkType.SUBSECTION) == (2000, 50)

    def test_truncate_content_prefers_paragraph_boundary(self) -> None:
        text = "Line1\n\nLine2\n\nLine3\n\nLine4"
        result = HierarchicalChunker._truncate_content(text, 14)
        # Should truncate at the paragraph boundary before 14 chars
        assert result == "Line1\n\nLine2"

    def test_truncate_content_no_boundary_falls_back_to_hard_limit(self) -> None:
        text = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        result = HierarchicalChunker._truncate_content(text, 10)
        assert result == "ABCDEFGHIJ"
