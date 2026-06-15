"""Build an exclusive symbol ownership catalog for retrieval routing."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ate_rag_kb.domain.scopes import RetrievalScope, infer_scope_from_source

ScopeResolver = Callable[[str, str, dict[str, Any]], RetrievalScope | None]

_HEADING_RE = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
_SYMBOL_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_.]*\b")


@dataclass(frozen=True, slots=True)
class SymbolOwner:
    symbol: str
    scope: RetrievalScope
    source_mds: tuple[str, ...]


@dataclass(slots=True)
class SymbolCatalog:
    owners: dict[str, SymbolOwner]

    @classmethod
    def empty(cls) -> SymbolCatalog:
        return cls({})

    def owner_for(self, symbol: str) -> RetrievalScope | None:
        owner = self.owners.get(symbol.casefold())
        return owner.scope if owner else None

    def find_owner_in_query(self, query: str) -> SymbolOwner | None:
        matches = [
            self.owners[token.casefold()]
            for token in _SYMBOL_RE.findall(query)
            if token.casefold() in self.owners
        ]
        if not matches:
            return None
        if len({match.scope for match in matches}) != 1:
            return None
        return matches[0]

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "owners": {
                key: {
                    "symbol": owner.symbol,
                    **asdict(owner.scope),
                    "source_mds": list(owner.source_mds),
                }
                for key, owner in sorted(self.owners.items())
            },
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> SymbolCatalog:
        payload = json.loads(path.read_text(encoding="utf-8"))
        owners = {
            key: SymbolOwner(
                symbol=value["symbol"],
                scope=RetrievalScope(
                    vendor=value["vendor"],
                    platform=value["platform"],
                    software=value["software"],
                    software_release=value.get("software_release", ""),
                ),
                source_mds=tuple(value["source_mds"]),
            )
            for key, value in payload["owners"].items()
        }
        return cls(owners)

    @classmethod
    def load_if_exists(cls, path: Path) -> SymbolCatalog:
        return cls.load(path) if path.exists() else cls.empty()


class SymbolCatalogBuilder:
    def __init__(
        self,
        markdown_dir: Path,
        json_dir: Path | None = None,
        scope_resolver: ScopeResolver | None = None,
    ) -> None:
        self.markdown_dir = markdown_dir
        self.json_dir = json_dir
        self.scope_resolver = scope_resolver or (
            lambda source_md, _title, _metadata: infer_scope_from_source(source_md)
        )

    def build(self) -> SymbolCatalog:
        observed: dict[str, dict[RetrievalScope, set[str]]] = {}
        display_names: dict[str, str] = {}

        for md_path in sorted(self.markdown_dir.rglob("*.md")):
            source_md = md_path.relative_to(self.markdown_dir).as_posix()
            metadata = self._metadata(source_md)
            title = metadata.get("title") or metadata.get("doc_title", "")
            scope = self.scope_resolver(source_md, title, metadata)
            if scope is None:
                continue

            text = md_path.read_text(encoding="utf-8")
            candidates = [title, *_HEADING_RE.findall(text)]
            for symbol in _SYMBOL_RE.findall("\n".join(candidates)):
                key = symbol.casefold()
                display_names.setdefault(key, symbol)
                observed.setdefault(key, {}).setdefault(scope, set()).add(source_md)

        owners = {
            key: SymbolOwner(
                symbol=display_names[key],
                scope=next(iter(scopes)),
                source_mds=tuple(sorted(next(iter(scopes.values())))),
            )
            for key, scopes in observed.items()
            if len(scopes) == 1
        }
        return SymbolCatalog(owners)

    def _metadata(self, source_md: str) -> dict[str, Any]:
        if self.json_dir is None:
            return {}
        path = self.json_dir / Path(source_md).with_suffix(".json")
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))
