# Multi-Platform Acceptance Rollout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild normalized artifacts, verify production retrieval behavior, and document the operator workflow for future SMT8 enablement.

**Architecture:** Add one deterministic validation script and one regression fixture matrix before rebuilding. Recreate the collection from normalized payloads, rebuild derived artifacts, restart MCP, and execute live acceptance queries through MCP rather than raw file search.

**Tech Stack:** Python CLI, pytest, Qdrant, MCP, Markdown documentation

---

## File Responsibility Map

| File | Responsibility |
|---|---|
| `tests/fixtures/multi_platform_acceptance.yaml` | Required routing and isolation cases |
| `tests/retrieval/test_multi_platform_acceptance.py` | Deterministic coordinator regression |
| `scripts/validate_multi_platform_retrieval.py` | Collection, graph, catalog, and live coordinator validation |
| `docs/agent_integration.md` | Runtime query-routing behavior |
| `docs/beta_checklist_CN.md` | Operator rebuild and beta acceptance checklist |
| `README.md` | Canonical terminology summary |
| `README_CN.md` | Canonical terminology summary in Chinese |

## Task 1: Add Acceptance Fixture Matrix

**Files:**
- Create: `tests/fixtures/multi_platform_acceptance.yaml`
- Create: `tests/retrieval/test_multi_platform_acceptance.py`

- [ ] Create the fixture:

```yaml
cases:
  - id: explicit_igxl_serial_loop
    query: IG-XL 多 site 串行处理怎么实现？
    answer_mode: direct
    scopes: [j750/igxl]
    required_terms: [SelectFirst, SelectNext, loopDone]
    forbidden_terms: [ON_FIRST_INVOCATION_BEGIN]
  - id: explicit_smt7_site_control
    query: SMT7 Site Control 怎么用？
    answer_mode: direct
    scopes: [v93000/smt7]
    required_terms: [ON_FIRST_INVOCATION_BEGIN]
    forbidden_terms: [SelectFirst]
  - id: exclusive_igxl_symbol
    query: SelectFirst 怎么用？
    answer_mode: direct
    scopes: [j750/igxl]
    required_terms: [SelectFirst]
    forbidden_terms: [ON_FIRST_INVOCATION_BEGIN]
  - id: wrong_platform_symbol
    query: SMT7 SelectFirst 怎么用？
    answer_mode: direct
    scopes: [j750/igxl]
    correction_required: true
  - id: neutral_site_loop
    query: 多 site 串行处理怎么实现？
    answer_mode: platform_comparison
    scopes: [j750/igxl, v93000/smt7]
```

- [ ] Implement a parametrized test that loads each case, calls `RetrievalCoordinator.retrieve()`, checks `answer_mode`, scope keys, correction notice, and required or forbidden terms in each grouped context:

```python
def load_cases() -> list[dict]:
    fixture_path = Path(__file__).parents[1] / "fixtures" / "multi_platform_acceptance.yaml"
    return yaml.safe_load(fixture_path.read_text(encoding="utf-8"))["cases"]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", load_cases())
async def test_multi_platform_acceptance(case: dict, coordinator: RetrievalCoordinator) -> None:
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
```
- [ ] Run:

```bash
uv run pytest tests/retrieval/test_multi_platform_acceptance.py -q
```

Expected: pass after the coordinator plan is complete.

- [ ] Commit:

```bash
git add tests/fixtures/multi_platform_acceptance.yaml tests/retrieval/test_multi_platform_acceptance.py
git commit -m "test: add multi-platform acceptance matrix"
```

## Task 2: Add Artifact Validation Script

**Files:**
- Create: `scripts/validate_multi_platform_retrieval.py`
- Test: `tests/test_validate_multi_platform_retrieval.py`

- [ ] Write unit tests for validation failures:

