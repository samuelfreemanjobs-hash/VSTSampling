"""Dashboard view — system status and quick actions."""
from __future__ import annotations

import customtkinter as ctk


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

        self._card(cards, 0, "CPU", "—")
        self._card(cards, 1, "RAM", "—")
        self._card(cards, 2, "Queue", "0 jobs")
        self._card(cards, 3, "Disk", "—")

        placeholder = ctk.CTkFrame(self)
        placeholder.grid(row=3, column=0, padx=24, pady=24, sticky="nsew")
        self.grid_rowconfigure(3, weight=1)
        placeholder.grid_columnconfigure(0, weight=1)
        placeholder.grid_rowconfigure(0, weight=1)
        ctk.CTkLabel(
            placeholder,
            text=(
                "v0.1 shell.\n\n"
                "Queue manager, Reaper integration, and rendering pipeline\n"
                "arrive in the v0.2 → v0.5 milestones."
            ),
            justify="center",
            text_color="gray",
        ).grid(row=0, column=0)

    def _card(self, parent, col: int, label: str, value: str) -> None:
        card = ctk.CTkFrame(parent, height=80)
        card.grid(row=0, column=col, padx=6, sticky="ew")
        ctk.CTkLabel(card, text=label, text_color="gray").pack(padx=12, pady=(10, 0), anchor="w")
        ctk.CTkLabel(
            card, text=value, font=ctk.CTkFont(size=20, weight="bold")
        ).pack(padx=12, pady=(0, 10), anchor="w")
