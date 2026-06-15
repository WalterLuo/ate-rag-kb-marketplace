# Installing ATE RAG KB for OpenCode

## Prerequisites

- [OpenCode.ai](https://opencode.ai) installed
- Python 3.10+ with `uv`
- ATE RAG KB cloned and dependencies installed (`uv sync`)
- Embedding models present under `embeddings/cache/`
- Documents ingested into Qdrant (or access to an existing Qdrant server)

## Installation

Add ATE RAG KB to the `plugin` array in your `opencode.json` (global or
project-level):

```json
{
  "plugin": ["ate-rag-kb@git+https://github.com/WalterLuo/ate-rag-kb.git"]
}
```

Restart OpenCode. The plugin installs through OpenCode's plugin manager.

## MCP Configuration

ATE RAG KB exposes an MCP server over stdio. Configure it in OpenCode so the
agent can use `ate_kb.search`, `ate_kb.retrieve`, and `ate_kb.ask`.

The MCP command is:

```bash
uv run -m ate_rag_kb.cli.main mcp
```

Run this from the project root where `pyproject.toml` lives.

## Usage

Ask ATE-related questions and OpenCode will invoke the `ate_kb` MCP tools:

- "How do I configure a timing set on V93000?"
- "What is the J750 DPS voltage range?"
- "Explain site control in SMT7"

## Updating

OpenCode installs through a git-backed package spec. To pick up the latest
changes, restart OpenCode or reinstall the plugin.

To pin a specific version:

```json
{
  "plugin": ["ate-rag-kb@git+https://github.com/WalterLuo/ate-rag-kb.git#v0.1.0"]
}
```

## Troubleshooting

### Plugin not loading

1. Check logs: `opencode run --print-logs "hello" 2>&1 | grep -i ate-rag-kb`
2. Verify the plugin line in your `opencode.json`
3. Make sure you're running a recent version of OpenCode

### MCP server not responding

1. Verify `uv run -m ate_rag_kb.cli.main mcp` works manually from the project root.
2. Check that models are present in `embeddings/cache/`.
3. Verify Qdrant is accessible (check `configs/config.yaml`).

## Getting Help

- Report issues: https://github.com/WalterLuo/ate-rag-kb/issues
