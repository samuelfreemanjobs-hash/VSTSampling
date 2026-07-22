"""Drives Reaper from Python: writes job files, launches headless renders."""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from core.logger import get_logger
from reaper.midi_generator import NotePlan, write_midi_file

log = get_logger(__name__)

SCRIPT_DIR = Path(__file__).resolve().parent / "scripts"
RENDER_SCRIPT = SCRIPT_DIR / "render_job.lua"

_DEFAULT_REAPER_PATHS = [
    r"C:\Program Files\REAPER (x64)\reaper.exe",
    r"C:\Program Files\REAPER\reaper.exe",
    "/Applications/REAPER.app/Contents/MacOS/REAPER",
    "/usr/local/bin/reaper",
]


class ReaperError(RuntimeError):
    pass


@dataclass
class RenderJob:
    plugin: str
    preset: str
    midi_file: Path
    output_wav: Path
    total_seconds: float
    sample_rate: int = 44100
    bit_depth: int = 24
    channels: int = 2
    fxchain: str = ""

    def to_json(self) -> str:
        return json.dumps(
            {
                "plugin": self.plugin,
                "preset": self.preset,
                "fxchain": self.fxchain,
                "midi_file": str(self.midi_file),
                "output_wav": str(self.output_wav),
                "total_seconds": round(self.total_seconds, 3),
                "sample_rate": self.sample_rate,
                "bit_depth": self.bit_depth,
                "channels": self.channels,
            },
            indent=2,
        )


def find_reaper(configured: str = "") -> Path | None:
    """Locate reaper executable: explicit config first, then PATH, then defaults."""
    if configured:
        p = Path(configured)
        if p.exists():
            return p
    on_path = shutil.which("reaper")
    if on_path:
        return Path(on_path)
    for candidate in _DEFAULT_REAPER_PATHS:
        p = Path(candidate)
        if p.exists():
            return p
    return None


class ReaperController:
    def __init__(self, reaper_path: str = "", work_dir: Path | None = None) -> None:
        self.reaper_path = find_reaper(reaper_path)
        # Absolute, because Reaper resolves the -script argument (and the
        # Lua script resolves its sibling files) from its own directory.
        self.work_dir = (work_dir or SCRIPT_DIR).resolve()

    def prepare_job(self, job: RenderJob, plan: NotePlan) -> Path:
        """Write the MIDI timeline, slice map, events file, and job JSON.

        The .mid file is a reference artifact; the Lua script reads the
        tab-separated events file instead (direct MIDI-API insertion —
        no import prompts, tempo-independent timing).
        """
        write_midi_file(plan, job.midi_file)
        plan.save_slice_map(job.output_wav.with_suffix(".slices.json"))
        self.work_dir.mkdir(parents=True, exist_ok=True)
        events_file = self.work_dir / "current_events.txt"
        lines = [
            f"{e.start_seconds:.6f}\t{e.start_seconds + e.note_length_seconds:.6f}"
            f"\t{e.midi_note}\t{e.velocity}"
            for e in plan.events
        ]
        events_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        job_file = self.work_dir / "current_job.json"
        job_file.write_text(job.to_json(), encoding="utf-8")
        # The Lua script resolves job/events/result paths relative to its own
        # location, so run a copy that lives next to the job files.
        script_copy = self.work_dir / RENDER_SCRIPT.name
        if script_copy.resolve() != RENDER_SCRIPT.resolve():
            shutil.copyfile(RENDER_SCRIPT, script_copy)
        return job_file

    def build_command(self) -> list[str]:
        if self.reaper_path is None:
            raise ReaperError(
                "Reaper executable not found. Set 'reaper_path' in settings.json."
            )
        # Script files are positional arguments — Reaper runs .lua files
        # passed on the command line at startup (there is no -script flag).
        # -newinst forces a private instance: without it, an already-open
        # Reaper swallows the command and our process exits immediately.
        return [
            str(self.reaper_path),
            "-newinst",
            "-new",
            "-nosplash",
            "-ignoreerrors",
            str(self.work_dir / RENDER_SCRIPT.name),
        ]

    def render(self, job: RenderJob, plan: NotePlan, timeout_seconds: int = 1800) -> Path:
        """Blocking render. Returns the output WAV path or raises ReaperError."""
        self.prepare_job(job, plan)
        result_file = self.work_dir / "render_result.txt"
        started_file = self.work_dir / "render_started.txt"
        result_file.unlink(missing_ok=True)
        started_file.unlink(missing_ok=True)
        job.output_wav.parent.mkdir(parents=True, exist_ok=True)

        cmd = self.build_command()
        log.info("Launching Reaper: %s", " ".join(cmd))
        proc = subprocess.Popen(cmd, cwd=str(self.work_dir))

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if result_file.exists():
                break
            if proc.poll() is not None and not result_file.exists():
                # Reaper exited without writing a result — give the FS a beat.
                time.sleep(2)
                break
            time.sleep(1)
        else:
            proc.kill()
            raise ReaperError(f"Render timed out after {timeout_seconds}s")

        # The script asks Reaper to quit, but a modal prompt (e.g. "save
        # project?") could leave it hanging — once we have a result, the
        # process has no further job to do. Reap it ourselves.
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

        if not result_file.exists():
            if not started_file.exists():
                raise ReaperError(
                    "Reaper exited without ever running the render script. "
                    "Most common cause: another Reaper window was already open "
                    "— close ALL Reaper windows and retry. If none were open, "
                    "check for a Reaper error dialog on screen."
                )
            raise ReaperError(
                "The render script started but died before reporting a result. "
                "If a Reaper window is open with an error dialog, note what it "
                "says and close it, then retry."
            )
        result = result_file.read_text(encoding="utf-8").strip()
        if result.startswith("ERROR"):
            raise ReaperError(result)
        if not job.output_wav.exists():
            raise ReaperError(f"Render reported OK but {job.output_wav} is missing")
        log.info("Rendered %s", job.output_wav)
        return job.output_wav
