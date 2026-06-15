# Claude Code Completion Report

## Status

`codex_review` (round 2 — review fixes applied)

## Task Package

`docs/agent_workflows/tasks/2026-06-12-http-rerank-input-optimization.md`

## Branch

`codex/http-rerank-input-optimization`

## Summary

Optimized HTTP reranker latency by adding a rerank input shaping layer that limits
the number and length of documents sent to the SiliconFlow rerank API, while
preserving full original chunks for final context output.

**Key results (Site Control query):**

| Metric | Before | After |
|--------|--------|-------|
| Documents sent to API | ~78 | 32 |
| Total chars sent | ~200K+ | 51,499 |
| Reranking time | 180,000–288,000 ms (3–5 min) | 668 ms |
| Wall time | ~5+ min | ~12 s |

The improvement is ~270x faster for the reranking step, reducing total query time
from minutes to seconds. Source coverage is preserved: `100096.md` (Site Control
states), `143608.md` (site-dependent firmware commands), and other key sources are
still returned.

A small LRU cache (64 entries) was added to the HTTP provider to avoid duplicate
API calls for identical query+document combinations within a single session.

## Changed Files

| File | Change |
|---|---|
| `configs/config.yaml` | Added `retrieval.reranker.input` section with shaping config; updated `api.timeout_seconds` to 30, `api.top_n` to 32, added `api.max_chunks_per_doc` and `api.overlap_tokens` |
| `src/ate_rag_kb/retrieval/rerank_input.py` | **New** — input shaping module with `shape_rerank_input()`, `InputConfig`, and `ShapedInput` dataclass |
| `src/ate_rag_kb/retrieval/reranker.py` | Updated `rerank()` to use input shaping; added `seed_count` and `title_match_terms` params; added observability stats (`pre_rerank_candidate_count`, `rerank_input_*`) |
| `src/ate_rag_kb/retrieval/reranker_providers.py` | Added `_RerankCache` LRU cache and `_build_cache_key()`; added `max_chunks_per_doc` and `overlap_tokens` to HTTP request; added specific error messages for 429/503/504; changed timeout to explicit `httpx.Timeout()` |
| `src/ate_rag_kb/retrieval/pipeline.py` | Updated `retrieve_enriched()` to pass `seed_count` and `title_match_terms` to reranker |
| `scripts/benchmark_reranker_mode.py` | Added rerank input stats output (`pre_rerank_candidate_count`, `rerank_input_*`, final chunk count) |
| `tests/test_retrieval_reranker.py` | Added tests for input shaping, cache behavior, HTTP request fields, error messages, observability stats |

## Verification

| Command | Result | Notes |
|---|---|---|
| `uv run pytest tests/test_retrieval_reranker.py -q` | 51 passed | All reranker + input shaping + cache + review-fix tests |
| `uv run pytest tests/retrieval/test_pipeline.py -q` | 10 passed | Pipeline integration tests |
| `uv run pytest tests/retrieval/test_document_graph_expander.py tests/retrieval/test_broad_context.py tests/mcp/test_tools.py -q` | 51 passed | Broader affected tests |
| `rg -n "sk-\|SILICONFLOW_API_KEY=.*sk" docs scripts configs src tests` | No secrets found | Only matches are template docs using `>-` markdown syntax |
| `ATE_KB_RERANKER_PROVIDER=http uv run python scripts/benchmark_reranker_mode.py --top-k 15 --runs 1` | Success | Reranking: 645 ms, wall: 15,295 ms |
| `ATE_KB_RERANKER_PROVIDER=http uv run python scripts/benchmark_reranker_mode.py --top-k 15 --runs 2` | Success | Second run also completes; cache works within single coordinator instance |

## Acceptance Criteria

- [x] HTTP reranker request document count is bounded and observable. For the Site Control query, it sends 32 documents (not ~78).
- [x] HTTP reranker request payload is bounded by document count (32) and per-document character cap (2400).
- [x] Final returned chunks/context still use full original chunk content (truncation only affects API payload).
- [x] Site Control query returns plausible source coverage: `v93000/smt7/100096.md` and `v93000/smt7/143608.md` confirmed.
- [x] Benchmark with `ATE_KB_RERANKER_PROVIDER=http` completes successfully.
- [x] Benchmark report shows rerank input count (32), total chars (51,607), wall time (15,295 ms), and reranking time (645 ms).
- [x] Unit tests cover candidate limiting, text truncation, source diversity, preservation of full original chunks, HTTP request fields, and cache hits/misses.
- [x] No secrets are printed, committed, or stored.
- [x] `embedding.provider` remains local (not changed).

