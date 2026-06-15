# ate-rag-kb — Developer Guide

## Project Goal

Agentic RAG system for ATE (Automatic Test Equipment) test engineers. Ingests
Markdown + JSON metadata, chunks with rich hierarchy, embeds with BAAI/bge-m3,
stores in Qdrant, and exposes retrieval + Q&A via FastAPI and MCP.

## Core Architecture

```
Markdown + JSON  ->  IngestionPipeline  ->  Chunks  ->  EmbeddingEncoder
                                                            |
                                                            v
FastAPI / MCP  <-  RetrievalCoordinator  <-  RetrievalPipeline  <-  QdrantVectorStore  <-  Vectors
```

FastAPI endpoints:
- `/search` — basic semantic search
- `/retrieve` — hybrid + rerank + parent-child + compression
- `/ask` — coordinator-backed retrieval + citations for agent synthesis
- `/related` — parent/sibling/children for a chunk
- `/document` — all chunks for a source file

MCP tools (stdio transport):
- `ate_kb.search`, `ate_kb.retrieve`, `ate_kb.ask`
- `ate_kb.related`, `ate_kb.get_document`

Agent routing rule:
- ATE / SMT7 / V93000 / IG-XL / J750 technical questions must use the
  `ate_kb` MCP tools before WebSearch, shell grep/rg, CLI search, or raw
  markdown reads.
- In Codex, `ate_kb` can be a deferred MCP tool. If the `ate_kb` tools are not
  visible, first call `tool_search` with a query such as
  `ate_kb status ask retrieve search get_document`, then use
  `ate_kb.ask` or `ate_kb.retrieve`.
- In Claude Code, first confirm the project MCP server is available through
  the MCP tool list or `/mcp` state. Use `mcp__ate-kb__ate_kb_ask` or
  `mcp__ate-kb__ate_kb_retrieve` before fallback sources.
- Do not answer ATE KB questions from memory or public web results unless MCP
  is unavailable, fails, or returns insufficient context.

Current operational status:
- Multi-platform retrieval coordinator is active for FastAPI and MCP.
- Current enabled scopes are Teradyne J750 / IG-XL and Advantest V93000 / SMT7.
- Explicit IG-XL/J750 questions are isolated to `j750/igxl`; explicit SMT7
  questions are isolated to `v93000/smt7`.
- Neutral questions search both enabled scopes and return separated answer
  groups unless routing requires clarification.
- Live acceptance is `uv run scripts/validate_multi_platform_retrieval.py`.

## ATE KB Question Policy

Engineers should ask domain questions directly. Agents must choose the retrieval
strategy without asking the engineer to pick MCP, CLI, grep, or raw files.

When the user asks any technical question about ATE documentation, SmarTest,
TDC, V93000, J750, IG-XL, pin configuration, timing, levels, patterns, DPS,
PMU, test flow, tester behavior, command syntax, or API references:

1. Use MCP tools first.
2. Prefer `ate_kb.retrieve` for specific technical answers.
3. Prefer `ate_kb.ask` for direct Q&A that needs citations.
4. Use `ate_kb.get_document` only after relevant `source_md` files are
   identified by `ate_kb.retrieve` or `ate_kb.ask`.
5. Use `ate_kb.search` only for exploratory discovery or source-file location.
6. Do not use `uv run -m ate_rag_kb.cli.main search`, shell grep, `rg`, or raw
   markdown reads as the first step for ATE KB questions.
7. Fall back to CLI/file search/manual reads only when MCP tools are unavailable,
   fail, or return insufficient context.
8. Cite `source_md`, `section_title`, and relevant command/document names in the
   final answer.

Default flow: user question -> expose `ate_kb` first if the tools are deferred
or hidden -> `ate_kb.retrieve` or `ate_kb.ask` -> inspect `context_package` and
citations -> `ate_kb.get_document` if full-document context is needed ->
synthesize the answer.

Canonical ATE terminology:

| Vendor | Tester platform | Software |
|---|---|---|
| Advantest | V93000 | SMT7, SMT8 |
| Teradyne | J750 | IG-XL |

V93000 and J750 are tester platforms. SMT7, SMT8, and IG-XL are software
scopes. Do not treat IG-XL as a tester platform or SMT7/SMT8 as separate
testers. When both J750 / IG-XL and V93000 / SMT7 are enabled, a neutral query
returns separate scoped groups. When SMT7 and SMT8 are both enabled, a V93000
query without a software version asks the user to choose SMT7 or SMT8.

### Broad Concept Answer Policy

For broad ATE concept questions, do not stop at the first retrieved chunks.

