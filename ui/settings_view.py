"""Settings view — edit settings.json in place with validation."""
from __future__ import annotations

import json

import customtkinter as ctk


class SettingsView(ctk.CTkFrame):
    def __init__(self, master, app) -> None:
        super().__init__(master, corner_radius=0)
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            self, text="Settings", font=ctk.CTkFont(size=24, weight="bold")
        ).grid(row=0, column=0, padx=24, pady=(24, 8), sticky="w")

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=1, column=0, padx=24, pady=(0, 8), sticky="ew")
        ctk.CTkButton(bar, text="Save", width=90, command=self._save).pack(side="left")
        ctk.CTkButton(bar, text="Revert", width=90, command=self._revert).pack(
            side="left", padx=8
        )
        self.feedback = ctk.CTkLabel(bar, text="", text_color="gray")
        self.feedback.pack(side="left", padx=12)

        self.textbox = ctk.CTkTextbox(
            self, wrap="none", font=ctk.CTkFont(family="Courier New", size=12)
        )
        self.textbox.grid(row=2, column=0, padx=24, pady=(0, 24), sticky="nsew")
        self._revert()

    def _revert(self) -> None:
        self.textbox.delete("1.0", "end")
        self.textbox.insert("1.0", json.dumps(self.app.config_obj.as_dict(), indent=4))
        self.feedback.configure(text="", text_color="gray")

    def _save(self) -> None:
        raw = self.textbox.get("1.0", "end")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            self.feedback.configure(text=f"Invalid JSON: {exc}", text_color="#E04F4F")
            return
        if not isinstance(data, dict):
            self.feedback.configure(text="Settings must be a JSON object", text_color="#E04F4F")
            return
        self.app.config_obj.replace(data)
        self.app.config_obj.save()
        self.feedback.configure(text="Saved", text_color="#2CC985")
        self.app.set_status("Settings saved")
