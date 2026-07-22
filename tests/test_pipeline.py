"""End-to-end pipeline test with a synthetic renderer standing in for Reaper."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import soundfile as sf

from core.config import Config
from core.database import Database
from core.pipeline import PipelineRunner
from core.queue_manager import Job, JobStatus, QueueManager
from reaper.midi_generator import NotePlan
from reaper.reaper_controller import RenderJob

SR = 44100


def fake_render(job: RenderJob, plan: NotePlan) -> Path:
    """Synthesize the timeline: a sine at each event's pitch/velocity."""
    total = int(np.ceil(plan.total_seconds * SR)) + SR
    timeline = np.zeros(total)
    for e in plan.events:
        freq = 440.0 * 2 ** ((e.midi_note - 69) / 12)
        amp = 0.6 * e.velocity / 127
        n = int(e.note_length_seconds * SR)
        start = int(e.start_seconds * SR)
        t = np.arange(n) / SR
        env = np.minimum(1.0, np.minimum(t / 0.01, (e.note_length_seconds - t) / 0.05))
        timeline[start : start + n] = amp * env * np.sin(2 * np.pi * freq * t)
    job.output_wav.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(job.output_wav), timeline, SR, subtype="PCM_24")
    return job.output_wav


def build_config(tmp_path: Path) -> Config:
    cfg = Config(
        {
            "output_dir": str(tmp_path / "out"),
            "midi": {
                "lowest_note": 48,
                "highest_note": 60,
                "note_interval_semitones": 12,
                "note_length_seconds": 1.0,
                "release_tail_seconds": 0.3,
            },
            "velocities": [60, 127],
            "audio": {
                "sample_rate": SR,
                "bit_depth": 24,
                "channels": 1,
                "trim_silence": True,
                "normalize": True,
                "normalize_target_db": -3.0,
                "loop_detection": True,
            },
            "exporters": {"mpc_xpm": True, "sfz": True, "decentsampler": True},
        }
    )
    return cfg


def test_full_pipeline(tmp_path: Path) -> None:
    config = build_config(tmp_path)
    queue = QueueManager(save_path=tmp_path / "queue.json")
    db = Database()
    job = queue.add(Job(plugin="FakeSynth", bank="Bank A", preset="Warm Pad"))

    runner = PipelineRunner(
        queue, config, db=db, render_fn=fake_render,
        output_root=Path(config.get("output_dir")),
    )
    runner.start()
    runner.join(timeout=120)
    assert not runner.is_running

    finished = queue.get(job.id)
    assert finished.status == JobStatus.COMPLETED, finished.error
    assert finished.progress == 1.0

    preset_dir = tmp_path / "out" / "FakeSynth" / "Bank A" / "Warm Pad"
    samples = sorted((preset_dir / "Samples").glob("*.wav"))
    assert len(samples) == 4  # notes 48,60 x vels 60,127

    # Metadata
    meta = json.loads((preset_dir / "instrument.json").read_text())
    assert meta["sample_count"] == 4
    assert (preset_dir / "samples.csv").exists()

    # Exports
    assert (preset_dir / "Warm Pad.xpm").exists()
    assert (preset_dir / "Warm Pad.sfz").exists()
    assert (preset_dir / "Warm Pad.dspreset").exists()

    # SFZ references samples relative to the preset dir
    sfz = (preset_dir / "Warm Pad.sfz").read_text()
    assert "sample=Samples/C3_v60.wav" in sfz

    # DB state
    summary = db.run_summary(1)
    assert summary["status"] == "completed"
    assert summary["sample_count"] == 4

    # Batch report
    report = tmp_path / "out" / "Logs" / "render_report.md"
    assert report.exists()
    assert "- Completed: 1" in report.read_text()


def test_fxchain_override_reaches_render_job(tmp_path: Path) -> None:
    config = build_config(tmp_path)
    queue = QueueManager(save_path=tmp_path / "queue.json")
    db = Database()
    seen: dict = {}

    def capturing_render(render_job: RenderJob, plan: NotePlan) -> Path:
        seen["fxchain"] = render_job.fxchain
        return fake_render(render_job, plan)

    queue.add(
        Job(
            plugin="FakeSynth",
            preset="Custom",
            settings_override={"fxchain": "C:/chains/warm.RfxChain"},
        )
    )
    runner = PipelineRunner(
        queue, config, db=db, render_fn=capturing_render,
        output_root=Path(config.get("output_dir")),
    )
    runner.start()
    runner.join(timeout=60)
    assert seen["fxchain"] == "C:/chains/warm.RfxChain"


def test_pipeline_records_failure(tmp_path: Path) -> None:
    config = build_config(tmp_path)
    queue = QueueManager(save_path=tmp_path / "queue.json")
    db = Database()
    job = queue.add(Job(plugin="Broken"))

    def broken_render(render_job: RenderJob, plan: NotePlan) -> Path:
        raise RuntimeError("plugin not found: Broken")

    runner = PipelineRunner(
        queue, config, db=db, render_fn=broken_render,
        output_root=Path(config.get("output_dir")),
    )
    runner.start()
    runner.join(timeout=60)

    finished = queue.get(job.id)
    assert finished.status == JobStatus.FAILED
    assert "plugin not found" in finished.error
    assert db.run_summary(1)["status"] == "failed"