`ate_kb.retrieve` and `ate_kb.ask` automatically assemble bounded context from
content-bearing chunks and related subtopics. Inspect the returned
`coverage_topics` first. If important details are still missing, call
`ate_kb.get_document` with explicit `limit` / `offset` for the discovered main
topic and subtopics.

When the MCP response contains
`answer_contract.completeness_required == true`, treat that contract as
mandatory. Do not return only a short overview. Cover each applicable
`answer_contract.coverage_topics` item, or briefly state why it is outside the
answer scope.

A complete broad answer should cover, when applicable:

1. Core concept and purpose
2. Related windows, flags, commands, APIs, or configuration fields
3. Common usage scenarios
4. Execution behavior and examples
5. Limitations, warnings, and best practices
6. Unsupported or unverified claims explicitly marked as unconfirmed
7. Complete citations with `source_md` and `section_title`

Do not invent unsupported details. If a detail is plausible but not found in
the current KB context, label it as not confirmed by the KB.

#### Cross-Agent Answer Quality Alignment

For broad ATE concept answers, Claude Code, Codex, and other agents should use
the same engineer-facing answer standard. Optimize for grounded completeness
over brevity when the question asks "what is", "what does it do", "how does it
work", or otherwise asks for a concept overview.

A high-quality aligned answer should:

1. Separate concept layers clearly, for example UI/window behavior versus
   testflow/test-suite flags versus command/API behavior.
2. Use compact tables when comparing states, modes, flags, commands, or
   configuration fields.
3. Include practical execution behavior, examples, and debug consequences
   discovered from related KB pages, not only the first definition chunk.
4. Call out important caveats such as default behavior, unavailable states,
   focus/query side effects, data-loss risks, and when settings are ignored.
5. Cite every major claim with the retrieved `source_md` and `section_title`.
6. Avoid treating a concise answer as sufficient when related documents expose
   operational details needed by a test engineer.

When comparing or calibrating answers across agents, prefer the answer that is
more complete, better structured, and better grounded in retrieved KB context,
even if it is longer. Keep the answer concise enough to read, but do not omit
engineering details that affect setup, execution, debug, or result analysis.

Example: For Site Control questions, inspect related documents such as
`v93000/smt7/100118.md`, `v93000/smt7/100096.md`,
`v93000/smt7/100168.md`, `v93000/smt7/13863.md`,
`v93000/smt7/100119.md`, `v93000/smt7/100324.md`,
`v93000/smt7/20264.md`, and `v93000/smt7/21615.md` when they are
discovered as related sources.

## Directory Layout

| Path | Purpose |
|------|---------|
| `configs/config.yaml` | Central configuration (paths, models, retrieval params) |
| `src/ate_rag_kb/chunking/` | HierarchicalChunker: markdown -> document/section/subsection/paragraph/code/table/image chunks |
| `src/ate_rag_kb/embedding/` | EmbeddingEncoder: sentence-transformers wrapper (bge-m3) |
| `src/ate_rag_kb/ingestion/` | IngestionPipeline + IncrementalIngestion (mtime-based change detection) |
| `src/ate_rag_kb/retrieval/` | RetrievalCoordinator, scoped routing, HybridRetriever (dense + sparse), graph expansion, reranking, parent-child enrichment, compression |
| `src/ate_rag_kb/vector_store/` | QdrantVectorStore wrapper + schema/index setup |
| `src/ate_rag_kb/api/` | FastAPI app, routes, Pydantic models |
| `src/ate_rag_kb/mcp/` | MCP server (stdio), tool handlers, context builder |
| `src/ate_rag_kb/prompts/` | Prompt templates + Claude Code skill schema |
| `src/ate_rag_kb/evaluation/` | EvalRunner, metrics, dataset loader, formatters |
| `eval/` | Evaluation datasets, metrics, and reports |

## Common Commands

```bash
# Install dependencies
uv sync

# Run tests
uv run pytest tests/ -q

# Run tests with coverage
uv run pytest tests/ --cov=src/ate_rag_kb --cov-report=term

# Ingest documents (full)
uv run -m ate_rag_kb.cli.main ingest --dir ./data/raw/markdown

# Ingest documents (incremental)
uv run -m ate_rag_kb.cli.main ingest --dir ./data/raw/markdown --incremental

# Start API server
uv run -m ate_rag_kb.cli.main serve --host 0.0.0.0 --port 8080

# Start MCP server
uv run python scripts/start_mcp.py

# Search from CLI (developer/debugging fallback; not the default agent path)
uv run -m ate_rag_kb.cli.main search "timing set configuration" --top-k 5

# Run retrieval eval
uv run python scripts/run_eval.py

# Check collection stats
uv run -m ate_rag_kb.cli.main status
```

## Key Flows

### Ingestion Flow
1. `cli/main.py _cmd_ingest` builds `EmbeddingEncoder`, `QdrantVectorStore`, and
   `IngestionPipeline`.
