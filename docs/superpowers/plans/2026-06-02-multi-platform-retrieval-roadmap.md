# Multi-Platform Retrieval Coordinator Roadmap

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver isolated, complete retrieval for Teradyne J750 / IG-XL and Advantest V93000 / SMT7, while preserving a clear migration path for V93000 / SMT8.

**Architecture:** Normalize document metadata first, repair IG-XL document relationships and generated symbol ownership, then route every search, retrieve, and ask request through one scope-aware coordinator. Finish with a clean rebuild and live MCP acceptance run.

**Tech Stack:** Python 3.11, Pydantic, Qdrant, pytest, YAML configuration, MCP tools

---

## Source Of Truth

Implement against the approved design:

- `docs/superpowers/specs/2026-06-02-multi-platform-retrieval-coordinator-design.md`

Use these canonical identities throughout the implementation:

| Vendor | Platform | Software | Current state |
|---|---|---|---|
| `teradyne` | `j750` | `igxl` | Enabled |
| `advantest` | `v93000` | `smt7` | Enabled |
| `advantest` | `v93000` | `smt8` | Reserved for later enablement |

`platform` must never contain `smt7`, `smt8`, or `igxl`. Those values belong in `software`.

## Implementation Order

Execute these plans in order:

1. `docs/superpowers/plans/2026-06-02-metadata-graph-foundation.md`
2. `docs/superpowers/plans/2026-06-02-retrieval-coordinator-routing.md`
3. `docs/superpowers/plans/2026-06-02-multi-platform-acceptance-rollout.md`

Do not begin the clean production rebuild until the first two plans pass their targeted test suites.

## Worktree Rules

The repository already contains user changes. Preserve them.

- [ ] Run `git status --short` before editing and record the baseline in the session notes.
- [ ] Inspect every touched file before patching it.
- [ ] Stage only the exact files named by the completed task.
- [ ] Use `git diff --cached --stat` and `git diff --cached --check` before each commit.
- [ ] Do not revert unrelated modifications or stage the full repository with `git add -A`.

## Phase Gates

### Gate 1: Metadata And Graph Foundation

- [ ] Canonical metadata is written to chunk payloads.
- [ ] Qdrant indexes exist for `vendor`, `platform`, `software`, and `software_release`.
- [ ] IG-XL relative Markdown links resolve into document graph edges.
- [ ] The generated symbol catalog identifies `SelectFirst` as IG-XL-owned and `ON_FIRST_INVOCATION_BEGIN` as SMT7-owned.
- [ ] Run:

```bash
uv run pytest tests/domain tests/ingestion tests/test_chunking_models.py tests/test_document_scope.py tests/test_ingestion_pipeline.py tests/test_ingestion_incremental.py tests/vector_store -q
```

Expected: exit code `0`.

### Gate 2: Unified Coordinator

- [ ] MCP `search`, `retrieve`, and `ask` delegate to the same coordinator.
- [ ] Every retrieval branch applies its scope filter before dense search, sparse search, graph expansion, broad-context assembly, and compression.
- [ ] Explicit platform requests never return chunks from another platform.
- [ ] Neutral requests return two isolated answer sections while only IG-XL and SMT7 are enabled.
- [ ] Run:

```bash
uv run pytest tests/retrieval tests/mcp -q
```

Expected: exit code `0`.

### Gate 3: Clean Rebuild And Acceptance

- [ ] Rebuild the production collection from normalized metadata.
- [ ] Rebuild sparse vocabulary, document graph, and symbol catalog.
- [ ] Restart the MCP server so handlers load the rebuilt artifacts.
- [ ] Run:

```bash
uv run pytest -q
```

Expected: exit code `0`.

- [ ] Execute the live acceptance matrix from the rollout plan.

## Required User-Visible Behavior

| Query shape | Expected behavior |
|---|---|
| Explicit `IG-XL` or `J750` | Return only `J750 / IG-XL` |
| Explicit `SMT7` | Return only `V93000 / SMT7` |
| Explicit `V93000` with only SMT7 enabled | Return only `V93000 / SMT7` |
| Neutral question with IG-XL and SMT7 enabled | Return two isolated answer sections |
| Explicit request for two answers | Return two isolated answer sections |
| Neutral exclusive API such as `SelectFirst` | Route directly to owning software |
| `SMT7 SelectFirst 怎么用` | Explain mismatch and answer from IG-XL only |
| Future neutral query with SMT7 and SMT8 enabled | Ask whether the user wants `J750` or `V93000` |
| Future `V93000` query with SMT7 and SMT8 enabled | Ask whether the user wants `SMT7` or `SMT8` |
