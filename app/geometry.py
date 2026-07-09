"""Trailer geometry + slot-fit math. Pure functions, no I/O — unit-testable.

The trailer has two columns of slots. Slots 1 & 2 are the dancefloor; 3-10 are
general floor. Each slot occupies one column, so its usable width is the
column width (total trailer width / 2).
"""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# Diagram totals ("T-25 Mechanix '25", inches). The diagram gives the dancefloor
# and general areas as a TOTAL length and a TOTAL width spanning two columns.
DANCEFLOOR_SLOTS = {1, 2}
DIAGRAM = dict(
    dancefloor_length=120.0, dancefloor_total_width=96.0,
    general_length=480.0, general_total_width=98.0,
)

# DEFAULT_GEOM holds the USABLE per-slot dimensions the fit math consumes. The
# defaults are the even-split reading of the diagram (each slot = one column,
# so width = total/2). Every value here is independently tunable from the UI.
DEFAULT_GEOM = dict(
    dancefloor_length=DIAGRAM["dancefloor_length"],
    dancefloor_width=DIAGRAM["dancefloor_total_width"] / 2.0,   # even-split default
    general_length=DIAGRAM["general_length"],
    general_width=DIAGRAM["general_total_width"] / 2.0,         # even-split default
)


@dataclass
class SlotGeom:
    length: float          # usable length along the slot (inches)
    width: float           # usable width of the slot (inches)


def slot_geometry(slot: int, geom: dict = None) -> SlotGeom:
    """Return usable (length, width) for a slot number.

    `geom` may supply any of dancefloor_length/dancefloor_width/general_length/
    general_width to override the even-split diagram defaults.
    """
    g = {**DEFAULT_GEOM, **(geom or {})}
    if slot in DANCEFLOOR_SLOTS:
        return SlotGeom(g["dancefloor_length"], g["dancefloor_width"])
    return SlotGeom(g["general_length"], g["general_width"])


@dataclass
class Item:
    equipment_id: int
    length: float
    width: float
    label: str = ""


@dataclass
class FitResult:
    fits: bool
    orientation: str            # 'lengthwise' | 'widthwise' | 'none'
    used: float                 # packed dimension along slot length (in)
    capacity: float             # slot length available (in)
    overflow: float             # max(0, used - capacity) for the best arrangement
    width_violation: bool       # an item too wide for the slot even rotated
    detail: str = ""


def _pack_along(items: List[Item], slot: SlotGeom, gap: float,
                axis: str) -> Tuple[bool, float, bool]:
    """Try to lay items in a single row along the slot length.

    axis='lengthwise': each item contributes its length to the running total and
      its width must fit the slot width (item may rotate to achieve this).
    axis='widthwise' : the roles swap (item contributes its width to the total,
      its length must fit the slot width).
    Per-item rotation is allowed: for each item we pick the orientation that (a)
    satisfies the cross-dimension cap and (b) minimizes the along-slot dimension.
    Returns (all_widths_ok, total_along + gaps, any_width_violation).
    """
    n = len(items)
    total = 0.0
    width_violation = False
    for it in items:
        # The two possible (along, across) pairings for this item.
        opts = [(it.length, it.width), (it.width, it.length)]
        if axis == "widthwise":
            opts = [(it.width, it.length), (it.length, it.width)]
        # Keep orientations whose across-dimension fits the slot width.
        valid = [(along, across) for (along, across) in opts if across <= slot.width]
        if not valid:
            width_violation = True
            # still count its smaller along-dim so overflow is meaningful
            total += min(along for along, _ in opts)
        else:
            total += min(along for along, _ in valid)
    total += max(0, n - 1) * gap
    return (not width_violation), total, width_violation


def evaluate_slot(items: List[Item], slot: SlotGeom, gap: float) -> FitResult:
    """Best-of-both-orientations fit for a set of items sharing one slot."""
    if not items:
        return FitResult(True, "none", 0.0, slot.length, 0.0, False, "empty")

    best = None
    for axis in ("lengthwise", "widthwise"):
        widths_ok, used, wviol = _pack_along(items, slot, gap, axis)
        overflow = max(0.0, used - slot.length)
        fits = widths_ok and overflow <= 1e-9
        cand = FitResult(fits, axis, used, slot.length, overflow, wviol)
        # Prefer a fitting arrangement; else the one with least overflow.
        if best is None:
            best = cand
        elif cand.fits and not best.fits:
            best = cand
        elif cand.fits == best.fits and cand.overflow < best.overflow:
            best = cand
    return best
