# Beta Trial Checklist

Use this checklist when onboarding engineers to the ATE RAG Knowledge Base.

Current status: beta is ready for engineer handoff. The first recorded run
passed 9/10 questions; the priority retest for questions 1-5 passed after the
ARRAY citation, expected-answer coverage, and paginated document retrieval
fixes. Retest evidence is recorded in `docs/archive/10q_retest.csv`.

---

## A. Environment Preparation

- [ ] Python / `uv` is installed
- [ ] `uv sync` completed without errors
- [ ] `configs/config.yaml` exists
- [ ] `data/raw/markdown/` contains built-in documents
- [ ] Ingestion has been run at least once
- [ ] Qdrant server is running (`docker compose up -d qdrant`)
- [ ] `uv run -m ate_rag_kb.cli.main status` returns `ok` with `total_chunks > 0`

---

## B. MCP Configuration

- [ ] Copied `.mcp.example.json` to `.mcp.json` (or configured agent MCP directly)
- [ ] Replaced `/path/to/ate-rag-kb` with the absolute project path
- [ ] `CONFIG_PATH` uses an absolute path
- [ ] Agent was restarted after MCP configuration
- [ ] Agent can see all `ate_kb.*` tools
- [ ] `ate_kb.status` returns `ok`

---

## C. Basic Query Validation

Ask the agent the following 10 beta trial questions. These are real engineer
questions from the first recorded beta run. For each, verify:

1. The agent used an MCP tool
2. The answer is relevant
3. The answer includes `source_md`
4. The answer includes `section_title` or `doc_title`
5. No obvious hallucination
6. The answer covers the required key points when listed below

### Questions

1. smt7中，如何在测试代码中通过代码的方式写limit
2. smt7中ARRAY在代码中的作用是什么
3. smt7中test suite的site control都有什么用处
4. smt7中port pin的用处是什么
5. smt7中timing文件都包含哪些内容？可以以哪种文件格式被使用
6. smt7中RDI_Configure文件中都有哪些配置，每个配置都是什么意思
7. smt7中 change device的edit device中的各项设置都有什么用处
8. smt7中test flow的都有哪些flags，每个flags的配置有什么作用
9. smt7中timing diagram怎么使用
10. smt7中，level eqnset里可以对dps pin做哪些配置

### Required Key Points

| # | Required coverage |
|---|-------------------|
| 1 | Cite `v93000/smt7/29504.md` / `v93000/smt7/120084.md` when available. Include `LIMIT(TM::COMPARE opl, DOUBLE low, TM::COMPARE oph, DOUBLE high)`, comparison operators such as `TM::GT` / `TM::GE` / `TM::LT` / `TM::LE` / `TM::NA`, and code-level usage. |
| 2 | Cite ARRAY sources such as `v93000/smt7/130224.md` (`Array in MTL`) and `v93000/smt7/102025.md` (`APG program file syntax`). Do not pass if the answer has no citation. |
| 3 | Cite Site Match / site control sources such as `v93000/smt7/21615.md`. Explain ON, OFF, AUTO, successive starts, simultaneous starts, and shared analog/digital module behavior. |
| 4 | Explain the relationship between ports, pins, multi-port timing, and multi-clock-domain use. |
| 5 | Cite timing-file sources such as `v93000/smt7/101980.md`. Cover device cycles, edges, waveforms, clocks, equation set, timing set, spec set, wavetable, and file forms such as `.tim`, `.wvt`, `.eqn`, `.ac_spec`. |
| 6 | For large RDI documents, use `ate_kb.get_document` pagination instead of one full-document call. |
| 7 | For large technology-file documents, use `ate_kb.get_document` pagination and cite the exact source document. |
| 8 | Cover the main testflow flags and cite each major source or the testflow flag index document. |
| 9 | Cover timing diagram opening/use, display modes, resolution modes, axis behavior, and signal display rules with citations. |
| 10 | Cover DPS pin configuration fields from the level / DPS setup source and cite the source document. |

### Checklist

