"""Unit tests for CLI main."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from ate_rag_kb.cli.main import main


class TestMain:
    def test_keyboard_interrupt_exits_130(self) -> None:
        with patch("ate_rag_kb.cli.main.asyncio.run", side_effect=KeyboardInterrupt):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 130

    def test_normal_exit(self) -> None:
        with patch("ate_rag_kb.cli.main.asyncio.run", return_value=0):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0
