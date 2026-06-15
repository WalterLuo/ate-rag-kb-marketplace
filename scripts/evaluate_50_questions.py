"""Evaluate retrieval quality on 50 ATE questions."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from ate_rag_kb.retrieval.pipeline import RetrievalPipeline
from ate_rag_kb.utils.config import get_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

QUESTIONS: list[tuple[str, str]] = [
    ("Timing / Timeset", "How to configure drive edge in TDC?"),
    ("Timing / Timeset", "What is the difference between drive edge and compare edge?"),
    ("Timing / Timeset", "How to create a new timeset?"),
    ("Timing / Timeset", "How does edge placement work?"),
    ("Timing / Timeset", "What causes timing mismatch across sites?"),
    ("Timing / Timeset", "How to debug timing fail on high frequency pattern?"),
    ("Timing / Timeset", "How to apply different timing to different pin groups?"),
    ("Timing / Timeset", "What is waveform table in TDC?"),
    ("Timing / Timeset", "How to configure strobe edge?"),
    ("Timing / Timeset", "How to reuse timing sets between test methods?"),
    ("Pattern", "How to enable burst pattern mode?"),
    ("Pattern", "How does pattern looping work?"),
    ("Pattern", "How to debug pattern miscompare?"),
    ("Pattern", "How to load external pattern files?"),
    ("Pattern", "What causes pattern alignment failure?"),
    ("Pattern", "How to configure start label in pattern execution?"),
    ("Pattern", "How to stop pattern on first fail?"),
    ("Pattern", "How to debug vector mismatch?"),
    ("Pattern", "How to run pattern in single site only?"),
    ("Pattern", "What is the difference between burst and functional pattern?"),
    ("DPS / Power", "What does DPS alarm 2034 mean?"),
    ("DPS / Power", "How to configure voltage clamp?"),
    ("DPS / Power", "How to debug overcurrent issue?"),
    ("DPS / Power", "How to enable DPS sequencing?"),
    ("DPS / Power", "What is foldback protection?"),
    ("DPS / Power", "How to force voltage and measure current?"),
    ("DPS / Power", "Why does DPS trip during pattern execution?"),
    ("DPS / Power", "How to configure power up sequence?"),
    ("DPS / Power", "What causes unstable DPS measurement?"),
    ("DPS / Power", "How to set current limit in DPS?"),
    ("PMU / Measurement", "How to configure PMU force current mode?"),
    ("PMU / Measurement", "What is PMU measurement range?"),
    ("PMU / Measurement", "How to debug PMU saturation?"),
    ("PMU / Measurement", "How to perform leakage test?"),
    ("PMU / Measurement", "How to improve PMU accuracy?"),
    ("PMU / Measurement", "What causes unstable PMU readings?"),
    ("PMU / Measurement", "How to configure PMU averaging?"),
    ("PMU / Measurement", "How to perform continuity test?"),
    ("PMU / Measurement", "What is the difference between FVMI and FIMV?"),
    ("PMU / Measurement", "How to calibrate PMU channels?"),
    ("Flow / Test Program", "How does flow bypass work?"),
    ("Flow / Test Program", "How to run tests conditionally in flow?"),
    ("Flow / Test Program", "How to debug multisite flow issue?"),
    ("Flow / Test Program", "How to skip failing test items automatically?"),
    ("Flow / Test Program", "How to execute different flow per bin?"),
    ("Flow / Test Program", "What causes site desynchronization?"),
    ("Flow / Test Program", "How to debug flow jump issue?"),
    ("Flow / Test Program", "How to share variables between test methods?"),
    ("Flow / Test Program", "How to enable parallel test execution?"),
    ("Flow / Test Program", "How to trace test item execution order?"),
]


def truncate(text: str, max_len: int = 300) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len].rsplit(" ", 1)[0] + " ..."


async def evaluate() -> dict:
    config = get_config(Path("configs/config.yaml"))
    pipeline = RetrievalPipeline(config)

    results: list[dict] = []
    total_start = time.perf_counter()

    for idx, (category, question) in enumerate(QUESTIONS, 1):
        logger.info("[%d/50] %s", idx, question)
        start = time.perf_counter()

        try:
            chunks_with_scores = await pipeline.search(question, top_k=5)
        except Exception as exc:
            logger.error("Search failed for '%s': %s", question, exc)
            results.append({
                "index": idx,
                "category": category,
                "question": question,
                "error": str(exc),
                "latency_ms": round((time.perf_counter() - start) * 1000, 2),
                "results": [],
            })
            continue

        top_results = []
        for chunk, score in chunks_with_scores:
            top_results.append({
                "score": round(float(score), 6),
                "chunk_type": chunk.chunk_type.value,
                "platform": chunk.platform,
                "doc_title": chunk.doc_title,
                "section_title": chunk.section_title,
                "source_md": chunk.source_md,
                "content_preview": truncate(chunk.content, 400),
            })

        results.append({
            "index": idx,
            "category": category,
            "question": question,
            "latency_ms": round((time.perf_counter() - start) * 1000, 2),
            "results": top_results,
        })

    total_latency_ms = round((time.perf_counter() - total_start) * 1000, 2)

    summary = {
        "total_questions": len(QUESTIONS),
        "successful": sum(1 for r in results if "error" not in r),
        "failed": sum(1 for r in results if "error" in r),
        "total_latency_ms": total_latency_ms,
        "avg_latency_ms": round(total_latency_ms / len(QUESTIONS), 2),
    }

    output = {
        "summary": summary,
        "questions": results,
    }

    out_path = Path("data/evaluation_50_questions.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Results saved to %s", out_path)
    return output


if __name__ == "__main__":
    asyncio.run(evaluate())
