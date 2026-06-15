# Metadata And Graph Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Normalize platform metadata, repair IG-XL Markdown relationships, and generate a symbol ownership catalog that later routing can trust.

**Architecture:** Add one shared domain scope model consumed by ingestion and retrieval. Store canonical metadata alongside legacy compatibility fields during migration. Extend graph construction for relative `.md` links and generate symbol ownership from indexed source documents rather than runtime source hints.

**Tech Stack:** Python dataclasses, pathlib, JSON, regex, Qdrant payload indexes, pytest

---

## File Responsibility Map

| File | Responsibility |
|---|---|
| `src/ate_rag_kb/domain/scopes.py` | Canonical vendor, platform, and software identities plus configuration parsing |
| `src/ate_rag_kb/chunking/models.py` | Chunk payload serialization |
| `src/ate_rag_kb/vector_store/schema.py` | Qdrant payload index creation |
| `configs/config.yaml` | Enabled scopes and schema version |
| `src/ate_rag_kb/ingestion/pipeline.py` | Scope detection, chunk metadata, artifact rebuild lifecycle |
| `src/ate_rag_kb/utils/scope.py` | Ingestion inclusion filter using canonical scopes |
| `src/ate_rag_kb/ingestion/document_graph.py` | Internal link parsing and graph resolution |
| `src/ate_rag_kb/ingestion/symbol_catalog.py` | Generated exclusive-symbol ownership artifact |

## Task 1: Add Canonical Scope Model

**Files:**
- Create: `src/ate_rag_kb/domain/__init__.py`
- Create: `src/ate_rag_kb/domain/scopes.py`
- Test: `tests/domain/test_scopes.py`

- [ ] Write the failing tests:

```python
from ate_rag_kb.domain.scopes import (
    ADVANTEST_V93000_SMT7,
    TERADYNE_J750_IGXL,
    configured_scopes,
    infer_scope_from_source,
)
from ate_rag_kb.utils.config import Config


def test_scope_filters_use_canonical_fields() -> None:
    assert TERADYNE_J750_IGXL.to_filters() == {
        "vendor": "teradyne",
        "platform": "j750",
        "software": "igxl",
    }


def test_v93000_scope_filters_include_platform_common_docs() -> None:
    assert ADVANTEST_V93000_SMT7.to_filters() == {
        "vendor": "advantest",
        "platform": "v93000",
        "software": ["smt7", ""],
    }


def test_enabled_scopes_are_loaded_from_config() -> None:
    config = Config({
        "documents": {
            "enabled_scopes": [
                {"vendor": "teradyne", "platform": "j750", "software": "igxl"},
                {"vendor": "advantest", "platform": "v93000", "software": "smt7"},
            ]
        }
    })
    assert configured_scopes(config) == (
        TERADYNE_J750_IGXL,
        ADVANTEST_V93000_SMT7,
    )


def test_source_path_infers_igxl_scope() -> None:
    assert infer_scope_from_source("igxl/vbt/execSites.39.08.md") == TERADYNE_J750_IGXL


def test_source_path_infers_smt7_scope() -> None:
    assert infer_scope_from_source("v93000/smt7/100096.md") == ADVANTEST_V93000_SMT7
```

- [ ] Run:

```bash
uv run pytest tests/domain/test_scopes.py -q
```

Expected: fail because `ate_rag_kb.domain.scopes` does not exist.

- [ ] Create the scope module with this public API:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from ate_rag_kb.utils.config import Config


@dataclass(frozen=True, slots=True)
class RetrievalScope:
    vendor: str
    platform: str
    software: str
    software_release: str = ""

    @property
    def key(self) -> str:
        return f"{self.platform}/{self.software}"

    def to_filters(self) -> dict[str, str | list[str]]:
        software_filter: str | list[str] = self.software
        if self.platform == "v93000" and self.software:
            software_filter = [self.software, ""]
        filters: dict[str, str | list[str]] = {
            "vendor": self.vendor,
            "platform": self.platform,
            "software": software_filter,
        }
        if self.software_release:
            filters["software_release"] = self.software_release
        return filters

    def matches_document(self, vendor: str, platform: str, software: str) -> bool:
        if vendor != self.vendor or platform != self.platform:
            return False
        return software == self.software or (
            self.platform == "v93000" and software == ""
        )


