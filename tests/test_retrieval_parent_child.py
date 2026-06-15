"""Unit tests for parent-child expansion."""

from __future__ import annotations

from unittest.mock import MagicMock

from ate_rag_kb.chunking.models import Chunk, ChunkType
from ate_rag_kb.retrieval.parent_child import ParentChildExpander


class TestParentChildExpander:
    def test_expand_with_parent_and_siblings(self) -> None:
        store = MagicMock()
        store.get_by_ids.side_effect = lambda cids: [
            {
                "p1": Chunk(id="p1", content="Parent", chunk_type=ChunkType.SECTION),
                "s1": Chunk(id="s1", content="Sib1", chunk_type=ChunkType.PARAGRAPH),
                "s2": Chunk(id="s2", content="Sib2", chunk_type=ChunkType.PARAGRAPH),
            }.get(cid)
            for cid in cids
        ]

        expander = ParentChildExpander()
        chunks = [
            Chunk(
                id="c1",
                content="Child",
                chunk_type=ChunkType.PARAGRAPH,
                parent_id="p1",
                sibling_ids=["s1", "s2"],
            )
        ]

        result = expander.expand(chunks, store)
        ids = [c.id for c in result]

        assert ids[0] == "c1"
        assert "p1" in ids
        assert "s1" in ids
        assert "s2" in ids

    def test_expand_filters_related_chunks_by_scope(self) -> None:
        igxl_parent = Chunk(
            id="p1",
            content="IG-XL Parent",
            chunk_type=ChunkType.SECTION,
            vendor="teradyne",
            platform="j750",
            software="igxl",
        )
        smt7_sibling = Chunk(
            id="s1",
            content="SMT7 Sibling",
            chunk_type=ChunkType.PARAGRAPH,
            vendor="advantest",
            platform="v93000",
            software="smt7",
        )
        store = MagicMock()
        store.get_by_ids.side_effect = lambda cids: [
            {"p1": igxl_parent, "s1": smt7_sibling}.get(cid) for cid in cids
        ]

        expander = ParentChildExpander()
        chunks = [
            Chunk(
                id="c1",
                content="Child",
                chunk_type=ChunkType.PARAGRAPH,
                parent_id="p1",
                sibling_ids=["s1"],
                vendor="teradyne",
                platform="j750",
                software="igxl",
            )
        ]

        result = expander.expand(
            chunks,
            store,
            filters={"vendor": "teradyne", "platform": "j750", "software": "igxl"},
        )

        assert [chunk.id for chunk in result] == ["c1", "p1"]

    def test_expand_deduplicates(self) -> None:
        store = MagicMock()
        store.get_by_ids.return_value = []

        expander = ParentChildExpander()
        chunks = [
            Chunk(id="c1", content="A", chunk_type=ChunkType.PARAGRAPH),
            Chunk(id="c1", content="A", chunk_type=ChunkType.PARAGRAPH),
        ]

        result = expander.expand(chunks, store)

        assert len(result) == 1

    def test_expand_with_children(self) -> None:
        store = MagicMock()
        store.get_by_ids.side_effect = lambda cids: [
            {
                "child1": Chunk(id="child1", content="Child1", chunk_type=ChunkType.PARAGRAPH),
            }.get(cid)
            for cid in cids
        ]

        expander = ParentChildExpander()
        expander.include_children = True
        expander.include_parent = False
        expander.include_siblings = False

        chunks = [
            Chunk(
                id="c1",
                content="Parent",
                chunk_type=ChunkType.PARAGRAPH,
                child_ids=["child1"],
            )
        ]

        result = expander.expand(chunks, store)
        ids = [c.id for c in result]

        assert ids == ["c1", "child1"]

    def test_expand_respects_max_siblings(self) -> None:
        store = MagicMock()
        store.get_by_ids.side_effect = lambda cids: [
            Chunk(id=cid, content="Sib", chunk_type=ChunkType.PARAGRAPH)
            for cid in cids
        ]

        expander = ParentChildExpander()
        expander.max_siblings = 1
        chunks = [
            Chunk(
                id="c1",
                content="Child",
                chunk_type=ChunkType.PARAGRAPH,
                sibling_ids=["s1", "s2", "s3"],
            )
        ]

        result = expander.expand(chunks, store)
        sibling_ids = [c.id for c in result if c.id != "c1"]

        assert len(sibling_ids) == 1
