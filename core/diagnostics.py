"""One-file diagnostics bundle for remote debugging."""
from __future__ import annotations

import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from core.env_check import run_checks
from reaper.plugin_scanner import scan_reaper_plugins

_LOG_FILE = Path(__file__).resolve().parent.parent / "logs" / "app.log"
_LOG_TAIL_LINES = 150


def build_report(config, app_version: str) -> str:
    lines = [
        "=== VST Sampling Factory diagnostics ===",
        f"generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"app version: {app_version}",
        f"python: {sys.version}",
        f"platform: {platform.platform()}",
        "",
        "--- setup checks ---",
    ]
    for check in run_checks(config):
        status = "OK " if check.ok else "FAIL"
        lines.append(f"[{status}] {check.label}: {check.detail}")
        if not check.ok and check.fix:
            lines.append(f"       fix: {check.fix}")

    plugins = scan_reaper_plugins()
    lines += ["", f"--- detected instruments ({len(plugins)}) ---"]
    lines += [f"  {p.display_name}" for p in plugins[:80]]
    if len(plugins) > 80:
        lines.append(f"  ... and {len(plugins) - 80} more")

    lines += ["", "--- settings ---", json.dumps(config.as_dict(), indent=2)]

    lines += ["", f"--- last {_LOG_TAIL_LINES} log lines ---"]
    if _LOG_FILE.exists():
        try:
            log_lines = _LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
            lines += log_lines[-_LOG_TAIL_LINES:]
        except OSError as exc:
            lines.append(f"(could not read log: {exc})")
    else:
        lines.append("(no log file yet)")

    return "\n".join(lines) + "\n"


def save_report(config, app_version: str) -> Path:
    out = _LOG_FILE.parent / "diagnostics.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_report(config, app_version), encoding="utf-8")
    return out
