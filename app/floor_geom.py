"""Trailer geometry: slot -> floor/side classification and container specs.

The trailer is a SINGLE container laid along its length axis, split by an
exclusion line into a dance chamber (front) and a general chamber (rear).
Slot numbers only classify which chamber a piece of equipment rode in:

  - dance   : slots 1-2  -> left chamber  (front `dance_length` inches)
  - general : slots 3-10 -> right chamber (rear `general_length` inches)

Both chambers share one interior `width`. The actual 2D packing lives in
:mod:`cp_packer` (OR-Tools CP-SAT); this module only turns a geometry dict
into a :class:`ContainerSpec`.
"""

from __future__ import annotations

from cp_packer import (  # re-exported so callers have one geometry import
    SIDE_DANCE,
    SIDE_GENERAL,
    ContainerSpec,
)

DANCEFLOOR_SLOTS = {1, 2}
FLOOR_DANCE = SIDE_DANCE
FLOOR_GENERAL = SIDE_GENERAL

# Physical defaults (inches). Width is the shared interior width of the trailer.
DEFAULT_GEOM = dict(
    dance_length=129.0,
    general_length=483.0,
    width=98.0,
)

DEFAULT_PADDING = 2.0


def floor_for_slot(slot: int) -> str:
    """Map a load-sheet slot number to its floor/chamber side."""
    return FLOOR_DANCE if int(slot) in DANCEFLOOR_SLOTS else FLOOR_GENERAL


# ``side_for_slot`` reads better where the exclusion-line side is meant.
side_for_slot = floor_for_slot


def container_for_geom(geom: dict | None = None, padding: float = DEFAULT_PADDING) -> ContainerSpec:
    """Build a :class:`ContainerSpec` from a (partial) geometry dict.

    ``geom`` may hold ``dance_length`` / ``general_length`` / ``width`` plus the
    optional rotation flags ``dance_rotation`` / ``general_rotation``; anything
    missing falls back to :data:`DEFAULT_GEOM` (rotation defaults to True).
    """
    g = {**DEFAULT_GEOM, **(geom or {})}
    return ContainerSpec(
        dance_length=float(g["dance_length"]),
        general_length=float(g["general_length"]),
        width=float(g["width"]),
        padding=float(padding),
        dance_rotation=bool(g.get("dance_rotation", True)),
        general_rotation=bool(g.get("general_rotation", True)),
    )
