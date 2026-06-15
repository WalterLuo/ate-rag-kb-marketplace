# ATE RAG KB — Multi-Harness Plugin Installation

This document describes how to install and configure **ate-rag-kb** as a plugin
or MCP extension in various AI CLI tools.

## Installation Model

There are two valid setup paths:

1. **Local checkout deployment:** clone the repo, prepare models/docs/Qdrant in
   that checkout, then run `scripts/install_mcp.py`. Agent settings point to
   that exact absolute path.
2. **Marketplace/plugin deployment:** the AI tool clones the plugin into its own
   plugin cache and reads the plugin-root `.mcp.json`. It starts from that cache
   by default and does not automatically reuse a separate manual clone.

The shared MCP entrypoint is `scripts/start_mcp.py`. `uv run` creates or reuses
the Python environment, and the wrapper starts Qdrant with Docker Compose when
`ATE_KB_AUTO_BOOTSTRAP=1`. Authorized source docs, model cache or cloud API
credentials, and ingestion are still deployment prerequisites.

## Local Checkout Setup

Use this after cloning and preparing the project:

```bash
uv run python scripts/install_mcp.py --install-agent-policy
```

Dry-run first to see what will change:

```bash
uv run python scripts/install_mcp.py --dry-run
```

Configure only specific harnesses:

```bash
uv run python scripts/install_mcp.py --harness claude,cursor
```

Only project-level configs (no global dotfiles):

```bash
uv run python scripts/install_mcp.py --project-only
```

Configure MCP only, without global agent policy:

```bash
uv run python scripts/install_mcp.py --skip-agent-policy
```

This is not recommended for Codex projectless sessions because the repository
`AGENTS.md` may not be loaded.

The generated MCP config runs:

```text
uv run --project /path/to/ate-rag-kb python /path/to/ate-rag-kb/scripts/start_mcp.py
```

with `ATE_RAG_KB_PROJECT_ROOT`, `CONFIG_PATH`, and
`ATE_KB_AUTO_BOOTSTRAP=1` in the server environment.

---

## Per-Harness Installation

### Claude Code

**Marketplace install (recommended):**

```bash
/plugin marketplace add WalterLuo/ate-rag-kb-marketplace
/plugin install ate-rag-kb@ate-rag-kb-marketplace
```

**Or install from this repo directly:**

```bash
/plugin install ate-rag-kb@git+https://github.com/WalterLuo/ate-rag-kb.git
```

Marketplace and git plugin installs include a plugin-root `.mcp.json` that
registers the `ate-kb` stdio MCP server automatically using
`${CLAUDE_PLUGIN_ROOT}/scripts/start_mcp.py`. Restart Claude Code after
installation, then run `/mcp` or ask an ATE question to verify the server is
visible.

If you already prepared a local checkout, do not expect the marketplace clone
to reuse it automatically. Prefer `uv run python scripts/install_mcp.py
--install-agent-policy`, or launch Claude Code with `ATE_RAG_KB_PROJECT_ROOT`
and optionally `ATE_RAG_KB_CONFIG_PATH` pointing at the prepared checkout.

**Manual MCP Configuration (fallback only):**

Use manual settings only if you are not installing the plugin. Claude Code also
supports MCP servers via `settings.json`; add:

```json
// ~/.claude/settings.json (global) or .claude/settings.json (project)
{
  "mcpServers": {
    "ate_kb": {
      "command": "uv",
      "args": [
        "run",
        "--project",
        "/path/to/ate-rag-kb",
        "python",
        "/path/to/ate-rag-kb/scripts/start_mcp.py"
      ],
      "env": {
        "ATE_RAG_KB_PROJECT_ROOT": "/path/to/ate-rag-kb",
        "CONFIG_PATH": "/path/to/ate-rag-kb/configs/config.yaml",
        "ATE_KB_AUTO_BOOTSTRAP": "1"
      }
    }
  }
}
```

**Verify:**

```
What V93000 timing set commands are available?
```

Claude Code should invoke `ate_kb.search` or `ate_kb.retrieve` automatically.

---

### Cursor

**Install from marketplace:**

```bash
/add-plugin ate-rag-kb
```

**Or search:**

Open Cursor Agent chat, search for "ate-rag-kb" in the plugin marketplace.

The Cursor plugin manifest also references `mcpServers: "./.mcp.json"` so
compatible plugin installs can load the same `ate-kb` MCP server automatically.

**Manual MCP Configuration (fallback only):**

If the Cursor plugin flow does not load MCP automatically, use `.cursor/mcp.json`
(project) or `~/.cursor/mcp.json` (global):

```json
{
  "mcpServers": {
    "ate_kb": {
      "command": "uv",
      "args": [
        "run",
        "--project",
        "/path/to/ate-rag-kb",
        "python",
        "/path/to/ate-rag-kb/scripts/start_mcp.py"
      ],
      "env": {
        "ATE_RAG_KB_PROJECT_ROOT": "/path/to/ate-rag-kb",
        "CONFIG_PATH": "/path/to/ate-rag-kb/configs/config.yaml",
        "ATE_KB_AUTO_BOOTSTRAP": "1"
      }
    }
  }
}
```

The `scripts/install_mcp.py` also configures this automatically for local
checkouts.

