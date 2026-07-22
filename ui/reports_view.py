"""Reports view — shows the latest batch render report."""
from __future__ import annotations

from pathlib import Path

import customtkinter as ctk


class ReportsView(ctk.CTkFrame):
    def __init__(self, master, app) -> None:
        super().__init__(master, corner_radius=0)
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            self, text="Reports", font=ctk.CTkFont(size=24, weight="bold")
        ).grid(row=0, column=0, padx=24, pady=(24, 8), sticky="w")

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=1, column=0, padx=24, pady=(0, 8), sticky="ew")
        ctk.CTkButton(bar, text="Refresh", width=90, command=self.refresh).pack(side="left")
        self.path_label = ctk.CTkLabel(bar, text="", text_color="gray")
        self.path_label.pack(side="left", padx=12)

        self.textbox = ctk.CTkTextbox(
            self, wrap="none", font=ctk.CTkFont(family="Courier New", size=12)
        )
        self.textbox.grid(row=2, column=0, padx=24, pady=(0, 24), sticky="nsew")
        self.refresh()

    def _report_path(self) -> Path:
        return Path(self.app.config_obj.get("output_dir", "output")) / "Logs" / "render_report.md"

    def refresh(self) -> None:
        report = self._report_path()
        self.textbox.configure(state="normal")
        self.textbox.delete("1.0", "end")
        if report.exists():
            self.textbox.insert("1.0", report.read_text(encoding="utf-8"))
            self.path_label.configure(text=str(report))
        else:
            self.textbox.insert("1.0", "No report yet. Run a queue to generate one.")
            self.path_label.configure(text="")
        self.textbox.configure(state="disabled")
