"""Smoke tests for core.config."""
from __future__ import annotations

from pathlib import Path

from core.config import Config


def test_dotted_get_and_default(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"ui": {"theme": "dark"}, "n": 3}', encoding="utf-8")
    cfg = Config.load(path)
    assert cfg.get("ui.theme") == "dark"
    assert cfg.get("ui.missing", "fallback") == "fallback"
    assert cfg.get("n") == 3


def test_set_and_save_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{}", encoding="utf-8")
    cfg = Config.load(path)
    cfg.set("audio.sample_rate", 48000)
    cfg.save()
    reloaded = Config.load(path)
    assert reloaded.get("audio.sample_rate") == 48000
