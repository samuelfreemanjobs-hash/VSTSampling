"""Pipeline orchestrator: pulls jobs from the queue and runs the full
render → slice → process → QC → metadata → export chain in a worker
thread. The Reaper render step is injectable so tests (and dry runs)
can substitute a synthetic renderer.
"""
from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any, Callable

from core.audio_processor import process_sample_file, qc_check, slice_render
from core.config import Config
from core.database import Database
from core.logger import get_logger
from core.metadata import write_instrument_metadata, write_run_report
from core.queue_manager import Job, JobStatus, QueueManager
from exporters.decentsampler import export_decentsampler
from exporters.kontakt import export_kontakt
from exporters.mapping import build_instrument_map
from exporters.mpc import export_mpc_xpm
from exporters.sfz import export_sfz
from reaper.midi_generator import NotePlan, build_note_plan
from reaper.reaper_controller import ReaperController, RenderJob

log = get_logger(__name__)

RenderFn = Callable[[RenderJob, NotePlan], Path]


def _safe_name(name: str) -> str:
    return re.sub(r"[^\w\- ]+", "_", name).strip() or "Untitled"


class PipelineRunner:
    def __init__(
        self,
        queue: QueueManager,
        config: Config,
        db: Database | None = None,
        render_fn: RenderFn | None = None,
        output_root: Path | None = None,
    ) -> None:
        self.queue = queue
        self.config = config
        self.db = db or Database(Path(config.get("database_path", "database/factory.db")))
        # Absolute: these paths get handed to Reaper, which runs with a
        # different working directory than the app.
        self.output_root = (output_root or Path(config.get("output_dir", "output"))).resolve()
        self._render_fn = render_fn
        self._thread: threading.Thread | None = None

    # -- lifecycle ----------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            return
        self.queue.reset_run_flags()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="pipeline")
        self._thread.start()

    def join(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)

    # -- main loop ----------------------------------------------------

    def _run_loop(self) -> None:
        run_ids: list[int] = []
        try:
            log.info("Pipeline started; %d job(s) pending",
                     sum(1 for j in self.queue.jobs() if j.status == JobStatus.PENDING))
            while not self.queue.cancel_event.is_set():
                if self.queue.pause_event.is_set():
                    if self.queue.pause_event.wait(0.2):
                        continue
                job = self.queue.next_pending()
                if job is None:
                    break
                run_ids.append(self._run_job(job))
        except Exception:  # noqa: BLE001 — a dead worker must leave a trace in the log
            log.exception("Pipeline worker crashed")
        finally:
            log.info("Pipeline finished; %d run(s)", len(run_ids))
            self._write_batch_report(run_ids)

    def _write_batch_report(self, run_ids: list[int]) -> None:
        if not run_ids:
            return
        summaries = [s for rid in run_ids if (s := self.db.run_summary(rid))]
        report = self.output_root / "Logs" / "render_report.md"
        write_run_report(report, summaries)
        log.info("Batch report: %s", report)

    # -- one job ------------------------------------------------------

    def _job_settings(self, job: Job) -> dict[str, Any]:
        cfg = self.config
        s = {
            "lowest_note": cfg.get("midi.lowest_note", 24),
            "highest_note": cfg.get("midi.highest_note", 108),
            "interval_semitones": cfg.get("midi.note_interval_semitones", 3),
            "velocities": cfg.get("velocities", [100]),
            "round_robins": cfg.get("midi.round_robins", 1),
            "note_length_seconds": cfg.get("midi.note_length_seconds", 3.0),
            "release_tail_seconds": cfg.get("midi.release_tail_seconds", 1.5),
            "sample_rate": cfg.get("audio.sample_rate", 44100),
            "bit_depth": cfg.get("audio.bit_depth", 24),
            "channels": cfg.get("audio.channels", 2),
            "trim_silence": cfg.get("audio.trim_silence", True),
            "normalize": cfg.get("audio.normalize", False),
            "normalize_target_db": cfg.get("audio.normalize_target_db", -3.0),
            "loop_detection": cfg.get("audio.loop_detection", True),
            "exporters": cfg.get("exporters", {"mpc_xpm": True}),
            "fxchain": "",
        }
        s.update(job.settings_override or {})
        return s

    def _run_job(self, job: Job) -> int:
        s = self._job_settings(job)
        out_dir = (
            self.output_root
            / _safe_name(job.plugin)
            / _safe_name(job.bank or "Default")
            / _safe_name(job.preset or "Default")
        )
        samples_dir = out_dir / "Samples"

        plugin_id = self.db.upsert_plugin(job.plugin)
        bank_id = self.db.upsert_bank(plugin_id, job.bank or "Default")
        preset_id = self.db.upsert_preset(bank_id, job.preset or "Default")
        run_id = self.db.start_run(job.id, preset_id, str(out_dir))

        self.queue.update(job.id, status=JobStatus.RUNNING, progress=0.0, message="Planning")
        try:
            plan = build_note_plan(
                lowest_note=s["lowest_note"],
                highest_note=s["highest_note"],
                interval_semitones=s["interval_semitones"],
                velocities=list(s["velocities"]),
                round_robins=s["round_robins"],
                note_length_seconds=s["note_length_seconds"],
                release_tail_seconds=s["release_tail_seconds"],
            )

            # 1. Render one long WAV via Reaper (or injected renderer)
            self.queue.update(job.id, progress=0.05, message="Rendering in Reaper")
            render_wav = out_dir / "render.wav"
            render_job = RenderJob(
                plugin=job.plugin,
                preset=job.preset,
                midi_file=out_dir / "timeline.mid",
                output_wav=render_wav,
                total_seconds=plan.total_seconds,
                sample_rate=s["sample_rate"],
                bit_depth=s["bit_depth"],
                channels=s["channels"],
                fxchain=s["fxchain"],
            )
            if self._render_fn is not None:
                ctrl = ReaperController(work_dir=out_dir)
                ctrl.prepare_job(render_job, plan)
                self._render_fn(render_job, plan)
            else:
                ctrl = ReaperController(
                    reaper_path=self.config.get("reaper_path", ""), work_dir=out_dir
                )
                ctrl.render(render_job, plan)

            # 2. Slice
            self.queue.update(job.id, progress=0.45, message="Slicing")
            written = slice_render(
                render_wav, render_wav.with_suffix(".slices.json"), samples_dir
            )
            by_name = {p.stem: p for p in written}

            # 3. Process + QC + collect metadata
            sample_rows: list[dict[str, Any]] = []
            total = len(plan.events) or 1
            for i, event in enumerate(plan.events):
                if self.queue.cancel_event.is_set():
                    raise InterruptedError("Cancelled")
                path = by_name.get(event.sample_name)
                if path is None:
                    continue
                meta = process_sample_file(
                    path,
                    trim=s["trim_silence"],
                    normalize=s["normalize"],
                    normalize_target_db=s["normalize_target_db"],
                    mono=s["channels"] == 1,
                    bit_depth=s["bit_depth"],
                    find_loop=s["loop_detection"],
                )
                if meta.get("silent"):
                    path.unlink(missing_ok=True)
                    continue
                qc = qc_check(path)
                row = {
                    "file_path": str(path),
                    "midi_note": event.midi_note,
                    "velocity": event.velocity,
                    "round_robin": event.round_robin,
                    "duration_seconds": meta.get("duration_seconds"),
                    "peak_db": meta.get("peak_db"),
                    "loop_start": meta.get("loop_start"),
                    "loop_end": meta.get("loop_end"),
                    "qc_passed": qc.passed,
                }
                sample_rows.append(row)
                self.db.add_sample(run_id, **row)
                self.queue.update(
                    job.id,
                    progress=0.45 + 0.4 * (i + 1) / total,
                    message=f"Processing {event.sample_name}",
                )
            if not sample_rows:
                raise RuntimeError("Every slice came back silent — check the plugin/preset")

            # 4. Metadata + exports
            self.queue.update(job.id, progress=0.9, message="Exporting")
            write_instrument_metadata(
                out_dir,
                plugin=job.plugin,
                bank=job.bank,
                preset=job.preset,
                samples=sample_rows,
                settings={k: v for k, v in s.items() if k != "exporters"},
            )
            imap = build_instrument_map(
                _safe_name(job.preset or job.plugin), sample_rows
            )
            exporters_cfg = s["exporters"]
            if exporters_cfg.get("mpc_xpm"):
                p = export_mpc_xpm(imap, out_dir / f"{imap.name}.xpm")
                self.db.add_export(run_id, "mpc_xpm", str(p))
            if exporters_cfg.get("sfz"):
                p = export_sfz(imap, out_dir / f"{imap.name}.sfz", samples_relative_to=out_dir)
                self.db.add_export(run_id, "sfz", str(p))
            if exporters_cfg.get("decentsampler"):
                p = export_decentsampler(
                    imap, out_dir / f"{imap.name}.dspreset", samples_relative_to=out_dir
                )
                self.db.add_export(run_id, "decentsampler", str(p))
            if exporters_cfg.get("kontakt"):
                p = export_kontakt(imap, out_dir, samples_relative_to=out_dir)
                self.db.add_export(run_id, "kontakt_sfz", str(p))

            self.db.finish_run(run_id, "completed")
            self.queue.update(
                job.id, status=JobStatus.COMPLETED, progress=1.0,
                message=f"{len(sample_rows)} samples",
            )
            log.info("Job %s completed: %d samples -> %s", job.id, len(sample_rows), out_dir)
        except InterruptedError:
            self.db.finish_run(run_id, "cancelled")
            self.queue.update(job.id, status=JobStatus.CANCELLED, message="Cancelled")
        except Exception as exc:  # noqa: BLE001 — job isolation: one failure must not kill the batch
            log.exception("Job %s failed", job.id)
            self.db.finish_run(run_id, "failed", error=str(exc))
            self.queue.update(job.id, status=JobStatus.FAILED, error=str(exc))
        return run_id
