#!/usr/bin/env python3
"""Install MCP server configuration and agent policy for AI CLI harnesses.

This script detects which AI CLI tools are installed and configures the
ate-rag-kb MCP server for each one. It can also install a managed ATE KB
routing policy so agents use the MCP tools before web, shell, or raw-file
fallbacks.

Supported harnesses:
  - Claude Code      (~/.claude/settings.json)
  - Cursor           (~/.cursor/mcp.json)
  - Codex CLI        (~/.codex/settings.json)
  - GitHub Copilot   (VS Code settings or CLI config)

Usage:
    uv run python scripts/install_mcp.py
    uv run python scripts/install_mcp.py --harness claude,cursor
    uv run python scripts/install_mcp.py --project-only
    uv run python scripts/install_mcp.py --install-agent-policy
    uv run python scripts/install_mcp.py --skip-agent-policy
    uv run python scripts/install_mcp.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import platform
import shutil
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# MCP server definition
MCP_SERVER_NAME = "ate-kb"

POLICY_BLOCK_START = "<!-- BEGIN ATE_KB_ROUTING_POLICY -->"
POLICY_BLOCK_END = "<!-- END ATE_KB_ROUTING_POLICY -->"

HARNESS_CONFIGS: dict[str, dict[str, Any]] = {
    "claude": {
        "name": "Claude Code",
        "global_config": {
            "darwin": "~/Library/Application Support/Claude/settings.json",
            "linux": "~/.config/claude/settings.json",
            "win32": "~/AppData/Roaming/Claude/settings.json",
        },
        "project_config": ".claude/settings.json",
        "mcp_key": "mcpServers",
    },
    "cursor": {
        "name": "Cursor",
        "global_config": {
            "darwin": "~/.cursor/mcp.json",
            "linux": "~/.cursor/mcp.json",
            "win32": "~/AppData/Roaming/.cursor/mcp.json",
        },
        "project_config": ".cursor/mcp.json",
        "mcp_key": "mcpServers",
    },
    "codex": {
        "name": "Codex CLI",
        "global_config": {
            "darwin": "~/.codex/settings.json",
            "linux": "~/.codex/settings.json",
            "win32": "~/AppData/Roaming/codex/settings.json",
        },
        "project_config": ".codex/settings.json",
        "mcp_key": "mcpServers",
    },
}

POLICY_CONFIGS: dict[str, dict[str, Any]] = {
    "codex": {
        "name": "Codex",
        "global_policy": {
            "darwin": "~/.codex/AGENTS.md",
            "linux": "~/.codex/AGENTS.md",
            "win32": "~/AppData/Roaming/codex/AGENTS.md",
        },
        "project_policy": "AGENTS.md",
    },
    "claude": {
        "name": "Claude Code",
        "global_policy": {
            "darwin": "~/.claude/CLAUDE.md",
            "linux": "~/.claude/CLAUDE.md",
            "win32": "~/AppData/Roaming/Claude/CLAUDE.md",
        },
        "project_policy": "CLAUDE.md",
    },
}


def resolve_project_root() -> Path:
    """Resolve project root from script location."""
    return Path(__file__).resolve().parents[1]


def get_platform() -> str:
    """Return normalized platform key."""
    system = platform.system()
    if system == "Darwin":
        return "darwin"
    if system == "Linux":
        return "linux"
    if system == "Windows":
        return "win32"
    return system.lower()


def build_mcp_server_config(project_root: Path) -> dict[str, Any]:
    """Build an MCP server config that works outside the project directory."""
    resolved_root = project_root.resolve()
    return {
        "command": "uv",
        "args": [
            "run",
            "--project",
            str(resolved_root),
            "python",
            str(resolved_root / "scripts" / "start_mcp.py"),
        ],
        "env": {
            "ATE_RAG_KB_PROJECT_ROOT": str(resolved_root),
            "CONFIG_PATH": str(resolved_root / "configs" / "config.yaml"),
            "ATE_KB_QUERY_DEVICE": "cpu",
            "ATE_KB_RERANKER_DEVICE": "cpu",
            "ATE_KB_AUTO_BOOTSTRAP": "1",
        },
    }


def build_agent_policy_block() -> str:
    """Return the managed ATE KB routing policy block."""
    body = """# ATE KB Routing

When the user asks any technical or business question about ATE documentation,
SmarTest, SMT7, SMT8, TDC, Advantest V93000, Teradyne J750, IG-XL, pin
configuration, timing, levels, patterns, DPS, PMU, test flow, tester behavior,
command syntax, or API references, use the local ATE knowledge-base MCP before
any other source.

Required first steps:

1. If `ate_kb` MCP tools are visible, call `ate_kb.ask` or `ate_kb.retrieve`.
2. If `ate_kb` tools are not visible in Codex, first call `tool_search` with a
   query such as `ate_kb status ask retrieve search get_document`.
