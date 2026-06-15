# Agent 端到端验证指南

本指南引导你正式验证 `ate-rag-kb` 是否已准备好通过 Claude Code、Codex、OpenClaw 或 Cursor 进行 Agent 使用。

---

## 1. 验证目标

在邀请真实工程师之前，确认以下内容：

- MCP server 无错误启动
- Agent 发现所有 `ate_kb.*` 工具
- `ate_kb.status` 返回健康的 collection 且 chunks 数量 > 0
- `ate_kb.retrieve` 返回相关、带引用的结果
- `ate_kb.ask` 返回带引用的结构化答案
- `ate_kb.get_document` 支持分页（`limit`、`offset`）
- Agent 答案包含 `source_md`、`section_title` 和 `chunk_id`
- Agent 在置信度低或无结果时**不会** hallucinate

---

## 2. 前置条件

- `uv` 已安装
- 已运行 `uv sync`
- Qdrant server 正在运行（默认：`http://localhost:6333`）
- 文档导入已完成
- `configs/config.yaml` 存在

### 启动 Qdrant Server

```bash
# Docker Compose（推荐）
docker compose up -d qdrant
```

### 导入文档

```bash
uv run -m ate_rag_kb.cli.main ingest --dir ./data/raw/markdown --incremental
```

### 验证状态

```bash
uv run -m ate_rag_kb.cli.main status
```

预期输出包含 `status: ok` 和 `total_chunks > 0`。

如果 `status` 失败或 `total_chunks` 为 `0`：

1. 确认 Qdrant 正在运行：`curl http://localhost:6333`
2. 重新运行导入
3. 检查 `configs/config.yaml` 是否使用 server mode（`vector_store.mode: server`）

---

## 3. MCP 配置

Marketplace/plugin 安装会自带已跟踪的插件根目录 `.mcp.json`，它使用
`${CLAUDE_PLUGIN_ROOT}/scripts/start_mcp.py`，不需要手动编辑 agent 设置。

如果是非插件的手动配置，复制示例配置：

```bash
cp .mcp.example.json .mcp.json
```

编辑 `.mcp.json`，将 `/path/to/ate-rag-kb` 替换为你机器上本仓库的绝对路径。

### Claude Code

将 server 添加到 `~/Library/Application Support/Claude/claude_desktop_config.json`（macOS）或你操作系统上的对应路径：

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

保存后重启 Claude Code。

### Codex / OpenClaw（通用 MCP）

大多数支持 MCP 的客户端接受相同的 JSON 结构。将客户端指向 `.mcp.json`（或将 `ate-kb` 块粘贴到客户端的 MCP 设置中），然后重启 Agent。

---

## 4. 启动 MCP Server

```bash
uv run python scripts/start_mcp.py
```

重要说明：

- **stdio transport** **不会**向终端打印普通 HTTP 式响应。
- 日志写入 **stderr**。
- **stdout 必须保持干净**，仅用于 JSON-RPC 消息。

如果你在终端中看到日志行，这是正常的（它们写入 stderr）。
如果你看到 JSON-RPC 被无关的 stdout 输出破坏，请检查代码库中是否存在 `print()` 语句或日志配置错误。

---

## 5. Agent 内验证步骤

### 步骤 1 — 确认工具可见

询问 Agent：

```text
What ATE KB tools do you have available?
```

预期工具列表：

- `ate_kb.search`
- `ate_kb.retrieve`
- `ate_kb.ask`
- `ate_kb.related`
- `ate_kb.get_document`
- `ate_kb.status`

如果有任何工具缺失，重启 Agent 并验证 MCP 配置路径。

---

### 步骤 2 — 调用 `ate_kb.status`

提示词：

```text
请调用 ate_kb.status 检查 ATE KB 是否可用，并总结 collection 状态。
```

预期结果：

- `status` = `ok`
- `total_chunks` > 0
- `collection_name` = `ate_kb`
- `embedding_model` 非空

---

### 步骤 3 — 调用 `ate_kb.retrieve`

提示词：

```text
请使用 ATE KB 查询：How to configure drive edge in TDC? 请给出带 source_md、section_title、chunk_id 的引用。
```

预期结果：

- Agent 调用 `ate_kb.retrieve`（或 `ate_kb.ask`）
- 响应包含时序 / drive edge 相关内容
- 答案包含类似以下的引用：
  ```
  [Source: 118727.md, Section: Syntax, Chunk: sha256-abc...]
  ```

---

### 步骤 4 — 调用 `ate_kb.ask`

提示词：

```text
请用 ate_kb.ask 回答：What is the difference between drive edge and compare edge? 并引用来源。
```

预期结果：

- Agent 使用 `ate_kb.ask`
- 答案基于返回的 `context_package`
- 没有在提供的上下文之外捏造细节
- 引用包含 `source_md`、`section_title` 和 `chunk_id`

---

### 步骤 5 — 带分页调用 `ate_kb.get_document`

提示词：

```text
请先用 ATE KB 找到与 drive edge 相关的 source_md，然后用 ate_kb.get_document 读取该文档前 5 个 chunks，不要一次读取全文。
```

预期结果：

