"""Rerank input shaping: select and truncate candidates before sending to the reranker API.

This module limits the number and length of documents sent to the cross-encoder
reranker while preserving the full original chunks for final context output.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from ate_rag_kb.chunking.models import Chunk, ChunkType
from ate_rag_kb.utils.config import Config

logger = logging.getLogger(__name__)

# Default config values
DEFAULT_MAX_CANDIDATES = 32
DEFAULT_MAX_CHARS_PER_DOCUMENT = 2400
DEFAULT_MAX_CHUNKS_PER_SOURCE = 2
DEFAULT_MIN_SOURCES = 6
DEFAULT_PREFER_SECTION_CHUNKS = True
DEFAULT_PRESERVE_TITLE_MATCHES = 3


@dataclass(frozen=True, slots=True)
class ShapedInput:
    """Result of rerank input shaping."""

    # Selected chunks (original full objects, not truncated)
    selected_chunks: list[Chunk]

    # Truncated texts sent to the reranker API
    truncated_texts: list[str]

    # Observability stats
    pre_candidate_count: int
    post_candidate_count: int
    total_chars: int
    max_chars_per_document: int
    source_count: int
    truncated_document_count: int


@dataclass(frozen=True, slots=True)
class InputConfig:
    """Configuration for rerank input shaping."""

    max_candidates: int = DEFAULT_MAX_CANDIDATES
    max_chars_per_document: int = DEFAULT_MAX_CHARS_PER_DOCUMENT
    max_chunks_per_source: int = DEFAULT_MAX_CHUNKS_PER_SOURCE
    min_sources: int = DEFAULT_MIN_SOURCES
    prefer_section_chunks: bool = DEFAULT_PREFER_SECTION_CHUNKS
    preserve_title_matches: int = DEFAULT_PRESERVE_TITLE_MATCHES

    @classmethod
    def from_config(cls, config: Config) -> InputConfig:
        """Build InputConfig from the application config."""
        return cls(
            max_candidates=config.get(
                "retrieval.reranker.input.max_candidates", DEFAULT_MAX_CANDIDATES
            ),
            max_chars_per_document=config.get(
                "retrieval.reranker.input.max_chars_per_document",
                DEFAULT_MAX_CHARS_PER_DOCUMENT,
            ),
            max_chunks_per_source=config.get(
                "retrieval.reranker.input.max_chunks_per_source",
                DEFAULT_MAX_CHUNKS_PER_SOURCE,
            ),
            min_sources=config.get(
                "retrieval.reranker.input.min_sources", DEFAULT_MIN_SOURCES
            ),
            prefer_section_chunks=config.get(
                "retrieval.reranker.input.prefer_section_chunks",
                DEFAULT_PREFER_SECTION_CHUNKS,
            ),
            preserve_title_matches=config.get(
                "retrieval.reranker.input.preserve_title_matches",
                DEFAULT_PRESERVE_TITLE_MATCHES,
            ),
        )


def _chunk_sort_key(
    chunk: Chunk,
    is_seed: bool,
    prefer_section: bool = True,
    title_terms: list[str] | None = None,
) -> tuple[int, int, int]:
    """Sort key favoring seed chunks, title matches, and section type.

    Lower values are selected first.

    Returns:
        (seed_priority, type_priority, title_priority)
    """
    # Priority: seed (0) before graph-expanded (1)
    seed_priority = 0 if is_seed else 1

    # Chunk type priority: SECTION (0) > SUBSECTION (1) > PARAGRAPH (2) > DOCUMENT (3) > others (4)
    # When prefer_section_chunks is False, all types share the same priority (0).
    type_order = {
        ChunkType.SECTION: 0,
        ChunkType.SUBSECTION: 1,
        ChunkType.PARAGRAPH: 2,
        ChunkType.TABLE: 2,
        ChunkType.CODE_BLOCK: 2,
        ChunkType.LIST: 2,
        ChunkType.DOCUMENT: 3,
        ChunkType.IMAGE: 4,
    }
    type_priority = (
        type_order.get(chunk.chunk_type, 4) if prefer_section else 0
    )

    # Title-match priority: matching chunks sort earlier (0 > 1)
    title_priority = 0 if _has_title_match(chunk, title_terms or []) else 1

    return (seed_priority, type_priority, title_priority)


def _has_title_match(chunk: Chunk, title_terms: list[str]) -> bool:
    """Check if chunk matches any title terms."""
    if not title_terms:
        return False
    haystack = " ".join(
        [chunk.doc_title, chunk.section_title, chunk.subsection_title, *chunk.toc_path]
    ).lower()
    return any(term.lower() in haystack for term in title_terms)


def shape_rerank_input(
    chunks: list[Chunk],
    config: InputConfig,
    seed_count: int = 0,
    title_match_terms: list[str] | None = None,
    is_broad_concept: bool = False,
) -> ShapedInput:
    """Select diverse, representative chunks for reranking.

    Returns a ShapedInput containing original (full) chunks and their
    truncated texts for the API call, plus observability stats.

    Args:
        chunks: All candidate chunks after graph expansion.
        config: Input shaping configuration.
        seed_count: Number of initial search-enriched chunks at the front
            of the list (graph-expanded chunks come after).
        title_match_terms: Terms extracted from the query for title matching.
        is_broad_concept: Whether this is a broad concept query.

    Returns:
        ShapedInput with selected chunks, truncated texts, and stats.
    """
    pre_count = len(chunks)
    if not chunks:
        return ShapedInput(
            selected_chunks=[],
            truncated_texts=[],
            pre_candidate_count=0,
            post_candidate_count=0,
            total_chars=0,
            max_chars_per_document=config.max_chars_per_document,
            source_count=0,
            truncated_document_count=0,
        )

    title_terms = title_match_terms or []
    # max_candidates is ALWAYS the hard cap — broad queries trade off within it
    max_candidates = config.max_candidates

    # Step 1: Classify chunks as seed vs graph-expanded
    seed_ids = {chunk.id for chunk in chunks[:seed_count]}

    # Step 2: Sort by priority (seed first, section over document, title matches)
    sorted_chunks = sorted(
        chunks,
        key=lambda c: _chunk_sort_key(
            c, c.id in seed_ids, config.prefer_section_chunks, title_terms
        ),
    )

    # Step 3: Source-diverse selection — all chunks go through the same
    # cap-checking path.  Title-match chunks get elevated priority via
    # the sort key but never bypass max_candidates or max_chunks_per_source.

    selected: list[Chunk] = []
    source_counts: dict[str, int] = {}
    seen_ids: set[str] = set()
    seen_sources: set[str] = set()
    title_match_added = 0

    def _source_key(chunk: Chunk) -> str:
        """Chunks without source_md are treated as unique per chunk."""
        return chunk.source_md if chunk.source_md else f"__anon_{chunk.id}"

    def _add_if_allowed(
        chunk: Chunk, *, require_new_source: bool = False
    ) -> bool:
        """Try to add *chunk* respecting hard caps.  Returns True on success."""
        if len(selected) >= max_candidates:
            return False
        if chunk.id in seen_ids:
            return False
        source = _source_key(chunk)
        if require_new_source and source in seen_sources:
            return False
        current_count = source_counts.get(source, 0)
        if current_count >= config.max_chunks_per_source:
            return False
        selected.append(chunk)
        seen_ids.add(chunk.id)
        source_counts[source] = current_count + 1
        seen_sources.add(source)
        return True

    # Phase A: title-match chunks (up to preserve_title_matches), elevated
    #          priority but still respecting both caps.
    for chunk in sorted_chunks:
        if title_match_added >= config.preserve_title_matches:
            break
        if _has_title_match(chunk, title_terms) and _add_if_allowed(chunk):
            title_match_added += 1

    # Phase B: first pass — one chunk per NEW (unseen) source only
    for chunk in sorted_chunks:
        _add_if_allowed(chunk, require_new_source=True)

    # Phase C: second pass — fill remaining slots with extra chunks per source
    for chunk in sorted_chunks:
        _add_if_allowed(chunk)

    # Step 5: Build truncated texts for API call
    # Include doc_title / section_title / toc_path prefix so the reranker
    # sees structural context even when body is truncated.
    truncated_texts: list[str] = []
    truncated_count = 0
    total_chars = 0
    for chunk in selected:
        text = _build_rerank_text(chunk, config.max_chars_per_document)
        if len(text) > config.max_chars_per_document:
            # _build_rerank_text already enforces the cap, but guard anyway
            text = text[: config.max_chars_per_document]
        if len(chunk.content) > config.max_chars_per_document:
            truncated_count += 1
        truncated_texts.append(text)
        total_chars += len(text)

    unique_sources = {c.source_md for c in selected if c.source_md}

    return ShapedInput(
        selected_chunks=selected,
        truncated_texts=truncated_texts,
        pre_candidate_count=pre_count,
        post_candidate_count=len(selected),
        total_chars=total_chars,
        max_chars_per_document=config.max_chars_per_document,
        source_count=len(unique_sources),
        truncated_document_count=truncated_count,
    )


def _build_rerank_text(chunk: Chunk, max_chars: int) -> str:
    """Construct the text sent to the reranker API.

    Prepends doc_title, section_title, and toc_path so the cross-encoder
    sees structural context even when the body is truncated.  The total
    length is capped at *max_chars*.
    """
    header_parts: list[str] = []
    if chunk.toc_path:
        header_parts.append(" > ".join(chunk.toc_path))
    if chunk.doc_title:
        header_parts.append(chunk.doc_title)
    if chunk.section_title and chunk.section_title != chunk.doc_title:
        header_parts.append(chunk.section_title)

    header = " | ".join(header_parts)
    separator = "\n" if header else ""
    body_budget = max(0, max_chars - len(header) - len(separator))
    body = chunk.content[:body_budget]
    text = f"{header}{separator}{body}"
    # Final safety cap
    return text[:max_chars]


def content_digest(text: str) -> str:
    """Return a stable SHA-256 digest for a document text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
