# Codex Task Package

## Status

`codex_verified`

## Owner Handoff

- Planner and reviewer: Codex
- Implementer: Claude Code
- Integration owner: Codex

## Branch

`codex/cloud-api-qdrant-packaging`

Codex has already created this branch from `main`. If it is not visible in the
Claude Code session, create it from `main` before editing:

```bash
git switch main
git switch -c codex/cloud-api-qdrant-packaging
```

Do not use the fallback branch `cloud-api-qdrant-packaging`; it was created only
while resolving local branch-prefix tooling.

## Objective

Make Windows/business-laptop deployment reliable by removing Qdrant embedded
local storage from supported runtime paths, replacing raw Qdrant directory
distribution with snapshot-based packaging, fixing offline model archive
integrity, and adding configurable cloud API providers for `BAAI/bge-m3`
embedding and `BAAI/bge-reranker-v2-m3` reranking with support for switching to
other vendors.

## Context

The current project defaults to Qdrant server mode in
`configs/config.yaml`, but `src/ate_rag_kb/vector_store/qdrant_client.py` still
supports `vector_store.mode: local` and `vector_store.use_local: true`, which
opens `data/qdrant_storage` through `QdrantClient(path=...)`. This is not viable
for the user's Windows 11 business laptop because `qdrant_storage` is about
3.5 GB, embedded loading can hang, and local mode is single-process only.

The existing `dist/ate-rag-kb-vector-data.tar.gz` contains raw Qdrant storage
directories. Raw Qdrant file trees are not a safe distribution format and can
produce missing `bitmask.dat` or gridstore page mismatch errors after unpacking.
Distribution must use Qdrant collection snapshots instead.

The current `dist/ate-kb-model-cache.zip` has invalid Hugging Face snapshot
weight files in at least one observed package: files such as `model.safetensors`
or `pytorch_model.bin` were only tens of bytes, consistent with unresolved cache
symlinks or pointer-like files. `scripts/package_models.py` already tries to
resolve symlinks, but it needs stronger verification so bad archives cannot be
published.

Runtime CPU inference is too slow on the Windows target. Add API-provider
support so the default local models can be replaced by free cloud APIs such as
SiliconFlow while keeping the provider interface configurable for other vendors.
Do not hard-code API keys. Use environment variables.

Preserve the repository's ATE KB MCP-first policy in `AGENTS.md`, `CLAUDE.md`,
and generated agent policy content.

## Scope

- Disable supported use of Qdrant local file mode (`data/qdrant_storage`) for
  normal runtime.
- Add Qdrant snapshot export/import tooling and documentation; remove raw
  Qdrant directory archives from the recommended packaging path.
- Harden offline model packaging and verification so generated model cache zips
  contain real weight files and fail fast on unresolved symlink/pointer files.
- Add configurable embedding provider support:
  - Local sentence-transformers provider remains available for developer
    machines.
  - OpenAI-compatible HTTP embedding provider supports SiliconFlow by
    configuration.
  - Users can switch base URL, model name, and API key env var without code
    edits.
- Add configurable reranker provider support:
  - Local `CrossEncoder` provider remains available for developer machines.
  - HTTP rerank provider supports SiliconFlow-style `/v1/rerank`.
  - Users can switch base URL, model name, API key env var, timeout, and top-N
    behavior without code edits.
- Ensure provider changes are covered by mocked unit tests. Do not call live
  external APIs in tests.
- Update Chinese and English docs for Windows deployment, cloud API setup,
  snapshot packaging, and model package regeneration.

## Out Of Scope

- Do not commit generated `dist/` archives, Qdrant data directories, model cache
  contents, raw ATE documents, or converted proprietary documentation.
- Do not remove the ability to use local sentence-transformers on development
  machines; only stop recommending or supporting Qdrant embedded local storage.
- Do not change chunking strategy, retrieval routing semantics, ATE KB MCP tool
  schemas, or citation behavior except where necessary for provider status
  reporting.
- Do not introduce a hard dependency on a single cloud vendor.
- Do not send real API keys, proprietary ATE content, or test documents to an
  external service in automated tests.
- Do not commit, merge, push, or open a PR from Claude Code. Codex will review,
  commit, and merge after verification passes.

