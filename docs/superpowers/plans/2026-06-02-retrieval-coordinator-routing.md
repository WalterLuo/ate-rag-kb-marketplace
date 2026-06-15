# Retrieval Coordinator Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route every search, retrieve, and ask request through one scope-aware coordinator and prevent cross-platform answer contamination.

**Architecture:** Separate query routing from low-level retrieval. The router resolves one scope, multiple isolated scopes, or a clarification prompt. The coordinator executes the same staged retrieval pipeline once per resolved scope and returns grouped results. MCP and HTTP handlers format coordinator output instead of rebuilding retrieval logic independently.

**Tech Stack:** Python dataclasses, Literal types, existing hybrid retriever, Qdrant filters, MCP Pydantic models, pytest

---

## File Responsibility Map

| File | Responsibility |
|---|---|
| `src/ate_rag_kb/retrieval/routing.py` | User intent, platform aliases, version ambiguity, symbol-owner correction |
| `src/ate_rag_kb/retrieval/planner.py` | Query expansion and low-level retrieval plan generation |
| `src/ate_rag_kb/retrieval/coordinator.py` | Per-scope staged execution and grouped result |
| `src/ate_rag_kb/retrieval/pipeline.py` | One scoped retrieval branch |
| `src/ate_rag_kb/retrieval/document_graph_expander.py` | Filtered graph expansion |
| `src/ate_rag_kb/retrieval/broad_context.py` | Filtered broad-context assembly |
| `src/ate_rag_kb/retrieval/glossary.py` | IG-XL serial-site-loop expansion |
| `src/ate_rag_kb/mcp/models.py` | Grouped MCP response contract |
| `src/ate_rag_kb/mcp/context_builder.py` | Scoped context package formatting |
| `src/ate_rag_kb/mcp/tools.py` | Thin MCP handler delegation |
| `src/ate_rag_kb/api/routes.py` | HTTP delegation to coordinator |

## Task 1: Add Deterministic Scope Routing

**Files:**
- Create: `src/ate_rag_kb/retrieval/routing.py`
- Modify: `src/ate_rag_kb/retrieval/planner.py`
- Test: `tests/retrieval/test_routing.py`
- Test: `tests/retrieval/test_planner.py`

- [ ] Write route tests for the approved matrix:

```python
def test_explicit_igxl_routes_only_to_j750(router) -> None:
    route = router.route("IG-XL 多 site 串行处理怎么实现？")
    assert route.answer_mode == "direct"
    assert route.scopes == (TERADYNE_J750_IGXL,)


def test_neutral_question_routes_to_two_isolated_scopes(router) -> None:
    route = router.route("多 site 串行处理怎么实现？")
    assert route.answer_mode == "platform_comparison"
    assert route.scopes == (TERADYNE_J750_IGXL, ADVANTEST_V93000_SMT7)


def test_exclusive_symbol_without_platform_routes_to_owner(router) -> None:
    route = router.route("SelectFirst 怎么用？")
    assert route.scopes == (TERADYNE_J750_IGXL,)


def test_wrong_platform_symbol_is_corrected(router) -> None:
    route = router.route("SMT7 SelectFirst 怎么用？")
    assert route.scopes == (TERADYNE_J750_IGXL,)
    assert "SelectFirst" in route.correction_notice
    assert "IG-XL" in route.correction_notice


def test_v93000_requires_version_when_smt7_and_smt8_enabled(catalog) -> None:
    router = ScopeRouter(
        enabled_scopes=(ADVANTEST_V93000_SMT7, ADVANTEST_V93000_SMT8),
        symbol_catalog=catalog,
    )
    route = router.route("V93000 site control 怎么用？")
    assert route.answer_mode == "clarification"
    assert "SMT7" in route.clarification_prompt
    assert "SMT8" in route.clarification_prompt


def test_neutral_question_requires_platform_after_smt8_enablement(catalog) -> None:
    router = ScopeRouter(
        enabled_scopes=(TERADYNE_J750_IGXL, ADVANTEST_V93000_SMT7, ADVANTEST_V93000_SMT8),
        symbol_catalog=catalog,
    )
    route = router.route("site control 怎么用？")
    assert route.answer_mode == "clarification"
    assert "J750" in route.clarification_prompt
    assert "V93000" in route.clarification_prompt


def test_explicit_two_software_products_return_two_scopes(router) -> None:
    route = router.route("请分别给出 IG-XL 和 SMT7 的答案")
    assert route.answer_mode == "platform_comparison"
    assert route.scopes == (TERADYNE_J750_IGXL, ADVANTEST_V93000_SMT7)


def test_follow_up_smt7_answer_routes_directly(router) -> None:
    route = router.route("我需要 SMT7 的答案")
    assert route.answer_mode == "direct"
    assert route.scopes == (ADVANTEST_V93000_SMT7,)
```

