"""Validate IG-XL weak topic source hints against the live vector store.

Usage:
    uv run python scripts/validate_igxl_source_hints.py

This script instantiates McpToolHandler with the real RetrievalPipeline
and runs the 15Q weak-topic queries to verify that expected source_md
files appear in the results and no smt7/v93000 sources are mixed in.
"""

from __future__ import annotations

import asyncio
import sys

from ate_rag_kb.mcp.tools import McpToolHandler
from ate_rag_kb.retrieval.pipeline import RetrievalPipeline
from ate_rag_kb.utils.config import get_config

QUERIES: list[dict[str, list[str]]] = [
    {
        "query": "DSIO200 的 VSSS/VSSC 是什么？quad mode 是否支持？",
        "expected": [
            "igxl/patternlanguage/plinstruments.5.07.md",
            "igxl/dibdesign/dib_hsd200.16.5.md",
        ],
    },
    {
        "query": "IG-XL SECS/GEM spooling 在什么 CONTROLSTATE 下有意义？Off-Line 时会发送哪些消息？",
        "expected": ["igxl/secsgem/secs_scenario.11.51.md"],
    },
    {
        "query": "IG-XL Test Analysis Tool 如何启动？可以从 Start menu 和 DataTool 哪里进入？",
        "expected": ["igxl/testanalysis/taUsing.1.2.md"],
    },
    {
        "query": "Available J750 Features 文档说明 J750 features 按哪些 instrument 或 feature 分类？",
        "expected": ["igxl/igxladmin/adLicensing.2.6.md"],
    },
    {
        "query": "MTO800 中 Programming the MTO Resource Map 应该查看哪个文档？MTO Pattern Microcodes 应该查看哪个文档？",
        "expected": [
            "igxl/patternlanguage/plmto.7.03.md",
            "igxl/patterntool/PTVectorsEditing.4.21.md",
            "igxl/datatool/DTSheets.11.185.md",
        ],
    },
    {
        "query": "DataTool 中 MTO Resource Map Sheet 的 programming restrictions 和 configuration limitations 应该查看哪里？",
        "expected": [
            "igxl/patternlanguage/plmto.7.03.md",
            "igxl/patterntool/PTVectorsEditing.4.21.md",
            "igxl/datatool/DTSheets.11.185.md",
        ],
    },
]


async def main() -> int:
    config = get_config()
    pipeline = RetrievalPipeline(config)
    handler = McpToolHandler(pipeline)

    exit_code = 0
    for item in QUERIES:
        query = item["query"]
        expected = item["expected"]
        print(f"\n{'=' * 60}")
        print(f"Query: {query}")
        print(f"Expected sources: {expected}")

        result = await handler.handle_ask({"question": query, "top_k": 10})
        source_files = result.source_files

        found = [src for src in expected if src in source_files]
        missing = [src for src in expected if src not in source_files]
        contamination = [
            src for src in source_files if src.startswith(("smt7/", "v93000/"))
        ]

        print(f"Retrieved sources ({len(source_files)}): {source_files}")
        print(f"Found expected   : {found}")
        print(f"Missing expected : {missing}")
        if contamination:
            print(f"SMT7/V93000 contamination: {contamination}")

        if missing:
            print("RESULT: FAIL")
            exit_code = 1
        elif contamination:
            print("RESULT: FAIL (contamination)")
            exit_code = 1
        else:
            print("RESULT: PASS")

    return exit_code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
