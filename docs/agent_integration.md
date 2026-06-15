# Agent Integration Guide

Integrate the ATE RAG Knowledge Base with your coding agent (Claude Code,
OpenClaw, Codex, Cursor) to query ATE platform documentation directly from your
development workflow.

## Overview

The ATE KB exposes 6 tools via MCP (Model Context Protocol). Your agent can
search, retrieve, ask, and browse technical documentation with full citation
support.

## Qdrant Server Setup (Required)

The default configuration uses **Qdrant server mode** (`url: http://localhost:6333`).
You must start Qdrant **before** ingesting documents or running MCP/API.

```bash
# Docker Compose (recommended)
docker compose up -d qdrant

# Or docker run
docker run -d -p 6333:6333 -p 6334:6334 \
  -v $(pwd)/data/qdrant_server:/qdrant/storage \
  qdrant/qdrant:latest
```

After Qdrant is running, ingest documents:

```bash
uv run -m ate_rag_kb.cli.main ingest --dir ./data/raw/markdown
```

Then verify:

```bash
uv run -m ate_rag_kb.cli.main status
```

### Local Mode (Deprecated)

Local file mode (`mode: local` or legacy `use_local: true`) is **no longer
supported**. Setting either option raises a `RuntimeError` at startup with a
message directing you to server mode. Use Docker-based server mode instead:

```bash
docker compose up -d qdrant
```

And in `configs/config.yaml`:

```yaml
vector_store:
  mode: server
```

### State Isolation and Profile Changes

Incremental ingestion state is isolated per profile (hash of backend mode,
collection name, embedding model, chunking config, and document scope).
Switching any of these settings automatically triggers a full re-ingest:

- Old `data/processed/ingestion_state.json` is preserved as `.json.legacy`
- New profile-specific state files are created under `data/processed/state_{hash}.json`
- The collection is cleared before the full rebuild to remove stale points
- Full ingest records the current profile state after rebuilding, so the next
  `--incremental` run only processes real file changes.

### Document Scope and Software Versions

ATE documentation uses canonical vendor, tester platform, and software scopes:

| Vendor | Tester platform | Software |
|---|---|---|
| Advantest | V93000 | SMT7, SMT8 |
| Teradyne | J750 | IG-XL |

The `documents` section in `configs/config.yaml` controls which scopes are
ingested and searchable. When `documents.enabled_scopes` is present, it is the
authoritative scope list:

```yaml
documents:
  enabled_scopes:
    - vendor: "teradyne"
      platform: "j750"
      software: "igxl"
    - vendor: "advantest"
      platform: "v93000"
      software: "smt7"
```

- **Adding SMT8:** add a scope with `vendor: "advantest"`, `platform: "v93000"`,
  and `software: "smt8"`.
- **Removing IG-XL:** remove the `teradyne / j750 / igxl` scope, then run a full
  ingest so stale chunks from the previous scope are cleared.
- SMT7 and SMT8 are software under the V93000 tester platform. IG-XL is software
  under the J750 tester platform. None of these software names should be treated
  as top-level tester platforms.

### Query Routing Rules

Agents should let the KB route platform scope automatically:

- Explicit software or platform resolves to one scope, such as `SMT7` to
  `v93000/smt7` or `IG-XL` to `j750/igxl`.
- Exclusive symbols resolve to the generated symbol-catalog owner scope, such
  as `SelectFirst` to `j750/igxl` and `ON_FIRST_INVOCATION_BEGIN` to
  `v93000/smt7`.
- Wrong platform plus exclusive symbol returns a correction notice and answers
  from the symbol owner scope only.
- A neutral query with IG-XL plus SMT7 enabled returns two isolated answer
  sections: `J750 / IG-XL` and `V93000 / SMT7`.
- When SMT7 and SMT8 are both enabled, a query that says only `V93000` asks the
  user to choose the software version.
- After SMT8 enablement, a neutral query across J750 and V93000 asks the user to
  choose the tester platform first unless the user explicitly asks for two
  answers.

## Claude Code Configuration

### Option 1: MCP (Recommended)

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)
or equivalent:

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

Restart Claude Code. The agent will auto-discover `ate_kb.*` tools.

Do not add API keys to the MCP JSON. If you use a cloud embedding or reranker
provider, export the key (for example `SILICONFLOW_API_KEY`) in the parent
process environment before starting the agent so the MCP server inherits it.

### Option 2: HTTP API

If MCP is unavailable, configure Claude Code to call the FastAPI endpoints
directly via custom tools. Start the API server:

