"""Setup health checks shown on the Dashboard."""
from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from reaper.plugin_scanner import scan_reaper_plugins
from reaper.reaper_controller import find_reaper


@dataclass
class CheckResult:
    label: str
    ok: bool
    detail: str
    fix: str = ""


def run_checks(config) -> list[CheckResult]:
    results: list[CheckResult] = []

    reaper = find_reaper(config.get("reaper_path", ""))
    if reaper:
        results.append(CheckResult("Reaper", True, str(reaper)))
    else:
        results.append(
            CheckResult(
                "Reaper", False, "reaper.exe not found",
                "Install Reaper, or set 'reaper_path' in the Settings tab to the "
                "full path of reaper.exe",
            )
        )

    plugins = scan_reaper_plugins()
    if plugins:
        results.append(
            CheckResult("VST instruments", True, f"{len(plugins)} instruments found")
        )
    else:
        results.append(
            CheckResult(
                "VST instruments", False, "Reaper's plugin cache not found",
                "Open Reaper once so it scans your plugins "
                "(Options > Preferences > Plug-ins > VST > Re-scan), then re-check",
            )
        )

    out_dir = Path(config.get("output_dir", "output"))
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=out_dir):
            pass
        free_gb = shutil.disk_usage(out_dir).free / 1e9
        if free_gb < 2:
            results.append(
                CheckResult(
                    "Output folder", False, f"only {free_gb:.1f} GB free",
                    "Free up disk space or point 'output_dir' at a bigger drive",
                )
            )
        else:
            results.append(
                CheckResult("Output folder", True, f"{out_dir} ({free_gb:.0f} GB free)")
            )
    except OSError as exc:
        results.append(
            CheckResult(
                "Output folder", False, f"cannot write to {out_dir}: {exc}",
                "Change 'output_dir' in the Settings tab to a folder you can write to",
            )
        )

    return results
