"""SQLite catalog for plugins, banks, presets, jobs, samples, and exports."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS plugins (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    developer TEXT DEFAULT '',
    version TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS banks (
    id INTEGER PRIMARY KEY,
    plugin_id INTEGER NOT NULL REFERENCES plugins(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    UNIQUE(plugin_id, name)
);
CREATE TABLE IF NOT EXISTS presets (
    id INTEGER PRIMARY KEY,
    bank_id INTEGER NOT NULL REFERENCES banks(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    category TEXT DEFAULT '',
    UNIQUE(bank_id, name)
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    job_id TEXT NOT NULL,
    preset_id INTEGER REFERENCES presets(id) ON DELETE SET NULL,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    error TEXT DEFAULT '',
    output_dir TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS samples (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    midi_note INTEGER NOT NULL,
    velocity INTEGER NOT NULL,
    round_robin INTEGER NOT NULL DEFAULT 0,
    duration_seconds REAL,
    peak_db REAL,
    loop_start INTEGER,
    loop_end INTEGER,
    qc_passed INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS exports (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    format TEXT NOT NULL,
    file_path TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_samples_run ON samples(run_id);
CREATE INDEX IF NOT EXISTS idx_runs_job ON runs(job_id);
"""


class Database:
    """Thin thread-safe wrapper. One connection, serialized by a lock —
    plenty for a desktop app writing a few rows per second."""

    def __init__(self, path: Path | str = ":memory:") -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._lock = threading.RLock()
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def _exec(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    # -- upserts ------------------------------------------------------

    def upsert_plugin(self, name: str, developer: str = "", version: str = "") -> int:
        self._exec(
            "INSERT INTO plugins(name, developer, version) VALUES(?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET developer=excluded.developer",
            (name, developer, version),
        )
        row = self._exec("SELECT id FROM plugins WHERE name=?", (name,)).fetchone()
        return int(row["id"])

    def upsert_bank(self, plugin_id: int, name: str) -> int:
        self._exec(
            "INSERT OR IGNORE INTO banks(plugin_id, name) VALUES(?,?)",
            (plugin_id, name),
        )
        row = self._exec(
            "SELECT id FROM banks WHERE plugin_id=? AND name=?", (plugin_id, name)
        ).fetchone()
        return int(row["id"])

    def upsert_preset(self, bank_id: int, name: str, category: str = "") -> int:
        self._exec(
            "INSERT OR IGNORE INTO presets(bank_id, name, category) VALUES(?,?,?)",
            (bank_id, name, category),
        )
        row = self._exec(
            "SELECT id FROM presets WHERE bank_id=? AND name=?", (bank_id, name)
        ).fetchone()
        return int(row["id"])

    # -- runs ---------------------------------------------------------

    def start_run(self, job_id: str, preset_id: int | None, output_dir: str) -> int:
        cur = self._exec(
            "INSERT INTO runs(job_id, preset_id, output_dir) VALUES(?,?,?)",
            (job_id, preset_id, output_dir),
        )
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, status: str, error: str = "") -> None:
        self._exec(
            "UPDATE runs SET status=?, error=?, finished_at=datetime('now') WHERE id=?",
            (status, error, run_id),
        )

    # -- samples ------------------------------------------------------

    def add_sample(
        self,
        run_id: int,
        file_path: str,
        midi_note: int,
        velocity: int,
        round_robin: int = 0,
        duration_seconds: float | None = None,
        peak_db: float | None = None,
        loop_start: int | None = None,
        loop_end: int | None = None,
        qc_passed: bool = True,
    ) -> int:
        cur = self._exec(
            "INSERT INTO samples(run_id, file_path, midi_note, velocity, round_robin,"
            " duration_seconds, peak_db, loop_start, loop_end, qc_passed)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                run_id, file_path, midi_note, velocity, round_robin,
                duration_seconds, peak_db, loop_start, loop_end, int(qc_passed),
            ),
        )
        return int(cur.lastrowid)

    def add_export(self, run_id: int, fmt: str, file_path: str) -> int:
        cur = self._exec(
            "INSERT INTO exports(run_id, format, file_path) VALUES(?,?,?)",
            (run_id, fmt, file_path),
        )
        return int(cur.lastrowid)

    # -- queries ------------------------------------------------------

    def samples_for_run(self, run_id: int) -> list[dict[str, Any]]:
        rows = self._exec(
            "SELECT * FROM samples WHERE run_id=? ORDER BY midi_note, velocity, round_robin",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def run_summary(self, run_id: int) -> dict[str, Any] | None:
        run = self._exec("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if run is None:
            return None
        counts = self._exec(
            "SELECT COUNT(*) AS total, SUM(qc_passed) AS passed FROM samples WHERE run_id=?",
            (run_id,),
        ).fetchone()
        return dict(run) | {
            "sample_count": counts["total"] or 0,
            "qc_passed_count": counts["passed"] or 0,
        }

    def recent_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._exec(
            "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
