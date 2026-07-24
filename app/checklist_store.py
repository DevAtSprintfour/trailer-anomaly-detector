"""SQLite-backed checklist store: verification + dimension corrections.

Verification: mark an equipment_id (in a race/trailer/floor context) as
physically confirmed correct despite FAIL/AMBIGUOUS — excluded from blame.

Dimension corrections: override stored WMS L×W for an equipment_id. These
feed reprocessing immediately and export as a downloadable list of WMS
changes. Persisted at data/checklist.db.
"""

from __future__ import annotations

import os
import sqlite3

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
CREATE TABLE IF NOT EXISTS dimension_correction (
    equipment_id INTEGER PRIMARY KEY,
    corrected_length REAL NOT NULL,
    corrected_width REAL NOT NULL,
    original_length REAL,
    original_width REAL,
    note TEXT DEFAULT '',
    corrected_at TEXT DEFAULT (datetime('now'))
);
"""


class ChecklistStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        # On a fresh deploy (e.g. Streamlit Cloud) the data/ dir may not exist,
        # and sqlite3 can't create the file in a missing directory.
        parent = os.path.dirname(os.path.abspath(self.db_path))
        os.makedirs(parent, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def mark_verified(
        self, equipment_id: int, race_id: int, trailer_id: int, floor: str, note: str = ""
    ) -> None:
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

    def unmark_verified(
        self,
        equipment_id: int,
        race_id: int | None = None,
        trailer_id: int | None = None,
        floor: str | None = None,
    ) -> None:
        """Remove verification. If race/trailer/floor are omitted, remove ALL
        verification rows for this equipment_id (used by the UI's blanket
        'un-verify' action)."""
        conn = self._connect()
        try:
            if race_id is None and trailer_id is None and floor is None:
                conn.execute("DELETE FROM verification WHERE equipment_id = ?", (equipment_id,))
            else:
                conn.execute(
                    "DELETE FROM verification WHERE equipment_id = ? AND "
                    "race_id = ? AND trailer_id = ? AND floor = ?",
                    (equipment_id, race_id, trailer_id, floor),
                )
            conn.commit()
        finally:
            conn.close()

    def get_verified_ids(self) -> set[int]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT DISTINCT equipment_id FROM verification").fetchall()
            return {int(r["equipment_id"]) for r in rows}
        finally:
            conn.close()

    def list_records(self) -> list[dict]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT equipment_id, race_id, trailer_id, floor, note, verified_at "
                "FROM verification ORDER BY verified_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def set_dimension_correction(
        self,
        equipment_id: int,
        corrected_length: float,
        corrected_width: float,
        original_length: float | None = None,
        original_width: float | None = None,
        note: str = "",
    ) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO dimension_correction "
                "(equipment_id, corrected_length, corrected_width, "
                " original_length, original_width, note, corrected_at) "
                "VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
                (
                    equipment_id,
                    corrected_length,
                    corrected_width,
                    original_length,
                    original_width,
                    note,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def clear_dimension_correction(self, equipment_id: int) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "DELETE FROM dimension_correction WHERE equipment_id = ?",
                (equipment_id,),
            )
            conn.commit()
        finally:
            conn.close()

    def get_dimension_corrections(self) -> dict[int, tuple[float, float]]:
        """Return {equipment_id: (corrected_length, corrected_width)}."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT equipment_id, corrected_length, corrected_width FROM dimension_correction"
            ).fetchall()
            return {
                int(r["equipment_id"]): (float(r["corrected_length"]), float(r["corrected_width"]))
                for r in rows
            }
        finally:
            conn.close()

    def list_dimension_corrections(self) -> list[dict]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT equipment_id, corrected_length, corrected_width, "
                "original_length, original_width, note, corrected_at "
                "FROM dimension_correction ORDER BY corrected_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