TERADYNE_J750_IGXL = RetrievalScope("teradyne", "j750", "igxl")
ADVANTEST_V93000_SMT7 = RetrievalScope("advantest", "v93000", "smt7")
ADVANTEST_V93000_SMT8 = RetrievalScope("advantest", "v93000", "smt8")


def configured_scopes(config: Config) -> tuple[RetrievalScope, ...]:
    raw_scopes = config.get("documents.enabled_scopes", ())
    if raw_scopes:
        return tuple(RetrievalScope(**raw_scope) for raw_scope in raw_scopes)

    scopes: list[RetrievalScope] = []
    if config.get("documents.igxl.enabled", False):
        scopes.append(TERADYNE_J750_IGXL)
    enabled_versions = config.get("documents.v93000.enabled_software_versions", ())
    if "smt7" in enabled_versions:
        scopes.append(ADVANTEST_V93000_SMT7)
    if "smt8" in enabled_versions:
        scopes.append(ADVANTEST_V93000_SMT8)
    return tuple(scopes)


def infer_scope_from_source(source_md: str) -> RetrievalScope | None:
    parts = {part.lower() for part in PurePosixPath(source_md).parts}
    if "igxl" in parts:
        return TERADYNE_J750_IGXL
    if "smt7" in parts:
        return ADVANTEST_V93000_SMT7
    if "smt8" in parts:
        return ADVANTEST_V93000_SMT8
    if "v93000" in parts or "tdc" in parts:
        return RetrievalScope("advantest", "v93000", "")
    return None
```

- [ ] Export the public names from `src/ate_rag_kb/domain/__init__.py`.
- [ ] Run:

```bash
uv run pytest tests/domain/test_scopes.py -q
```

Expected: pass.

- [ ] Commit:

```bash
git add src/ate_rag_kb/domain tests/domain
git commit -m "feat: add canonical retrieval scopes"
```

## Task 2: Store Canonical Metadata In Chunk Payloads

**Files:**
- Modify: `src/ate_rag_kb/chunking/models.py`
- Modify: `src/ate_rag_kb/vector_store/schema.py`
- Modify: `src/ate_rag_kb/ingestion/incremental.py`
- Modify: `configs/config.yaml`
- Test: `tests/test_chunking_models.py`
- Test: `tests/vector_store/test_schema.py`
- Test: `tests/test_ingestion_incremental.py`

- [ ] Extend existing payload round-trip tests to assert:

```python
assert payload["vendor"] == "teradyne"
assert payload["platform"] == "j750"
assert payload["software"] == "igxl"
assert payload["software_release"] == ""
assert Chunk.from_payload(payload).software == "igxl"
```

- [ ] Extend schema tests so the expected indexed fields include:

```python
{"vendor", "platform", "software", "software_release"}
```

- [ ] Run:

```bash
uv run pytest tests/test_chunking_models.py tests/vector_store/test_schema.py tests/test_ingestion_incremental.py -q
```

Expected: fail because the new payload fields and indexes are absent.

- [ ] Add canonical fields to `Chunk` while retaining migration compatibility fields:

```python
vendor: str = ""
platform: str = ""
software: str = ""
software_release: str = ""
ecosystem: str = ""
software_version: str = ""
doc_family: str = ""
release_version: str = ""
```

- [ ] Add `vendor`, `software`, and `software_release` to `to_payload()` and `from_payload()`.
- [ ] Add canonical indexes to the default `create_payload_indexes()` mapping in `src/ate_rag_kb/vector_store/schema.py`.
- [ ] Change `DEFAULT_SCHEMA_VERSION` from `5` to `6` in `src/ate_rag_kb/ingestion/incremental.py`.
- [ ] Insert these payload mappings in `Chunk.to_payload()` and `Chunk.from_payload()`:

```python
# to_payload()
"vendor": self.vendor,
"platform": self.platform,
"software": self.software,
"software_release": self.software_release,

