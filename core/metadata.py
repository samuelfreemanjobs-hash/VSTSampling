"""Metadata sidecars and run reports (JSON + CSV + Markdown)."""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from reaper.midi_generator import note_name

_SAMPLE_FIELDS = [
    "file_path", "midi_note", "note_name", "velocity", "round_robin",
    "duration_seconds", "peak_db", "loop_start", "loop_end", "qc_passed",
]


def _enrich(sample: dict[str, Any]) -> dict[str, Any]:
    out = {k: sample.get(k) for k in _SAMPLE_FIELDS}
    out["note_name"] = note_name(int(sample["midi_note"]))
    return out


def write_instrument_metadata(
    output_dir: Path,
    *,
    plugin: str,
    bank: str,
    preset: str,
    samples: list[dict[str, Any]],
    settings: dict[str, Any] | None = None,
) -> tuple[Path, Path]:
    """Write instrument.json + samples.csv next to the samples."""
    output_dir.mkdir(parents=True, exist_ok=True)
    enriched = [_enrich(s) for s in samples]

    payload = {
        "generator": "VST Sampling Factory",
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "plugin": plugin,
        "bank": bank,
        "preset": preset,
        "sample_count": len(enriched),
        "settings": settings or {},
        "samples": enriched,
    }
    json_path = output_dir / "instrument.json"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    csv_path = output_dir / "samples.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_SAMPLE_FIELDS)
        writer.writeheader()
        writer.writerows(enriched)
    return json_path, csv_path


def write_run_report(
    report_path: Path,
    runs: list[dict[str, Any]],
) -> Path:
    """Markdown summary across a batch of runs."""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    completed = [r for r in runs if r.get("status") == "completed"]
    failed = [r for r in runs if r.get("status") == "failed"]

    lines = [
        "# Render Report",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        "",
        f"- Runs: {len(runs)}",
        f"- Completed: {len(completed)}",
        f"- Failed: {len(failed)}",
        f"- Samples: {sum(r.get('sample_count', 0) for r in runs)}",
        f"- QC passed: {sum(r.get('qc_passed_count', 0) for r in runs)}",
        "",
        "| Run | Job | Status | Samples | QC | Output |",
        "| --- | --- | ------ | ------- | -- | ------ |",
    ]
    for r in runs:
        lines.append(
            f"| {r.get('id', '')} | {r.get('job_id', '')} | {r.get('status', '')} "
            f"| {r.get('sample_count', 0)} | {r.get('qc_passed_count', 0)} "
            f"| {r.get('output_dir', '')} |"
        )
    if failed:
        lines += ["", "## Failures", ""]
        for r in failed:
            lines.append(f"- Run {r.get('id')}: {r.get('error', 'unknown error')}")

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path
