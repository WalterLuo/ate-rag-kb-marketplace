"""Unit tests for chunking data models."""

from __future__ import annotations

from ate_rag_kb.chunking.models import Chunk, ChunkType


class TestChunk:
    def test_to_payload_returns_expected_keys(self) -> None:
        chunk = Chunk(
            id="abc123",
            content="Hello world",
            chunk_type=ChunkType.PARAGRAPH,
            doc_title="Test Doc",
            section_title="Section 1",
            platform="TDC",
            doc_type="guide",
            tags=["tag1", "tag2"],
            ecosystem="v93000",
            software_version="smt7",
            doc_family="tdc",
            release_version="2024.1",
        )
        payload = chunk.to_payload()

        assert payload["doc_title"] == "Test Doc"
        assert payload["section_title"] == "Section 1"
        assert payload["chunk_type"] == "paragraph"
        assert payload["platform"] == "TDC"
        assert payload["doc_type"] == "guide"
        assert payload["tags"] == ["tag1", "tag2"]
        assert payload["ecosystem"] == "v93000"
        assert payload["software_version"] == "smt7"
        assert payload["doc_family"] == "tdc"
        assert payload["release_version"] == "2024.1"
        assert "content" not in payload

    def test_to_payload_excludes_score(self) -> None:
        chunk = Chunk(
            id="id1",
            content="text",
            chunk_type=ChunkType.SECTION,
            score=0.95,
        )
        payload = chunk.to_payload()

        assert "score" not in payload

    def test_canonical_metadata_round_trip(self) -> None:
        chunk = Chunk(
            id="canonical",
            content="metadata",
            chunk_type=ChunkType.PARAGRAPH,
            vendor="teradyne",
            platform="j750",
            software="igxl",
        )

        payload = chunk.to_payload()

        assert payload["vendor"] == "teradyne"
        assert payload["platform"] == "j750"
        assert payload["software"] == "igxl"
        assert payload["software_release"] == ""
        reconstructed = Chunk.from_payload(chunk.id, payload)
        assert reconstructed.vendor == "teradyne"
        assert reconstructed.platform == "j750"
        assert reconstructed.software == "igxl"
        assert reconstructed.software_release == ""

    def test_from_payload_reconstructs_chunk(self) -> None:
        payload = {
            "content": "reconstructed content",
            "chunk_type": "code_block",
            "doc_title": "API Ref",
            "platform": "J750",
            "score": 0.88,
            "tags": ["api", "reference"],
            "parent_id": "parent1",
            "ecosystem": "v93000",
            "software_version": "smt7",
            "doc_family": "tdc",
            "release_version": "2024.1",
        }
        chunk = Chunk.from_payload("chunk_id_1", payload)

        assert chunk.id == "chunk_id_1"
        assert chunk.content == "reconstructed content"
        assert chunk.chunk_type == ChunkType.CODE_BLOCK
        assert chunk.doc_title == "API Ref"
        assert chunk.platform == "J750"
        assert chunk.score == 0.88
        assert chunk.tags == ["api", "reference"]
        assert chunk.parent_id == "parent1"
        assert chunk.ecosystem == "v93000"
        assert chunk.software_version == "smt7"
        assert chunk.doc_family == "tdc"
        assert chunk.release_version == "2024.1"

    def test_from_payload_uses_defaults_for_missing_fields(self) -> None:
        payload = {"content": "minimal"}
        chunk = Chunk.from_payload("id2", payload)

        assert chunk.chunk_type == ChunkType.PARAGRAPH
        assert chunk.platform == ""
        assert chunk.doc_type == ""
        assert chunk.tags == []
        assert chunk.score == 0.0

    def test_chunk_type_enum_values(self) -> None:
        assert ChunkType.DOCUMENT == "document"
        assert ChunkType.SECTION == "section"
        assert ChunkType.CODE_BLOCK == "code_block"
        assert ChunkType.TABLE == "table"


class TestChunkRelationships:
    def test_parent_child_ids_round_trip(self) -> None:
        _ = Chunk(id="p1", content="Parent", chunk_type=ChunkType.DOCUMENT)
        child = Chunk(
            id="c1",
            content="Child",
            chunk_type=ChunkType.SECTION,
            parent_id="p1",
        )

        assert child.parent_id == "p1"
        assert child.id == "c1"

    def test_sibling_ids_round_trip(self) -> None:
        chunk = Chunk(
            id="s1",
            content="Sibling",
            chunk_type=ChunkType.PARAGRAPH,
            sibling_ids=["s2", "s3"],
        )

        assert chunk.sibling_ids == ["s2", "s3"]
