"""Build agent-native context packages from retrieved chunks."""

from __future__ import annotations

import logging

from ate_rag_kb.chunking.models import Chunk
from ate_rag_kb.domain.scopes import RetrievalScope
from ate_rag_kb.mcp.models import McpChunkResult, McpContextPackage

logger = logging.getLogger(__name__)


def _chunk_to_mcp(chunk: Chunk, score: float = 0.0, is_expanded: bool = False) -> McpChunkResult:
    """Convert internal Chunk to MCP ChunkResult."""
    return McpChunkResult(
        id=chunk.id,
        content=chunk.content,
        score=round(score, 4),
        chunk_type=chunk.chunk_type.value,
        doc_title=chunk.doc_title,
        section_title=chunk.section_title,
        subsection_title=chunk.subsection_title,
        source_md=chunk.source_md,
        toc_path=chunk.toc_path,
        vendor=chunk.vendor,
        platform=chunk.platform,
        software=chunk.software,
        software_release=chunk.software_release,
        doc_type=chunk.doc_type,
        ecosystem=chunk.ecosystem,
        software_version=chunk.software_version,
        doc_family=chunk.doc_family,
        heading_level=chunk.heading_level,
        start_line=chunk.start_line,
        end_line=chunk.end_line,
        parent_id=chunk.parent_id,
        sibling_ids=chunk.sibling_ids,
        child_ids=chunk.child_ids,
        is_expanded=is_expanded,
    )


def build_scoped_context_package(
    groups: list[tuple[RetrievalScope, list[tuple[Chunk, float]]]],
    max_tokens: int = 4000,
) -> McpContextPackage:
    """Format grouped scoped chunks without flattening platform boundaries."""
    parts: list[str] = []
    citation_map: list[dict] = []
    token_estimate = 0
    citation_index = 1
    scope_budget = max(1, max_tokens // max(1, len(groups)))

    for scope, chunks in groups:
        header = f"## {scope.platform.upper()} / {scope.software.upper()}\n"
        parts.append(header)
        token_estimate += len(header) // 4
        scope_tokens = 0

        for chunk, _score in chunks:
            entry = (
                f'[{citation_index}] From "{chunk.doc_title or "Unknown"}" '
                f'> "{chunk.section_title or "Unknown"}":\n'
                f"    {chunk.content.strip()}\n"
            )
            entry_tokens = max(1, len(entry) // 4)
            if scope_tokens + entry_tokens > scope_budget:
                break

            parts.append(entry)
            token_estimate += entry_tokens
            scope_tokens += entry_tokens
            citation_map.append(
                {
                    "index": citation_index,
                    "scope": scope.key,
                    "chunk_id": chunk.id,
                    "source_md": chunk.source_md,
                    "toc_path": chunk.toc_path,
                    "start_line": chunk.start_line,
                    "end_line": chunk.end_line,
                }
            )
            citation_index += 1

    return McpContextPackage(
        text="\n".join(parts),
        token_estimate=token_estimate,
        citation_map=citation_map,
    )


def build_context_package(
    chunks: list[tuple[Chunk, float]],
    max_tokens: int = 4000,
) -> McpContextPackage:
    """Format chunks into a pre-formatted context string with citation markers.

    The output text uses numeric citations [1], [2] so the agent can reference
    sources without embedding raw metadata in the synthesized answer.
    """
    parts: list[str] = []
    citation_map: list[dict] = []
    token_estimate = 0

    for idx, (chunk, _score) in enumerate(chunks, start=1):
        header = f'[{idx}] From "{chunk.doc_title or "Unknown"}" > "{chunk.section_title or "Unknown"}"'
        if chunk.ecosystem:
            eco = chunk.ecosystem
            if chunk.software_version:
                eco += f" / {chunk.software_version}"
            header += f" ({eco})"
        elif chunk.platform:
            header += f" ({chunk.platform})"
        header += ":\n"

        body = chunk.content.strip()
        entry = f"{header}    {body}\n"

        token_estimate += len(entry) // 4  # Rough estimate: ~4 chars per token

        parts.append(entry)
        citation_map.append(
            {
                "index": idx,
                "chunk_id": chunk.id,
                "source_md": chunk.source_md,
                "toc_path": chunk.toc_path,
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
            }
        )

        if token_estimate >= max_tokens:
            logger.debug("Context package reached token budget at chunk %d", idx)
            break

    return McpContextPackage(
        text="\n".join(parts),
        token_estimate=token_estimate,
        citation_map=citation_map,
    )


def build_sources_summary(
    chunks: list[McpChunkResult],
) -> list[dict]:
    """Build unique source files summary ordered by top score."""
    source_map: dict[str, dict] = {}
    for chunk in chunks:
        smd = chunk.source_md
        if not smd:
            continue
        if smd not in source_map:
            source_map[smd] = {"source_md": smd, "chunk_count": 0, "top_score": chunk.score}
        source_map[smd]["chunk_count"] += 1
        source_map[smd]["top_score"] = max(source_map[smd]["top_score"], chunk.score)

    return sorted(source_map.values(), key=lambda x: x["top_score"], reverse=True)


def compute_confidence(chunks: list[McpChunkResult]) -> str:
    """Compute confidence level based on score distribution.

    - high: top score > 0.8 and gap between top-1 and top-3 > 0.2
    - medium: top score > 0.5
    - low: top score <= 0.5 or no results
    """
    if not chunks:
        return "low"

    scores = [c.score for c in chunks]
    top_score = scores[0]

    if top_score > 0.8 and len(scores) >= 3 and (top_score - scores[2]) > 0.2:
        return "high"
    if top_score > 0.5:
        return "medium"
    return "low"
