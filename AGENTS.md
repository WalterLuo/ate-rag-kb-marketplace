# Agent Operating Policy

This repository is an ATE knowledge-base system for test engineers. Engineers
should be able to ask domain questions directly, without deciding which search
or retrieval command an agent should run.

## ATE KB Question Policy

When a user asks any technical or business question about ATE documentation,
SmarTest, TDC, V93000, pin configuration, timing, levels, patterns, DPS, PMU,
test flow, tester behavior, command syntax, or API references:

1. Use MCP tools first.
2. Prefer `ate_kb.retrieve` for answering specific technical questions.
3. Prefer `ate_kb.ask` when the user asks a direct question and needs citations.
4. Use `ate_kb.get_document` only after relevant `source_md` files are
   identified by `ate_kb.retrieve` or `ate_kb.ask`. Prefer pagination
   (`limit`, `offset`) for large documents rather than fetching all chunks
   at once. Use small limits such as 10 or 20 for large references.
5. Use `ate_kb.search` only for exploratory discovery or when locating source
   files.
6. Do not use `uv run -m ate_rag_kb.cli.main search`, shell `grep`, `rg`, or
   manual raw markdown reads as the first step for ATE KB questions.
7. Fall back to CLI, file search, or raw markdown reads only when MCP tools are
   unavailable, fail, or return insufficient context.
8. Do not ask the engineer which retrieval method to use. Select the retrieval
   strategy yourself.
9. Cite `source_md`, `section_title`, and command/document names in final
   answers when the answer comes from the KB.

### Deferred MCP Bootstrap

`ate_kb` may be a deferred MCP tool in Codex. If `ate_kb.status`,
`ate_kb.ask`, `ate_kb.retrieve`, `ate_kb.search`, or `ate_kb.get_document` are
not visible in the current tool list, do not answer from memory, web search,
shell search, or raw markdown reads. First expose the tools with `tool_search`
using a query such as:

```text
ate_kb status ask retrieve search get_document
```

After the tools are exposed, run `ate_kb.status` when availability is uncertain,
then answer with `ate_kb.ask` or `ate_kb.retrieve`. Web search is never the
first source for ATE KB questions and is allowed only after MCP is unavailable
or insufficient.

Default flow:

```text
User asks ATE question
-> if ate_kb tools are not visible, call tool_search for ate_kb
-> call ate_kb.retrieve or ate_kb.ask
-> inspect citations and context_package
-> call ate_kb.get_document with limit/offset only if full-document context is needed
-> synthesize the answer with citations
```

The CLI search command is a developer/debugging fallback. It returns only a
short content preview and should not be treated as the normal agent interface.

## Broad Concept Answer Policy

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

### Cross-Agent Answer Quality Alignment

For broad ATE concept answers, Codex and other agents should match the more
complete Claude Code answer style used for engineer-facing explanations.
Optimize for grounded completeness over brevity when the question asks
"what is", "what does it do", "how does it work", or otherwise asks for a
concept overview.

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

For broad concept questions, inspect related sources discovered through
retrieval result citations. Site Control acceptance may reference sources
such as `v93000/smt7/100118.md`, `v93000/smt7/100096.md`,
`v93000/smt7/100168.md`, `v93000/smt7/13863.md`,
`v93000/smt7/100119.md`, `v93000/smt7/100324.md`,
`v93000/smt7/20264.md`, and `v93000/smt7/21615.md`, but these paths must
not be used as runtime source hints or fixed recall rules.

## Beta Retest Policy

The current beta acceptance flow is documented in:

- `docs/beta_checklist_CN.md`
- `docs/beta_test_report_10q.md`
- `docs/beta_retest_10q.md`

For ARRAY questions, verify that final answers cite ARRAY-specific sources such
as `v93000/smt7/20847.md`, `v93000/smt7/130224.md`, or `v93000/smt7/102025.md`. For large documents, verify that
the agent uses `ate_kb.get_document` with explicit `limit` / `offset`.