## Implementation Requirements

- Follow `CLAUDE.md` and `AGENTS.md`.
- Preserve the ATE KB MCP-first policy.
- Create or switch to `codex/cloud-api-qdrant-packaging` before editing.
- Do not revert unrelated user changes.
- Prefer existing project patterns and local helper APIs.
- Keep changes scoped to this task.

### Qdrant Runtime Mode

- Modify `src/ate_rag_kb/vector_store/qdrant_client.py` so `mode == "local"` or
  legacy `use_local == true` raises a clear `ValueError` or `RuntimeError`
  before touching `data/qdrant_storage`.
- The error message must tell users to use server mode and Qdrant snapshots, not
  raw storage directories.
- Keep server mode behavior unchanged:
  - Prefer `vector_store.url` when present.
  - Fall back to `host` / `port`.
  - Preserve localhost `NO_PROXY` behavior.
- Update tests that currently expect local mode, if any. Add focused tests that
  assert local mode and legacy `use_local` fail with the new message.

### Qdrant Snapshot Tooling

- Add a script such as `scripts/package_qdrant_snapshot.py` with subcommands or
  flags for:
  - Creating and downloading a collection snapshot from a running Qdrant server.
  - Uploading/restoring a snapshot to a running Qdrant server.
- Use HTTP APIs through `httpx`, not raw filesystem copies.
- Defaults:
  - URL: `http://localhost:6333`
  - Collection: `ate_kb`
  - Output directory: `dist`
  - Snapshot filename: use the server-returned snapshot name unless the user
    passes an explicit output filename.
- Restore/upload must use snapshot priority when supported by the endpoint.
- Script must have deterministic exit codes:
  - `0` on success.
  - Non-zero with a clear stderr/logging message on HTTP failure, missing file,
    or malformed response.
- Add mocked tests for create/download and upload/restore behavior. Do not start
  Docker in tests.
- Update docs to say `data/qdrant_server/` is runtime state, not a distribution
  artifact. The supported vector DB distribution artifact is a Qdrant snapshot.

### Model Packaging

- Harden `scripts/package_models.py`:
  - Continue resolving symlinks to real files.
  - Exclude `.locks`, `.no_exist`, `refs`, `.DS_Store`, `CACHEDIR.TAG`, and
    Python cache files from the staged archive.
  - After staging, scan model snapshots for unresolved symlinks.
  - After staging, reject suspicious weight files:
    - Names ending in `.safetensors` or `.bin` must be regular files.
    - Files below a conservative threshold such as 10 MiB must fail packaging
      unless they are explicitly known non-weight files.
  - Emit a manifest file in the archive, for example
    `embeddings/cache/ate_kb_model_manifest.json`, containing model names,
    snapshot paths, file sizes, and SHA-256 hashes for large weight files.
- Harden `scripts/verify_models.py`:
  - Add a structure-only integrity check for missing snapshots, unresolved
    symlinks, and suspiciously small weight files.
  - Verify the optional manifest if present.
  - Keep `--skip-load` behavior, but make it meaningful by checking the archive
    structure without importing heavy ML libraries.
- Add unit tests for packaging helpers using small temporary fake caches. Tests
  should assert:
  - Real symlink targets are copied as regular files.
  - Small fake weight files are rejected.
  - `.no_exist`, `.locks`, `refs`, and `.DS_Store` do not appear in staged
    output.
  - Manifest verification fails when a file hash changes.
- Do not regenerate or commit the real `dist/ate-kb-model-cache.zip`. The report
  should include the exact command the user should run locally:

```bash
uv run python scripts/package_models.py --output dist --name ate-kb-model-cache --format zip
uv run python scripts/verify_models.py
```

### Embedding Provider API

- Refactor `src/ate_rag_kb/embedding/encoder.py` so `EmbeddingEncoder` delegates
  actual embedding work to a provider selected by config.
- Preserve the existing public methods and properties:
  - `encode(texts, batch_size=None)`
  - `encode_query(query)`
  - `encode_documents(documents)`
  - `vector_size`
  - `model_name`
  - `device` for local provider compatibility
