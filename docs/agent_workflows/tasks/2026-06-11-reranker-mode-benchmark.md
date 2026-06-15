# Codex Task Package

## Status

`claude_working`

## Owner Handoff

- Planner and reviewer: Codex
- Implementer: Claude Code
- Integration owner: Codex

## Branch

`codex/reranker-mode-benchmark`

## Objective

Measure Site Control retrieval runtime after switching the reranker to:

1. Local GPU acceleration.
2. HTTP API reranking.

The output should make clear whether each mode completes successfully, how long
it takes, and which pipeline phase dominates runtime.

## Context

The current default reranker is local CPU:

```yaml
retrieval:
  reranker:
    provider: "${ATE_KB_RERANKER_PROVIDER:-local}"
    device: "${ATE_KB_RERANKER_DEVICE:-cpu}"
```

The performance report
`docs/agent_workflows/reports/2026-06-11-site-control-retrieval-timing.md`
identified Step 2 as the bottleneck because repeated `ate_kb.ask` calls each
run the full retrieval pipeline, including cross-encoder reranking.

Codex preflight on this machine found:

- `torch.cuda.is_available() == False`
- `torch.backends.mps.is_available() == True`
- `SILICONFLOW_API_KEY` is not set in the current Codex environment.
- MPS with current reranker batch size 4 failed in attention with
  `RuntimeError: Invalid buffer size: 16.00 GiB`.
- MPS with temporary reranker batch size 1 ran for more than 6 minutes without
  completing and was interrupted.
- HTTP provider setup reached `_get_api_key()` and failed before making the
  network request because `SILICONFLOW_API_KEY` was missing.

## Scope

Allowed changes:

- Add or update a focused benchmark script under `scripts/` if useful.
- Add the completion report under `docs/agent_workflows/reports/`.
- Add small documentation notes if needed to explain required environment
  variables or observed limitations.

## Out Of Scope

- Do not change ingestion data, vector store contents, generated processed data,
  or Qdrant snapshots.
- Do not commit API keys, tokens, `.env` files, or secret values.
- Do not permanently change default reranker provider/device unless explicitly
  requested after reviewing benchmark results.
- Do not merge, push, or open a pull request.

## Implementation Requirements

1. Read `AGENTS.md`, `CLAUDE.md` if present, and this task package before
   editing or running benchmarks.
2. Create or switch to branch `codex/reranker-mode-benchmark`.
3. Use the same query and comparable parameters for both modes:

   ```text
   ATE SMT7 中 Site Control 的作用是什么
   ```

   Recommended operation: `ate_kb.ask` equivalent with `top_k=15`,
   `include_context_package=true`, and filters for `v93000/smt7`.

4. For local GPU mode:
   - Use CUDA if available.
   - On this Mac, MPS is the only available local accelerator.
   - Record whether current batch size 4 succeeds.
   - If it fails, retry with reranker batch size 1 as a diagnostic and record
     the result separately from the default-config result.

5. For HTTP API mode:
   - Use `ATE_KB_RERANKER_PROVIDER=http`.
   - Use `SILICONFLOW_API_KEY` unless `ATE_KB_RERANKER_API_KEY_ENV` points to a
     different key variable.
   - If the key is unavailable, mark the HTTP runtime test as blocked and
     include the exact non-secret error.

6. Capture at minimum:
   - Wall-clock runtime.
   - `timing_total_ms`.
   - `timing_enriched_search_ms`.
   - `timing_graph_expansion_ms`.
   - `timing_reranking_ms`.
   - `timing_broad_context_ms`.
   - Whether the result set/citations are plausible.

## Acceptance Criteria

- [ ] GPU/local-accelerated reranker mode is tested or clearly reported as not
      runnable, with exact error or timeout evidence.
- [ ] HTTP API reranker mode is tested or clearly reported as blocked by missing
      credentials/network, with exact non-secret evidence.
- [ ] Results use the same query and comparable top-k/context settings.
- [ ] The report includes a concise recommendation on whether to use GPU, HTTP,
      or keep CPU until additional setup is done.
- [ ] No secrets are printed, committed, or stored in the repository.

## Required Verification Commands

```bash
uv run python -c 'import torch; print({"cuda": torch.cuda.is_available(), "mps": torch.backends.mps.is_available(), "mps_built": torch.backends.mps.is_built()})'

PYTORCH_ENABLE_MPS_FALLBACK=1 ATE_KB_RERANKER_PROVIDER=local ATE_KB_RERANKER_DEVICE=mps uv run python <benchmark-script> --top-k 15 --runs 1

ATE_KB_RERANKER_PROVIDER=http uv run python <benchmark-script> --top-k 15 --runs 1
```

If testing HTTP API with a configured key:

```bash
ATE_KB_RERANKER_PROVIDER=http SILICONFLOW_API_KEY=<set-in-shell-not-in-file> uv run python <benchmark-script> --top-k 15 --runs 1
```

## Expected Report Path

```text
docs/agent_workflows/reports/2026-06-11-reranker-mode-benchmark.md
```