---

### Codex CLI / Codex App

**Install from marketplace:**

```bash
/plugins
# Search for "ate-rag-kb" and select Install Plugin.
```

For local or team marketplace testing, add this repository's Codex marketplace
manifest first, then search for `ate-rag-kb`:

```bash
codex plugin marketplace add /path/to/ate-rag-kb/.agents/plugins/marketplace.json
```

Public Codex marketplace search requires publishing or registering that
marketplace entry outside this repository.

Plugin installs include `mcpServers: "./.mcp.json"` and a portable root
`.mcp.json`, so compatible Codex plugin flows can load the `ate-kb` MCP server
without hand-editing `~/.codex/settings.json`.

**Manual MCP Configuration (fallback only):**

If you are not using the plugin flow, Codex also supports MCP servers. Add to
`~/.codex/settings.json`:

```json
{
  "mcpServers": {
    "ate_kb": {
      "command": "uv",
      "args": [
        "run",
        "--project",
        "/path/to/ate-rag-kb",
        "python",
        "/path/to/ate-rag-kb/scripts/start_mcp.py"
      ],
      "env": {
        "ATE_RAG_KB_PROJECT_ROOT": "/path/to/ate-rag-kb",
        "CONFIG_PATH": "/path/to/ate-rag-kb/configs/config.yaml",
        "ATE_KB_AUTO_BOOTSTRAP": "1"
      }
    }
  }
}
```

Or run `scripts/install_mcp.py --harness codex --install-agent-policy` for a
local checkout and managed routing policy.

After installation, restart Codex and run:

```bash
uv run python scripts/validate_plugin_install.py
uv run python scripts/validate_agent_routing_policy.py
```

---

### Gemini CLI

**Install the extension:**

```bash
gemini extensions install https://github.com/WalterLuo/ate-rag-kb.git
```

**Update later:**

```bash
gemini extensions update ate-rag-kb
```

Gemini CLI reads `gemini-extension.json` at the repo root, which points to
`GEMINI.md` as the context file. No additional MCP configuration is needed —
Gemini uses the context instructions to know when to invoke tools.

---

### OpenCode

**Install via git-backed plugin:**

Add to your `opencode.json` (global or project-level):

```json
{
  "plugin": ["ate-rag-kb@git+https://github.com/WalterLuo/ate-rag-kb.git"]
}
```

Restart OpenCode. See `.opencode/INSTALL.md` for detailed instructions.

---

### GitHub Copilot CLI

**Register the marketplace:**

```bash
copilot plugin marketplace add WalterLuo/ate-rag-kb-marketplace
```

**Install the plugin:**

```bash
copilot plugin install ate-rag-kb@ate-rag-kb-marketplace
```

Copilot Chat in VS Code can also use MCP servers via
`~/.vscode/mcp.json` or workspace settings.

---

### Factory Droid

**Register the marketplace:**

```bash
droid plugin marketplace add https://github.com/WalterLuo/ate-rag-kb
droid plugin install ate-rag-kb@ate-rag-kb
```

---

## Plugin Files Reference

| Harness | Files in this repo |
|---------|-------------------|
| Claude Code | `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` |
| Cursor | `.cursor-plugin/plugin.json` |
| Codex | `.codex-plugin/plugin.json` |
| Gemini CLI | `gemini-extension.json`, `GEMINI.md` |
| OpenCode | `.opencode/INSTALL.md` |
| All MCP tools | `scripts/start_mcp.py`, `scripts/install_mcp.py` |

## Troubleshooting

### MCP server not starting

1. Verify `uv run python scripts/start_mcp.py` works from the project root.
2. If Docker bootstrap is disabled, ensure Qdrant is reachable at the configured URL.
3. Check that models exist in `embeddings/cache/` or that cloud API credentials are set.
4. Confirm authorized documents were ingested into the Qdrant collection.

### Plugin not loading

1. Confirm the plugin manifest syntax is valid JSON.
2. Check the AI tool's logs for plugin loading errors.
3. For marketplace installs, verify the marketplace URL is reachable.

### Model cache errors

If you see "Local model cache not found", the embedding models are missing.
Unpack the model archive or download them:

```bash
# After unpacking ate-rag-kb-models.zip into project root
uv run python scripts/verify_models.py
```

## Architecture Notes

- **MCP-first:** All harnesses that support MCP (Claude Code, Cursor, Codex,
  Copilot Chat) use `scripts/start_mcp.py`, which execs the same
  `ate_rag_kb.cli.main mcp` stdio server.
- **Routing skill:** `skills/ate-kb-router/SKILL.md` tells skill-aware agents to
  expose and call `ate_kb` before web or shell fallbacks.
- **Managed policy:** `scripts/install_mcp.py --install-agent-policy` appends or
  updates a managed ATE KB Routing block in global agent instructions without
  overwriting user rules.
- **Context files:** `CLAUDE.md`, `GEMINI.md`, and `AGENTS.md` provide
  harness-specific instructions so each AI tool knows how to use `ate_kb` tools.
- **Plugin manifests:** Each harness has its own manifest format in a dedicated
  directory (`.claude-plugin/`, `.cursor-plugin/`, `.codex-plugin/`).
