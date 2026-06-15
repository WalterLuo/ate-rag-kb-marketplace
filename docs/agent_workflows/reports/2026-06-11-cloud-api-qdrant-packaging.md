# Claude Code Completion Report

## Status

`codex_verified`

## Task Package

`docs/agent_workflows/tasks/2026-06-11-cloud-api-qdrant-packaging.md`

## Branch

`codex/cloud-api-qdrant-packaging`

## Summary

Implemented cloud API provider support for embedding and reranking, disabled
deprecated Qdrant local file mode, added Qdrant snapshot tooling with restore
priority, hardened model packaging/verification scripts, made model names
environment-switchable via `${VAR:-default}` syntax in config, and updated
documentation for Windows deployment. All changes are covered by mocked unit
tests; no live external API calls are made in tests.

This report covers the initial implementation, two blocking fixes from the
Codex review round, and Codex's final integration review.

## Changed Files

| File | Change |
|---|---|
| `configs/config.yaml` | Add `embedding.api` section, `embedding.provider`, `retrieval.reranker.provider`, `retrieval.reranker.api` section; switch `embedding.model_name` and `retrieval.reranker.model_name` to `${VAR:-default}` env expansion syntax; update vector_store comments to mark local mode deprecated |
| `src/ate_rag_kb/vector_store/qdrant_client.py` | Raise `RuntimeError` for `mode=local` and legacy `use_local=true` with deprecation message; update class docstring |
| `src/ate_rag_kb/embedding/providers.py` | New file: `LocalEmbeddingProvider` (extracted from encoder) and `OpenAICompatibleEmbeddingProvider` (HTTP embedding via httpx) |
| `src/ate_rag_kb/embedding/encoder.py` | Refactored to delegate to provider selected by `embedding.provider` config; preserves all public methods and properties |
| `src/ate_rag_kb/retrieval/reranker_providers.py` | New file: `LocalRerankerProvider` (extracted from reranker) and `HttpRerankerProvider` (HTTP rerank via SiliconFlow-style API) |
| `src/ate_rag_kb/retrieval/reranker.py` | Refactored to delegate to provider selected by `retrieval.reranker.provider` config; preserves public rerank interface |
| `src/ate_rag_kb/retrieval/pipeline.py` | Conditionally create `Reranker` only when `reranker.enabled=true`; guard all reranker access with null checks |
| `src/ate_rag_kb/retrieval/planner.py` | Merge nested `if` into single compound `if` (SIM102 ruff fix) |
| `scripts/package_qdrant_snapshot.py` | New script: create/download and upload/restore Qdrant collection snapshots via HTTP API. Restore uses POST multipart upload with `snapshot` field, `wait=true`, and configurable `priority` parameter (default: `snapshot`, choices: `snapshot`, `replica`, `no_sync`). CLI exposes `--priority` flag. |
| `scripts/package_models.py` | New script: stage model caches with symlink resolution, small weight file rejection, manifest generation with cache-relative paths |
| `scripts/verify_models.py` | New script: structure-only and manifest integrity verification for offline model caches |
| `tests/test_utils_config.py` | Add 4 config-level tests for embedding and reranker model name env-var expansion (override + default each) |
| `tests/test_vector_store_client.py` | Update local mode tests to expect `RuntimeError`; convert rebuild/dense-only tests to use `__new__` bypass with in-memory client |
| `tests/test_embedding_encoder.py` | Update for provider-based architecture; add `TestOpenAICompatibleProvider` tests (success, missing key, HTTP error, dimension mismatch, batching); add `test_model_name_env_override` provider-level test |
| `tests/test_retrieval_reranker.py` | Update patch targets for provider architecture; add `TestHttpRerankerProvider` tests (success, missing key, HTTP error, partial results, disabled flag, unknown provider); add `test_model_name_env_override` provider-level test |
| `tests/test_snapshot_tooling.py` | New test file: 8 tests — create/download, restore with POST multipart + `priority=snapshot` default, custom priority (`replica`), invalid priority raises `ValueError`, filename/content-type validation, missing file, HTTP error |
| `tests/test_model_packaging.py` | New test file: staging, exclusion patterns, symlink resolution, broken symlinks, manifest creation, structure verification, manifest hash verification, and end-to-end regression test (`stage_models -> create_manifest -> verify_manifest`) |
| `README.md` | Replace local mode docs with cloud API setup; snapshot restore uses POST multipart with `--priority` flag; model names switchable via `ATE_KB_EMBEDDING_MODEL` / `ATE_KB_RERANKER_MODEL`; all three switch points (base URL, model, API key env) documented |
| `README_CN.md` | Chinese translation of the same updates |
| `docs/beta_checklist.md` | Replace `data/qdrant_storage/` existence check with Qdrant server running check |
| `docs/beta_checklist_CN.md` | Same fix in Chinese |
| `docs/agent_e2e_validation.md` | Remove `use_local: false` reference; update `portalocker` troubleshooting row to state local mode is deprecated |
| `docs/agent_e2e_validation_CN.md` | Same fixes in Chinese |
| `docs/agent_integration.md` | Replace "Local Mode (Not Recommended)" section with "Local Mode (Deprecated)" — clearly states it raises `RuntimeError` |