2. Full ingest clears the collection, rebuilds sparse vocabulary, ingests all
   markdown, rebuilds graph/catalog artifacts, and records the current
   profile-specific state file.
3. Incremental ingest uses `IncrementalIngestion.run_incremental`; state files
   live under `data/processed/state_{profile_hash}.json`.
4. The profile hash covers backend mode, collection, embedding model, chunking
   config, document scopes, and ingestion schema version.
5. For changed files: `_chunk_document` -> `HierarchicalChunker.chunk` ->
   `_embed_and_upsert` -> `EmbeddingEncoder.encode` ->
   `QdrantVectorStore.upsert_chunks`.
6. Batch size defaults to 1000 chunks; memory errors trigger recursive halving.

### Retrieval Flow

1. `RetrievalCoordinator.retrieve` resolves scopes and answer mode.
2. Each resolved scope calls `RetrievalPipeline.retrieve_enriched` with scoped
   filters and an enhanced query.
3. `HybridRetriever.retrieve` (sync, wrapped in `asyncio.to_thread`)
   - Vector search via `QdrantVectorStore.search` (top 20)
   - Sparse vector search if available
   - Reciprocal Rank Fusion (dense + sparse)
   - Legacy BM25 fallback when sparse is unavailable
4. Optional: `DocumentGraphExpander.expand`
   - Follows internal document links with bounded hops
   - Narrow queries: 1 hop, limited budget
   - Broad concept queries: up to 2 hops, expanded budget
5. Optional: `Reranker.rerank` (cross-encoder)
   - **Graph-expanded candidates always participate in reranking**
   - Exact title/API matches can be preserved after rerank
   - Narrow queries: retain top 5 (default)
   - Broad concept queries: use independent candidate budget and
     source-diverse selection to preserve coverage across multiple documents
6. Optional: `ParentChildExpander.expand` (batched `get_by_ids`)
7. Optional: `ContextCompressor.compress` (dedup, merge adjacent, token cap)
8. Coordinator returns isolated groups, citations, processing diagnostics, and
   an `answer_contract` for agent synthesis.

**Query-type behavior:**

| Aspect | Narrow Query | Broad Concept Query |
|--------|-------------|---------------------|
| Graph hops | 1 | Up to 2 |
| Rerank budget | Small (top 5) | Expanded (`broad_candidate_top_k`) |
| Source diversity | Not applied | Applied (`broad_max_sources`) |
| Final top-k | Default | `broad_final_top_k` |

### /ask Flow
1. `routes.ask` uses `RetrievalCoordinator` when available.
2. Coordinator routes the query to one or more scopes.
3. Each scope runs the enriched retrieval path with dense + sparse search,
   graph expansion, reranking, and context compression.
4. The response includes citations, `source_md`, scoped processing diagnostics,
   and an `answer_contract`. The agent synthesizes the final natural-language
   answer from that grounded context.

### MCP Flow
1. Agent sends JSON-RPC request via stdio
2. `mcp/server.py` dispatches to `McpToolHandler`
3. Handler delegates `search`, `retrieve`, and `ask` to `RetrievalCoordinator`
4. Results are grouped by scope and formatted into structured JSON
5. Returned to agent as `TextContent`

`ate_kb.get_document` should call `RetrievalPipeline.get_document_page()` with
`limit` and `offset`; do not reintroduce full-document fetch-then-slice behavior
in MCP handlers.

## Configuration Notes

- `configs/config.yaml` is the single source of truth.
- `Config` class supports dot-notation: `config.get("embedding.model_name")`.
- Chunking limits are read from `chunking.strategies.*.max_length` and `overlap`.
- The `paragraph_threshold` defaults to `max(800, section_max_length // 5)`.

### Retrieval configuration options

These keys can be added to `configs/config.yaml` under `retrieval.reranker`:

| Key | Description | Default |
|-----|-------------|---------|
| `broad_candidate_top_k` | Candidate budget before coverage selection for broad queries | 40 |
| `broad_final_top_k` | Final chunk count after coverage selection for broad queries | 14 |
| `broad_max_sources` | Maximum distinct sources to retain in a broad query result | 8 |
| `broad_min_sources` | Minimum source-diverse base before topic coverage fill | 3 |
| `broad_max_chunks_per_source` | Maximum reranked chunks retained per source | 3 |

The `retrieval.broad_context` section controls automatic context assembly. Its
default budget is 32 discovered sources, 16 final chunks, and about 9000 tokens.

### State Isolation and Profile Changes

Incremental ingestion state is stored per profile (hash of backend mode,
collection name, embedding model, chunking config, and document scope).
Switching any of these settings automatically triggers a full re-ingest:

