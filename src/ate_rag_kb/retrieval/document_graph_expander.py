"""Bounded cross-document graph expansion for retrieval.

Expands initial retrieval results by following internal document links,
with strict hop, fan-out, and budget limits to prevent candidate explosion.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path
from typing import Any

from ate_rag_kb.chunking.models import Chunk, ChunkType
from ate_rag_kb.vector_store.qdrant_client import QdrantVectorStore

logger = logging.getLogger(__name__)

DEFAULT_MAX_HOPS = 1
DEFAULT_BROAD_MAX_HOPS = 2
DEFAULT_MAX_FANOUT = 5
DEFAULT_TOTAL_BUDGET = 20
DEFAULT_MAX_CHUNKS_PER_DOC = 3


class DocumentGraphExpander:
    """Expand retrieval candidates by traversing the cross-document link graph."""

    def __init__(
        self,
        graph_path: Path | None = None,
        max_hops: int = DEFAULT_MAX_HOPS,
        broad_max_hops: int = DEFAULT_BROAD_MAX_HOPS,
        max_fanout: int = DEFAULT_MAX_FANOUT,
        total_budget: int = DEFAULT_TOTAL_BUDGET,
        max_chunks_per_doc: int = DEFAULT_MAX_CHUNKS_PER_DOC,
    ) -> None:
        self.graph_path = graph_path
        self.max_hops = max_hops
        self.broad_max_hops = broad_max_hops
        self.max_fanout = max_fanout
        self.total_budget = total_budget
        self.max_chunks_per_doc = max_chunks_per_doc
        self._graph: dict[str, Any] | None = None
        self._graph_mtime: float | None = None

    def _load_graph(self) -> dict[str, Any]:
        """Load graph, reloading if the file has changed on disk."""
        if self.graph_path and self.graph_path.exists():
            mtime = self.graph_path.stat().st_mtime
            if self._graph is not None and self._graph_mtime == mtime:
                return self._graph
            import json

            self._graph = json.loads(self.graph_path.read_text(encoding="utf-8"))
            self._graph_mtime = mtime
            logger.debug("Loaded document graph with %d nodes", len(self._graph))
        else:
            self._graph = {}
        return self._graph or {}

    def expand(
        self,
        chunks: list[Chunk],
        vector_store: QdrantVectorStore,
        is_broad_concept: bool = False,
        filters: dict[str, Any] | None = None,
    ) -> tuple[list[Chunk], dict[str, Any]]:
        """Expand *chunks* with linked documents and return expanded chunks + stats.

        Returns:
            (expanded_chunks, stats_dict)
        """
        graph = self._load_graph()
        if not graph:
            return chunks, {
                "expanded_source_count": 0,
                "expanded_chunk_count": 0,
                "deduplicated_count": len(chunks),
            }

        max_hops = self.broad_max_hops if is_broad_concept else self.max_hops
        seed_chunks = self._deduplicate_chunks(chunks, graph)

        # Seed with source_mds from input chunks, preserving input order
        initial_source_mds = list(
            dict.fromkeys(
                self._preferred_source_md(graph, chunk.source_md)
                for chunk in seed_chunks
                if chunk.source_md
            )
        )

        # Track visited sources and frontier for BFS
        visited: set[str] = set(initial_source_mds)
        frontier: list[str] = list(initial_source_mds)
        expanded_source_mds: list[str] = []

        for _hop in range(max_hops):
            next_frontier: list[str] = []
            neighbor_lists = [self._neighbors(graph, source_md) for source_md in frontier]
            max_neighbor_count = max((len(neighbors) for neighbors in neighbor_lists), default=0)
            budget_exhausted = False
            for neighbor_index in range(max_neighbor_count):
                for neighbors in neighbor_lists:
                    if neighbor_index >= len(neighbors):
                        continue
                    target = neighbors[neighbor_index]
                    if target in visited:
                        continue
                    visited.add(target)
                    next_frontier.append(target)
                    expanded_source_mds.append(target)
                    if len(expanded_source_mds) >= self.total_budget:
                        budget_exhausted = True
                        break
                if budget_exhausted:
                    break

            if not next_frontier or budget_exhausted:
                break
            frontier = next_frontier

        # Deduplication state
        canonical_seen: dict[str, str] = {}
        content_hash_seen: dict[str, str] = {}
        for chunk in seed_chunks:
            source_md = chunk.source_md
            if not source_md:
                continue
            canonical, content_hash = self._source_identity(graph, source_md)
            canonical_seen.setdefault(canonical, source_md)
            if content_hash:
                content_hash_seen.setdefault(content_hash, source_md)

        # Fetch chunks for expanded sources with type priority
        expanded_chunks: list[Chunk] = []
        for source_md in expanded_source_mds:
            node = graph.get(source_md, {})
            canonical = node.get("canonical_source_md", source_md)
            content_hash = node.get("content_hash", "")

            # Canonical dedup
            if canonical in canonical_seen:
                continue
            canonical_seen[canonical] = source_md

            # Content hash dedup
            if content_hash and content_hash in content_hash_seen:
                continue
            if content_hash:
                content_hash_seen[content_hash] = source_md

            try:
                doc_chunks = self._fetch_doc_chunks_with_priority(
                    vector_store, source_md, self.max_chunks_per_doc,
                    is_broad_concept=is_broad_concept,
                    filters=filters,
                )
                for dc in doc_chunks:
                    expanded_chunks.append(replace(dc, score=0.3))
            except Exception as exc:
                logger.debug("Failed to fetch chunks for %s: %s", source_md, exc)

        final_chunks = self._deduplicate_chunks(seed_chunks + expanded_chunks, graph)
        seed_ids = {chunk.id for chunk in seed_chunks}
        stats = {
            "expanded_source_count": len(expanded_source_mds),
            "expanded_chunk_count": sum(chunk.id not in seed_ids for chunk in final_chunks),
            "deduplicated_count": len(final_chunks),
        }

        return final_chunks, stats

    def _neighbors(self, graph: dict[str, Any], source_md: str) -> list[str]:
        """Return bounded forward and reverse neighbors in stable order."""
        node = graph.get(source_md, {})
        combined = node.get("linked_source_mds", []) + node.get("referenced_by_source_mds", [])
        neighbors: list[str] = []
        seen: set[str] = set()
        for target in combined:
            preferred = self._preferred_source_md(graph, target)
            if preferred == source_md or preferred in seen:
                continue
            seen.add(preferred)
            neighbors.append(preferred)
            if len(neighbors) >= self.max_fanout:
                break
        return neighbors

    def forward_neighbors(self, source_md: str) -> list[str]:
        """Return bounded forward-linked sources in stable order."""
        graph = self._load_graph()
        node = graph.get(source_md, {})
        neighbors: list[str] = []
        seen: set[str] = set()
        for target in node.get("linked_source_mds", []):
            preferred = self._preferred_source_md(graph, target)
            if preferred == source_md or preferred in seen:
                continue
            seen.add(preferred)
            neighbors.append(preferred)
            if len(neighbors) >= self.max_fanout:
                break
        return neighbors

    def related_neighbors(self, source_md: str) -> list[str]:
        """Return bounded forward and reverse linked sources in stable order."""
        return self._neighbors(self._load_graph(), source_md)

    @staticmethod
    def _preferred_source_md(graph: dict[str, Any], source_md: str) -> str:
        """Resolve a variant to its canonical source when that source exists."""
        canonical = graph.get(source_md, {}).get("canonical_source_md", source_md)
        return canonical if canonical in graph else source_md

    @staticmethod
    def _source_identity(graph: dict[str, Any], source_md: str) -> tuple[str, str]:
        node = graph.get(source_md, {})
        return node.get("canonical_source_md", source_md), node.get("content_hash", "")

    def _deduplicate_chunks(self, chunks: list[Chunk], graph: dict[str, Any]) -> list[Chunk]:
        """Deduplicate chunks while retaining bounded context per source."""
        available_sources = {chunk.source_md for chunk in chunks if chunk.source_md}
        canonical_seen: dict[str, str] = {}
        content_hash_seen: dict[str, str] = {}
        source_counts: dict[str, int] = {}
        chunk_ids: set[str] = set()
        result: list[Chunk] = []

        for chunk in chunks:
            source_md = chunk.source_md
            if chunk.id in chunk_ids:
                continue
            if source_md:
                canonical, content_hash = self._source_identity(graph, source_md)
                if canonical in available_sources and source_md != canonical:
                    continue
                if canonical in canonical_seen and canonical_seen[canonical] != source_md:
                    continue
                if content_hash and (
                    content_hash in content_hash_seen
                    and content_hash_seen[content_hash] != source_md
                ):
                    continue
                if source_counts.get(source_md, 0) >= self.max_chunks_per_doc:
                    continue
                canonical_seen.setdefault(canonical, source_md)
                if content_hash:
                    content_hash_seen.setdefault(content_hash, source_md)
                source_counts[source_md] = source_counts.get(source_md, 0) + 1

            chunk_ids.add(chunk.id)
            result.append(chunk)

        return result

    @staticmethod
    def _fetch_doc_chunks_with_priority(
        vector_store: QdrantVectorStore,
        source_md: str,
        limit: int,
        is_broad_concept: bool = False,
        filters: dict[str, Any] | None = None,
    ) -> list[Chunk]:
        """Fetch chunks for a source, preferring DOCUMENT then SECTION types.

        For broad concept queries, prefer SECTION over DOCUMENT to avoid
        long document chunks monopolizing context.
        """
        combined: list[Chunk] = []

        if is_broad_concept:
            # Try SECTION chunks first
            section_chunks, _ = vector_store.scroll(
                filters=DocumentGraphExpander._merge_fetch_filters(
                    filters, source_md, ChunkType.SECTION
                ),
                limit=limit,
            )
            if len(section_chunks) >= limit:
                return section_chunks[:limit]

            # Try DOCUMENT chunks next
            doc_chunks, _ = vector_store.scroll(
                filters=DocumentGraphExpander._merge_fetch_filters(
                    filters, source_md, ChunkType.DOCUMENT
                ),
                limit=limit - len(section_chunks),
            )
            combined = section_chunks + doc_chunks
            if len(combined) >= limit:
                return combined[:limit]
        else:
            # Try DOCUMENT chunks first
            doc_chunks, _ = vector_store.scroll(
                filters=DocumentGraphExpander._merge_fetch_filters(
                    filters, source_md, ChunkType.DOCUMENT
                ),
                limit=limit,
            )
            if len(doc_chunks) >= limit:
                return doc_chunks[:limit]

            # Try SECTION chunks next
            section_chunks, _ = vector_store.scroll(
                filters=DocumentGraphExpander._merge_fetch_filters(
                    filters, source_md, ChunkType.SECTION
                ),
                limit=limit - len(doc_chunks),
            )
            combined = doc_chunks + section_chunks
            if len(combined) >= limit:
                return combined[:limit]

        # Fill remainder with any other chunks
        remaining, _ = vector_store.scroll(
            filters=DocumentGraphExpander._merge_fetch_filters(filters, source_md),
            limit=limit,
        )
        # Filter out already collected chunks by ID
        seen_ids = {c.id for c in combined}
        for c in remaining:
            if c.id not in seen_ids:
                combined.append(c)
            if len(combined) >= limit:
                break
        return combined[:limit]

    @staticmethod
    def _merge_fetch_filters(
        filters: dict[str, Any] | None,
        source_md: str,
        chunk_type: ChunkType | None = None,
    ) -> dict[str, Any]:
        merged = dict(filters or {})
        merged["source_md"] = source_md
        if chunk_type is not None:
            merged["chunk_type"] = chunk_type.value
        return merged
