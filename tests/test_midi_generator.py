"""Tests for reaper.midi_generator — plan geometry and SMF byte format."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from reaper.midi_generator import (
    PPQ,
    build_note_plan,
    note_name,
    write_midi_file,
    _vlq,
)


def test_note_names() -> None:
    assert note_name(60) == "C4"
    assert note_name(24) == "C1"
    assert note_name(61) == "C#4"
    assert note_name(127) == "G9"


def test_plan_geometry() -> None:
    plan = build_note_plan(
        lowest_note=24,
        highest_note=36,
        interval_semitones=3,
        velocities=[40, 100],
        note_length_seconds=2.0,
        release_tail_seconds=1.0,
        gap_seconds=0.5,
    )
    # notes 24,27,30,33,36 -> 5 notes x 2 velocities
    assert len(plan.events) == 10
    first, second = plan.events[0], plan.events[1]
    assert first.midi_note == 24 and first.velocity == 40
    assert second.midi_note == 24 and second.velocity == 100
    assert first.start_seconds == 0.0
    assert first.slot_length_seconds == 3.0
    assert second.start_seconds == 3.5  # slot + gap
    assert plan.total_seconds == pytest.approx(10 * 3.5)


def test_plan_round_robins_and_names() -> None:
    plan = build_note_plan(
        lowest_note=60, highest_note=60, velocities=[100], round_robins=3
    )
    assert [e.sample_name for e in plan.events] == [
        "C4_v100",
        "C4_v100_rr2",
        "C4_v100_rr3",
    ]


def test_plan_validation() -> None:
    with pytest.raises(ValueError):
        build_note_plan(lowest_note=50, highest_note=40)
    with pytest.raises(ValueError):
        build_note_plan(velocities=[0])
    with pytest.raises(ValueError):
        build_note_plan(interval_semitones=0)


def test_vlq_encoding() -> None:
    assert _vlq(0) == b"\x00"
    assert _vlq(127) == b"\x7f"
    assert _vlq(128) == b"\x81\x00"
    assert _vlq(0x0FFFFFFF) == b"\xff\xff\xff\x7f"


def test_smf_bytes_roundtrip(tmp_path: Path) -> None:
    plan = build_note_plan(
        lowest_note=60, highest_note=63, interval_semitones=3, velocities=[80, 127]
    )
    midi = write_midi_file(plan, tmp_path / "plan.mid")
    data = midi.read_bytes()

    # Header chunk: type 0, 1 track, our PPQ
    assert data[:4] == b"MThd"
    assert int.from_bytes(data[8:10], "big") == 0
    assert int.from_bytes(data[10:12], "big") == 1
    assert int.from_bytes(data[12:14], "big") == PPQ
    assert data[14:18] == b"MTrk"

    # Count note-on events (0x90, velocity > 0) in the track body
    body = data[22:]
    note_ons = 0
    i = 0
    while i < len(body) - 2:
        if body[i] == 0x90 and body[i + 2] > 0:
            note_ons += 1
            i += 3
        else:
            i += 1
    assert note_ons == len(plan.events) == 4  # 2 notes x 2 velocities


def test_item_chunk_format() -> None:
    from reaper.midi_generator import build_item_chunk

    plan = build_note_plan(
        lowest_note=60, highest_note=63, interval_semitones=3, velocities=[100],
        note_length_seconds=1.0, release_tail_seconds=0.5, gap_seconds=0.5,
    )
    chunk = build_item_chunk(plan)
    lines = chunk.splitlines()
    assert lines[0] == "<ITEM"
    assert any(l.startswith("LENGTH ") for l in lines)
    assert "<SOURCE MIDI" in lines
    assert "HASDATA 1 960 QN" in lines
    assert any(l.startswith("IGNTEMPO 1 120") for l in lines)

    e_lines = [l for l in lines if l.startswith("E ")]
    # 2 notes -> on+off each, plus the all-notes-off terminator
    assert len(e_lines) == 5
    # First note-on: delta 0, 0x90, C4 (0x3c), vel 100 (0x64)
    assert e_lines[0] == "E 0 90 3c 64"
    # Note-off after 1.0s at 120bpm/960ppq = 1920 ticks
    assert e_lines[1] == "E 1920 80 3c 00"
    # Second on after the 0.5 tail + 0.5 gap = 1.0s = 1920 ticks later
    assert e_lines[2] == "E 1920 90 3f 64"
    assert e_lines[-1] == "E 0 b0 7b 00"


def test_slice_map_saved(tmp_path: Path) -> None:
    plan = build_note_plan(lowest_note=60, highest_note=60, velocities=[100])
    out = tmp_path / "render.slices.json"
    plan.save_slice_map(out)
    payload = json.loads(out.read_text())
    assert payload["events"][0]["sample_name"] == "C4_v100"
    assert payload["total_seconds"] == plan.total_seconds