- Add a local provider that wraps the current `SentenceTransformer` behavior.
- Add an OpenAI-compatible HTTP provider using `httpx`:
  - POST `{base_url}/embeddings`
  - Request JSON: `{"model": model_name, "input": texts}`
  - Authorization: `Bearer <api_key>`
  - Parse `data[*].embedding`
  - Preserve input order.
  - Return `numpy.ndarray`.
  - Validate the returned embedding dimension when `schema.vector_size` is set.
- Suggested config shape:

```yaml
embedding:
  provider: "${ATE_KB_EMBEDDING_PROVIDER:-local}"
  model_name: "${ATE_KB_EMBEDDING_MODEL:-BAAI/bge-m3}"
  device: "${ATE_KB_QUERY_DEVICE:-cpu}"
  ingest_device: "${ATE_KB_INGEST_DEVICE:-auto}"
  normalize_embeddings: true
  batch_size: 8
  max_seq_length: 512
  cache_dir: "${ATE_KB_MODEL_CACHE:-./embeddings/cache}"
  local_files_only: true
  query_instruction: "Represent this sentence for searching relevant passages: "
  api:
    base_url: "${ATE_KB_EMBEDDING_BASE_URL:-https://api.siliconflow.cn/v1}"
    api_key_env: "${ATE_KB_EMBEDDING_API_KEY_ENV:-SILICONFLOW_API_KEY}"
    timeout_seconds: 60
```

- `provider: local` must behave as before.
- `provider: openai_compatible` must use the HTTP provider.
- Missing API key must fail with a clear error naming the expected env var.
- Do not log API keys or request payload content.
- Add mocked tests for success, missing API key, HTTP error, malformed response,
  batch behavior, and vector dimension mismatch.

### Reranker Provider API

- Refactor `src/ate_rag_kb/retrieval/reranker.py` so `Reranker` delegates scoring
  to a provider selected by config.
- Preserve the public `rerank(query, chunks, top_k=None, is_broad_concept=False)`
  behavior and diversity logic after scoring.
- Add a local provider that wraps the current `CrossEncoder` behavior.
- Add an HTTP rerank provider for SiliconFlow-style APIs:
  - POST `{base_url}/rerank`
  - Request JSON:

```json
{
  "model": "BAAI/bge-reranker-v2-m3",
  "query": "question text",
  "documents": ["candidate chunk text"],
  "top_n": 20,
  "return_documents": false
}
```

  - Authorization: `Bearer <api_key>`
  - Parse scores from `results[*].relevance_score` with `results[*].index`
    mapping back to the input document list.
  - If a provider returns fewer than all documents, assign missing documents a
    very low score so ordering remains deterministic.
- Suggested config shape:

```yaml
retrieval:
  reranker:
    enabled: true
    provider: "${ATE_KB_RERANKER_PROVIDER:-local}"
    model_name: "${ATE_KB_RERANKER_MODEL:-BAAI/bge-reranker-v2-m3}"
    top_k: 5
    batch_size: 4
    device: "${ATE_KB_RERANKER_DEVICE:-cpu}"
    api:
      base_url: "${ATE_KB_RERANKER_BASE_URL:-https://api.siliconflow.cn/v1}"
      api_key_env: "${ATE_KB_RERANKER_API_KEY_ENV:-SILICONFLOW_API_KEY}"
      timeout_seconds: 60
      top_n: 40
```

- Make `retrieval.reranker.enabled: false` actually skip local model creation and
  reranking in `RetrievalPipeline`. Today the pipeline constructs `Reranker`
  unconditionally, so changing YAML alone may not avoid CPU cost.
- MCP `retrieve` and `ask` paths must respect the effective reranker-enabled
  setting unless the request explicitly opts into reranking and the provider is
  configured.
- Add mocked tests for provider scoring, missing API key, partial score results,
  HTTP failure, disabled reranker avoiding local model construction, and existing
  broad-concept diversity behavior.

### Documentation

- Update `README.md` and `README_CN.md`:
  - Server mode is the only supported Windows/business-laptop Qdrant mode.
  - `data/qdrant_storage/` local mode is deprecated/unsupported.
  - Use Qdrant snapshots for vector DB transfer.
  - Do not copy raw Qdrant storage directories.
  - Show model package regeneration and verification commands.
  - Show SiliconFlow/free cloud API example for `BAAI/bge-m3` and
    `BAAI/bge-reranker-v2-m3`.
  - Show how to switch to another vendor by changing `*_BASE_URL`,
    `*_MODEL`, and `*_API_KEY_ENV`.
