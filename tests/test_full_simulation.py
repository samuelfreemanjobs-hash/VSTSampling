"""Full-pipeline simulation: the REAL ReaperController launches a fake
reaper executable that runs the REAL render_job.lua under a mocked
Reaper API and synthesizes actual audio. No production code is bypassed.
"""
from __future__ import annotations

import json
import shutil
import stat
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from core.config import Config
from core.database import Database
from core.pipeline import PipelineRunner
from core.queue_manager import Job, JobStatus, QueueManager

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="simulation uses a shell wrapper"
)

FAKE_REAPER = Path(__file__).parent / "sim" / "fake_reaper.py"


@pytest.fixture()
def fake_reaper_exe(tmp_path: Path) -> Path:
    exe = tmp_path / "reaper"
    exe.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_REAPER}" "$@"\n', encoding="utf-8"
    )
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return exe


def make_config(tmp_path: Path, exe: Path, **overrides) -> Config:
    data = {
        "output_dir": str(tmp_path / "out"),
        "reaper_path": str(exe),
        "midi": {
            "lowest_note": 48,
            "highest_note": 72,
            "note_interval_semitones": 12,
            "note_length_seconds": 1.0,
            "release_tail_seconds": 0.3,
        },
        "velocities": [60, 100, 127],
        "audio": {
            "sample_rate": 44100,
            "bit_depth": 24,
            "channels": 2,
            "trim_silence": True,
            "normalize": False,
            "loop_detection": True,
        },
        "exporters": {"mpc_xpm": True, "sfz": True, "decentsampler": True},
    }
    data.update(overrides)
    return Config(data)


def run_pipeline(config: Config, jobs: list[Job], tmp_path: Path):
    queue = QueueManager(save_path=tmp_path / "queue.json")
    db = Database()
    for job in jobs:
        queue.add(job)
    runner = PipelineRunner(queue, config, db=db)
    runner.start()
    runner.join(timeout=300)
    assert not runner.is_running, "pipeline did not finish"
    return queue, db


def test_complete_instrument_end_to_end(tmp_path: Path, fake_reaper_exe: Path) -> None:
    config = make_config(tmp_path, fake_reaper_exe)
    job = Job(plugin="VSTi: ReaSynth (Cockos)", bank="Factory", preset="")
    queue, db = run_pipeline(config, [job], tmp_path)

    result = queue.get(job.id)
    assert result.status == JobStatus.COMPLETED, f"job failed: {result.error}"

    preset_dir = tmp_path / "out" / "ReaSynth (Cockos)" / "Factory" / "Default"
    assert preset_dir.is_dir(), f"missing {preset_dir}"

    # Handshake artifacts
    assert (preset_dir / "render_started.txt").exists()
    assert (preset_dir / "render_result.txt").read_text().startswith("OK:")

    # 3 notes (48, 60, 72) x 3 velocities
    samples = sorted((preset_dir / "Samples").glob("*.wav"))
    assert len(samples) == 9, [p.name for p in samples]
    names = {p.stem for p in samples}
    assert {"C3_v60", "C4_v100", "C5_v127"} <= names

    # Metadata agrees
    meta = json.loads((preset_dir / "instrument.json").read_text())
    assert meta["sample_count"] == 9
    velocities = {s["velocity"] for s in meta["samples"]}
    assert velocities == {60, 100, 127}

    # XPM: 3 keygroups x 3 layers, valid XML
    xpm = next(preset_dir.glob("*.xpm"))
    program = ET.parse(str(xpm)).getroot().find("Program")
    assert program.findtext("KeygroupNumKeygroups") == "3"
    instruments = program.find("Instruments").findall("Instrument")
    assert all(len(i.find("Layers").findall("Layer")) == 3 for i in instruments)

    # SFZ + DecentSampler exist and reference real files
    sfz = next(preset_dir.glob("*.sfz")).read_text()
    for line in sfz.splitlines():
        if line.startswith("sample="):
            assert (preset_dir / line.split("=", 1)[1]).exists()
    assert next(preset_dir.glob("*.dspreset")).exists()

    # Database + batch report
    summary = db.run_summary(1)
    assert summary["status"] == "completed"
    assert summary["sample_count"] == 9
    report = (tmp_path / "out" / "Logs" / "render_report.md").read_text()
    assert "- Completed: 1" in report


def test_unknown_plugin_fails_with_actionable_error(
    tmp_path: Path, fake_reaper_exe: Path
) -> None:
    config = make_config(tmp_path, fake_reaper_exe)
    job = Job(plugin="VSTi: Omnisphere (Spectrasonics)")  # not in fake registry
    queue, db = run_pipeline(config, [job], tmp_path)

    result = queue.get(job.id)
    assert result.status == JobStatus.FAILED
    assert "plugin not found" in result.error
    assert db.run_summary(1)["status"] == "failed"


