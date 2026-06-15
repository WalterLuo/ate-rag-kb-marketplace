# Codex Task Package

## Status

`claude_done`

## Owner Handoff

- Planner and reviewer: Codex
- Implementer: Claude Code
- Integration owner: Codex

## Branch

`codex/http-rerank-input-optimization`

## Objective

Optimize HTTP reranker latency without reducing answer quality by limiting and
shortening only the documents sent to the reranker API, while preserving the
full retrieved chunks for final answer context.

## Context

The Site Control benchmark now uses the SiliconFlow HTTP reranker successfully,
but runtime can still become excessive when graph expansion inflates candidates.
The confirmed data path is:

```text
search_enriched() -> ~18 seed/enriched chunks
graph_expansion() -> ~60 additional chunks
reranker.rerank() -> sends ~78 full chunk contents to HTTP API
```

This is expensive because:

1. Graph expansion is useful for recall, but it currently feeds every expanded
   candidate into the cross-encoder reranker.
2. Some `DOCUMENT` chunks can be thousands of characters long.
3. `HttpRerankerProvider.predict()` sends a single `POST /rerank` with every
   document in `documents`.
4. The same broad question may be asked repeatedly by agents, causing duplicate
   remote rerank calls.

The target behavior is **not** to weaken retrieval quality. Keep graph expansion
and broad context available, but add a compact rerank input layer before the HTTP
provider:

- rerank fewer, better representatives;
- send shorter rerank text;
- keep original full chunks attached to the reranked results;
- retain source diversity and title/seed coverage;
- add observability so slow rerank requests explain candidate count and payload
  size.

Relevant code paths:

- `src/ate_rag_kb/retrieval/pipeline.py`
  - `retrieve_enriched()` runs graph expansion before reranking.
  - `RetrievalPipeline.__init__()` currently constructs `DocumentGraphExpander`
    without config-driven graph limits.
- `src/ate_rag_kb/retrieval/reranker.py`
  - `Reranker.rerank()` currently builds `(query, c.content)` for every chunk.
- `src/ate_rag_kb/retrieval/reranker_providers.py`
  - `HttpRerankerProvider.predict()` posts all documents to `/rerank`.
- `scripts/benchmark_reranker_mode.py`
  - Current benchmark script used for CPU/MPS/HTTP mode timing.
- `configs/config.yaml`
  - Reranker config and broad-context config live here.

External documentation checked by Codex:

- SentenceTransformers CrossEncoder supports `max_length`; longer inputs are
  truncated.
  <https://www.sbert.net/docs/package_reference/cross_encoder/model.html>
- SiliconFlow rerank API accepts `documents`, `top_n`, `return_documents`,
  `max_chunks_per_doc`, and `overlap_tokens`.
  <https://docs.siliconflow.cn/en/api-reference/rerank/create-rerank>
- `uv run --env-file` explicitly loads variables from a `.env` file.
  <https://docs.astral.sh/uv/reference/cli/#uv-run>

## Scope

Allowed changes:

- `configs/config.yaml`
- `src/ate_rag_kb/retrieval/reranker.py`
- `src/ate_rag_kb/retrieval/reranker_providers.py`
- `src/ate_rag_kb/retrieval/pipeline.py`
- New focused helper module under `src/ate_rag_kb/retrieval/` if useful, for
  example `rerank_input.py`
- `scripts/benchmark_reranker_mode.py`
- Unit tests under `tests/test_retrieval_reranker.py` or
  `tests/retrieval/test_pipeline.py`
- Completion report under
  `docs/agent_workflows/reports/2026-06-12-http-rerank-input-optimization.md`

## Out Of Scope

- Do not disable graph expansion globally.
- Do not remove broad-context assembly.
- Do not reduce answer quality by simply lowering `top_k` or turning off
  reranking.
- Do not switch embedding provider away from local as part of this task.
- Do not re-ingest data or modify Qdrant collections.
- Do not commit API keys, `.env`, shell history, or any secret values.
- Do not change generated data under `data/processed`, `data/raw`, or Qdrant
  storage.
- Do not commit, merge, push, or open a pull request.

## Implementation Requirements

1. Read `AGENTS.md`, `CLAUDE.md`, and this task package before editing.
2. Create or switch to branch `codex/http-rerank-input-optimization`.
3. Use test-driven development for the rerank input shaping behavior.
4. Add config fields with conservative defaults. Suggested names:

   ```yaml
   retrieval:
     reranker:
       input:
         max_candidates: 32
         max_chars_per_document: 2400
         max_chunks_per_source: 2
         min_sources: 6
         prefer_section_chunks: true
         preserve_title_matches: 3
       api:
         timeout_seconds: 30
         top_n: 32
         max_chunks_per_doc: 8
         overlap_tokens: 40
   ```

   The exact field names may differ if a cleaner local pattern exists, but the
   behavior must be configurable.

