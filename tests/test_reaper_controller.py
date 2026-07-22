"""Tests for reaper.reaper_controller — job prep and command construction.

Actual Reaper launches are exercised on the user's machine, not in CI.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from reaper.midi_generator import build_note_plan
from reaper.reaper_controller import ReaperController, ReaperError, RenderJob


def test_prepare_job_writes_all_artifacts(tmp_path: Path) -> None:
    plan = build_note_plan(lowest_note=60, highest_note=66, velocities=[100])
    job = RenderJob(
        plugin="VSTi: Serum (Xfer Records)",
        preset="Init",
        midi_file=tmp_path / "timeline.mid",
        output_wav=tmp_path / "render.wav",
        total_seconds=plan.total_seconds,
    )
    ctrl = ReaperController(work_dir=tmp_path)
    job_file = ctrl.prepare_job(job, plan)

    assert (tmp_path / "timeline.mid").exists()
    assert (tmp_path / "render.slices.json").exists()
    payload = json.loads(job_file.read_text())
    assert payload["plugin"] == "VSTi: Serum (Xfer Records)"
    assert payload["sample_rate"] == 44100
    assert payload["total_seconds"] == round(plan.total_seconds, 3)


def test_build_command_requires_reaper(tmp_path: Path) -> None:
    ctrl = ReaperController(reaper_path="", work_dir=tmp_path)
    if ctrl.reaper_path is None:
        with pytest.raises(ReaperError):
            ctrl.build_command()
    else:  # dev machine with reaper installed
        cmd = ctrl.build_command()
        assert "-script" in cmd


def test_build_command_with_explicit_path(tmp_path: Path) -> None:
    fake = tmp_path / "reaper.exe"
    fake.write_bytes(b"")
    ctrl = ReaperController(reaper_path=str(fake), work_dir=tmp_path)
    cmd = ctrl.build_command()
    assert cmd[0] == str(fake)
    assert cmd[1:3] == ["-new", "-nosplash"]