```bash
uv run -m ate_rag_kb.cli.main serve --host 0.0.0.0 --port 8080
```

## OpenClaw Configuration

OpenClaw supports MCP servers. Add the following to your OpenClaw configuration:

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

## Codex Configuration

Codex MCP support varies by version. If your Codex client supports MCP,
configure it similarly to Claude Code:

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

## Beta Validation

Before onboarding engineers, complete the formal validation steps:

- [Agent E2E Validation](agent_e2e_validation.md) — confirm MCP discovery, tool
  calls, citations, and pagination
- [Beta Checklist](beta_checklist.md) — 10-question trial with pass/fail criteria
- [Beta 10-Question Trial Report](archive/beta_test_report_10q.md) — archived first recorded
  engineer-facing trial result and follow-up acceptance gaps
- [Beta 10-Question Retest Plan](archive/beta_retest_10q.md) — archived post-fix retest flow
  for Q2 ARRAY, Q1/Q3/Q5 completeness, and pagination

Quick-start MCP config for plugin installs is now bundled in the tracked
plugin-root `.mcp.json` and runs `${CLAUDE_PLUGIN_ROOT}/scripts/start_mcp.py`.
For manual, non-plugin setups, copy the example configuration:

```bash
cp .mcp.example.json .mcp.json
# Replace /path/to/ate-rag-kb with your absolute project path
```

## Agent Usage Rules

When using ATE KB tools, follow these rules:

### 0. Default Contract

Engineers should ask ATE domain questions directly. The agent must choose the
retrieval path and should not ask the engineer whether to use MCP, CLI, grep, or
raw markdown files.

For any question about ATE documentation, SmarTest, TDC, V93000, pin
configuration, timing, levels, patterns, DPS, PMU, test flow, tester behavior,
command syntax, or API references:

- Use MCP tools first.
- Prefer `ate_kb.retrieve` for specific technical answers.
- Prefer `ate_kb.ask` for direct Q&A that needs citations.
- Use `ate_kb.get_document` only after relevant `source_md` files are identified.
- Use `ate_kb.search` only for exploratory discovery or source-file location.
- Do not use `uv run -m ate_rag_kb.cli.main search`, shell grep, `rg`, or manual
  raw markdown reads as the first step.
- Fall back to CLI/file reads only when MCP tools are unavailable, fail, or
  return insufficient context.

### 1. Tool Selection

- Use `ate_kb.retrieve` as the default tool for specific ATE technical questions
- Use `ate_kb.ask` for direct Q&A ("how do I configure drive edge?")
- Use `ate_kb.search` for quick exploratory lookups ("find docs about timing sets")
- Use `ate_kb.related` when a chunk is relevant but incomplete.
  Control sibling volume with `max_siblings` (default 2, max 10) to keep
  responses focused.
- Use `ate_kb.get_document` to read full API references after source discovery.
  This tool supports `limit`, `offset`, and `max_tokens`. For large documents,
  prefer small `limit` values (e.g. 20) and page through chunks rather than
  fetching the entire document at once.
- Use `ate_kb.status` to verify KB health before querying

Large documents observed during beta validation include
`v93000/smt7/146692.md` (`RDI_Configure file`), `v93000/smt7/13920.md`
(`Using the Timing Diagram Tool`), and `v93000/smt7/49363_2.md`
(`Technology file for a device`). These should be read through
pagination, not as single full-document payloads. MCP `ate_kb.get_document`
uses a paged backend path; agents should still pass explicit `limit` and
`offset` values so the response stays focused.

### 2. Citation Requirements

**Every claim derived from ATE KB must include a citation.**

Required citation format:
```
[Source: {source_md}, Section: {section_title}, Chunk: {chunk_id}]
```

Example:
> To configure drive edge in TDC, use the MSET command with the `drive_edge`
> action. [Source: 118727.md, Section: Syntax, Chunk: sha256-abc...]

### 3. Confidence Handling

- If top chunk score < 0.5: warn user that results may be unreliable
- If no chunks returned: state clearly that the KB has no relevant information
- If sources conflict: present all perspectives with their sources

### 4. Follow-up Strategy

After initial retrieval:
1. Check if top result is directly relevant (score > 0.6)
2. If not, try `ate_kb.retrieve` with different query phrasing
3. If still poor, use `ate_kb.related` on the best-matching chunk
4. If document-level context needed, use `ate_kb.get_document`

### Broad-query retrieval behavior

For broad concept questions (e.g. "what is site control", "how does timing work"),
the agent does **not** need to manually specify source hints.