- Update deployment validation docs if they still reference `qdrant_storage` as
  a beta prerequisite.
- Keep legal/distribution warnings: do not redistribute proprietary ATE docs or
  generated vector DB snapshots unless authorized.

## Acceptance Criteria

- [ ] `vector_store.mode: local` and legacy `vector_store.use_local: true` fail
      fast with a clear message; server mode continues to work as before.
- [ ] No recommended docs or scripts instruct users to package or unpack raw
      `data/qdrant_storage/` or `data/qdrant_server/` directories as the vector
      DB artifact.
- [ ] New Qdrant snapshot tooling can create/download and upload/restore
      snapshots through HTTP APIs, with mocked tests covering success and
      failure paths.
- [ ] Model packaging rejects unresolved symlinks and suspiciously small weight
      files, writes a manifest, and verification catches manifest/hash problems.
- [ ] `EmbeddingEncoder` supports `provider: local` and
      `provider: openai_compatible`; SiliconFlow `BAAI/bge-m3` is selectable via
      config/env vars without code edits.
- [ ] `Reranker` supports `provider: local` and an HTTP rerank provider;
      SiliconFlow `BAAI/bge-reranker-v2-m3` is selectable via config/env vars
      without code edits.
- [ ] `retrieval.reranker.enabled: false` prevents local reranker model loading
      and skips rerank work.
- [ ] Tests do not call live external APIs and do not require real API keys.
- [ ] `README.md`, `README_CN.md`, and affected validation docs explain the new
      Windows deployment flow.
- [ ] ATE KB MCP-first instructions remain intact.

## Required Verification

Run these commands and include results in the completion report:

```bash
uv run pytest tests/test_embedding_encoder.py tests/test_retrieval_reranker.py tests/test_retrieval_pipeline.py tests/test_vector_store_client.py -q
uv run pytest tests/ -q
uv run python scripts/verify_models.py --skip-load
uv run python scripts/validate_agent_routing_policy.py
```

If a command cannot be run, explain the exact reason in the report. Do not
substitute a live cloud API call for mocked unit tests.

## Changes Requested After Codex Review

Codex review remains `changes_requested`. The previous round fixed the README
restore verb, local-Qdrant documentation, tests, and ruff issues, but two
blocking acceptance gaps remain.

Claude Code must address only the items in this section, update the existing
completion report, and rerun the required verification commands. Do not commit,
merge, push, or open a PR.

### Blocking Finding 1: Qdrant Snapshot Restore Priority

The original task package requires:

> Restore/upload must use snapshot priority when supported by the endpoint.

Current issue:

- `scripts/package_qdrant_snapshot.py::restore_snapshot()` uploads snapshots
  without a `priority` parameter.
- The restore CLI has no `--priority` option.

Required fix:

- Add a `priority` parameter to `restore_snapshot()`.
- Default to `priority="snapshot"`.
- Allow CLI override with choices:
  - `snapshot`
  - `replica`
  - `no_sync`
- Include the selected priority in the upload request query params. The default
  call should produce params equivalent to:

```python
{"wait": "true", "priority": "snapshot"}
```

- Keep existing POST multipart upload behavior unchanged.
- Keep existing `wait=true` behavior unchanged.
- Update restore usage examples in docs if they show the script restore command.

Required tests:

- Update `tests/test_snapshot_tooling.py::test_restore_uses_post_multipart` or
  an equivalent restore test to assert:

```python
assert call_kwargs["params"]["wait"] == "true"
assert call_kwargs["params"]["priority"] == "snapshot"
```

- Add or update a test that calls `restore_snapshot(..., priority="replica")`
  and asserts the HTTP params contain `"priority": "replica"`.
- Add or update a CLI-level test, if CLI parsing is already covered in this
  test file, proving `--priority no_sync` reaches `restore_snapshot()`. If there
  is no CLI-level test pattern yet, a focused function-level test is acceptable,
  but the completion report must state this choice.

