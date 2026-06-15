# Site Control 检索性能基准报告

**日期**: 2026-06-11
**查询**: "ATE SMT7 中 Site Control 的作用是什么"
**目的**: 建立检索管线各步骤的耗时基线，识别 Step 2（MCP 并行调用）的性能瓶颈

---

## 1. 执行流程总览

```
用户提问 → 判断问题类型 → MCP 并行调用 → 分析 answer_contract
                                            → 分析 context_package
                                            → 综合输出答案
```

## 2. 步骤级耗时

| 步骤 | 操作 | 耗时 (s) | 占比 |
|------|------|----------|------|
| Step 1 | 判断问题类型 → ATE/SMT7 → 必须使用 MCP | ~0 | 0% |
| **Step 2** | **并行发起 5 次 `ate_kb.ask` 调用** | **~1501.8** | **99.2%** |
| Step 3 | 分析 `answer_contract`（completeness_required, coverage_topics） | ~1 | 0.1% |
| Step 4 | 分析 `context_package`（9 个引用来源, ~9000 tokens） | ~2 | 0.1% |
| Step 5 | 综合所有上下文，按结构化输出组织答案 | ~5 | 0.3% |
| Step 6 | 答案撰写 + 格式化 | ~2 | 0.1% |
| **总计** | | **~1510s** | |

## 3. Step 2 详细分析

### 3.1 调用参数

5 次 `ate_kb.ask` 调用，参数略有不同以获取更广覆盖：

| # | top_k | query 重点 | coverage_topics 数 | source_files 数 |
|---|-------|-----------|-------------------|----------------|
| 1 | 15 | 全覆盖（states, focus, multi-site, firmware commands） | 9 | 9 |
| 2 | 15 | 标准查询 | 6 | 6 |
| 3 | 15 | 标准查询（重复） | 6 | 6 |
| 4 | 15 | 标准查询（重复） | 6 | 6 |
| 5 | 15 | Enable/Active/Focus + multi-site control | 9 | 9 |

### 3.2 单次调用内部 pipeline 统计

以下是 `processing.processing_by_scope["v93000/smt7"]` 中关键字段的中位数：

| 指标 | 值 | 说明 |
|------|----|------|
| `dense_candidate_count` | 20 | Dense 向量检索候选数 |
| `sparse_candidate_count` | 20 | Sparse 向量检索候选数 |
| `fused_candidate_count` | 40 | RRF 融合后候选数 |
| `graph_expanded_source_count` | 20 | 图扩展发现的源文档数 |
| `graph_expanded_chunk_count` | 59-60 | 图扩展发现的 chunk 数 |
| `post_rerank_candidate_count` | 40 | Rerank 后候选数 |
| `post_rerank_source_count` | 26-27 | Rerank 后源文档数 |
| `post_diversity_candidate_count` | 14 | 源多样性筛选后候选数 |
| `broad_context_assembled` | true | Broad context 组装启用 |
| `broad_context_discovered_source_count` | 26-32 | Broad context 发现的源数 |
| `broad_context_token_estimate` | 8786-8887 | 最终上下文 token 估计 |
| `final_context_source_count` | 6-9 | 最终引用的源文档数 |

### 3.3 瓶颈分析

**核心问题：5 次 MCP 调用实际是串行执行**

Claude Code 虽然在一个消息中发出 5 个 MCP 调用，但 MCP stdio transport 是
单连接的，实际逐个处理。每次调用走完整 pipeline：

```
HybridRetriever.retrieve()     ← dense + sparse + RRF (~X ms)
  ↓
DocumentGraphExpander.expand()  ← BFS 图遍历 (~Y ms)
  ↓
Reranker.rerank()               ← cross-encoder (~Z ms, 通常是瓶颈)
  ↓
ParentChildExpander.expand()    ← batch get_by_ids (~W ms)
  ↓
BroadConceptAssembler.assemble()← 最多 32 源, 16 chunks (~V ms)
  ↓
ContextCompressor.compress()    ← dedup + merge + truncate (~U ms)
```

**估算单次调用耗时**: ~1501.8 / 5 ≈ **300s/次**

这个数字远超预期，可能原因：
1. Cross-encoder reranker 在 CPU 上推理慢（`device: "cpu"`）
2. Graph expansion 的 BFS 遍历涉及大量 `vector_store.scroll` 调用
3. Broad context assembly 发现 26-32 个源文档，每个需要 scroll 获取

## 4. 优化建议

### 4.1 高优先级（预计提速 3-5x）

