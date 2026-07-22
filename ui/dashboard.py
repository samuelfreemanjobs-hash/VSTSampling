"""Dashboard view — live system status and queue summary."""
from __future__ import annotations

import shutil
from pathlib import Path

import customtkinter as ctk

try:
    import psutil
except ImportError:
    psutil = None

from core.env_check import run_checks
from core.queue_manager import JobStatus

_REFRESH_MS = 2000


class DashboardView(ctk.CTkFrame):
    def __init__(self, master, app) -> None:
        super().__init__(master, corner_radius=0)
        self.app = app
        self.grid_columnconfigure(0, weight=1)

        header = ctk.CTkLabel(
            self, text="Dashboard", font=ctk.CTkFont(size=24, weight="bold")
        )
        header.grid(row=0, column=0, padx=24, pady=(24, 8), sticky="w")

        subtitle = ctk.CTkLabel(
            self,
            text="System status, active queue, and quick actions.",
            text_color="gray",
        )
        subtitle.grid(row=1, column=0, padx=24, pady=(0, 24), sticky="w")

        cards = ctk.CTkFrame(self, fg_color="transparent")
        cards.grid(row=2, column=0, padx=24, pady=8, sticky="ew")
        for col in range(4):
            cards.grid_columnconfigure(col, weight=1)

        self.cpu_value = self._card(cards, 0, "CPU", "—")
        self.ram_value = self._card(cards, 1, "RAM", "—")
        self.queue_value = self._card(cards, 2, "Queue", "0 jobs")
        self.disk_value = self._card(cards, 3, "Output Disk", "—")

        activity = ctk.CTkFrame(self)
        activity.grid(row=3, column=0, padx=24, pady=(24, 8), sticky="ew")
        activity.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            activity, text="Current Activity", font=ctk.CTkFont(size=14, weight="bold")
        ).grid(row=0, column=0, padx=16, pady=(12, 4), sticky="w")
        self.activity_label = ctk.CTkLabel(activity, text="Idle", text_color="gray", anchor="w")
        self.activity_label.grid(row=1, column=0, padx=16, pady=(0, 12), sticky="ew")

        self._build_check_panel()
        self._tick()

    def _build_check_panel(self) -> None:
        panel = ctk.CTkFrame(self)
        panel.grid(row=4, column=0, padx=24, pady=(8, 24), sticky="nsew")
        self.grid_rowconfigure(4, weight=1)
        panel.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(panel, fg_color="transparent")
        header.grid(row=0, column=0, padx=16, pady=(12, 4), sticky="ew")
        ctk.CTkLabel(
            header, text="Setup Check", font=ctk.CTkFont(size=14, weight="bold")
        ).pack(side="left")
        ctk.CTkButton(header, text="Re-check", width=80, command=self._run_checks).pack(
            side="right"
        )

        self.check_rows = ctk.CTkFrame(panel, fg_color="transparent")
        self.check_rows.grid(row=1, column=0, padx=16, pady=(0, 12), sticky="ew")
        self.check_rows.grid_columnconfigure(1, weight=1)
        self._run_checks()

    def _run_checks(self) -> None:
        for child in self.check_rows.winfo_children():
            child.destroy()
        row = 0
        for check in run_checks(self.app.config_obj):
            icon = "✓" if check.ok else "✗"
            color = "#2CC985" if check.ok else "#E04F4F"
            ctk.CTkLabel(
                self.check_rows, text=icon, width=24, text_color=color,
                font=ctk.CTkFont(size=14, weight="bold"),
            ).grid(row=row, column=0, sticky="w")
            ctk.CTkLabel(
                self.check_rows, text=f"{check.label}: {check.detail}", anchor="w"
            ).grid(row=row, column=1, sticky="ew", padx=(4, 0))
            row += 1
            if not check.ok and check.fix:
                ctk.CTkLabel(
                    self.check_rows, text=f"→ {check.fix}", anchor="w",
                    text_color="gray", wraplength=700, justify="left",
                ).grid(row=row, column=1, sticky="ew", padx=(4, 0))
                row += 1

    def _card(self, parent, col: int, label: str, value: str) -> ctk.CTkLabel:
        card = ctk.CTkFrame(parent, height=80)
        card.grid(row=0, column=col, padx=6, sticky="ew")
        ctk.CTkLabel(card, text=label, text_color="gray").pack(padx=12, pady=(10, 0), anchor="w")
        value_label = ctk.CTkLabel(card, text=value, font=ctk.CTkFont(size=20, weight="bold"))
        value_label.pack(padx=12, pady=(0, 10), anchor="w")
        return value_label

    def _tick(self) -> None:
        if psutil is not None:
            self.cpu_value.configure(text=f"{psutil.cpu_percent():.0f}%")
            mem = psutil.virtual_memory()
            self.ram_value.configure(text=f"{mem.percent:.0f}%")

        jobs = self.app.queue.jobs()
        pending = sum(1 for j in jobs if j.status == JobStatus.PENDING)
        running = next((j for j in jobs if j.status == JobStatus.RUNNING), None)
        self.queue_value.configure(text=f"{pending} pending")
        if running:
            self.activity_label.configure(
                text=f"{running.display_name} — {running.message} "
                f"({running.progress * 100:.0f}%)"
            )
        else:
            self.activity_label.configure(text="Idle")

        out_dir = Path(self.app.config_obj.get("output_dir", "output"))
        try:
            usage = shutil.disk_usage(out_dir if out_dir.exists() else Path.cwd())
            self.disk_value.configure(text=f"{usage.free / 1e9:.0f} GB free")
        except OSError:
            self.disk_value.configure(text="—")

        self.after(_REFRESH_MS, self._tick)
