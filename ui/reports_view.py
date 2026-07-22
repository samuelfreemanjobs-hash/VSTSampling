"""Reports view — placeholder in v0.1."""
from __future__ import annotations

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

        ctk.CTkLabel(
            self,
            text="Render summaries and QC reports. Populated in v0.5.",
            text_color="gray",
        ).grid(row=1, column=0, padx=24, pady=(0, 24), sticky="w")
