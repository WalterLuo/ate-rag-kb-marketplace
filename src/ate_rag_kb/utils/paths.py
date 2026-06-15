"""Path resolution utilities."""

from __future__ import annotations

from pathlib import Path


def resolve_path(path: str | Path, base: Path | None = None) -> Path:
    """Resolve a path relative to a base directory."""
    p = Path(path)
    if p.is_absolute():
        return p.resolve()
    if base is None:
        base = Path.cwd()
    return (base / p).resolve()
