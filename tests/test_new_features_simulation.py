"""Simulation tests for preset enumeration, drum mode, and auto-length.

Same harness as test_full_simulation: the REAL ReaperController and
PipelineRunner drive a fake reaper.exe that runs the REAL Lua scripts.
"""
from __future__ import annotations

import stat
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from core.pipeline import PipelineRunner
from core.queue_manager import Job, JobStatus, QueueManager
from core.database import Database
from reaper.reaper_controller import ReaperController

from tests.test_full_simulation import FAKE_REAPER, make_config

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="simulation uses a shell wrapper"
)


@pytest.fixture()
def fake_reaper_exe(tmp_path: Path) -> Path:
    exe = tmp_path / "reaper"
    exe.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_REAPER}" "$@"\n', encoding="utf-8"
    )
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return exe


def run_pipeline(config, jobs, tmp_path):
    queue = QueueManager(save_path=tmp_path / "queue.json")
    db = Database()
    for job in jobs:
        queue.add(job)
    runner = PipelineRunner(queue, config, db=db)
    runner.start()
    runner.join(timeout=300)
    assert not runner.is_running
    return queue, db


# -- preset enumeration -----------------------------------------------


def test_enumerate_presets_returns_names(tmp_path: Path, fake_reaper_exe: Path) -> None:
    ctrl = ReaperController(reaper_path=str(fake_reaper_exe), work_dir=tmp_path / "scan")
    names = ctrl.enumerate_presets("VSTi: Diva (u-he)")
    assert names == ["Init", "Warm Pad", "Solo Lead", "Deep Bass"]


def test_enumerate_presets_empty_for_unlisted_plugin(
    tmp_path: Path, fake_reaper_exe: Path
) -> None:
    ctrl = ReaperController(reaper_path=str(fake_reaper_exe), work_dir=tmp_path / "scan")
    # Blofeld is a known plugin with no PRESETS entry in the fake registry
    assert ctrl.enumerate_presets("VSTi: Blofeld (Waldorf) (34 out)") == []


def test_preset_index_selection_renders(tmp_path: Path, fake_reaper_exe: Path) -> None:
    config = make_config(tmp_path, fake_reaper_exe)
    # Queue Diva preset index 1 ("Warm Pad") explicitly by index
    job = Job(
        plugin="VSTi: Diva (u-he)",
        preset="Warm Pad",
        settings_override={"preset_index": 1},
    )
    queue, _db = run_pipeline(config, [job], tmp_path)
    result = queue.get(job.id)
    assert result.status == JobStatus.COMPLETED, result.error
    assert (tmp_path / "out" / "Diva (u-he)" / "Default" / "Warm Pad").is_dir()


# -- drum mode --------------------------------------------------------


def test_drum_mode_one_shot_and_sparse(tmp_path: Path, fake_reaper_exe: Path) -> None:
    config = make_config(tmp_path, fake_reaper_exe)
    # Kit only maps notes 36,38,42,45,49 — the rest render silent and drop.
    job = Job(
        plugin="VSTi: Kit (Test)",
        preset="",
        settings_override={
            "mode": "drum",
            "lowest_note": 35,
            "highest_note": 50,
            "interval_semitones": 1,
            "velocities": [127],
            "note_length_seconds": 0.5,
            "release_tail_seconds": 1.0,
        },
    )
    queue, _db = run_pipeline(config, [job], tmp_path)
    result = queue.get(job.id)
    assert result.status == JobStatus.COMPLETED, result.error

    preset_dir = tmp_path / "out" / "Kit (Test)" / "Default" / "Default"
    samples = sorted((preset_dir / "Samples").glob("*.wav"))
    # Only the 5 mapped pads survive
    assert len(samples) == 5, [p.name for p in samples]

    # XPM: one-shot, ignore-base-note, 1-note-wide zones, NO loops
    xpm = next((preset_dir / "Samples").glob("*.xpm"))
    program = ET.parse(str(xpm)).getroot().find("Program")
    instruments = program.find("Instruments").findall("Instrument")
    assert len(instruments) == 5
    for inst in instruments:
        assert inst.findtext("OneShot") == "True"
        assert inst.findtext("IgnoreBaseNote") == "True"
        assert inst.findtext("LowNote") == inst.findtext("HighNote")
        layer = inst.find("Layers").find("Layer")
        assert layer.findtext("SliceLoop") == "0"  # loops off in drum mode


