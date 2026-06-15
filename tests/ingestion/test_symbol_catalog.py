"""Tests for symbol ownership catalog generation."""

from __future__ import annotations

from pathlib import Path

from ate_rag_kb.domain.scopes import ADVANTEST_V93000_SMT7, TERADYNE_J750_IGXL
from ate_rag_kb.ingestion.symbol_catalog import SymbolCatalog, SymbolCatalogBuilder


def write_md(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_catalog_records_exclusive_symbol_owners(tmp_path: Path) -> None:
    write_md(tmp_path, "igxl/vbt/execSites.39.08.md", "# SelectFirst Method")
    write_md(tmp_path, "v93000/smt7/100096.md", "# ON_FIRST_INVOCATION_BEGIN")

    catalog = SymbolCatalogBuilder(tmp_path).build()

    assert catalog.owner_for("SelectFirst") == TERADYNE_J750_IGXL
    assert catalog.owner_for("ON_FIRST_INVOCATION_BEGIN") == ADVANTEST_V93000_SMT7


def test_catalog_does_not_claim_shared_symbol(tmp_path: Path) -> None:
    write_md(tmp_path, "igxl/vbt/shared.md", "# Execute")
    write_md(tmp_path, "v93000/smt7/shared.md", "# Execute")

    catalog = SymbolCatalogBuilder(tmp_path).build()

    assert catalog.owner_for("Execute") is None


def test_catalog_finds_single_owner_in_query(tmp_path: Path) -> None:
    write_md(tmp_path, "igxl/vbt/execSites.39.08.md", "# SelectFirst Method")
    write_md(tmp_path, "v93000/smt7/100096.md", "# ON_FIRST_INVOCATION_BEGIN")

    catalog = SymbolCatalogBuilder(tmp_path).build()
    owner = catalog.find_owner_in_query("How do I use SelectFirst and SelectNext?")

    assert owner is not None
    assert owner.scope == TERADYNE_J750_IGXL
    assert owner.source_mds == ("igxl/vbt/execSites.39.08.md",)


def test_catalog_save_and_load_round_trip(tmp_path: Path) -> None:
    write_md(tmp_path, "igxl/vbt/execSites.39.08.md", "# SelectFirst Method")
    catalog = SymbolCatalogBuilder(tmp_path).build()
    path = tmp_path / "processed" / "symbol_catalog.json"

    catalog.save(path)
    loaded = SymbolCatalog.load(path)

    assert loaded.owner_for("selectfirst") == TERADYNE_J750_IGXL