- [ ] Run:

```bash
uv run pytest tests/retrieval/test_routing.py tests/retrieval/test_planner.py -q
```

Expected: fail because routing is not modeled separately from retrieval planning.

- [ ] Implement the public route model:

```python
from dataclasses import dataclass
from typing import Literal

from ate_rag_kb.domain.scopes import (
    ADVANTEST_V93000_SMT7,
    ADVANTEST_V93000_SMT8,
    TERADYNE_J750_IGXL,
    RetrievalScope,
)
from ate_rag_kb.ingestion.symbol_catalog import SymbolCatalog


AnswerMode = Literal["direct", "platform_comparison", "clarification"]


@dataclass(frozen=True, slots=True)
class QueryRoute:
    answer_mode: AnswerMode
    scopes: tuple[RetrievalScope, ...] = ()
    correction_notice: str = ""
    clarification_prompt: str = ""
```

- [ ] Implement `ScopeRouter.route()` with deterministic precedence:

```python
class ScopeRouter:
    def __init__(
        self,
        enabled_scopes: tuple[RetrievalScope, ...],
        symbol_catalog: SymbolCatalog,
    ) -> None:
        self.enabled_scopes = enabled_scopes
        self.symbol_catalog = symbol_catalog

    def route(self, query: str) -> QueryRoute:
        symbol_owner = self.symbol_catalog.find_owner_in_query(query)
        explicit = self._explicit_scopes(query)
        requested_platforms = self._explicit_platforms(query)
        if symbol_owner is not None:
            correction = ""
            conflicts_with_scope = explicit and symbol_owner.scope not in explicit
            conflicts_with_platform = (
                requested_platforms
                and symbol_owner.scope.platform not in requested_platforms
            )
            if conflicts_with_scope or conflicts_with_platform:
                correction = (
                    f"{symbol_owner.symbol} belongs to "
                    f"{symbol_owner.scope.platform.upper()} / {symbol_owner.scope.software.upper()}, "
                    "so the answer is routed to its owning software."
                )
            return QueryRoute("direct", (symbol_owner.scope,), correction_notice=correction)

        if "j750" in requested_platforms:
            explicit = (*explicit, TERADYNE_J750_IGXL)
        if "v93000" in requested_platforms and not any(
            scope.platform == "v93000" for scope in explicit
        ):
            versions = self._v93000_scopes()
            if len(versions) != 1:
                return QueryRoute(
                    "clarification",
                    clarification_prompt="V93000 currently has multiple software versions. Do you need SMT7 or SMT8?",
                )
            explicit = (*explicit, *versions)
        explicit = tuple(dict.fromkeys(explicit))
        if explicit:
            return QueryRoute(
                "platform_comparison" if len(explicit) > 1 else "direct",
                explicit,
            )

        if len(self._v93000_scopes()) > 1:
            return QueryRoute(
                "clarification",
                clarification_prompt="Which tester platform do you need: J750 or V93000?",
            )
        return QueryRoute(
            "platform_comparison" if len(self.enabled_scopes) > 1 else "direct",
            self.enabled_scopes,
        )

    def _explicit_scopes(self, query: str) -> tuple[RetrievalScope, ...]:
        normalized = query.casefold().replace("ig-xl", "igxl")
        scopes: list[RetrievalScope] = []
        if "igxl" in normalized:
            scopes.append(TERADYNE_J750_IGXL)
        if "smt7" in normalized or "smartest 7" in normalized:
            scopes.append(ADVANTEST_V93000_SMT7)
        if "smt8" in normalized or "smartest 8" in normalized:
            scopes.append(ADVANTEST_V93000_SMT8)
        return tuple(scope for scope in scopes if scope in self.enabled_scopes)

    def _explicit_platforms(self, query: str) -> set[str]:
        normalized = query.casefold()
        platforms: set[str] = set()
        if "j750" in normalized:
            platforms.add("j750")
        if "v93000" in normalized:
            platforms.add("v93000")
        return platforms

    def _v93000_scopes(self) -> tuple[RetrievalScope, ...]:
        return tuple(scope for scope in self.enabled_scopes if scope.platform == "v93000")
```