| # | Question | MCP Used | Relevant | `source_md` | `section_title` | No Hallucination | Pass |
|---|----------|----------|----------|-------------|-----------------|------------------|------|
| 1 | smt7中，如何在测试代码中通过代码的方式写limit | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 2 | smt7中ARRAY在代码中的作用是什么 | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 3 | smt7中test suite的site control都有什么用处 | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 4 | smt7中port pin的用处是什么 | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 5 | smt7中timing文件都包含哪些内容？可以以哪种文件格式被使用 | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 6 | smt7中RDI_Configure文件中都有哪些配置，每个配置都是什么意思 | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 7 | smt7中 change device的edit device中的各项设置都有什么用处 | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 8 | smt7中test flow的都有哪些flags，每个flags的配置有什么作用 | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 9 | smt7中timing diagram怎么使用 | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 10 | smt7中，level eqnset里可以对dps pin做哪些配置 | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |

---

## D. Pagination Verification

- [ ] Agent can first `retrieve` / `ask` to discover `source_md`
- [ ] Agent can call `get_document` and uses a `limit` parameter
- [ ] Response includes `has_more` and `next_offset`
- [ ] Agent does **not** fetch the entire large document in a single call

Use these large-document checks:

| Source | Topic | Required behavior |
|--------|-------|-------------------|
| `v93000/smt7/146692.md` | RDI_Configure file | Fetch with `limit` and continue by `offset` only as needed |
| `v93000/smt7/13920.md` | Using the Timing Diagram Tool | Do not fetch the whole document in one call |
| `v93000/smt7/49363_2.md` | Technology file for a device | Use pagination and cite exact sections |

---

## E. Low-Confidence Verification

- [ ] For an obviously off-topic question, the agent states uncertainty
- [ ] Agent does **not** fabricate APIs, commands, or error codes
- [ ] Agent suggests a more specific query when results are poor

---

## F. Failure Log Template

Record any failures here:

| Question | Expected | Actual | Pass? | Failure Type | Notes |
|----------|----------|--------|-------|--------------|-------|
| | | | | | |

### Failure Types

- `retrieval_miss` — No relevant chunks returned
- `wrong_source` — Citation points to unrelated document
- `no_citation` — Answer lacks `source_md` / `section_title` / `chunk_id`
- `hallucination` — Agent invented facts not in the KB
- `tool_error` — MCP tool call failed or returned an error
- `payload_too_large` — `get_document` returned excessive data
- `slow_response` — Response took an unreasonably long time
- `unclear_answer` — Answer is vague or does not address the question

---

## G. Broad-Concept Query Checks

For questions that ask broad concepts (e.g. Q3 site control, Q8 test flow flags):

- [ ] Graph-expanded sources are **not** completely pruned by the reranker
- [ ] Source diversity is verified: `post_diversity_source_count >= 3`
  in the MCP `processing` field
- [ ] Automatic coverage assembly ran: `broad_context_assembled == true`
- [ ] `coverage_topics` contains content-bearing subtopics, not only titles,
  images, or functional-change notes
- [ ] `answer_contract.completeness_required == true`; the final answer is not
  only a summary
- [ ] The final answer covers every applicable `answer_contract.coverage_topics`
  item, or explicitly states why it is outside the answer scope
- [ ] The answer does **not** rely on hardcoded source hints
- [ ] Final context package source coverage is checked, not just graph reachability
- [ ] MCP `processing` data and call latency are recorded for analysis

## H. Beta Pass Criteria

Beta is **approved** when all of the following are met:

- [ ] All 10 questions produce usable answers
- [ ] Every answer includes proper citations (`source_md`, `section_title`)
- [ ] Q2 ARRAY includes citations and no longer fails for `no_citation`
- [ ] Q1 / Q3 / Q5 cover the required key points listed above
- [ ] No serious hallucinations observed
- [ ] MCP tool calls are stable (no repeated JSON-RPC errors)
- [ ] `get_document` never returns an oversized payload
- [ ] Broad-concept queries pass the source-diversity checks in Section G
- [ ] Any failures are documented in the Failure Log above

For the first recorded beta trial result, see
[Beta 10-Question Trial Report](archive/beta_test_report_10q.md).
For the post-fix retest procedure, see
[Beta 10-Question Retest Plan](archive/beta_retest_10q.md).
