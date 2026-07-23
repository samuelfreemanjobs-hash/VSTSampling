"""Tests for output folder naming."""
from __future__ import annotations

from core.pipeline import _instrument_type, _plugin_folder, _safe_name, program_name


def test_plugin_folder_strips_prefix_and_channel_suffix() -> None:
    assert _plugin_folder("VSTi: ReaSynth (Cockos)") == "ReaSynth (Cockos)"
    assert _plugin_folder("VST3i: Pigments (Arturia)") == "Pigments (Arturia)"
    assert _plugin_folder("VSTi: Blofeld (Waldorf) (34 out)") == "Blofeld (Waldorf)"
    assert _plugin_folder("Diva") == "Diva"


def test_safe_name_cleans_but_keeps_readability() -> None:
    assert _safe_name("Warm Pad") == "Warm Pad"
    assert _safe_name("A/B: Test?") == "A_B Test"
    assert _safe_name("  ") == "Untitled"


def test_instrument_type_strips_prefix_and_vendor() -> None:
    assert _instrument_type("VSTi: JD-800 (Roland Cloud)") == "JD-800"
    assert _instrument_type("VSTi: Blofeld (Waldorf) (34 out)") == "Blofeld"
    assert _instrument_type("VST3i: Pigments (Arturia)") == "Pigments"


def test_program_name_default_format() -> None:
    name = program_name("VSTi_{instrument}_{preset}", "VSTi: JD-800 (Roland Cloud)",
                         "Brass Section", "Factory")
    assert name == "VSTi_JD-800_Brass Section"


def test_program_name_no_preset() -> None:
    name = program_name("VSTi_{instrument}_{preset}", "VSTi: JUNO-106 (Roland Cloud)",
                        "", "")
    assert name == "VSTi_JUNO-106_Default"


def test_program_name_bad_template_falls_back() -> None:
    name = program_name("{nonsense}", "VSTi: Diva (u-he)", "Init", "")
    assert name == "VSTi_Diva_Init"
