"""Provider-based cross-encoder reranker for retrieved chunks."""

from __future__ import annotations

import logging

from ate_rag_kb.chunking.models import Chunk
from ate_rag_kb.retrieval.chunk_quality import (
    chunk_quality_bonus,
    coverage_topic,
    is_low_utility_chunk,
)
from ate_rag_kb.retrieval.rerank_input import (
    InputConfig,
    shape_rerank_input,
)
from ate_rag_kb.retrieval.reranker_providers import (
    HttpRerankerProvider,
    LocalRerankerProvider,
)
from ate_rag_kb.utils.config import Config

logger = logging.getLogger(__name__)

_PROVIDER_MAP = {
    "local": LocalRerankerProvider,
    "http": HttpRerankerProvider,
}


class Reranker:
    """Rerank query-chunk pairs using a pluggable reranker provider."""

    def __init__(self, config: Config | None = None) -> None:
        cfg = config or Config({})
        self.enabled: bool = cfg.get("retrieval.reranker.enabled", True)
        self.top_k = cfg.get("retrieval.reranker.top_k", 5)
        self.batch_size = cfg.get("retrieval.reranker.batch_size", 16)
        self.broad_candidate_top_k = cfg.get("retrieval.reranker.broad_candidate_top_k", 16)
        self.broad_final_top_k = cfg.get("retrieval.reranker.broad_final_top_k", 10)
        self.broad_max_sources = cfg.get("retrieval.reranker.broad_max_sources", 8)
        self.broad_min_sources = cfg.get("retrieval.reranker.broad_min_sources", 3)
        self.broad_max_chunks_per_source = cfg.get(
            "retrieval.reranker.broad_max_chunks_per_source", 3
        )
        self.input_config = InputConfig.from_config(cfg)

        provider_name: str = cfg.get("retrieval.reranker.provider", "local")
        provider_cls = _PROVIDER_MAP.get(provider_name)
        if provider_cls is None:
            raise ValueError(
                f"Unknown reranker provider: {provider_name!r}. "
                f"Supported providers: {sorted(_PROVIDER_MAP)}"
            )
        self._provider = provider_cls(cfg)
        self._last_rerank_stats: dict[str, int] = {}

    @property
    def model(self) -> object:
        return getattr(self._provider, "model", None)

    @property
    def device(self) -> str:
        return getattr(self._provider, "device", "cpu")

    def rerank(
        self,
        query: str,
        chunks: list[Chunk],
        top_k: int | None = None,
        is_broad_concept: bool = False,
        seed_count: int = 0,
        title_match_terms: list[str] | None = None,
    ) -> list[Chunk]:
        if not chunks:
            return []

        # Shape input: select diverse candidates and truncate for API
        shaped = shape_rerank_input(
            chunks=chunks,
            config=self.input_config,
            seed_count=seed_count,
            title_match_terms=title_match_terms,
            is_broad_concept=is_broad_concept,
        )

        # Build pairs using truncated texts for the API call
        pairs = [(query, text) for text in shaped.truncated_texts]
        scores = self._provider.predict(pairs, batch_size=self.batch_size, show_progress_bar=False)

        # Map scores back to the original full chunks
        scored = list(zip(shaped.selected_chunks, scores, strict=True))
        scored.sort(key=lambda item: item[1], reverse=True)

        if is_broad_concept:
            scored.sort(
                key=lambda item: (
                    not is_low_utility_chunk(item[0]),
                    item[1] + chunk_quality_bonus(item[0]),
                ),
                reverse=True,
            )
            candidate_pool = scored[: self.broad_candidate_top_k]
            selected = self._select_coverage_diverse(
                [c for c, _ in candidate_pool],
                max_chunks=self.broad_final_top_k,
                max_sources=self.broad_max_sources,
                min_sources=self.broad_min_sources,
                max_chunks_per_source=self.broad_max_chunks_per_source,
            )
            self._last_rerank_stats = {
                "pre_rerank_candidate_count": shaped.pre_candidate_count,
                "rerank_input_candidate_count": shaped.post_candidate_count,
                "rerank_input_total_chars": shaped.total_chars,
                "rerank_input_max_chars_per_document": shaped.max_chars_per_document,
                "rerank_input_source_count": shaped.source_count,
                "rerank_input_truncated_document_count": shaped.truncated_document_count,
                "post_rerank_candidate_count": len(candidate_pool),
                "post_rerank_source_count": len(
                    {chunk.source_md for chunk, _ in candidate_pool if chunk.source_md}
                ),
                "post_diversity_candidate_count": len(selected),
                "post_diversity_source_count": len(
                    {chunk.source_md for chunk in selected if chunk.source_md}
                ),
                "low_utility_rerank_candidate_count": sum(
                    is_low_utility_chunk(chunk) for chunk, _ in candidate_pool
                ),
            }
            return selected

        tk = top_k or self.top_k
        selected = [c for c, _ in scored[:tk]]
        self._last_rerank_stats = {
            "pre_rerank_candidate_count": shaped.pre_candidate_count,
            "rerank_input_candidate_count": shaped.post_candidate_count,
            "rerank_input_total_chars": shaped.total_chars,
            "rerank_input_max_chars_per_document": shaped.max_chars_per_document,
            "rerank_input_source_count": shaped.source_count,
            "rerank_input_truncated_document_count": shaped.truncated_document_count,
            "post_rerank_candidate_count": len(selected),
            "post_rerank_source_count": len(
                {chunk.source_md for chunk in selected if chunk.source_md}
            ),
            "post_diversity_candidate_count": len(selected),
            "post_diversity_source_count": len(
                {chunk.source_md for chunk in selected if chunk.source_md}
            ),
            "low_utility_rerank_candidate_count": sum(
                is_low_utility_chunk(chunk) for chunk in selected
            ),
        }
        return selected

    @staticmethod
    def _select_coverage_diverse(
        chunks: list[Chunk],
        max_chunks: int,
        max_sources: int,
        min_sources: int,
        max_chunks_per_source: int,
    ) -> list[Chunk]:
        """Select content-bearing chunks with source and topic coverage.

        Pass 1: establish a small source-diverse base.
        Pass 2: add chunks that cover new sections or subtopics.
        Pass 3: fill remaining slots in rank order.
        """
        if not chunks:
            return []

        useful_chunks = [chunk for chunk in chunks if not is_low_utility_chunk(chunk)]
        candidates = useful_chunks or chunks
        result: list[Chunk] = []
        seen_sources: set[str] = set()
        seen_topics: set[tuple[str, str]] = set()
        seen_ids: set[str] = set()
        source_counts: dict[str, int] = {}

        def add(chunk: Chunk) -> bool:
            source = chunk.source_md or ""
            if chunk.id in seen_ids:
                return False
            if source not in seen_sources and len(seen_sources) >= max_sources:
                return False
            if source_counts.get(source, 0) >= max_chunks_per_source:
                return False
            result.append(chunk)
            seen_sources.add(source)
            seen_topics.add((source, coverage_topic(chunk).lower()))
            seen_ids.add(chunk.id)
            source_counts[source] = source_counts.get(source, 0) + 1
            return True

        for chunk in candidates:
            if len(result) >= max_chunks or len(seen_sources) >= min_sources:
                break
            if (chunk.source_md or "") not in seen_sources:
                add(chunk)

        for chunk in candidates:
            if len(result) >= max_chunks:
                break
            topic = (chunk.source_md or "", coverage_topic(chunk).lower())
            if topic not in seen_topics:
                add(chunk)

        for chunk in candidates:
            if len(result) >= max_chunks:
                break
            add(chunk)

        return result
