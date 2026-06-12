---
name: "ate-kb-router"
description: "Use for any ATE documentation or semiconductor test engineering question, including SmarTest, SMT7, SMT8, TDC, Advantest V93000, Teradyne J750, IG-XL, pin configuration, timing, levels, patterns, DPS, PMU, test flow, tester behavior, command syntax, API references, or requests that should use the ate_kb MCP knowledge base."
---

# ATE KB Router

Use this skill before answering ATE domain questions. Engineers should ask
questions naturally; do not ask them to choose MCP, CLI search, grep, or raw
document reads.

## Required Route

1. Use `ate_kb` MCP before any other source.
2. In Codex, if `ate_kb.status`, `ate_kb.ask`, `ate_kb.retrieve`,
   `ate_kb.search`, or `ate_kb.get_document` are not visible, first call
   `tool_search` with:

```text
ate_kb status ask retrieve search get_document
```

3. If MCP availability is uncertain, call `ate_kb.status`.
4. For direct questions needing citations, call `ate_kb.ask`.
5. For specific technical retrieval, call `ate_kb.retrieve`.
6. Use `ate_kb.search` only for exploratory discovery or locating source files.
7. Use `ate_kb.get_document` only after `ate_kb.ask` or `ate_kb.retrieve`
   identifies relevant `source_md` files. For large documents, pass explicit
   `limit` and `offset`.

## Forbidden First Sources

Do not answer ATE KB questions from model memory, WebSearch, shell `grep`, `rg`,
CLI search, or raw markdown reads before trying MCP. These are fallbacks only
when MCP is unavailable, fails, or returns insufficient context.

## Answer Contract

When the answer comes from the KB, cite:

- `source_md`
- `section_title`
- relevant document, command, API, window, or configuration names

If fallback sources were used, state why MCP was unavailable or insufficient.