- [ ] Implement route priority in this order:

```text
exclusive symbol owner
-> explicit software
-> explicit platform
-> explicit request for two answers
-> enabled-scope default
```

- [ ] Treat `j750`, `ig-xl`, and `igxl` as J750 / IG-XL aliases.
- [ ] Treat `v93000` as the tester platform alias and `smt7`, `smt8`, `smartest 7`, `smartest 8` as software aliases.
- [ ] If an exclusive symbol conflicts with an explicit platform or software, return only the symbol owner scope and populate `correction_notice`.
- [ ] Use catalog ownership only to select a scope. Do not copy catalog `source_mds` into search filters, ranking boosts, or context packages.
- [ ] When only IG-XL and SMT7 are enabled, default a neutral query to both scopes.
- [ ] When SMT7 and SMT8 are both enabled, return a clarification prompt for neutral requests and V93000-only requests.
- [ ] Keep broad-answer completeness separate from `answer_mode`: use `completeness_required` and scoped coverage topics for broad concepts while `answer_mode` remains `direct`, `platform_comparison`, or `clarification`.
- [ ] Refactor `RetrievalPlanner` so query expansion receives the resolved scope instead of independently guessing the ecosystem.
- [ ] Run:

```bash
uv run pytest tests/retrieval/test_routing.py tests/retrieval/test_planner.py -q
```

Expected: pass.

- [ ] Commit:

```bash
git add src/ate_rag_kb/retrieval/routing.py src/ate_rag_kb/retrieval/planner.py tests/retrieval/test_routing.py tests/retrieval/test_planner.py
git commit -m "feat: add deterministic scope routing"
```

## Task 2: Expand IG-XL Serial Site Loop Vocabulary

**Files:**
- Modify: `src/ate_rag_kb/retrieval/glossary.py`
- Test: `tests/retrieval/test_planner.py`

- [ ] Add a failing planner test:

```python
def test_igxl_serial_site_loop_expands_api_terms(planner) -> None:
    plan = planner.plan("IG-XL 多 site 串行处理怎么实现？", scope=TERADYNE_J750_IGXL)
    assert "SelectFirst" in plan.enhanced_query
    assert "SelectNext" in plan.enhanced_query
    assert "loopDone" in plan.enhanced_query
    assert "FastSiteLoop" in plan.enhanced_query
```

- [ ] Run:

```bash
uv run pytest tests/retrieval/test_planner.py -q
```

Expected: fail because the IG-XL serial-site-loop glossary entry is absent.

- [ ] Add a scoped glossary entry:

