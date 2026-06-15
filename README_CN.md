# ATE RAG 知识库

[English](README.md) | [中文](README_CN.md)

> **你的编码助手在 ATE 平台上的长期记忆。**

直接在 Claude Code、Cursor、Codex 或其他支持 MCP 的智能体中查询 ATE 技术文档、API、错误代码和调试流程。获取关于时序、pattern、DPS、PMU 和测试流程的可靠、带引用的答案，无需离开 IDE。

**适用人群：** 使用 AI 编码助手的测试工程师、维护 ATE 测试程序的团队（V93000、J750），以及任何拥有本地授权 ATE 文档并需要 grounded、带引用答案的人。

---

## 前置条件 — 安装所需软件

开始之前，请先安装以下三个工具。本知识库在 **macOS 和 Windows 上都能运行**。
其余的一切（Python 本身、Qdrant 数据库、Embedding 模型）都由 `uv` 和 Docker
自动处理，你**无需**单独安装。

| 软件 | 用途 | 下载地址 | 安装后验证 |
|------|------|----------|------------|
| **Git** | 克隆本仓库 | [git-scm.com/downloads](https://git-scm.com/downloads) | `git --version` |
| **uv** | 自动安装 Python 3.10+ 及所有依赖 | [docs.astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/) | `uv --version` |
| **Docker Desktop** | 运行 Qdrant 向量数据库（默认的 server 模式） | [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/) | `docker --version` |

> 项目要求 Python 3.10+，但你**不需要**自己下载——`uv` 会自动安装正确的版本。
> 如果你仍想手动安装，可从 [python.org/downloads](https://www.python.org/downloads/) 获取。

### 一行命令安装

**macOS** — 使用 [Homebrew](https://brew.sh)（如果还没有 Homebrew，请先安装它）：

```bash
brew install git
brew install uv
brew install --cask docker   # 然后从"应用程序"中启动一次 Docker Desktop
```

**Windows** — 在 **PowerShell** 中使用
[winget](https://learn.microsoft.com/windows/package-manager/winget/)（Windows 10/11 自带）：

```powershell
winget install Git.Git
winget install astral-sh.uv
winget install Docker.DockerDesktop   # 然后从"开始"菜单启动一次 Docker Desktop
```

安装完成后，打开一个**新的**终端窗口，确认三个命令都能响应：

```bash
git --version
uv --version
docker --version
```

> **Windows 用户：** 本指南中的所有命令请都在 **PowerShell** 中运行（不要用旧的
> `cmd` 命令提示符）。在执行任何 `docker compose` 命令前，确保 Docker Desktop
> 已经在运行（系统托盘里有鲸鱼图标）。

---

## 选择安装路径

请先选择其中一种路径。两种路径相关，但不会自动互相映射。

| 路径 | 配置内容 | 适用场景 |
|------|----------|----------|
| **本地 checkout 部署** | 你手动 clone 本仓库，在该目录准备模型、文档和 Qdrant 数据，然后由 `scripts/install_mcp.py` 写入指向这个绝对路径的 agent 配置。 | 你已经在本机准备了私有 ATE 文档、模型缓存或已导入的 Qdrant 数据。 |
| **Marketplace/plugin 部署** | AI 工具把插件 clone 到自己的插件缓存目录，并读取插件根目录的 `.mcp.json`。MCP server 默认从这个插件缓存目录启动。 | 你希望由插件安装流程管理 checkout，并且知道它和任何手动 clone 的目录是两份不同的副本。 |

不要先 clone 并准备一个目录，然后再安装 marketplace 插件并期望插件自动复用那个
目录。已有本地部署请使用本地 checkout 安装器，或显式设置
`ATE_RAG_KB_PROJECT_ROOT` 让插件 wrapper 指向该目录。

---

## 快速开始 — 本地 checkout 部署（15–30 分钟）

下方所有命令和路径都假设你正处在 **`ate-rag-kb` 文件夹内**（即"项目根目录"）。
此路径会把 agent 配置到这个 checkout。

### 1. 克隆仓库

选一个你记得住的目录（用户主目录即可）：

```bash
git clone https://github.com/WalterLuo/ate-rag-kb.git
cd ate-rag-kb
```

### 2. 安装依赖

```bash
uv sync
```

### 3. 启动 Qdrant 服务器

```bash
docker compose up -d qdrant
```

### 4. 下载 Embedding 模型

方案 A：使用预打包缓存（约 6.4 GB）。从
[PikPak](https://mypikpak.com/s/VOuGT6UlblOdQSw2ZNEP9F12o2) 下载并解压到项目根目录。

方案 B：首次使用时让 Hugging Face 自动下载（临时在 `configs/config.yaml` 中设置
`local_files_only: false`）。

方案 C：使用云端 API 提供商（如 SiliconFlow）进行 GPU 加速推理，无需下载模型到本地。
设置 API 密钥并更新 `configs/config.yaml` 即可——详见
[云端 API 进行 Embedding 和 Reranking](#云端-api-进行-embedding-和-reranking) 章节。

```bash
uv run python scripts/verify_models.py
```

### 5. 准备本地授权 Markdown 文档

```bash
mkdir -p data/raw/markdown/v93000/smt7
```

将你有权使用的 Markdown 文件复制或生成到 `data/raw/markdown/`。

### 6. 导入文档

首次为全量；后续运行加 `--incremental`。

```bash
uv run -m ate_rag_kb.cli.main ingest --dir ./data/raw/markdown
```

### 7. 配置智能体

```bash
uv run python scripts/install_mcp.py --install-agent-policy
```

该命令会写入 MCP 配置，调用此 checkout 下的 `scripts/start_mcp.py`，并把
`ATE_RAG_KB_PROJECT_ROOT` 设置为这个绝对路径。除非你明确想使用单独的插件缓存
部署，否则不要用 marketplace 安装来替代这一步。

Marketplace 和手动配置细节见下方[智能体集成](#智能体集成)。

### 8. 验证并重启

```bash
uv run python scripts/validate_plugin_install.py
uv run python scripts/validate_agent_routing_policy.py
```

然后重启 Codex / Claude Code / Cursor。

### 9. 直接启动 MCP 服务器（可选排错）

```bash
uv run python scripts/start_mcp.py
```

或启动 HTTP API（用于直接访问）：

```bash
uv run -m ate_rag_kb.cli.main serve --host 0.0.0.0 --port 8080
```

> **注意：** 模型缓存（`./embeddings/cache/`）因体积较大，**未**提交到 git。
> 导入会在 `data/processed/` 和 `data/qdrant_server/` 下生成本地状态；
> 这些生成文件同样不会提交到 git。
>
> **Server mode 是唯一支持的 Qdrant 模式。** KB 连接到
> `http://localhost:6333`（由 Docker 启动的 Qdrant 服务器）。Local file mode
>（`./data/qdrant_storage/`）已废弃且不受支持——启动时会抛出 RuntimeError。

---

## 模型缓存与离线模式

默认配置使用离线/缓存优先模式：

```yaml
embedding:
  cache_dir: "${ATE_KB_MODEL_CACHE:-./embeddings/cache}"
  local_files_only: true
```

需要的缓存模型：

- `BAAI/bge-m3`：用于 embedding
- `BAAI/bge-reranker-v2-m3`：用于 cross-encoder rerank

**下载预打包模型缓存（约 6.4 GB）：**

如果你不想手动从 Hugging Face 下载模型，可使用预打包的缓存压缩包：

1. 从 [PikPak](https://mypikpak.com/s/VOuGT6UlblOdQSw2ZNEP9F12o2) 下载
2. 将 `ate-kb-model-cache.zip` 解压到项目根目录
3. 运行 `uv run python scripts/verify_models.py` 验证

该压缩包包含完整的 Hugging Face 缓存结构
（`models--BAAI--bge-m3` 和 `models--BAAI--bge-reranker-v2-m3`），可直接配合
`local_files_only: true` 使用。

如果希望把模型缓存放到共享目录或外部磁盘：

```bash
export ATE_KB_MODEL_CACHE=/path/to/ate-kb-model-cache
```

Windows PowerShell：

```powershell
$env:ATE_KB_MODEL_CACHE="D:\ate-kb-model-cache"
```

### 使用 Qdrant 快照传输向量库

要在不同机器之间迁移或备份已索引的数据，请使用 Qdrant 内置的快照功能，而不是直接复制 Docker 卷目录：

```bash
# 创建当前集合的快照
curl -X POST http://localhost:6333/collections/ate_kb/snapshots

# 下载快照文件
curl -o ate_kb.snapshot http://localhost:6333/collections/ate_kb/snapshots/<snapshot_name>

# 在目标机器上从快照恢复（POST multipart，带 wait=true 和 priority=snapshot）
curl -X POST "http://localhost:6333/collections/ate_kb/snapshots/upload?wait=true&priority=snapshot" \
  -H "Content-Type: multipart/form-data" \
  -F "snapshot=@ate_kb.snapshot"
```

也可以使用内置的快照脚本，自动完成创建、下载和恢复：

```bash
# 创建并下载
uv run python scripts/package_qdrant_snapshot.py create --output dist

# 在目标机器上上传并恢复
uv run python scripts/package_qdrant_snapshot.py restore --snapshot dist/ate_kb.snapshot

# 或指定优先级（默认为 snapshot）
uv run python scripts/package_qdrant_snapshot.py restore --snapshot dist/ate_kb.snapshot --priority replica
```

这样可以避免文件锁定问题，确保备份的一致性。

### 云端 API 进行 Embedding 和 Reranking

默认情况下，KB 使用本地 sentence-transformers 模型进行 embedding 和 reranking。
你可以切换到云端 API 提供商（如 SiliconFlow），在没有本地 GPU 的情况下获得
GPU 加速推理。

#### SiliconFlow 配置

1. 从 [siliconflow.cn](https://siliconflow.cn) 获取 API 密钥。
2. 在 Windows PowerShell 中设置用户级环境变量：

```powershell
[Environment]::SetEnvironmentVariable("SILICONFLOW_API_KEY", "your-api-key-here", "User")
[Environment]::SetEnvironmentVariable("ATE_KB_EMBEDDING_PROVIDER", "openai_compatible", "User")
[Environment]::SetEnvironmentVariable("ATE_KB_RERANKER_PROVIDER", "http", "User")
```

设置后请关闭并重新打开 PowerShell、Codex、Claude Code、Cursor 或其它 MCP
客户端，让新环境变量生效。

如果只想在当前 PowerShell 窗口临时生效：

```powershell
$env:SILICONFLOW_API_KEY="your-api-key-here"
$env:ATE_KB_EMBEDDING_PROVIDER="openai_compatible"
$env:ATE_KB_RERANKER_PROVIDER="http"
```

macOS / Linux 使用：

```bash
export SILICONFLOW_API_KEY="your-api-key-here"
export ATE_KB_EMBEDDING_PROVIDER="openai_compatible"
export ATE_KB_RERANKER_PROVIDER="http"
```

不要把真实 API key 写入 `.mcp.json`、`.claude/settings.json`、Cursor MCP
设置或其它 agent 配置文件。MCP server 配置应从父进程环境继承
`SILICONFLOW_API_KEY`，配置文件里只保留 `CONFIG_PATH` 等非敏感值。

3. `configs/config.yaml` 的推荐写法是保留环境变量占位符，不写真实 key。
   当前配置已包含：

```yaml
embedding:
  provider: "${ATE_KB_EMBEDDING_PROVIDER:-local}"
  api:
    base_url: "${ATE_KB_EMBEDDING_BASE_URL:-https://api.siliconflow.cn/v1}"
    api_key_env: "${ATE_KB_EMBEDDING_API_KEY_ENV:-SILICONFLOW_API_KEY}"

retrieval:
  reranker:
    provider: "${ATE_KB_RERANKER_PROVIDER:-http}"
    api:
      base_url: "${ATE_KB_RERANKER_BASE_URL:-https://api.siliconflow.cn/v1}"
      api_key_env: "${ATE_KB_RERANKER_API_KEY_ENV:-SILICONFLOW_API_KEY}"
```

含义：

- `api_key_env` 是环境变量名，不是 API key 本身。
- `SILICONFLOW_API_KEY` 的真实值只放在 Windows 环境变量里。
- `reranker.provider` 默认已经是 `http`。
- `embedding.provider` 默认是 `local`；Windows 上使用云端 embedding 时，必须设置
  `ATE_KB_EMBEDDING_PROVIDER=openai_compatible`，或把配置直接改成
  `provider: "openai_compatible"`。

如果你不想依赖 provider 环境变量，也可以直接把 provider 写死在
`configs/config.yaml`，但仍然不要写真实 API key：

```yaml
embedding:
  provider: "openai_compatible"
  api:
    base_url: "https://api.siliconflow.cn/v1"
    api_key_env: "SILICONFLOW_API_KEY"

retrieval:
  reranker:
    provider: "http"
    api:
      base_url: "https://api.siliconflow.cn/v1"
      api_key_env: "SILICONFLOW_API_KEY"
```

4. 切换模型名称、base URL 或 API key 变量名。

Windows PowerShell：

```powershell
# 可选：切换模型名称（默认：BAAI/bge-m3、BAAI/bge-reranker-v2-m3）
[Environment]::SetEnvironmentVariable("ATE_KB_EMBEDDING_MODEL", "vendor/custom-embedding", "User")
[Environment]::SetEnvironmentVariable("ATE_KB_RERANKER_MODEL", "vendor/custom-reranker", "User")

# 可选：切换 API base URL（默认：https://api.siliconflow.cn/v1）
[Environment]::SetEnvironmentVariable("ATE_KB_EMBEDDING_BASE_URL", "https://api.your-vendor.com/v1", "User")
[Environment]::SetEnvironmentVariable("ATE_KB_RERANKER_BASE_URL", "https://api.your-vendor.com/v1", "User")

# 可选：如果供应商使用其它 key 变量名
[Environment]::SetEnvironmentVariable("MY_VENDOR_API_KEY", "your-api-key-here", "User")
[Environment]::SetEnvironmentVariable("ATE_KB_EMBEDDING_API_KEY_ENV", "MY_VENDOR_API_KEY", "User")
[Environment]::SetEnvironmentVariable("ATE_KB_RERANKER_API_KEY_ENV", "MY_VENDOR_API_KEY", "User")
```

macOS / Linux：

```bash
# 可选：切换模型名称（默认：BAAI/bge-m3、BAAI/bge-reranker-v2-m3）
export ATE_KB_EMBEDDING_MODEL="vendor/custom-embedding"
export ATE_KB_RERANKER_MODEL="vendor/custom-reranker"

# 可选：切换 API base URL（默认：https://api.siliconflow.cn/v1）
export ATE_KB_EMBEDDING_BASE_URL="https://api.your-vendor.com/v1"
export ATE_KB_RERANKER_BASE_URL="https://api.your-vendor.com/v1"

# 可选：如果供应商使用其它 key 变量名
export MY_VENDOR_API_KEY="your-api-key-here"
export ATE_KB_EMBEDDING_API_KEY_ENV="MY_VENDOR_API_KEY"
export ATE_KB_RERANKER_API_KEY_ENV="MY_VENDOR_API_KEY"
```

验证 Windows 环境变量是否生效：

```powershell
Get-ChildItem Env:ATE_KB_EMBEDDING_PROVIDER
Get-ChildItem Env:ATE_KB_RERANKER_PROVIDER
Get-ChildItem Env:SILICONFLOW_API_KEY
```

#### 切换到其他供应商

`openai_compatible` embedding provider 和 `http` reranker provider 兼容任何
OpenAI 兼容 API。只需修改配置中的 `base_url` 和 `api_key_env` 即可指向你偏好的
供应商。

#### 禁用 Reranker

如果你想完全跳过重排序（为了速度或成本），可以设置：

```yaml
retrieval:
  reranker:
    enabled: false
```

### 模型包重新生成

如果你需要重新生成模型缓存包（例如添加了新模型或更新了现有模型）：

```bash
uv run python scripts/package_models.py
```

这会创建当前 `embeddings/cache/` 目录的压缩包，可用于离线分发。

---

## 添加文档

只导入你有权使用和检索的文档。本仓库本身不授予任何第三方 ATE 文档的使用或再分发权利。

**ATE 规范术语：**

| 厂商 | 测试平台 | 软件 |
|---|---|---|
| Advantest | V93000 | SMT7、SMT8 |
| Teradyne | J750 | IG-XL |

V93000 和 J750 是测试平台。SMT7、SMT8、IG-XL 是软件范围，用于导入、检索路由和引用隔离。

如果你已经有 Markdown 文件，请按标准 scope 路径放置：

```
data/raw/
├── markdown/
│   ├── v93000/smt7/   # V93000 / SmarTest 7 文档
│   ├── v93000/smt8/   # V93000 / SmarTest 8 文档
│   └── igxl/          # J750 / IG-XL 文档
├── json/
│   ├── v93000/smt7/   # 可选 SMT7 元数据 sidecar
│   ├── v93000/smt8/   # 可选 SMT8 元数据 sidecar
│   └── igxl/          # 可选 IG-XL 元数据 sidecar
└── assets/
    ├── v93000/smt7/   # 可选 SMT7 本地图片
    ├── v93000/smt8/   # 可选 SMT8 本地图片
    └── igxl/          # 可选 IG-XL 本地图片
```

然后运行导入：

```bash
uv run -m ate_rag_kb.cli.main ingest --dir ./data/raw/markdown --incremental
```

### 使用本地转换脚本

你可以提供一个本地脚本，把你有权使用的文档转换为 Markdown。建议将厂商文档相关的私有转换脚本放在公开仓库之外，或放在已被 git 忽略的 `scripts/local/` 目录下。

对于 TDC/Eclipse Help 和 IG-XL 帮助源，推荐使用配套转换器项目：
[ate-help-converters](https://github.com/WalterLuo/ate-help-converters)。
该项目提供 macOS 和 Windows 一键安装脚本，以及用于把本地授权帮助文件转换为
Markdown/JSON/assets 的命令行工具。

除非你拥有明确的再分发授权，否则不要提交转换后的 Markdown、提取图片、生成的 JSON sidecar 或向量数据库快照。

---

## 智能体集成

### 本地 checkout 智能体配置

完成本地 checkout 快速开始后，使用此路径。安装器会把检测到的 AI 工具配置为从
你已经准备好的 checkout 启动 MCP server：

```bash
# 配置所有检测到的 AI CLI 工具
uv run python scripts/install_mcp.py --install-agent-policy

# 先干跑预览将要修改的内容
uv run python scripts/install_mcp.py --dry-run

# 只配置指定工具
uv run python scripts/install_mcp.py --harness claude,cursor

# 只配置 MCP，不写全局 agent policy（不推荐 projectless 会话使用）
uv run python scripts/install_mcp.py --skip-agent-policy
```

生成的 MCP 配置会使用 `uv run --project <checkout> python
<checkout>/scripts/start_mcp.py`，把 `ATE_RAG_KB_PROJECT_ROOT` 设置为该
checkout，并通过 `ATE_KB_AUTO_BOOTSTRAP=1` 启用 Qdrant 启动逻辑。

### Marketplace 插件安装

Marketplace/plugin 安装是另一条路径。AI 工具会把插件 clone 到自己的插件缓存目录；
它不会自动复用你在其它位置手动准备好的 checkout。

#### 各平台快速安装

| 工具 | 安装命令 |
|---------|-----------------|
| **Claude Code** | `/plugin marketplace add WalterLuo/ate-rag-kb-marketplace` 后执行 `/plugin install ate-rag-kb@ate-rag-kb-marketplace` |
| **Cursor** | `/add-plugin ate-rag-kb` |
| **Codex** | `/plugins` → 搜索 "ate-rag-kb" |
| **Gemini CLI** | `gemini extensions install https://github.com/WalterLuo/ate-rag-kb.git` |
| **OpenCode** | 在 `opencode.json` 的 plugins 中添加 `"ate-rag-kb@git+https://github.com/WalterLuo/ate-rag-kb.git"` |
| **Copilot CLI** | `copilot plugin install ate-rag-kb@ate-rag-kb-marketplace` |

详细的各平台说明、故障排查和架构说明请参阅 [docs/PLUGIN_INSTALL_CN.md](docs/PLUGIN_INSTALL_CN.md)。

Codex 本地/团队 marketplace 可使用本仓库的
`.agents/plugins/marketplace.json` 注册后搜索安装；公共插件市场可搜索安装还需要
后续发布或注册 marketplace。

### Claude Code（MCP — Marketplace 自动配置）

Marketplace 和插件安装会自带插件根目录 `.mcp.json`：

```json
{
  "mcpServers": {
    "ate-kb": {
      "command": "uv",
      "args": [
        "run",
        "--project",
        "${CLAUDE_PLUGIN_ROOT}",
        "python",
        "${CLAUDE_PLUGIN_ROOT}/scripts/start_mcp.py"
      ],
      "env": {
        "ATE_KB_QUERY_DEVICE": "cpu",
        "ATE_KB_RERANKER_DEVICE": "cpu",
        "ATE_KB_AUTO_BOOTSTRAP": "1"
      }
    }
  }
}
```

启动时，`uv run` 会创建或复用插件的 Python 环境；`scripts/start_mcp.py` 会解析
项目根目录、推导 `CONFIG_PATH`，在 `ATE_KB_AUTO_BOOTSTRAP=1` 时通过 Docker
Compose 启动 Qdrant，然后 exec 到真正的 `ate_rag_kb.cli.main mcp` server。

安装插件后重启 Claude Code。智能体将从插件提供的 MCP server 自动发现
`ate_kb.*` 工具。授权源文档、模型缓存或云端 API 凭据、以及文档导入仍然是部署前提；
插件不会也不能再分发或生成你的私有 ATE 文档。

如果你已经准备好了一个本地 checkout，并希望 agent 使用它，优先运行
`uv run python scripts/install_mcp.py --install-agent-policy`。高级用户也可以在
启动 agent 前设置 `ATE_RAG_KB_PROJECT_ROOT=/path/to/ate-rag-kb`，必要时再设置
`ATE_RAG_KB_CONFIG_PATH=/path/to/ate-rag-kb/configs/config.yaml`；wrapper 会先读取
这些变量，然后才回退到插件缓存目录。

只有不使用插件安装时，才需要手动配置。此时添加到 `~/.claude/settings.json`
（macOS / Linux）或 `%USERPROFILE%\.claude\settings.json`（Windows）：

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

### 默认智能体行为

工程师只需要提出 ATE 技术问题，智能体应自行选择检索策略。默认路径是优先使用
MCP 工具中的 `ate_kb.retrieve` 或 `ate_kb.ask`；只有在已经识别出相关
`source_md` 且需要完整上下文时，才调用 `ate_kb.get_document`。CLI 搜索、
grep、`rg` 和手动读取 markdown 只作为 MCP 不可用或上下文不足时的降级方案，
不应作为默认工作流。

仅配置 MCP server 并不等于 agent 一定会第一时间调用 MCP。Codex 中
`ate_kb` 可能是 deferred tool，需要先通过 `tool_search` 暴露。因此推荐使用
`uv run python scripts/install_mcp.py --install-agent-policy`，它会在 MCP 配置之外
安装全局 ATE KB Routing policy。对于 Codex projectless 会话，这个全局 policy
尤其重要；如果使用 `--skip-agent-policy`，则无法保证不在项目目录中打开的会话会
优先调用 `ate_kb`。

安装后请重启 agent，并运行：

```bash
uv run python scripts/validate_plugin_install.py
uv run python scripts/validate_agent_routing_policy.py
```

## 可用智能体工具

| 工具 | 描述 | 适用场景 |
|------|------|----------|
| `ate_kb.search` | 快速语义搜索 | 查找相关文档 |
| `ate_kb.retrieve` | 深度检索（含重排序 + 扩展） | 获取全面答案 |
| `ate_kb.ask` | 结构化问答（带引用） | 直接提问 |
| `ate_kb.related` | 查看 chunk 的父/兄弟/子节点 | 需要更广泛的上下文 |
| `ate_kb.get_document` | 分页获取文档 chunks（支持 `limit`/`offset`） | 在发现相关文档后阅读完整参考 |
| `ate_kb.status` | 集合统计信息 | 检查知识库健康状态 |

所有工具都返回结构化 JSON，包含每条结果的 `source_md`、`doc_title`、
`section_title`、`chunk_id`、`start_line` 和 `end_line`。

`ate_kb.get_document` 支持分页（`limit`、`offset`）和 `max_tokens` 预算。
智能体在处理大文档时应使用较小的 `limit`（如 20）并逐步翻页，而不是一次性获取所有 chunks。
MCP handler 内部已经使用分页读取路径，因此读取第一页时不需要先加载整篇大文档。

---

## 项目架构

```
Markdown + JSON  ->  IngestionPipeline  ->  Chunks  ->  EmbeddingEncoder
                                                            |
                                                            v
FastAPI / MCP  <-  RetrievalCoordinator  <-  RetrievalPipeline  <-  QdrantVectorStore  <-  Vectors
```

**RetrievalPipeline 阶段：**

1. **HybridRetriever** — dense + sparse 向量搜索，使用 Reciprocal Rank Fusion
2. **DocumentGraphExpander**（可选）— 遍历文档内部链接
3. **Reranker** — cross-encoder（`BAAI/bge-reranker-v2-m3`）
4. **BroadConceptAssembler**（可选）— 宽泛查询的覆盖感知选择
5. **ParentChildExpander** — 补充父/兄弟节点上下文
6. **ContextCompressor** — 去重、合并相邻片段、token 上限控制

高级配置选项（分块策略、检索参数、状态隔离、从 local mode 迁移）请参阅 [CLAUDE.md](CLAUDE.md)。

---

## 评估与验证

运行检索评估：

```bash
uv run python scripts/run_eval.py
```

指标：`hit@k`、`recall@k`、`MRR@k`、`source_precision@k`。

当前基线（50 个问题）：

| 指标 | 数值 |
|------|------|
| `source_precision@5` | 1.0000 |
| `failed_count` | 0 |

在让工程师正式使用前，请先完成：

1. [Agent 端到端验证](docs/agent_e2e_validation_CN.md) — 逐步验证指南
2. [Beta 试用清单](docs/beta_checklist_CN.md) — 含 10 个真实试用问题及通过标准
3. [Beta 10-Question Trial Report](docs/archive/beta_test_report_10q.md) — 已归档的第一次真实工程师试用结果
4. [Beta 10-Question Retest Plan](docs/archive/beta_retest_10q.md) — 已归档的修复后复测流程

当前 Beta 状态：可交付给工程师继续试用。第一次真实试用通过 9/10；在修复
ARRAY 引用、补充预期答案检查点、实现 `get_document` 分页读取后，前 5 个
重点问题已复测通过，证据记录在 [docs/archive/10q_retest.csv](docs/archive/10q_retest.csv)。

---

## 开发命令

```bash
# 运行测试
uv run pytest tests/ -q

# 运行测试（含覆盖率）
uv run pytest tests/ --cov=src/ate_rag_kb --cov-report=term

# 代码检查
uv run ruff check src/ tests/

# CLI 搜索（开发/调试降级方案）
uv run -m ate_rag_kb.cli.main search "timing set configuration" --top-k 5

# 检查集合统计
uv run -m ate_rag_kb.cli.main status
```

### 维护脚本

```bash
# 在 sparse encoder 词汇表或配置变更后重建稀疏向量
# （需要运行中的 Qdrant 服务器和已有集合）
uv run python scripts/rebuild_sparse_vectors.py
```

该脚本从 Qdrant 集合中读取每个点的文本内容，使用当前
`SparseVectorEncoder` 重新编码稀疏向量并原地更新。不会重新分块或
重新编码 dense 向量。仅在完成全量导入且 sparse encoder 配置发生变更后运行。

## 所有文件都放在哪里？

本指南中所有以 `./data/...` 或 `./embeddings/...` 开头的路径，都是**相对于项目
根目录**的——也就是你在第 1 步克隆下来的那个 `ate-rag-kb` 文件夹。除非你主动
修改配置，否则不会有任何文件写到这个文件夹之外。macOS 和 Windows 行为一致。

| 内容 | 路径 | 由谁创建 | 是否提交 git |
|------|------|----------|--------------|
| 你的源 Markdown 文档 | `data/raw/markdown/` | **你**（手动放入） | 否 |
| 可选 JSON 元数据 | `data/raw/json/` | 你（可选） | 否 |
| 可选图片 | `data/raw/assets/` | 你（可选） | 否 |
| **Qdrant 数据 — server 模式（默认）** | `data/qdrant_server/` | Docker 容器 | 否 |
| 导入状态 | `data/processed/` | `ingest` 命令 | 否 |
| Embedding 模型缓存（约 6.4 GB） | `embeddings/cache/` | 你（下载）或 Hugging Face | 否 |

**具体示例** — 相对于项目根目录：

| 内容 | 相对路径 |
|------|----------|
| V93000 / SMT7 Markdown 文件 | `data/raw/markdown/v93000/smt7/` |
| J750 / IG-XL Markdown 文件 | `data/raw/markdown/igxl/` |
| Embedding 模型缓存 | `embeddings/cache/` |

> **Qdrant 数据是运行时状态，不是分发产物：**
>
> - **`data/qdrant_server/`** 是 Qdrant 容器写入的 Docker 卷。用
>   `docker compose up -d qdrant` 启动。
> - 要传输或备份向量数据，请使用 **Qdrant 快照**而不是直接复制卷目录。
>   参见上方"使用 Qdrant 快照传输向量库"章节。
> - Local file mode（`data/qdrant_storage/`）已废弃，启动时会抛出 RuntimeError。

---

## 许可证

应用代码使用 MIT License 发布。请参阅 [LICENSE](LICENSE)。

第三方 ATE 厂商文档、转换后的文档、提取的资源文件、模型文件和生成的向量库不包含在该许可证内。再分发注意事项见
[THIRD_PARTY.md](THIRD_PARTY.md)。
