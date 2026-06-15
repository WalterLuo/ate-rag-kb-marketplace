"""Backfill expected_source_mds from evaluation_50_questions.json into questions.jsonl."""

from __future__ import annotations

import json
from pathlib import Path


def main() -> None:
    data = json.loads(Path("data/evaluation_50_questions.json").read_text())
    questions = data["questions"]

    lines = Path("eval/v1/questions.jsonl").read_text().strip().split("\n")
    existing = [json.loads(line) for line in lines]

    source_map = {}
    for q in questions:
        query = q["question"]
        sources = list(dict.fromkeys([r["source_md"] for r in q["results"]]))
        source_map[query] = sources

    updated = []
    for eq in existing:
        query = eq["query"]
        if query in source_map:
            eq["expected_source_mds"] = source_map[query]
            eq["metadata"]["reviewed"] = True
        updated.append(eq)

    out = "\n".join(json.dumps(q, ensure_ascii=False) for q in updated) + "\n"
    Path("eval/v1/questions.jsonl").write_text(out, encoding="utf-8")
    print(f"Updated {len(updated)} questions")
    for q in updated[:3]:
        print(q["id"], q["query"], "->", q["expected_source_mds"])


if __name__ == "__main__":
    main()