```python
GlossaryEntry(
    cn_terms=(
        "多 site 串行处理",
        "多site串行处理",
        "串行 site",
    ),
    en_terms=("serial site loop",),
    expansions=("SelectFirst", "SelectNext", "LoopStatus", "loopDone", "FastSiteLoop"),
    doc_family="igxl_help",
    software="igxl",
)
```

- [ ] Add `software: str | None = None` to `GlossaryEntry`. Retain compatibility for existing `ecosystem` glossary entries while preferring the canonical `software` field.
- [ ] Run:

```bash
uv run pytest tests/retrieval/test_planner.py -q
```

Expected: pass.

- [ ] Commit:

```bash
git add src/ate_rag_kb/retrieval/glossary.py tests/retrieval/test_planner.py
git commit -m "feat: expand IG-XL serial site loop queries"
```

## Task 3: Apply Scope Filters To Every Retrieval Stage

**Files:**
- Modify: `src/ate_rag_kb/retrieval/pipeline.py`
- Modify: `src/ate_rag_kb/retrieval/document_graph_expander.py`
- Modify: `src/ate_rag_kb/retrieval/broad_context.py`
- Modify: `src/ate_rag_kb/retrieval/parent_child.py`
- Test: `tests/retrieval/test_pipeline.py`
- Test: `tests/retrieval/test_document_graph_expander.py`
- Test: `tests/retrieval/test_broad_context.py`
- Test: `tests/test_retrieval_parent_child.py`

- [ ] Add graph-expansion regression coverage:

```python
def test_graph_expansion_keeps_scope_filter(expander, vector_store) -> None:
    chunks = expander.expand(
        [igxl_seed],
        vector_store=vector_store,
        filters={"vendor": "teradyne", "platform": "j750", "software": "igxl"},
    )
    assert {chunk.software for chunk in chunks} == {"igxl"}
```

- [ ] Add broad-context regression coverage using one IG-XL seed and one linked SMT7 fixture. Assert SMT7 chunks are excluded from the IG-XL branch.
- [ ] Run:

```bash
uv run pytest tests/retrieval/test_pipeline.py tests/retrieval/test_document_graph_expander.py tests/retrieval/test_broad_context.py tests/test_retrieval_parent_child.py -q
```

Expected: fail because filters are not threaded through expansion and broad assembly.

- [ ] Import `dataclass`, `RetrievalScope`, and `RetrievalPlan` into `src/ate_rag_kb/retrieval/pipeline.py`, then add scoped branch entry points:

```python
@dataclass(slots=True)
class ScopedPipelineResult:
    chunks: list[tuple[Chunk, float]]
    processing: dict[str, Any]


async def search_scope(
    self,
    query: str,
    *,
    plan: RetrievalPlan,
    scope: RetrievalScope,
    top_k: int,
    user_filters: dict[str, Any] | None = None,
) -> ScopedPipelineResult:
    filters = dict(user_filters or {})
    filters.update(scope.to_filters())
    chunks = await self.search_enriched(
        query=query,
        plan=plan,
        top_k=top_k,
        filters=filters,
    )
    before_filter = len(chunks)
    chunks = [
        (chunk, score)
        for chunk, score in chunks
        if scope.matches_document(chunk.vendor, chunk.platform, chunk.software)
    ]
    processing = dict(self._last_retrieval_stats)
    processing["cross_scope_dropped_chunk_count"] = (
        processing.get("cross_scope_dropped_chunk_count", 0)
        + before_filter
        - len(chunks)
    )
    return ScopedPipelineResult(chunks=chunks, processing=processing)


async def retrieve_scope(
    self,
    query: str,
    *,
    plan: RetrievalPlan,
    scope: RetrievalScope,
    top_k: int,
    user_filters: dict[str, Any] | None,
    rerank: bool,
    expand_parents: bool,
    expand_siblings: bool,
    compress: bool,
) -> ScopedPipelineResult:
    filters = dict(user_filters or {})
    filters.update(scope.to_filters())
    chunks = await self.retrieve_enriched(
        query=query,
        plan=plan,
        top_k=top_k,
        filters=filters,
        expand_parents=expand_parents,
        expand_siblings=expand_siblings,
        rerank=rerank,
        compress=compress,
        scope=scope,
    )
    before_filter = len(chunks)
    chunks = [
        (chunk, score)
        for chunk, score in chunks
        if scope.matches_document(chunk.vendor, chunk.platform, chunk.software)
    ]
    processing = dict(self._last_retrieval_stats)
    processing["cross_scope_dropped_chunk_count"] = (
        processing.get("cross_scope_dropped_chunk_count", 0)
        + before_filter
        - len(chunks)
    )
    return ScopedPipelineResult(chunks=chunks, processing=processing)
```

