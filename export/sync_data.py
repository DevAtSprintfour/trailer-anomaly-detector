#!/usr/bin/env python3
"""Refresh the committed data/*.csv snapshots from the two production databases.

Sources (read-only):
  - Champschedule (PostgreSQL): races, trailers, and the race->trailer->slot->
    equipment assignments (``champschedule_raceequipment`` with ``sheet_type IS NULL``,
    i.e. the trailer load sheet — not the separate load_in / load_out sheets).
  - WMS / MODX (MySQL): equipment physical dimensions, keyed by equipment id.

The load sheet is raceequipment LEFT JOINed to WMS equipment on equipment_id, so
equipment with no WMS record still appears (dims_found=False, dims_missing=True).

Credentials come from the repo-root .env (gitignored). This whole directory is
gitignored; only the resulting data/*.csv snapshots are committed.

Usage:  uv run python export/sync_data.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import psycopg2
import pymysql

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
YEAR = 2026


def _env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in (ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def _trailer_view(is_awning, cup_equipment, nxs_equipment) -> str:
    # Priority Awning -> Cup -> NOAPS (verified against the committed snapshot).
    if is_awning:
        return "Awning"
    if cup_equipment:
        return "Cup"
    if nxs_equipment:
        return "NOAPS"
    return ""


def main() -> None:
    env = _env()

    # ---- Champschedule (PostgreSQL) -------------------------------------
    pg = psycopg2.connect(
        host=env["DB_HOST"],
        dbname=env["DB_NAME"],
        user=env["DB_USER"],
        password=env["DB_PASSWORD"],
        port=int(env.get("DB_PORT", 5432)),
        connect_timeout=10,
    )

    races = pd.read_sql(
        """
        SELECT r.id   AS race_id,
               r.year AS race_year,
               r.mec_date AS race_date,
               l.location_name AS race_name
        FROM champschedule_race r
        LEFT JOIN champschedule_location l ON r.race_location_id = l.id
        WHERE r.year = %(year)s
        ORDER BY r.mec_date, r.id
        """,
        pg,
        params={"year": YEAR},
    )

    # Trailer load sheet: sheet_type IS NULL (excludes load_in / load_out sheets).
    base = pd.read_sql(
        """
        SELECT re.id           AS assignment_id,
               re.race_id      AS race_id,
               r.year          AS race_year,
               r.mec_date      AS race_date,
               re.trailer_id   AS trailer_id,
               t.name          AS trailer_name,
               t.is_awning     AS is_awning,
               t.cup_equipment AS cup_equipment,
               t.nxs_equipment AS nxs_equipment,
               re.position     AS slot,
               re.equipment_id AS equipment_id,
               re.is_loaded    AS is_loaded,
               l.location_name AS race_name
        FROM champschedule_raceequipment re
        JOIN champschedule_race r    ON re.race_id = r.id
        JOIN champschedule_trailer t ON re.trailer_id = t.id
        LEFT JOIN champschedule_location l ON r.race_location_id = l.id
        WHERE r.year = %(year)s
          AND re.sheet_type IS NULL
        ORDER BY re.race_id, re.trailer_id, re.position, re.id
        """,
        pg,
        params={"year": YEAR},
    )
    pg.close()

    # ---- WMS / MODX (MySQL): equipment dimensions -----------------------
    wms = pymysql.connect(
        host=env["WMS_HOST"],
        user=env["WMS_USER"],
        password=env["WMS_PWD"],
        database=env["WMS_NAME"],
        port=int(env.get("WMS_PORT", 3306)),
        connect_timeout=10,
    )
    equip = pd.read_sql(
        """
        SELECT id           AS equipment_id,
               serial_number,
               description  AS equipment_desc,
               type_id,
               CAST(length AS SIGNED) AS eq_length,
               CAST(width  AS SIGNED) AS eq_width,
               CAST(height AS SIGNED) AS eq_height,
               CAST(weight AS SIGNED) AS eq_weight,
               dancefloor_restricted,
               load_position,
               status_code
        FROM wms_equipment
        """,
        wms,
    )
    wms.close()
    equip["serial_number"] = equip["serial_number"].replace("", pd.NA)
    equip["load_position"] = equip["load_position"].replace("", pd.NA)

    # ---- Load sheet: LEFT JOIN assignments -> WMS equipment -------------
    found_ids = set(equip["equipment_id"])
    ls = base.merge(equip, on="equipment_id", how="left")
    ls["trailer_view"] = [
        _trailer_view(a, c, n)
        for a, c, n in zip(ls["is_awning"], ls["cup_equipment"], ls["nxs_equipment"], strict=True)
    ]
    ls["dims_found"] = ls["equipment_id"].isin(found_ids)
    ls["dims_missing"] = ~((ls["eq_length"] > 0) & (ls["eq_width"] > 0) & (ls["eq_height"] > 0))

    loadsheet = ls[
        [
            "assignment_id",
            "race_id",
            "race_year",
            "race_date",
            "trailer_id",
            "trailer_name",
            "trailer_view",
            "is_awning",
            "slot",
            "equipment_id",
            "is_loaded",
            "serial_number",
            "equipment_desc",
            "type_id",
            "eq_length",
            "eq_width",
            "eq_height",
            "eq_weight",
            "dancefloor_restricted",
            "load_position",
            "status_code",
            "dims_found",
            "dims_missing",
            "race_name",
        ]
    ]

    # ---- Derived snapshots ---------------------------------------------
    trailers = (
        ls[
            [
                "trailer_id",
                "trailer_name",
                "trailer_view",
                "is_awning",
                "cup_equipment",
                "nxs_equipment",
            ]
        ]
        .drop_duplicates("trailer_id")
        .rename(columns={"trailer_name": "name"})
        .sort_values("trailer_id")
    )

    slots = (
        ls.groupby(
            ["race_id", "trailer_id", "trailer_name", "trailer_view", "slot"],
            dropna=False,
        )
        .size()
        .reset_index(name="items_in_slot")
        .sort_values(["race_id", "trailer_id", "slot"])
    )

    equipment = (
        ls[
            [
                "equipment_id",
                "serial_number",
                "equipment_desc",
                "eq_length",
                "eq_width",
                "eq_height",
                "eq_weight",
                "dancefloor_restricted",
                "dims_found",
                "dims_missing",
            ]
        ]
        .drop_duplicates("equipment_id")
        .sort_values("equipment_id")
    )

    # ---- Write ----------------------------------------------------------
    outputs = {
        "races_2026.csv": races,
        "trailers_2026.csv": trailers,
        "slots_2026.csv": slots,
        "equipment_2026.csv": equipment,
        "loadsheet_2026.csv": loadsheet,
    }
    for name, df in outputs.items():
        df.to_csv(DATA / name, index=False)
        print(f"wrote {name:22s} {len(df):6d} rows")


if __name__ == "__main__":
    main()
