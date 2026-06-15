"""Run retrieval evaluation and generate reports."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Ensure src is on path when running directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ate_rag_kb.evaluation import DatasetLoader, EvalRunner, write_json, write_markdown
from ate_rag_kb.retrieval.pipeline import RetrievalPipeline
from ate_rag_kb.utils.config import get_config

logger = logging.getLogger(__name__)


async def main() -> int:
    config = get_config(Path("configs/config.yaml"))
    eval_config = config.section("evaluation")

    dataset_dir = Path(eval_config.get("dataset_dir", "./eval/v1"))
    output_dir = Path(eval_config.get("output_dir", "./reports"))
    default_k_values = eval_config.get("default_k_values", [1, 3, 5, 10])

    questions_path = dataset_dir / "questions.jsonl"
    if not questions_path.exists():
        logger.error("Dataset not found: %s", questions_path)
        return 1

    loader = DatasetLoader()
    questions = loader.load(questions_path)
    logger.info("Loaded %d questions from %s", len(questions), questions_path)

    pipeline = RetrievalPipeline(config)
    runner = EvalRunner(k_values=default_k_values)

    report = await runner.run(
        pipeline=pipeline,
        questions=questions,
        config_snapshot=config.to_dict(),
    )

    timestamp = report.timestamp.replace(":", "-")
    json_path = output_dir / f"eval_report_{timestamp}.json"
    md_path = output_dir / f"eval_report_{timestamp}.md"

    write_json(report, json_path)
    write_markdown(report, md_path)

    logger.info("Reports written to %s and %s", json_path, md_path)
    logger.info(
        "Results: %d success, %d failed, %.2f ms total",
        len(questions) - report.failed_count,
        report.failed_count,
        report.total_latency_ms,
    )

    # Log aggregated metrics
    for metric_name, values in report.aggregated_metrics.items():
        for k in sorted(values):
            logger.info("%s@%d = %.4f", metric_name, k, values[k])

    return 0 if report.failed_count == 0 else 2


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    sys.exit(asyncio.run(main()))
