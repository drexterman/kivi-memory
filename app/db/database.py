from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "kivi.sqlite3"
SCHEMA_PATH = ROOT / "database" / "schema.sql"


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_database() -> None:
    with get_connection() as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()


def reset_database() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
    initialize_database()


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    if "metadata" in result and isinstance(result["metadata"], str):
        try:
            result["metadata"] = json.loads(result["metadata"])
        except json.JSONDecodeError:
            pass
    return result


def migrate_phase4_evidence_judge() -> None:
    with get_connection() as conn:
        columns={row[1] for row in conn.execute("PRAGMA table_info(answer_runs)").fetchall()}
        if "evidence_verdict" not in columns:
            conn.execute("ALTER TABLE answer_runs ADD COLUMN evidence_verdict TEXT NOT NULL DEFAULT 'UNSUPPORTED'")
        if "evidence_reason" not in columns:
            conn.execute("ALTER TABLE answer_runs ADD COLUMN evidence_reason TEXT NOT NULL DEFAULT 'Legacy answer run'")
        conn.commit()