# from_payload()
vendor=payload.get("vendor", ""),
platform=payload.get("platform", ""),
software=payload.get("software", ""),
software_release=payload.get("software_release", ""),
```

- [ ] Extend the default payload-index mapping:

```python
fields = {
    "vendor": "keyword",
    "platform": "keyword",
    "software": "keyword",
    "software_release": "keyword",
    "doc_type": "keyword",
    "chunk_type": "keyword",
    "source_md": "text",
    "doc_title": "text",
}
```

- [ ] In `configs/config.yaml`, change `ingestion.schema_version` from `5` to `6` and ensure `schema.payload_indexes` contains:

```yaml
- field: "vendor"
  type: "keyword"
- field: "platform"
  type: "keyword"
- field: "software"
  type: "keyword"
- field: "software_release"
  type: "keyword"
```

- [ ] Run:

```bash
uv run pytest tests/test_chunking_models.py tests/vector_store/test_schema.py tests/test_ingestion_incremental.py -q
```

Expected: pass.

- [ ] Commit:

```bash
git add src/ate_rag_kb/chunking/models.py src/ate_rag_kb/vector_store/schema.py src/ate_rag_kb/ingestion/incremental.py configs/config.yaml tests/test_chunking_models.py tests/vector_store/test_schema.py tests/test_ingestion_incremental.py
git commit -m "feat: store canonical ATE metadata"
```

## Task 3: Normalize Metadata During Ingestion

**Files:**
- Modify: `src/ate_rag_kb/ingestion/pipeline.py`
- Modify: `src/ate_rag_kb/utils/scope.py`
- Test: `tests/test_ingestion_pipeline.py`
- Test: `tests/test_ingestion_pipeline_docs.py`
- Test: `tests/test_ingestion_incremental.py`
- Test: `tests/test_document_scope.py`

- [ ] Add ingestion tests for IG-XL and SMT7 documents:

```python
def test_igxl_chunks_use_j750_igxl_scope(pipeline) -> None:
    chunks = pipeline._chunk_document(Path("igxl/vbt/execSites.39.08.md"))
    assert {(chunk.vendor, chunk.platform, chunk.software) for chunk in chunks} == {
        ("teradyne", "j750", "igxl")
    }


def test_smt7_chunks_use_v93000_smt7_scope(pipeline) -> None:
    chunks = pipeline._chunk_document(Path("v93000/smt7/100096.md"))
    assert {(chunk.vendor, chunk.platform, chunk.software) for chunk in chunks} == {
        ("advantest", "v93000", "smt7")
    }
```

- [ ] Run:

```bash
uv run pytest tests/test_ingestion_pipeline.py tests/test_ingestion_pipeline_docs.py tests/test_ingestion_incremental.py tests/test_document_scope.py -q
```

Expected: fail because SMT7 is still represented as a platform in part of the ingestion path and canonical fields are not assigned.

- [ ] Keep the existing ecosystem and software-version detectors because root-level SMT7 files may require title or TOC metadata. Add one canonical scope wrapper:

```python
def _detect_scope(
    self,
    source_md: str,
    doc_title: str,
    metadata: dict[str, Any],
) -> RetrievalScope | None:
    ecosystem = self._detect_ecosystem(source_md, doc_title, metadata)
    software = self._detect_software_version(source_md, doc_title, metadata)
    if ecosystem == "igxl":
        return TERADYNE_J750_IGXL
    if ecosystem == "v93000":
        return RetrievalScope("advantest", "v93000", software)
    return None
```

- [ ] Write canonical fields from the wrapper and preserve compatibility payloads during migration:

```python
scope = self._detect_scope(source_md, metadata.get("doc_title", ""), metadata)
vendor = scope.vendor if scope else ""
platform = scope.platform if scope else ""
software = scope.software if scope else ""
software_release = scope.software_release if scope else ""
ecosystem = "igxl" if software == "igxl" else "v93000" if platform == "v93000" else ""
software_version = software if software in {"smt7", "smt8"} else ""
```

- [ ] Change `_detect_platform()` so `smt7` and `smt8` documents report tester platform `V93000`, then update the existing platform-detection assertions.
- [ ] Update `DocumentScope` inclusion checks to compare configured canonical scopes. Keep the existing legacy configuration parser as a compatibility fallback by calling `configured_scopes(config)`:

```python
def should_ingest_scope(self, path: Path, scope: RetrievalScope | None) -> bool:
    if scope is None:
        logger.debug("Skipping %s: no canonical document scope", path)
        return False
    enabled = configured_scopes(self.config)
    if not enabled:
        return True
    return any(
        candidate.matches_document(scope.vendor, scope.platform, scope.software)
        for candidate in enabled
    )
