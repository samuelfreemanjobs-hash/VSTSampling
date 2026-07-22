"""Configuration loader with dotted-key access and defaults."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class Config:
    def __init__(self, data: dict[str, Any], path: Path | None = None) -> None:
        self._data = data
        self._path = path

    @classmethod
    def load(cls, path: Path) -> "Config":
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            data = {}
        return cls(data, path)

    def get(self, key: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, key: str, value: Any) -> None:
        parts = key.split(".")
        node = self._data
        for part in parts[:-1]:
            if part not in node or not isinstance(node[part], dict):
                node[part] = {}
            node = node[part]
        node[parts[-1]] = value

    def replace(self, data: dict[str, Any]) -> None:
        self._data = data

    def save(self) -> None:
        if self._path is None:
            raise RuntimeError("Config has no backing file")
        self._path.write_text(json.dumps(self._data, indent=4), encoding="utf-8")

    def as_dict(self) -> dict[str, Any]:
        return self._data