| # | 优化项 | 预期效果 | 复杂度 |
|---|--------|---------|--------|
| 1 | **减少重复调用** — 1 次 `ate_kb.ask` + 1 次 `ate_kb.retrieve` 即可覆盖，无需 5 次 | **直接减少 60%+ 耗时** | 无代码改动 |
| 2 | **Reranker 迁移到 GPU 或 HTTP API** — 当前 `device: "cpu"` 是最大瓶颈 | 单次 rerank 从 ~200s 降至 ~2s | 配置改动 |
| 3 | **启用 reranker HTTP provider** — `config.yaml` 已支持 `provider: "http"` | 避免 CPU 推理 | 配置改动 |

### 4.2 中优先级（预计再提速 1.5-2x）

| # | 优化项 | 预期效果 | 复杂度 |
|---|--------|---------|--------|
| 4 | **Graph expansion 限制** — 减少 `max_hops` 或 `max_fan_out` | 减少 scroll 调用 | 配置改动 |
| 5 | **Broad context 限制** — 降低 `max_sources` (32→16) 和 `max_chunks` (16→8) | 减少后期处理 | 配置改动 |
| 6 | **Pipeline 内部计时** — 使用已实现的 `StepTimer` 定位具体哪步最慢 | 数据驱动优化 | 已完成 |

### 4.3 低优先级（架构级）

| # | 优化项 | 预期效果 | 复杂度 |
|---|--------|---------|--------|
| 7 | **MCP 多连接支持** — 允许真正并行调用 | 多查询真正并行 | 高 |
| 8 | **缓存常见查询** — 对重复 Site Control 查询返回缓存结果 | 重复查询 ~0s | 中 |
| 9 | **预计算 broad context** — 对热点文档预组装 context | 减少运行时开销 | 高 |

## 5. 已完成的 Timing 基础设施

本次实现了 `StepTimer` 工具类和全链路计时集成：

### 新增文件

| 文件 | 用途 |
|------|------|
| `src/ate_rag_kb/utils/timing.py` | `StepTimer` 轻量计时器（context manager） |
| `tests/test_utils_timing.py` | 12 个单元测试 |

### 修改文件

| 文件 | 改动 |
|------|------|
| `configs/config.yaml` | 新增 `retrieval.timing.enabled` + `log_threshold_ms` |
| `src/ate_rag_kb/retrieval/hybrid.py` | dense_search / sparse_search / rrf_fusion / bm25_fallback 计时 |
| `src/ate_rag_kb/retrieval/pipeline.py` | retrieve / search_enriched / retrieve_enriched 全 phase 计时 |
| `src/ate_rag_kb/mcp/tools.py` | handle_retrieve / handle_ask 端到端 `timing_total_ms` |
| `src/ate_rag_kb/api/models.py` | SearchResponse / RetrieveResponse / AskResponse 新增 `timing` 字段 |
| `src/ate_rag_kb/api/routes.py` | search / retrieve / ask 路由计时 |
| `src/ate_rag_kb/api/server.py` | `TimingMiddleware`（`X-Process-Time-Ms` header） |

### 配置

```yaml
retrieval:
  timing:
    enabled: true           # 总开关
    log_threshold_ms: 500   # 单步超 500ms 输出日志到 stderr
```

### 预期 timing 输出格式

重启 MCP 服务器后，`processing` dict 中将出现：

```json
{
  "timing_dense_search_ms": 45.2,
  "timing_sparse_search_ms": 12.3,
  "timing_rrf_fusion_ms": 0.5,
  "timing_enriched_search_ms": 58.0,
  "timing_graph_expansion_ms": 23.1,
  "timing_reranking_ms": 156.3,
  "timing_parent_child_expansion_ms": 8.7,
  "timing_broad_context_ms": 34.2,
  "timing_compression_ms": 2.1,
  "timing_total_ms": 282.4
}
```

## 6. 下一步

1. **重启 MCP 服务器**，确认 `timing_*` 字段出现在响应中
2. **运行一次 Site Control 查询**，获取真实 pipeline 内部各步骤耗时
3. **根据 timing 数据**，针对性优化最大瓶颈（预计是 reranker）
4. **减少重复 MCP 调用** — 1 ask + 1 retrieve 足以覆盖大多数 broad concept 查询

## 7. 引用来源

| source_md | 主题 |
|-----------|------|
| `v93000/smt7/100096.md` | The states of the sites（Enable / Active / Focus） |
| `v93000/smt7/13863.md` | Changing the site in focus |
| `v93000/smt7/42588.md` | Using the site control |
| `v93000/smt7/20921.md` | Controlling Multiple Sites |
| `v93000/smt7/42642.md` | Controlling the Setup/Query-Focus Automatically |
| `v93000/smt7/143608.md` | Site dependent firmware commands |
| `v93000/smt7/10664.md` | Defining the query focus |
| `v93000/smt7/42579.md` | focus（多站点执行状态） |
| `v93000/smt7/78972.md` | Sharing Channels Between Several Sites |
