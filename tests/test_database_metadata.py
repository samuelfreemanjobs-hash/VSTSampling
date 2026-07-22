"""Tests for core.database and core.metadata."""
from __future__ import annotations

import json
from pathlib import Path

from core.database import Database
from core.metadata import write_instrument_metadata, write_run_report


def test_upserts_are_idempotent() -> None:
    db = Database()
    p1 = db.upsert_plugin("Omnisphere", developer="Spectrasonics")
    p2 = db.upsert_plugin("Omnisphere")
    assert p1 == p2
    b1 = db.upsert_bank(p1, "Factory A")
    b2 = db.upsert_bank(p1, "Factory A")
    assert b1 == b2
    pr1 = db.upsert_preset(b1, "Warm Pad", category="Pad")
    pr2 = db.upsert_preset(b1, "Warm Pad")
    assert pr1 == pr2
    db.close()


def test_run_lifecycle_and_summary() -> None:
    db = Database()
    plugin = db.upsert_plugin("Serum")
    bank = db.upsert_bank(plugin, "Factory")
    preset = db.upsert_preset(bank, "Init")
    run = db.start_run("job123", preset, "/out/serum/init")

    db.add_sample(run, "/out/C4_v100.wav", 60, 100, duration_seconds=2.0,
                  peak_db=-3.0, qc_passed=True)
    db.add_sample(run, "/out/C4_v40.wav", 60, 40, qc_passed=False)
    db.finish_run(run, "completed")
    db.add_export(run, "sfz", "/out/serum.sfz")

    summary = db.run_summary(run)
    assert summary is not None
    assert summary["status"] == "completed"
    assert summary["sample_count"] == 2
    assert summary["qc_passed_count"] == 1

    samples = db.samples_for_run(run)
    assert [s["velocity"] for s in samples] == [40, 100]
    assert db.recent_runs()[0]["id"] == run
    db.close()


def _sample_dicts() -> list[dict]:
    return [
        {
            "file_path": "Samples/C4_v100.wav", "midi_note": 60, "velocity": 100,
            "round_robin": 0, "duration_seconds": 2.0, "peak_db": -3.0,
            "loop_start": 22050, "loop_end": 66150, "qc_passed": True,
        },
        {
            "file_path": "Samples/D#4_v100.wav", "midi_note": 63, "velocity": 100,
            "round_robin": 0, "duration_seconds": 2.0, "peak_db": -3.2,
            "loop_start": None, "loop_end": None, "qc_passed": True,
        },
    ]


def test_instrument_metadata_files(tmp_path: Path) -> None:
    json_path, csv_path = write_instrument_metadata(
        tmp_path,
        plugin="Omnisphere",
        bank="Factory A",
        preset="Warm Pad",
        samples=_sample_dicts(),
        settings={"velocities": [100]},
    )
    payload = json.loads(json_path.read_text())
    assert payload["preset"] == "Warm Pad"
    assert payload["sample_count"] == 2
    assert payload["samples"][0]["note_name"] == "C4"
    assert payload["samples"][1]["note_name"] == "D#4"

    csv_body = csv_path.read_text()
    assert "C4_v100.wav" in csv_body
    assert csv_body.count("\n") == 3  # header + 2 rows


def test_run_report(tmp_path: Path) -> None:
    runs = [
        {"id": 1, "job_id": "a", "status": "completed", "sample_count": 10,
         "qc_passed_count": 10, "output_dir": "/out/a"},
        {"id": 2, "job_id": "b", "status": "failed", "sample_count": 0,
         "qc_passed_count": 0, "output_dir": "/out/b", "error": "plugin not found"},
    ]
    report = write_run_report(tmp_path / "report.md", runs)
    body = report.read_text()
    assert "- Runs: 2" in body
    assert "- Completed: 1" in body
    assert "plugin not found" in body
