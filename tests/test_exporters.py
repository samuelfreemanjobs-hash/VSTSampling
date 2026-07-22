"""Tests for the mapping model and format writers."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from exporters.decentsampler import export_decentsampler
from exporters.kontakt import export_kontakt
from exporters.mapping import build_instrument_map
from exporters.mpc import ExportError, export_mpc_xpm
from exporters.sfz import export_sfz


def make_samples(notes=(48, 60, 72), vels=(40, 100), rrs=1, with_loop=False):
    out = []
    for n in notes:
        for v in vels:
            for rr in range(rrs):
                out.append(
                    {
                        "file_path": f"Samples/n{n}_v{v}_rr{rr}.wav",
                        "midi_note": n,
                        "velocity": v,
                        "round_robin": rr,
                        "loop_start": 1000 if with_loop else None,
                        "loop_end": 40000 if with_loop else None,
                    }
                )
    return out


def test_mapping_ranges() -> None:
    imap = build_instrument_map("Test", make_samples())
    assert imap.root_notes == [48, 60, 72]
    assert imap.velocity_layers == [40, 127]

    by_root = {z.root_note: z for z in imap.zones if z.high_vel == 127}
    # First root extends to 0, last to 127, midpoint splits between
    assert by_root[48].low_note == 0
    assert by_root[48].high_note == 54
    assert by_root[60].low_note == 55
    assert by_root[60].high_note == 66
    assert by_root[72].high_note == 127

    lows = {z.low_vel for z in imap.zones}
    assert lows == {1, 41}


def test_mapping_rejects_empty() -> None:
    with pytest.raises(ValueError):
        build_instrument_map("Empty", [])


def test_sfz_output(tmp_path: Path) -> None:
    imap = build_instrument_map("MySynth", make_samples(with_loop=True, rrs=2))
    out = export_sfz(imap, tmp_path / "MySynth.sfz", samples_relative_to=tmp_path)
    body = out.read_text()
    assert body.count("<region>") == 3 * 2 * 2
    assert "pitch_keycenter=60" in body
    assert "loop_mode=loop_continuous" in body
    assert "seq_length=2 seq_position=2" in body


def test_decentsampler_output(tmp_path: Path) -> None:
    imap = build_instrument_map("Pad", make_samples(rrs=2))
    out = export_decentsampler(imap, tmp_path / "Pad.dspreset", samples_relative_to=tmp_path)
    tree = ET.parse(str(out))
    groups = tree.getroot().find("groups")
    assert groups is not None
    group_els = groups.findall("group")
    assert len(group_els) == 2  # one per round robin
    assert group_els[1].get("seqPosition") == "2"
    samples = group_els[0].findall("sample")
    assert len(samples) == 6
    assert samples[0].get("rootNote") is not None


def test_mpc_xpm_output(tmp_path: Path) -> None:
    imap = build_instrument_map("Keys", make_samples(vels=(40, 80, 100, 127)))
    out = export_mpc_xpm(imap, tmp_path / "Keys.xpm")
    tree = ET.parse(str(out))
    program = tree.getroot().find("Program")
    assert program is not None and program.get("type") == "Keygroup"
    assert program.findtext("KeygroupNumKeygroups") == "3"
    instruments = program.find("Instruments").findall("Instrument")
    assert len(instruments) == 3
    layers = instruments[0].find("Layers").findall("Layer")
    assert len(layers) == 4
    assert layers[0].findtext("VelStart") == "1"
    assert layers[-1].findtext("VelEnd") == "127"


def test_mpc_rejects_too_many_layers(tmp_path: Path) -> None:
    imap = build_instrument_map("TooMany", make_samples(vels=(20, 40, 60, 80, 100)))
    with pytest.raises(ExportError, match="velocity layers"):
        export_mpc_xpm(imap, tmp_path / "x.xpm")


def test_mpc_skips_round_robins(tmp_path: Path) -> None:
    imap = build_instrument_map("RR", make_samples(rrs=3))
    out = export_mpc_xpm(imap, tmp_path / "RR.xpm")
    tree = ET.parse(str(out))
    instruments = tree.getroot().find("Program").find("Instruments").findall("Instrument")
    for inst in instruments:
        assert len(inst.find("Layers").findall("Layer")) == 2  # 2 vels, rr0 only


def test_drum_mode_mapping_is_one_shot_and_pinned() -> None:
    imap = build_instrument_map(
        "Kit", make_samples(notes=(36, 38, 42), vels=(127,), with_loop=True),
        drum_mode=True,
    )
    assert imap.one_shot is True
    for zone in imap.zones:
        # 1-note-wide, no stretching across gaps
        assert zone.low_note == zone.root_note == zone.high_note
        # loops stripped even though source samples had loop points
        assert not zone.has_loop


def test_drum_mode_xpm_flags(tmp_path: Path) -> None:
    imap = build_instrument_map(
        "Kit", make_samples(notes=(36, 38), vels=(127,)), drum_mode=True
    )
    out = export_mpc_xpm(imap, tmp_path / "Kit.xpm")
    instruments = ET.parse(str(out)).getroot().find("Program").find("Instruments")
    for inst in instruments.findall("Instrument"):
        assert inst.findtext("OneShot") == "True"
        assert inst.findtext("IgnoreBaseNote") == "True"


def test_kontakt_routes_to_sfz(tmp_path: Path) -> None:
    imap = build_instrument_map("Kon", make_samples())
    out = export_kontakt(imap, tmp_path, samples_relative_to=tmp_path)
    assert out.suffix == ".sfz" and out.exists()
    assert (tmp_path / "KONTAKT_IMPORT.txt").exists()