- [ ] Pass the same filters through dense search, sparse search, graph expansion, broad-context assembly, parent-child expansion, and final deduplication. Add `filters: dict[str, Any] | None = None` to the graph, broad-context, and parent-child expansion methods and merge those filters into their vector-store fetches.
- [ ] Merge optional user filters first and canonical scope filters second so callers cannot override `vendor`, `platform`, or `software`.
- [ ] Merge `source_md` and `chunk_type` graph fetch filters with the canonical scope filters.
- [ ] Add `scope: RetrievalScope | None = None` to `retrieve_enriched()`. Apply this defensive check after expansion and before compression:

```python
cross_scope_dropped_chunk_count = 0
if scope is not None:
    before_scope_filter = len(chunks)
    chunks = [chunk for chunk in chunks if scope.matches_document(
        chunk.vendor,
        chunk.platform,
        chunk.software,
    )]
    cross_scope_dropped_chunk_count = before_scope_filter - len(chunks)
```

- [ ] Record `cross_scope_dropped_chunk_count` in `_last_retrieval_stats`.
- [ ] Run:

```bash
uv run pytest tests/retrieval/test_pipeline.py tests/retrieval/test_document_graph_expander.py tests/retrieval/test_broad_context.py tests/test_retrieval_parent_child.py -q
```

Expected: pass.

- [ ] Commit:

```bash
git add src/ate_rag_kb/retrieval/pipeline.py src/ate_rag_kb/retrieval/document_graph_expander.py src/ate_rag_kb/retrieval/broad_context.py src/ate_rag_kb/retrieval/parent_child.py tests/retrieval/test_pipeline.py tests/retrieval/test_document_graph_expander.py tests/retrieval/test_broad_context.py tests/test_retrieval_parent_child.py
git commit -m "fix: enforce scope filters across retrieval stages"
```

## Task 4: Introduce Unified Retrieval Coordinator

**Files:**
- Create: `src/ate_rag_kb/retrieval/coordinator.py`
- Test: `tests/retrieval/test_coordinator.py`

- [ ] Write coordinator tests:

```python
@pytest.mark.asyncio
async def test_coordinator_executes_one_branch_per_resolved_scope(coordinator, pipeline) -> None:
    result = await coordinator.retrieve("多 site 串行处理怎么实现？", top_k=8)
    assert [group.scope.key for group in result.groups] == ["j750/igxl", "v93000/smt7"]
    assert pipeline.retrieve_scope.call_count == 2


@pytest.mark.asyncio
async def test_clarification_route_skips_retrieval(coordinator_with_smt8, pipeline) -> None:
    result = await coordinator_with_smt8.retrieve("V93000 site control 怎么用？", top_k=8)
    assert result.answer_mode == "clarification"
    pipeline.retrieve_scope.assert_not_called()
```

- [ ] Run:

```bash
uv run pytest tests/retrieval/test_coordinator.py -q
```

Expected: fail because the coordinator does not exist.

- [ ] Implement grouped result models:

```python
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
```

- [ ] Implement `RetrievalCoordinator.search()` and `RetrievalCoordinator.retrieve()`:

