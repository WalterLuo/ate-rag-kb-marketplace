#!/usr/bin/env python3
"""Validate plugin, skill, and agent-routing installation assets."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def validate_json(path: Path, errors: list[str]) -> None:
    try:
        json.loads(read(path))
    except FileNotFoundError:
        errors.append(f"Missing JSON file: {path.relative_to(PROJECT_ROOT)}")
    except json.JSONDecodeError as exc:
        errors.append(f"Invalid JSON in {path.relative_to(PROJECT_ROOT)}: {exc}")


def frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}
    result: dict[str, str] = {}
    for raw_line in text[4:end].splitlines():
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        result[key.strip()] = value.strip().strip('"')
    return result


def main() -> int:
    errors: list[str] = []

    for relative in [
        ".codex-plugin/plugin.json",
        ".claude-plugin/plugin.json",
        ".cursor-plugin/plugin.json",
        ".agents/plugins/marketplace.json",
        ".mcp.json",
    ]:
        validate_json(PROJECT_ROOT / relative, errors)

    skill_path = PROJECT_ROOT / "skills" / "ate-kb-router" / "SKILL.md"
    require(skill_path.exists(), "Missing skills/ate-kb-router/SKILL.md", errors)
    if skill_path.exists():
        metadata = frontmatter(read(skill_path))
        description = metadata.get("description", "")
        require(metadata.get("name") == "ate-kb-router", "Skill name must be ate-kb-router", errors)
        require(bool(description), "Skill description is missing", errors)
        lower_description = description.lower()
        for keyword in ["smt7", "v93000", "ig-xl", "j750", "ate", "mcp", "ate_kb"]:
            require(
                keyword in lower_description,
                f"Skill description must include {keyword}",
                errors,
            )

    agents = read(PROJECT_ROOT / "AGENTS.md")
    claude = read(PROJECT_ROOT / "CLAUDE.md")
    gemini = read(PROJECT_ROOT / "GEMINI.md")
    installer = read(PROJECT_ROOT / "scripts" / "install_mcp.py")
    start_mcp_path = PROJECT_ROOT / "scripts" / "start_mcp.py"
    start_mcp = read(start_mcp_path) if start_mcp_path.exists() else ""
    plugin_mcp = json.loads(read(PROJECT_ROOT / ".mcp.json"))
    plugin_mcp_server = plugin_mcp.get("mcpServers", {}).get("ate-kb", {})
    claude_plugin = json.loads(read(PROJECT_ROOT / ".claude-plugin" / "plugin.json"))
    codex_plugin = json.loads(read(PROJECT_ROOT / ".codex-plugin" / "plugin.json"))
    cursor_plugin = json.loads(read(PROJECT_ROOT / ".cursor-plugin" / "plugin.json"))
    mcp_example = read(PROJECT_ROOT / ".mcp.example.json")

    require("Deferred MCP Bootstrap" in agents, "AGENTS.md missing Deferred MCP Bootstrap", errors)
    require("tool_search" in agents, "AGENTS.md missing tool_search bootstrap", errors)
    require("deferred MCP tool" in claude, "CLAUDE.md missing Codex deferred MCP rule", errors)
    require("mcp__ate-kb__ate_kb_ask" in claude, "CLAUDE.md missing Claude Code ask tool", errors)
    require("MCP tools first" in gemini or "Use MCP tools first" in gemini, "GEMINI.md missing MCP-first rule", errors)
    require("ate_kb.ask" in gemini, "GEMINI.md missing ate_kb.ask rule", errors)
    require("--install-agent-policy" in installer, "install_mcp.py missing --install-agent-policy", errors)
    require("--skip-agent-policy" in installer, "install_mcp.py missing --skip-agent-policy", errors)
    require(start_mcp_path.exists(), "Missing scripts/start_mcp.py", errors)
    require("ATE_RAG_KB_PROJECT_ROOT" in start_mcp, "start_mcp.py missing project root override", errors)
    require("ATE_KB_AUTO_BOOTSTRAP" in start_mcp, "start_mcp.py missing Qdrant bootstrap switch", errors)
    require("scripts/start_mcp.py" in installer, "install_mcp.py must configure start_mcp.py", errors)
    require(
        plugin_mcp_server.get("args")
        == [
            "run",
            "--project",
            "${CLAUDE_PLUGIN_ROOT}",
            "python",
            "${CLAUDE_PLUGIN_ROOT}/scripts/start_mcp.py",
        ],
        ".mcp.json must run scripts/start_mcp.py from ${CLAUDE_PLUGIN_ROOT}",
        errors,
    )
    plugin_env = plugin_mcp_server.get("env", {})
    require(
        "ATE_RAG_KB_PROJECT_ROOT" not in plugin_env,
        ".mcp.json must not pin ATE_RAG_KB_PROJECT_ROOT; start_mcp.py resolves it",
        errors,
    )
    require(
        "CONFIG_PATH" not in plugin_env,
        ".mcp.json must not pin CONFIG_PATH; start_mcp.py derives it from the project root",
        errors,
    )
    require(
        plugin_env.get("ATE_KB_AUTO_BOOTSTRAP") == "1",
        ".mcp.json must enable start_mcp.py Qdrant bootstrap",
        errors,
    )
    for name, manifest in [
        ("Claude Code", claude_plugin),
        ("Codex", codex_plugin),
        ("Cursor", cursor_plugin),
    ]:
        require(
            manifest.get("mcpServers") == "./.mcp.json",
            f"{name} plugin manifest must reference ./.mcp.json",
            errors,
        )
    require('"--project"' in mcp_example, ".mcp.example.json must use --project", errors)
    require("scripts/start_mcp.py" in mcp_example, ".mcp.example.json must run start_mcp.py", errors)
    require("CONFIG_PATH" in mcp_example, ".mcp.example.json must include CONFIG_PATH", errors)

    if errors:
        for error in errors:
            print(f"[FAIL] {error}")
        return 1

    print("[OK] Plugin install assets are valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