```python
def test_validation_fails_when_selectfirst_owner_is_missing(tmp_path: Path) -> None:
    result = validate_symbol_catalog(tmp_path / "symbol_catalog.json")
    assert result.errors == ["symbol catalog missing owner: SelectFirst -> j750/igxl"]


def test_validation_fails_when_igxl_graph_edge_is_missing(tmp_path: Path) -> None:
    result = validate_document_graph(tmp_path / "document_graph.json")
    assert result.errors == [
        "document graph missing edge: igxl/vbt/execSites.39.08.md -> igxl/vbt/execSites.39.09.md"
    ]
```

- [ ] Run:

```bash
uv run pytest tests/test_validate_multi_platform_retrieval.py -q
```

Expected: fail because the validation script does not exist.

- [ ] Implement script checks for:

```text
Qdrant collection exists
-> collection contains j750/igxl chunks
-> collection contains v93000/smt7 chunks
-> sparse vocabulary artifact exists and is non-empty
-> document graph contains execSites.39.08.md -> execSites.39.09.md
-> document graph contains execSites.39.44.md -> execSites.39.45.md
-> symbol catalog owns SelectFirst as j750/igxl
-> symbol catalog owns ON_FIRST_INVOCATION_BEGIN as v93000/smt7
-> coordinator returns isolated groups for acceptance fixture cases
```

- [ ] Implement artifact validators with exact errors:

```python
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
```

- [ ] Add a `main()` function that loads `configs/config.yaml`, checks Qdrant counts with canonical filters, checks the persisted sparse vocabulary, runs both artifact validators, executes fixture cases through `RetrievalCoordinator`, prints `PASS` or `FAIL` per check, and exits with `1` when any error is present:

```python
def load_cases() -> list[dict]:
    fixture_path = Path("tests/fixtures/multi_platform_acceptance.yaml")
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
    vocab_path = Path(config.get("data.processed_dir", "./data/processed")) / "sparse_vocab.json"
    vocab = json.loads(vocab_path.read_text(encoding="utf-8")) if vocab_path.exists() else {}
    if vocab.get("vocab_size", 0) == 0:
        errors.append("sparse vocabulary missing or empty")
    for case in load_cases():
        result = await coordinator.retrieve(case["query"], top_k=8)
        if result.answer_mode != case["answer_mode"]:
            errors.append(f"{case['id']}: unexpected answer mode {result.answer_mode}")
        if [group.scope.key for group in result.groups] != case["scopes"]:
            errors.append(f"{case['id']}: unexpected resolved scopes")
        for group in result.groups:
            if not group.processing.get("sparse_search_used", False):
                errors.append(f"{case['id']}: sparse search inactive for {group.scope.key}")
            if group.processing.get("sparse_candidate_count", 0) == 0:
                errors.append(f"{case['id']}: sparse search returned no candidates for {group.scope.key}")
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
```

- [ ] End the script with `raise SystemExit(main())`.
- [ ] Print one line per check and exit non-zero when any check fails.
- [ ] Run:

```bash
uv run pytest tests/test_validate_multi_platform_retrieval.py -q
```

Expected: pass.

- [ ] Commit:

```bash
git add scripts/validate_multi_platform_retrieval.py tests/test_validate_multi_platform_retrieval.py
git commit -m "test: add multi-platform artifact validator"
```

## Task 3: Document Canonical Terminology And Operator Flow

**Files:**
- Modify: `README.md`
- Modify: `README_CN.md`
- Modify: `docs/agent_integration.md`
- Modify: `docs/beta_checklist_CN.md`

- [ ] Add this terminology table to both README variants:

| Vendor | Tester platform | Software |
|---|---|---|
| Advantest | V93000 | SMT7, SMT8 |
| Teradyne | J750 | IG-XL |

- [ ] Document routing rules in `docs/agent_integration.md`:

