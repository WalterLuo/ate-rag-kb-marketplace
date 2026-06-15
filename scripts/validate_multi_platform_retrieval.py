"""Validate multi-platform retrieval artifacts and runtime behavior."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from ate_rag_kb.domain.scopes import ADVANTEST_V93000_SMT7, TERADYNE_J750_IGXL
from ate_rag_kb.ingestion.symbol_catalog import SymbolCatalog
from ate_rag_kb.retrieval.coordinator import build_retrieval_coordinator
from ate_rag_kb.utils.config import Config, get_config


@dataclass(slots=True)
class ValidationResult:
    errors: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_symbol_catalog(path: Path) -> ValidationResult:
    if not path.exists():
        return ValidationResult([f"symbol catalog missing: {path}"])

    catalog = SymbolCatalog.load(path)
    errors: list[str] = []
    expected = {
        "SelectFirst": "j750/igxl",
        "ON_FIRST_INVOCATION_BEGIN": "v93000/smt7",
    }
    for symbol, scope_key in expected.items():
        scope = catalog.owner_for(symbol)
        if scope is None or scope.key != scope_key:
            errors.append(f"symbol catalog missing owner: {symbol} -> {scope_key}")
    return ValidationResult(errors)


def validate_document_graph(path: Path) -> ValidationResult:
    if not path.exists():
        return ValidationResult([f"document graph missing: {path}"])

    graph = json.loads(path.read_text(encoding="utf-8"))
    expected_edges = (
        ("igxl/vbt/execSites.39.08.md", "igxl/vbt/execSites.39.09.md"),
        ("igxl/vbt/execSites.39.44.md", "igxl/vbt/execSites.39.45.md"),
    )
    errors = [
        f"document graph missing edge: {source} -> {target}"
        for source, target in expected_edges
        if target not in graph.get(source, {}).get("linked_source_mds", [])
    ]
    return ValidationResult(errors)


def load_cases() -> list[dict]:
    fixture_path = (
        Path(__file__).resolve().parents[1]
        / "tests"
        / "fixtures"
        / "multi_platform_acceptance.yaml"
    )
    return yaml.safe_load(fixture_path.read_text(encoding="utf-8"))["cases"]


async def validate_runtime(config: Config) -> ValidationResult:
    coordinator = build_retrieval_coordinator(config)
    pipeline = coordinator.pipeline
    errors: list[str] = []

    counts = {
        "j750/igxl": pipeline.vector_store.count(TERADYNE_J750_IGXL.to_filters()),
        "v93000/smt7": pipeline.vector_store.count(ADVANTEST_V93000_SMT7.to_filters()),
    }
    for scope_key, count in counts.items():
        if count == 0:
            errors.append(f"collection missing scoped chunks: {scope_key}")

    processed_dir = Path(config.get("data.processed_dir", "./data/processed"))
    vocab_path = processed_dir / "sparse_vocab.json"
    vocab = json.loads(vocab_path.read_text(encoding="utf-8")) if vocab_path.exists() else {}
    if vocab.get("vocab_size", 0) == 0:
        errors.append("sparse vocabulary missing or empty")

    for case in load_cases():
        result = await coordinator.retrieve(case["query"], top_k=8)
        if result.answer_mode != case["answer_mode"]:
            errors.append(f"{case['id']}: unexpected answer mode {result.answer_mode}")
        if [group.scope.key for group in result.groups] != case["scopes"]:
            errors.append(f"{case['id']}: unexpected resolved scopes")
        if case.get("correction_required") and not result.correction_notice:
            errors.append(f"{case['id']}: missing correction notice")
        for group in result.groups:
            if not group.processing.get("sparse_search_used", False):
                errors.append(f"{case['id']}: sparse search inactive for {group.scope.key}")
            if group.processing.get("sparse_candidate_count", 0) == 0:
                errors.append(
                    f"{case['id']}: sparse search returned no candidates for {group.scope.key}"
                )

    return ValidationResult(errors)


def main() -> int:
    config = get_config()
    processed_dir = Path(config.get("data.processed_dir", "./data/processed"))
    results = [
        validate_document_graph(processed_dir / "document_graph.json"),
        validate_symbol_catalog(processed_dir / "symbol_catalog.json"),
        asyncio.run(validate_runtime(config)),
    ]
    errors = [error for result in results for error in result.errors]
    for error in errors:
        print(f"FAIL {error}")
    if errors:
        return 1
    print("PASS multi-platform retrieval artifacts and runtime")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
