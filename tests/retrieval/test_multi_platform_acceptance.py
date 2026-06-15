"""Deterministic multi-platform coordinator acceptance matrix."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from ate_rag_kb.chunking.models import Chunk, ChunkType
from ate_rag_kb.domain.scopes import ADVANTEST_V93000_SMT7, TERADYNE_J750_IGXL
from ate_rag_kb.ingestion.symbol_catalog import SymbolCatalog, SymbolOwner
from ate_rag_kb.retrieval.coordinator import RetrievalCoordinator
from ate_rag_kb.retrieval.pipeline import ScopedPipelineResult
from ate_rag_kb.retrieval.planner import RetrievalPlanner
from ate_rag_kb.retrieval.routing import ScopeRouter
from ate_rag_kb.utils.config import Config


def load_cases() -> list[dict]:
    fixture_path = Path(__file__).parents[1] / "fixtures" / "multi_platform_acceptance.yaml"
    return yaml.safe_load(fixture_path.read_text(encoding="utf-8"))["cases"]


@pytest.fixture
def coordinator() -> RetrievalCoordinator:
    pipeline = MagicMock()

    async def retrieve_scope(**kwargs):
        scope = kwargs["scope"]
        if scope == TERADYNE_J750_IGXL:
            content = "IG-XL serial site loop uses SelectFirst, SelectNext, and loopDone."
        else:
            content = "SMT7 Site Control uses ON_FIRST_INVOCATION_BEGIN for per-site setup."
        chunk = Chunk(
            id=scope.key.replace("/", "-"),
            content=content,
            chunk_type=ChunkType.PARAGRAPH,
            source_md=f"{scope.platform}/{scope.software}/doc.md",
            vendor=scope.vendor,
            platform=scope.platform,
            software=scope.software,
        )
        return ScopedPipelineResult(chunks=[(chunk, 0.9)], processing={})

    pipeline.retrieve_scope = AsyncMock(side_effect=retrieve_scope)
    catalog = SymbolCatalog(
        {
            "selectfirst": SymbolOwner(
                "SelectFirst",
                TERADYNE_J750_IGXL,
                ("igxl/vbt/execSites.39.08.md",),
            ),
            "on_first_invocation_begin": SymbolOwner(
                "ON_FIRST_INVOCATION_BEGIN",
                ADVANTEST_V93000_SMT7,
                ("v93000/smt7/site-control.md",),
            ),
        }
    )
    router = ScopeRouter(
        enabled_scopes=(TERADYNE_J750_IGXL, ADVANTEST_V93000_SMT7),
        symbol_catalog=catalog,
    )
    return RetrievalCoordinator(router, RetrievalPlanner(Config({})), pipeline)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", load_cases())
async def test_multi_platform_acceptance(
    case: dict,
    coordinator: RetrievalCoordinator,
) -> None:
    result = await coordinator.retrieve(case["query"], top_k=8)

    assert result.answer_mode == case["answer_mode"]
    assert [group.scope.key for group in result.groups] == case["scopes"]
    if case.get("correction_required"):
        assert result.correction_notice

    text = "\n".join(
        chunk.content
        for group in result.groups
        for chunk, _score in group.chunks
    )
    for term in case.get("required_terms", []):
        assert term in text
    for term in case.get("forbidden_terms", []):
        assert term not in text
