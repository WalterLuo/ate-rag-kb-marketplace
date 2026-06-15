"""Regression tests for the marketplace MCP startup wrapper."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

PROJECT_ROOT = Path(__file__).resolve().parents[1]
START_MCP_PATH = PROJECT_ROOT / "scripts" / "start_mcp.py"


def load_start_mcp() -> ModuleType:
    spec = importlib.util.spec_from_file_location("start_mcp", START_MCP_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_resolve_project_root_prefers_explicit_project_root(tmp_path: Path) -> None:
    start_mcp = load_start_mcp()
    explicit_root = tmp_path / "existing-checkout"
    plugin_root = tmp_path / "plugin-cache"

    root = start_mcp.resolve_project_root(
        env={
            "ATE_RAG_KB_PROJECT_ROOT": str(explicit_root),
            "CLAUDE_PLUGIN_ROOT": str(plugin_root),
        },
        script_path=START_MCP_PATH,
    )

    assert root == explicit_root.resolve()


def test_resolve_project_root_uses_plugin_root_before_script_location(tmp_path: Path) -> None:
    start_mcp = load_start_mcp()
    plugin_root = tmp_path / "plugin-cache"

    root = start_mcp.resolve_project_root(
        env={"CLAUDE_PLUGIN_ROOT": str(plugin_root)},
        script_path=START_MCP_PATH,
    )

    assert root == plugin_root.resolve()


def test_resolve_project_root_falls_back_to_script_parent() -> None:
    start_mcp = load_start_mcp()

    root = start_mcp.resolve_project_root(env={}, script_path=START_MCP_PATH)

    assert root == PROJECT_ROOT


def test_build_runtime_env_sets_defaults_and_preserves_existing_values(tmp_path: Path) -> None:
    start_mcp = load_start_mcp()
    project_root = tmp_path / "ate-rag-kb"
    base_env = {
        "PATH": "/usr/bin",
        "SILICONFLOW_API_KEY": "secret",
        "ATE_KB_QUERY_DEVICE": "mps",
    }

    runtime_env = start_mcp.build_runtime_env(project_root, base_env)

    assert runtime_env["PATH"] == "/usr/bin"
    assert runtime_env["SILICONFLOW_API_KEY"] == "secret"
    assert runtime_env["ATE_RAG_KB_PROJECT_ROOT"] == str(project_root)
    assert runtime_env["CONFIG_PATH"] == str(project_root / "configs" / "config.yaml")
    assert runtime_env["ATE_KB_QUERY_DEVICE"] == "mps"
    assert runtime_env["ATE_KB_RERANKER_DEVICE"] == "cpu"


def test_build_runtime_env_honors_config_path_override(tmp_path: Path) -> None:
    start_mcp = load_start_mcp()
    project_root = tmp_path / "ate-rag-kb"
    config_path = tmp_path / "custom.yaml"

    runtime_env = start_mcp.build_runtime_env(
        project_root,
        {"ATE_RAG_KB_CONFIG_PATH": str(config_path)},
    )

    assert runtime_env["CONFIG_PATH"] == str(config_path)


def test_build_mcp_command_uses_resolved_project_root(tmp_path: Path) -> None:
    start_mcp = load_start_mcp()
    project_root = tmp_path / "ate-rag-kb"

    command = start_mcp.build_mcp_command(project_root)

    assert command == [
        "uv",
        "run",
        "--project",
        str(project_root),
        "-m",
        "ate_rag_kb.cli.main",
        "mcp",
    ]


def test_maybe_bootstrap_qdrant_skips_without_opt_in(tmp_path: Path, monkeypatch) -> None:
    start_mcp = load_start_mcp()

    def fail_if_called(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("Qdrant bootstrap should not run without opt-in")

    monkeypatch.setattr(start_mcp, "qdrant_is_ready", fail_if_called)
    monkeypatch.setattr(start_mcp.subprocess, "run", fail_if_called)

    start_mcp.maybe_bootstrap_qdrant(tmp_path, {"ATE_KB_AUTO_BOOTSTRAP": "0"})


def test_maybe_bootstrap_qdrant_starts_docker_when_enabled(tmp_path: Path, monkeypatch) -> None:
    start_mcp = load_start_mcp()
    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text("services: {}\n", encoding="utf-8")
    readiness = iter([False, True])
    commands: list[list[str]] = []

    monkeypatch.setattr(start_mcp.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(start_mcp, "qdrant_is_ready", lambda url: next(readiness))
    monkeypatch.setattr(start_mcp.time, "sleep", lambda seconds: None)

    def fake_run(command, cwd, check):  # noqa: ANN001
        commands.append(command)
        assert cwd == tmp_path
        assert check is True

    monkeypatch.setattr(start_mcp.subprocess, "run", fake_run)

    start_mcp.maybe_bootstrap_qdrant(
        tmp_path,
        {"ATE_KB_AUTO_BOOTSTRAP": "1", "ATE_KB_QDRANT_URL": "http://localhost:6333"},
        wait_seconds=1,
    )

    assert commands == [
        ["docker", "compose", "-f", str(compose_file), "up", "-d", "qdrant"]
    ]
