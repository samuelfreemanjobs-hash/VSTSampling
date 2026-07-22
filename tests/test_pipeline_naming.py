"""Tests for output folder naming."""
from __future__ import annotations

from core.pipeline import _plugin_folder, _safe_name


def test_plugin_folder_strips_prefix_and_channel_suffix() -> None:
    assert _plugin_folder("VSTi: ReaSynth (Cockos)") == "ReaSynth (Cockos)"
    assert _plugin_folder("VST3i: Pigments (Arturia)") == "Pigments (Arturia)"
    assert _plugin_folder("VSTi: Blofeld (Waldorf) (34 out)") == "Blofeld (Waldorf)"
    assert _plugin_folder("Diva") == "Diva"


def test_safe_name_cleans_but_keeps_readability() -> None:
    assert _safe_name("Warm Pad") == "Warm Pad"
    assert _safe_name("A/B: Test?") == "A_B Test"
    assert _safe_name("  ") == "Untitled"
