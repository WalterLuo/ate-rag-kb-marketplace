"""Tests for DocumentGraphExpander."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from ate_rag_kb.chunking.models import Chunk, ChunkType
from ate_rag_kb.retrieval.document_graph_expander import DocumentGraphExpander


class TestDocumentGraphExpander:
    def _make_graph_file(self, tmp_path: Path, graph: dict) -> Path:
        path = tmp_path / "document_graph.json"
        path.write_text(json.dumps(graph), encoding="utf-8")
        return path

    def _make_vector_store(self, chunks_by_source: dict[str, list[Chunk]]) -> MagicMock:
        store = MagicMock()

        def mock_scroll(*, filters, limit):
            source_md = filters.get("source_md", "")
            chunk_type = filters.get("chunk_type")
            chunks = chunks_by_source.get(source_md, [])
            if chunk_type:
                chunks = [c for c in chunks if c.chunk_type.value == chunk_type]
            return chunks[:limit], None

        store.scroll.side_effect = mock_scroll
        return store

    def test_one_hop_expansion(self, tmp_path: Path) -> None:
        graph = {
            "a.md": {
                "linked_source_mds": ["b.md"],
                "referenced_by_source_mds": [],
                "canonical_source_md": "a.md",
                "content_hash": "h1",
            },
            "b.md": {
                "linked_source_mds": [],
                "referenced_by_source_mds": [],
                "canonical_source_md": "b.md",
                "content_hash": "h2",
            },
        }
        graph_path = self._make_graph_file(tmp_path, graph)
        store = self._make_vector_store({
            "b.md": [Chunk(id="b1", content="b", chunk_type=ChunkType.PARAGRAPH, source_md="b.md")],
        })

        expander = DocumentGraphExpander(graph_path=graph_path)
        initial = [Chunk(id="a1", content="a", chunk_type=ChunkType.PARAGRAPH, source_md="a.md")]
        result, stats = expander.expand(initial, store)

        assert any(c.id == "b1" for c in result)
        assert stats["expanded_source_count"] == 1

    def test_graph_expansion_keeps_scope_filter(self, tmp_path: Path) -> None:
        graph = {
            "igxl/a.md": {
                "linked_source_mds": ["v93000/smt7/b.md"],
                "referenced_by_source_mds": [],
                "canonical_source_md": "igxl/a.md",
                "content_hash": "h1",
            },
            "v93000/smt7/b.md": {
                "linked_source_mds": [],
                "referenced_by_source_mds": [],
                "canonical_source_md": "v93000/smt7/b.md",
                "content_hash": "h2",
            },
        }
        graph_path = self._make_graph_file(tmp_path, graph)
        smt7_chunk = Chunk(
            id="smt7",
            content="SMT7",
            chunk_type=ChunkType.PARAGRAPH,
            source_md="v93000/smt7/b.md",
            vendor="advantest",
            platform="v93000",
            software="smt7",
        )
        store = MagicMock()

        def scroll(*, filters, limit):
            if filters.get("vendor") == "teradyne":
                return [], None
            return [smt7_chunk][:limit], None

        store.scroll.side_effect = scroll
        seed = Chunk(
            id="igxl",
            content="IG-XL",
            chunk_type=ChunkType.PARAGRAPH,
            source_md="igxl/a.md",
            vendor="teradyne",
            platform="j750",
            software="igxl",
        )
        expander = DocumentGraphExpander(graph_path=graph_path)

        result, _stats = expander.expand(
            [seed],
            store,
            filters={"vendor": "teradyne", "platform": "j750", "software": "igxl"},
        )

        assert {chunk.software for chunk in result} == {"igxl"}

    def test_referenced_by_expansion(self, tmp_path: Path) -> None:
        """Documents reachable only via referenced_by_source_mds can be expanded."""
        graph = {
            "a.md": {
                "linked_source_mds": [],
                "referenced_by_source_mds": ["b.md"],
                "canonical_source_md": "a.md",
                "content_hash": "h1",
            },
            "b.md": {
                "linked_source_mds": [],
                "referenced_by_source_mds": [],
                "canonical_source_md": "b.md",
                "content_hash": "h2",
            },
        }
        graph_path = self._make_graph_file(tmp_path, graph)
        store = self._make_vector_store({
            "b.md": [Chunk(id="b1", content="b", chunk_type=ChunkType.PARAGRAPH, source_md="b.md")],
        })

        expander = DocumentGraphExpander(graph_path=graph_path)
        initial = [Chunk(id="a1", content="a", chunk_type=ChunkType.PARAGRAPH, source_md="a.md")]
        result, stats = expander.expand(initial, store)

        assert any(c.id == "b1" for c in result)
        assert stats["expanded_source_count"] == 1

    def test_two_hop_budget(self, tmp_path: Path) -> None:
        graph = {
            "a.md": {
                "linked_source_mds": ["b.md"],
                "referenced_by_source_mds": [],
                "canonical_source_md": "a.md",
                "content_hash": "h1",
            },
            "b.md": {
                "linked_source_mds": ["c.md"],
                "referenced_by_source_mds": [],
                "canonical_source_md": "b.md",
                "content_hash": "h2",
            },
            "c.md": {
                "linked_source_mds": [],
                "referenced_by_source_mds": [],
                "canonical_source_md": "c.md",
                "content_hash": "h3",
            },
        }
        graph_path = self._make_graph_file(tmp_path, graph)
        store = self._make_vector_store({
            "b.md": [Chunk(id="b1", content="b", chunk_type=ChunkType.PARAGRAPH, source_md="b.md")],
            "c.md": [Chunk(id="c1", content="c", chunk_type=ChunkType.PARAGRAPH, source_md="c.md")],
        })

        # Default max_hops=1; broad concept allows 2
        expander = DocumentGraphExpander(graph_path=graph_path)
        initial = [Chunk(id="a1", content="a", chunk_type=ChunkType.PARAGRAPH, source_md="a.md")]

        # Not broad: only 1 hop
        result1, _ = expander.expand(initial, store, is_broad_concept=False)
        assert any(c.id == "b1" for c in result1)
        assert not any(c.id == "c1" for c in result1)

        # Broad: 2 hops
        result2, _ = expander.expand(initial, store, is_broad_concept=True)
        assert any(c.id == "c1" for c in result2)

    def test_bidirectional_two_hop_site_control_like(self, tmp_path: Path) -> None:
        """Simulate 100118 -> 100324 -> 21615 / 20264 structure."""
        graph = {
            "100118.md": {
                "linked_source_mds": [],
                "referenced_by_source_mds": ["100324.md"],
                "canonical_source_md": "100118.md",
                "content_hash": "h100118",
            },
            "100324.md": {
                "linked_source_mds": ["21615.md", "20264.md", "100118.md"],
                "referenced_by_source_mds": [],
                "canonical_source_md": "100324.md",
                "content_hash": "h100324",
            },
            "21615.md": {
                "linked_source_mds": [],
                "referenced_by_source_mds": [],
                "canonical_source_md": "21615.md",
                "content_hash": "h21615",
            },
            "20264.md": {
                "linked_source_mds": [],
                "referenced_by_source_mds": [],
                "canonical_source_md": "20264.md",
                "content_hash": "h20264",
            },
        }
        graph_path = self._make_graph_file(tmp_path, graph)
        store = self._make_vector_store({
            "100324.md": [Chunk(id="c100324", content="100324", chunk_type=ChunkType.PARAGRAPH, source_md="100324.md")],
            "21615.md": [Chunk(id="c21615", content="21615", chunk_type=ChunkType.PARAGRAPH, source_md="21615.md")],
            "20264.md": [Chunk(id="c20264", content="20264", chunk_type=ChunkType.PARAGRAPH, source_md="20264.md")],
        })

        expander = DocumentGraphExpander(graph_path=graph_path, broad_max_hops=2)
        initial = [Chunk(id="c100118", content="100118", chunk_type=ChunkType.PARAGRAPH, source_md="100118.md")]
        result, stats = expander.expand(initial, store, is_broad_concept=True)

        result_ids = {c.id for c in result}
        assert "c100324" in result_ids
        assert "c21615" in result_ids
        assert "c20264" in result_ids
        assert stats["expanded_source_count"] == 3

    def test_fanout_limit(self, tmp_path: Path) -> None:
        graph = {
            "a.md": {
                "linked_source_mds": ["b.md", "c.md", "d.md", "e.md", "f.md", "g.md"],
                "referenced_by_source_mds": [],
                "canonical_source_md": "a.md",
                "content_hash": "h1",
            },
            **{
                f"{k}.md": {"linked_source_mds": [], "referenced_by_source_mds": [], "canonical_source_md": f"{k}.md", "content_hash": f"h{k}"}
                for k in "bcdefg"
            },
        }
        graph_path = self._make_graph_file(tmp_path, graph)
        store = self._make_vector_store({})

        expander = DocumentGraphExpander(graph_path=graph_path, max_fanout=3)
        initial = [Chunk(id="a1", content="a", chunk_type=ChunkType.PARAGRAPH, source_md="a.md")]
        result, stats = expander.expand(initial, store)

        assert stats["expanded_source_count"] == 3

    def test_fanout_limit_applies_to_combined_forward_and_reverse_links(
        self, tmp_path: Path
    ) -> None:
        graph = {
            "a.md": {
                "linked_source_mds": ["b.md", "c.md"],
                "referenced_by_source_mds": ["d.md", "e.md"],
                "canonical_source_md": "a.md",
                "content_hash": "h1",
            },
            **{
                f"{name}.md": {
                    "linked_source_mds": [],
                    "referenced_by_source_mds": [],
                    "canonical_source_md": f"{name}.md",
                    "content_hash": f"h{name}",
                }
                for name in "bcde"
            },
        }
        graph_path = self._make_graph_file(tmp_path, graph)
        expander = DocumentGraphExpander(graph_path=graph_path, max_fanout=2)
        initial = [Chunk(id="a1", content="a", chunk_type=ChunkType.PARAGRAPH, source_md="a.md")]

        _, stats = expander.expand(initial, self._make_vector_store({}))

        assert stats["expanded_source_count"] == 2

    def test_broad_budget_is_shared_fairly_across_first_hop_sources(
        self, tmp_path: Path
    ) -> None:
        graph = {
            "seed.md": {
                "linked_source_mds": ["noisy.md"],
                "referenced_by_source_mds": ["site-control.md"],
                "canonical_source_md": "seed.md",
                "content_hash": "seed",
            },
            "noisy.md": {
                "linked_source_mds": ["n1.md", "n2.md", "n3.md"],
                "referenced_by_source_mds": [],
                "canonical_source_md": "noisy.md",
                "content_hash": "noisy",
            },
            "site-control.md": {
                "linked_source_mds": ["21615_2.md", "20264.md"],
                "referenced_by_source_mds": [],
                "canonical_source_md": "site-control.md",
                "content_hash": "site-control",
            },
            "21615.md": {
                "linked_source_mds": [],
                "referenced_by_source_mds": [],
                "canonical_source_md": "21615.md",
                "content_hash": "21615",
            },
            "21615_2.md": {
                "linked_source_mds": [],
                "referenced_by_source_mds": [],
                "canonical_source_md": "21615.md",
                "content_hash": "21615-variant",
            },
            "20264.md": {
                "linked_source_mds": [],
                "referenced_by_source_mds": [],
                "canonical_source_md": "20264.md",
                "content_hash": "20264",
            },
            **{
                f"n{i}.md": {
                    "linked_source_mds": [],
                    "referenced_by_source_mds": [],
                    "canonical_source_md": f"n{i}.md",
                    "content_hash": f"n{i}",
                }
                for i in range(1, 4)
            },
        }
        graph_path = self._make_graph_file(tmp_path, graph)
        store = self._make_vector_store({
            "21615.md": [
                Chunk(
                    id="site-match",
                    content="site match",
                    chunk_type=ChunkType.DOCUMENT,
                    source_md="21615.md",
                )
            ],
            "20264.md": [
                Chunk(
                    id="site-control-detail",
                    content="site control",
                    chunk_type=ChunkType.DOCUMENT,
                    source_md="20264.md",
                )
            ],
        })
        expander = DocumentGraphExpander(
            graph_path=graph_path,
            broad_max_hops=2,
            max_fanout=3,
            total_budget=6,
        )
        initial = [
            Chunk(id="seed", content="seed", chunk_type=ChunkType.PARAGRAPH, source_md="seed.md")
        ]

        result, _ = expander.expand(initial, store, is_broad_concept=True)

        result_ids = {chunk.id for chunk in result}
        assert "site-match" in result_ids
        assert "site-control-detail" in result_ids

    def test_seed_chunks_are_deduplicated_by_canonical_source(
        self, tmp_path: Path
    ) -> None:
        graph = {
            "base.md": {
                "linked_source_mds": [],
                "referenced_by_source_mds": [],
                "canonical_source_md": "base.md",
                "content_hash": "base",
            },
            "base_2.md": {
                "linked_source_mds": [],
                "referenced_by_source_mds": [],
                "canonical_source_md": "base.md",
                "content_hash": "variant",
            },
        }
        graph_path = self._make_graph_file(tmp_path, graph)
        expander = DocumentGraphExpander(graph_path=graph_path)
        initial = [
            Chunk(id="base", content="base", chunk_type=ChunkType.PARAGRAPH, source_md="base.md"),
            Chunk(
                id="variant",
                content="variant",
                chunk_type=ChunkType.PARAGRAPH,
                source_md="base_2.md",
            ),
        ]

        result, stats = expander.expand(initial, self._make_vector_store({}))

        assert [chunk.id for chunk in result] == ["base"]
        assert stats["deduplicated_count"] == 1

    def test_cycle_termination(self, tmp_path: Path) -> None:
        graph = {
            "a.md": {
                "linked_source_mds": ["b.md"],
                "referenced_by_source_mds": [],
                "canonical_source_md": "a.md",
                "content_hash": "h1",
            },
            "b.md": {
                "linked_source_mds": ["a.md"],
                "referenced_by_source_mds": [],
                "canonical_source_md": "b.md",
                "content_hash": "h2",
            },
        }
        graph_path = self._make_graph_file(tmp_path, graph)
        store = self._make_vector_store({
            "b.md": [Chunk(id="b1", content="b", chunk_type=ChunkType.PARAGRAPH, source_md="b.md")],
        })

        expander = DocumentGraphExpander(graph_path=graph_path, broad_max_hops=5)
        initial = [Chunk(id="a1", content="a", chunk_type=ChunkType.PARAGRAPH, source_md="a.md")]
        result, stats = expander.expand(initial, store, is_broad_concept=True)

        # Should not infinite loop
        assert stats["expanded_source_count"] == 1
        assert stats["expanded_chunk_count"] == 1

    def test_canonical_dedup(self, tmp_path: Path) -> None:
        graph = {
            "a.md": {
                "linked_source_mds": ["b.md", "c.md"],
                "referenced_by_source_mds": [],
                "canonical_source_md": "a.md",
                "content_hash": "h1",
            },
            "b.md": {
                "linked_source_mds": [],
                "referenced_by_source_mds": [],
                "canonical_source_md": "base.md",
                "content_hash": "h_same",
            },
            "c.md": {
                "linked_source_mds": [],
                "referenced_by_source_mds": [],
                "canonical_source_md": "base.md",
                "content_hash": "h_same",
            },
        }
        graph_path = self._make_graph_file(tmp_path, graph)
        store = self._make_vector_store({
            "b.md": [Chunk(id="b1", content="b", chunk_type=ChunkType.PARAGRAPH, source_md="b.md")],
            "c.md": [Chunk(id="c1", content="c", chunk_type=ChunkType.PARAGRAPH, source_md="c.md")],
        })

        expander = DocumentGraphExpander(graph_path=graph_path)
        initial = [Chunk(id="a1", content="a", chunk_type=ChunkType.PARAGRAPH, source_md="a.md")]
        result, stats = expander.expand(initial, store)

        # b.md and c.md share canonical, so only one should produce chunks
        assert stats["expanded_source_count"] == 2
        canonical_mds = {c.source_md for c in result if c.id in ("b1", "c1")}
        assert len(canonical_mds) == 1

    def test_content_hash_dedup(self, tmp_path: Path) -> None:
        graph = {
            "a.md": {
                "linked_source_mds": ["b.md", "c.md"],
                "referenced_by_source_mds": [],
                "canonical_source_md": "a.md",
                "content_hash": "h1",
            },
            "b.md": {
                "linked_source_mds": [],
                "referenced_by_source_mds": [],
                "canonical_source_md": "b.md",
                "content_hash": "h_same",
            },
            "c.md": {
                "linked_source_mds": [],
                "referenced_by_source_mds": [],
                "canonical_source_md": "c.md",
                "content_hash": "h_same",
            },
        }
        graph_path = self._make_graph_file(tmp_path, graph)
        store = self._make_vector_store({
            "b.md": [Chunk(id="b1", content="b", chunk_type=ChunkType.PARAGRAPH, source_md="b.md")],
            "c.md": [Chunk(id="c1", content="c", chunk_type=ChunkType.PARAGRAPH, source_md="c.md")],
        })

        expander = DocumentGraphExpander(graph_path=graph_path)
        initial = [Chunk(id="a1", content="a", chunk_type=ChunkType.PARAGRAPH, source_md="a.md")]
        result, stats = expander.expand(initial, store)

        # b.md and c.md share content_hash, so only one should produce chunks
        expanded_chunks = [c for c in result if c.id in ("b1", "c1")]
        assert len(expanded_chunks) == 1

    def test_stable_traversal_order(self, tmp_path: Path) -> None:
        graph = {
            "a.md": {
                "linked_source_mds": ["c.md", "b.md"],
                "referenced_by_source_mds": [],
                "canonical_source_md": "a.md",
                "content_hash": "h1",
            },
            "b.md": {
                "linked_source_mds": [],
                "referenced_by_source_mds": [],
                "canonical_source_md": "b.md",
                "content_hash": "h2",
            },
            "c.md": {
                "linked_source_mds": [],
                "referenced_by_source_mds": [],
                "canonical_source_md": "c.md",
                "content_hash": "h3",
            },
        }
        graph_path = self._make_graph_file(tmp_path, graph)
        store = self._make_vector_store({
            "b.md": [Chunk(id="b1", content="b", chunk_type=ChunkType.PARAGRAPH, source_md="b.md")],
            "c.md": [Chunk(id="c1", content="c", chunk_type=ChunkType.PARAGRAPH, source_md="c.md")],
        })

        expander = DocumentGraphExpander(graph_path=graph_path)
        initial = [Chunk(id="a1", content="a", chunk_type=ChunkType.PARAGRAPH, source_md="a.md")]

        result1, _ = expander.expand(initial, store)
        result2, _ = expander.expand(initial, store)

        order1 = [c.id for c in result1 if c.id in ("b1", "c1")]
        order2 = [c.id for c in result2 if c.id in ("b1", "c1")]
        assert order1 == order2

    def test_document_chunk_priority(self, tmp_path: Path) -> None:
        graph = {
            "a.md": {
                "linked_source_mds": ["b.md"],
                "referenced_by_source_mds": [],
                "canonical_source_md": "a.md",
                "content_hash": "h1",
            },
            "b.md": {
                "linked_source_mds": [],
                "referenced_by_source_mds": [],
                "canonical_source_md": "b.md",
                "content_hash": "h2",
            },
        }
        graph_path = self._make_graph_file(tmp_path, graph)
        store = self._make_vector_store({
            "b.md": [
                Chunk(id="b_doc", content="doc", chunk_type=ChunkType.DOCUMENT, source_md="b.md"),
                Chunk(id="b_sec", content="section", chunk_type=ChunkType.SECTION, source_md="b.md"),
                Chunk(id="b_par", content="paragraph", chunk_type=ChunkType.PARAGRAPH, source_md="b.md"),
            ],
        })

        expander = DocumentGraphExpander(graph_path=graph_path, max_chunks_per_doc=2)
        initial = [Chunk(id="a1", content="a", chunk_type=ChunkType.PARAGRAPH, source_md="a.md")]
        result, _ = expander.expand(initial, store)

        expanded = [c for c in result if c.source_md == "b.md"]
        assert len(expanded) == 2
        assert expanded[0].chunk_type == ChunkType.DOCUMENT
        assert expanded[1].chunk_type == ChunkType.SECTION

    def test_graph_reload_on_file_change(self, tmp_path: Path) -> None:
        graph = {
            "a.md": {
                "linked_source_mds": ["b.md"],
                "referenced_by_source_mds": [],
                "canonical_source_md": "a.md",
                "content_hash": "h1",
            },
            "b.md": {
                "linked_source_mds": [],
                "referenced_by_source_mds": [],
                "canonical_source_md": "b.md",
                "content_hash": "h2",
            },
        }
        graph_path = self._make_graph_file(tmp_path, graph)
        store = self._make_vector_store({
            "b.md": [Chunk(id="b1", content="b", chunk_type=ChunkType.PARAGRAPH, source_md="b.md")],
        })

        expander = DocumentGraphExpander(graph_path=graph_path)
        initial = [Chunk(id="a1", content="a", chunk_type=ChunkType.PARAGRAPH, source_md="a.md")]
        result1, _ = expander.expand(initial, store)
        assert any(c.id == "b1" for c in result1)

        # Update graph file on disk
        updated_graph = {
            "a.md": {
                "linked_source_mds": ["c.md"],
                "referenced_by_source_mds": [],
                "canonical_source_md": "a.md",
                "content_hash": "h1",
            },
            "c.md": {
                "linked_source_mds": [],
                "referenced_by_source_mds": [],
                "canonical_source_md": "c.md",
                "content_hash": "h3",
            },
        }
        graph_path.write_text(json.dumps(updated_graph), encoding="utf-8")
        # Update mtime by touching the file
        import time
        time.sleep(0.01)
        graph_path.write_text(json.dumps(updated_graph), encoding="utf-8")

        store2 = self._make_vector_store({
            "c.md": [Chunk(id="c1", content="c", chunk_type=ChunkType.PARAGRAPH, source_md="c.md")],
        })
        result2, _ = expander.expand(initial, store2)
        assert any(c.id == "c1" for c in result2)
        assert not any(c.id == "b1" for c in result2)

    def test_no_graph_returns_unchanged(self, tmp_path: Path) -> None:
        store = MagicMock()
        expander = DocumentGraphExpander(graph_path=tmp_path / "nonexistent.json")
        initial = [Chunk(id="a1", content="a", chunk_type=ChunkType.PARAGRAPH)]
        result, stats = expander.expand(initial, store)

        assert result == initial
        assert stats["expanded_source_count"] == 0

    def test_broad_fetch_section_first(self, tmp_path: Path) -> None:
        """Broad concept query should prefer SECTION chunks over DOCUMENT chunks."""
        graph = {
            "a.md": {
                "linked_source_mds": ["b.md"],
                "referenced_by_source_mds": [],
                "canonical_source_md": "a.md",
                "content_hash": "h1",
            },
            "b.md": {
                "linked_source_mds": [],
                "referenced_by_source_mds": [],
                "canonical_source_md": "b.md",
                "content_hash": "h2",
            },
        }
        graph_path = self._make_graph_file(tmp_path, graph)
        store = self._make_vector_store({
            "b.md": [
                Chunk(id="b_doc", content="doc", chunk_type=ChunkType.DOCUMENT, source_md="b.md"),
                Chunk(id="b_sec", content="section", chunk_type=ChunkType.SECTION, source_md="b.md"),
                Chunk(id="b_par", content="paragraph", chunk_type=ChunkType.PARAGRAPH, source_md="b.md"),
            ],
        })

        expander = DocumentGraphExpander(graph_path=graph_path, max_chunks_per_doc=2)
        initial = [Chunk(id="a1", content="a", chunk_type=ChunkType.PARAGRAPH, source_md="a.md")]

        # Narrow query: DOCUMENT first
        result_narrow, _ = expander.expand(initial, store, is_broad_concept=False)
        expanded_narrow = [c for c in result_narrow if c.source_md == "b.md"]
        assert expanded_narrow[0].chunk_type == ChunkType.DOCUMENT

        # Broad query: SECTION first
        result_broad, _ = expander.expand(initial, store, is_broad_concept=True)
        expanded_broad = [c for c in result_broad if c.source_md == "b.md"]
        assert expanded_broad[0].chunk_type == ChunkType.SECTION

    def test_broad_fetch_falls_back_to_document_when_no_section(self, tmp_path: Path) -> None:
        """Broad concept query should fall back to DOCUMENT when SECTION is absent."""
        graph = {
            "a.md": {
                "linked_source_mds": ["b.md"],
                "referenced_by_source_mds": [],
                "canonical_source_md": "a.md",
                "content_hash": "h1",
            },
            "b.md": {
                "linked_source_mds": [],
                "referenced_by_source_mds": [],
                "canonical_source_md": "b.md",
                "content_hash": "h2",
            },
        }
        graph_path = self._make_graph_file(tmp_path, graph)
        store = self._make_vector_store({
            "b.md": [
                Chunk(id="b_doc", content="doc", chunk_type=ChunkType.DOCUMENT, source_md="b.md"),
                Chunk(id="b_par", content="paragraph", chunk_type=ChunkType.PARAGRAPH, source_md="b.md"),
            ],
        })

        expander = DocumentGraphExpander(graph_path=graph_path, max_chunks_per_doc=2)
        initial = [Chunk(id="a1", content="a", chunk_type=ChunkType.PARAGRAPH, source_md="a.md")]

        result_broad, _ = expander.expand(initial, store, is_broad_concept=True)
        expanded_broad = [c for c in result_broad if c.source_md == "b.md"]
        assert expanded_broad[0].chunk_type == ChunkType.DOCUMENT

    def test_chunk_id_dedup(self, tmp_path: Path) -> None:
        """Seed chunk IDs should not be duplicated by expanded chunks."""
        graph = {
            "a.md": {
                "linked_source_mds": ["b.md"],
                "referenced_by_source_mds": [],
                "canonical_source_md": "a.md",
                "content_hash": "h1",
            },
            "b.md": {
                "linked_source_mds": [],
                "referenced_by_source_mds": [],
                "canonical_source_md": "b.md",
                "content_hash": "h2",
            },
        }
        graph_path = self._make_graph_file(tmp_path, graph)
        store = self._make_vector_store({
            "b.md": [Chunk(id="a1", content="dup", chunk_type=ChunkType.PARAGRAPH, source_md="b.md")],
        })

        expander = DocumentGraphExpander(graph_path=graph_path)
        initial = [Chunk(id="a1", content="a", chunk_type=ChunkType.PARAGRAPH, source_md="a.md")]
        result, stats = expander.expand(initial, store)

        ids = [c.id for c in result]
        assert ids.count("a1") == 1
        assert stats["expanded_chunk_count"] == 0
