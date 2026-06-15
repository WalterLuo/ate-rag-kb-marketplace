"""Tests for multi-platform retrieval validation helpers."""

from __future__ import annotations

import json
from pathlib import Path

from ate_rag_kb.domain.scopes import ADVANTEST_V93000_SMT7
from ate_rag_kb.ingestion.symbol_catalog import SymbolCatalog, SymbolOwner
from scripts.validate_multi_platform_retrieval import (
    validate_document_graph,
    validate_symbol_catalog,
)


def test_validation_fails_when_selectfirst_owner_is_missing(tmp_path: Path) -> None:
    path = tmp_path / "symbol_catalog.json"
    SymbolCatalog(
        {
            "on_first_invocation_begin": SymbolOwner(
                "ON_FIRST_INVOCATION_BEGIN",
                ADVANTEST_V93000_SMT7,
                ("v93000/smt7/site-control.md",),
            )
        }
    ).save(path)

    result = validate_symbol_catalog(path)

    assert result.errors == ["symbol catalog missing owner: SelectFirst -> j750/igxl"]


def test_validation_fails_when_igxl_graph_edge_is_missing(tmp_path: Path) -> None:
    path = tmp_path / "document_graph.json"
    path.write_text(
        json.dumps(
            {
                "igxl/vbt/execSites.39.44.md": {
                    "linked_source_mds": ["igxl/vbt/execSites.39.45.md"]
                }
            }
        ),
        encoding="utf-8",
    )

    result = validate_document_graph(path)

    assert result.errors == [
        "document graph missing edge: igxl/vbt/execSites.39.08.md -> igxl/vbt/execSites.39.09.md"
    ]
