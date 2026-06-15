# ATE RAG Knowledge Base

[English](README.md) | [中文](README_CN.md)

> **Your coding agent's long-term memory for ATE platform knowledge.**

Query ATE technical documentation, APIs, error codes, and debug flows directly
from Claude Code, Cursor, Codex, or other MCP-enabled agents. Get reliable,
cited answers about timing, patterns, DPS, PMU, and test flows without leaving
your IDE.

**Built for:** Test engineers using AI coding assistants, teams maintaining ATE
test programs (V93000、J750), and anyone with authorized local ATE
documentation who needs grounded, cited answers.

---

## Prerequisites — Install Required Software

Before you start, install these three tools. The KB runs on **both macOS and
Windows**. Everything else (Python itself, the Qdrant database, the embedding
models) is handled for you by `uv` and Docker — you do **not** install them
separately.

| Software | Why it's needed | Download | Verify after install |
|----------|-----------------|----------|----------------------|
| **Git** | Clone this repository | [git-scm.com/downloads](https://git-scm.com/downloads) | `git --version` |
| **uv** | Installs Python 3.10+ and all dependencies automatically | [docs.astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/) | `uv --version` |
| **Docker Desktop** | Runs the Qdrant vector database (server mode, the default) | [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/) | `docker --version` |

> Python 3.10+ is required, but you do **not** download it yourself — `uv`
> installs the correct version automatically. If you prefer a manual install
> anyway, get it from [python.org/downloads](https://www.python.org/downloads/).

### One-line install commands

**macOS** — using [Homebrew](https://brew.sh) (install Homebrew first if you
don't have it):

```bash
brew install git
brew install uv
brew install --cask docker   # then launch Docker Desktop once from Applications
```

**Windows** — using [winget](https://learn.microsoft.com/windows/package-manager/winget/)
(built into Windows 10/11), in **PowerShell**:

```powershell
winget install Git.Git
winget install astral-sh.uv
winget install Docker.DockerDesktop   # then launch Docker Desktop once from the Start menu
```

After installing, open a **new** terminal window and confirm all three respond:

```bash
git --version
uv --version
docker --version
```

> **Windows users:** Run every command in this guide in **PowerShell** (not the
> old `cmd` prompt). Make sure Docker Desktop is running (whale icon in the
> system tray) before any `docker compose` command.

---

## Choose an Install Path

Use one of these paths. They are related, but they do not automatically map to
each other.

| Path | What it configures | Use when |
|------|--------------------|----------|
| **Local checkout deployment** | You clone this repo, prepare models/docs/Qdrant in that folder, then `scripts/install_mcp.py` writes agent settings that point to that exact absolute path. | You already have private ATE docs, model cache, or ingested Qdrant data on this machine. |
| **Marketplace/plugin deployment** | The AI tool clones the plugin into its plugin cache and reads the plugin-root `.mcp.json`. The MCP server starts from that plugin cache by default. | You want plugin-managed installation and understand it is a separate checkout from any manual clone. |

Do not clone and prepare one folder, then install the marketplace plugin
expecting the plugin to reuse that folder automatically. Use the local checkout
installer for that case, or explicitly set `ATE_RAG_KB_PROJECT_ROOT` for the
plugin wrapper.

---

## Quick Start — Local Checkout Deployment (15–30 min)

Every command and path below assumes you are **inside the `ate-rag-kb`
folder** (the "project root"). This path configures agents to this checkout.

### 1. Clone the repository

Pick a folder you'll remember (your home directory is fine):

```bash
git clone https://github.com/WalterLuo/ate-rag-kb.git
cd ate-rag-kb
```

### 2. Install dependencies

```bash
uv sync
```

### 3. Start Qdrant server

```bash
docker compose up -d qdrant
```

### 4. Download embedding models

Option A: use the pre-packaged cache (~6.4 GB). Download from
[PikPak](https://mypikpak.com/s/VOuGT6UlblOdQSw2ZNEP9F12o2) and unzip into
the project root.

Option B: let Hugging Face download on first use (temporarily set
`local_files_only: false` in `configs/config.yaml`).

Option C: use a cloud API provider (e.g., SiliconFlow) for GPU-accelerated
inference without downloading models locally. Set the API key and update
`configs/config.yaml` — see the [Cloud API for Embedding and
Reranking](#cloud-api-for-embedding-and-reranking) section for details.

```bash
uv run python scripts/verify_models.py
```

### 5. Prepare local authorized Markdown documents

```bash
mkdir -p data/raw/markdown/v93000/smt7
```

Copy or generate your own authorized Markdown files into `data/raw/markdown/`.

### 6. Ingest documents

First run is full; subsequent runs use `--incremental`.

```bash
uv run -m ate_rag_kb.cli.main ingest --dir ./data/raw/markdown
```

### 7. Configure your agent

```bash
uv run python scripts/install_mcp.py --install-agent-policy
```

This writes MCP settings that call `scripts/start_mcp.py` from this checkout and
set `ATE_RAG_KB_PROJECT_ROOT` to this absolute path. Do not run the marketplace
install as a replacement for this step unless you intentionally want a separate
plugin-cache deployment.

See [Agent Integration](#agent-integration) below for marketplace and manual
configuration details.

### 8. Validate and restart

```bash
uv run python scripts/validate_plugin_install.py
uv run python scripts/validate_agent_routing_policy.py
```

Then restart Codex / Claude Code / Cursor.

### 9. Start the MCP server directly (optional troubleshooting)

```bash
uv run python scripts/start_mcp.py
```

Or start the HTTP API (for direct access):

```bash
uv run -m ate_rag_kb.cli.main serve --host 0.0.0.0 --port 8080
```

> **Note:** The model cache (`./embeddings/cache/`) is **not** committed to git
> due to its large size. Ingestion creates local state under `data/processed/`
> and `data/qdrant_server/`; these generated files are also not committed.
>
> **Server mode is the only supported Qdrant mode.** The KB connects to
> `http://localhost:6333` (Qdrant server started by Docker). Local file mode
> (`./data/qdrant_storage/`) is deprecated and unsupported — it raises a
> RuntimeError at startup.

---

## Model Cache and Offline Mode

The default config runs in offline/cache-only mode:

```yaml
embedding:
  cache_dir: "${ATE_KB_MODEL_CACHE:-./embeddings/cache}"
  local_files_only: true
```

Required cached models:

- `BAAI/bge-m3` for embeddings
- `BAAI/bge-reranker-v2-m3` for cross-encoder reranking

**Download pre-packaged model cache (~6.4 GB):**

If you don't want to download models from Hugging Face manually, use the
pre-packaged cache archive:

1. Download from [PikPak](https://mypikpak.com/s/VOuGT6UlblOdQSw2ZNEP9F12o2)
2. Unzip `ate-kb-model-cache.zip` into the project root
3. Verify with `uv run python scripts/verify_models.py`

The archive contains the full Hugging Face cache layout
(`models--BAAI--bge-m3` and `models--BAAI--bge-reranker-v2-m3`) ready to use
with `local_files_only: true`.

Set a shared or external cache directory when useful:

```bash
export ATE_KB_MODEL_CACHE=/path/to/ate-kb-model-cache
```

Windows PowerShell:

```powershell
$env:ATE_KB_MODEL_CACHE="D:\ate-kb-model-cache"
```

### Vector DB Transfer with Qdrant Snapshots

To move your indexed data between machines or back it up, use Qdrant's built-in
snapshot feature instead of copying the Docker volume directory:

```bash
# Create a snapshot of the current collection
curl -X POST http://localhost:6333/collections/ate_kb/snapshots

# Download the snapshot file
curl -o ate_kb.snapshot http://localhost:6333/collections/ate_kb/snapshots/<snapshot_name>

# On the target machine, restore from snapshot (POST multipart with wait=true and priority=snapshot)
curl -X POST "http://localhost:6333/collections/ate_kb/snapshots/upload?wait=true&priority=snapshot" \
  -H "Content-Type: multipart/form-data" \
  -F "snapshot=@ate_kb.snapshot"
```

Or use the built-in snapshot script, which handles creation, download, and restore:

```bash
# Create and download
uv run python scripts/package_qdrant_snapshot.py create --output dist

# Upload and restore on the target machine
uv run python scripts/package_qdrant_snapshot.py restore --snapshot dist/ate_kb.snapshot

# Or with explicit priority (default: snapshot)
uv run python scripts/package_qdrant_snapshot.py restore --snapshot dist/ate_kb.snapshot --priority replica
```

This avoids file-locking issues and ensures a consistent backup.

### Cloud API for Embedding and Reranking

By default, the KB uses local sentence-transformers models for embedding and
reranking. You can switch to a cloud API provider (e.g., SiliconFlow) for
GPU-accelerated inference without a local GPU.

#### SiliconFlow Setup

1. Get an API key from [siliconflow.cn](https://siliconflow.cn).
2. On Windows PowerShell, set user-level environment variables:

```powershell
[Environment]::SetEnvironmentVariable("SILICONFLOW_API_KEY", "your-api-key-here", "User")
[Environment]::SetEnvironmentVariable("ATE_KB_EMBEDDING_PROVIDER", "openai_compatible", "User")
[Environment]::SetEnvironmentVariable("ATE_KB_RERANKER_PROVIDER", "http", "User")
```

Then close and reopen PowerShell, Codex, Claude Code, Cursor, or your MCP
client so the new environment variables are inherited.

For a temporary setting in the current PowerShell window only:

```powershell
$env:SILICONFLOW_API_KEY="your-api-key-here"
$env:ATE_KB_EMBEDDING_PROVIDER="openai_compatible"
$env:ATE_KB_RERANKER_PROVIDER="http"
```

On macOS / Linux:

```bash
export SILICONFLOW_API_KEY="your-api-key-here"
export ATE_KB_EMBEDDING_PROVIDER="openai_compatible"
export ATE_KB_RERANKER_PROVIDER="http"
```

Do not put real API keys in `.mcp.json`, `.claude/settings.json`, Cursor MCP
settings, or other agent configuration files. MCP server configs should inherit
`SILICONFLOW_API_KEY` from the parent process environment and only contain
non-sensitive values such as `CONFIG_PATH`.

3. The recommended `configs/config.yaml` setup is to keep environment-variable
   placeholders and never store the real key in the file. The current config
   already contains:

```yaml
embedding:
  provider: "${ATE_KB_EMBEDDING_PROVIDER:-local}"
  api:
    base_url: "${ATE_KB_EMBEDDING_BASE_URL:-https://api.siliconflow.cn/v1}"
    api_key_env: "${ATE_KB_EMBEDDING_API_KEY_ENV:-SILICONFLOW_API_KEY}"

retrieval:
  reranker:
    provider: "${ATE_KB_RERANKER_PROVIDER:-http}"
    api:
      base_url: "${ATE_KB_RERANKER_BASE_URL:-https://api.siliconflow.cn/v1}"
      api_key_env: "${ATE_KB_RERANKER_API_KEY_ENV:-SILICONFLOW_API_KEY}"
```

Meaning:

- `api_key_env` is the environment variable name, not the API key value.
- The real `SILICONFLOW_API_KEY` value should only be stored in the Windows
  environment.
- `reranker.provider` already defaults to `http`.
- `embedding.provider` defaults to `local`; on Windows cloud embedding, set
  `ATE_KB_EMBEDDING_PROVIDER=openai_compatible` or change the config value to
  `provider: "openai_compatible"`.

If you prefer not to use provider environment variables, you can pin the
providers in `configs/config.yaml`, but still do not write the real API key:

```yaml
embedding:
  provider: "openai_compatible"
  api:
    base_url: "https://api.siliconflow.cn/v1"
    api_key_env: "SILICONFLOW_API_KEY"

retrieval:
  reranker:
    provider: "http"
    api:
      base_url: "https://api.siliconflow.cn/v1"
      api_key_env: "SILICONFLOW_API_KEY"
```

4. Switch model names, base URLs, or the API key variable name as needed.

Windows PowerShell:

```powershell
# Optional: switch model names (defaults: BAAI/bge-m3, BAAI/bge-reranker-v2-m3)
[Environment]::SetEnvironmentVariable("ATE_KB_EMBEDDING_MODEL", "vendor/custom-embedding", "User")
[Environment]::SetEnvironmentVariable("ATE_KB_RERANKER_MODEL", "vendor/custom-reranker", "User")

# Optional: switch API base URLs (defaults: https://api.siliconflow.cn/v1)
[Environment]::SetEnvironmentVariable("ATE_KB_EMBEDDING_BASE_URL", "https://api.your-vendor.com/v1", "User")
[Environment]::SetEnvironmentVariable("ATE_KB_RERANKER_BASE_URL", "https://api.your-vendor.com/v1", "User")

# Optional: if your vendor uses a different key variable name
[Environment]::SetEnvironmentVariable("MY_VENDOR_API_KEY", "your-api-key-here", "User")
[Environment]::SetEnvironmentVariable("ATE_KB_EMBEDDING_API_KEY_ENV", "MY_VENDOR_API_KEY", "User")
[Environment]::SetEnvironmentVariable("ATE_KB_RERANKER_API_KEY_ENV", "MY_VENDOR_API_KEY", "User")
```

macOS / Linux:

```bash
# Optionally switch model names (defaults: BAAI/bge-m3, BAAI/bge-reranker-v2-m3)
export ATE_KB_EMBEDDING_MODEL="vendor/custom-embedding"
export ATE_KB_RERANKER_MODEL="vendor/custom-reranker"

# Optionally switch API base URLs (defaults: https://api.siliconflow.cn/v1)
export ATE_KB_EMBEDDING_BASE_URL="https://api.your-vendor.com/v1"
export ATE_KB_RERANKER_BASE_URL="https://api.your-vendor.com/v1"

# Optional: if your vendor uses a different key variable name
export MY_VENDOR_API_KEY="your-api-key-here"
export ATE_KB_EMBEDDING_API_KEY_ENV="MY_VENDOR_API_KEY"
export ATE_KB_RERANKER_API_KEY_ENV="MY_VENDOR_API_KEY"
```

Verify the Windows environment variables:

```powershell
Get-ChildItem Env:ATE_KB_EMBEDDING_PROVIDER
Get-ChildItem Env:ATE_KB_RERANKER_PROVIDER
Get-ChildItem Env:SILICONFLOW_API_KEY
```

#### Switching to Other Vendors

The `openai_compatible` embedding provider and `http` reranker provider work
with any OpenAI-compatible API. Change `base_url` and `api_key_env` in the
config to point to your preferred vendor.

#### Disabling the Reranker

If you want to skip reranking entirely (for speed or cost), set:

```yaml
retrieval:
  reranker:
    enabled: false
```

### Model Package Regeneration

If you need to regenerate the model cache package (e.g., after adding new models
or updating existing ones):

```bash
uv run python scripts/package_models.py
```

This creates an archive of the current `embeddings/cache/` directory that can be
distributed for offline use.

---

## Adding Documents

Use only documents that you are authorized to ingest and query. The repository
does not grant rights to third-party ATE documentation.

**Canonical ATE terminology:**

| Vendor | Tester platform | Software |
|---|---|---|
| Advantest | V93000 | SMT7, SMT8 |
| Teradyne | J750 | IG-XL |

V93000 and J750 are tester platforms. SMT7, SMT8, and IG-XL are software
scopes used for ingestion, retrieval routing, and citation isolation.

If you already have Markdown files, place them under the canonical scope path:

```
data/raw/
├── markdown/
│   ├── v93000/smt7/   # V93000 / SmarTest 7 documents
│   ├── v93000/smt8/   # V93000 / SmarTest 8 documents
│   └── igxl/          # J750 / IG-XL documents
├── json/
│   ├── v93000/smt7/   # optional metadata sidecars for SMT7
│   ├── v93000/smt8/   # optional metadata sidecars for SMT8
│   └── igxl/          # optional metadata sidecars for IG-XL
└── assets/
    ├── v93000/smt7/   # optional local images for SMT7 docs
    ├── v93000/smt8/   # optional local images for SMT8 docs
    └── igxl/          # optional local images for IG-XL docs
```

Then run ingestion:

```bash
uv run -m ate_rag_kb.cli.main ingest --dir ./data/raw/markdown --incremental
```

### Using a Local Conversion Script

You can provide a local script that converts documentation you are allowed to
use into Markdown. Keep vendor-specific conversion scripts outside the public
repository, or place private scripts under `scripts/local/`, which is ignored by
git.

For TDC/Eclipse Help and IG-XL help sources, use the companion converter
project: [ate-help-converters](https://github.com/WalterLuo/ate-help-converters).
It provides macOS and Windows one-click installers plus CLI commands for
converting authorized local help files into Markdown/JSON/assets.

Do not commit converted Markdown, extracted assets, generated JSON sidecars, or
vector database snapshots unless you have explicit redistribution rights.

---

## Agent Integration

### Local Checkout Agent Configuration

Use this after the local checkout quick start. The installer configures detected
AI tools to run the MCP server from the checkout you prepared:

```bash
# Configure all detected AI CLI tools
uv run python scripts/install_mcp.py --install-agent-policy

# Dry-run first to preview changes
uv run python scripts/install_mcp.py --dry-run

# Configure only specific tools
uv run python scripts/install_mcp.py --harness claude,cursor

# Configure MCP only, without global agent policy (not recommended for projectless sessions)
uv run python scripts/install_mcp.py --skip-agent-policy
```

The generated MCP settings use `uv run --project <checkout> python
<checkout>/scripts/start_mcp.py`, set `ATE_RAG_KB_PROJECT_ROOT` to the checkout,
and enable Qdrant bootstrap with `ATE_KB_AUTO_BOOTSTRAP=1`.

### Marketplace Plugin Installation

Marketplace/plugin installation is a separate path. The AI tool clones the
plugin into its plugin cache; it does not automatically reuse a manual clone
that you prepared elsewhere.

#### Per-Harness Quick Install

| Harness | Install Command |
|---------|-----------------|
| **Claude Code** | `/plugin marketplace add WalterLuo/ate-rag-kb-marketplace` then `/plugin install ate-rag-kb@ate-rag-kb-marketplace` |
| **Cursor** | `/add-plugin ate-rag-kb` |
| **Codex** | `/plugins` → search "ate-rag-kb" |
| **Gemini CLI** | `gemini extensions install https://github.com/WalterLuo/ate-rag-kb.git` |
| **OpenCode** | Add `"ate-rag-kb@git+https://github.com/WalterLuo/ate-rag-kb.git"` to `opencode.json` plugins |
| **Copilot CLI** | `copilot plugin install ate-rag-kb@ate-rag-kb-marketplace` |

For detailed per-harness instructions, troubleshooting, and architecture notes,
see [docs/PLUGIN_INSTALL.md](docs/PLUGIN_INSTALL.md).

For local or team Codex marketplace installs, register this repository's
`.agents/plugins/marketplace.json` and then search for `ate-rag-kb`. Public
Codex marketplace search requires publishing or registering the marketplace
outside this repository.

### Claude Code (MCP — Marketplace Auto Config)

Marketplace and plugin installs include a plugin-root `.mcp.json`:

```json
{
  "mcpServers": {
    "ate-kb": {
      "command": "uv",
      "args": [
        "run",
        "--project",
        "${CLAUDE_PLUGIN_ROOT}",
        "python",
        "${CLAUDE_PLUGIN_ROOT}/scripts/start_mcp.py"
      ],
      "env": {
        "ATE_KB_QUERY_DEVICE": "cpu",
        "ATE_KB_RERANKER_DEVICE": "cpu",
        "ATE_KB_AUTO_BOOTSTRAP": "1"
      }
    }
  }
}
```

On startup, `uv run` creates or reuses the plugin Python environment,
`scripts/start_mcp.py` resolves the project root, derives `CONFIG_PATH`, starts
Qdrant with Docker Compose when `ATE_KB_AUTO_BOOTSTRAP=1`, and then execs the
real `ate_rag_kb.cli.main mcp` server.

Restart Claude Code after installing the plugin. The agent will auto-discover
`ate_kb.*` tools from the plugin-provided MCP server. Authorized source docs,
model cache or cloud API credentials, and ingestion are still deployment
prerequisites; the plugin cannot redistribute or invent your private ATE docs.

If you already prepared a local checkout and want agents to use it, prefer
`uv run python scripts/install_mcp.py --install-agent-policy`. Advanced users
can launch the agent with `ATE_RAG_KB_PROJECT_ROOT=/path/to/ate-rag-kb` and,
if needed, `ATE_RAG_KB_CONFIG_PATH=/path/to/ate-rag-kb/configs/config.yaml`;
the wrapper reads those variables before falling back to the plugin cache.

Manual configuration is only needed if you are not using the plugin installer.
In that case, add to `~/.claude/settings.json` (macOS / Linux) or
`%USERPROFILE%\.claude\settings.json` (Windows):

```json
{
  "mcpServers": {
    "ate-kb": {
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

If you use the HTTP reranker or cloud embedding provider, export
`SILICONFLOW_API_KEY` before starting Claude Code or the MCP client. Keep the
key out of this JSON block; it should be inherited from the parent process
environment.

### Default Agent Behavior

When an engineer asks an ATE technical question, the agent should use MCP tools
first and choose the retrieval strategy itself. The normal path is
`ate_kb.retrieve` or `ate_kb.ask`, followed by `ate_kb.get_document` only when a
full source document is needed. CLI search, grep, and manual markdown reads are
fallbacks for unavailable or insufficient MCP results, not the default workflow.

Configuring an MCP server does not by itself guarantee the model will call MCP
first. In Codex, `ate_kb` may be a deferred tool that must be exposed through
`tool_search`. The recommended installer command,
`uv run python scripts/install_mcp.py --install-agent-policy`, installs a
managed ATE KB Routing policy in addition to MCP configuration. This matters
especially for Codex projectless sessions. If you run `--skip-agent-policy`,
projectless sessions may not reliably prefer `ate_kb`.

After installation, restart your agent and run:

```bash
uv run python scripts/validate_plugin_install.py
uv run python scripts/validate_agent_routing_policy.py
```

## Available Agent Tools

| Tool | Description | Use When |
|------|-------------|----------|
| `ate_kb.search` | Quick semantic search | Finding relevant docs |
| `ate_kb.retrieve` | Deep retrieval with rerank + expansion | Comprehensive answers |
| `ate_kb.ask` | Structured Q&A with citations | Direct questions |
| `ate_kb.related` | Parent/sibling/children of a chunk | Need broader context |
| `ate_kb.get_document` | Paginated document chunks (`limit`/`offset`) | Reading full reference after discovery |
| `ate_kb.status` | Collection stats | Checking KB health |

All tools return structured JSON with `source_md`, `doc_title`,
`section_title`, `chunk_id`, `start_line`, and `end_line` for every result.

`ate_kb.get_document` supports pagination (`limit`, `offset`) and a
`max_tokens` budget. Agents should prefer small `limit` values (e.g. 20) and
page through large documents rather than fetching all chunks at once. The MCP
handler uses a paged retrieval path internally, so large documents do not need
to be loaded in full for the first page.

---

## Project Architecture

```
Markdown + JSON  ->  IngestionPipeline  ->  Chunks  ->  EmbeddingEncoder
                                                            |
                                                            v
FastAPI / MCP  <-  RetrievalCoordinator  <-  RetrievalPipeline  <-  QdrantVectorStore  <-  Vectors
```

**RetrievalPipeline stages:**

1. **HybridRetriever** — dense + sparse vector search with Reciprocal Rank Fusion
2. **DocumentGraphExpander** (optional) — follows internal document links
3. **Reranker** — cross-encoder (`BAAI/bge-reranker-v2-m3`)
4. **BroadConceptAssembler** (optional) — coverage-aware selection for broad queries
5. **ParentChildExpander** — enriches with parent/sibling context
6. **ContextCompressor** — deduplicates, merges adjacent, token-caps

For advanced configuration options (chunking strategies, retrieval parameters,
state isolation, migration from local mode), see [CLAUDE.md](CLAUDE.md).

---

## Evaluation & Validation

Run retrieval evaluation:

```bash
uv run python scripts/run_eval.py
```

Metrics: `hit@k`, `recall@k`, `MRR@k`, `source_precision@k`.

Current baseline (50 questions):

| Metric | Value |
|--------|-------|
| `source_precision@5` | 1.0000 |
| `failed_count` | 0 |

Before using the KB with real engineers, run:

1. [Agent E2E Validation](docs/agent_e2e_validation.md) — step-by-step verification
2. [Beta Checklist](docs/beta_checklist.md) — 10-question trial with pass criteria
3. [Beta 10-Question Trial Report](docs/archive/beta_test_report_10q.md) — archived first trial result
4. [Beta 10-Question Retest Plan](docs/archive/beta_retest_10q.md) — archived post-fix retest procedure

Current beta status: ready for engineer handoff. The first recorded trial
passed 9/10 questions. After the ARRAY citation fix, expected-answer checklist
updates, and paginated `get_document` implementation, the first five priority
questions were retested and passed; evidence is recorded in
[docs/archive/10q_retest.csv](docs/archive/10q_retest.csv).

---

## Development Commands

```bash
# Run tests
uv run pytest tests/ -q

# Run tests with coverage
uv run pytest tests/ --cov=src/ate_rag_kb --cov-report=term

# Lint
uv run ruff check src/ tests/

# Search from CLI (developer/debugging fallback)
uv run -m ate_rag_kb.cli.main search "timing set configuration" --top-k 5

# Check collection stats
uv run -m ate_rag_kb.cli.main status
```

### Maintenance Scripts

```bash
# Rebuild sparse vectors after vocabulary or encoder changes
# (requires a running Qdrant server and an existing collection)
uv run python scripts/rebuild_sparse_vectors.py
```

This script reads every point's content from the Qdrant collection,
re-encodes the sparse vectors using the current `SparseVectorEncoder`, and
updates them in-place. It does not re-chunk or re-embed dense vectors. Run it
after a full ingestion and only when the sparse encoder configuration has
changed.

## Where Do All the Files Live?

Every path in this guide that starts with `./data/...` or `./embeddings/...` is
**relative to the project root** — the `ate-rag-kb` folder you cloned in Step 1.
Nothing is written outside this folder unless you deliberately change the config.
This is the same on macOS and Windows.

| What | Path | Created by | Commit to git? |
|------|------|------------|----------------|
| Your source Markdown docs | `data/raw/markdown/` | **You** (copy files in) | No |
| Optional JSON metadata | `data/raw/json/` | You (optional) | No |
| Optional images | `data/raw/assets/` | You (optional) | No |
| **Qdrant data — server mode (default)** | `data/qdrant_server/` | Docker container | No |
| Ingestion state | `data/processed/` | `ingest` command | No |
| Embedding model cache (~6.4 GB) | `embeddings/cache/` | You (download) or Hugging Face | No |

**Concrete examples** — relative to the project root:

| What | Relative path |
|------|---------------|
| V93000 / SMT7 Markdown files | `data/raw/markdown/v93000/smt7/` |
| J750 / IG-XL Markdown files | `data/raw/markdown/igxl/` |
| Embedding model cache | `embeddings/cache/` |

> **Qdrant data is runtime state, not a distribution artifact:**
>
> - **`data/qdrant_server/`** is the Docker volume that the Qdrant container
>   writes to. Start it with `docker compose up -d qdrant`.
> - To transfer or back up your vector data, use **Qdrant snapshots** instead
>   of copying the volume directory. See the "Vector DB Transfer with Qdrant
>   Snapshots" section above.
> - Local file mode (`data/qdrant_storage/`) is deprecated and raises a
>   RuntimeError at startup.

---

## License

The application code is released under the MIT License. See [LICENSE](LICENSE).

Third-party ATE vendor documentation, converted documentation, extracted
assets, model files, and generated vector stores are not included in this
license. See [THIRD_PARTY.md](THIRD_PARTY.md) for redistribution notes.