```python
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
                    query,
                    plan=plan,
                    scope=scope,
                    top_k=top_k,
                    user_filters=filters,
                )
            else:
                branch = await self.pipeline.retrieve_scope(
                    query,
                    plan=plan,
                    scope=scope,
                    top_k=top_k,
                    user_filters=filters,
                    rerank=rerank,
                    expand_parents=expand_parents,
                    expand_siblings=expand_siblings,
                    compress=compress,
                )
            groups.append(ScopedRetrievalResult(scope, branch.chunks, branch.processing))
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
```

- [ ] The implementation must preserve this staged behavior:

```text
route query
-> return clarification without retrieval when required
-> execute one pipeline branch per resolved scope
-> retain groups instead of flattening chunks
-> aggregate processing statistics by scope key
```

- [ ] Run:

```bash
uv run pytest tests/retrieval/test_coordinator.py -q
```

Expected: pass.

- [ ] Commit:

```bash
git add src/ate_rag_kb/retrieval/coordinator.py tests/retrieval/test_coordinator.py
git commit -m "feat: add unified retrieval coordinator"
```

## Task 5: Delegate MCP Search, Retrieve, And Ask

**Files:**
- Modify: `src/ate_rag_kb/mcp/models.py`
- Modify: `src/ate_rag_kb/mcp/context_builder.py`
- Modify: `src/ate_rag_kb/mcp/tools.py`
- Modify: `src/ate_rag_kb/retrieval/pipeline.py`
- Test: `tests/mcp/test_context_builder.py`
- Test: `tests/mcp/test_tools.py`

- [ ] Extend MCP handler tests:

```python
@pytest.mark.asyncio
async def test_ask_returns_isolated_context_sections(handler) -> None:
    response = await handler.handle_ask({"question": "多 site 串行处理怎么实现？"})
    assert response.answer_contract.answer_mode == "platform_comparison"
    assert [scope.model_dump(exclude_defaults=True) for scope in response.answer_contract.resolved_scopes] == [
        {"vendor": "teradyne", "platform": "j750", "software": "igxl"},
        {"vendor": "advantest", "platform": "v93000", "software": "smt7"},
    ]
    assert set(response.answer_contract.coverage_topics_by_scope) == {
        "j750/igxl",
        "v93000/smt7",
    }


@pytest.mark.asyncio
async def test_ask_returns_clarification_without_flat_context(handler_with_smt8) -> None:
    response = await handler_with_smt8.handle_ask({"question": "V93000 site control 怎么用？"})
    assert response.answer_contract.answer_mode == "clarification"
    assert response.context_package is None
```

- [ ] Run:

```bash
uv run pytest tests/mcp/test_tools.py -q
```

Expected: fail because MCP tools still assemble one flat retrieval result.

- [ ] Add canonical metadata to MCP chunk models:

```python
vendor: str = ""
platform: str = ""
software: str = ""
software_release: str = ""
```

- [ ] Add the resolved-scope model and extend the answer contract:

```python
class McpResolvedScope(BaseModel):
    vendor: str
    platform: str
    software: str
    software_release: str = ""


class McpAnswerContract(BaseModel):
    answer_mode: str = "direct"
    completeness_required: bool = False
    resolved_scopes: list[McpResolvedScope] = Field(default_factory=list)
    correction_notice: str = ""
    clarification_prompt: str = ""
    required_sections: list[str] = Field(default_factory=list)
    coverage_topics: list[str] = Field(default_factory=list)
    coverage_topics_by_scope: dict[str, list[str]] = Field(default_factory=dict)
    synthesis_rules: list[str] = Field(default_factory=list)
    diagnostics: dict = Field(default_factory=dict)
```

- [ ] Preserve flat `coverage_topics` for single-scope compatibility. Populate `coverage_topics_by_scope` for every resolved scope and represent broadness with `completeness_required`, not a separate `answer_mode`.
- [ ] Add canonical status fields:

```python
vendors: list[str] = Field(default_factory=list)
softwares: list[str] = Field(default_factory=list)
software_releases: list[str] = Field(default_factory=list)
```