```text
Explicit software or platform -> one resolved scope
Exclusive symbol -> generated catalog owner scope
Wrong platform plus exclusive symbol -> correction notice and owner scope
Neutral query with IG-XL plus SMT7 enabled -> two isolated answer sections
V93000 with SMT7 plus SMT8 enabled -> ask for software version
Neutral query after SMT8 enablement -> ask J750 or V93000 first
```

- [ ] Add production rebuild steps and the acceptance matrix command to `docs/beta_checklist_CN.md`.
- [ ] Run:

```bash
git diff --check README.md README_CN.md docs/agent_integration.md docs/beta_checklist_CN.md
```

Expected: no whitespace errors.

- [ ] Commit:

```bash
git add README.md README_CN.md docs/agent_integration.md docs/beta_checklist_CN.md
git commit -m "docs: describe multi-platform retrieval routing"
```

## Task 4: Run Full Automated Verification

- [ ] Run:

```bash
uv run pytest -q
```

Expected: exit code `0`.

- [ ] Run:

```bash
git diff --check
```

Expected: no whitespace errors.

## Task 5: Perform Clean Production Rebuild

- [ ] Confirm the Qdrant service configured in `configs/config.yaml` is reachable:

```bash
uv run -m ate_rag_kb.cli.main status
```

Expected: collection status is printed without a connection error.

- [ ] Perform a full rebuild:

```bash
uv run -m ate_rag_kb.cli.main ingest --dir data/raw/markdown
```

Expected: ingestion completes successfully, sparse vocabulary is rebuilt, document graph is rebuilt, and symbol catalog is rebuilt.

- [ ] Validate rebuilt artifacts:

```bash
uv run scripts/validate_multi_platform_retrieval.py
```

Expected: every validation line reports `PASS` and the command exits with code `0`.

## Task 6: Restart MCP And Run Live Acceptance

- [ ] Restart the configured ATE KB MCP server from the Codex MCP settings so the process loads the rebuilt collection metadata and generated artifacts.
- [ ] Call `ate_kb.status`.
- [ ] Confirm status reports canonical metadata counts for `j750/igxl` and `v93000/smt7`.
- [ ] Call `ate_kb.ask` for:

```text
IG-XL 多 site 串行处理怎么实现？
```

- [ ] Confirm the response cites IG-XL sources including:

```text
igxl/vbt/execSites.39.08.md
igxl/vbt/execSites.39.09.md
igxl/vbt/execSites.39.45.md
```

- [ ] Confirm the response explains `SelectFirst`, `SelectNext`, and `loopDone` without SMT7-only APIs.
- [ ] Confirm IG-XL processing diagnostics report `sparse_search_used=true` and a non-zero `sparse_candidate_count`.
- [ ] Call `ate_kb.ask` for:

```text
SMT7 Site Control 怎么用？
```

- [ ] Confirm the response cites SMT7 sources and contains no IG-XL-only APIs such as `SelectFirst`.
- [ ] Confirm SMT7 processing diagnostics report `sparse_search_used=true`; record whether `legacy_bm25_fallback_used` was needed.
- [ ] Call `ate_kb.ask` for:

```text
多 site 串行处理怎么实现？
```

- [ ] Confirm the response returns two isolated sections:

```text
J750 / IG-XL
V93000 / SMT7
```

- [ ] Call `ate_kb.ask` for:

```text
SMT7 SelectFirst 怎么用？
```

- [ ] Confirm the response explains that `SelectFirst` belongs to J750 / IG-XL and answers only from IG-XL sources.

## Task 7: Record Acceptance Result

**Files:**
- Modify: `docs/beta_checklist_CN.md`

- [ ] Record the rebuild timestamp, collection chunk count, validation-script result, full pytest result, and the four live MCP acceptance outcomes.
- [ ] Run:

```bash
git diff --check docs/beta_checklist_CN.md
```

Expected: no whitespace errors.

- [ ] Commit:

```bash
git add docs/beta_checklist_CN.md
git commit -m "docs: record multi-platform retrieval acceptance"
```
