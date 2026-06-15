# ATE RAG KB — 多平台插件安装指南

本文档介绍如何在各种 AI CLI 工具中安装和配置 **ate-rag-kb** 插件或 MCP 扩展。

## 安装模式

有两条有效路径：

1. **本地 checkout 部署：** clone 仓库，在该 checkout 中准备模型、文档和 Qdrant
   数据，然后运行 `scripts/install_mcp.py`。Agent 配置会指向这个明确的绝对路径。
2. **Marketplace/plugin 部署：** AI 工具把插件 clone 到自己的插件缓存目录，并读取
   插件根目录的 `.mcp.json`。默认从该缓存目录启动，不会自动复用另一处手动 clone。

共享的 MCP 入口是 `scripts/start_mcp.py`。`uv run` 会创建或复用 Python 环境；
当 `ATE_KB_AUTO_BOOTSTRAP=1` 时，wrapper 会通过 Docker Compose 启动 Qdrant。
授权源文档、模型缓存或云端 API 凭据、以及文档导入仍然是部署前提。

## 本地 checkout 设置

clone 并准备好项目后运行：

```bash
uv run python scripts/install_mcp.py --install-agent-policy
```

先干跑查看将要修改的内容：

```bash
uv run python scripts/install_mcp.py --dry-run
```

只配置指定的工具：

```bash
uv run python scripts/install_mcp.py --harness claude,cursor
```

只配置 MCP，不写全局 agent policy：

```bash
uv run python scripts/install_mcp.py --skip-agent-policy
```

这不推荐用于 Codex projectless 会话，因为仓库里的 `AGENTS.md` 可能不会被加载。

生成的 MCP 配置会运行：

```text
uv run --project /path/to/ate-rag-kb python /path/to/ate-rag-kb/scripts/start_mcp.py
```

并在 server 环境中设置 `ATE_RAG_KB_PROJECT_ROOT`、`CONFIG_PATH` 和
`ATE_KB_AUTO_BOOTSTRAP=1`。

---

## 各平台安装方式

### Claude Code

**通过 Marketplace 安装（推荐）：**

```bash
/plugin marketplace add WalterLuo/ate-rag-kb-marketplace
/plugin install ate-rag-kb@ate-rag-kb-marketplace
```

**或直接从本仓库安装：**

```bash
/plugin install ate-rag-kb@git+https://github.com/WalterLuo/ate-rag-kb.git
```

Marketplace 和 git 插件安装会自带插件根目录 `.mcp.json`，使用
`${CLAUDE_PLUGIN_ROOT}/scripts/start_mcp.py` 自动注册 `ate-kb` stdio MCP
server。安装后重启 Claude Code，然后运行 `/mcp` 或直接提出 ATE 问题验证
server 是否可见。

如果你已经准备了一个本地 checkout，不要期望 marketplace clone 自动复用它。
优先运行 `uv run python scripts/install_mcp.py --install-agent-policy`，或在启动
Claude Code 前设置 `ATE_RAG_KB_PROJECT_ROOT`，必要时再设置
`ATE_RAG_KB_CONFIG_PATH` 指向已准备好的 checkout。

**手动 MCP 配置（仅作为 fallback）：**

只有不使用插件安装时，才需要手动配置。Claude Code 也可以通过
`settings.json` 配置 MCP server：