def test_drum_sfz_has_one_shot(tmp_path: Path, fake_reaper_exe: Path) -> None:
    config = make_config(tmp_path, fake_reaper_exe, exporters={"sfz": True})
    job = Job(
        plugin="VSTi: Kit (Test)",
        preset="",
        settings_override={
            "mode": "drum", "lowest_note": 36, "highest_note": 49,
            "interval_semitones": 1, "velocities": [127],
        },
    )
    queue, _db = run_pipeline(config, [job], tmp_path)
    assert queue.get(job.id).status == JobStatus.COMPLETED
    preset_dir = tmp_path / "out" / "Kit (Test)" / "Default" / "Default"
    sfz = next(preset_dir.glob("*.sfz")).read_text()
    assert "loop_mode=one_shot" in sfz


# -- auto-length probe ------------------------------------------------


def test_auto_length_percussive_source(tmp_path: Path, fake_reaper_exe: Path) -> None:
    # Pluck decays in ~0.4s; probe should classify percussive and shorten hold
    config = make_config(tmp_path, fake_reaper_exe)
    job = Job(
        plugin="VSTi: Pluck (Test)",
        preset="",
        settings_override={
            "auto_length": True,
            "probe_hold_seconds": 6.0,
            "probe_tail_seconds": 4.0,
            "lowest_note": 60,
            "highest_note": 60,
            "interval_semitones": 12,
            "velocities": [127],
        },
    )
    queue, _db = run_pipeline(config, [job], tmp_path)
    result = queue.get(job.id)
    assert result.status == JobStatus.COMPLETED, result.error

    preset_dir = tmp_path / "out" / "Pluck (Test)" / "Default" / "Default"
    # The single rendered sample should be short — trimmed near the decay,
    # far under the 6s probe hold.
    import soundfile as sf

    sample = next((preset_dir / "Samples").glob("*.wav"))
    data, sr = sf.read(str(sample))
    assert len(data) / sr < 2.0, "percussive sample should be short after auto-length"


def test_resume_skips_completed_preset(tmp_path: Path, fake_reaper_exe: Path) -> None:
    config = make_config(tmp_path, fake_reaper_exe)
    job = Job(plugin="VSTi: ReaSynth (Cockos)", bank="B", preset="")
    queue, _db = run_pipeline(config, [job], tmp_path)
    preset_dir = tmp_path / "out" / "ReaSynth (Cockos)" / "B" / "Default"
    assert (preset_dir / ".complete.json").exists()
    render_wav = preset_dir / "render.wav"
    first_mtime = render_wav.stat().st_mtime

    # Re-queue the same preset; resume must skip re-rendering it
    job2 = Job(plugin="VSTi: ReaSynth (Cockos)", bank="B", preset="")
    queue2, _db2 = run_pipeline(config, [job2], tmp_path)
    result = queue2.get(job2.id)
    assert result.status == JobStatus.COMPLETED
    assert "resumed" in result.message.lower()
    # render.wav untouched -> no new render happened
    assert render_wav.stat().st_mtime == first_mtime


def test_pitch_verification_flags_wrong_octave_is_ok(
    tmp_path: Path, fake_reaper_exe: Path
) -> None:
    # ReaSynth in the fake renders at the correct pitch; all samples pass.
    config = make_config(tmp_path, fake_reaper_exe)
    job = Job(plugin="VSTi: ReaSynth (Cockos)", preset="")
    queue, db = run_pipeline(config, [job], tmp_path)
    assert queue.get(job.id).status == JobStatus.COMPLETED
    samples = db.samples_for_run(1)
    assert all(s["qc_passed"] for s in samples)


def test_auto_length_sustained_source(tmp_path: Path, fake_reaper_exe: Path) -> None:
    # ReaSynth sustains for the full hold; probe keeps a long note.
    config = make_config(tmp_path, fake_reaper_exe)
    job = Job(
        plugin="VSTi: ReaSynth (Cockos)",
        preset="",
        settings_override={
            "auto_length": True,
            "probe_hold_seconds": 3.0,
            "probe_tail_seconds": 1.0,
            "lowest_note": 60,
            "highest_note": 60,
            "interval_semitones": 12,
            "velocities": [127],
        },
    )
    queue, _db = run_pipeline(config, [job], tmp_path)
    result = queue.get(job.id)
    assert result.status == JobStatus.COMPLETED, result.error

    preset_dir = tmp_path / "out" / "ReaSynth (Cockos)" / "Default" / "Default"
    import soundfile as sf

    sample = next((preset_dir / "Samples").glob("*.wav"))
    data, sr = sf.read(str(sample))
    assert len(data) / sr > 2.0, "sustained sample should keep a long hold"