5. Implement rerank input shaping with these invariants:
   - HTTP reranker receives at most `max_candidates` documents.
   - HTTP reranker document text is capped by `max_chars_per_document`.
   - Selection is source-diverse and respects `max_chunks_per_source`.
   - Original seed/search chunks and exact title matches are favored over graph
     expansion-only chunks.
   - `SECTION` chunks are preferred over huge `DOCUMENT` chunks when they carry
     useful title/section content.
   - The returned `Chunk` objects remain the original full chunks, not truncated
     copies, so final context quality is preserved.
   - Local reranker should also benefit from the same max length/candidate
     limiting unless doing so would break existing tests; if different behavior
     is necessary, document why.

6. Add HTTP provider request controls:
   - Include `max_chunks_per_doc` and `overlap_tokens` in the SiliconFlow
     request when configured.
   - Keep `return_documents: false`.
   - Ensure `top_n <= len(documents)` and `top_n <= max_candidates`.
   - Include non-secret error messages if the API returns 429, 503, or 504.

7. Add observability:
   - Add reranker stats such as:

     ```text
     pre_rerank_candidate_count
     rerank_input_candidate_count
     rerank_input_total_chars
     rerank_input_max_chars_per_document
     rerank_input_source_count
     rerank_input_truncated_document_count
     ```

   - Propagate these stats into existing `processing` output alongside
     `post_rerank_candidate_count`.

8. Add duplicate-call protection:
   - Add a small in-process cache for HTTP rerank scoring keyed by query,
     provider/model, and stable document digests.
   - Do not cache or log API keys.
   - Cache may be simple LRU with bounded size, for example 64 entries.
   - If cache risk is high, implement only instrumentation and clearly justify
     the skipped cache in the report.

9. Update `scripts/benchmark_reranker_mode.py` so benchmark output includes:
   - provider;
   - wall time;
   - reranking time;
   - graph expansion time;
   - pre-rerank candidate count;
   - rerank input candidate count;
   - rerank input total chars;
   - final chunk count.

10. Keep `embedding.provider` local. The embedding model used for query vectors
    should remain aligned with the indexed Qdrant vectors unless a separate
    ingestion/embedding migration is explicitly planned.

## Acceptance Criteria

- [ ] HTTP reranker request document count is bounded and observable. For the
      Site Control query, it must not send ~78 documents to the API.
- [ ] HTTP reranker request payload is bounded by document count and per-document
      character cap.
- [ ] Final returned chunks/context still use full original chunk content.
- [ ] Site Control query still returns plausible source coverage, including
      Site Control state/focus sources such as `v93000/smt7/100096.md` and at
      least one site-focus or site-control command source such as
      `v93000/smt7/143608_2.md`, `v93000/smt7/98698.md`, or
      `v93000/smt7/42588.md`.
- [ ] Benchmark with `ATE_KB_RERANKER_PROVIDER=http` completes successfully with
      exported `SILICONFLOW_API_KEY`.
- [ ] Benchmark report shows rerank input count, total chars, wall time, and
      reranking time before/after or clearly explains why before/after cannot be
      compared.
- [ ] Unit tests cover candidate limiting, text truncation, source diversity,
      preservation of full original chunks, and HTTP request fields.
- [ ] No secrets are printed, committed, or stored.
- [ ] `embedding.provider` remains local, with the report explaining why this is
      not the current bottleneck.

## Required Verification Commands

Run focused tests first:

```bash
uv run pytest tests/test_retrieval_reranker.py -q
uv run pytest tests/retrieval/test_pipeline.py -q
```

Run broader affected tests:

```bash
uv run pytest tests/retrieval/test_document_graph_expander.py tests/retrieval/test_broad_context.py tests/mcp/test_tools.py -q
```

Confirm no secret was written:

```bash
rg -n "sk-|SILICONFLOW_API_KEY=.*sk" docs scripts configs src tests
```

Run the HTTP benchmark with the key supplied only by environment:

```bash
ATE_KB_RERANKER_PROVIDER=http uv run python scripts/benchmark_reranker_mode.py --top-k 15 --runs 1
```

If using `.env`, run:

```bash
ATE_KB_RERANKER_PROVIDER=http uv run --env-file .env python scripts/benchmark_reranker_mode.py --top-k 15 --runs 1
```

Optional repeat-run cache check:

```bash
ATE_KB_RERANKER_PROVIDER=http uv run python scripts/benchmark_reranker_mode.py --top-k 15 --runs 2
```

## Expected Report Path

```text
docs/agent_workflows/reports/2026-06-12-http-rerank-input-optimization.md
```

## Report Requirements

The completion report must include:

- changed files;
- tests run and results;
- benchmark command and output summary;
- pre-rerank candidate count and rerank input candidate count;
- rerank input total chars;
- wall time and reranking time;
- source coverage for the Site Control query;
- whether caching was implemented;
- confirmation that no API key or secret was committed;
- recommended next action: `Codex review`.
