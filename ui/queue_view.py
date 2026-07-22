"""Queue view — job list with add/remove/reorder/pause/resume controls."""
from __future__ import annotations

from pathlib import Path
from tkinter import filedialog

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

# Drum kits: every note chromatically, one velocity, one-shots with a
# generous ring-out; unmapped notes render silent and are dropped.
DRUM_MODE_OVERRIDE = {
    "mode": "drum",
    "lowest_note": 24,
    "highest_note": 96,
    "interval_semitones": 1,
    "velocities": [127],
    "round_robins": 1,
    "note_length_seconds": 0.5,
    "release_tail_seconds": 2.5,
    "loop_detection": False,
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

        options = ctk.CTkFrame(row, fg_color="transparent")
        options.grid(row=1, column=0, columnspan=3, pady=(6, 0), sticky="w")

        self.mode_menu = ctk.CTkOptionMenu(
            options, values=["Keygroup (pitched)", "Drum kit (one-shots)"], width=180
        )
        self.mode_menu.pack(side="left", padx=(0, 12))

        self.quick_test = ctk.CTkCheckBox(options, text="Quick test (~1 min)")
        self.quick_test.pack(side="left", padx=(0, 12))

        self.auto_length = ctk.CTkCheckBox(
            options, text="Auto length (probe each preset)"
        )
        self.auto_length.pack(side="left")

        # Optional saved Reaper FX chain — captures a fully dialed-in sound,
        # needed for plugins whose presets Reaper can't select by name.
        self._fxchain: str = ""
        self.fxchain_btn = ctk.CTkButton(
            row, text="FX Chain…", width=100, command=self._pick_fxchain
        )
        self.fxchain_btn.grid(row=1, column=2, pady=(6, 0), sticky="e")
        side = ctk.CTkFrame(row, fg_color="transparent")
        side.grid(row=1, column=3, padx=(6, 0), pady=(6, 0), sticky="e")
        ctk.CTkButton(side, text="Scan Presets…", width=110, command=self._scan_presets).pack(
            side="top", pady=(0, 4)
        )
        ctk.CTkButton(side, text="Batch Add…", width=110, command=self._open_batch_add).pack(
            side="top"
        )

    def _pick_fxchain(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose a Reaper FX chain",
            filetypes=[("Reaper FX chain", "*.RfxChain"), ("All files", "*.*")],
        )
        if path:
            self._fxchain = path
            self.fxchain_btn.configure(text=f"FX: {Path(path).stem[:12]}")
            self.app.set_status(f"Jobs will load FX chain {Path(path).name}")
        else:
            self._fxchain = ""
            self.fxchain_btn.configure(text="FX Chain…")

    def _open_batch_add(self) -> None:
        dialog = ctk.CTkToplevel(self)
        dialog.title("Batch Add Presets")
        dialog.geometry("460x420")
        dialog.grab_set()
        dialog.grid_columnconfigure(0, weight=1)
        dialog.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            dialog,
            text="One preset name per line. Each line becomes a job for the\n"
            "plugin and bank currently selected above.",
            justify="left",
        ).grid(row=0, column=0, padx=16, pady=(16, 8), sticky="w")

        textbox = ctk.CTkTextbox(dialog)
        textbox.grid(row=1, column=0, padx=16, pady=8, sticky="nsew")

        def add_all() -> None:
            plugin = self.plugin_entry.get().strip()
            if not plugin or plugin.startswith("("):
                self.app.set_status("Pick a plugin first")
                return
            names = [
                line.strip()
                for line in textbox.get("1.0", "end").splitlines()
                if line.strip()
            ]
            override = self._current_override()
            for name in names:
                self.queue.add(
                    Job(
                        plugin=plugin,
                        bank=self.bank_entry.get().strip(),
                        preset=name,
                        settings_override=dict(override),
                    )
                )
            self.app.set_status(f"Queued {len(names)} job(s)")
            dialog.destroy()

        ctk.CTkButton(dialog, text="Add All", command=add_all).grid(
            row=2, column=0, padx=16, pady=(8, 16), sticky="e"
        )

    def _current_override(self) -> dict:
        override: dict = {}
        if self.mode_menu.get().startswith("Drum"):
            override.update(DRUM_MODE_OVERRIDE)
        if self.quick_test.get():
            override.update(QUICK_TEST_OVERRIDE)
        if self.auto_length.get():
            override["auto_length"] = True
        if self._fxchain:
            override["fxchain"] = self._fxchain
        return override

    # -- preset scanning ----------------------------------------------

    def _scan_presets(self) -> None:
        plugin = self.plugin_entry.get().strip()
        if not plugin or plugin.startswith("("):
            self.app.set_status("Pick a plugin first")
            return
        self.app.set_status(f"Scanning presets of {plugin} — Reaper will open briefly…")

        def worker() -> None:
            from core.pipeline import _plugin_folder
            from reaper.reaper_controller import ReaperController, ReaperError

            try:
                scan_dir = (
                    Path(self.app.config_obj.get("output_dir", "output")).resolve()
                    / "_preset_scans"
                    / _plugin_folder(plugin)
                )
                ctrl = ReaperController(
                    reaper_path=self.app.config_obj.get("reaper_path", ""),
                    work_dir=scan_dir,
                )
                names = ctrl.enumerate_presets(plugin)
                self.after(0, lambda: self._show_scan_results(plugin, names))
            except ReaperError as exc:
                msg = str(exc)
                self.after(0, lambda: self.app.set_status(f"Preset scan failed: {msg}"))

        import threading

        threading.Thread(target=worker, daemon=True, name="preset-scan").start()

    def _show_scan_results(self, plugin: str, names: list[str]) -> None:
        if not names:
            self.app.set_status(
                f"{plugin} exposes no presets to Reaper — use an FX chain instead"
            )
            return
        self.app.set_status(f"Found {len(names)} presets")

        dialog = ctk.CTkToplevel(self)
        dialog.title(f"Presets — {plugin}")
        dialog.geometry("520x560")
        dialog.grab_set()
        dialog.grid_columnconfigure(0, weight=1)
        dialog.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(dialog, fg_color="transparent")
        header.grid(row=0, column=0, padx=16, pady=(16, 4), sticky="ew")
        count_label = ctk.CTkLabel(header, text=f"{len(names)} presets — 0 selected")
        count_label.pack(side="left")

        scroll = ctk.CTkScrollableFrame(dialog)
        scroll.grid(row=1, column=0, padx=16, pady=8, sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)

        vars_: list[ctk.BooleanVar] = []

        def update_count() -> None:
            n = sum(1 for v in vars_ if v.get())
            count_label.configure(text=f"{len(names)} presets — {n} selected")

        for i, name in enumerate(names):
            var = ctk.BooleanVar(value=False)
            vars_.append(var)
            ctk.CTkCheckBox(
                scroll, text=name, variable=var, command=update_count
            ).grid(row=i, column=0, sticky="w", pady=1)

        def set_all(value: bool) -> None:
            for v in vars_:
                v.set(value)
            update_count()

        ctk.CTkButton(header, text="All", width=50, command=lambda: set_all(True)).pack(
            side="right", padx=(4, 0)
        )
        ctk.CTkButton(header, text="None", width=54, command=lambda: set_all(False)).pack(
            side="right"
        )

        def queue_selected() -> None:
            base = self._current_override()
            queued = 0
            for i, name in enumerate(names):
                if not vars_[i].get():
                    continue
                override = dict(base)
                override["preset_index"] = i
                self.queue.add(
                    Job(
                        plugin=plugin,
                        bank=self.bank_entry.get().strip(),
                        preset=name,
                        settings_override=override,
                    )
                )
                queued += 1
            self.app.set_status(f"Queued {queued} preset job(s)")
            dialog.destroy()

        ctk.CTkButton(dialog, text="Queue Selected", command=queue_selected).grid(
            row=2, column=0, padx=16, pady=(8, 16), sticky="e"
        )

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
        ctk.CTkButton(bar, text="Retry Failed", width=100, command=self._retry).pack(
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
        override = self._current_override()
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

    def _retry(self) -> None:
        n = self.queue.retry_finished()
        self.app.set_status(f"Re-queued {n} job(s)" if n else "Nothing to retry")

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
                err = ctk.CTkLabel(
                    frame, text=f"{job.error[:50]}…  (click for details)"
                    if len(job.error) > 50 else job.error,
                    text_color="#E04F4F", anchor="e",
                )
                err.grid(row=0, column=2, padx=8)
                err.bind(
                    "<Button-1>",
                    lambda _e, j=job: self._show_error(j),
                )

    def _show_error(self, job) -> None:
        dialog = ctk.CTkToplevel(self)
        dialog.title(f"Error — {job.display_name}")
        dialog.geometry("560x300")
        dialog.grab_set()
        dialog.grid_columnconfigure(0, weight=1)
        dialog.grid_rowconfigure(0, weight=1)
        box = ctk.CTkTextbox(dialog, wrap="word")
        box.grid(row=0, column=0, padx=16, pady=16, sticky="nsew")
        box.insert(
            "1.0",
            f"{job.display_name}\n\n{job.error}\n\n"
            "Tip: use 'Save Diagnostics' on the Dashboard and paste the file "
            "to Claude to get this fixed.",
        )
        box.configure(state="disabled")
