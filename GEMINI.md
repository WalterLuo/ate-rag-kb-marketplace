# ATE RAG Knowledge Base — Gemini Guide

## Project Overview

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

## MCP Tools Available

When the ate_kb MCP server is connected, these tools are available:

- `ate_kb.search` — exploratory semantic search
- `ate_kb.retrieve` — hybrid + rerank retrieval with citations
- `ate_kb.ask` — direct Q&A with citations
- `ate_kb.related` — parent/sibling/children for a chunk
- `ate_kb.get_document` — full document content

## ATE KB Question Policy

For any technical question about ATE documentation, SmarTest, TDC, V93000,
J750, IG-XL, pin configuration, timing, levels, patterns, DPS, PMU, test flow,
tester behavior, or command syntax:

1. Use MCP tools first.
2. Prefer `ate_kb.retrieve` for specific technical answers.
3. Prefer `ate_kb.ask` for direct Q&A that needs citations.
4. Use `ate_kb.get_document` only after relevant `source_md` files are identified.
5. Use `ate_kb.search` only for exploratory discovery.
6. Cite `source_md`, `section_title`, and relevant command/document names.

Do not answer ATE KB questions from model memory, public web search, shell
grep/rg, CLI search, or raw markdown reads before trying MCP. Use those
fallbacks only when MCP is unavailable, fails, or returns insufficient context,
and state the fallback reason in the final answer.

## Canonical Terminology

| Vendor | Tester platform | Software |
|--------|-----------------|----------|
| Advantest | V93000 | SMT7, SMT8 |
| Teradyne | J750 | IG-XL |

V93000 and J750 are tester platforms. SMT7, SMT8, and IG-XL are software scopes.

## Common Commands

```bash
# Install dependencies
uv sync

# Ingest documents
uv run -m ate_rag_kb.cli.main ingest --dir ./data/raw/markdown

# Start API server
uv run -m ate_rag_kb.cli.main serve --host 0.0.0.0 --port 8080

# Start MCP server
uv run -m ate_rag_kb.cli.main mcp

# Search from CLI
uv run -m ate_rag_kb.cli.main search "timing set configuration" --top-k 5
```

## Directory Layout

| Path | Purpose |
|------|---------|
| `configs/config.yaml` | Central configuration |
| `src/ate_rag_kb/chunking/` | Hierarchical chunker |
| `src/ate_rag_kb/embedding/` | Embedding encoder (bge-m3) |
| `src/ate_rag_kb/ingestion/` | Ingestion pipeline |
| `src/ate_rag_kb/retrieval/` | Retrieval coordinator & pipeline |
| `src/ate_rag_kb/vector_store/` | Qdrant wrapper |
| `src/ate_rag_kb/api/` | FastAPI app |
| `src/ate_rag_kb/mcp/` | MCP server (stdio) |

## Development Conventions

- Immutability: NEVER mutate existing Chunk objects. Use `dataclasses.replace`.
- Error handling: Explicit at every level; never swallow exceptions.
- Naming: `camelCase` for vars/functions, `PascalCase` for types.
- File size: Keep files under 800 lines.
- Test coverage: 80% minimum.
