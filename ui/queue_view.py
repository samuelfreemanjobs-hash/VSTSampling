"""Queue view — job list with add/remove/reorder/pause/resume controls."""
from __future__ import annotations

import customtkinter as ctk

from core.queue_manager import Job, JobStatus
from reaper.plugin_scanner import scan_reaper_plugins

# A fast validation job: 2 notes x 1 velocity, short holds — done in ~1 min
QUICK_TEST_OVERRIDE = {
    "lowest_note": 48,
    "highest_note": 60,
    "interval_semitones": 12,
    "velocities": [100],
    "round_robins": 1,
    "note_length_seconds": 1.5,
    "release_tail_seconds": 0.5,
}

_STATUS_COLORS = {
    JobStatus.PENDING: "gray",
    JobStatus.RUNNING: "#3B8ED0",
    JobStatus.PAUSED: "orange",
    JobStatus.COMPLETED: "#2CC985",
    JobStatus.FAILED: "#E04F4F",
    JobStatus.CANCELLED: "gray",
}


class QueueView(ctk.CTkFrame):
    def __init__(self, master, app) -> None:
        super().__init__(master, corner_radius=0)
        self.app = app
        self.queue = app.queue
        self._selected_id: str | None = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(
            self, text="Queue", font=ctk.CTkFont(size=24, weight="bold")
        ).grid(row=0, column=0, padx=24, pady=(24, 8), sticky="w")

        self._build_add_row()
        self._build_controls()

        self.job_list = ctk.CTkScrollableFrame(self)
        self.job_list.grid(row=3, column=0, padx=24, pady=(8, 24), sticky="nsew")
        self.job_list.grid_columnconfigure(0, weight=1)

        # Queue mutations can come from worker threads; marshal the
        # refresh onto the Tk main loop.
        self.queue.subscribe(lambda: self.after(0, self.refresh))
        self.refresh()

    def _build_add_row(self) -> None:
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.grid(row=1, column=0, padx=24, pady=4, sticky="ew")
        row.grid_columnconfigure((0, 1, 2), weight=1)

        plugins = [p.display_name for p in scan_reaper_plugins()]
        self.plugin_entry = ctk.CTkComboBox(
            row, values=plugins or ["(no plugins found — type the name manually)"]
        )
        self.plugin_entry.set(plugins[0] if plugins else "")
        self.plugin_entry.grid(row=0, column=0, padx=(0, 6), sticky="ew")

        self.bank_entry = ctk.CTkEntry(row, placeholder_text="Bank (optional)")
        self.bank_entry.grid(row=0, column=1, padx=6, sticky="ew")
        self.preset_entry = ctk.CTkEntry(row, placeholder_text="Preset (optional)")
        self.preset_entry.grid(row=0, column=2, padx=6, sticky="ew")
        ctk.CTkButton(row, text="Add Job", width=100, command=self._add_job).grid(
            row=0, column=3, padx=(6, 0)
        )

        self.quick_test = ctk.CTkCheckBox(
            row,
            text="Quick test (4 tiny samples, ~1 min — use this to verify setup first)",
        )
        self.quick_test.grid(row=1, column=0, columnspan=3, pady=(6, 0), sticky="w")

    def _build_controls(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=2, column=0, padx=24, pady=4, sticky="ew")

        self.start_btn = ctk.CTkButton(bar, text="Start Queue", width=110, command=self._start)
        self.start_btn.pack(side="left", padx=(0, 6))
        self.pause_btn = ctk.CTkButton(bar, text="Pause", width=80, command=self._toggle_pause)
        self.pause_btn.pack(side="left", padx=6)
        ctk.CTkButton(bar, text="Cancel All", width=90, command=self.queue.cancel_all).pack(
            side="left", padx=6
        )
        ctk.CTkButton(bar, text="Clear Finished", width=110, command=self.queue.clear_finished).pack(
            side="left", padx=6
        )
        ctk.CTkButton(bar, text="▲", width=36, command=lambda: self._move(-1)).pack(
            side="left", padx=(18, 3)
        )
        ctk.CTkButton(bar, text="▼", width=36, command=lambda: self._move(1)).pack(
            side="left", padx=3
        )
        ctk.CTkButton(bar, text="Remove", width=80, command=self._remove).pack(side="left", padx=6)
        ctk.CTkButton(bar, text="Save Queue", width=100, command=self._save).pack(
            side="right", padx=(6, 0)
        )
        ctk.CTkButton(bar, text="Load Queue", width=100, command=self._load).pack(side="right")

    # -- actions ------------------------------------------------------

    def _add_job(self) -> None:
        plugin = self.plugin_entry.get().strip()
        if not plugin or plugin.startswith("("):
            self.app.set_status("Plugin name is required")
            return
        override = dict(QUICK_TEST_OVERRIDE) if self.quick_test.get() else {}
        self.queue.add(
            Job(
                plugin=plugin,
                bank=self.bank_entry.get().strip(),
                preset=self.preset_entry.get().strip(),
                settings_override=override,
            )
        )
        self.preset_entry.delete(0, "end")
        self.app.set_status(f"Queued {plugin}")

    def _start(self) -> None:
        self.app.start_queue()

    def _toggle_pause(self) -> None:
        if self.queue.is_paused:
            self.queue.resume()
        else:
            self.queue.pause()

    def _move(self, offset: int) -> None:
        if self._selected_id:
            self.queue.move(self._selected_id, offset)

    def _remove(self) -> None:
        if self._selected_id:
            self.queue.remove(self._selected_id)
            self._selected_id = None

    def _save(self) -> None:
        path = self.queue.save()
        self.app.set_status(f"Queue saved to {path}")

    def _load(self) -> None:
        n = self.queue.load()
        self.app.set_status(f"Loaded {n} job(s)")

    def _select(self, job_id: str) -> None:
        self._selected_id = job_id
        self.refresh()

    # -- rendering ----------------------------------------------------

    def refresh(self) -> None:
        for child in self.job_list.winfo_children():
            child.destroy()

        jobs = self.queue.jobs()
        self.pause_btn.configure(text="Resume" if self.queue.is_paused else "Pause")
        self.app.set_queue_status(
            f"Queue: {sum(1 for j in jobs if j.status == JobStatus.PENDING)} pending"
            if jobs
            else "Queue: idle"
        )

        if not jobs:
            ctk.CTkLabel(self.job_list, text="No jobs queued.", text_color="gray").grid(
                row=0, column=0, pady=24
            )
            return

        for row, job in enumerate(jobs):
            selected = job.id == self._selected_id
            frame = ctk.CTkFrame(
                self.job_list,
                fg_color=("gray80", "gray25") if selected else "transparent",
            )
            frame.grid(row=row, column=0, pady=2, sticky="ew")
            frame.grid_columnconfigure(1, weight=1)
            frame.bind("<Button-1>", lambda _e, jid=job.id: self._select(jid))

            status = ctk.CTkLabel(
                frame,
                text=job.status.value.upper(),
                width=90,
                text_color=_STATUS_COLORS.get(job.status, "gray"),
                font=ctk.CTkFont(size=11, weight="bold"),
            )
            status.grid(row=0, column=0, padx=8, pady=6)
            status.bind("<Button-1>", lambda _e, jid=job.id: self._select(jid))

            name = ctk.CTkLabel(frame, text=job.display_name, anchor="w")
            name.grid(row=0, column=1, padx=8, sticky="ew")
            name.bind("<Button-1>", lambda _e, jid=job.id: self._select(jid))

            if job.status == JobStatus.RUNNING:
                bar = ctk.CTkProgressBar(frame, width=160)
                bar.set(job.progress)
                bar.grid(row=0, column=2, padx=8)
            elif job.error:
                ctk.CTkLabel(
                    frame, text=job.error[:60], text_color="#E04F4F", anchor="e"
                ).grid(row=0, column=2, padx=8)