## Verification

| Command | Result | Notes |
|---|---|---|
| `uv run pytest tests/test_snapshot_tooling.py -v` | `pass` | 8/8 passed — restore asserts POST multipart, `snapshot` field, `wait=true`, `priority=snapshot` default, custom priority, invalid priority raises, filename, content type |
| `uv run pytest tests/test_embedding_encoder.py tests/test_retrieval_reranker.py tests/test_retrieval_pipeline.py tests/test_vector_store_client.py -q` | `pass` | 71 tests passed (includes 2 new env-override provider tests) |
| `uv run pytest tests/test_model_packaging.py tests/test_snapshot_tooling.py -q` | `pass` | 26 tests passed |
| `uv run pytest tests/ -q` | `pass` | 581 passed, 0 failed, 28 warnings (pre-existing) |
| `uv run ruff check src/ tests/ scripts/` | `pass` | All checks passed |
| `uv run python scripts/verify_models.py --skip-load` | `pass` | Structure OK, manifest OK (no manifest file present, which is expected for the dev cache) |
| `uv run python scripts/validate_agent_routing_policy.py` | `pass` | Agent routing policy helpers are valid |

## Codex Review Round Fixes

### Blocking Finding 1: Snapshot Restore Priority

**Requirement:** Restore/upload must use snapshot priority when supported by the endpoint.

**Fix applied:**

- `scripts/package_qdrant_snapshot.py::restore_snapshot()` now accepts a `priority` parameter (default: `"snapshot"`, choices: `"snapshot"`, `"replica"`, `"no_sync"`).
- The upload request includes both `wait=true` and `priority=<value>` in query params.
- CLI `restore` subcommand exposes `--priority` with the same choices.
- Invalid priority values raise `ValueError` before any HTTP call.
- `README.md` and `README_CN.md` show both direct `curl` restore examples with
  `priority=snapshot` and script restore examples with the `--priority` flag.

**Tests added/updated:**

- `test_restore_uses_post_multipart` — now asserts `params["priority"] == "snapshot"` alongside `params["wait"] == "true"`.
- `test_restore_with_custom_priority` — calls `restore_snapshot(..., priority="replica")` and asserts `params["priority"] == "replica"`.
- `test_restore_invalid_priority_raises` — calls with `priority="invalid"` and asserts `ValueError`.
- No CLI-level parsing test was added (no existing CLI test pattern in this file). Function-level tests cover the behavior.

### Blocking Finding 2: Model Names Environment-Switchable

**Requirement:** Users must switch base URL, model name, and API key env var without code edits.

**Fix applied:**

- `configs/config.yaml` changed:
  - `embedding.model_name`: `"BAAI/bge-m3"` → `"${ATE_KB_EMBEDDING_MODEL:-BAAI/bge-m3}"`
  - `retrieval.reranker.model_name`: `"BAAI/bge-reranker-v2-m3"` → `"${ATE_KB_RERANKER_MODEL:-BAAI/bge-reranker-v2-m3}"`
- The existing `Config._expand_env_vars` already supports `${VAR:-default}` syntax — no code changes needed.
- `README.md` and `README_CN.md` now document all three switch points:
  - `ATE_KB_EMBEDDING_BASE_URL` / `ATE_KB_RERANKER_BASE_URL`
  - `ATE_KB_EMBEDDING_MODEL` / `ATE_KB_RERANKER_MODEL`
  - `ATE_KB_EMBEDDING_API_KEY_ENV` / `ATE_KB_RERANKER_API_KEY_ENV`

**Tests added:**

- `test_utils_config.py` — 4 config-level tests:
  - `test_embedding_model_name_env_override` — sets `ATE_KB_EMBEDDING_MODEL` to `"vendor/custom-embedding"`, asserts config resolves correctly.
  - `test_embedding_model_name_default_when_no_env` — env unset, falls back to `"BAAI/bge-m3"`.
  - `test_reranker_model_name_env_override` — sets `ATE_KB_RERANKER_MODEL` to `"vendor/custom-reranker"`.
  - `test_reranker_model_name_default_when_no_env` — env unset, falls back to `"BAAI/bge-reranker-v2-m3"`.
