"""Configuration management."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-(.*?))?\}")


def _expand_env_vars(value: str) -> str:
    """Expand ${VAR} and ${VAR:-default} placeholders in config strings."""

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        default = match.group(2)
        if name in os.environ:
            return os.environ[name]
        if default is not None:
            return default
        return match.group(0)

    return _ENV_PATTERN.sub(replace, value)


class Config:
    """Simple attribute-access config backed by a nested dict."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def get(self, key: str, default: Any = None) -> Any:
        """Dot-notation access, e.g. config.get('embedding.model_name')."""
        parts = key.split(".")
        val = self._data
        for part in parts:
            if isinstance(val, dict) and part in val:
                val = val[part]
            else:
                return default
        if isinstance(val, str):
            return _expand_env_vars(val)
        return val

    def __getitem__(self, key: str) -> Any:
        val = self.get(key)
        if val is None and key not in str(self._data):
            raise KeyError(key)
        return val

    def section(self, name: str) -> Config:
        """Return a subsection as a new Config."""
        return Config(self._data.get(name, {}))

    def to_dict(self) -> dict[str, Any]:
        return self._data.copy()


_config_instance: Config | None = None


def _resolve_config_path(path: Path | str | None = None) -> Path:
    """Resolve config path from argument, CONFIG_PATH env var, or default."""
    if path is not None:
        return Path(path)

    env_path = os.environ.get("CONFIG_PATH")
    if env_path:
        resolved = Path(env_path)
        if not resolved.exists():
            raise FileNotFoundError(
                f"CONFIG_PATH is set to '{env_path}' but the file does not exist. "
                "Please verify the path or unset CONFIG_PATH to use the default."
            )
        return resolved

    default = Path(__file__).resolve().parents[3] / "configs" / "config.yaml"
    if not default.exists():
        raise FileNotFoundError(
            f"Default config not found at {default}. "
            "Please run from the project root or set CONFIG_PATH."
        )
    return default


def get_config(path: Path | str | None = None) -> Config:
    """Load or return cached config."""
    global _config_instance
    if _config_instance is not None:
        return _config_instance
    resolved = _resolve_config_path(path)
    data = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    _config_instance = Config(data)
    return _config_instance


def reload_config(path: Path | str | None = None) -> Config:
    """Force reload config from disk."""
    global _config_instance
    _config_instance = None
    return get_config(path)
