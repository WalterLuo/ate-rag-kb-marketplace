#!/usr/bin/env python3
"""Validate managed ATE KB routing policy helpers."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INSTALLER_PATH = PROJECT_ROOT / "scripts" / "install_mcp.py"


def load_installer():
    spec = importlib.util.spec_from_file_location("install_mcp", INSTALLER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load scripts/install_mcp.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    installer = load_installer()
    block = installer.build_agent_policy_block()

    appended = installer.upsert_managed_block("# Existing\n", block)
    if installer.POLICY_BLOCK_START not in appended:
        print("[FAIL] Managed block was not appended.")
        return 1

    replaced = installer.upsert_managed_block(appended.replace("ate_kb.ask", "old_ask"), block)
    if "old_ask" in replaced:
        print("[FAIL] Managed block was not replaced.")
        return 1
    if replaced.count(installer.POLICY_BLOCK_START) != 1:
        print("[FAIL] Managed block duplicated.")
        return 1

    print("[OK] Agent routing policy helpers are valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
