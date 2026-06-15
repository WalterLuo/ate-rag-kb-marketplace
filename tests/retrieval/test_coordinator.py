"""Tests for unified retrieval coordinator."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from ate_rag_kb.domain.scopes import (
    ADVANTEST_V93000_SMT7,
    ADVANTEST_V93000_SMT8,
    TERADYNE_J750_IGXL,
)
from ate_rag_kb.ingestion.symbol_catalog import SymbolCatalog
from ate_rag_kb.retrieval.coordinator import RetrievalCoordinator
from ate_rag_kb.retrieval.pipeline import ScopedPipelineResult
from ate_rag_kb.retrieval.planner import RetrievalPlanner
from ate_rag_kb.retrieval.routing import ScopeRouter
from ate_rag_kb.utils.config import Config


@pytest.fixture
def pipeline() -> MagicMock:
    pipe = MagicMock()

    async def retrieve_scope(**kwargs):
        scope = kwargs["scope"]
        return ScopedPipelineResult(chunks=[], processing={"scope": scope.key})

    pipe.retrieve_scope = AsyncMock(side_effect=retrieve_scope)
    pipe.search_scope = AsyncMock(side_effect=retrieve_scope)
    return pipe


@pytest.fixture
def coordinator(pipeline: MagicMock) -> RetrievalCoordinator:
    router = ScopeRouter(
        enabled_scopes=(TERADYNE_J750_IGXL, ADVANTEST_V93000_SMT7),
        symbol_catalog=SymbolCatalog.empty(),
    )
    return RetrievalCoordinator(router, RetrievalPlanner(Config({})), pipeline)


@pytest.fixture
def coordinator_with_smt8(pipeline: MagicMock) -> RetrievalCoordinator:
    router = ScopeRouter(
        enabled_scopes=(
            TERADYNE_J750_IGXL,
            ADVANTEST_V93000_SMT7,
            ADVANTEST_V93000_SMT8,
        ),
        symbol_catalog=SymbolCatalog.empty(),
    )
    return RetrievalCoordinator(router, RetrievalPlanner(Config({})), pipeline)


@pytest.mark.asyncio
async def test_coordinator_executes_one_branch_per_resolved_scope(
    coordinator: RetrievalCoordinator,
    pipeline: MagicMock,
) -> None:
    result = await coordinator.retrieve("多 site 串行处理怎么实现？", top_k=8)

    assert [group.scope.key for group in result.groups] == ["j750/igxl", "v93000/smt7"]
    assert pipeline.retrieve_scope.call_count == 2


@pytest.mark.asyncio
async def test_clarification_route_skips_retrieval(
    coordinator_with_smt8: RetrievalCoordinator,
    pipeline: MagicMock,
) -> None:
    result = await coordinator_with_smt8.retrieve("V93000 site control 怎么用？", top_k=8)

    assert result.answer_mode == "clarification"
    assert "SMT7" in result.clarification_prompt
    assert "SMT8" in result.clarification_prompt
    pipeline.retrieve_scope.assert_not_called()
