"""Unit tests for evaluation dataset loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from ate_rag_kb.evaluation.dataset_loader import DatasetLoader
from ate_rag_kb.evaluation.models import EvalQuestion


class TestDatasetLoader:
    def test_load_valid_jsonl(self, tmp_path: Path) -> None:
        path = tmp_path / "questions.jsonl"
        path.write_text(
            '{"id": "q1", "query": "What is X?", "expected_chunk_ids": ["c1"], "category": "A"}\n'
            '{"id": "q2", "query": "How to Y?", "expected_source_mds": ["doc.md"]}\n',
            encoding="utf-8",
        )
        loader = DatasetLoader()
        questions = loader.load(path)
        assert len(questions) == 2
        assert questions[0] == EvalQuestion(
            id="q1", query="What is X?", expected_chunk_ids=("c1",), category="A"
        )
        assert questions[1] == EvalQuestion(
            id="q2", query="How to Y?", expected_source_mds=("doc.md",)
        )

    def test_skips_empty_lines(self, tmp_path: Path) -> None:
        path = tmp_path / "questions.jsonl"
        path.write_text(
            '\n'
            '{"id": "q1", "query": "What?"}\n'
            '\n',
            encoding="utf-8",
        )
        loader = DatasetLoader()
        questions = loader.load(path)
        assert len(questions) == 1

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        loader = DatasetLoader()
        with pytest.raises(FileNotFoundError):
            loader.load(tmp_path / "missing.jsonl")

    def test_invalid_json_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.jsonl"
        path.write_text('not json\n', encoding="utf-8")
        loader = DatasetLoader()
        with pytest.raises(ValueError, match="Invalid JSON on line 1"):
            loader.load(path)

    def test_missing_id_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.jsonl"
        path.write_text('{"query": "What?"}\n', encoding="utf-8")
        loader = DatasetLoader()
        with pytest.raises(ValueError, match="Missing or invalid 'id'"):
            loader.load(path)

    def test_missing_query_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.jsonl"
        path.write_text('{"id": "q1"}\n', encoding="utf-8")
        loader = DatasetLoader()
        with pytest.raises(ValueError, match="Missing or invalid 'query'"):
            loader.load(path)
