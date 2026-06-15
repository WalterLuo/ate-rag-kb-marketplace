#!/usr/bin/env python3
"""Marketplace-safe entrypoint for the ATE KB MCP stdio server."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_QDRANT_URL = "http://localhost:6333"
QDRANT_READY_PATH = "/collections"
TRUTHY_VALUES = {"1", "true", "yes", "on"}


def _expand_path(raw_path: str) -> Path:
    return Path(raw_path).expanduser().resolve()


def is_truthy(value: str | None) -> bool:
    """Return whether an environment-style string enables an option."""
    return value is not None and value.strip().lower() in TRUTHY_VALUES


def resolve_project_root(
    env: Mapping[str, str] | None = None,
    script_path: Path | None = None,
) -> Path:
    """Resolve the project root for local checkout and plugin-cache installs."""
    runtime_env = os.environ if env is None else env

    explicit_root = runtime_env.get("ATE_RAG_KB_PROJECT_ROOT")
    if explicit_root:
        return _expand_path(explicit_root)

    plugin_root = runtime_env.get("CLAUDE_PLUGIN_ROOT")
    if plugin_root:
        return _expand_path(plugin_root)

    script = Path(__file__) if script_path is None else script_path
    return script.resolve().parents[1]


def build_runtime_env(project_root: Path, base_env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Build the environment inherited by the actual MCP server process."""
    runtime_env = dict(os.environ if base_env is None else base_env)
    project_root_str = str(project_root)

    runtime_env.setdefault("ATE_RAG_KB_PROJECT_ROOT", project_root_str)
    runtime_env["CONFIG_PATH"] = (
        runtime_env.get("CONFIG_PATH")
        or runtime_env.get("ATE_RAG_KB_CONFIG_PATH")
        or str(project_root / "configs" / "config.yaml")
    )
    runtime_env.setdefault("ATE_KB_QUERY_DEVICE", "cpu")
    runtime_env.setdefault("ATE_KB_RERANKER_DEVICE", "cpu")

    return runtime_env


def build_mcp_command(project_root: Path) -> list[str]:
    """Build the command that runs the real MCP server."""
    return [
        "uv",
        "run",
        "--project",
        str(project_root),
        "-m",
        "ate_rag_kb.cli.main",
        "mcp",
    ]


def qdrant_is_ready(url: str, timeout_seconds: float = 1.0) -> bool:
    """Return whether a Qdrant HTTP endpoint is reachable."""
    ready_url = url.rstrip("/") + QDRANT_READY_PATH
    request = Request(ready_url, method="GET")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return 200 <= response.status < 500
    except HTTPError as exc:
        return 200 <= exc.code < 500
    except (OSError, TimeoutError, URLError):
        return False


def _qdrant_url(env: Mapping[str, str]) -> str:
    return env.get("ATE_KB_QDRANT_URL") or env.get("QDRANT_URL") or DEFAULT_QDRANT_URL


def maybe_bootstrap_qdrant(
    project_root: Path,
    env: Mapping[str, str] | None = None,
    wait_seconds: float = 45.0,
    poll_seconds: float = 1.0,
) -> None:
    """Start Qdrant with Docker Compose when explicitly enabled."""
    runtime_env = os.environ if env is None else env
    if not is_truthy(runtime_env.get("ATE_KB_AUTO_BOOTSTRAP")):
        return

    qdrant_url = _qdrant_url(runtime_env)
    if qdrant_is_ready(qdrant_url):
        return

    if shutil.which("docker") is None:
        raise RuntimeError(
            "ATE_KB_AUTO_BOOTSTRAP is enabled, but Docker was not found. "
            "Install Docker Desktop or set ATE_KB_AUTO_BOOTSTRAP=0 and start Qdrant yourself."
        )

    compose_file = project_root / "docker-compose.yml"
    if not compose_file.exists():
        raise RuntimeError(
            f"ATE_KB_AUTO_BOOTSTRAP is enabled, but {compose_file} does not exist."
        )

    print("ate-rag-kb: starting Qdrant with Docker Compose...", file=sys.stderr)
    subprocess.run(
        ["docker", "compose", "-f", str(compose_file), "up", "-d", "qdrant"],
        cwd=project_root,
        check=True,
    )

    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if qdrant_is_ready(qdrant_url):
            return
        time.sleep(poll_seconds)

    raise RuntimeError(
        f"Qdrant did not become reachable at {qdrant_url} within {wait_seconds:.0f}s."
    )


def main() -> int:
    project_root = resolve_project_root()
    runtime_env = build_runtime_env(project_root)

    try:
        maybe_bootstrap_qdrant(project_root, runtime_env)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"ate-rag-kb: MCP startup failed: {exc}", file=sys.stderr)
        return 1

    command = build_mcp_command(project_root)
    if shutil.which(command[0], path=runtime_env.get("PATH")) is None:
        print(
            "ate-rag-kb: uv was not found on PATH. Install uv before starting the MCP server.",
            file=sys.stderr,
        )
        return 127

    os.execvpe(command[0], command, runtime_env)
    return 127


if __name__ == "__main__":
    sys.exit(main())
