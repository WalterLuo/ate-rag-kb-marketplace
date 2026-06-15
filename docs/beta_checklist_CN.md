# Beta 试用清单

工程师试用 ATE RAG 知识库时的逐项检查表。

当前状态：Beta 已可交付给工程师继续试用。第一次真实试用通过 9/10；在修复
ARRAY 引用、补充预期答案覆盖点、实现文档分页读取后，前 5 个重点问题已复测
通过。复测证据记录在 `docs/archive/10q_retest.csv`。

---

## A. 环境准备

- [ ] 已安装 Python / uv
- [ ] `uv sync` 已完成且无报错
- [ ] `configs/config.yaml` 存在
- [ ] `data/raw/markdown/` 中包含内置文档
- [ ] 已至少运行过一次 ingest
- [ ] Qdrant server 正在运行（`docker compose up -d qdrant`）
- [ ] `uv run -m ate_rag_kb.cli.main status` 返回 `ok` 且 `total_chunks > 0`

### 多平台生产重建与门禁

用于验证 IG-XL / J750 与 SMT7 / V93000 不再互相污染。规范术语如下：

| 厂商 | 测试平台 | 软件 |
|------|----------|------|
| Advantest | V93000 | SMT7、SMT8 |
| Teradyne | J750 | IG-XL |

- [ ] `configs/config.yaml` 的 `documents.enabled_scopes` 至少包含
  `teradyne / j750 / igxl` 和 `advantest / v93000 / smt7`
- [ ] Qdrant server 可连接：
  ```bash
  uv run -m ate_rag_kb.cli.main status
  ```
- [ ] 执行全量重建：
  ```bash
  uv run -m ate_rag_kb.cli.main ingest --dir data/raw/markdown
  ```
- [ ] 运行 deterministic acceptance matrix：
  ```bash
  uv run python -m pytest tests/retrieval/test_multi_platform_acceptance.py -q
  ```
- [ ] 验证重建产物和运行时检索行为：
  ```bash
  uv run scripts/validate_multi_platform_retrieval.py
  ```
- [ ] 重启 MCP server 后，通过 `ate_kb.ask` 验证以下查询：
  `IG-XL 多 site 串行处理怎么实现？`、`SMT7 Site Control 怎么用？`、
  `多 site 串行处理怎么实现？`、`SMT7 SelectFirst 怎么用？`
- [ ] 验证 IG-XL 答案引用 `igxl/vbt/execSites.39.08.md`、
  `igxl/vbt/execSites.39.09.md`、`igxl/vbt/execSites.39.45.md`，且包含
  `SelectFirst`、`SelectNext`、`loopDone`
- [ ] 验证 SMT7 答案引用 SMT7 来源，包含 `ON_FIRST_INVOCATION_BEGIN`，
  且不混入 `SelectFirst`
- [ ] 验证中性查询输出两段隔离答案：`J750 / IG-XL` 与 `V93000 / SMT7`
- [ ] 验证 `SMT7 SelectFirst 怎么用？` 会给出纠正提示，并只从 IG-XL 来源回答

---

## B. MCP 配置

- [ ] 已复制 `.mcp.example.json` 为 `.mcp.json`（或直接在 agent 中配置了 MCP）
- [ ] 已将 `/path/to/ate-rag-kb` 替换为项目绝对路径
- [ ] `CONFIG_PATH` 使用了绝对路径
- [ ] 配置后已重启 agent
- [ ] Agent 能看到全部 `ate_kb.*` 工具
- [ ] `ate_kb.status` 返回 `ok`

---

## C. 基础查询验证

向 agent 提出以下 10 个 Beta 试用问题。这些问题来自第一次真实工程师试用记录。每个问题检查：

1. Agent 使用了 MCP 工具
2. 回答内容相关
3. 回答包含 `source_md`
4. 回答包含 `section_title` 或 `doc_title`
5. 没有明显幻觉
6. 如果下方列出了必答关键点，回答必须覆盖这些关键点

### 问题列表

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

### 必答关键点

