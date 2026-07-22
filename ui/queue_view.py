"""Queue view — placeholder in v0.1, wired in v0.2."""
from __future__ import annotations

import customtkinter as ctk


class QueueView(ctk.CTkFrame):
    def __init__(self, master, app) -> None:
        super().__init__(master, corner_radius=0)
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            self, text="Queue", font=ctk.CTkFont(size=24, weight="bold")
        ).grid(row=0, column=0, padx=24, pady=(24, 8), sticky="w")

        ctk.CTkLabel(
            self,
            text="Add, reorder, pause, and resume render jobs.",
            text_color="gray",
        ).grid(row=1, column=0, padx=24, pady=(0, 24), sticky="w")

        empty = ctk.CTkFrame(self)
        empty.grid(row=2, column=0, padx=24, pady=24, sticky="nsew")
        empty.grid_columnconfigure(0, weight=1)
        empty.grid_rowconfigure(0, weight=1)
        ctk.CTkLabel(
            empty, text="No jobs queued.", text_color="gray"
        ).grid(row=0, column=0)
