"""Compatibility shim — prefer `floor_geom`.

Streamlit Cloud / older imports used `geometry`; that name can collide with
third-party packages and stale deploys. All symbols live in `floor_geom`.
"""
from floor_geom import (  # noqa: F401
    DANCEFLOOR_SLOTS,
    DEFAULT_GEOM,
    DIAGRAM,
    FLOOR_DANCE,
    FLOOR_GENERAL,
    FloorGeom,
    Item,
    PackResult,
    Placement,
    floor_for_slot,
    floor_geometry,
    pack_floor,
    slot_geometry,
)
