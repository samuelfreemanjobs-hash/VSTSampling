"""Discover installed VST instruments from Reaper's plugin cache.

Reaper keeps scanned-plugin caches in its resource directory
(%APPDATA%\\REAPER on Windows). Lines look like:

    Serum_x64.dll=00A1B2C3,1234567890,Serum (Xfer Records)!!!VSTi
    ValhallaRoom_x64.dll=00FF11AA,987654,ValhallaRoom (Valhalla DSP)

The ``!!!VSTi`` marker identifies instruments. Names from .vst3 caches
get the "VST3i:" browser prefix, others "VSTi:".
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_CACHE_FILES = [
    ("reaper-vstplugins64.ini", "VSTi"),
    ("reaper-vstplugins.ini", "VSTi"),
    ("reaper-vst3plugins64.ini", "VST3i"),
    ("reaper-vst3plugins.ini", "VST3i"),
]


@dataclass(frozen=True)
class PluginInfo:
    name: str        # e.g. "Serum (Xfer Records)"
    prefix: str      # "VSTi" or "VST3i"
    source_file: str

    @property
    def display_name(self) -> str:
        return f"{self.prefix}: {self.name}"


def default_resource_dirs() -> list[Path]:
    dirs: list[Path] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        dirs.append(Path(appdata) / "REAPER")
    home = Path.home()
    dirs.append(home / "Library" / "Application Support" / "REAPER")  # macOS
    dirs.append(home / ".config" / "REAPER")  # Linux
    return [d for d in dirs if d.is_dir()]


def parse_cache_text(text: str, prefix: str, source_file: str) -> list[PluginInfo]:
    plugins: list[PluginInfo] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("[") or "=" not in line:
            continue
        _, _, value = line.partition("=")
        parts = value.split(",", 2)
        if len(parts) < 3:
            continue
        name_field = parts[2].strip()
        if "!!!VSTi" not in name_field:
            continue
        name = name_field.replace("!!!VSTi", "").strip()
        # Shell-plugin sub-entries can carry an instance id after a '|'
        name = name.split("|")[0].strip()
        if name:
            plugins.append(PluginInfo(name=name, prefix=prefix, source_file=source_file))
    return plugins


def scan_reaper_plugins(resource_dir: Path | None = None) -> list[PluginInfo]:
    """Return installed instruments, deduplicated, sorted by name.

    Empty result means Reaper's cache wasn't found — either Reaper isn't
    installed or it has never scanned plugins on this machine.
    """
    dirs = [resource_dir] if resource_dir else default_resource_dirs()
    found: dict[str, PluginInfo] = {}
    for d in dirs:
        for filename, prefix in _CACHE_FILES:
            cache = d / filename
            if not cache.is_file():
                continue
            try:
                text = cache.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for p in parse_cache_text(text, prefix, filename):
                found.setdefault(p.display_name, p)
    return sorted(found.values(), key=lambda p: p.name.lower())