| 序号 | 必须覆盖的内容 |
|------|----------------|
| 1 | 尽量引用 `v93000/smt7/29504.md` / `v93000/smt7/120084.md`。必须包含 `LIMIT(TM::COMPARE opl, DOUBLE low, TM::COMPARE oph, DOUBLE high)`、`TM::GT` / `TM::GE` / `TM::LT` / `TM::LE` / `TM::NA` 等比较符，以及代码级使用方式。 |
| 2 | 必须引用 ARRAY 相关来源，例如 `v93000/smt7/130224.md`（`Array in MTL`）和 `v93000/smt7/102025.md`（`APG program file syntax`）。没有引用不能通过。 |
| 3 | 必须引用 Site Match / site control 相关来源，例如 `v93000/smt7/21615.md`。需要解释 ON、OFF、AUTO、依次启动、同步启动，以及 shared analog/digital module 对默认行为的影响。 |
| 4 | 需要说明 port、pin、multi-port timing、多时钟域测试之间的关系。 |
| 5 | 尽量引用 `v93000/smt7/101980.md` 等 timing file 来源。必须覆盖 device cycles、edges、waveforms、clocks、equation set、timing set、spec set、wavetable，以及 `.tim`、`.wvt`、`.eqn`、`.ac_spec` 等文件形式。 |
| 6 | 对 RDI_Configure 这类大文档，必须用 `ate_kb.get_document` 分页读取，不能一次性读取全文。 |
| 7 | 对 technology file 这类大文档，必须用 `ate_kb.get_document` 分页读取，并引用具体来源。 |
| 8 | 需要覆盖主要 testflow flags，并引用 flag 主文档或各 flag 子文档。 |
| 9 | 需要覆盖 timing diagram 的打开/使用方式、显示模式、分辨率模式、坐标轴行为和信号显示规则，并给出引用。 |
| 10 | 需要覆盖 level / DPS setup 文档中 DPS pin 可配置字段，并引用来源。 |

### 检查表

| 序号 | 问题 | 使用 MCP | 内容相关 | 含 source_md | 含 section_title | 无幻觉 | 通过 |
|------|------|----------|----------|--------------|------------------|--------|------|
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

## D. 分页验证

- [ ] Agent 能先通过 `retrieve` / `ask` 找到 `source_md`
- [ ] Agent 能调用 `get_document` 并使用 `limit` 参数
- [ ] 返回结果包含 `has_more` 和 `next_offset`
- [ ] Agent 不会一次性读取整篇大文档

使用以下大文档进行分页验证：

| Source | 主题 | 要求 |
|--------|------|------|
| `v93000/smt7/146692.md` | RDI_Configure file | 使用 `limit` 读取，只在需要时继续按 `offset` 翻页 |
| `v93000/smt7/13920.md` | Using the Timing Diagram Tool | 不允许一次性读取全文 |
| `v93000/smt7/49363_2.md` | Technology file for a device | 使用分页并引用具体 section |

---

## E. 低置信度验证

- [ ] 对于明显无关的问题，agent 会说明不确定
- [ ] Agent 不会编造不存在的 API、命令或错误码
- [ ] 当结果较差时，agent 会建议更具体的查询方式

---

## F. 失败记录模板

在此处记录所有失败案例：

| 问题 | 期望结果 | 实际结果 | 是否通过 | 失败类型 | 备注 |
|------|----------|----------|----------|----------|------|
| | | | | | |

### 失败类型说明

- `retrieval_miss` — 未返回相关 chunk
- `wrong_source` — 引用指向了无关文档
- `no_citation` — 回答缺少 `source_md` / `section_title` / `chunk_id`
- `hallucination` — Agent 编造了知识库中不存在的事实
- `tool_error` — MCP 工具调用失败或返回错误
- `payload_too_large` — `get_document` 返回了过量数据
- `slow_response` — 响应时间异常长
- `unclear_answer` — 回答模糊或未回答问题

---

## G. Broad Concept Query 检查项

对于 broad concept 类问题（如 Q3 site control、Q8 test flow flags）：

- [ ] graph expansion 后的 source 不应被 reranker 全部裁掉
- [ ] 必须检查 source diversity：MCP `processing` 中 `post_diversity_source_count >= 3`
- [ ] 自动覆盖组装已执行：`broad_context_assembled == true`
- [ ] `coverage_topics` 包含可用于回答的正文子主题，不能只有标题、图片或版本变更记录
- [ ] `answer_contract.completeness_required == true`，最终回答不能只有摘要
- [ ] 最终回答覆盖每个适用的 `answer_contract.coverage_topics` 项，或明确说明为何不纳入回答范围
- [ ] 不允许依赖 source hints
- [ ] 不允许只验证 graph 可达性，还要验证最终 context package 的 source 覆盖率
- [ ] 记录 MCP processing 数据和调用耗时

## H. Beta 通过标准

满足以下全部条件时，Beta 试用通过：

- [ ] 10 个问题全部产生可用回答
- [ ] 每个回答都包含规范引用（`source_md`、`section_title`）
- [ ] Q2 ARRAY 已包含引用，不再出现 `no_citation`
- [ ] Q1 / Q3 / Q5 覆盖上方列出的必答关键点
- [ ] 未观察到严重幻觉
- [ ] MCP 工具调用稳定（无频繁 JSON-RPC 错误）
- [ ] `get_document` 未返回超大 payload
- [ ] Broad concept query 通过 G 节中的 source-diversity 检查
- [ ] 所有失败案例已记录在上方的失败日志中

第一次真实 Beta 试用结果见
[Beta 10-Question Trial Report](archive/beta_test_report_10q.md)。
修复后的复测流程见
[Beta 10-Question Retest Plan](archive/beta_retest_10q.md)。
