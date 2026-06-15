"""Content-quality helpers for broad-concept retrieval."""

from __future__ import annotations

import re

from ate_rag_kb.chunking.models import Chunk, ChunkType

_IMAGE_ONLY_RE = re.compile(r"^\s*(?:Image:\s*.+|!\[[^\]]*\]\([^)]+\))\s*$", re.DOTALL)
_LOW_VALUE_SECTION_TITLES = {
    "functional changes",
    "related information",
}


def normalized_content(content: str) -> str:
    """Return whitespace-normalized content for lightweight deduplication."""
    return " ".join(content.lower().split())


def is_low_utility_chunk(chunk: Chunk) -> bool:
    """Return True for chunks that should not consume broad-answer context slots."""
    content = chunk.content.strip()
    normalized = normalized_content(content)
    section_title = normalized_content(chunk.section_title)

    if not normalized:
        return True
    if chunk.chunk_type == ChunkType.IMAGE or _IMAGE_ONLY_RE.match(content):
        return True
    if section_title in _LOW_VALUE_SECTION_TITLES:
        return True
    if normalized.startswith("functional changes") and len(normalized) < 600:
        return True

    titles = {
        normalized_content(chunk.doc_title),
        section_title,
        normalized_content(chunk.subsection_title),
    }
    if len(normalized) < 80 and normalized in titles:
        return True
    return len(normalized) < 40 and not any(char in normalized for char in ".:;!?。；：")


def chunk_quality_bonus(chunk: Chunk) -> float:
    """Return a small broad-query ranking adjustment for useful context chunks."""
    if is_low_utility_chunk(chunk):
        return -1.0

    type_bonus = {
        ChunkType.DOCUMENT: 0.24,
        ChunkType.SECTION: 0.18,
        ChunkType.SUBSECTION: 0.16,
        ChunkType.TABLE: 0.16,
        ChunkType.LIST: 0.10,
        ChunkType.PARAGRAPH: 0.08,
        ChunkType.CODE_BLOCK: 0.04,
        ChunkType.IMAGE: -1.0,
    }
    content = chunk.content
    length_bonus = min(len(content), 6000) / 6000 * 0.12
    link_bonus = min(content.count("]("), 4) * 0.03
    return type_bonus.get(chunk.chunk_type, 0.0) + length_bonus + link_bonus


def coverage_topic(chunk: Chunk) -> str:
    """Return a stable human-readable topic label for observability."""
    topic = chunk.subsection_title or chunk.section_title or chunk.doc_title
    return topic.strip() or chunk.source_md