```json
// ~/.claude/settings.json（全局）或 .claude/settings.json（项目级）
{
  "mcpServers": {
    "ate_kb": {
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

**验证：**

```
What V93000 timing set commands are available?
```

Claude Code 应自动调用 `ate_kb.search` 或 `ate_kb.retrieve`。

---

### Cursor

**从 Marketplace 安装：**

```bash
/add-plugin ate-rag-kb
```

**或搜索安装：**

在 Cursor Agent 聊天中，于插件市场搜索 "ate-rag-kb"。

Cursor 插件 manifest 同样引用 `mcpServers: "./.mcp.json"`，兼容的插件安装流程
可以自动加载同一个 `ate-kb` MCP server。

**手动 MCP 配置（仅作为 fallback）：**

如果 Cursor 插件流程没有自动加载 MCP，可使用 `.cursor/mcp.json`（项目级）或
`~/.cursor/mcp.json`（全局）：

```json
{
  "mcpServers": {
    "ate_kb": {
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

`scripts/install_mcp.py` 也会为本地 checkout 自动配置此项。

---

### Codex CLI / Codex App

**从 Marketplace 安装：**

```bash
/plugins
# 搜索 "ate-rag-kb" 并选择 Install Plugin。
```

如果是本地或团队 marketplace 测试，先添加本仓库提供的 Codex marketplace
manifest，然后再搜索 `ate-rag-kb`：

```bash
codex plugin marketplace add /path/to/ate-rag-kb/.agents/plugins/marketplace.json
```

如果要进入公共 Codex 插件市场搜索结果，还需要在仓库之外完成 marketplace 发布或注册。

插件安装已包含 `mcpServers: "./.mcp.json"` 和可移植的根目录 `.mcp.json`，
因此兼容的 Codex 插件流程可以自动加载 `ate-kb` MCP server，不需要手动编辑
`~/.codex/settings.json`。

**手动 MCP 配置（仅作为 fallback）：**

如果不使用插件流程，Codex 也支持 MCP server。添加到 `~/.codex/settings.json`：

```json
{
  "mcpServers": {
    "ate_kb": {
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

或对本地 checkout 运行 `scripts/install_mcp.py --harness codex --install-agent-policy`
来同时安装托管 routing policy。

安装后重启 Codex，并运行：

```bash
uv run python scripts/validate_plugin_install.py
uv run python scripts/validate_agent_routing_policy.py
```

---

### Gemini CLI

**安装扩展：**

```bash
gemini extensions install https://github.com/WalterLuo/ate-rag-kb.git
```

**后续更新：**

```bash
gemini extensions update ate-rag-kb
```

Gemini CLI 读取仓库根目录的 `gemini-extension.json`，该文件指向 `GEMINI.md` 作为上下文文件。无需额外的 MCP 配置 — Gemini 通过上下文指令了解何时调用工具。

---

### OpenCode

**通过 git-backed 插件安装：**

在你的 `opencode.json`（全局或项目级）中添加：

```json
{
  "plugin": ["ate-rag-kb@git+https://github.com/WalterLuo/ate-rag-kb.git"]
}
```

重启 OpenCode。详细说明请参阅 `.opencode/INSTALL.md`。

---

### GitHub Copilot CLI

**注册 Marketplace：**

```bash
copilot plugin marketplace add WalterLuo/ate-rag-kb-marketplace
```

**安装插件：**

```bash
copilot plugin install ate-rag-kb@ate-rag-kb-marketplace
```

VS Code 中的 Copilot Chat 也可以通过 `~/.vscode/mcp.json` 或工作区设置使用 MCP server。

---

### Factory Droid

**注册 Marketplace：**

```bash
droid plugin marketplace add https://github.com/WalterLuo/ate-rag-kb
droid plugin install ate-rag-kb@ate-rag-kb
```

---

## 插件文件参考

| 工具 | 本仓库中的对应文件 |
|---------|-------------------|
| Claude Code | `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` |
| Cursor | `.cursor-plugin/plugin.json` |
| Codex | `.codex-plugin/plugin.json` |
| Gemini CLI | `gemini-extension.json`, `GEMINI.md` |
| OpenCode | `.opencode/INSTALL.md` |
| 所有 MCP 工具 | `scripts/start_mcp.py`, `scripts/install_mcp.py` |

## 故障排查

### MCP server 无法启动

1. 在项目根目录下手动运行 `uv run python scripts/start_mcp.py` 验证是否正常。
2. 如果关闭了 Docker bootstrap，确认 Qdrant 在配置的 URL 上可访问。
3. 检查 `embeddings/cache/` 中模型是否存在，或确认云端 API 凭据已设置。
4. 确认授权文档已经导入到 Qdrant collection。

### 插件未加载

1. 确认插件 manifest 的 JSON 语法有效。
2. 检查 AI 工具的日志中是否有插件加载错误。
3. 对于 Marketplace 安装，确认 Marketplace URL 可访问。

### 模型缓存错误

如果看到 "Local model cache not found"，说明 embedding 模型缺失。解压模型压缩包或重新下载：

```bash
# 将 ate-rag-kb-models.zip 解压到项目根目录后
uv run python scripts/verify_models.py
```

## 架构说明

- **MCP 优先：** 所有支持 MCP 的工具（Claude Code、Cursor、Codex、Copilot Chat）都使用 `scripts/start_mcp.py`，它会 exec 到同一个 `ate_rag_kb.cli.main mcp` stdio server。
- **路由 skill：** `skills/ate-kb-router/SKILL.md` 让支持 skill 的 agent 在 web 或 shell 降级前先暴露并调用 `ate_kb`。
- **托管 policy：** `scripts/install_mcp.py --install-agent-policy` 会追加或更新全局 agent 指令中的 ATE KB Routing 块，不覆盖用户原有规则。
- **上下文文件：** `CLAUDE.md`、`GEMINI.md` 和 `AGENTS.md` 提供各工具专属指令，让 AI 知道如何使用 `ate_kb` 工具。
- **插件清单：** 每个工具在专属目录中维护自己的 manifest 格式（`.claude-plugin/`、`.cursor-plugin/`、`.codex-plugin/`）。