```

- [ ] Call `should_ingest_scope(md_path, scope)` from `_chunk_document()` after canonical metadata is populated.
- [ ] Preserve platform-level V93000 common documentation with `vendor="advantest"`, `platform="v93000"`, and `software=""`. A V93000 software branch may include these common documents with a scoped filter such as `software=["smt7", ""]`; vendor and platform filters remain mandatory.
- [ ] Add canonical enabled scopes to `configs/config.yaml`:

```yaml
documents:
  enabled_scopes:
    - vendor: teradyne
      platform: j750
      software: igxl
    - vendor: advantest
      platform: v93000
      software: smt7
```

- [ ] Run:

```bash
uv run pytest tests/test_ingestion_pipeline.py tests/test_ingestion_pipeline_docs.py tests/test_ingestion_incremental.py tests/test_document_scope.py -q
```

Expected: pass.

- [ ] Commit:

```bash
git add src/ate_rag_kb/ingestion/pipeline.py src/ate_rag_kb/utils/scope.py configs/config.yaml tests/test_ingestion_pipeline.py tests/test_ingestion_pipeline_docs.py tests/test_ingestion_incremental.py tests/test_document_scope.py
git commit -m "feat: normalize ingestion document scopes"
```

## Task 4: Resolve IG-XL Relative Markdown Links

**Files:**
- Modify: `src/ate_rag_kb/ingestion/document_graph.py`
- Test: `tests/ingestion/test_document_graph.py`

- [ ] Add parser and graph tests:

```python
def write_md(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_markdown_parser_keeps_relative_markdown_links() -> None:
    assert MarkdownLinkParser.extract_links(
        "[SelectNext](execSites.39.09.md) [SMT](100096.htm)"
    ) == ["execSites.39.09.md", "100096.htm"]


def test_graph_resolves_igxl_relative_markdown_link(tmp_path: Path) -> None:
    write_md(tmp_path, "igxl/vbt/execSites.39.08.md", "[SelectNext](execSites.39.09.md)")
    write_md(tmp_path, "igxl/vbt/execSites.39.09.md", "# SelectNext")
    graph = DocumentGraphBuilder(tmp_path).build()
    assert graph["igxl/vbt/execSites.39.08.md"]["linked_source_mds"] == [
        "igxl/vbt/execSites.39.09.md"
    ]
```

- [ ] Run:

```bash
uv run pytest tests/ingestion/test_document_graph.py -q
```

Expected: fail because `.md` links are discarded.

- [ ] Expand the parser pattern to accept Markdown and HTML targets:

```python
_MD_LINK_RE = re.compile(
    r"\[([^\]]+)\]\(([^)#?\s\"]+\.(?:md|html?))(?:[?#][^)\s\"]*)?(?:\s+\"[^\"]*\")?\)",
    re.IGNORECASE,
)
_HTML_A_RE = re.compile(
    r'<a\s+[^>]*href="([^"]+\.(?:md|html?))"[^>]*>',
    re.IGNORECASE,
)


def _is_internal_href(href: str) -> bool:
    href_lower = href.lower()
    if href_lower.startswith(("http://", "https://", "ftp://", "mailto:")):
        return False
    if "/assets/" in href_lower or href_lower.startswith(("assets/", "../assets/")):
        return False
    return href_lower.endswith((".md", ".htm", ".html"))
```

- [ ] Import `posixpath` and `PurePosixPath` in `src/ate_rag_kb/ingestion/document_graph.py`.
- [ ] Resolve `.md` links relative to the current Markdown document:

```python
def _resolve_href(self, current_source_md: str, href: str) -> str | None:
    href_path = PurePosixPath(href)
    if href_path.suffix.lower() == ".md":
        candidate = posixpath.normpath(
            str(PurePosixPath(current_source_md).parent / href_path)
        )
        if (self.markdown_dir / candidate).exists():
            return candidate
        return None
    relative_html = posixpath.normpath(
        str(PurePosixPath(current_source_md).parent / href_path)
    )
    return self._html_to_md.get(href) or self._html_to_md.get(relative_html)
```

- [ ] Call `_resolve_href(rel_md, href)` from `build()`.
- [ ] Normalize `.` and `..` segments with `posixpath.normpath()` before checking whether a Markdown target exists.
- [ ] Retain the HTML-to-Markdown lookup for `.htm` and `.html` links and try both the literal href and the normalized relative href.
- [ ] Run:

```bash
uv run pytest tests/ingestion/test_document_graph.py -q
```

Expected: pass.

- [ ] Commit:

```bash
git add src/ate_rag_kb/ingestion/document_graph.py tests/ingestion/test_document_graph.py
git commit -m "fix: resolve IG-XL markdown graph links"
```

## Task 5: Generate Symbol Ownership Catalog

**Files:**
- Create: `src/ate_rag_kb/ingestion/symbol_catalog.py`
- Modify: `src/ate_rag_kb/ingestion/pipeline.py`
- Test: `tests/ingestion/test_symbol_catalog.py`

- [ ] Write tests using small IG-XL and SMT7 fixtures:

```python
def write_md(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_catalog_records_exclusive_symbol_owners(tmp_path: Path) -> None:
    write_md(tmp_path, "igxl/vbt/execSites.39.08.md", "# SelectFirst Method")
    write_md(tmp_path, "v93000/smt7/100096.md", "# ON_FIRST_INVOCATION_BEGIN")
    catalog = SymbolCatalogBuilder(tmp_path).build()
    assert catalog.owner_for("SelectFirst").software == "igxl"
    assert catalog.owner_for("ON_FIRST_INVOCATION_BEGIN").software == "smt7"


def test_catalog_does_not_claim_shared_symbol(tmp_path: Path) -> None:
    write_md(tmp_path, "igxl/vbt/shared.md", "# Execute")
    write_md(tmp_path, "v93000/smt7/shared.md", "# Execute")
    catalog = SymbolCatalogBuilder(tmp_path).build()
    assert catalog.owner_for("Execute") is None
```

- [ ] Run:

```bash
uv run pytest tests/ingestion/test_symbol_catalog.py -q
```

Expected: fail because the catalog module does not exist.

- [ ] Implement a catalog that extracts code-like symbols from headings and first-line titles, records the scopes where each symbol appears, and exposes only symbols with exactly one owning scope. Accept a scope-resolver callable so the builder uses ingestion's title and TOC-aware `_detect_scope()` for root-level SMT7 documents:

```python
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from ate_rag_kb.domain.scopes import RetrievalScope, infer_scope_from_source

ScopeResolver = Callable[[str, str, dict[str, Any]], RetrievalScope | None]
_HEADING_RE = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
_SYMBOL_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_.]*\b")


@dataclass(frozen=True, slots=True)
class SymbolOwner:
    symbol: str
    scope: RetrievalScope
    source_mds: tuple[str, ...]


@dataclass(slots=True)
class SymbolCatalog:
    owners: dict[str, SymbolOwner]

    @classmethod
    def empty(cls) -> "SymbolCatalog":
        return cls({})

    def owner_for(self, symbol: str) -> RetrievalScope | None:
        owner = self.owners.get(symbol.casefold())
        return owner.scope if owner else None

    def find_owner_in_query(self, query: str) -> SymbolOwner | None:
        matches = [
            self.owners[token.casefold()]
            for token in _SYMBOL_RE.findall(query)
            if token.casefold() in self.owners
        ]
        return matches[0] if len({match.scope for match in matches}) == 1 and matches else None

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "owners": {
                key: {
                    "symbol": owner.symbol,
                    **asdict(owner.scope),
                    "source_mds": list(owner.source_mds),
                }
                for key, owner in sorted(self.owners.items())
            },
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "SymbolCatalog":
        payload = json.loads(path.read_text(encoding="utf-8"))
        owners = {
            key: SymbolOwner(
                symbol=value["symbol"],
                scope=RetrievalScope(
                    vendor=value["vendor"],
                    platform=value["platform"],
                    software=value["software"],
                    software_release=value.get("software_release", ""),
                ),
                source_mds=tuple(value["source_mds"]),
            )
            for key, value in payload["owners"].items()
        }
        return cls(owners)

    @classmethod
    def load_if_exists(cls, path: Path) -> "SymbolCatalog":
        return cls.load(path) if path.exists() else cls.empty()


class SymbolCatalogBuilder:
    def __init__(
        self,
        markdown_dir: Path,
        json_dir: Path | None = None,
        scope_resolver: ScopeResolver | None = None,
    ) -> None:
        self.markdown_dir = markdown_dir
        self.json_dir = json_dir
        self.scope_resolver = scope_resolver or (
            lambda source_md, _title, _metadata: infer_scope_from_source(source_md)
        )

    def build(self) -> SymbolCatalog:
        observed: dict[str, dict[RetrievalScope, set[str]]] = {}
        display_names: dict[str, str] = {}
        for md_path in sorted(self.markdown_dir.rglob("*.md")):
            source_md = md_path.relative_to(self.markdown_dir).as_posix()
            metadata = self._metadata(source_md)
            title = metadata.get("title", "")
            scope = self.scope_resolver(source_md, title, metadata)
            if scope is None:
                continue
            text = md_path.read_text(encoding="utf-8")
            candidates = [title, *_HEADING_RE.findall(text)]
            for symbol in _SYMBOL_RE.findall("\n".join(candidates)):
                key = symbol.casefold()
                display_names.setdefault(key, symbol)
                observed.setdefault(key, {}).setdefault(scope, set()).add(source_md)
        owners = {
            key: SymbolOwner(display_names[key], next(iter(scopes)), tuple(sorted(next(iter(scopes.values())))))
            for key, scopes in observed.items()
            if len(scopes) == 1
        }
        return SymbolCatalog(owners)

    def _metadata(self, source_md: str) -> dict[str, Any]:
        if self.json_dir is None:
            return {}
        path = self.json_dir / Path(source_md).with_suffix(".json")
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))
```

- [ ] Serialize the artifact to `data/processed/symbol_catalog.json` with stable, sorted keys:

```json
{
  "schema_version": 1,
  "owners": {
    "selectfirst": {
      "symbol": "SelectFirst",
      "vendor": "teradyne",
      "platform": "j750",
      "software": "igxl",
      "source_mds": ["igxl/vbt/execSites.39.08.md"]
    }
  }
}
```

- [ ] Add this artifact builder to `IngestionPipeline`:

```python
def _build_symbol_catalog(
    self,
    markdown_dir: Path,
    json_dir: Path | None = None,
) -> None:
    processed_dir = Path(self.config.get("data.processed_dir", "./data/processed"))
    catalog = SymbolCatalogBuilder(
        markdown_dir=markdown_dir,
        json_dir=json_dir,
        scope_resolver=self._detect_scope,
    ).build()
    catalog.save(processed_dir / "symbol_catalog.json")
```

- [ ] Call `_build_symbol_catalog()` after document graph construction in full ingestion and incremental rebuild flows.
- [ ] Run:

```bash
uv run pytest tests/ingestion/test_symbol_catalog.py tests/test_ingestion_pipeline.py tests/test_ingestion_incremental.py -q
```

Expected: pass.

- [ ] Commit:

```bash
git add src/ate_rag_kb/ingestion/symbol_catalog.py src/ate_rag_kb/ingestion/pipeline.py tests/ingestion/test_symbol_catalog.py tests/test_ingestion_pipeline.py tests/test_ingestion_incremental.py
git commit -m "feat: generate symbol ownership catalog"
```

## Task 6: Foundation Regression Gate

- [ ] Run:

```bash
uv run pytest tests/domain tests/ingestion tests/test_chunking_models.py tests/test_document_scope.py tests/test_ingestion_pipeline.py tests/test_ingestion_pipeline_docs.py tests/test_ingestion_incremental.py tests/vector_store -q
```

Expected: exit code `0`.

- [ ] Inspect staged state:

```bash
git status --short
git diff --check
```

Expected: no whitespace errors. Existing unrelated user changes may remain visible.