- [ ] Add scoped context formatting to `src/ate_rag_kb/mcp/context_builder.py`:

```python
def build_scoped_context_package(
    groups: list[tuple[RetrievalScope, list[tuple[Chunk, float]]]],
    max_tokens: int = 4000,
) -> McpContextPackage:
    parts: list[str] = []
    citation_map: list[dict] = []
    token_estimate = 0
    citation_index = 1
    scope_budget = max(1, max_tokens // max(1, len(groups)))
    for scope, chunks in groups:
        parts.append(f"## {scope.platform.upper()} / {scope.software.upper()}\n")
        scope_tokens = 0
        for chunk, _score in chunks:
            entry = (
                f'[{citation_index}] From "{chunk.doc_title or "Unknown"}" '
                f'> "{chunk.section_title or "Unknown"}":\n'
                f"    {chunk.content.strip()}\n"
            )
            entry_tokens = len(entry) // 4
            if scope_tokens + entry_tokens > scope_budget:
                break
            parts.append(entry)
            citation_map.append(
                {
                    "index": citation_index,
                    "chunk_id": chunk.id,
                    "source_md": chunk.source_md,
                    "toc_path": chunk.toc_path,
                    "start_line": chunk.start_line,
                    "end_line": chunk.end_line,
                    "scope": scope.key,
                }
            )
            scope_tokens += entry_tokens
            token_estimate += entry_tokens
            citation_index += 1
    return McpContextPackage(
        text="\n".join(parts),
        token_estimate=token_estimate,
        citation_map=citation_map,
    )
```

- [ ] Add `processing_by_scope` and `cross_scope_dropped_chunk_count` under the existing top-level processing metadata.
- [ ] Preserve `dense_candidate_count`, `sparse_candidate_count`, `sparse_search_used`, and `legacy_bm25_fallback_used` inside each `processing_by_scope` entry so sparse-retrieval health remains observable per platform.
- [ ] Format grouped context with explicit headings. Each heading is followed by the retrieved citation blocks for that scope:

```text
## J750 / IG-XL
## V93000 / SMT7
```

- [ ] Construct one coordinator in `McpToolHandler.__init__()`:

```python
self.coordinator = build_retrieval_coordinator(pipeline.config, pipeline=self.pipeline)
self.planner = self.coordinator.planner
```

- [ ] Delegate `handle_search()`, `handle_retrieve()`, and `handle_ask()` to the coordinator. For retrieve and ask, build processing metadata from isolated branches:

```python
coordinated = await self.coordinator.retrieve(
    question,
    top_k=top_k * 2,
    filters=user_filters,
    rerank=True,
    expand_parents=True,
    expand_siblings=True,
    compress=True,
)
processing_info = {
    "processing_by_scope": coordinated.processing_by_scope,
    "cross_scope_dropped_chunk_count": coordinated.cross_scope_dropped_chunk_count,
}
grouped_chunks = [(group.scope, group.chunks) for group in coordinated.groups]
context_package = build_scoped_context_package(
    grouped_chunks,
    max_tokens=self.pipeline.config.get("retrieval.broad_context.max_tokens", 9000),
)
```

- [ ] Build the route portion of every answer contract from coordinator output:

```python
contract = McpAnswerContract(
    answer_mode=coordinated.answer_mode,
    resolved_scopes=[
        McpResolvedScope(**asdict(group.scope))
        for group in coordinated.groups
    ],
    correction_notice=coordinated.correction_notice,
    clarification_prompt=coordinated.clarification_prompt,
    completeness_required=any(
        stats.get("broad_context_assembled", False)
        for stats in coordinated.processing_by_scope.values()
    ),
    coverage_topics_by_scope={
        scope_key: list(stats.get("coverage_topics", []))
        for scope_key, stats in coordinated.processing_by_scope.items()
    },
)
```

