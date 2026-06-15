"""Unified retrieval pipeline for the API layer."""

from __future__ import annotations

import asyncio
import logging
import typing
from contextlib import nullcontext as _nullcontext
from dataclasses import dataclass, replace
from typing import Any

from ate_rag_kb.chunking.models import Chunk, ChunkType
from ate_rag_kb.domain.scopes import RetrievalScope
from ate_rag_kb.embedding.encoder import EmbeddingEncoder
from ate_rag_kb.retrieval.broad_context import BroadConceptAssembler
from ate_rag_kb.retrieval.compression import ContextCompressor
from ate_rag_kb.retrieval.document_graph_expander import DocumentGraphExpander
from ate_rag_kb.retrieval.hybrid import HybridRetriever
from ate_rag_kb.retrieval.parent_child import ParentChildExpander
from ate_rag_kb.retrieval.reranker import Reranker
from ate_rag_kb.utils.config import Config
from ate_rag_kb.utils.timing import StepTimer
from ate_rag_kb.vector_store.qdrant_client import QdrantVectorStore

if typing.TYPE_CHECKING:
    from ate_rag_kb.retrieval.planner import RetrievalPlan

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ScopedPipelineResult:
    chunks: list[tuple[Chunk, float]]
    processing: dict[str, Any]


class RetrievalPipeline:
    """High-level retrieval facade wiring hybrid search, reranking, expansion, and compression."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.encoder = EmbeddingEncoder(config)
        self.vector_store = QdrantVectorStore(config)
        self.hybrid = HybridRetriever(self.encoder, self.vector_store, config)
        self.reranker_enabled: bool = config.get("retrieval.reranker.enabled", True)
        self.reranker_fallback_on_error: bool = config.get(
            "retrieval.reranker.fallback_on_error", True
        )
        self.reranker = Reranker(config) if self.reranker_enabled else None
        self.expander = ParentChildExpander(config)
        self.compressor = ContextCompressor(config)

        from pathlib import Path

        graph_path = (
            Path(config.get("data.processed_dir", "./data/processed")) / "document_graph.json"
        )
        self.graph_expander = DocumentGraphExpander(graph_path=graph_path)
        self.broad_assembler = BroadConceptAssembler(config, self.graph_expander)

        self._timing_enabled: bool = config.get("retrieval.timing.enabled", False)
        self._timing_log_threshold_ms: float = config.get(
            "retrieval.timing.log_threshold_ms", 500.0
        )
        self._last_retrieval_stats: dict[str, Any] = {}

    async def search(
        self,
        query: str,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[tuple[Chunk, float]]:
        """Basic semantic search returning chunks with scores."""
        chunks: list[Chunk] = await asyncio.to_thread(self.hybrid.retrieve, query, top_k, filters)
        return [(c, c.score) for c in chunks]

    async def retrieve(
        self,
        query: str,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
        expand_parents: bool = True,
        expand_siblings: bool = True,
        rerank: bool = True,
        compress: bool = True,
        is_broad_concept: bool = False,
    ) -> list[tuple[Chunk, float]]:
        """Advanced retrieval with optional graph expansion, reranking, parent-child expansion, and compression."""
        timer = StepTimer() if getattr(self, "_timing_enabled", False) else None

        # Phase 1: hybrid retrieval (dense + sparse + RRF)
        with timer.step("hybrid_search") if timer else _nullcontext():
            chunks: list[Chunk] = await asyncio.to_thread(
                self.hybrid.retrieve, query, top_k, filters
            )
        hybrid_stats = self._capture_hybrid_stats(chunks)

        # Phase 2: document graph expansion
        with timer.step("graph_expansion") if timer else _nullcontext():
            chunks, graph_stats = await asyncio.to_thread(
                self.graph_expander.expand,
                chunks,
                self.vector_store,
                is_broad_concept=is_broad_concept,
                filters=filters,
            )

        # Phase 3: reranking (graph-expanded candidates participate)
        pre_rerank_chunk_count = len(chunks)
        rerank_stats = self._empty_rerank_stats()
        if rerank and self.reranker is not None:
            with timer.step("reranking") if timer else _nullcontext():
                try:
                    chunks = await asyncio.to_thread(
                        self.reranker.rerank, query, chunks, is_broad_concept=is_broad_concept
                    )
                    rerank_stats = self._capture_rerank_stats(
                        pre_rerank_chunk_count, chunks, is_broad_concept
                    )
                except Exception as exc:
                    rerank_stats = self._handle_rerank_error(
                        exc=exc,
                        candidate_count=pre_rerank_chunk_count,
                        fallback_chunks=chunks,
                    )

        # Phase 4: parent-child expansion
        if expand_parents or expand_siblings:
            with timer.step("parent_child_expansion") if timer else _nullcontext():
                chunks = await asyncio.to_thread(
                    self.expander.expand,
                    chunks,
                    self.vector_store,
                    include_parent=expand_parents,
                    include_siblings=expand_siblings,
                    filters=filters,
                )

        broad_stats = self._empty_broad_context_stats()
        if is_broad_concept:
            with timer.step("broad_context") if timer else _nullcontext():
                chunks, broad_stats = await asyncio.to_thread(
                    self._assemble_broad_context, query, chunks, filters
                )

        # Phase 5: compression
        if compress:
            max_tokens = broad_stats.get("broad_context_max_tokens")
            with timer.step("compression") if timer else _nullcontext():
                chunks = await asyncio.to_thread(
                    self._compress_chunks, chunks, max_tokens
                )

        final_sources = {c.source_md for c in chunks if c.source_md}
        token_estimate = sum(len(c.content) // 4 for c in chunks)
        timing_dict = timer.to_dict() if timer else {}
        self._log_slow_steps(timing_dict)

        self._last_retrieval_stats = {
            **hybrid_stats,
            "graph_expanded_source_count": graph_stats.get("expanded_source_count", 0),
            "graph_expanded_chunk_count": graph_stats.get("expanded_chunk_count", 0),
            **rerank_stats,
            **broad_stats,
            "cross_scope_dropped_chunk_count": 0,
            "title_match_preserved_chunk_count": 0,
            "final_context_source_count": len(final_sources),
            "final_context_token_estimate": token_estimate,
            "reranked_candidate_count": rerank_stats["post_rerank_candidate_count"],
            **timing_dict,
        }

        return [(c, c.score) for c in chunks]

    async def search_enriched(
        self,
        query: str,
        plan: RetrievalPlan,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[tuple[Chunk, float]]:
        """Planner-driven search with title boost and context enrichment."""
        timer = StepTimer() if getattr(self, "_timing_enabled", False) else None

        search_top_k = top_k * 3
        effective_filters = filters if filters is not None else plan.inferred_filters
        with timer.step("hybrid_search") if timer else _nullcontext():
            chunks: list[Chunk] = await asyncio.to_thread(
                self.hybrid.retrieve, plan.enhanced_query, search_top_k, effective_filters
            )
        hybrid_stats = self._capture_hybrid_stats(chunks)

        with timer.step("title_boost") if timer else _nullcontext():
            boost_factor = self.config.get("retrieval.planner.title_boost_factor", 0.15)
            chunks = self._boost_title_matches(chunks, plan.title_match_terms, boost_factor)

        primary = chunks[:top_k]
        enrichment_enabled = self.config.get("retrieval.planner.context_enrichment_enabled", True)
        if enrichment_enabled:
            with timer.step("context_enrichment") if timer else _nullcontext():
                enriched = await asyncio.to_thread(self._enrich_chunks, chunks[: top_k * 2])
            primary_ids = {c.id for c in primary}
            enrichment_budget = self.config.get("retrieval.planner.enrichment_budget", 3)
            enrichment_chunks = [c for c in enriched if c.id not in primary_ids][:enrichment_budget]
            final_chunks = primary + enrichment_chunks
        else:
            final_chunks = primary

        timing_dict = timer.to_dict() if timer else {}
        self._last_retrieval_stats = {
            **hybrid_stats,
            "graph_expanded_source_count": 0,
            "graph_expanded_chunk_count": 0,
            "deduplicated_candidate_count": len(final_chunks),
            **timing_dict,
        }

        return [(c, c.score) for c in final_chunks]

    async def retrieve_enriched(
        self,
        query: str,
        plan: RetrievalPlan,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
        expand_parents: bool = True,
        expand_siblings: bool = True,
        rerank: bool = True,
        compress: bool = True,
        scope: RetrievalScope | None = None,
    ) -> list[tuple[Chunk, float]]:
        """Advanced retrieval with planner-driven enrichment, title boost, and optional reranking/expansion/compression."""
        timer = StepTimer() if getattr(self, "_timing_enabled", False) else None

        # Phase 1: enriched search with title boost and context enrichment
        with timer.step("enriched_search") if timer else _nullcontext():
            chunks_with_scores = await self.search_enriched(
                query=query,
                plan=plan,
                top_k=top_k,
                filters=filters,
            )
        search_stats = dict(self._last_retrieval_stats)
        chunks = [c for c, _ in chunks_with_scores]

        # Phase 2: document graph expansion
        with timer.step("graph_expansion") if timer else _nullcontext():
            chunks, graph_stats = await asyncio.to_thread(
                self.graph_expander.expand,
                chunks,
                self.vector_store,
                is_broad_concept=plan.is_broad_concept,
                filters=filters,
            )

        # Phase 3: optional reranking (graph-expanded candidates participate)
        pre_rerank_chunk_count = len(chunks)
        rerank_stats = self._empty_rerank_stats()
        title_match_preserved_chunk_count = 0
        if rerank and self.reranker is not None:
            with timer.step("reranking") if timer else _nullcontext():
                rerank_candidates = list(chunks)
                rerank_query = plan.enhanced_query or query
                try:
                    chunks = await asyncio.to_thread(
                        self.reranker.rerank,
                        rerank_query,
                        chunks,
                        is_broad_concept=plan.is_broad_concept,
                        seed_count=search_stats.get(
                            "deduplicated_candidate_count", len(rerank_candidates)
                        ),
                        title_match_terms=plan.title_match_terms,
                    )
                    chunks, title_match_preserved_chunk_count = self._preserve_title_match_chunks(
                        reranked=chunks,
                        candidates=rerank_candidates,
                        title_match_terms=plan.title_match_terms,
                        max_preserved=self.config.get(
                            "retrieval.planner.title_match_preserve_count", 3
                        ),
                    )
                    rerank_stats = self._capture_rerank_stats(
                        pre_rerank_chunk_count, chunks, plan.is_broad_concept
                    )
                except Exception as exc:
                    rerank_stats = self._handle_rerank_error(
                        exc=exc,
                        candidate_count=pre_rerank_chunk_count,
                        fallback_chunks=chunks,
                    )

        # Phase 4: optional parent-child expansion
        if expand_parents or expand_siblings:
            with timer.step("parent_child_expansion") if timer else _nullcontext():
                chunks = await asyncio.to_thread(
                    self.expander.expand,
                    chunks,
                    self.vector_store,
                    include_parent=expand_parents,
                    include_siblings=expand_siblings,
                    filters=filters,
                )

        broad_stats = self._empty_broad_context_stats()
        if plan.is_broad_concept:
            with timer.step("broad_context") if timer else _nullcontext():
                chunks, broad_stats = await asyncio.to_thread(
                    self._assemble_broad_context, query, chunks, filters
                )

        cross_scope_dropped_chunk_count = 0
        if scope is not None:
            before_scope_filter = len(chunks)
            chunks = [
                chunk
                for chunk in chunks
                if scope.matches_document(chunk.vendor, chunk.platform, chunk.software)
            ]
            cross_scope_dropped_chunk_count = before_scope_filter - len(chunks)

        # Phase 5: optional compression
        if compress:
            max_tokens = broad_stats.get("broad_context_max_tokens")
            with timer.step("compression") if timer else _nullcontext():
                chunks = await asyncio.to_thread(
                    self._compress_chunks, chunks, max_tokens
                )

        final_sources = {c.source_md for c in chunks if c.source_md}
        token_estimate = sum(len(c.content) // 4 for c in chunks)
        timing_dict = timer.to_dict() if timer else {}
        self._log_slow_steps(timing_dict)

        self._last_retrieval_stats = {
            **search_stats,
            "graph_expanded_source_count": graph_stats.get("expanded_source_count", 0),
            "graph_expanded_chunk_count": graph_stats.get("expanded_chunk_count", 0),
            **rerank_stats,
            **broad_stats,
            "cross_scope_dropped_chunk_count": cross_scope_dropped_chunk_count,
            "title_match_preserved_chunk_count": title_match_preserved_chunk_count,
            "final_context_source_count": len(final_sources),
            "final_context_token_estimate": token_estimate,
            "reranked_candidate_count": rerank_stats["post_rerank_candidate_count"],
            **timing_dict,
        }

        return [(c, c.score) for c in chunks]

    async def search_scope(
        self,
        query: str,
        *,
        plan: RetrievalPlan,
        scope: RetrievalScope,
        top_k: int,
        user_filters: dict[str, Any] | None = None,
    ) -> ScopedPipelineResult:
        filters = self._scope_filters(scope, user_filters)
        chunks = await self.search_enriched(
            query=query,
            plan=plan,
            top_k=top_k,
            filters=filters,
        )
        filtered, dropped = self._filter_scored_chunks_by_scope(chunks, scope)
        processing = dict(self._last_retrieval_stats)
        processing["cross_scope_dropped_chunk_count"] = (
            processing.get("cross_scope_dropped_chunk_count", 0) + dropped
        )
        return ScopedPipelineResult(chunks=filtered, processing=processing)

    async def retrieve_scope(
        self,
        query: str,
        *,
        plan: RetrievalPlan,
        scope: RetrievalScope,
        top_k: int,
        user_filters: dict[str, Any] | None,
        rerank: bool,
        expand_parents: bool,
        expand_siblings: bool,
        compress: bool,
    ) -> ScopedPipelineResult:
        filters = self._scope_filters(scope, user_filters)
        chunks = await self.retrieve_enriched(
            query=query,
            plan=plan,
            top_k=top_k,
            filters=filters,
            expand_parents=expand_parents,
            expand_siblings=expand_siblings,
            rerank=rerank,
            compress=compress,
            scope=scope,
        )
        filtered, dropped = self._filter_scored_chunks_by_scope(chunks, scope)
        processing = dict(self._last_retrieval_stats)
        processing["cross_scope_dropped_chunk_count"] = (
            processing.get("cross_scope_dropped_chunk_count", 0) + dropped
        )
        return ScopedPipelineResult(chunks=filtered, processing=processing)

    @staticmethod
    def _empty_rerank_stats() -> dict[str, Any]:
        return {
            "post_rerank_candidate_count": 0,
            "post_rerank_source_count": 0,
            "post_diversity_candidate_count": 0,
            "post_diversity_source_count": 0,
            "low_utility_rerank_candidate_count": 0,
            "reranker_fallback_used": False,
            "reranker_error_type": "",
            "reranker_error": "",
        }

    def _handle_rerank_error(
        self,
        *,
        exc: Exception,
        candidate_count: int,
        fallback_chunks: list[Chunk],
    ) -> dict[str, Any]:
        """Return fallback stats or re-raise depending on config."""
        if not self.reranker_fallback_on_error:
            raise exc

        logger.warning("Reranker failed; using pre-rerank candidates: %s", exc)
        source_count = len({chunk.source_md for chunk in fallback_chunks if chunk.source_md})
        return {
            **self._empty_rerank_stats(),
            "post_rerank_candidate_count": candidate_count,
            "post_rerank_source_count": source_count,
            "post_diversity_candidate_count": len(fallback_chunks),
            "post_diversity_source_count": source_count,
            "reranker_fallback_used": True,
            "reranker_error_type": type(exc).__name__,
            "reranker_error": str(exc)[:300],
        }

    def _capture_rerank_stats(
        self,
        pre_rerank_chunk_count: int,
        chunks: list[Chunk],
        is_broad_concept: bool,
    ) -> dict[str, int]:
        if self.reranker is None:
            return self._empty_rerank_stats()

        raw_stats = getattr(self.reranker, "_last_rerank_stats", {})
        if isinstance(raw_stats, dict) and raw_stats:
            return {**self._empty_rerank_stats(), **raw_stats}

        if is_broad_concept:
            candidate_limit = getattr(self.reranker, "broad_candidate_top_k", len(chunks))
        else:
            candidate_limit = getattr(self.reranker, "top_k", len(chunks))
        selected_sources = {chunk.source_md for chunk in chunks if chunk.source_md}
        return {
            "post_rerank_candidate_count": min(pre_rerank_chunk_count, candidate_limit),
            "post_rerank_source_count": len(selected_sources),
            "post_diversity_candidate_count": len(chunks),
            "post_diversity_source_count": len(selected_sources),
            "low_utility_rerank_candidate_count": 0,
        }

    @staticmethod
    def _empty_broad_context_stats() -> dict[str, Any]:
        return {
            "broad_context_assembled": False,
            "broad_context_seed_source_count": 0,
            "broad_context_discovered_source_count": 0,
            "broad_context_added_chunk_count": 0,
            "broad_context_source_count": 0,
            "broad_context_token_estimate": 0,
            "broad_context_max_tokens": None,
            "low_utility_chunk_count": 0,
            "coverage_topics": [],
        }

    def _assemble_broad_context(
        self,
        query: str,
        chunks: list[Chunk],
        filters: dict[str, Any] | None = None,
    ) -> tuple[list[Chunk], dict[str, Any]]:
        assembler = getattr(self, "broad_assembler", None)
        if assembler is None:
            return chunks, self._empty_broad_context_stats()
        assembled, stats = assembler.assemble(
            chunks, self.vector_store, query=query, filters=filters
        )
        return assembled, {
            **self._empty_broad_context_stats(),
            **stats,
            "broad_context_max_tokens": assembler.max_tokens,
        }

    @staticmethod
    def _scope_filters(
        scope: RetrievalScope,
        user_filters: dict[str, Any] | None,
    ) -> dict[str, Any]:
        filters = dict(user_filters or {})
        filters.update(scope.to_filters())
        return filters

    @staticmethod
    def _filter_scored_chunks_by_scope(
        chunks: list[tuple[Chunk, float]],
        scope: RetrievalScope,
    ) -> tuple[list[tuple[Chunk, float]], int]:
        filtered = [
            (chunk, score)
            for chunk, score in chunks
            if scope.matches_document(chunk.vendor, chunk.platform, chunk.software)
        ]
        return filtered, len(chunks) - len(filtered)

    def _compress_chunks(self, chunks: list[Chunk], max_tokens: int | None) -> list[Chunk]:
        if max_tokens is None:
            return self.compressor.compress(chunks)
        return self.compressor.compress(chunks, max_tokens=max_tokens)

    def _capture_hybrid_stats(self, chunks: list[Chunk]) -> dict[str, Any]:
        """Return the retriever's real candidate counts with stable defaults."""
        raw_stats = getattr(self.hybrid, "_last_retrieval_stats", {})
        stats = dict(raw_stats) if isinstance(raw_stats, dict) else {}
        return {
            "dense_candidate_count": stats.get("dense_candidate_count", len(chunks)),
            "sparse_candidate_count": stats.get("sparse_candidate_count", 0),
            "fused_candidate_count": stats.get("fused_candidate_count", len(chunks)),
            "sparse_search_used": stats.get("sparse_search_used", False),
            "legacy_bm25_fallback_used": stats.get("legacy_bm25_fallback_used", False),
        }

    def _log_slow_steps(self, timing_dict: dict[str, float]) -> None:
        """Log warnings for pipeline steps exceeding the configured threshold."""
        if not getattr(self, "_timing_enabled", False) or not timing_dict:
            return
        threshold = getattr(self, "_timing_log_threshold_ms", 500.0)
        for key, value in timing_dict.items():
            if value > threshold:
                logger.info("Slow retrieval step: %s = %.1f ms", key, value)

    @classmethod
    def _boost_title_matches(
        cls,
        chunks: list[Chunk],
        title_match_terms: list[str],
        boost_factor: float = 0.15,
    ) -> list[Chunk]:
        """Boost chunk scores based on title/TOC term matches."""
        if not title_match_terms:
            return chunks
        boosted: list[Chunk] = []
        for chunk in chunks:
            haystack = " ".join(
                [
                    chunk.doc_title,
                    chunk.section_title,
                    chunk.subsection_title,
                    *chunk.toc_path,
                ]
            ).lower()
            match_count = cls._title_match_count(chunk, title_match_terms, haystack=haystack)
            if match_count > 0:
                chunk = replace(chunk, score=chunk.score * (1.0 + boost_factor * match_count))
            boosted.append(chunk)
        boosted.sort(key=lambda c: c.score, reverse=True)
        return boosted

    @classmethod
    def _preserve_title_match_chunks(
        cls,
        *,
        reranked: list[Chunk],
        candidates: list[Chunk],
        title_match_terms: list[str],
        max_preserved: int,
    ) -> tuple[list[Chunk], int]:
        """Prepend exact title/TOC matches that a cross-encoder may demote."""
        if not title_match_terms or max_preserved <= 0:
            return reranked, 0

        protected: list[tuple[int, float, int, Chunk]] = []
        for position, chunk in enumerate(candidates):
            match_count = cls._title_match_count(chunk, title_match_terms)
            if match_count > 0:
                protected.append((match_count, chunk.score, -position, chunk))

        if not protected:
            return reranked, 0

        selected_ids = {chunk.id for chunk in reranked}
        protected.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        preserved = [item[3] for item in protected[:max_preserved]]
        preserved_ids = {chunk.id for chunk in preserved}
        rest = [chunk for chunk in reranked if chunk.id not in preserved_ids]
        newly_preserved_count = sum(1 for chunk in preserved if chunk.id not in selected_ids)
        return preserved + rest, newly_preserved_count

    @staticmethod
    def _title_match_count(
        chunk: Chunk,
        title_match_terms: list[str],
        *,
        haystack: str | None = None,
    ) -> int:
        if haystack is None:
            haystack = " ".join(
                [
                    chunk.doc_title,
                    chunk.section_title,
                    chunk.subsection_title,
                    *chunk.toc_path,
                ]
            ).lower()
        return sum(1 for term in title_match_terms if term.lower() in haystack)

    def _enrich_chunks(self, chunks: list[Chunk]) -> list[Chunk]:
        """Supplement edge chunks with parent and document context."""
        if not chunks:
            return chunks

        result_ids = {c.id for c in chunks}
        ordered = list(chunks)

        # Collect parent_ids from edge chunks
        parent_ids: list[str] = []
        source_mds_with_docs: set[str] = set()
        source_mds_needing_doc: set[str] = set()

        for chunk in chunks:
            if chunk.chunk_type not in (ChunkType.DOCUMENT, ChunkType.SECTION):
                if chunk.parent_id:
                    parent_ids.append(chunk.parent_id)
                if chunk.source_md:
                    source_mds_needing_doc.add(chunk.source_md)
            else:
                if chunk.source_md:
                    source_mds_with_docs.add(chunk.source_md)

        # Batch fetch parents
        if parent_ids:
            fetched = self.vector_store.get_by_ids(list(dict.fromkeys(parent_ids)))
            for parent in fetched:
                if parent is not None and parent.id not in result_ids:
                    ordered.append(parent)
                    result_ids.add(parent.id)

        # Fetch document chunks for sources that lack one
        for source_md in source_mds_needing_doc - source_mds_with_docs:
            try:
                doc_chunks, _ = self.vector_store.scroll(
                    filters={"source_md": source_md, "chunk_type": ChunkType.DOCUMENT.value},
                    limit=1,
                )
                for doc_chunk in doc_chunks:
                    if doc_chunk.id not in result_ids:
                        doc_chunk.score = 0.5
                        ordered.append(doc_chunk)
                        result_ids.add(doc_chunk.id)
            except Exception:
                logger.debug("Failed to fetch document chunk for %s", source_md)

        return ordered

    async def get_related(self, chunk_id: str) -> dict[str, Any]:
        """Fetch parent, siblings, and children for a chunk."""
        chunk = await asyncio.to_thread(self.vector_store.get_by_id, chunk_id)
        if chunk is None:
            return {"parent": None, "siblings": [], "children": []}

        parent = None
        if chunk.parent_id:
            parent = await asyncio.to_thread(self.vector_store.get_by_id, chunk.parent_id)

        siblings: list[Chunk] = []
        for sid in chunk.sibling_ids:
            sc = await asyncio.to_thread(self.vector_store.get_by_id, sid)
            if sc:
                siblings.append(sc)

        children: list[Chunk] = []
        for cid in chunk.child_ids:
            cc = await asyncio.to_thread(self.vector_store.get_by_id, cid)
            if cc:
                children.append(cc)

        return {"parent": parent, "siblings": siblings, "children": children}

    async def get_document(self, source_md: str) -> list[Chunk]:
        """Return all chunks belonging to a source markdown file."""
        all_chunks: list[Chunk] = []
        offset: str | None = None
        while True:
            chunks, next_offset = await asyncio.to_thread(
                self.vector_store.scroll,
                filters={"source_md": source_md},
                limit=100,
                offset=offset,
            )
            all_chunks.extend(chunks)
            if not next_offset:
                break
            offset = next_offset
        return all_chunks

    async def get_document_page(
        self,
        source_md: str,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Return one numeric page of chunks for a source markdown file."""
        filters = {"source_md": source_md}
        total = await asyncio.to_thread(self.vector_store.count, filters)
        target_count = max(0, offset) + max(1, limit) + 1

        fetched: list[Chunk] = []
        qdrant_offset: str | None = None
        while len(fetched) < target_count:
            batch_limit = min(100, target_count - len(fetched))
            chunks, next_offset = await asyncio.to_thread(
                self.vector_store.scroll,
                filters=filters,
                limit=batch_limit,
                offset=qdrant_offset,
            )
            fetched.extend(chunks)
            if not next_offset or not chunks:
                break
            qdrant_offset = next_offset

        page_chunks = fetched[offset : offset + limit]
        has_more = offset + len(page_chunks) < total
        next_numeric_offset = offset + len(page_chunks) if has_more else None

        return {
            "chunks": page_chunks,
            "total": total,
            "returned": len(page_chunks),
            "has_more": has_more,
            "next_offset": next_numeric_offset,
        }

    async def collection_stats(self) -> dict[str, Any]:
        """Return collection statistics."""
        count = await asyncio.to_thread(self.vector_store.count)
        vector_size = self.config.get("schema.vector_size", 0)
        embedding_model = self.config.get("embedding.model_name", "")

        platforms: set[str] = set()
        doc_types: set[str] = set()
        ecosystems: set[str] = set()
        software_versions: set[str] = set()
        doc_families: set[str] = set()
        sample_limit = 1000
        sample_chunks: list[Chunk] = []
        try:
            sample_chunks, _ = await asyncio.to_thread(self.vector_store.scroll, limit=sample_limit)
            for chunk in sample_chunks:
                if chunk.platform:
                    platforms.add(chunk.platform)
                if chunk.doc_type:
                    doc_types.add(chunk.doc_type)
                if chunk.ecosystem:
                    ecosystems.add(chunk.ecosystem)
                if chunk.software_version:
                    software_versions.add(chunk.software_version)
                if chunk.doc_family:
                    doc_families.add(chunk.doc_family)
        except Exception:
            logger.exception("Failed to sample platforms/doc_types for stats")

        return {
            "collection_name": self.vector_store.collection_name,
            "total_chunks": count,
            "vector_size": vector_size,
            "embedding_model": embedding_model,
            "platforms": sorted(platforms),
            "doc_types": sorted(doc_types),
            "ecosystems": sorted(ecosystems),
            "software_versions": sorted(software_versions),
            "doc_families": sorted(doc_families),
            "sampled_chunks": len(sample_chunks),
        }
