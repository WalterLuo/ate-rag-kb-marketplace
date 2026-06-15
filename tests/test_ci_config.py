"""Regression checks for repository quality gates."""

from __future__ import annotations

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_github_actions_ci_runs_lint_and_tests() -> None:
    workflow_path = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"

    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["test"]["steps"]
    run_commands = "\n".join(step.get("run", "") for step in steps)

    assert "uv run ruff check ." in run_commands
    assert "uv run pytest -q" in run_commands