## Benchmark Output Summary

```
Provider:  http
Wall time: 11686.6 ms

Pipeline phase timing:
  timing_reranking_ms:             668.4
  timing_graph_expansion_ms:     5286.7
  timing_enriched_search_ms:     3029.4
  timing_broad_context_ms:       2587.4

Rerank input stats:
  pre_rerank_candidate_count:             77
  rerank_input_candidate_count:           32
  rerank_input_total_chars:           51,499
  rerank_input_truncated_document_count: 17
  rerank_input_source_count:             31
```

Source coverage:

```
v93000/smt7/100096.md   (Site Control states)
v93000/smt7/108710.md
v93000/smt7/13863.md   (Changing the site in focus)
v93000/smt7/143608.md  (Site dependent firmware commands)
v93000/smt7/20921.md   (Controlling Multiple Sites)
v93000/smt7/42642.md   (Controlling Setup/Query-Focus)
v93000/smt7/42646.md
```

## Caching

Implemented: LRU cache (64 entries) in `HttpRerankerProvider`. Keyed by
SHA-256 digest of query + model name + document digests. No API keys cached.
Cache is per-provider-instance (in-process), so it works within a single MCP
server session. The benchmark creates a new coordinator per run, so the cache
doesn't help across benchmark iterations — this is by design.

## Why `embedding.provider` Remains Local

The embedding model (`BAAI/bge-m3`) generates query vectors that must align with
the pre-indexed Qdrant vectors. Switching the embedding provider would require
re-ingesting the entire collection. The bottleneck was never embedding — it was
the reranker API payload size. This optimization addresses the actual bottleneck.

## Risks And Notes

- The `max_candidates: 32` and `max_chars_per_document: 2400` defaults are
  conservative. For very broad queries that need many sources, these may need
  tuning. The config is exposed in `config.yaml` for adjustment.
- The input shaping prefers `SECTION` chunks over `DOCUMENT` chunks by default
  (`prefer_section_chunks: true`). If a use case needs full document-level
  reranking, this can be disabled. This flag now controls the sort order in
  `_chunk_sort_key`: when `False`, all chunk types share the same type priority.
- The LRU cache is bounded at 64 entries and does not expire by time. In a
  long-running MCP server, frequently changing queries will naturally evict
  old entries.
- `shape_rerank_input()` treats chunks with empty `source_md` as unique sources
  (one per chunk) so they are not artificially limited by `max_chunks_per_source`.

### Codex Review Round 3 Fixes

Title-match cap bypass:

5. **Title-match respects hard caps** — `preserved_title` no longer bypasses
   `max_candidates` or `max_chunks_per_source`. All chunks, including title-match
   entries, now go through `_add_if_allowed()` with the same cap checks. Title-match
   chunks only get elevated priority (Phase A), not cap exemption.

### Codex Review Round 2 Fixes

Four issues addressed after initial Codex review:

1. **max_candidates hard cap** — Removed the broad-concept override that raised
   `max_candidates` above the configured value. `max_candidates` is now always
   the absolute ceiling; broad queries trade off within it via source-diverse
   selection.
2. **Two-pass source diversity** — First pass now selects only chunks from
   previously-unseen sources. Second pass fills remaining slots with extra
   chunks per source (up to `max_chunks_per_source`). This guarantees small caps
   don't lose source coverage.
3. **Rerank text includes headers** — `_build_rerank_text()` constructs
   `toc_path | doc_title | section_title \n body_snippet` within the char cap.
   This preserves title-match quality even when long DOCUMENT chunks are
   truncated.
4. **prefer_section_chunks controls sort** — `_chunk_sort_key()` now accepts a
   `prefer_section` flag. When `False`, all chunk types share type priority 0,
   so the config field is no longer a no-op.

## Skipped Checks

No checks skipped.

## Recommended Next Action

`Codex review`
