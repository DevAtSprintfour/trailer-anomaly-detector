"""SQLite-backed checklist store for manually-verified equipment.

Lets a user mark an equipment_id (in the context of a specific race/trailer/
floor) as verified — meaning they physically confirmed the stored dimensions
are correct despite the analyzer flagging it FAIL/AMBIGUOUS. Verified items
are excluded from blame candidacy on the next analyze() run (see analysis.py).

Persisted at data/checklist.db by default so it survives Streamlit reruns
and app restarts.
"""
from __future__ import annotations

import sqlite3
from typing import Dict, List, Set


_SCHEMA = """
CREATE TABLE IF NOT EXISTS verification (
    equipment_id INTEGER NOT NULL,
    race_id INTEGER NOT NULL,
    trailer_id INTEGER NOT NULL,
    floor TEXT NOT NULL,
    note TEXT DEFAULT '',
    verified_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (equipment_id, race_id, trailer_id, floor)
);
"""


class ChecklistStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(_SCHEMA)
            conn.commit()
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def mark_verified(self, equipment_id: int, race_id: int, trailer_id: int,
                      floor: str, note: str = "") -> None:
        conn = self._connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO verification "
                "(equipment_id, race_id, trailer_id, floor, note, verified_at) "
                "VALUES (?, ?, ?, ?, ?, datetime('now'))",
                (equipment_id, race_id, trailer_id, floor, note),
            )
            conn.commit()
        finally:
            conn.close()

    def unmark_verified(self, equipment_id: int, race_id: int = None,
                        trailer_id: int = None, floor: str = None) -> None:
        """Remove verification. If race/trailer/floor are omitted, remove ALL
        verification rows for this equipment_id (used by the UI's blanket
        'un-verify' action)."""
        conn = self._connect()
        try:
            if race_id is None and trailer_id is None and floor is None:
                conn.execute("DELETE FROM verification WHERE equipment_id = ?",
                            (equipment_id,))
            else:
                conn.execute(
                    "DELETE FROM verification WHERE equipment_id = ? AND "
                    "race_id = ? AND trailer_id = ? AND floor = ?",
                    (equipment_id, race_id, trailer_id, floor),
                )
            conn.commit()
        finally:
            conn.close()

    def get_verified_ids(self) -> Set[int]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT DISTINCT equipment_id FROM verification").fetchall()
            return {int(r["equipment_id"]) for r in rows}
        finally:
            conn.close()

    def list_records(self) -> List[Dict]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT equipment_id, race_id, trailer_id, floor, note, verified_at "
                "FROM verification ORDER BY verified_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
