# Beta 10-Question Retest Plan

Use this plan after restarting the agent/MCP server with the latest code. The
goal is to confirm that the first beta trial has moved from 9/10 to 10/10 and
that large documents are read through pagination.

## Current Retest Status

The priority retest for questions 1-5 has been completed and recorded in
`docs/archive/10q_retest.csv`. All five retested questions passed with MCP usage,
`source_md`, `section_title`, and no hallucination recorded. Questions 6-10
passed in the first beta trial and were not repeated in this retest cycle.

Current project status: ready for engineer handoff.

## Before Retest

1. Restart the MCP client or coding agent. Running MCP servers do not hot-reload
   code changes.
2. Confirm the agent can see all six tools:
   - `ate_kb.search`
   - `ate_kb.retrieve`
   - `ate_kb.ask`
   - `ate_kb.related`
   - `ate_kb.get_document`
   - `ate_kb.status`
3. Run `ate_kb.status` and confirm `status=ok` and `total_chunks > 0`.

## Retest Questions

Run the exact questions from `docs/beta_checklist_CN.md`.

Priority checks:

| Question | Must verify |
|----------|-------------|
| Q1 limit | Includes `LIMIT(TM::COMPARE opl, DOUBLE low, TM::COMPARE oph, DOUBLE high)` and comparison operators |
| Q2 ARRAY | Includes citations from ARRAY sources, especially `20847.md`, `130224.md`, or `102025.md` |
| Q3 site control | Explains ON/OFF/AUTO and shared module behavior |
| Q5 timing file | Covers timing content and file forms such as `.tim`, `.wvt`, `.eqn`, `.ac_spec` |
| Q6/Q7/Q9 large docs | Uses `ate_kb.get_document` with `limit` / `offset` rather than one full-document read |

## Pass Criteria

| Criterion | Required |
|-----------|----------|
| 10-question pass rate | 10 / 10 |
| MCP usage | 10 / 10 |
| `source_md` coverage | 10 / 10 |
| `section_title` or `doc_title` coverage | 10 / 10 |
| Q2 ARRAY citation regression | Pass |
| Q1/Q3/Q5 completeness | Pass |
| Large-document pagination | Pass |
| Serious hallucination count | 0 |

## Result Template

| # | Question | MCP Used | Relevant | Citations | Key Points | Pagination | Pass |
|---|----------|----------|----------|-----------|------------|------------|------|
| 1 | limit | [ ] | [ ] | [ ] | [ ] | N/A | [ ] |
| 2 | ARRAY | [ ] | [ ] | [ ] | [ ] | N/A | [ ] |
| 3 | site control | [ ] | [ ] | [ ] | [ ] | N/A | [ ] |
| 4 | port pin | [ ] | [ ] | [ ] | [ ] | N/A | [ ] |
| 5 | timing file | [ ] | [ ] | [ ] | [ ] | N/A | [ ] |
| 6 | RDI_Configure | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 7 | change device / edit device | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 8 | test flow flags | [ ] | [ ] | [ ] | [ ] | N/A | [ ] |
| 9 | timing diagram | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 10 | level eqnset DPS pin | [ ] | [ ] | [ ] | [ ] | N/A | [ ] |

## If Q2 Still Fails

If Q2 does not cite ARRAY sources after restart:

1. Confirm the agent was restarted after the code change.
2. Call `ate_kb.retrieve` directly with:
   `smt7中ARRAY在代码中的作用是什么`
3. Check whether the returned `source_files` / chunks include `20847.md`,
   `130224.md`, or `102025.md`.
4. If the sources are present but the final answer omits citations, the failure
   is in agent synthesis behavior, not retrieval.
5. If the sources are absent, inspect MCP server logs and rerun
   `uv run pytest tests/mcp -q`.
