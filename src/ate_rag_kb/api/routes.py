"""API route definitions for ATE RAG Knowledge Base."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ate_rag_kb.api.models import (
    AskRequest,
    AskResponse,
    ChunkResult,
    Citation,
    DocumentResponse,
    RelatedRequest,
    RelatedResponse,
    ResolvedScope,
    RetrieveRequest,
    RetrieveResponse,
    SearchRequest,
    SearchResponse,
)
from ate_rag_kb.chunking.models import Chunk
from ate_rag_kb.retrieval.coordinator import CoordinatedRetrievalResult
from ate_rag_kb.retrieval.planner import RetrievalPlanner
from ate_rag_kb.utils.timing import StepTimer

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Placeholder retrieval layer — replace with real vector store + pipeline
# ---------------------------------------------------------------------------

_retriever: Any | None = None
_planner: RetrievalPlanner | None = None
_coordinator: Any | None = None


def set_retriever(retriever: Any) -> None:
    """Inject the retrieval backend (called during app creation)."""
    global _retriever
    _retriever = retriever


def set_planner(planner: RetrievalPlanner) -> None:
    """Inject the retrieval planner (called during app creation)."""
    global _planner
    _planner = planner


def set_coordinator(coordinator: Any | None) -> None:
    """Inject the retrieval coordinator (called during app creation)."""
    global _coordinator
    _coordinator = coordinator


def _extract_timing(retriever: Any) -> dict[str, float]:
    """Extract timing_* keys from the retriever's last stats."""
    stats = getattr(retriever, "_last_retrieval_stats", {})
    if not isinstance(stats, dict):
        return {}
    return {k: v for k, v in stats.items() if k.startswith("timing_")}


def _was_reranked(requested: bool, retriever: Any) -> bool:
    """Return whether the latest retrieval actually completed reranking."""
    if not requested:
        return False
    stats = getattr(retriever, "_last_retrieval_stats", {})
    if not isinstance(stats, dict):
        return requested
    return not stats.get("reranker_fallback_used", False)


def _coordinated_was_reranked(
    requested: bool,
    result: CoordinatedRetrievalResult,
) -> bool:
    """Return whether all coordinated branches completed reranking."""
    if not requested or result.answer_mode == "clarification":
        return False
    return not any(
        group.processing.get("reranker_fallback_used", False)
        for group in result.groups
    )


def _ensure_retriever() -> Any:
    if _retriever is None:
        raise HTTPException(status_code=503, detail="Retrieval backend not initialized")
    return _retriever


def is_retriever_initialized() -> bool:
    """Return whether the retrieval backend has been injected."""
    return _retriever is not None


def _ensure_planner() -> RetrievalPlanner:
    if _planner is None:
        raise HTTPException(status_code=503, detail="Planner not initialized")
    return _planner


def _resolved_scopes(result: CoordinatedRetrievalResult) -> list[ResolvedScope]:
    return [
        ResolvedScope(
            vendor=group.scope.vendor,
            platform=group.scope.platform,
            software=group.scope.software,
            software_release=group.scope.software_release,
        )
        for group in result.groups
    ]


def _flatten_coordinated(result: CoordinatedRetrievalResult) -> list[tuple[Chunk, float]]:
    return [
        (chunk, score)
        for group in result.groups
        for chunk, score in group.chunks
    ]