- Agent 首先调用 `ate_kb.retrieve` 或 `ate_kb.ask` 发现 `source_md`
- 然后调用 `ate_kb.get_document` 并带 `limit` 参数（例如 `limit=5`）
- 响应包含 `has_more` 和 `next_offset`
- Agent **不会**在一次调用中获取整篇文档

对 Beta 测试中发现的大文档重复相同的分页行为：

| Source | 主题 | 预期行为 |
|--------|-------|-------------------|
| `v93000/smt7/146692.md` | RDI_Configure file | 使用 `limit` 并仅在需要时继续 `offset=next_offset` |
| `v93000/smt7/13920.md` | Using the Timing Diagram Tool | 不要一次获取整篇文档 |
| `v93000/smt7/49363_2.md` | Technology file for a device | 分页阅读后引用确切章节 |

---

### 步骤 6 — 低置信度 / 无结果测试

提示词：

```text
请查询一个知识库可能没有的问题：How to repair a coffee machine with TDC timing APIs?
```

预期结果：

- Agent **不会**编造答案
- Agent 说明 KB 可能不包含相关信息
- 如果返回了最近的结果，它们被展示为"可能相关"并标注低置信度

### 步骤 7 — 宽泛概念验证

提示词：

```text
SMT7中site control的作用是什么
```

预期结果：

- Agent 调用 `ate_kb.ask` 或 `ate_kb.retrieve`
- 答案自然涵盖以下方面：
  - Site Control 窗口用途
  - available / enabled / active / focus 状态
  - PARALLEL / SERIAL / SEMIPARALLEL 模式
  - Size / Cycle
  - Allow parallel
  - Site Match Mode
- 引用包含多个不同的 `source_md` 文件
- `processing` 字段显示 `post_diversity_source_count >= 3`
- MCP 响应显示 `answer_contract.answer_mode == "broad_concept"` 且 `answer_contract.completeness_required == true`
- 最终答案涵盖每个适用的 `answer_contract.coverage_topics` 项，而不是停在简短概述

> **注意：** 验收测试期间，以下来源可能会手动检查完整性，但它们**不得**被硬编码为运行时源文件提示或固定召回规则：
> - `v93000/smt7/42588.md`
> - `v93000/smt7/100096.md`
> - `v93000/smt7/100119.md`
> - `v93000/smt7/100324.md`
> - `v93000/smt7/20264.md`
> - `v93000/smt7/21615.md`

---

## 6. 通过标准

当**所有**以下条件为真时，Beta 被视为**就绪**：

| # | 标准 |
|---|-----------|
| 1 | 所有 6 个 MCP 工具对 Agent 可见 |
| 2 | `ate_kb.status` 返回 `ok` 且 `total_chunks > 0` |
| 3 | 至少 4/5 个典型问题返回相关引用 |
| 4 | 每个答案都引用 `source_md`、`section_title` 和 `chunk_id` |
| 5 | `get_document` 使用 `limit` 调用并返回 `has_more` / `next_offset` |
| 6 | 对跨域或低置信度查询没有 hallucination |
| 7 | MCP stdout 中没有 JSON-RPC 解析错误 |
| 8 | 10 问题 Beta 清单通过，每个答案都有引用 |
| 9 | 宽泛概念验证（步骤 7）涵盖所有必要方面，并带有来自多个来源的引用 |

首次记录的 Beta 试用总结在
[Beta 10-Question Trial Report](archive/beta_test_report_10q.md) 中。使用该报告作为 Q2 ARRAY 引用回归和 Q1/Q3/Q5 完整性检查的基线。
精确的修复后复测流程请参阅
[Beta 10-Question Retest Plan](archive/beta_retest_10q.md)。

---

## 7. 故障排查

| 症状 | 可能原因 | 解决方案 |
|---------|--------------|----------|
| 工具未出现 | MCP 配置路径错误 | 验证 `.mcp.json` / Claude Code 配置使用绝对路径 |
| `CONFIG_PATH` 错误 | 配置文件缺失或路径为相对路径 | 使用 `scripts/start_mcp.py` 或设置 `configs/config.yaml` 的绝对路径 |
| `status` 失败 | Qdrant server 未运行 | 保留 `ATE_KB_AUTO_BOOTSTRAP=1` 或手动启动 Qdrant：`docker compose up -d qdrant` |
| `status` 失败 | 未导入或 collection 为空 | 重新运行 `uv run -m ate_rag_kb.cli.main ingest --dir ./data/raw/markdown --incremental` |
| `status` 失败 | `portalocker.AlreadyLocked` | Local file mode 已废弃且不受支持。请使用 server mode：`docker compose up -d qdrant`，并在 `configs/config.yaml` 中设置 `vector_store.mode: server` |
| 响应非常慢 | 首次加载模型或 `top_k` 过大 | 等待 embedding 模型缓存预热；减小 `configs/config.yaml` 中的 `top_k` |
| `get_document` 返回过多数据 | `limit` 过高 | 使用 `limit=5` 或 `limit=20` |
| Agent 遗漏引用 | System prompt 不够明确 | 使用 [docs/agent_integration_CN.md](docs/agent_integration_CN.md) 中的推荐 system prompt |
| JSON-RPC 解析错误 | 有内容写入了 stdout | 检查日志是否写入 stderr，且 MCP 代码中没有 `print()` 语句 |
