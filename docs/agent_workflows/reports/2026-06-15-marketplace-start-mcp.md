# Claude Code Completion Report

## Status

`codex_review`

## Task Package

`docs/agent_workflows/tasks/2026-06-15-marketplace-start-mcp.md`

## Branch

`codex/http-rerank-input-optimization`

## Summary

Added `scripts/start_mcp.py` as the shared MCP startup wrapper and updated local
checkout, marketplace, and manual MCP configuration paths to use it. The docs
now explicitly separate local checkout deployment from marketplace/plugin cache
deployment, so engineers do not expect a manually prepared clone to be reused by
marketplace install unless they explicitly point the wrapper at it.

## Changed Files

| File | Change |
|---|---|
| `scripts/start_mcp.py` | New MCP wrapper that resolves project root, builds runtime env, optionally starts Qdrant via Docker Compose, and execs the real MCP server. |
| `.mcp.json` | Marketplace/plugin MCP config now launches `scripts/start_mcp.py` from `${CLAUDE_PLUGIN_ROOT}` and enables Qdrant bootstrap. |
| `.mcp.example.json` | Manual MCP example now uses the wrapper and includes root/config/bootstrap env. |
| `scripts/install_mcp.py` | Local checkout installer now configures agents to call `scripts/start_mcp.py`. |
| `scripts/validate_plugin_install.py` | Validation now checks wrapper presence and wrapper-based MCP config shape. |
| `tests/test_start_mcp.py` | Added focused tests for root resolution, runtime env defaults, MCP command construction, and Qdrant bootstrap behavior. |
| `tests/test_plugin_install.py` | Updated plugin/local installer expectations for wrapper-based startup. |
| `README.md`, `README_CN.md` | Split local checkout and marketplace deployment paths; updated startup examples. |
| `CLAUDE.md` | Updated the default MCP startup command to use `scripts/start_mcp.py`. |
| `docs/PLUGIN_INSTALL.md`, `docs/PLUGIN_INSTALL_CN.md` | Reworked plugin install model and per-harness fallback examples. |
| `docs/agent_integration.md` | Updated agent MCP examples and troubleshooting to use the wrapper. |
| `docs/agent_e2e_validation.md`, `docs/agent_e2e_validation_CN.md` | Updated E2E MCP config and startup checks to use the wrapper. |
| `docs/agent_workflows/tasks/2026-06-15-marketplace-start-mcp.md` | Added task package for this workflow. |

## Verification

| Command | Result | Notes |
|---|---|---|
| `uv run pytest tests/test_plugin_install.py tests/test_start_mcp.py -q` | `pass` | `16 passed in 0.04s` |
| `uv run python scripts/validate_plugin_install.py` | `pass` | Plugin install assets valid. |
| `uv run ruff check scripts/start_mcp.py scripts/install_mcp.py scripts/validate_plugin_install.py tests/test_start_mcp.py tests/test_plugin_install.py` | `pass` | Ruff found no issues. |
| `python3 /Users/walter_luo/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py /Users/walter_luo/Project/ate-rag-kb` | `pass` | Plugin validation passed. |
| `uv run python scripts/validate_agent_routing_policy.py` | `pass` | Agent routing policy helpers valid. |

## Acceptance Criteria

- [x] `scripts/start_mcp.py` exists, is tested, and has no import-time side effects.
- [x] `.mcp.json` uses `${CLAUDE_PLUGIN_ROOT}/scripts/start_mcp.py`.
- [x] `scripts/install_mcp.py` uses `scripts/start_mcp.py` for local checkout agent configuration.
- [x] `.mcp.example.json` matches the wrapper-based manual configuration.
- [x] README English and Chinese versions explain the two install paths without implying that a prior local clone is mapped to a marketplace install.
- [x] `docs/PLUGIN_INSTALL.md` and `docs/PLUGIN_INSTALL_CN.md` match the new marketplace startup behavior.
- [x] Plugin validation and focused tests pass.
- [x] A completion report is written under the expected report path.

## Risks And Notes

- Marketplace/plugin install now auto-configures MCP startup, dependency
  environment creation through `uv run`, and Qdrant startup when Docker is
  available. It still cannot provide private ATE source documents, model cache,
  cloud API secrets, or ingestion data automatically.
- The plugin-root `.mcp.json` intentionally does not pin `CONFIG_PATH` or
  `ATE_RAG_KB_PROJECT_ROOT`; `start_mcp.py` derives them so an advanced
  environment override can point the plugin wrapper at a prepared checkout.

## Skipped Checks

No checks skipped.

## Recommended Next Action

`Codex review`
