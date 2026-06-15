"""Unit tests for hybrid retriever and RRF fusion."""

from __future__ import annotations

from unittest.mock import MagicMock

from ate_rag_kb.chunking.models import Chunk, ChunkType
from ate_rag_kb.retrieval.hybrid import HybridRetriever


class TestHybridRetriever:
    def _make_encoder_and_store(self, vector_results: list[Chunk]) -> tuple:
        encoder = MagicMock()
        encoder.encode_query.return_value = MagicMock(tolist=lambda: [0.1] * 1024)

        store = MagicMock()
        store.search.return_value = vector_results
        store.sparse_encoder = MagicMock()
        store.sparse_encoder.is_fitted.return_value = False

        return encoder, store

    def test_retrieve_returns_fused_results(self) -> None:
        chunks = [
            Chunk(id="c1", content="alpha", chunk_type=ChunkType.PARAGRAPH),
            Chunk(id="c2", content="beta", chunk_type=ChunkType.PARAGRAPH),
        ]
        encoder, store = self._make_encoder_and_store(chunks)

        retriever = HybridRetriever(encoder, store)
        result = retriever.retrieve("query", top_k=2)

        assert len(result) == 2
        assert {c.id for c in result} == {"c1", "c2"}

    def test_retrieve_respects_top_k(self) -> None:
        chunks = [
            Chunk(id=f"c{i}", content=f"text{i}", chunk_type=ChunkType.PARAGRAPH)
            for i in range(10)
        ]
        encoder, store = self._make_encoder_and_store(chunks)

        retriever = HybridRetriever(encoder, store)
        result = retriever.retrieve("query", top_k=3)

        assert len(result) == 3

    def test_retrieve_with_empty_candidates(self) -> None:
        encoder, store = self._make_encoder_and_store([])

        retriever = HybridRetriever(encoder, store)
        result = retriever.retrieve("query")

        assert result == []

    def test_reciprocal_rank_fusion_combines_scores(self) -> None:
        encoder, store = self._make_encoder_and_store([])
        retriever = HybridRetriever(encoder, store)

        v1 = Chunk(id="a", content="", chunk_type=ChunkType.PARAGRAPH)
        v2 = Chunk(id="b", content="", chunk_type=ChunkType.PARAGRAPH)
        b1 = Chunk(id="b", content="", chunk_type=ChunkType.PARAGRAPH)
        b2 = Chunk(id="c", content="", chunk_type=ChunkType.PARAGRAPH)

        fused = retriever._reciprocal_rank_fusion([v1, v2], [b1, b2])

        ids = [c.id for c in fused]
        assert "b" in ids  # appears in both lists
        assert len(ids) == 3

    def test_bm25_search_on_empty_returns_empty(self) -> None:
        encoder, store = self._make_encoder_and_store([])
        retriever = HybridRetriever(encoder, store)

        result = retriever._bm25_search("query", [])

        assert result == []

    def test_tokenize_splits_and_lowercases(self) -> None:
        result = HybridRetriever._tokenize("Hello World")

        assert result == ["hello", "world"]

    # -------------------------------------------------------------------
    # Sparse retrieval tests
    # -------------------------------------------------------------------

    def test_sparse_retrieval_independent_of_dense(self) -> None:
        """Sparse candidates are fetched separately from dense candidates."""
        encoder = MagicMock()
        encoder.encode_query.return_value = MagicMock(tolist=lambda: [0.1] * 1024)

        dense_chunk = Chunk(id="dense1", content="dense only", chunk_type=ChunkType.PARAGRAPH, score=0.8)
        sparse_chunk = Chunk(id="sparse1", content="sparse only", chunk_type=ChunkType.PARAGRAPH, score=0.7)

        store = MagicMock()
        store.search.return_value = [dense_chunk]
        store.sparse_encoder = MagicMock()
        store.sparse_encoder.is_fitted.return_value = True
        store.sparse_search.return_value = [sparse_chunk]

        from ate_rag_kb.utils.config import Config
        retriever = HybridRetriever(encoder, store, config=Config({}))
        result = retriever.retrieve("query", top_k=10)

        ids = {c.id for c in result}
        assert "dense1" in ids
        assert "sparse1" in ids
        store.sparse_search.assert_called_once()

    def test_sparse_can_recall_when_dense_misses(self) -> None:
        """When dense retrieval returns no relevant results, sparse can supplement."""
        encoder = MagicMock()
        encoder.encode_query.return_value = MagicMock(tolist=lambda: [0.1] * 1024)

        sparse_chunk = Chunk(id="sparse1", content="keyword match", chunk_type=ChunkType.PARAGRAPH)

        store = MagicMock()
        store.search.return_value = []
        store.sparse_encoder = MagicMock()
        store.sparse_encoder.is_fitted.return_value = True
        store.sparse_search.return_value = [sparse_chunk]

        retriever = HybridRetriever(encoder, store)
        result = retriever.retrieve("query", top_k=10)

        assert any(c.id == "sparse1" for c in result)

    def test_rrf_fusion_stable_ranking(self) -> None:
        """RRF fusion should be deterministic for identical inputs."""
        encoder = MagicMock()
        store = MagicMock()
        store.sparse_encoder = MagicMock()
        store.sparse_encoder.is_fitted.return_value = True

        c1 = Chunk(id="a", content="", chunk_type=ChunkType.PARAGRAPH)
        c2 = Chunk(id="b", content="", chunk_type=ChunkType.PARAGRAPH)

        store.search.return_value = [c1, c2]
        store.sparse_search.return_value = [c2, c1]

        retriever = HybridRetriever(encoder, store)
        result1 = retriever.retrieve("query", top_k=10)
        result2 = retriever.retrieve("query", top_k=10)

        assert [c.id for c in result1] == [c.id for c in result2]

    def test_filters_passed_to_both_dense_and_sparse(self) -> None:
        """Query filters must be forwarded to both retrieval paths."""
        encoder = MagicMock()
        encoder.encode_query.return_value = MagicMock(tolist=lambda: [0.1] * 1024)

        store = MagicMock()
        store.search.return_value = []
        store.sparse_encoder = MagicMock()
        store.sparse_encoder.is_fitted.return_value = True
        store.sparse_search.return_value = []

        retriever = HybridRetriever(encoder, store)
        filters = {"ecosystem": "v93000"}
        retriever.retrieve("query", filters=filters)

        store.search.assert_called_once()
        call_kwargs = store.search.call_args[1]
        assert call_kwargs.get("filters") == filters

        store.sparse_search.assert_called_once()
        sparse_kwargs = store.sparse_search.call_args[1]
        assert sparse_kwargs.get("filters") == filters

    def test_retrieve_records_real_candidate_stats(self) -> None:
        encoder = MagicMock()
        encoder.encode_query.return_value = MagicMock(tolist=lambda: [0.1] * 1024)
        dense = [
            Chunk(id="dense1", content="", chunk_type=ChunkType.PARAGRAPH),
            Chunk(id="both", content="", chunk_type=ChunkType.PARAGRAPH),
        ]
        sparse = [
            Chunk(id="both", content="", chunk_type=ChunkType.PARAGRAPH),
            Chunk(id="sparse1", content="", chunk_type=ChunkType.PARAGRAPH),
        ]
        store = MagicMock()
        store.search.return_value = dense
        store.sparse_encoder.is_fitted.return_value = True
        store.sparse_search.return_value = sparse

        retriever = HybridRetriever(encoder, store)
        retriever.retrieve("query")

        assert retriever._last_retrieval_stats == {
            "dense_candidate_count": 2,
            "sparse_candidate_count": 2,
            "fused_candidate_count": 3,
            "sparse_search_used": True,
            "legacy_bm25_fallback_used": False,
        }
