"""Pure metric functions for retrieval evaluation."""

from __future__ import annotations

from collections.abc import Sequence

from ate_rag_kb.chunking.models import Chunk


def hit_at_k(
    retrieved: Sequence[tuple[Chunk, float]],
    expected_chunk_ids: Sequence[str],
    k: int,
) -> float:
    """Return 1.0 if any expected chunk appears in top-k, else 0.0."""
    if k <= 0 or not expected_chunk_ids:
        return 0.0
    top_k_ids = {chunk.id for chunk, _ in retrieved[:k]}
    return 1.0 if any(eid in top_k_ids for eid in expected_chunk_ids) else 0.0


def recall_at_k(
    retrieved: Sequence[tuple[Chunk, float]],
    expected_chunk_ids: Sequence[str],
    k: int,
) -> float:
    """Return |expected intersect top-k| / |expected|."""
    if k <= 0 or not expected_chunk_ids:
        return 0.0
    top_k_ids = {chunk.id for chunk, _ in retrieved[:k]}
    expected_set = set(expected_chunk_ids)
    hits = len(expected_set & top_k_ids)
    return hits / len(expected_set)


def mrr_at_k(
    retrieved: Sequence[tuple[Chunk, float]],
    expected_chunk_ids: Sequence[str],
    k: int,
) -> float:
    """Return 1 / rank_of_first_relevant_chunk, or 0.0 if none found."""
    if k <= 0 or not expected_chunk_ids:
        return 0.0
    expected_set = set(expected_chunk_ids)
    for rank, (chunk, _) in enumerate(retrieved[:k], start=1):
        if chunk.id in expected_set:
            return 1.0 / rank
    return 0.0


def source_precision_at_k(
    retrieved: Sequence[tuple[Chunk, float]],
    expected_source_mds: Sequence[str],
    k: int,
) -> float:
    """Return |top-k with source_md in expected| / k."""
    if k <= 0 or not expected_source_mds:
        return 0.0
    expected_set = set(expected_source_mds)
    top_k = retrieved[:k]
    if not top_k:
        return 0.0
    matches = sum(1 for chunk, _ in top_k if chunk.source_md in expected_set)
    return matches / k
