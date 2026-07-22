"""Tests for reaper.plugin_scanner cache parsing."""
from __future__ import annotations

from pathlib import Path

from reaper.plugin_scanner import parse_cache_text, scan_reaper_plugins

VST_CACHE = """[vstcache]
Serum_x64.dll=00A1B2C3D4E5F607,1234567890,Serum (Xfer Records)!!!VSTi
ValhallaRoom_x64.dll=00FF11AA22BB33CC,987654321,ValhallaRoom (Valhalla DSP)
Omnisphere.dll=0011223344556677,111222333,Omnisphere (Spectrasonics)!!!VSTi
Broken_line_no_commas=xyz
"""

VST3_CACHE = """[vstcache]
Pigments.vst3=AABBCCDD,44556677,Pigments (Arturia)!!!VSTi
Serum.vst3=EEFF0011,8899,Serum (Xfer Records)!!!VSTi
"""


def test_parse_filters_instruments_only() -> None:
    plugins = parse_cache_text(VST_CACHE, "VSTi", "reaper-vstplugins64.ini")
    names = [p.name for p in plugins]
    assert names == ["Serum (Xfer Records)", "Omnisphere (Spectrasonics)"]
    assert plugins[0].display_name == "VSTi: Serum (Xfer Records)"


def test_scan_merges_and_dedupes(tmp_path: Path) -> None:
    (tmp_path / "reaper-vstplugins64.ini").write_text(VST_CACHE)
    (tmp_path / "reaper-vst3plugins64.ini").write_text(VST3_CACHE)
    plugins = scan_reaper_plugins(tmp_path)
    display = [p.display_name for p in plugins]
    # sorted by name; Serum appears as both VST2 and VST3 (different display names)
    assert display == [
        "VSTi: Omnisphere (Spectrasonics)",
        "VST3i: Pigments (Arturia)",
        "VSTi: Serum (Xfer Records)",
        "VST3i: Serum (Xfer Records)",
    ]


def test_scan_missing_dir_returns_empty(tmp_path: Path) -> None:
    assert scan_reaper_plugins(tmp_path / "nope") == []
