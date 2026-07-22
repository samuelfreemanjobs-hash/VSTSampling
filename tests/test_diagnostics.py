"""Tests for core.diagnostics."""
from __future__ import annotations

from core.config import Config
from core.diagnostics import build_report


def test_report_contains_key_sections() -> None:
    config = Config({"output_dir": "output", "reaper_path": ""})
    report = build_report(config, "1.1.0")
    assert "diagnostics" in report
    assert "app version: 1.1.0" in report
    assert "--- setup checks ---" in report
    assert "--- settings ---" in report
    assert '"output_dir": "output"' in report
    assert "--- last" in report
