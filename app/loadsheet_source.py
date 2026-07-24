"""Read the 2026 trailer load sheet directly from the production databases.

Sources (read-only):
  - Champschedule (PostgreSQL): races, trailers, and the race->trailer->slot->
    equipment assignments (``champschedule_raceequipment`` with ``sheet_type IS NULL``,
    i.e. the trailer load sheet — not the separate load_in / load_out sheets).
  - WMS / MODX (MySQL): equipment physical dimensions, keyed by equipment id.

The load sheet is raceequipment LEFT JOINed to WMS equipment on equipment_id, so
equipment with no WMS record still appears (dims_found=False, dims_missing=True).

Credentials are resolved from ``st.secrets`` first (Streamlit Cloud), then the
repo-root ``.env`` (local dev). Keys:
  DB_HOST, DB_NAME, DB_USER, DB_PASSWORD, DB_PORT     (Postgres / Champschedule)
  WMS_HOST, WMS_NAME, WMS_USER, WMS_PWD, WMS_PORT     (MySQL / WMS)
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import psycopg2
import pymysql

ROOT = Path(__file__).resolve().parent.parent
YEAR = 2026

_REQUIRED_KEYS = (
    "DB_HOST",
    "DB_NAME",
    "DB_USER",
    "DB_PASSWORD",
    "WMS_HOST",
    "WMS_NAME",
    "WMS_USER",
    "WMS_PWD",
)


def _env_file() -> dict[str, str]:
    """Parse the repo-root .env (returns {} if it doesn't exist)."""
    env: dict[str, str] = {}
    path = ROOT / ".env"
    if not path.exists():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def _config() -> dict[str, str]:
    """Resolve DB config from st.secrets first, then the repo-root .env.

    st.secrets is preferred so the deployed app works without a checked-in .env;
    the .env fallback keeps local dev working with the existing file.
    """
    env: dict[str, str] = {}
    try:
        import streamlit as st

        # Accessing st.secrets raises if no secrets file/config exists; guard it.
        env = {str(k): str(v) for k, v in dict(st.secrets).items()}
    except Exception:
        env = {}
    if not all(env.get(k) for k in _REQUIRED_KEYS):
        # Missing or partial secrets — fall back to .env, letting .env fill gaps.
        env = {**_env_file(), **{k: v for k, v in env.items() if v}}
    missing = [k for k in _REQUIRED_KEYS if not env.get(k)]
    if missing:
        raise RuntimeError(
            "Missing database credentials: "
            + ", ".join(missing)
            + ". Set them in .streamlit/secrets.toml or the repo-root .env."
        )
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


def fetch_loadsheet() -> pd.DataFrame:
    """Return the 2026 load sheet, read live from Postgres + MySQL.

    24 columns incl. race_name — the schema the rest of the app expects.
    """
    env = _config()

    # ---- Champschedule (PostgreSQL) -------------------------------------
    pg = psycopg2.connect(
        host=env["DB_HOST"],
        dbname=env["DB_NAME"],
        user=env["DB_USER"],
        password=env["DB_PASSWORD"],
        port=int(env.get("DB_PORT") or 5432),
        connect_timeout=10,
    )
    try:
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
    finally:
        pg.close()

    # ---- WMS / MODX (MySQL): equipment dimensions -----------------------
    wms = pymysql.connect(
        host=env["WMS_HOST"],
        user=env["WMS_USER"],
        password=env["WMS_PWD"],
        database=env["WMS_NAME"],
        port=int(env.get("WMS_PORT") or 3306),
        connect_timeout=10,
    )
    try:
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
    finally:
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

    return ls[
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
