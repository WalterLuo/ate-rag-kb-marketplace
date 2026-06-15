"""Dataset loader for evaluation questions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ate_rag_kb.evaluation.models import EvalQuestion


class DatasetLoader:
    """Load evaluation questions from a JSONL file."""

    def load(self, path: Path) -> list[EvalQuestion]:
        """Read JSONL and return validated EvalQuestion instances."""
        if not path.exists():
            raise FileNotFoundError(f"Dataset not found: {path}")

        questions: list[EvalQuestion] = []
        raw_text = path.read_text(encoding="utf-8")

        for line_number, line in enumerate(raw_text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on line {line_number}: {exc}") from exc

            questions.append(self._parse_record(record, line_number))

        return questions

    @staticmethod
    def _parse_record(record: dict[str, Any], line_number: int) -> EvalQuestion:
        """Validate and convert a raw JSON record into an EvalQuestion."""
        question_id = record.get("id")
        query = record.get("query")
        if not question_id or not isinstance(question_id, str):
            raise ValueError(f"Missing or invalid 'id' on line {line_number}")
        if not query or not isinstance(query, str):
            raise ValueError(f"Missing or invalid 'query' on line {line_number}")

        return EvalQuestion(
            id=question_id,
            query=query,
            expected_chunk_ids=tuple(record.get("expected_chunk_ids", [])),
            expected_source_mds=tuple(record.get("expected_source_mds", [])),
            category=record.get("category", ""),
            metadata=record.get("metadata", {}),
        )