3. After exposing the tools, call `ate_kb.status` when availability is
   uncertain, then call `ate_kb.ask` or `ate_kb.retrieve`.
4. Use `ate_kb.get_document` only after `ate_kb.ask` or `ate_kb.retrieve`
   identifies relevant `source_md` files, and use explicit `limit` / `offset`
   for large documents.
5. Use `ate_kb.search` only for exploratory discovery or source-file location.

Do not answer ATE KB questions from model memory, WebSearch, shell grep/rg, CLI
search, or raw markdown reads as the first step. Fallback sources are allowed
only when MCP is unavailable, fails, or returns insufficient context.

When the answer comes from the KB, cite `source_md`, `section_title`, and the
relevant document or command names.
"""
    return f"{POLICY_BLOCK_START}\n{body.rstrip()}\n{POLICY_BLOCK_END}\n"


def upsert_managed_block(existing: str, block: str) -> str:
    """Append or replace the managed policy block in existing text."""
    start = existing.find(POLICY_BLOCK_START)
    end = existing.find(POLICY_BLOCK_END)
    if start != -1 and end != -1 and end >= start:
        end += len(POLICY_BLOCK_END)
        suffix = existing[end:]
        if suffix.startswith("\n"):
            suffix = suffix[1:]
        return existing[:start].rstrip() + "\n\n" + block.rstrip() + "\n" + suffix

    separator = "" if not existing.strip() else "\n\n"
    return existing.rstrip() + separator + block


def install_policy_file(path: Path, block: str, dry_run: bool = False) -> bool:
    """Install or update the managed policy block in a markdown file."""
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    updated = upsert_managed_block(existing, block)
    if updated == existing:
        logger.info("  [OK] Agent policy already up-to-date: %s", path)
        return False
    if dry_run:
        logger.info("[DRY-RUN] Would update agent policy: %s", path)
        logger.info("[DRY-RUN] Managed block:\n%s", block.rstrip())
        return True

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(updated, encoding="utf-8")
    logger.info("  [OK] Agent policy updated: %s", path)
    return True


def load_json(path: Path) -> dict[str, Any]:
    """Load JSON if it exists, otherwise return empty dict."""
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.warning("Failed to parse %s: %s", path, exc)
    return {}


def save_json(path: Path, data: dict[str, Any], dry_run: bool = False) -> bool:
    """Save data to JSON file."""
    if dry_run:
        logger.info("[DRY-RUN] Would write to %s", path)
        logger.info("[DRY-RUN] Content:\n%s", json.dumps(data, indent=2, ensure_ascii=False))
        return True

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    logger.info("Updated: %s", path)
    return True


def configure_harness(
    harness_id: str,
    harness_info: dict[str, Any],
    project_root: Path,
    project_only: bool,
    dry_run: bool,
) -> bool:
    """Configure MCP server for a single harness."""
    harness_name = harness_info["name"]
    plat = get_platform()
    mcp_key = harness_info["mcp_key"]
    mcp_server_config = build_mcp_server_config(project_root)

    # Project-level config
    project_config_path = project_root / harness_info["project_config"]

    # Global config
    global_config_path = None
    if not project_only and plat in harness_info["global_config"]:
        global_config_path = Path(harness_info["global_config"][plat]).expanduser()

    configured = False

    # Try project-level first
    if project_config_path.parent.exists() or project_root.exists():
        config = load_json(project_config_path)
        if mcp_key not in config:
            config[mcp_key] = {}

        existing = config[mcp_key].get(MCP_SERVER_NAME)
        if existing == mcp_server_config:
            logger.info("  [OK] %s project config already up-to-date: %s", harness_name, project_config_path)
        else:
            config[mcp_key][MCP_SERVER_NAME] = mcp_server_config
            if save_json(project_config_path, config, dry_run):
                logger.info("  [OK] %s project config updated: %s", harness_name, project_config_path)
                configured = True

    # Then global
    if global_config_path and global_config_path.parent.exists():
        config = load_json(global_config_path)
        if mcp_key not in config:
            config[mcp_key] = {}

        existing = config[mcp_key].get(MCP_SERVER_NAME)
        if existing == mcp_server_config:
            logger.info("  [OK] %s global config already up-to-date: %s", harness_name, global_config_path)
        else:
            config[mcp_key][MCP_SERVER_NAME] = mcp_server_config
            if save_json(global_config_path, config, dry_run):
                logger.info("  [OK] %s global config updated: %s", harness_name, global_config_path)
                configured = True

    return configured


def install_agent_policies(
    harness_ids: list[str],
    project_root: Path,
    project_only: bool,
    dry_run: bool,
) -> bool:
    """Install managed agent policy blocks for supported harnesses."""
    block = build_agent_policy_block()
    plat = get_platform()
    changed = False

    for harness_id in harness_ids:
        policy_info = POLICY_CONFIGS.get(harness_id)
        if policy_info is None:
            continue

        policy_paths: list[Path] = []
        if project_only:
            project_policy = policy_info.get("project_policy")
            if project_policy:
                policy_paths.append(project_root / project_policy)
        else:
            global_policy = policy_info.get("global_policy", {}).get(plat)
            if global_policy:
                policy_paths.append(Path(global_policy).expanduser())

        if not policy_paths:
            continue

        logger.info("%s agent policy:", policy_info["name"])
        for policy_path in policy_paths:
            if install_policy_file(policy_path, block, dry_run):
                changed = True
        logger.info("")

    return changed


def check_prerequisites(project_root: Path) -> bool:
    """Check that the project is ready for MCP usage."""
    ok = True

    # Check uv
    if shutil.which("uv") is None:
        logger.warning("  'uv' not found in PATH. Install from https://docs.astral.sh/uv/")
        ok = False
    else:
        logger.info("  [OK] uv found")

    # Check pyproject.toml
    if not (project_root / "pyproject.toml").exists():
        logger.error("  pyproject.toml not found in project root")
        ok = False
    else:
        logger.info("  [OK] pyproject.toml found")

    # Check models
    cache_dir = project_root / "embeddings" / "cache"
    models = ["models--BAAI--bge-m3", "models--BAAI--bge-reranker-v2-m3"]
    for model_dir in models:
        model_path = cache_dir / model_dir
        if model_path.exists():
            logger.info("  [OK] Model found: %s", model_dir)
        else:
            logger.warning("  [MISSING] Model not found: %s (run scripts/package_models.py)", model_dir)
            ok = False

    return ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Configure ate-rag-kb MCP server for AI CLI tools."
    )
    parser.add_argument(
        "--harness",
        type=str,
        default=None,
        help="Comma-separated list of harnesses to configure (default: all detected)",
    )
    parser.add_argument(
        "--project-only",
        action="store_true",
        help="Only write project-level configs and policies, skip global configs",
    )
    policy_group = parser.add_mutually_exclusive_group()
    policy_group.add_argument(
        "--install-agent-policy",
        action="store_true",
        help="Install managed agent policy blocks that route ATE questions to MCP first (default)",
    )
    policy_group.add_argument(
        "--skip-agent-policy",
        action="store_true",
        help="Configure MCP only; do not write AGENTS.md / CLAUDE.md policy blocks",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without writing",
    )
    parser.add_argument(
        "--skip-checks",
        action="store_true",
        help="Skip prerequisite checks",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    project_root = resolve_project_root()
    logger.info("Project root: %s", project_root)
    logger.info("Platform:     %s", get_platform())
    logger.info("")

    if not args.skip_checks:
        logger.info("Checking prerequisites...")
        check_prerequisites(project_root)
        logger.info("")

    # Determine which harnesses to configure
    if args.harness:
        harnesses = {h.strip(): HARNESS_CONFIGS.get(h.strip()) for h in args.harness.split(",")}
        invalid = [h for h, cfg in harnesses.items() if cfg is None]
        if invalid:
            logger.error("Unknown harnesses: %s", ", ".join(invalid))
            logger.error("Supported: %s", ", ".join(HARNESS_CONFIGS.keys()))
            return 1
    else:
        harnesses = dict(HARNESS_CONFIGS.items())

    harness_ids = list(harnesses.keys())
    logger.info("Configuring MCP server for: %s", ", ".join(harness_ids))
    logger.info("")

    any_configured = False
    for harness_id, harness_info in harnesses.items():
        if harness_info is None:
            continue
        logger.info("%s:", harness_info["name"])
        if configure_harness(
            harness_id, harness_info, project_root, args.project_only, args.dry_run
        ):
            any_configured = True
        logger.info("")

    if not args.skip_agent_policy:
        logger.info("Installing managed agent routing policy...")
        if install_agent_policies(harness_ids, project_root, args.project_only, args.dry_run):
            any_configured = True
    else:
        logger.info("Skipping managed agent routing policy (--skip-agent-policy).")

    if args.dry_run:
        logger.info("Dry-run complete. No files were modified.")
        logger.info("Run without --dry-run to apply changes.")
    elif any_configured:
        logger.info("Configuration complete. Restart your AI CLI tool to pick up changes.")
    else:
        logger.info("All configs already up-to-date.")

    logger.info("")
    logger.info("Test the MCP server manually:")
    logger.info("  uv run python scripts/start_mcp.py")
    logger.info("")
    logger.info("Validate plugin installation:")
    logger.info("  uv run python scripts/validate_plugin_install.py")
    logger.info("  uv run python scripts/validate_agent_routing_policy.py")

    return 0


if __name__ == "__main__":
    sys.exit(main())
