# Beta 10-Question Trial Report

This report records the first engineer-facing beta trial for the ATE RAG
Knowledge Base. The trial validates whether an agent can answer real
SmarTest/TDC questions through MCP tools with grounded citations.

Source review file: `docs/archive/CheckTable.numbers`

Retest evidence file: `docs/archive/10q_retest.csv`

## Summary

| Metric | Result |
|--------|--------|
| Total questions | 10 |
| MCP used | 10 / 10 |
| Initial trial passed | 9 / 10 |
| Initial trial failed | 1 / 10 |
| Initial answers with `source_md` | 9 / 10 |
| Initial answers with `section_title` | 9 / 10 |
| Priority retest passed | 5 / 5 |
| Final beta acceptance status | Ready for engineer handoff |
| Serious hallucinations | 0 |

## Stage Assessment

The project has completed the priority beta retest. The first trial proved the
MCP path was usable for real engineer questions, but exposed one citation
failure and several answers that needed stronger expected-key-point coverage.
After the ARRAY source-hint fix, large-document pagination change, and checklist
updates, the first five priority questions were retested and passed.

The current acceptance status is:

- Functional MCP use: pass
- Engineer usability: pass
- Citation completeness: pass for priority retest
- Regression coverage for real trial questions: added
- Large-document pagination: implemented for MCP `get_document`
- Engineer handoff readiness: pass

## Question Results

| # | Question | Result | Notes |
|---|----------|--------|-------|
| 1 | smt7中，如何在测试代码中通过代码的方式写limit | Pass with improvement needed | Answer was relevant and cited, but should explicitly include the full `LIMIT(TM::COMPARE opl, DOUBLE low, TM::COMPARE oph, DOUBLE high)` signature and comparison operators. |
| 2 | smt7中ARRAY在代码中的作用是什么 | Fail | Answer lacked `source_md` and `section_title`. The final answer summarized likely meaning but did not provide grounded citations. |
| 3 | smt7中test suite的site control都有什么用处 | Pass with improvement needed | Answer was cited, but Site Match details should be more complete, including ON/OFF timing behavior and shared-module behavior. |
| 4 | smt7中port pin的用处是什么 | Pass | Answer was relevant and cited. |
| 5 | smt7中timing文件都包含哪些内容？可以以哪种文件格式被使用 | Pass with improvement needed | Answer was cited, but should cover equation set, timing set, spec set, wavetable, and file extensions more explicitly. |
| 6 | smt7中RDI_Configure文件中都有哪些配置，每个配置都是什么意思 | Pass | Answer covered the large configuration document and cited sources. |
| 7 | smt7中 change device的edit device中的各项设置都有什么用处 | Pass | Answer used MCP-discovered sources and cited them. |
| 8 | smt7中test flow的都有哪些flags，每个flags的配置有什么作用 | Pass | Answer used MCP and read multiple flag documents. |
| 9 | smt7中timing diagram怎么使用 | Pass | Answer used MCP-discovered timing diagram documents. |
| 10 | smt7中，level eqnset里可以对dps pin做哪些配置 | Pass | Answer used MCP and cited the DPS setup source. |

## Priority Retest Result

After restarting the agent/MCP server with the latest code, the first five
priority questions were retested and recorded in `docs/archive/10q_retest.csv`. These
questions covered the original ARRAY citation failure plus the Q1/Q3/Q5
completeness improvements.

| # | Retest status | Evidence |
|---|---------------|----------|
| 1 | Pass | Used MCP, included `source_md`, included `section_title`, no hallucination recorded. |
| 2 | Pass | Used MCP, included ARRAY source coverage including `20847.md`, included `source_md` and `section_title`, no hallucination recorded. |
| 3 | Pass | Used MCP, included `source_md`, included `section_title`, no hallucination recorded. |
| 4 | Pass | Used MCP, included `source_md`, included `section_title`, no hallucination recorded. |
| 5 | Pass | Used MCP, included `source_md`, included `section_title`, no hallucination recorded. |

The remaining five questions were already passing in the first trial and were
not repeated in this retest cycle. This moves the beta gate from "pending
retest" to "ready for engineer handoff."

## Required Regression Fixes

### Q2 ARRAY Citation Regression

