"""Hybrid retrieval: dense vector search + sparse vector search + fusion."""

from __future__ import annotations

import logging
from contextlib import nullcontext as _nullcontext
from typing import Any

from rank_bm25 import BM25Okapi

from ate_rag_kb.chunking.models import Chunk
from ate_rag_kb.embedding.encoder import EmbeddingEncoder
from ate_rag_kb.utils.config import Config
from ate_rag_kb.utils.timing import StepTimer
from ate_rag_kb.vector_store.qdrant_client import QdrantVectorStore

logger = logging.getLogger(__name__)


class HybridRetriever:
    """Combines dense vector search with corpus-wide sparse vector search."""

    def __init__(
        self,
        encoder: EmbeddingEncoder,
        vector_store: QdrantVectorStore,
        config: Config | None = None,
    ) -> None:
        cfg = config or Config({})
        self.encoder = encoder
        self.vector_store = vector_store
        self.vector_top_k = cfg.get("retrieval.vector_search.top_k", 20)
        self.sparse_enabled = cfg.get("retrieval.sparse_search.enabled", True)
        self.sparse_top_k = cfg.get("retrieval.sparse_search.top_k", 20)
        self.dense_weight = cfg.get("retrieval.hybrid.dense_weight", 0.7)
        self.sparse_weight = cfg.get("retrieval.hybrid.sparse_weight", 0.3)
        self.final_top_k = cfg.get("retrieval.hybrid.final_top_k", 10)
        self.legacy_bm25_enabled = cfg.get("retrieval.hybrid.legacy_bm25_fallback", True)
        self.k1 = cfg.get("retrieval.bm25_search.k1", 1.5)
        self.b = cfg.get("retrieval.bm25_search.b", 0.75)
        self._timing_enabled = cfg.get("retrieval.timing.enabled", False)
        self._last_retrieval_stats: dict[str, Any] = {}

    def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[Chunk]:
        """Retrieve chunks using hybrid fusion.

        Flow:
            1. Dense retrieval (vector search)
            2. Sparse retrieval (corpus-wide sparse vector search) if available
            3. RRF fusion of both result sets
            4. If sparse is unavailable and legacy fallback enabled,
               run BM25 on dense candidates as a compatibility fallback.
        """
        top_k = top_k or self.final_top_k
        timer = StepTimer() if self._timing_enabled else None

        with timer.step("dense_search") if timer else _nullcontext():
            query_vector = self.encoder.encode_query(query)
            vector_results = self.vector_store.search(
                query_vector.tolist(),
                top_k=self.vector_top_k,
                filters=filters,
            )

        sparse_results: list[Chunk] = []
        sparse_search_used = False
        legacy_bm25_fallback_used = False
        sparse_encoder = getattr(self.vector_store, "sparse_encoder", None)
        store_sparse_enabled = getattr(self.vector_store, "enable_sparse_vectors", True) is not False
        if (
            self.sparse_enabled
            and store_sparse_enabled
            and sparse_encoder is not None
            and sparse_encoder.is_fitted()
        ):
            with timer.step("sparse_search") if timer else _nullcontext():
                try:
                    sparse_search_used = True
                    sparse_results = self.vector_store.sparse_search(
                        query,
                        top_k=self.sparse_top_k,
                        filters=filters,
                    )
                except Exception as exc:
                    logger.warning("Sparse search failed: %s", exc)

        if sparse_results:
            with timer.step("rrf_fusion") if timer else _nullcontext():
                fused = self._reciprocal_rank_fusion(vector_results, sparse_results)
        elif self.legacy_bm25_enabled:
            logger.debug("Sparse retrieval unavailable; using legacy BM25 fallback.")
            legacy_bm25_fallback_used = True
            with timer.step("bm25_fallback") if timer else _nullcontext():
                bm25_results = self._bm25_search(query, vector_results)
                fused = self._reciprocal_rank_fusion(vector_results, bm25_results)
        else:
            fused = vector_results

        timing_dict = timer.to_dict() if timer else {}
        self._last_retrieval_stats = {
            "dense_candidate_count": len(vector_results),
            "sparse_candidate_count": len(sparse_results),
            "fused_candidate_count": len(fused),
            "sparse_search_used": sparse_search_used,
            "legacy_bm25_fallback_used": legacy_bm25_fallback_used,
            **timing_dict,
        }
        return fused[:top_k]

    def _bm25_search(self, query: str, candidates: list[Chunk]) -> list[Chunk]:
        """Legacy fallback: BM25 re-ranking on dense candidates only."""
        if not candidates:
            return []

        tokenized_corpus = [self._tokenize(c.content) for c in candidates]
        bm25 = BM25Okapi(tokenized_corpus, k1=self.k1, b=self.b)
        scores = bm25.get_scores(self._tokenize(query))

        scored = list(zip(candidates, scores, strict=True))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [c for c, _ in scored[: self.sparse_top_k]]

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return text.lower().split()

    def _reciprocal_rank_fusion(
        self,
        dense_results: list[Chunk],
        sparse_results: list[Chunk],
    ) -> list[Chunk]:
        """Fuse two ranked lists via weighted Reciprocal Rank Fusion."""
        k = 60
        scores: dict[str, float] = {}

        for rank, chunk in enumerate(dense_results):
            scores[chunk.id] = scores.get(chunk.id, 0.0) + self.dense_weight * (
                1.0 / (k + rank + 1)
            )

        for rank, chunk in enumerate(sparse_results):
            scores[chunk.id] = scores.get(chunk.id, 0.0) + self.sparse_weight * (
                1.0 / (k + rank + 1)
            )

        id_to_chunk = {c.id: c for c in dense_results + sparse_results}
        sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
        return [id_to_chunk[cid] for cid in sorted_ids if cid in id_to_chunk]