- [ ] For `clarification`, return empty chunks and citations, `context_package=None`, and an answer contract containing `clarification_prompt`.
- [ ] Preserve flat MCP `chunks`, `citations`, and `source_files` for compatibility by flattening only after each isolated branch completes. Use the grouped context package for synthesis so platform sections remain explicit.
- [ ] Populate MCP status from canonical collection stats while retaining legacy `ecosystems` and `software_versions` during migration.
- [ ] Extend `RetrievalPipeline.collection_stats()` with canonical sets and return fields:

```python
vendors: set[str] = set()
softwares: set[str] = set()
software_releases: set[str] = set()

for chunk in sample_chunks:
    if chunk.vendor:
        vendors.add(chunk.vendor)
    if chunk.software:
        softwares.add(chunk.software)
    if chunk.software_release:
        software_releases.add(chunk.software_release)

return {
    "collection_name": self.vector_store.collection_name,
    "total_chunks": count,
    "vector_size": vector_size,
    "embedding_model": embedding_model,
    "platforms": sorted(platforms),
    "doc_types": sorted(doc_types),
    "ecosystems": sorted(ecosystems),
    "software_versions": sorted(software_versions),
    "doc_families": sorted(doc_families),
    "sampled_chunks": len(sample_chunks),
    "vendors": sorted(vendors),
    "softwares": sorted(softwares),
    "software_releases": sorted(software_releases),
}
```
- [ ] Keep `get_document`, `related`, and `status` as direct utility operations.
- [ ] Delete handler-level platform post-filtering after equivalent coordinator tests pass.
- [ ] Run:

```bash
uv run pytest tests/mcp/test_context_builder.py tests/mcp/test_tools.py -q
```

Expected: pass.

- [ ] Commit:

```bash
git add src/ate_rag_kb/mcp/models.py src/ate_rag_kb/mcp/context_builder.py src/ate_rag_kb/mcp/tools.py src/ate_rag_kb/retrieval/pipeline.py tests/mcp/test_context_builder.py tests/mcp/test_tools.py
git commit -m "feat: route MCP retrieval through coordinator"
```

## Task 6: Delegate HTTP Retrieval Endpoints

**Files:**
- Modify: `src/ate_rag_kb/api/routes.py`
- Modify: `src/ate_rag_kb/api/models.py`
- Modify: `src/ate_rag_kb/api/server.py`
- Modify: `tests/test_api_server.py`
- Modify: `tests/integration/test_api.py`

- [ ] Add route tests that assert HTTP `/search` and `/ask` return the same `answer_mode`, `resolved_scopes`, and clarification behavior as MCP.
- [ ] Run:

```bash
uv run pytest tests/test_api_server.py tests/integration/test_api.py -q
```

Expected: fail because HTTP handlers still use the pre-coordinator flow.

- [ ] Extend API response models with `answer_mode`, `resolved_scopes`, `correction_notice`, and `clarification_prompt`.
- [ ] Build and inject one `RetrievalCoordinator` in `src/ate_rag_kb/api/server.py`, then delegate `/search`, `/retrieve`, and `/ask`.
- [ ] Use the same grouped response serialization helper as MCP where field names overlap.
- [ ] Run:

```bash
uv run pytest tests/test_api_server.py tests/integration/test_api.py -q
```

Expected: pass.

- [ ] Commit:

```bash
git add src/ate_rag_kb/api/routes.py src/ate_rag_kb/api/models.py src/ate_rag_kb/api/server.py tests/test_api_server.py tests/integration/test_api.py
git commit -m "feat: route HTTP retrieval through coordinator"
```

## Task 7: Coordinator Regression Gate

- [ ] Run:

```bash
uv run pytest tests/retrieval tests/mcp tests/test_api_server.py tests/integration/test_api.py -q
```

Expected: exit code `0`.

- [ ] Run:

```bash
git diff --check
```

Expected: no whitespace errors.