### Blocking Finding 2: Model Names Must Be Environment-Switchable

The original task package requires users to switch base URL, model name, and API
key env var without code edits.

Current issue:

- `configs/config.yaml` still has fixed:

```yaml
embedding:
  model_name: "BAAI/bge-m3"
```

- `configs/config.yaml` still has fixed:

```yaml
retrieval:
  reranker:
    model_name: "BAAI/bge-reranker-v2-m3"
```

Required fix:

- Change the embedding model config to:

```yaml
embedding:
  model_name: "${ATE_KB_EMBEDDING_MODEL:-BAAI/bge-m3}"
```

- Change the reranker model config to:

```yaml
retrieval:
  reranker:
    model_name: "${ATE_KB_RERANKER_MODEL:-BAAI/bge-reranker-v2-m3}"
```

- Ensure docs showing provider switching mention all three switch points:
  - `ATE_KB_EMBEDDING_BASE_URL` / `ATE_KB_RERANKER_BASE_URL`
  - `ATE_KB_EMBEDDING_MODEL` / `ATE_KB_RERANKER_MODEL`
  - `ATE_KB_EMBEDDING_API_KEY_ENV` / `ATE_KB_RERANKER_API_KEY_ENV`

Required tests:

- Add or update a config/provider test proving:

```python
monkeypatch.setenv("ATE_KB_EMBEDDING_MODEL", "vendor/custom-embedding")
cfg = Config({"embedding": {"model_name": "${ATE_KB_EMBEDDING_MODEL:-BAAI/bge-m3}"}})
assert cfg.get("embedding.model_name") == "vendor/custom-embedding"
```

- Add or update a config/provider test proving:

```python
monkeypatch.setenv("ATE_KB_RERANKER_MODEL", "vendor/custom-reranker")
cfg = Config(
    {
        "retrieval": {
            "reranker": {
                "model_name": "${ATE_KB_RERANKER_MODEL:-BAAI/bge-reranker-v2-m3}"
            }
        }
    }
)
assert cfg.get("retrieval.reranker.model_name") == "vendor/custom-reranker"
```

- Add provider-level assertions when practical:
  - `EmbeddingEncoder(cfg).model_name` reflects the expanded embedding model.
  - `Reranker(cfg).model_name` reflects the expanded reranker model.
  - Use local provider mocks or disabled-provider construction patterns so tests
    do not load real models or call external APIs.

### Verification To Rerun

After implementing the two fixes, rerun and report:

```bash
uv run pytest tests/test_snapshot_tooling.py -v
uv run pytest tests/test_embedding_encoder.py tests/test_retrieval_reranker.py tests/test_retrieval_pipeline.py tests/test_vector_store_client.py -q
uv run pytest tests/test_model_packaging.py tests/test_snapshot_tooling.py -q
uv run pytest tests/ -q
uv run ruff check src/ tests/ scripts/
uv run python scripts/verify_models.py --skip-load
uv run python scripts/validate_agent_routing_policy.py
```

If a command cannot be run, explain the exact reason in the completion report.

### Report Update

Update:

```text
docs/agent_workflows/reports/2026-06-11-cloud-api-qdrant-packaging.md
```

The updated report must mention:

- The snapshot restore default priority and CLI override.
- The two model-name env var config changes.
- Tests added or updated for both acceptance gaps.
- Full verification results.

## Expected Report

Write the report to:

```text
docs/agent_workflows/reports/2026-06-11-cloud-api-qdrant-packaging.md
```

Use `docs/agent_workflows/templates/claude_report.md` as the report structure.
The report must include:

- Branch name.
- Summary of changed behavior.
- Changed files table.
- Verification commands and outcomes.
- Acceptance criteria checklist.
- Any skipped checks with exact reasons.
- Recommended next action: `Codex review`.

## Integration Instructions For Codex

After Claude Code reports completion, Codex must:

1. Confirm current branch is `codex/cloud-api-qdrant-packaging`.
2. Review the diff and report; do not treat the report alone as proof.
3. Run or inspect required checks.
4. Confirm no generated archives, model caches, Qdrant storage directories, raw
   ATE docs, or unrelated user changes are included.
5. Commit only approved files.
6. Merge to `main` only after review and tests pass.