def _chunk_to_result(chunk: Chunk, score: float = 0.0) -> ChunkResult:
    """Convert internal Chunk model to API ChunkResult."""
    return ChunkResult(
        id=chunk.id,
        content=chunk.content,
        score=score,
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
        tags=chunk.tags,
        ecosystem=chunk.ecosystem,
        software_version=chunk.software_version,
        doc_family=chunk.doc_family,
        heading_level=chunk.heading_level,
        start_line=chunk.start_line,
        end_line=chunk.end_line,
        parent_id=chunk.parent_id,
        sibling_ids=chunk.sibling_ids,
        child_ids=chunk.child_ids,
        images=chunk.images,
        tables=chunk.tables,
        code_blocks=chunk.code_blocks,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/search", response_model=SearchResponse)
async def search(request: SearchRequest) -> SearchResponse:
    """Semantic search over the ATE knowledge base."""
    timer = StepTimer()
    with timer.step("total"):
        if _coordinator is not None:
            result = await _coordinator.search(
                request.query,
                top_k=request.top_k,
                filters=request.filters or None,
            )
            chunks = [_chunk_to_result(chunk, score) for chunk, score in _flatten_coordinated(result)]
            return SearchResponse(
                query=request.query,
                chunks=chunks,
                total=len(chunks),
                answer_mode=result.answer_mode,
                resolved_scopes=_resolved_scopes(result),
                correction_notice=result.correction_notice,
                clarification_prompt=result.clarification_prompt,
                message=result.correction_notice or result.clarification_prompt,
                timing=timer.to_dict(),
            )

        retriever = _ensure_retriever()
        planner = _ensure_planner()

        plan = planner.plan(request.query)
        if plan.is_blocked:
            return SearchResponse(
                query=request.query, chunks=[], total=0, message=plan.block_reason or ""
            )
        if plan.is_ambiguous:
            return SearchResponse(
                query=request.query, chunks=[], total=0, message=plan.clarification_prompt or ""
            )

        filters = plan.inferred_filters or request.filters
        if request.filters and plan.inferred_filters:
            merged = dict(plan.inferred_filters)
            merged.update(request.filters)
            filters = merged

        results: list[tuple[Chunk, float]] = await retriever.search(
            query=plan.enhanced_query,
            top_k=request.top_k,
            filters=filters,
        )
        chunks = [_chunk_to_result(chunk, score) for chunk, score in results]
        pipeline_timing = _extract_timing(retriever)

    return SearchResponse(
        query=request.query,
        chunks=chunks,
        total=len(chunks),
        timing={**pipeline_timing, **timer.to_dict()},
    )


@router.post("/retrieve", response_model=RetrieveResponse)
async def retrieve(request: RetrieveRequest) -> RetrieveResponse:
    """Advanced retrieval with parent-child expansion, reranking, and compression."""
    timer = StepTimer()
    with timer.step("total"):
        if _coordinator is not None:
            result = await _coordinator.retrieve(
                request.query,
                top_k=request.top_k,
                filters=request.filters or None,
                expand_parents=request.expand_parents,
                expand_siblings=request.expand_siblings,
                rerank=request.rerank,
                compress=request.compress,
            )
            chunks = [_chunk_to_result(chunk, score) for chunk, score in _flatten_coordinated(result)]
            return RetrieveResponse(
                query=request.query,
                chunks=chunks,
                total=len(chunks),
                reranked=_coordinated_was_reranked(request.rerank, result),
                expanded=(request.expand_parents or request.expand_siblings)
                and result.answer_mode != "clarification",
                compressed=request.compress and result.answer_mode != "clarification",
                answer_mode=result.answer_mode,
                resolved_scopes=_resolved_scopes(result),
                correction_notice=result.correction_notice,
                clarification_prompt=result.clarification_prompt,
                message=result.correction_notice or result.clarification_prompt,
                timing=timer.to_dict(),
            )

        retriever = _ensure_retriever()
        planner = _ensure_planner()

        plan = planner.plan(request.query)
        if plan.is_blocked:
            return RetrieveResponse(
                query=request.query,
                chunks=[],
                total=0,
                reranked=False,
                expanded=False,
                compressed=False,
                message=plan.block_reason or "",
            )
        if plan.is_ambiguous:
            return RetrieveResponse(
                query=request.query,
                chunks=[],
                total=0,
                reranked=False,
                expanded=False,
                compressed=False,
                message=plan.clarification_prompt or "",
            )

        filters = plan.inferred_filters or request.filters
        if request.filters and plan.inferred_filters:
            merged = dict(plan.inferred_filters)
            merged.update(request.filters)
            filters = merged

        results: list[tuple[Chunk, float]] = await retriever.retrieve(
            query=plan.enhanced_query,
            top_k=request.top_k,
            filters=filters,
            expand_parents=request.expand_parents,
            expand_siblings=request.expand_siblings,
            rerank=request.rerank,
            compress=request.compress,
        )
        chunks = [_chunk_to_result(chunk, score) for chunk, score in results]
        pipeline_timing = _extract_timing(retriever)
        was_reranked = _was_reranked(request.rerank, retriever)

    return RetrieveResponse(
        query=request.query,
        chunks=chunks,
        total=len(chunks),
        reranked=was_reranked,
        expanded=request.expand_parents or request.expand_siblings,
        compressed=request.compress,
        timing={**pipeline_timing, **timer.to_dict()},
    )


@router.post("/ask", response_model=AskResponse)
async def ask(request: AskRequest) -> AskResponse:
    """Agent-friendly Q&A endpoint with citations and source tracking."""
    timer = StepTimer()
    with timer.step("total"):
        if _coordinator is not None:
            result = await _coordinator.retrieve(
                request.question,
                top_k=request.top_k,
                filters=request.filters or None,
                expand_parents=True,
                expand_siblings=True,
                rerank=True,
                compress=True,
            )
            chunks = [_chunk_to_result(chunk, score) for chunk, score in _flatten_coordinated(result)]
            citations = [
                Citation(
                    chunk_id=chunk.id,
                    excerpt=chunk.content[:300],
                    source_md=chunk.source_md,
                    toc_path=chunk.toc_path,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                )
                for chunk in chunks
            ]
            toc_paths = sorted({tuple(c.toc_path) for c in chunks if c.toc_path})
            source_files = sorted({c.source_md for c in chunks if c.source_md})
            return AskResponse(
                question=request.question,
                chunks=chunks,
                citations=citations,
                toc_paths=[list(tp) for tp in toc_paths],
                source_files=list(source_files),
                answer_mode=result.answer_mode,
                resolved_scopes=_resolved_scopes(result),
                correction_notice=result.correction_notice,
                clarification_prompt=result.clarification_prompt,
                message=result.correction_notice or result.clarification_prompt,
                timing=timer.to_dict(),
            )

        retriever = _ensure_retriever()
        planner = _ensure_planner()

        plan = planner.plan(request.question)
        if plan.is_blocked:
            return AskResponse(
                question=request.question,
                chunks=[],
                citations=[],
                toc_paths=[],
                source_files=[],
                message=plan.block_reason or "",
            )
        if plan.is_ambiguous:
            return AskResponse(
                question=request.question,
                chunks=[],
                citations=[],
                toc_paths=[],
                source_files=[],
                message=plan.clarification_prompt or "",
            )

        filters = plan.inferred_filters or request.filters
        if request.filters and plan.inferred_filters:
            merged = dict(plan.inferred_filters)
            merged.update(request.filters)
            filters = merged

        results: list[tuple[Chunk, float]] = await retriever.search(
            query=plan.enhanced_query,
            top_k=request.top_k,
            filters=filters,
        )

        chunks = [_chunk_to_result(chunk, score) for chunk, score in results]

        citations = [
            Citation(
                chunk_id=chunk.id,
                excerpt=chunk.content[:300],
                source_md=chunk.source_md,
                toc_path=chunk.toc_path,
                start_line=chunk.start_line,
                end_line=chunk.end_line,
            )
            for chunk in chunks
        ]

        toc_paths = sorted({tuple(c.toc_path) for c in chunks if c.toc_path})
        source_files = sorted({c.source_md for c in chunks if c.source_md})
        pipeline_timing = _extract_timing(retriever)

    return AskResponse(
        question=request.question,
        chunks=chunks,
        citations=citations,
        toc_paths=[list(tp) for tp in toc_paths],
        source_files=list(source_files),
        timing={**pipeline_timing, **timer.to_dict()},
    )


@router.post("/related", response_model=RelatedResponse)
async def related(request: RelatedRequest) -> RelatedResponse:
    """Find related chunks (parent, siblings, children) for a given chunk."""
    retriever = _ensure_retriever()
    relations = await retriever.get_related(request.chunk_id)

    parent = None
    if relations.get("parent"):
        parent = _chunk_to_result(relations["parent"], score=1.0)

    siblings = [
        _chunk_to_result(chunk, score=1.0)
        for chunk in relations.get("siblings", [])
    ]
    children = [
        _chunk_to_result(chunk, score=1.0)
        for chunk in relations.get("children", [])
    ]

    return RelatedResponse(
        chunk_id=request.chunk_id,
        parent=parent,
        siblings=siblings,
        children=children,
    )


@router.get("/document/{source_md:path}", response_model=DocumentResponse)
async def get_document(
    source_md: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> DocumentResponse:
    """Return one page of chunks for a given markdown source file."""
    retriever = _ensure_retriever()
    page = await retriever.get_document_page(source_md, limit=limit, offset=offset)
    chunks: list[Chunk] = page["chunks"]
    results = [_chunk_to_result(chunk, score=1.0) for chunk in chunks]
    return DocumentResponse(
        source_md=source_md,
        chunks=results,
        total=page["total"],
        returned=page["returned"],
        offset=offset,
        limit=limit,
        has_more=page["has_more"],
        next_offset=page["next_offset"],
    )
