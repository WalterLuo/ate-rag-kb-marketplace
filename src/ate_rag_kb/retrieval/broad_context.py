"""Automatic context assembly for broad-concept questions."""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from typing import Any

from ate_rag_kb.chunking.models import Chunk, ChunkType
from ate_rag_kb.retrieval.chunk_quality import (
    chunk_quality_bonus,
    coverage_topic,
    is_low_utility_chunk,
    normalized_content,
)
from ate_rag_kb.retrieval.document_graph_expander import DocumentGraphExpander
from ate_rag_kb.utils.config import Config
from ate_rag_kb.vector_store.qdrant_client import QdrantVectorStore

logger = logging.getLogger(__name__)


class BroadConceptAssembler:
    """Build a compact, content-bearing context package for broad questions.

    The assembler follows forward document links discovered at runtime. It does
    not contain topic-specific source paths or query-specific recall rules.
    """

    def __init__(self, config: Config, graph_expander: DocumentGraphExpander) -> None:
        self.graph_expander = graph_expander
        self.enabled = config.get("retrieval.broad_context.enabled", True)
        self.seed_sources = config.get("retrieval.broad_context.seed_sources", 4)
        self.max_sources = config.get("retrieval.broad_context.max_sources", 32)
        self.max_hops = config.get("retrieval.broad_context.max_hops", 2)
        self.max_chunks = config.get("retrieval.broad_context.max_chunks", 16)
        self.max_chunks_per_source = config.get(
            "retrieval.broad_context.max_chunks_per_source", 3
        )
        self.max_tokens = config.get("retrieval.broad_context.max_tokens", 9000)
        self.document_max_chars = config.get(
            "retrieval.broad_context.document_max_chars", 9000
        )
        self.sections_per_source = config.get(
            "retrieval.broad_context.sections_per_source", 2
        )

    def assemble(
        self,
        chunks: list[Chunk],
        vector_store: QdrantVectorStore,
        query: str = "",
        filters: dict[str, Any] | None = None,
    ) -> tuple[list[Chunk], dict[str, Any]]:
        """Return broad-answer context plus observability stats."""
        stats: dict[str, Any] = {
            "broad_context_assembled": False,
            "broad_context_seed_source_count": 0,
            "broad_context_discovered_source_count": 0,
            "broad_context_added_chunk_count": 0,
            "broad_context_source_count": 0,
            "broad_context_token_estimate": 0,
            "low_utility_chunk_count": sum(is_low_utility_chunk(c) for c in chunks),
            "coverage_topics": [],
        }
        if not self.enabled or not chunks:
            return chunks, stats

        seed_sources = self._seed_source_mds(chunks)
        discovered_sources = self._discover_related_sources(seed_sources)
        representatives: list[Chunk] = []
        for source_md in discovered_sources:
            representatives.extend(
                self._fetch_representatives(vector_store, source_md, filters=filters)
            )
        source_priorities = self._coverage_source_priorities(query, representatives)
        representatives.sort(
            key=lambda chunk: (
                source_priorities.get(chunk.source_md, 0),
                *self._context_priority(query, chunk, discovered_sources),
            ),
            reverse=True,
        )

        assembled = self._select_context([*representatives, *chunks])
        if not assembled:
            assembled = chunks

        original_ids = {chunk.id for chunk in chunks}
        stats.update(
            {
                "broad_context_assembled": True,
                "broad_context_seed_source_count": len(seed_sources),
                "broad_context_discovered_source_count": len(discovered_sources),
                "broad_context_added_chunk_count": sum(
                    chunk.id not in original_ids for chunk in assembled
                ),
                "broad_context_source_count": len(
                    {chunk.source_md for chunk in assembled if chunk.source_md}
                ),
                "broad_context_token_estimate": sum(
                    max(1, len(chunk.content) // 4) for chunk in assembled
                ),
                "coverage_topics": list(
                    dict.fromkeys(coverage_topic(chunk) for chunk in assembled)
                ),
            }
        )
        return assembled, stats

    def _seed_source_mds(self, chunks: list[Chunk]) -> list[str]:
        useful = [chunk for chunk in chunks if chunk.source_md and not is_low_utility_chunk(chunk)]
        fallback = [chunk for chunk in chunks if chunk.source_md]
        candidates = useful or fallback
        return list(dict.fromkeys(chunk.source_md for chunk in candidates))[: self.seed_sources]

    def _discover_related_sources(self, seed_sources: list[str]) -> list[str]:
        ordered = list(dict.fromkeys(seed_sources))
        seen = set(ordered)
        frontier = list(ordered)

        for _hop in range(self.max_hops):
            next_frontier: list[str] = []
            neighbor_lists = [
                self.graph_expander.related_neighbors(source_md) for source_md in frontier
            ]
            max_neighbor_count = max((len(neighbors) for neighbors in neighbor_lists), default=0)
            for neighbor_index in range(max_neighbor_count):
                for neighbors in neighbor_lists:
                    if neighbor_index >= len(neighbors):
                        continue
                    target = neighbors[neighbor_index]
                    if target in seen:
                        continue
                    ordered.append(target)
                    seen.add(target)
                    next_frontier.append(target)
                    if len(ordered) >= self.max_sources:
                        return ordered
            if not next_frontier:
                break
            frontier = next_frontier

        return ordered

    def _coverage_source_priorities(
        self,
        query: str,
        representatives: list[Chunk],
    ) -> dict[str, int]:
        """Prioritize concept hubs and their linked subtopics before text-only matches."""
        phrases = self._query_phrases(query)
        priorities: dict[str, int] = {}
        hub_sources: list[str] = []

        for chunk in representatives:
            title = normalized_content(
                " ".join([chunk.doc_title, chunk.section_title, chunk.subsection_title])
            )
            forward_neighbors = self.graph_expander.forward_neighbors(chunk.source_md)
            if forward_neighbors and any(phrase in title for phrase in phrases):
                priorities[chunk.source_md] = 3
                hub_sources.append(chunk.source_md)

        for source_md in hub_sources:
            for child_source_md in self.graph_expander.forward_neighbors(source_md):
                priorities[child_source_md] = max(priorities.get(child_source_md, 0), 2)

        first_level_sources = [
            source_md for source_md, priority in priorities.items() if priority == 2
        ]
        for source_md in first_level_sources:
            for child_source_md in self.graph_expander.forward_neighbors(source_md):
                priorities[child_source_md] = max(priorities.get(child_source_md, 0), 1)

        return priorities

    @staticmethod
    def _query_phrases(query: str) -> list[str]:
        terms = [
            term
            for term in re.findall(r"[a-z0-9_]+", query.lower())
            if len(term) >= 3
        ]
        return [" ".join(terms[index : index + 2]) for index in range(len(terms) - 1)]

    @staticmethod
    def _context_priority(
        query: str,
        chunk: Chunk,
        discovered_sources: list[str],
    ) -> tuple[int, int, int, int, float, int]:
        """Rank representatives by query match while keeping graph order stable."""
        terms = [
            term
            for term in re.findall(r"[a-z0-9_]+", query.lower())
            if len(term) >= 3
        ]
        title = normalized_content(
            " ".join([chunk.doc_title, chunk.section_title, chunk.subsection_title])
        )
        body = normalized_content(chunk.content[:5000])
        phrases = BroadConceptAssembler._query_phrases(query)
        title_phrase_matches = sum(phrase in title for phrase in phrases)
        body_phrase_matches = sum(phrase in body for phrase in phrases)
        title_matches = sum(term in title for term in terms)
        body_matches = sum(term in body for term in terms)
        source_order = discovered_sources.index(chunk.source_md)
        return (
            title_phrase_matches,
            title_matches,
            body_phrase_matches,
            body_matches,
            chunk_quality_bonus(chunk),
            -source_order,
        )

    def _fetch_representatives(
        self,
        vector_store: QdrantVectorStore,
        source_md: str,
        filters: dict[str, Any] | None = None,
    ) -> list[Chunk]:
        try:
            documents, _ = vector_store.scroll(
                filters=self._merge_fetch_filters(filters, source_md, ChunkType.DOCUMENT),
                limit=1,
            )
            if documents:
                document = documents[0]
                if (
                    len(document.content) <= self.document_max_chars
                    and not is_low_utility_chunk(document)
                ):
                    return [replace(document, score=max(document.score, 0.45))]

            sections, _ = vector_store.scroll(
                filters=self._merge_fetch_filters(filters, source_md, ChunkType.SECTION),
                limit=max(self.sections_per_source * 3, self.sections_per_source),
            )
            useful_sections = [
                section for section in sections if not is_low_utility_chunk(section)
            ]
            useful_sections.sort(key=chunk_quality_bonus, reverse=True)
            return [
                replace(section, score=max(section.score, 0.4))
                for section in useful_sections[: self.sections_per_source]
            ]
        except Exception as exc:
            logger.debug("Failed to assemble broad context for %s: %s", source_md, exc)
            return []

    @staticmethod
    def _merge_fetch_filters(
        filters: dict[str, Any] | None,
        source_md: str,
        chunk_type: ChunkType,
    ) -> dict[str, Any]:
        merged = dict(filters or {})
        merged.update({"source_md": source_md, "chunk_type": chunk_type.value})
        return merged

    def _select_context(self, chunks: list[Chunk]) -> list[Chunk]:
        selected: list[Chunk] = []
        selected_ids: set[str] = set()
        selected_content: list[str] = []
        source_counts: dict[str, int] = {}
        total_tokens = 0

        for chunk in chunks:
            if chunk.id in selected_ids or is_low_utility_chunk(chunk):
                continue
            normalized = normalized_content(chunk.content)
            if any(
                normalized == existing
                or (len(normalized) > 120 and normalized in existing)
                for existing in selected_content
            ):
                continue

            source_md = chunk.source_md
            if source_counts.get(source_md, 0) >= self.max_chunks_per_source:
                continue
            estimated_tokens = max(1, len(chunk.content) // 4)
            if total_tokens + estimated_tokens > self.max_tokens:
                continue

            selected.append(chunk)
            selected_ids.add(chunk.id)
            selected_content.append(normalized)
            source_counts[source_md] = source_counts.get(source_md, 0) + 1
            total_tokens += estimated_tokens
            if len(selected) >= self.max_chunks:
                break

        return selected