- `test_embedding_encoder.py::test_model_name_env_override` — provider-level test: `EmbeddingEncoder(cfg).model_name == "vendor/custom-embedding"` with mocked `SentenceTransformer`.
- `test_retrieval_reranker.py::test_model_name_env_override` — provider-level test: `Reranker(cfg)._provider.model_name == "vendor/custom-reranker"` with mocked `CrossEncoder`.

## Codex Integration Review

Codex reviewed the implementation and report, then made two documentation-only
fixes before integration:

- Added `priority=snapshot` to the raw `curl` snapshot restore examples in
  `README.md` and `README_CN.md`, so direct Qdrant API usage matches the script
  behavior.
- Fixed an extra Markdown code-fence terminator in the English README cloud API
  section.

Codex reran all verification commands listed above after those fixes.

## Acceptance Criteria

- [x] `vector_store.mode: local` and legacy `vector_store.use_local: true` fail fast with a clear message; server mode continues to work as before.
- [x] No recommended docs or scripts instruct users to package or unpack raw `data/qdrant_storage/` or `data/qdrant_server/` directories as the vector DB artifact.
- [x] New Qdrant snapshot tooling can create/download and upload/restore snapshots through HTTP APIs, with mocked tests covering success and failure paths. `restore_snapshot()` uses POST multipart upload with `snapshot` field, `wait=true` query param, and configurable `priority` (default: `snapshot`); tests assert `mock_client.post` (not `put`) and verify multipart field structure and priority param.
- [x] Model packaging rejects unresolved symlinks and suspiciously small weight files, writes a manifest, and verification catches manifest/hash problems.
- [x] `EmbeddingEncoder` supports `provider: local` and `provider: openai_compatible`; SiliconFlow `BAAI/bge-m3` is selectable via config/env vars without code edits. Model name is environment-switchable via `ATE_KB_EMBEDDING_MODEL`.
- [x] `Reranker` supports `provider: local` and an HTTP rerank provider; SiliconFlow `BAAI/bge-reranker-v2-m3` is selectable via config/env vars without code edits. Model name is environment-switchable via `ATE_KB_RERANKER_MODEL`.
- [x] `retrieval.reranker.enabled: false` prevents local reranker model loading and skips rerank work.
- [x] Tests do not call live external APIs and do not require real API keys.
- [x] `README.md`, `README_CN.md`, and affected validation docs explain the new Windows deployment flow and all three provider switch points (base URL, model name, API key env var).
- [x] ATE KB MCP-first instructions remain intact.

## Risks And Notes

- The `HttpRerankerProvider` assigns a score of `-1000.0` to documents not returned by the API. This ensures deterministic ordering but may cause unexpected behavior if all documents are missing. Tests cover partial results.
- The `OpenAICompatibleEmbeddingProvider` requires `schema.vector_size` in config to report `vector_size` without making an API call. If unset, accessing `vector_size` raises `ValueError`.
- The snapshot tooling has been tested with mocked HTTP responses but not against a live Qdrant server in this session. The script follows Qdrant's documented HTTP API.
- Model packaging scripts (`package_models.py`, `verify_models.py`) were tested with synthetic fake caches plus an end-to-end regression test (`stage_models -> create_manifest -> verify_manifest`), not real model directories.
- The `_resolve_device` helper was duplicated into both `LocalEmbeddingProvider` and `LocalRerankerProvider`. This is acceptable for now but could be extracted into a shared utility if more providers are added.
- No real `dist/` archives were generated. The report includes the exact commands for local regeneration.
- Manifest paths are cache-root-relative (e.g., `models--BAAI--bge-m3/snapshots/...`) so they resolve correctly with both `package_models.py` staging and `verify_models.py` `cache_dir / path` resolution.
- Pre-existing ruff violations (I001 import sort, UP037 quoted annotations, UP035 `typing.Callable`, SIM102 nested-if in `planner.py`) were fixed in an earlier pass. All clean now.
- No CLI-level parsing test for `--priority` was added (no existing CLI test pattern in `test_snapshot_tooling.py`). Function-level tests with `restore_snapshot(..., priority=...)` cover the behavior fully.

## Skipped Checks

- No checks skipped. All required verification commands passed.

## Model Package Regeneration Commands

Per the task package, users should run locally:

```bash
uv run python scripts/package_models.py --output dist --name ate-kb-model-cache --format zip
uv run python scripts/verify_models.py
```

## Recommended Next Action

`Commit and merge to main`
