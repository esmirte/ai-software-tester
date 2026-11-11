"""Persistência de execuções em SQLite."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any


class RunRepository:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._conn()) as c, c:
            c.execute("""CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
                label TEXT, project TEXT, total INTEGER, passed INTEGER, failed INTEGER,
                pass_rate REAL, duration REAL, data TEXT NOT NULL)""")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def save(self, run: dict[str, Any]) -> int:
        s = run["summary"]
        with closing(self._conn()) as c, c:
            cur = c.execute(
                "INSERT INTO runs (created_at,label,project,total,passed,failed,pass_rate,duration,data) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (run["created_at"], run.get("label", ""), run.get("project", ""), s["total"], s["passed"],
                 s["failed"] + s["errors"], s["pass_rate"], s["duration"], json.dumps(run, default=str)))
            return int(cur.lastrowid)

    def list_runs(self, limit: int = 200) -> list[dict[str, Any]]:
        with closing(self._conn()) as c:
            rows = c.execute("SELECT id,created_at,label,project,total,passed,failed,pass_rate,duration "
                             "FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def get(self, run_id: int) -> dict[str, Any] | None:
        with closing(self._conn()) as c:
            row = c.execute("SELECT data FROM runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            return None
        data = json.loads(row["data"])
        data["id"] = run_id
        return data

    @staticmethod
    def now() -> str:
        return datetime.now().isoformat(timespec="seconds")
