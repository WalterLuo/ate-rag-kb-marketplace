"""Context compression: merge, deduplicate, truncate."""

from __future__ import annotations

import logging
from dataclasses import replace

from ate_rag_kb.chunking.models import Chunk
from ate_rag_kb.utils.config import Config

logger = logging.getLogger(__name__)


class ContextCompressor:
    """Compress a list of chunks for LLM context window."""

    def __init__(self, config: Config | None = None) -> None:
        cfg = config or Config({})
        self.merge_adjacent = cfg.get("retrieval.compression.merge_adjacent", True)
        self.remove_duplicates = cfg.get("retrieval.compression.remove_duplicates", True)
        self.max_tokens = cfg.get("retrieval.compression.max_tokens", 4000)

    def compress(self, chunks: list[Chunk], max_tokens: int | None = None) -> list[Chunk]:
        if not chunks:
            return []
        token_budget = self.max_tokens if max_tokens is None else max_tokens

        if self.remove_duplicates:
            seen: set[str] = set()
            unique: list[Chunk] = []
            for c in chunks:
                if c.id not in seen:
                    unique.append(c)
                    seen.add(c.id)
            chunks = unique

        if self.merge_adjacent:
            chunks = self._merge_adjacent(chunks)

        result: list[Chunk] = []
        total_tokens = 0
        for chunk in chunks:
            est_tokens = len(chunk.content) // 4
            if total_tokens + est_tokens > token_budget:
                remaining = token_budget - total_tokens
                if remaining > 100:
                    result.append(replace(chunk, content=chunk.content[: remaining * 4]))
                break
            result.append(chunk)
            total_tokens += est_tokens

        return result

    @staticmethod
    def _merge_adjacent(chunks: list[Chunk]) -> list[Chunk]:
        if not chunks:
            return []

        merged: list[Chunk] = []
        current = chunks[0]

        for nxt in chunks[1:]:
            if (
                nxt.source_md == current.source_md
                and nxt.section_title == current.section_title
                and nxt.chunk_type == current.chunk_type
                and len(current.content) + len(nxt.content) < 3000
            ):
                current = replace(
                    current,
                    content=current.content + "\n\n" + nxt.content,
                    end_line=nxt.end_line,
                    images=[*current.images, *[i for i in nxt.images if i not in current.images]],
                    tables=[*current.tables, *[t for t in nxt.tables if t not in current.tables]],
                    code_blocks=[*current.code_blocks, *[c for c in nxt.code_blocks if c not in current.code_blocks]],
                )
            else:
                merged.append(current)
                current = nxt

        merged.append(current)
        return merged
