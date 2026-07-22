"""Settings view — read-only in v0.1, editable in v0.2."""
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

        ctk.CTkLabel(
            self,
            text="Live settings.json snapshot. Editable in v0.2.",
            text_color="gray",
        ).grid(row=1, column=0, padx=24, pady=(0, 16), sticky="w")

        textbox = ctk.CTkTextbox(self, wrap="none", font=ctk.CTkFont(family="Courier New", size=12))
        textbox.grid(row=2, column=0, padx=24, pady=(0, 24), sticky="nsew")
        textbox.insert("1.0", json.dumps(app.config_obj.as_dict(), indent=4))
        textbox.configure(state="disabled")