- Old `data/processed/ingestion_state.json` is preserved as `.json.legacy`
- A new profile-specific state file is created under `data/processed/state_{hash}.json`
- The collection is cleared before the full rebuild to remove stale points
- Full ingest records the current profile state after a successful rebuild, so
the next `--incremental` run can scan for real changes instead of rebuilding
again immediately.

### Migration from Local Mode

If you previously ingested into `./data/qdrant_storage/` (local mode) and want
to switch to server mode:

1. Update `configs/config.yaml`: set `vector_store.mode: server`.
2. Start the Qdrant server (`docker compose up -d qdrant`).
3. Re-run ingestion (server collections are independent of local files):
   ```bash
   uv run -m ate_rag_kb.cli.main ingest --dir ./data/raw/markdown
   ```
4. Verify:
   ```bash
   uv run -m ate_rag_kb.cli.main status
   ```

There is no automatic migration path from local files to server collections;
re-ingestion is required once.

## Development Conventions

### Immutability (CRITICAL)
- NEVER mutate existing Chunk objects. ALWAYS return new copies.
- Use `dataclasses.replace` when deriving modified chunks.
- Do not add new violations, and fix existing ones when encountered.

### Error Handling
- Explicit error handling at every level; never swallow exceptions silently.
- Ingestion isolates failures per file and per batch.

### Naming
- `camelCase` for variables/functions.
- `PascalCase` for types/components.
- Booleans prefixed with `is`/`has`/`should`.

### File Size
- Keep files under 800 lines; split large modules.

## Testing Strategy

- Unit tests for pure logic (chunking, config, filters).
- Mock external deps (Qdrant, embedding model) for fast unit tests.
- Integration tests should spin up real Qdrant (use temporary directory).
- **Coverage gate: 80% minimum.**
- Run ruff before commit: `uv run ruff check src/ tests/`

## Common Pitfalls

1. **Qdrant API drift**: The project uses `query_points` (not old `search`). Mock tests
   must match the actual API call.
2. **Embedding memory**: Large batches can OOM on MPS/CUDA. `_embed_and_upsert` has
   recursive halving, but batch_size should still be conservative on GPU.
3. **Global config singleton**: `get_config()` caches the first loaded config. In tests,
   call `reload_config()` or patch `_config_instance` to None.
4. **Local files only**: `embedding.local_files_only: true` means models must be
   pre-downloaded to `./embeddings/cache`. First-time setup requires internet.
5. **Chunk ID determinism**: IDs are SHA256 hashes of source + title + suffix + content
   snippet. Changing chunking logic changes IDs, breaking incremental state.
6. **MCP stdio transport**: Must not write to stdout except JSON-RPC messages. Use
   logging (stderr) or structured logging for diagnostics.

## Agent Rules (for dev agents)

When modifying code, prioritize:

1. **Fix immutability violations** — return new objects instead of mutating.
2. **Read config from `config.yaml`** — do not add new hardcoded constants in source.
   If a new tunable is needed, add it to `config.yaml` and read via `Config.get()`.
3. **Keep functions under 50 lines** — extract helpers.
4. **Add tests for new logic** — maintain 80%+ coverage.
5. **Update eval dataset if behavior changes** — if chunking/retrieval logic changes,
   re-run `scripts/run_eval.py` and update golden expectations if the change is
   intentional.
6. **Do not break the incremental ingestion contract** — full ingest must record
   the current profile state; incremental ingest must only reuse state when the
   profile metadata matches the current config.
7. **MCP changes must not break FastAPI** — both share `RetrievalCoordinator`
   and `RetrievalPipeline`. Keep transport-specific formatting in API/MCP
   handlers, not in the retrieval core.

## Protected Directories

- `data/raw/` — Original documents. NEVER modify in-place; treat as immutable source.
- `data/qdrant_storage/` — Local Qdrant data. Do not manually delete while server is running.
- `data/processed/state_*.json` — Profile-specific incremental ingestion state. Do not edit manually unless explicitly repairing a verified rebuilt collection.
- `embeddings/cache/` — Downloaded transformer models. Large; do not commit.
- `eval/v1/` — Evaluation datasets. Version-controlled; do not overwrite without bumping version.

## Current Priority Tasks

1. **Keep multi-platform acceptance green** — run `uv run scripts/validate_multi_platform_retrieval.py` after ingestion or routing changes.
2. **Preserve scope isolation** — IG-XL/J750 answers must not cite SMT7 sources, and SMT7/V93000 answers must not cite IG-XL sources.
3. **Prepare SMT8 enablement** — add `advantest / v93000 / smt8` only after SMT8 raw docs are available and a full ingest has been run.
4. **Add CI gate** — pytest -> ruff -> multi-platform retrieval validator.
