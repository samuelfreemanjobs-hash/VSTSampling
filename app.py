"""VST Sampling Factory — desktop application entry point.

v0.1 milestone: navigation shell + status bar. No rendering yet.
"""
from __future__ import annotations

import sys
from pathlib import Path

import customtkinter as ctk

from core.config import Config
from core.logger import get_logger
from core.queue_manager import QueueManager
from ui.dashboard import DashboardView
from ui.queue_view import QueueView
from ui.banks_view import BanksView
from ui.settings_view import SettingsView
from ui.reports_view import ReportsView

APP_TITLE = "VST Sampling Factory"
APP_VERSION = "1.1.2"
ROOT_DIR = Path(__file__).parent
CONFIG_PATH = ROOT_DIR / "settings.json"

log = get_logger(__name__)


class App(ctk.CTk):
    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config_obj = config
        self.queue = QueueManager(save_path=ROOT_DIR / "database" / "queue.json")
        self.queue.load()

        ctk.set_appearance_mode(config.get("ui.theme", "dark"))
        ctk.set_default_color_theme(config.get("ui.color_theme", "blue"))

        self.title(f"{APP_TITLE}  v{APP_VERSION}")
        self.geometry("1200x760")
        self.minsize(1000, 640)

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_content_area()
        self._build_status_bar()

        self._views: dict[str, ctk.CTkFrame] = {}
        self._register_views()
        self.show_view("dashboard")

    def _build_sidebar(self) -> None:
        self.sidebar = ctk.CTkFrame(self, width=200, corner_radius=0)
        self.sidebar.grid(row=0, column=0, rowspan=2, sticky="nsew")
        self.sidebar.grid_rowconfigure(7, weight=1)

        title = ctk.CTkLabel(
            self.sidebar,
            text="VST Sampling\nFactory",
            font=ctk.CTkFont(size=18, weight="bold"),
            justify="left",
        )
        title.grid(row=0, column=0, padx=20, pady=(20, 24), sticky="w")

        self._nav_buttons: dict[str, ctk.CTkButton] = {}
        for row, (key, label) in enumerate(
            [
                ("dashboard", "Dashboard"),
                ("queue", "Queue"),
                ("banks", "Banks"),
                ("reports", "Reports"),
                ("settings", "Settings"),
            ],
            start=1,
        ):
            btn = ctk.CTkButton(
                self.sidebar,
                text=label,
                anchor="w",
                height=36,
                command=lambda k=key: self.show_view(k),
            )
            btn.grid(row=row, column=0, padx=12, pady=4, sticky="ew")
            self._nav_buttons[key] = btn

        version_label = ctk.CTkLabel(
            self.sidebar,
            text=f"v{APP_VERSION}",
            font=ctk.CTkFont(size=11),
            text_color="gray",
        )
        version_label.grid(row=8, column=0, padx=20, pady=(0, 16), sticky="sw")

    def _build_content_area(self) -> None:
        self.content = ctk.CTkFrame(self, corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

    def _build_status_bar(self) -> None:
        self.status_bar = ctk.CTkFrame(self, height=28, corner_radius=0)
        self.status_bar.grid(row=1, column=1, sticky="ew")
        self.status_bar.grid_columnconfigure(0, weight=1)

        self.status_text = ctk.CTkLabel(
            self.status_bar,
            text="Ready",
            font=ctk.CTkFont(size=12),
            anchor="w",
        )
        self.status_text.grid(row=0, column=0, padx=12, sticky="w")

        self.queue_status = ctk.CTkLabel(
            self.status_bar,
            text="Queue: idle",
            font=ctk.CTkFont(size=12),
            anchor="e",
        )
        self.queue_status.grid(row=0, column=1, padx=12, sticky="e")

    def _register_views(self) -> None:
        for key, cls in [
            ("dashboard", DashboardView),
            ("queue", QueueView),
            ("banks", BanksView),
            ("reports", ReportsView),
            ("settings", SettingsView),
        ]:
            view = cls(self.content, app=self)
            view.grid(row=0, column=0, sticky="nsew")
            self._views[key] = view

    def show_view(self, key: str) -> None:
        view = self._views.get(key)
        if view is None:
            log.warning("Unknown view: %s", key)
            return
        view.tkraise()
        self.set_status(f"{key.title()} view")

    def set_status(self, text: str) -> None:
        self.status_text.configure(text=text)

    def set_queue_status(self, text: str) -> None:
        self.queue_status.configure(text=text)

    def start_queue(self) -> None:
        if getattr(self, "_runner", None) and self._runner.is_running:
            self.set_status("Queue already running")
            return
        if self.queue.next_pending() is None:
            self.set_status(
                "Queue is empty — fill in the plugin row and click 'Add Job' first, "
                "then Start Queue"
            )
            return
        try:
            from core.pipeline import PipelineRunner

            self._runner = PipelineRunner(self.queue, self.config_obj)
            self._runner.start()
        except Exception as exc:  # noqa: BLE001 — surface any startup failure to the user
            log.exception("Could not start queue")
            self.set_status(f"Could not start queue: {exc}")
            return
        self.set_status("Queue started")


def main() -> int:
    config = Config.load(CONFIG_PATH)
    log.info("Starting %s v%s", APP_TITLE, APP_VERSION)
    app = App(config)
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
