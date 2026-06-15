"""Unit tests for provider-based cross-encoder reranker."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ate_rag_kb.chunking.models import Chunk, ChunkType
from ate_rag_kb.retrieval.rerank_input import (
    InputConfig,
    content_digest,
    shape_rerank_input,
)
from ate_rag_kb.retrieval.reranker import Reranker
from ate_rag_kb.retrieval.reranker_providers import _build_cache_key, _RerankCache
from ate_rag_kb.utils.config import Config


def _make_chunk(
    idx: int,
    content: str = "",
    source_md: str = "",
    chunk_type: ChunkType = ChunkType.PARAGRAPH,
    section_title: str = "",
    doc_title: str = "",
) -> Chunk:
    return Chunk(
        id=f"c{idx}",
        content=content or f"content-{idx}",
        chunk_type=chunk_type,
        source_md=source_md,
        section_title=section_title,
        doc_title=doc_title,
    )


class TestRerankInputShaping:
    """Tests for shape_rerank_input() in rerank_input.py."""

    def test_empty_chunks_returns_empty(self) -> None:
        config = InputConfig(max_candidates=32)
        result = shape_rerank_input([], config)
        assert result.selected_chunks == []
        assert result.truncated_texts == []
        assert result.pre_candidate_count == 0

    def test_limits_candidates_to_max_candidates(self) -> None:
        config = InputConfig(max_candidates=5, max_chunks_per_source=10)
        chunks = [_make_chunk(i, source_md=f"s{i % 3}.md") for i in range(20)]
        result = shape_rerank_input(chunks, config)
        assert result.post_candidate_count <= 5
        assert len(result.selected_chunks) <= 5

    def test_truncates_long_documents(self) -> None:
        config = InputConfig(
            max_candidates=5,
            max_chars_per_document=100,
            max_chunks_per_source=10,
        )
        chunks = [_make_chunk(0, content="x" * 500, source_md="a.md")]
        result = shape_rerank_input(chunks, config)
        assert result.truncated_texts[0] == "x" * 100
        assert result.truncated_document_count == 1

    def test_preserves_full_original_chunks(self) -> None:
        long_content = "x" * 500
        config = InputConfig(
            max_candidates=5,
            max_chars_per_document=100,
            max_chunks_per_source=10,
        )
        chunks = [_make_chunk(0, content=long_content, source_md="a.md")]
        result = shape_rerank_input(chunks, config)
        # Original chunk content must NOT be truncated
        assert result.selected_chunks[0].content == long_content

    def test_source_diversity_respects_max_chunks_per_source(self) -> None:
        config = InputConfig(
            max_candidates=10,
            max_chunks_per_source=2,
            min_sources=6,
        )
        chunks = [
            _make_chunk(0, source_md="a.md"),
            _make_chunk(1, source_md="a.md"),
            _make_chunk(2, source_md="a.md"),
            _make_chunk(3, source_md="a.md"),
            _make_chunk(4, source_md="b.md"),
        ]
        result = shape_rerank_input(chunks, config)
        a_count = sum(1 for c in result.selected_chunks if c.source_md == "a.md")
        assert a_count <= 2

    def test_prefers_section_over_document_type(self) -> None:
        config = InputConfig(max_candidates=2, max_chunks_per_source=10)
        doc_chunk = _make_chunk(0, source_md="a.md", chunk_type=ChunkType.DOCUMENT)
        section_chunk = _make_chunk(1, source_md="a.md", chunk_type=ChunkType.SECTION)
        # Document chunk is listed first, but SECTION should be preferred
        chunks = [doc_chunk, section_chunk]
        result = shape_rerank_input(chunks, config)
        ids = [c.id for c in result.selected_chunks]
        # Section chunk should come before document chunk
        assert ids.index("c1") < ids.index("c0")

    def test_seed_chunks_prioritized_over_graph_expanded(self) -> None:
        config = InputConfig(max_candidates=5, max_chunks_per_source=10)
        seed = _make_chunk(0, source_md="seed.md", content="seed content")
        expanded = [
            _make_chunk(i, source_md=f"exp{i}.md", content=f"expanded {i}")
            for i in range(1, 20)
        ]
        result = shape_rerank_input(chunks=[seed] + expanded, config=config, seed_count=1)
        assert "c0" in [c.id for c in result.selected_chunks]

    def test_preserves_title_match_chunks(self) -> None:
        config = InputConfig(
            max_candidates=5,
            max_chunks_per_source=10,
            preserve_title_matches=2,
        )
        chunks = [
            _make_chunk(0, source_md="a.md", doc_title="Site Control Window"),
            _make_chunk(1, source_md="b.md", doc_title="Other Topic"),
            _make_chunk(2, source_md="c.md", section_title="Site Control States"),
            _make_chunk(3, source_md="d.md", doc_title="Unrelated"),
            _make_chunk(4, source_md="e.md", doc_title="Another"),
        ]
        result = shape_rerank_input(
            chunks, config, title_match_terms=["site control"]
        )
        ids = [c.id for c in result.selected_chunks]
        assert "c0" in ids
        assert "c2" in ids

    def test_title_match_respects_max_candidates_cap(self) -> None:
        """Title-match chunks must not exceed max_candidates hard cap."""
        config = InputConfig(
            max_candidates=2,
            max_chunks_per_source=10,
            preserve_title_matches=5,  # More than max_candidates
        )
        chunks = [
            _make_chunk(0, source_md="a.md", doc_title="Site Control A"),
            _make_chunk(1, source_md="b.md", doc_title="Site Control B"),
            _make_chunk(2, source_md="c.md", doc_title="Site Control C"),
            _make_chunk(3, source_md="d.md", doc_title="Site Control D"),
        ]
        result = shape_rerank_input(
            chunks, config, title_match_terms=["site control"]
        )
        assert result.post_candidate_count <= 2

    def test_title_match_respects_per_source_cap(self) -> None:
        """Title-match chunks from the same source respect max_chunks_per_source."""
        config = InputConfig(
            max_candidates=10,
            max_chunks_per_source=2,
            preserve_title_matches=5,
        )
        chunks = [
            _make_chunk(0, source_md="a.md", doc_title="Site Control A"),
            _make_chunk(1, source_md="a.md", doc_title="Site Control B"),
            _make_chunk(2, source_md="a.md", doc_title="Site Control C"),
            _make_chunk(3, source_md="a.md", doc_title="Site Control D"),
        ]
        result = shape_rerank_input(
            chunks, config, title_match_terms=["site control"]
        )
        a_count = sum(1 for c in result.selected_chunks if c.source_md == "a.md")
        assert a_count <= 2

    def test_title_matches_do_not_monopolize_broad_input_slots(self) -> None:
        """Title priority should still leave room for distinct sources."""
        config = InputConfig(
            max_candidates=6,
            max_chunks_per_source=3,
            preserve_title_matches=3,
            min_sources=4,
        )
        chunks = [
            _make_chunk(0, source_md="a.md", doc_title="Site Control A"),
            _make_chunk(1, source_md="a.md", doc_title="Site Control B"),
            _make_chunk(2, source_md="a.md", doc_title="Site Control C"),
            _make_chunk(3, source_md="b.md", doc_title="Other"),
            _make_chunk(4, source_md="c.md", doc_title="Other"),
            _make_chunk(5, source_md="d.md", doc_title="Other"),
            _make_chunk(6, source_md="e.md", doc_title="Other"),
        ]

        result = shape_rerank_input(
            chunks,
            config,
            title_match_terms=["site control"],
            is_broad_concept=True,
        )

        assert len({chunk.source_md for chunk in result.selected_chunks}) >= 4
        assert result.post_candidate_count <= config.max_candidates

    def test_total_chars_stat(self) -> None:
        config = InputConfig(
            max_candidates=10,
            max_chars_per_document=50,
            max_chunks_per_source=10,
        )
        chunks = [
            _make_chunk(0, content="x" * 100, source_md="a.md"),
            _make_chunk(1, content="y" * 30, source_md="b.md"),
        ]
        result = shape_rerank_input(chunks, config)
        # First truncated to 50, second is 30
        assert result.total_chars == 50 + 30

    def test_broad_concept_respects_hard_cap(self) -> None:
        """max_candidates is always a hard cap — broad queries cannot exceed it."""
        config = InputConfig(
            max_candidates=8,
            max_chunks_per_source=2,
            min_sources=6,
        )
        chunks = [
            _make_chunk(i, source_md=f"s{i}.md")
            for i in range(20)
        ]
        result = shape_rerank_input(chunks, config, is_broad_concept=True)
        assert result.post_candidate_count <= 8

    def test_first_pass_picks_new_sources_before_duplicates(self) -> None:
        """First pass must pick one chunk per unseen source; second pass fills extras."""
        config = InputConfig(
            max_candidates=4,
            max_chunks_per_source=3,
        )
        chunks = [
            _make_chunk(0, source_md="a.md"),
            _make_chunk(1, source_md="a.md"),
            _make_chunk(2, source_md="a.md"),
            _make_chunk(3, source_md="b.md"),
            _make_chunk(4, source_md="c.md"),
        ]
        result = shape_rerank_input(chunks, config)
        selected_sources = [c.source_md for c in result.selected_chunks]
        # First 3 selected should all be distinct sources if possible
        # (a, b, c in some order) before any second-a appears
        first_three_sources = selected_sources[:3]
        assert len(set(first_three_sources)) == 3

    def test_rerank_text_includes_header_and_body(self) -> None:
        """Truncated text for the API must include doc_title/section_title/toc_path."""
        from ate_rag_kb.retrieval.rerank_input import _build_rerank_text

        chunk = _make_chunk(
            0,
            content="body text here",
            source_md="a.md",
            doc_title="Site Control",
            section_title="States",
        )
        text = _build_rerank_text(chunk, max_chars=200)
        assert "Site Control" in text
        assert "States" in text
        assert "body text here" in text

    def test_rerank_text_respects_char_cap(self) -> None:
        """Header + body must not exceed max_chars."""
        from ate_rag_kb.retrieval.rerank_input import _build_rerank_text

        chunk = _make_chunk(
            0,
            content="x" * 5000,
            source_md="a.md",
            doc_title="Title",
            section_title="Section",
        )
        text = _build_rerank_text(chunk, max_chars=100)
        assert len(text) <= 100
        # Title/Section header should still be present
        assert "Title" in text

    def test_prefer_section_chunks_false_disables_type_sort(self) -> None:
        """When prefer_section_chunks=False, DOCUMENT chunks are not deprioritized."""
        config = InputConfig(
            max_candidates=2,
            max_chunks_per_source=10,
            prefer_section_chunks=False,
        )
        doc_chunk = _make_chunk(0, source_md="a.md", chunk_type=ChunkType.DOCUMENT)
        section_chunk = _make_chunk(1, source_md="a.md", chunk_type=ChunkType.SECTION)
        # DOCUMENT is listed first; with prefer_section_chunks=False,
        # both share type priority 0 so DOCUMENT should come first
        chunks = [doc_chunk, section_chunk]
        result = shape_rerank_input(chunks, config)
        ids = [c.id for c in result.selected_chunks]
        assert ids.index("c0") < ids.index("c1")

    def test_source_count_stat(self) -> None:
        config = InputConfig(
            max_candidates=10,
            max_chunks_per_source=2,
        )
        chunks = [
            _make_chunk(0, source_md="a.md"),
            _make_chunk(1, source_md="b.md"),
            _make_chunk(2, source_md="a.md"),
        ]
        result = shape_rerank_input(chunks, config)
        assert result.source_count == 2


class TestContentDigest:
    def test_stable_digest(self) -> None:
        d1 = content_digest("hello")
        d2 = content_digest("hello")
        assert d1 == d2
        assert len(d1) == 16

    def test_different_content_different_digest(self) -> None:
        d1 = content_digest("hello")
        d2 = content_digest("world")
        assert d1 != d2


class TestRerankCache:
    def test_cache_miss_returns_none(self) -> None:
        cache = _RerankCache(max_size=4)
        assert cache.get("nonexistent") is None

    def test_cache_put_and_get(self) -> None:
        import numpy as np

        cache = _RerankCache(max_size=4)
        scores = np.array([0.5, 0.9])
        cache.put("key1", scores)
        result = cache.get("key1")
        assert result is not None
        assert list(result) == [0.5, 0.9]

    def test_cache_lru_eviction(self) -> None:
        import numpy as np

        cache = _RerankCache(max_size=2)
        cache.put("a", np.array([1.0]))
        cache.put("b", np.array([2.0]))
        cache.put("c", np.array([3.0]))
        # "a" should be evicted
        assert cache.get("a") is None
        assert cache.get("b") is not None
        assert cache.get("c") is not None

    def test_cache_clear(self) -> None:
        import numpy as np

        cache = _RerankCache(max_size=4)
        cache.put("a", np.array([1.0]))
        cache.clear()
        assert cache.size == 0
        assert cache.get("a") is None

    def test_cache_key_stability(self) -> None:
        key1 = _build_cache_key("query", "model", ["doc1", "doc2"])
        key2 = _build_cache_key("query", "model", ["doc1", "doc2"])
        assert key1 == key2

    def test_cache_key_differs_for_different_docs(self) -> None:
        key1 = _build_cache_key("query", "model", ["doc1"])
        key2 = _build_cache_key("query", "model", ["doc2"])
        assert key1 != key2


class TestReranker:
    def test_rerank_returns_top_k(self) -> None:
        with patch("sentence_transformers.CrossEncoder") as mock_cls:
            model = MagicMock()
            model.predict.return_value = [0.5, 0.9, 0.1]
            mock_cls.return_value = model

            reranker = Reranker()
            chunks = [
                Chunk(id="c1", content="low", chunk_type=ChunkType.PARAGRAPH),
                Chunk(id="c2", content="high", chunk_type=ChunkType.PARAGRAPH),
                Chunk(id="c3", content="lower", chunk_type=ChunkType.PARAGRAPH),
            ]

            result = reranker.rerank("query", chunks, top_k=2)

            assert len(result) == 2
            assert result[0].id == "c2"

    def test_rerank_empty_list(self) -> None:
        with patch("sentence_transformers.CrossEncoder"):
            reranker = Reranker()

            result = reranker.rerank("query", [])

            assert result == []

    def test_rerank_uses_default_top_k(self) -> None:
        with patch("sentence_transformers.CrossEncoder") as mock_cls:
            model = MagicMock()
            model.predict.return_value = [0.1] * 10
            mock_cls.return_value = model

            reranker = Reranker()
            reranker.top_k = 3
            chunks = [
                Chunk(id=f"c{i}", content=f"text{i}", chunk_type=ChunkType.PARAGRAPH)
                for i in range(10)
            ]

            result = reranker.rerank("query", chunks)

            assert len(result) == 3

    def test_rerank_stats_include_input_shaping(self) -> None:
        with patch("sentence_transformers.CrossEncoder") as mock_cls:
            model = MagicMock()
            model.predict.return_value = [0.5, 0.9, 0.1]
            mock_cls.return_value = model

            reranker = Reranker(Config({"retrieval": {"reranker": {"input": {"max_candidates": 32}}}}))
            chunks = [
                Chunk(id="c1", content="low", chunk_type=ChunkType.PARAGRAPH),
                Chunk(id="c2", content="high", chunk_type=ChunkType.PARAGRAPH),
                Chunk(id="c3", content="lower", chunk_type=ChunkType.PARAGRAPH),
            ]
            reranker.rerank("query", chunks)

            stats = reranker._last_rerank_stats
            assert "pre_rerank_candidate_count" in stats
            assert "rerank_input_candidate_count" in stats
            assert "rerank_input_total_chars" in stats
            assert "rerank_input_truncated_document_count" in stats

    def test_offline_mode_raises_clear_error_when_reranker_cache_missing(self, tmp_path) -> None:
        cfg = Config(
            {
                "embedding": {
                    "cache_dir": str(tmp_path),
                    "local_files_only": True,
                },
                "retrieval": {
                    "reranker": {
                        "model_name": "BAAI/bge-reranker-v2-m3",
                    }
                },
            }
        )
        reranker = Reranker(cfg)

        with pytest.raises(FileNotFoundError, match="Local model cache not found"):
            _ = reranker.model

    def test_reranker_cpu_device_passed_to_cross_encoder(self, tmp_path) -> None:
        with patch("sentence_transformers.CrossEncoder") as mock_cls:
            cfg = Config(
                {
                    "embedding": {"cache_dir": str(tmp_path), "local_files_only": False},
                    "retrieval": {"reranker": {"device": "cpu"}},
                }
            )
            reranker = Reranker(cfg)
            _ = reranker.model

            mock_cls.assert_called_once()
            assert mock_cls.call_args.kwargs.get("device") == "cpu"

    def test_reranker_auto_device_resolves_correctly(self) -> None:
        with (
            patch("torch.cuda.is_available", return_value=False),
            patch("torch.backends.mps.is_available", return_value=False),
        ):
            from ate_rag_kb.retrieval.reranker_providers import LocalRerankerProvider
            assert LocalRerankerProvider._resolve_device("auto") == "cpu"

        with (
            patch("torch.cuda.is_available", return_value=False),
            patch("torch.backends.mps.is_available", return_value=True),
        ):
            from ate_rag_kb.retrieval.reranker_providers import LocalRerankerProvider
            assert LocalRerankerProvider._resolve_device("auto") == "mps"

        with (
            patch("torch.cuda.is_available", return_value=True),
            patch("torch.backends.mps.is_available", return_value=False),
        ):
            from ate_rag_kb.retrieval.reranker_providers import LocalRerankerProvider
            assert LocalRerankerProvider._resolve_device("auto") == "cuda"

    def test_env_var_ate_kb_reranker_device_overrides_default(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        monkeypatch.setenv("ATE_KB_RERANKER_DEVICE", "cuda")
        with patch("sentence_transformers.CrossEncoder") as mock_cls:
            cfg = Config(
                {
                    "embedding": {"cache_dir": str(tmp_path), "local_files_only": False},
                    "retrieval": {"reranker": {"device": "${ATE_KB_RERANKER_DEVICE:-cpu}"}},
                }
            )
            reranker = Reranker(cfg)
            _ = reranker.model

            assert reranker.device == "cuda"
            assert mock_cls.call_args.kwargs.get("device") == "cuda"

    def test_model_name_env_override(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        """Reranker provider model_name must reflect the env-var-expanded model name."""
        monkeypatch.setenv("ATE_KB_RERANKER_MODEL", "vendor/custom-reranker")
        with patch("sentence_transformers.CrossEncoder"):
            cfg = Config(
                {
                    "embedding": {"cache_dir": str(tmp_path), "local_files_only": False},
                    "retrieval": {
                        "reranker": {
                            "model_name": "${ATE_KB_RERANKER_MODEL:-BAAI/bge-reranker-v2-m3}",
                            "device": "cpu",
                        }
                    },
                }
            )
            reranker = Reranker(cfg)
            assert reranker._provider.model_name == "vendor/custom-reranker"

    def test_rerank_broad_concept_uses_source_diverse_selection(self) -> None:
        with patch("sentence_transformers.CrossEncoder") as mock_cls:
            model = MagicMock()
            # Scores: a1=0.99, a2=0.98, a3=0.97, b1=0.80, c1=0.70, d1=0.60
            model.predict.return_value = [0.99, 0.98, 0.97, 0.80, 0.70, 0.60]
            mock_cls.return_value = model

            cfg = Config(
                {
                    "retrieval": {
                        "reranker": {
                            "top_k": 5,
                            "broad_candidate_top_k": 16,
                            "broad_final_top_k": 4,
                            "broad_max_sources": 3,
                            "input": {"max_candidates": 32, "max_chunks_per_source": 10},
                        }
                    }
                }
            )
            reranker = Reranker(cfg)
            chunks = [
                Chunk(id="a1", content="a1", chunk_type=ChunkType.PARAGRAPH, source_md="a.md"),
                Chunk(id="a2", content="a2", chunk_type=ChunkType.PARAGRAPH, source_md="a.md"),
                Chunk(id="a3", content="a3", chunk_type=ChunkType.PARAGRAPH, source_md="a.md"),
                Chunk(id="b1", content="b1", chunk_type=ChunkType.PARAGRAPH, source_md="b.md"),
                Chunk(id="c1", content="c1", chunk_type=ChunkType.PARAGRAPH, source_md="c.md"),
                Chunk(id="d1", content="d1", chunk_type=ChunkType.PARAGRAPH, source_md="d.md"),
            ]

            result = reranker.rerank("query", chunks, is_broad_concept=True)

            assert len(result) == 4
            ids = [c.id for c in result]
            assert "a1" in ids
            assert "b1" in ids
            assert "c1" in ids
            assert "a2" in ids
            assert "d1" not in ids

    def test_rerank_narrow_query_ignores_broad_settings(self) -> None:
        with patch("sentence_transformers.CrossEncoder") as mock_cls:
            model = MagicMock()
            model.predict.return_value = [0.99, 0.98, 0.97, 0.80, 0.70, 0.60]
            mock_cls.return_value = model

            cfg = Config(
                {
                    "retrieval": {
                        "reranker": {
                            "top_k": 5,
                            "broad_candidate_top_k": 16,
                            "broad_final_top_k": 4,
                            "broad_max_sources": 3,
                            "input": {"max_candidates": 32, "max_chunks_per_source": 10},
                        }
                    }
                }
            )
            reranker = Reranker(cfg)
            chunks = [
                Chunk(id="a1", content="a1", chunk_type=ChunkType.PARAGRAPH, source_md="a.md"),
                Chunk(id="a2", content="a2", chunk_type=ChunkType.PARAGRAPH, source_md="a.md"),
                Chunk(id="a3", content="a3", chunk_type=ChunkType.PARAGRAPH, source_md="a.md"),
                Chunk(id="b1", content="b1", chunk_type=ChunkType.PARAGRAPH, source_md="b.md"),
                Chunk(id="c1", content="c1", chunk_type=ChunkType.PARAGRAPH, source_md="c.md"),
                Chunk(id="d1", content="d1", chunk_type=ChunkType.PARAGRAPH, source_md="d.md"),
            ]

            result = reranker.rerank("query", chunks, is_broad_concept=False)

            assert len(result) == 5
            ids = [c.id for c in result]
            # Source-diverse first pass orders: a1, b1, c1, d1; second pass: a2
            # Positional scores [0.99,0.98,0.97,0.80,0.70,0.60] map to that order,
            # so top-5 by score: a1(0.99), b1(0.98), c1(0.97), d1(0.80), a2(0.70)
            assert ids == ["a1", "b1", "c1", "d1", "a2"]

    def test_rerank_broad_concept_preserves_order_within_source(self) -> None:
        with patch("sentence_transformers.CrossEncoder") as mock_cls:
            model = MagicMock()
            model.predict.return_value = [0.90, 0.85, 0.80, 0.75]
            mock_cls.return_value = model

            cfg = Config(
                {
                    "retrieval": {
                        "reranker": {
                            "top_k": 5,
                            "broad_candidate_top_k": 16,
                            "broad_final_top_k": 4,
                            "broad_max_sources": 2,
                            "input": {"max_candidates": 32, "max_chunks_per_source": 10},
                        }
                    }
                }
            )
            reranker = Reranker(cfg)
            chunks = [
                Chunk(id="a1", content="a1", chunk_type=ChunkType.PARAGRAPH, source_md="a.md"),
                Chunk(id="b1", content="b1", chunk_type=ChunkType.PARAGRAPH, source_md="b.md"),
                Chunk(id="a2", content="a2", chunk_type=ChunkType.PARAGRAPH, source_md="a.md"),
                Chunk(id="b2", content="b2", chunk_type=ChunkType.PARAGRAPH, source_md="b.md"),
            ]

            result = reranker.rerank("query", chunks, is_broad_concept=True)

            assert len(result) == 4
            ids = [c.id for c in result]
            assert ids == ["a1", "b1", "a2", "b2"]

    def test_rerank_broad_concept_with_empty_source_md(self) -> None:
        with patch("sentence_transformers.CrossEncoder") as mock_cls:
            model = MagicMock()
            model.predict.return_value = [0.99, 0.98, 0.80]
            mock_cls.return_value = model

            cfg = Config(
                {
                    "retrieval": {
                        "reranker": {
                            "top_k": 5,
                            "broad_candidate_top_k": 16,
                            "broad_final_top_k": 4,
                            "broad_max_sources": 3,
                            "input": {"max_candidates": 32, "max_chunks_per_source": 10},
                        }
                    }
                }
            )
            reranker = Reranker(cfg)
            chunks = [
                Chunk(id="a1", content="a1", chunk_type=ChunkType.PARAGRAPH, source_md="a.md"),
                Chunk(id="no_src", content="no_src", chunk_type=ChunkType.PARAGRAPH, source_md=""),
                Chunk(id="b1", content="b1", chunk_type=ChunkType.PARAGRAPH, source_md="b.md"),
            ]

            result = reranker.rerank("query", chunks, is_broad_concept=True)

            ids = [c.id for c in result]
            assert "a1" in ids
            assert "no_src" in ids
            assert "b1" in ids

    def test_rerank_broad_concept_demotes_low_utility_chunks(self) -> None:
        with patch("sentence_transformers.CrossEncoder") as mock_cls:
            model = MagicMock()
            model.predict.return_value = [0.99, 0.98, 0.80, 0.70]
            mock_cls.return_value = model

            reranker = Reranker(
                Config(
                    {
                        "retrieval": {
                            "reranker": {
                                "broad_candidate_top_k": 4,
                                "broad_final_top_k": 2,
                                "broad_max_sources": 2,
                                "input": {"max_candidates": 32, "max_chunks_per_source": 10},
                            }
                        }
                    }
                )
            )
            chunks = [
                Chunk(
                    id="image",
                    content="Image: Site Control window (site-control.png)",
                    chunk_type=ChunkType.IMAGE,
                    source_md="image.md",
                ),
                Chunk(
                    id="title",
                    content="Site Control Window",
                    chunk_type=ChunkType.SECTION,
                    source_md="title.md",
                    section_title="Site Control Window",
                ),
                Chunk(
                    id="states",
                    content="Enable connects a site. Active executes the flow. Focus selects results.",
                    chunk_type=ChunkType.SECTION,
                    source_md="states.md",
                    section_title="The states of the sites",
                ),
                Chunk(
                    id="expanded",
                    content="Parallel, Serial and Semi-Parallel modes use Size and Cycle.",
                    chunk_type=ChunkType.SECTION,
                    source_md="expanded.md",
                    section_title="Expanded Site Control window",
                ),
            ]

            result = reranker.rerank("site control作用", chunks, is_broad_concept=True)

            assert [chunk.id for chunk in result] == ["states", "expanded"]
            assert reranker._last_rerank_stats["low_utility_rerank_candidate_count"] == 2


class TestHttpRerankerProvider:
    """Tests for the HTTP reranker provider."""

    def test_http_rerank_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_RERANK_KEY", "test-key-123")
        cfg = Config(
            {
                "retrieval": {
                    "reranker": {
                        "provider": "http",
                        "model_name": "BAAI/bge-reranker-v2-m3",
                        "api": {
                            "base_url": "https://api.example.com/v1",
                            "api_key_env": "TEST_RERANK_KEY",
                            "timeout_seconds": 30,
                            "top_n": 10,
                        },
                    }
                }
            }
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {"index": 1, "relevance_score": 0.95},
                {"index": 0, "relevance_score": 0.80},
            ]
        }

        with patch("ate_rag_kb.retrieval.reranker_providers.httpx.post", return_value=mock_response):
            reranker = Reranker(cfg)
            chunks = [
                Chunk(id="c1", content="low", chunk_type=ChunkType.PARAGRAPH),
                Chunk(id="c2", content="high", chunk_type=ChunkType.PARAGRAPH),
            ]
            result = reranker.rerank("query", chunks)

        assert len(result) == 2
        assert result[0].id == "c2"

    def test_http_rerank_includes_max_chunks_per_doc(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_RERANK_KEY", "test-key")
        cfg = Config(
            {
                "retrieval": {
                    "reranker": {
                        "provider": "http",
                        "model_name": "BAAI/bge-reranker-v2-m3",
                        "api": {
                            "base_url": "https://api.example.com/v1",
                            "api_key_env": "TEST_RERANK_KEY",
                            "timeout_seconds": 30,
                            "top_n": 10,
                            "max_chunks_per_doc": 8,
                            "overlap_tokens": 40,
                        },
                    }
                }
            }
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [{"index": 0, "relevance_score": 0.9}]
        }

        with patch("ate_rag_kb.retrieval.reranker_providers.httpx.post", return_value=mock_response) as mock_post:
            reranker = Reranker(cfg)
            chunks = [Chunk(id="c1", content="text", chunk_type=ChunkType.PARAGRAPH)]
            reranker.rerank("query", chunks)

            call_args = mock_post.call_args
            payload = call_args.kwargs.get("json", call_args[1].get("json", {}))
            assert payload.get("max_chunks_per_doc") == 8
            assert payload.get("overlap_tokens") == 40

    def test_http_rerank_top_n_capped_by_document_count(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_RERANK_KEY", "test-key")
        cfg = Config(
            {
                "retrieval": {
                    "reranker": {
                        "provider": "http",
                        "model_name": "BAAI/bge-reranker-v2-m3",
                        "api": {
                            "base_url": "https://api.example.com/v1",
                            "api_key_env": "TEST_RERANK_KEY",
                            "timeout_seconds": 30,
                            "top_n": 100,  # Much larger than document count
                        },
                    }
                }
            }
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [{"index": 0, "relevance_score": 0.9}]
        }

        with patch("ate_rag_kb.retrieval.reranker_providers.httpx.post", return_value=mock_response) as mock_post:
            reranker = Reranker(cfg)
            chunks = [Chunk(id="c1", content="text", chunk_type=ChunkType.PARAGRAPH)]
            reranker.rerank("query", chunks)

            call_args = mock_post.call_args
            payload = call_args.kwargs.get("json", call_args[1].get("json", {}))
            assert payload["top_n"] == 1  # Capped to len(documents)

    def test_http_rerank_429_error_message(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_RERANK_KEY", "test-key")
        cfg = Config(
            {
                "retrieval": {
                    "reranker": {
                        "provider": "http",
                        "model_name": "BAAI/bge-reranker-v2-m3",
                        "api": {
                            "base_url": "https://api.example.com/v1",
                            "api_key_env": "TEST_RERANK_KEY",
                            "timeout_seconds": 30,
                        },
                    }
                }
            }
        )

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.text = "Too Many Requests"

        with patch("ate_rag_kb.retrieval.reranker_providers.httpx.post", return_value=mock_response):
            reranker = Reranker(cfg)
            chunks = [Chunk(id="c1", content="text", chunk_type=ChunkType.PARAGRAPH)]
            with pytest.raises(RuntimeError, match="Rate limited"):
                reranker.rerank("query", chunks)

    def test_http_rerank_503_error_message(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_RERANK_KEY", "test-key")
        cfg = Config(
            {
                "retrieval": {
                    "reranker": {
                        "provider": "http",
                        "model_name": "BAAI/bge-reranker-v2-m3",
                        "api": {
                            "base_url": "https://api.example.com/v1",
                            "api_key_env": "TEST_RERANK_KEY",
                            "timeout_seconds": 30,
                        },
                    }
                }
            }
        )

        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_response.text = "Service Unavailable"

        with patch("ate_rag_kb.retrieval.reranker_providers.httpx.post", return_value=mock_response):
            reranker = Reranker(cfg)
            chunks = [Chunk(id="c1", content="text", chunk_type=ChunkType.PARAGRAPH)]
            with pytest.raises(RuntimeError, match="Service unavailable"):
                reranker.rerank("query", chunks)

    def test_http_rerank_504_error_message(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_RERANK_KEY", "test-key")
        cfg = Config(
            {
                "retrieval": {
                    "reranker": {
                        "provider": "http",
                        "model_name": "BAAI/bge-reranker-v2-m3",
                        "api": {
                            "base_url": "https://api.example.com/v1",
                            "api_key_env": "TEST_RERANK_KEY",
                            "timeout_seconds": 30,
                        },
                    }
                }
            }
        )

        mock_response = MagicMock()
        mock_response.status_code = 504
        mock_response.text = "Gateway Timeout"

        with patch("ate_rag_kb.retrieval.reranker_providers.httpx.post", return_value=mock_response):
            reranker = Reranker(cfg)
            chunks = [Chunk(id="c1", content="text", chunk_type=ChunkType.PARAGRAPH)]
            with pytest.raises(RuntimeError, match="Gateway timeout"):
                reranker.rerank("query", chunks)

    def test_http_rerank_missing_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MISSING_RERANK_KEY", raising=False)
        cfg = Config(
            {
                "retrieval": {
                    "reranker": {
                        "provider": "http",
                        "model_name": "BAAI/bge-reranker-v2-m3",
                        "api": {
                            "base_url": "https://api.example.com/v1",
                            "api_key_env": "MISSING_RERANK_KEY",
                            "timeout_seconds": 30,
                        },
                    }
                }
            }
        )

        reranker = Reranker(cfg)
        chunks = [Chunk(id="c1", content="text", chunk_type=ChunkType.PARAGRAPH)]
        with pytest.raises(ValueError, match="API key not found"):
            reranker.rerank("query", chunks)

    def test_http_rerank_http_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_RERANK_KEY", "test-key")
        cfg = Config(
            {
                "retrieval": {
                    "reranker": {
                        "provider": "http",
                        "model_name": "BAAI/bge-reranker-v2-m3",
                        "api": {
                            "base_url": "https://api.example.com/v1",
                            "api_key_env": "TEST_RERANK_KEY",
                            "timeout_seconds": 30,
                        },
                    }
                }
            }
        )

        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_response.text = "Service Unavailable"

        with patch("ate_rag_kb.retrieval.reranker_providers.httpx.post", return_value=mock_response):
            reranker = Reranker(cfg)
            chunks = [Chunk(id="c1", content="text", chunk_type=ChunkType.PARAGRAPH)]
            with pytest.raises(RuntimeError, match="HTTP 503"):
                reranker.rerank("query", chunks)

    def test_http_rerank_partial_results(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_RERANK_KEY", "test-key")
        cfg = Config(
            {
                "retrieval": {
                    "reranker": {
                        "provider": "http",
                        "model_name": "BAAI/bge-reranker-v2-m3",
                        "top_k": 3,
                        "api": {
                            "base_url": "https://api.example.com/v1",
                            "api_key_env": "TEST_RERANK_KEY",
                            "timeout_seconds": 30,
                            "top_n": 2,
                        },
                    }
                }
            }
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {"index": 2, "relevance_score": 0.95},
            ]
        }

        with patch("ate_rag_kb.retrieval.reranker_providers.httpx.post", return_value=mock_response):
            reranker = Reranker(cfg)
            chunks = [
                Chunk(id="c1", content="a", chunk_type=ChunkType.PARAGRAPH),
                Chunk(id="c2", content="b", chunk_type=ChunkType.PARAGRAPH),
                Chunk(id="c3", content="c", chunk_type=ChunkType.PARAGRAPH),
            ]
            result = reranker.rerank("query", chunks, top_k=3)

        assert len(result) == 3
        assert result[0].id == "c3"

    def test_http_rerank_cache_hit_avoids_api_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_RERANK_KEY", "test-key")
        cfg = Config(
            {
                "retrieval": {
                    "reranker": {
                        "provider": "http",
                        "model_name": "BAAI/bge-reranker-v2-m3",
                        "top_k": 2,
                        "api": {
                            "base_url": "https://api.example.com/v1",
                            "api_key_env": "TEST_RERANK_KEY",
                            "timeout_seconds": 30,
                            "top_n": 2,
                        },
                    }
                }
            }
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {"index": 1, "relevance_score": 0.95},
                {"index": 0, "relevance_score": 0.80},
            ]
        }

        with patch("ate_rag_kb.retrieval.reranker_providers.httpx.post", return_value=mock_response) as mock_post:
            reranker = Reranker(cfg)
            chunks = [
                Chunk(id="c1", content="low", chunk_type=ChunkType.PARAGRAPH),
                Chunk(id="c2", content="high", chunk_type=ChunkType.PARAGRAPH),
            ]
            # First call hits API
            result1 = reranker.rerank("query", chunks)
            assert mock_post.call_count == 1

            # Second call with same query/docs should hit cache
            result2 = reranker.rerank("query", chunks)
            assert mock_post.call_count == 1  # No additional API call

            assert [c.id for c in result1] == [c.id for c in result2]

    def test_reranker_enabled_field(self) -> None:
        cfg = Config({"retrieval": {"reranker": {"enabled": False}}})
        reranker = Reranker(cfg)
        assert reranker.enabled is False

    def test_unknown_provider_raises_value_error(self) -> None:
        cfg = Config({"retrieval": {"reranker": {"provider": "nonexistent"}}})
        with pytest.raises(ValueError, match="Unknown reranker provider"):
            Reranker(cfg)
