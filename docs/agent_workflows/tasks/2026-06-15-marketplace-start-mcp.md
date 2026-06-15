# Codex Task Package

## Status

`ready_for_claude`

## Owner Handoff

- Planner and reviewer: Codex
- Implementer: Claude Code
- Integration owner: Codex

## Branch

`codex/http-rerank-input-optimization`

Use the current branch. Do not create an unrelated branch unless Codex requests
it during review.

## Objective

Remove the ambiguity between local checkout setup and marketplace plugin
installation, and add a marketplace-safe MCP startup wrapper.

The final install story must be:

1. Local checkout setup configures agents to this checkout.
2. Marketplace/plugin setup clones the plugin to the tool cache and runs MCP
   from that plugin root.
3. `scripts/start_mcp.py` is the stable MCP entrypoint for both paths.

## Context

The current README flow asks users to clone the repository, run `uv sync`, start
Qdrant, ingest documents, and then install the marketplace plugin. That can
mislead engineers into thinking the marketplace clone automatically maps back
to the manually prepared checkout. It does not.

The tracked plugin-root `.mcp.json` currently launches
`ate_rag_kb.cli.main mcp` directly with `${CLAUDE_PLUGIN_ROOT}`. That registers
MCP automatically, but it gives us no controlled place to resolve a separate
project root, normalize environment variables, or bring up Qdrant for plugin
cache installs.

## Scope

Allowed changes:

- `scripts/start_mcp.py`
- `scripts/install_mcp.py`
- `scripts/validate_plugin_install.py`
- `.mcp.json`
- `.mcp.example.json`
- plugin manifests and marketplace docs when needed
- `README.md`
- `README_CN.md`
- `docs/PLUGIN_INSTALL.md`
- `docs/PLUGIN_INSTALL_CN.md`
- focused tests for plugin install and startup behavior
- this task package and matching completion report

## Out Of Scope

- Do not change retrieval, ingestion, reranking, or MCP tool semantics.
- Do not ingest documents, download model caches, or modify generated Qdrant
  data.
- Do not put secrets or API keys into tracked MCP/plugin JSON.
- Do not remove the ATE KB MCP-first policy from `AGENTS.md`, `CLAUDE.md`, or
  related agent instructions.

## Implementation Requirements

1. Read `AGENTS.md`, `CLAUDE.md`, and this task package before editing.
2. Add tests before implementing `scripts/start_mcp.py`.
3. Implement `scripts/start_mcp.py` as the stdio MCP startup wrapper:
   - Resolve project root from `ATE_RAG_KB_PROJECT_ROOT`, then
     `CLAUDE_PLUGIN_ROOT`, then the script location.
   - Set default `CONFIG_PATH` to `<project-root>/configs/config.yaml` when not
     provided.
   - Preserve inherited environment variables, especially API-key env vars.
   - Default query/reranker device env vars to CPU when absent.
   - Execute `uv run --project <project-root> -m ate_rag_kb.cli.main mcp`.
   - Support Qdrant Docker bootstrap when `ATE_KB_AUTO_BOOTSTRAP` is enabled.
4. Update plugin-root `.mcp.json`, `.mcp.example.json`, and
   `scripts/install_mcp.py` so marketplace installs, git plugin installs, and
   local checkout installs all invoke `scripts/start_mcp.py`.
5. Update English and Chinese docs to clearly separate:
   - local checkout deployment,
   - marketplace plugin cache deployment,
   - explicit override to point the plugin wrapper at an existing local
     checkout.
6. Document that `uv run` performs dependency environment setup at startup, and
   that `start_mcp.py` handles Qdrant startup when configured, but authorized
   source docs, model cache/cloud credentials, and ingestion remain deployment
   prerequisites.
7. Keep marketplace/plugin install commands aligned with the new wrapper logic.

## Acceptance Criteria

- [ ] `scripts/start_mcp.py` exists, is tested, and has no import-time side
      effects.
- [ ] `.mcp.json` uses `${CLAUDE_PLUGIN_ROOT}/scripts/start_mcp.py`.
- [ ] `scripts/install_mcp.py` uses `scripts/start_mcp.py` for local checkout
      agent configuration.
- [ ] `.mcp.example.json` matches the wrapper-based manual configuration.
- [ ] README English and Chinese versions explain the two install paths without
      implying that a prior local clone is mapped to a marketplace install.
- [ ] `docs/PLUGIN_INSTALL.md` and `docs/PLUGIN_INSTALL_CN.md` match the new
      marketplace startup behavior.
- [ ] Plugin validation and focused tests pass.
- [ ] A completion report is written under the expected report path.

## Required Verification Commands

```bash
uv run pytest tests/test_plugin_install.py tests/test_start_mcp.py -q
uv run python scripts/validate_plugin_install.py
uv run ruff check scripts/start_mcp.py scripts/install_mcp.py scripts/validate_plugin_install.py tests/test_start_mcp.py tests/test_plugin_install.py
python3 /Users/walter_luo/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py /Users/walter_luo/Project/ate-rag-kb
```

## Expected Report Path

```text
docs/agent_workflows/reports/2026-06-15-marketplace-start-mcp.md
```