def test_bad_preset_fails_with_fxchain_hint(
    tmp_path: Path, fake_reaper_exe: Path
) -> None:
    config = make_config(tmp_path, fake_reaper_exe)
    job = Job(plugin="VSTi: Diva (u-he)", preset="BadPreset XYZ")
    queue, _db = run_pipeline(config, [job], tmp_path)

    result = queue.get(job.id)
    assert result.status == JobStatus.FAILED
    assert "preset not found" in result.error
    assert "FX chain" in result.error


def test_channel_suffix_plugin_matches(tmp_path: Path, fake_reaper_exe: Path) -> None:
    config = make_config(tmp_path, fake_reaper_exe)
    job = Job(plugin="VSTi: Blofeld (Waldorf) (34 out)")
    queue, _db = run_pipeline(config, [job], tmp_path)
    result = queue.get(job.id)
    assert result.status == JobStatus.COMPLETED, result.error


def test_stale_instance_forwarding_detected(tmp_path: Path, fake_reaper_exe: Path) -> None:
    """If -newinst were ever dropped, the fake mimics single-instance
    forwarding (instant exit, no script run) and the controller must
    produce the 'never ran the render script' error."""
    from reaper.midi_generator import build_note_plan
    from reaper.reaper_controller import ReaperController, ReaperError, RenderJob

    # Wrapper that strips -newinst before delegating, simulating old behavior
    exe = tmp_path / "reaper_forwarding"
    exe.write_text(
        "#!/bin/sh\n"
        "args=''\n"
        'for a in "$@"; do [ "$a" = "-newinst" ] || args="$args \'$a\'"; done\n'
        f'eval exec "{sys.executable}" "{FAKE_REAPER}" $args\n',
        encoding="utf-8",
    )
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)

    work = tmp_path / "work"
    plan = build_note_plan(lowest_note=60, highest_note=60, velocities=[100])
    rj = RenderJob(
        plugin="VSTi: ReaSynth (Cockos)", preset="",
        midi_file=work / "timeline.mid", output_wav=work / "render.wav",
        total_seconds=plan.total_seconds,
    )
    ctrl = ReaperController(reaper_path=str(exe), work_dir=work)
    with pytest.raises(ReaperError, match="without ever running the render script"):
        ctrl.render(rj, plan, timeout_seconds=60)


def test_survives_missing_midi_item_api(
    tmp_path: Path, fake_reaper_exe: Path, monkeypatch
) -> None:
    """Reproduces the real-hardware failure: CreateNewMIDIItemInProject
    is nil. The script must complete via its fallback ladder."""
    monkeypatch.setenv("FAKE_REAPER_STARTUP_API_GAP", "1")
    config = make_config(tmp_path, fake_reaper_exe)
    job = Job(plugin="VSTi: ReaSynth (Cockos)", preset="")
    queue, _db = run_pipeline(config, [job], tmp_path)
    result = queue.get(job.id)
    assert result.status == JobStatus.COMPLETED, result.error


def test_api_fallback_branch_still_works(
    tmp_path: Path, fake_reaper_exe: Path, monkeypatch
) -> None:
    """With the chunk API missing, the per-note insertion branch runs."""
    monkeypatch.setenv("FAKE_REAPER_NO_CHUNK_API", "1")
    config = make_config(tmp_path, fake_reaper_exe)
    job = Job(plugin="VSTi: ReaSynth (Cockos)", preset="")
    queue, _db = run_pipeline(config, [job], tmp_path)
    result = queue.get(job.id)
    assert result.status == JobStatus.COMPLETED, result.error


def test_multi_job_batch_isolates_failures(tmp_path: Path, fake_reaper_exe: Path) -> None:
    config = make_config(tmp_path, fake_reaper_exe)
    good1 = Job(plugin="VSTi: ReaSynth (Cockos)", preset="")
    bad = Job(plugin="VSTi: NotInstalled (Nobody)")
    good2 = Job(plugin="VSTi: Diva (u-he)", preset="")
    queue, db = run_pipeline(config, [good1, bad, good2], tmp_path)

    assert queue.get(good1.id).status == JobStatus.COMPLETED
    assert queue.get(bad.id).status == JobStatus.FAILED
    assert queue.get(good2.id).status == JobStatus.COMPLETED
    report = (tmp_path / "out" / "Logs" / "render_report.md").read_text()
    assert "- Runs: 3" in report
    assert "- Completed: 2" in report
    assert "- Failed: 1" in report
