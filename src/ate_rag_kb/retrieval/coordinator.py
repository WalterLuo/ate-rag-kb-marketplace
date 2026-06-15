"""Unified retrieval coordinator for scoped search and retrieve flows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ate_rag_kb.chunking.models import Chunk
from ate_rag_kb.domain.scopes import RetrievalScope, configured_scopes
from ate_rag_kb.ingestion.symbol_catalog import SymbolCatalog
from ate_rag_kb.retrieval.pipeline import RetrievalPipeline
from ate_rag_kb.retrieval.planner import RetrievalPlanner
from ate_rag_kb.retrieval.routing import AnswerMode, ScopeRouter
from ate_rag_kb.utils.config import Config


@dataclass(slots=True)
class ScopedRetrievalResult:
    scope: RetrievalScope
    chunks: list[tuple[Chunk, float]]
    processing: dict[str, Any]


@dataclass(slots=True)
class CoordinatedRetrievalResult:
    answer_mode: AnswerMode
    groups: list[ScopedRetrievalResult]
    correction_notice: str = ""
    clarification_prompt: str = ""

    @property
    def processing_by_scope(self) -> dict[str, dict[str, Any]]:
        return {group.scope.key: group.processing for group in self.groups}

    @property
    def cross_scope_dropped_chunk_count(self) -> int:
        return sum(
            group.processing.get("cross_scope_dropped_chunk_count", 0)
            for group in self.groups
        )


class RetrievalCoordinator:
    def __init__(
        self,
        router: ScopeRouter,
        planner: RetrievalPlanner,
        pipeline: RetrievalPipeline,
    ) -> None:
        self.router = router
        self.planner = planner
        self.pipeline = pipeline

    async def search(
        self,
        query: str,
        *,
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> CoordinatedRetrievalResult:
        return await self._execute(query, top_k=top_k, operation="search", filters=filters)

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int,
        filters: dict[str, Any] | None = None,
        rerank: bool = True,
        expand_parents: bool = True,
        expand_siblings: bool = True,
        compress: bool = True,
    ) -> CoordinatedRetrievalResult:
        return await self._execute(
            query,
            top_k=top_k,
            operation="retrieve",
            filters=filters,
            rerank=rerank,
            expand_parents=expand_parents,
            expand_siblings=expand_siblings,
            compress=compress,
        )

    async def _execute(
        self,
        query: str,
        *,
        top_k: int,
        operation: Literal["search", "retrieve"],
        filters: dict[str, Any] | None = None,
        rerank: bool = True,
        expand_parents: bool = True,
        expand_siblings: bool = True,
        compress: bool = True,
    ) -> CoordinatedRetrievalResult:
        route = self.router.route(query)
        if route.answer_mode == "clarification":
            return CoordinatedRetrievalResult(
                answer_mode=route.answer_mode,
                groups=[],
                correction_notice=route.correction_notice,
                clarification_prompt=route.clarification_prompt,
            )

        groups: list[ScopedRetrievalResult] = []
        for scope in route.scopes:
            plan = self.planner.plan(query, scope=scope)
            if operation == "search":
                branch = await self.pipeline.search_scope(
                    query=query,
                    plan=plan,
                    scope=scope,
                    top_k=top_k,
                    user_filters=filters,
                )
            else:
                branch = await self.pipeline.retrieve_scope(
                    query=query,
                    plan=plan,
                    scope=scope,
                    top_k=top_k,
                    user_filters=filters,
                    rerank=rerank,
                    expand_parents=expand_parents,
                    expand_siblings=expand_siblings,
                    compress=compress,
                )
            groups.append(
                ScopedRetrievalResult(
                    scope=scope,
                    chunks=branch.chunks,
                    processing=branch.processing,
                )
            )

        return CoordinatedRetrievalResult(
            answer_mode=route.answer_mode,
            groups=groups,
            correction_notice=route.correction_notice,
        )


def build_retrieval_coordinator(
    config: Config,
    pipeline: RetrievalPipeline | None = None,
) -> RetrievalCoordinator:
    active_pipeline = pipeline or RetrievalPipeline(config)
    processed_dir = Path(config.get("data.processed_dir", "./data/processed"))
    catalog = SymbolCatalog.load_if_exists(processed_dir / "symbol_catalog.json")
    router = ScopeRouter(configured_scopes(config), catalog)
    return RetrievalCoordinator(router, RetrievalPlanner(config), active_pipeline)