- `ate_kb.ask` and `ate_kb.retrieve` automatically detect broad concept queries
  and expand linked-document coverage via the document graph.
- Graph-expanded candidates participate in reranking, so related documents
  have a chance to surface in the final result.
- A coverage-aware rerank step preserves content-bearing chunks from multiple
  sources and subtopics rather than letting one document monopolize the result.
- `BroadConceptAssembler` follows related links discovered from the document
  graph, prioritizes concept hubs and their forward-linked subtopics, adds
  bounded representative documents or sections, and drops image
  placeholders, title-only chunks, and functional-change notes when better
  answer context exists.
- The MCP response includes an `answer_contract`. When
  `answer_contract.completeness_required` is `true`, the calling agent must
  provide a sectioned broad answer instead of a short overview, inspect the
  dynamically discovered `coverage_topics`, and cite each answer section.
- The `processing` field in the MCP response can be used to diagnose where
  content was dropped (e.g. reranker pruned too aggressively, or diversity
  selection kept too few sources).

## Recommended System Prompt

Add this to your agent's system prompt when ATE KB is active:

```
You have access to the ATE RAG Knowledge Base, which contains technical
documentation for TDC/SmarTest ATE platforms.

When answering questions about:
- Timing configuration (timesets, edges, waveforms)
- Pattern programming (bursts, vectors, loops)
- DPS/power management
- PMU/measurement
- Test flows and test programs
- API references

ALWAYS use MCP first. Use ate_kb.retrieve or ate_kb.ask to get grounded
context before answering. Do not start with CLI search, grep, rg, or manual
markdown reads unless MCP tools are unavailable or insufficient. Then synthesize
your answer, citing the source_md and section_title for every claim.

If the retrieved context is insufficient or low-confidence (score < 0.5),
say so explicitly. Do not hallucinate technical details.
```

## Query Best Practices

### Good Queries

- "How to configure drive edge in TDC?" (specific, includes platform)
- "DPS alarm 2034 meaning" (includes error code)
- "Pattern burst syntax example" (includes topic + intent)

### Bad Queries

- "timing" (too vague)
- "help with test" (no specific topic)
- "why does it fail" (no context)

## Low Confidence Response Strategy

When retrieval scores are low:

1. **Acknowledge uncertainty**: "The knowledge base has limited relevant
   information for this query."
2. **Present best available**: "Here are the closest matches, but they may not
   fully answer your question."
3. **Suggest alternatives**: "You may want to search for [related term] or
   consult the [specific document]."
4. **Never fabricate**: If the KB doesn't have the answer, say so.

## MCP Processing Fields

`ate_kb.retrieve` and `ate_kb.ask` responses include a `processing` object that
traces how the result was produced. Use these counts to diagnose drops:

| Field | Meaning |
|-------|---------|
| `post_rerank_candidate_count` | Chunks remaining after cross-encoder rerank |
| `post_rerank_source_count` | Distinct sources represented after rerank |
| `post_diversity_candidate_count` | Chunks remaining after source-diversity selection (broad queries only) |
| `post_diversity_source_count` | Distinct sources represented after diversity selection |
| `broad_context_assembled` | Whether automatic broad-answer assembly ran |
| `broad_context_discovered_source_count` | Sources inspected during related-document assembly |
| `broad_context_added_chunk_count` | Representative chunks added by the assembler |
| `low_utility_chunk_count` | Low-utility chunks removed from assembled context |
| `coverage_topics` | Distinct document or section topics retained for synthesis |
| `final_context_source_count` | Distinct sources in the final context package |
| `final_context_token_estimate` | Approximate token count of the returned context |

The sibling `answer_contract` object is the synthesis contract for the calling
agent. For broad queries, it sets `answer_mode = "broad_concept"`, requires
complete coverage, lists expected answer sections, carries the dynamically
discovered `coverage_topics`, and exposes coverage diagnostics. It must not be
implemented with topic-specific source hints.

If `post_rerank_source_count` is high but `final_context_source_count` is low,
the context compressor or parent-child expander may have dropped sources.
If both are low, the reranker or graph expander may need tuning.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| MCP tools not showing | Check `claude_desktop_config.json` syntax; restart Claude Code |
| Empty results | Verify documents are ingested (`ate_kb.status`) |
| Slow responses | Check Qdrant is running; consider reducing `top_k` |
| Wrong platform results | Add `filters: {"platform": "TDC"}` to queries |
| `uv` command not found | Install `uv`; the MCP wrapper uses `uv run` to create or reuse the project environment |
