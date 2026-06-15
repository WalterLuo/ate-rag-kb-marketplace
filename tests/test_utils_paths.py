"""Unit tests for path utilities."""

from __future__ import annotations

from pathlib import Path

from ate_rag_kb.utils.paths import resolve_path


class TestResolvePath:
    def test_absolute_path(self) -> None:
        p = resolve_path("/tmp/test.md")

        assert p.is_absolute()

    def test_relative_path_with_base(self) -> None:
        base = Path("/home/user")
        p = resolve_path("docs/test.md", base=base)

        assert p == Path("/home/user/docs/test.md").resolve()

    def test_relative_path_without_base_uses_cwd(self) -> None:
        p = resolve_path("test.md")

        assert p.is_absolute()
        assert p.parent == Path.cwd()
