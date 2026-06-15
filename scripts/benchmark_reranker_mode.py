"""Benchmark reranker modes for Site Control retrieval.

Usage:
    # CPU (default baseline)
    uv run python scripts/benchmark_reranker_mode.py --top-k 15 --runs 1

    # MPS (Apple Silicon GPU)
    PYTORCH_ENABLE_MPS_FALLBACK=1 ATE_KB_RERANKER_PROVIDER=local \
        ATE_KB_RERANKER_DEVICE=mps uv run python scripts/benchmark_reranker_mode.py \
        --top-k 15 --runs 1

    # HTTP API
    ATE_KB_RERANKER_PROVIDER=http uv run python scripts/benchmark_reranker_mode.py \
        --top-k 15 --runs 1

    # HTTP API with .env file
    ATE_KB_RERANKER_PROVIDER=http uv run --env-file .env \
        python scripts/benchmark_reranker_mode.py --top-k 15 --runs 1

    # Override reranker batch size (for MPS diagnostic)
    ATE_KB_RERANKER_BATCH_SIZE=1 uv run python scripts/benchmark_reranker_mode.py \
        --top-k 15 --runs 1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

# Ensure project src is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ate_rag_kb.utils.config import Config, get_config, reload_config

QUERY = "ATE SMT7 中 Site Control 的作用是什么"
PLATFORM_FILTERS = {"platform": "v93000", "software": "smt7"}


def _run_once(config: Config, top_k: int, run_index: int) -> dict:
    """Run a single benchmark iteration and return timing + diagnostics."""
    import asyncio

    from ate_rag_kb.retrieval.coordinator import build_retrieval_coordinator

    pipeline_run_start = time.perf_counter()

    coordinator = build_retrieval_coordinator(config)

    # Determine provider/device for logging
    reranker_provider = config.get("retrieval.reranker.provider", "local")
    reranker_device = config.get("retrieval.reranker.device", "cpu")
    reranker_batch_size = config.get("retrieval.reranker.batch_size", 4)

    async def _ask() -> dict:
        try:
            result = await coordinator.retrieve(
                QUERY,
                top_k=top_k,
                filters=PLATFORM_FILTERS,
                rerank=True,
                expand_parents=True,
                expand_siblings=True,
                compress=True,
            )
            return {
                "answer_mode": result.answer_mode,
                "groups": [
                    {
                        "scope": str(g.scope),
                        "chunk_count": len(g.chunks),
                        "processing_keys": sorted(g.processing.keys()),
                        "timing": {
                            k: v
                            for k, v in g.processing.items()
                            if k.startswith("timing_")
                        },
                        "rerank_input_stats": {
                            k: v
                            for k, v in g.processing.items()
                            if k.startswith("rerank_input_")
                            or k == "pre_rerank_candidate_count"
                        },
                    }
                    for g in result.groups
                ],
            }
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}

    try:
        data = asyncio.run(_ask())
    except Exception as exc:
        data = {"error": f"{type(exc).__name__}: {exc}"}

    wall_ms = (time.perf_counter() - pipeline_run_start) * 1000.0

    return {
        "run": run_index,
        "provider": reranker_provider,
        "device": reranker_device,
        "batch_size": reranker_batch_size,
        "wall_ms": round(wall_ms, 1),
        "result": data,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark reranker modes")
    parser.add_argument("--top-k", type=int, default=15, help="top_k for retrieval")
    parser.add_argument("--runs", type=int, default=1, help="Number of iterations")
    args = parser.parse_args()

    # Allow overriding batch size via env var for diagnostics
    if os.environ.get("ATE_KB_RERANKER_BATCH_SIZE"):
        pass  # Config reads env vars; will be picked up via config.yaml expansion

    reload_config()
    config = get_config()

    # Allow overriding batch_size via env var for diagnostics (e.g. MPS batch_size=1)
    env_batch = os.environ.get("ATE_KB_RERANKER_BATCH_SIZE")
    if env_batch is not None:
        config._data.setdefault("retrieval", {}).setdefault("reranker", {})[
            "batch_size"
        ] = int(env_batch)

    reranker_provider = config.get("retrieval.reranker.provider", "local")
    reranker_device = config.get("retrieval.reranker.device", "cpu")
    reranker_batch_size = config.get("retrieval.reranker.batch_size", 4)

    print("=== Reranker Mode Benchmark ===")
    print(f"Query:     {QUERY}")
    print(f"Provider:  {reranker_provider}")
    print(f"Device:    {reranker_device}")
    print(f"Batch:     {reranker_batch_size}")
    print(f"Top-K:     {args.top_k}")
    print(f"Runs:      {args.runs}")
    print()

    results = []
    for i in range(args.runs):
        print(f"--- Run {i + 1}/{args.runs} ---")
        result = _run_once(config, args.top_k, i)
        results.append(result)

        error = result.get("result", {}).get("error")
        if error:
            print(f"  ERROR: {error}")
        else:
            print(f"  Wall time: {result['wall_ms']:.1f} ms")
            for group in result.get("result", {}).get("groups", []):
                timing = group.get("timing", {})
                rerank_stats = group.get("rerank_input_stats", {})
                if timing or rerank_stats:
                    print(f"  Scope: {group['scope']}")
                    for k in sorted(timing.keys()):
                        print(f"    {k}: {timing[k]:.1f} ms")
                    if rerank_stats:
                        print("    --- Rerank Input Stats ---")
                        for k in sorted(rerank_stats.keys()):
                            print(f"    {k}: {rerank_stats[k]}")
                chunk_count = group.get("chunk_count", 0)
                print(f"  Final chunks: {chunk_count}")
        print()

    # Summary
    successful = [r for r in results if "error" not in r.get("result", {})]
    failed = [r for r in results if "error" in r.get("result", {})]

    print("=== Summary ===")
    print(f"Successful: {len(successful)}/{len(results)}")
    print(f"Failed:     {len(failed)}/{len(results)}")

    if successful:
        walls = [r["wall_ms"] for r in successful]
        print(f"Wall time:  min={min(walls):.1f} ms  max={max(walls):.1f} ms  "
              f"avg={sum(walls) / len(walls):.1f} ms")

        # Collect all timing keys across runs
        all_timings: dict[str, list[float]] = {}
        for r in successful:
            for group in r.get("result", {}).get("groups", []):
                for k, v in group.get("timing", {}).items():
                    all_timings.setdefault(k, []).append(v)

        if all_timings:
            print("\nPipeline phase timing (avg ms):")
            for k in sorted(all_timings.keys()):
                vals = all_timings[k]
                avg = sum(vals) / len(vals)
                print(f"  {k}: {avg:.1f}")

        # Collect rerank input stats
        all_rerank_stats: dict[str, list] = {}
        for r in successful:
            for group in r.get("result", {}).get("groups", []):
                for k, v in group.get("rerank_input_stats", {}).items():
                    all_rerank_stats.setdefault(k, []).append(v)

        if all_rerank_stats:
            print("\nRerank input stats (avg):")
            for k in sorted(all_rerank_stats.keys()):
                vals = all_rerank_stats[k]
                avg = sum(vals) / len(vals)
                print(f"  {k}: {avg:.1f}")

    if failed:
        print("\nErrors:")
        for r in failed:
            print(f"  Run {r['run']}: {r['result']['error']}")

    # Output JSON for programmatic consumption
    print("\n--- JSON ---")
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