Day 2 remediation status: code-level regression coverage added. MCP
`retrieve` / `ask` handlers now add curated source hints for the short,
ambiguous `ARRAY` term so authoritative ARRAY documents remain visible even
when dense retrieval initially recalls generic array examples. Restart the
agent/MCP server before rerunning the beta question because already-running MCP
servers do not hot-reload this code.

Expected behavior:

- The agent must use MCP first.
- The final answer must cite `source_md` and `section_title`.
- The answer must not rely on an uncited summary.

Expected relevant sources:

- `130224.md` — `Array in MTL`
- `102025.md` — `APG program file syntax`

Expected key points:

- In MTL/APG program files, ARRAY is a C-like array construct.
- ARRAY belongs to pattern/program syntax context, not a generic Python-like
  runtime structure.
- If the answer also discusses C++ Test Method API array classes such as
  `ARRAY_D` or `ARRAY_I`, those claims must have their own citations.

### Q1 Limit Completeness

Day 3 status: expected sources and key points have been added to the beta
checklists. The next beta retest must verify that the final synthesized answer
includes these items, not merely the retrieved context.

Expected sources:

- `29504.md` — `LIMIT`
- `120084.md` — `SMC_TEST()`
- `110432.md` — `TMLimits`

Expected key points:

- `LIMIT(TM::COMPARE opl, DOUBLE low, TM::COMPARE oph, DOUBLE high)`
- `opl` and `oph` are comparison operators.
- Common comparison operators include `TM::GT`, `TM::GE`, `TM::LT`, `TM::LE`,
  and `TM::NA`.
- `low`, `high`, and `unit()` can be used when building a limit object.
- Code-level usage should include an example such as
  `LIMIT(TM::GT, low_limit, TM::LT, high_limit)`.

### Q3 Site Control Completeness

Day 3 status: expected Site Match behavior has been added to the beta
checklists. The next beta retest must verify ON/OFF/AUTO and shared-module
behavior explicitly.

Expected source:

- `21615.md` — `Site Match Mode flag`

Expected key points:

- Site Match controls how sites start during parallel multi-site testing.
- ON starts sites successively with a slight delay.
- OFF starts all sites simultaneously.
- AUTO depends on pin configuration.
- Shared analog or digital modules cause the automatic behavior to select the
  simultaneous-start behavior.

### Q5 Timing File Completeness

Day 3 status: expected timing file content and file-form coverage has been added
to the beta checklists. The next beta retest must verify both content structure
and file extensions.

Expected sources:

- `101980.md` — `Timing file`
- `102150.md` — timing file usage in waveform mapping / configuration context
- `130561.md` — timing file list / file extension context

Expected key points:

- Timing files contain device cycles, edges, waveforms, and clocks.
- Timing content can include equation set, timing set, specification set, and
  wavetable content.
- Important file forms include `.tim`, `.wvt`, `.eqn`, and `.ac_spec`.
- The answer should distinguish a main timing file from split or referenced
  timing-related files.

## Large Document Pagination Requirement

Day 5 status: MCP `ate_kb.get_document` now uses a true paged retrieval path in
`RetrievalPipeline.get_document_page()` instead of fetching the entire document
and slicing it in the MCP handler.

Large-document answers in this trial sometimes relied on temporary-file style
fallbacks after reading very large sources. For beta handoff, agents should
prefer MCP pagination:

1. Use `ate_kb.retrieve` or `ate_kb.ask` to identify relevant `source_md`.
2. Call `ate_kb.get_document` with a bounded `limit`, such as `limit=10` or
   `limit=20`.
3. Continue with `offset=next_offset` only when more context is required.
4. Do not fetch a whole large document in one call.

Priority documents for pagination validation:

- `146692.md` — `RDI_Configure file`
- `13920.md` — `Using the Timing Diagram Tool`
- `49363_2.md` — `Technology file for a device`

## Beta Gate

The beta gate for the next trial is:

| Criterion | Required |
|-----------|----------|
| 10-question pass rate | 10 / 10 |
| MCP usage | 10 / 10 |
| `source_md` coverage | 10 / 10 |
| `section_title` coverage | 10 / 10 |
| Serious hallucination count | 0 |
| Large document pagination | Required for large sources |
| Raw markdown / grep as default path | Not allowed |

## Retest Handoff

The priority retest evidence is recorded in `docs/archive/10q_retest.csv`. For future
regression runs, use [Beta 10-Question Retest Plan](beta_retest_10q.md) after
restarting the agent/MCP server.
