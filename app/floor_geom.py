"""Trailer floor geometry + 2D packing. Pure functions, no I/O — unit-testable.

The trailer has two floors (not ten slots):
  - dance: slots 1–2 map here; one rectangle
  - general: slots 3–10 map here; one rectangle

Slot numbers on the load sheet only classify which floor an item rode on.
Packing is full 2D rectangle packing inside each floor with per-item 90°
rotation and a harness gap between items.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

DANCEFLOOR_SLOTS = {1, 2}
FLOOR_DANCE = "dance"
FLOOR_GENERAL = "general"

DIAGRAM = dict(
    dancefloor_length=129.0, dancefloor_total_width=98.0,
    general_length=483.0, general_total_width=98.0,
)

DEFAULT_GEOM = dict(
    dancefloor_length=DIAGRAM["dancefloor_length"],
    dancefloor_width=DIAGRAM["dancefloor_total_width"],
    general_length=DIAGRAM["general_length"],
    general_width=DIAGRAM["general_total_width"],
)


@dataclass
class FloorGeom:
    length: float
    width: float
    name: str  # 'dance' | 'general'


def floor_for_slot(slot: int) -> str:
    return FLOOR_DANCE if int(slot) in DANCEFLOOR_SLOTS else FLOOR_GENERAL


def floor_geometry(floor: str, geom: dict = None) -> FloorGeom:
    """geom is a full dance+general dict for ONE trailer category — callers
    resolve which category's geom to pass in (see trailer_categories.py)."""
    g = {**DEFAULT_GEOM, **(geom or {})}
    if floor == FLOOR_DANCE:
        return FloorGeom(g["dancefloor_length"], g["dancefloor_width"], FLOOR_DANCE)
    if floor == FLOOR_GENERAL:
        return FloorGeom(g["general_length"], g["general_width"], FLOOR_GENERAL)
    raise ValueError(f"unknown floor: {floor}")


@dataclass
class Item:
    equipment_id: int
    length: float
    width: float
    label: str = ""


@dataclass
class Placement:
    equipment_id: int
    x: float
    y: float
    w: float  # placed width (after rotation choice)
    h: float  # placed height (along length axis)


@dataclass
class PackResult:
    fits: bool
    placements: List[Placement] = field(default_factory=list)
    area_used: float = 0.0
    area_cap: float = 0.0
    area_overflow: float = 0.0  # max(0, area_used - area_cap) when no fit
    detail: str = ""


def _orientations(it: Item) -> List[Tuple[float, float]]:
    """Return unique (w, h) orientations. w along floor width, h along floor length."""
    opts = [(it.width, it.length), (it.length, it.width)]
    # de-dupe squares
    seen, out = set(), []
    for w, h in opts:
        key = (round(w, 6), round(h, 6))
        if key not in seen:
            seen.add(key)
            out.append((w, h))
    return out


def _inflate(w: float, h: float, gap: float) -> Tuple[float, float]:
    """Inflate by gap on the far edges so adjacent items keep gap between them.
    Packing into (W+gap) x (L+gap) makes edge gaps cancel — only inter-item gaps count.
    """
    return w + gap, h + gap


@dataclass
class _FreeRect:
    x: float
    y: float
    w: float
    h: float


def _fits_in(fr: _FreeRect, w: float, h: float) -> bool:
    return w <= fr.w + 1e-9 and h <= fr.h + 1e-9


def _score_bssf(fr: _FreeRect, w: float, h: float) -> Tuple[float, float]:
    """Best Short Side Fit: minimize leftover short side, then long side."""
    short = min(fr.w - w, fr.h - h)
    long = max(fr.w - w, fr.h - h)
    return (short, long)


def _prune_free(free: List[_FreeRect]) -> List[_FreeRect]:
    """Drop free rects fully contained in another."""
    kept: List[_FreeRect] = []
    for i, a in enumerate(free):
        contained = False
        for j, b in enumerate(free):
            if i == j:
                continue
            if (a.x >= b.x - 1e-9 and a.y >= b.y - 1e-9
                    and a.x + a.w <= b.x + b.w + 1e-9
                    and a.y + a.h <= b.y + b.h + 1e-9):
                contained = True
                break
        if not contained and a.w > 1e-9 and a.h > 1e-9:
            kept.append(a)
    return kept


def _try_pack_order(items: List[Item], bin_w: float, bin_h: float,
                    gap: float) -> Optional[List[Placement]]:
    """MaxRects-BSSF for one item order. bin is already inflated (W+gap, L+gap)."""
    free = [_FreeRect(0.0, 0.0, bin_w, bin_h)]
    placements: List[Placement] = []

    for it in items:
        best = None  # (score, fr_idx, x, y, w, h)  — w/h are inflated
        for fr_i, fr in enumerate(free):
            for ow, oh in _orientations(it):
                iw, ih = _inflate(ow, oh, gap)
                if not _fits_in(fr, iw, ih):
                    continue
                score = _score_bssf(fr, iw, ih)
                cand = (score, fr_i, fr.x, fr.y, iw, ih, ow, oh)
                if best is None or cand[0] < best[0]:
                    best = cand
        if best is None:
            return None
        _, fr_i, x, y, iw, ih, ow, oh = best
        placements.append(Placement(it.equipment_id, x, y, ow, oh))
        # split the chosen free rect; also punch the placed rect out of all free rects
        new_free: List[_FreeRect] = []
        for fr in free:
            # no overlap with placed inflated rect
            if (x + iw <= fr.x + 1e-9 or fr.x + fr.w <= x + 1e-9
                    or y + ih <= fr.y + 1e-9 or fr.y + fr.h <= y + 1e-9):
                new_free.append(fr)
                continue
            # overlap — split into up to 4 remainders (MaxRects)
            if x > fr.x + 1e-9:  # left
                new_free.append(_FreeRect(fr.x, fr.y, x - fr.x, fr.h))
            if x + iw < fr.x + fr.w - 1e-9:  # right
                new_free.append(_FreeRect(x + iw, fr.y, (fr.x + fr.w) - (x + iw), fr.h))
            if y > fr.y + 1e-9:  # below
                new_free.append(_FreeRect(fr.x, fr.y, fr.w, y - fr.y))
            if y + ih < fr.y + fr.h - 1e-9:  # above
                new_free.append(_FreeRect(fr.x, y + ih, fr.w, (fr.y + fr.h) - (y + ih)))
        free = _prune_free(new_free)
    return placements


def pack_floor(items: List[Item], length: float, width: float,
               gap: float = 2.0) -> PackResult:
    """2D-pack items into a floor rectangle (length × width).

    Rotation allowed. Harness gap is reserved between items (not beyond the
    floor edges). Returns fits=True if any tried order packs successfully.
    """
    area_cap = length * width
    if not items:
        return PackResult(True, [], 0.0, area_cap, 0.0, "empty")

    # Impossible if any single item can't fit even alone (either orientation).
    for it in items:
        alone_ok = any(ow <= width + 1e-9 and oh <= length + 1e-9
                       for ow, oh in _orientations(it))
        if not alone_ok:
            area_used = sum(it.length * it.width for it in items)
            return PackResult(
                False, [], area_used, area_cap,
                max(0.0, area_used - area_cap),
                f"item {it.equipment_id} ({it.length:.0f}×{it.width:.0f}) "
                f"cannot fit floor {length:.0f}×{width:.0f} alone",
            )

    area_used = sum(it.length * it.width for it in items)
    bin_w, bin_h = width + gap, length + gap

    # Try several sort orders — MaxRects quality depends on insertion order.
    orders = [
        sorted(items, key=lambda it: max(it.length, it.width), reverse=True),
        sorted(items, key=lambda it: it.length * it.width, reverse=True),
        sorted(items, key=lambda it: min(it.length, it.width), reverse=True),
        list(items),
    ]
    # de-dupe identical orders by equipment id sequence
    seen_orders, unique_orders = set(), []
    for ord_ in orders:
        key = tuple(it.equipment_id for it in ord_)
        if key not in seen_orders:
            seen_orders.add(key)
            unique_orders.append(ord_)

    for ord_ in unique_orders:
        placed = _try_pack_order(ord_, bin_w, bin_h, gap)
        if placed is not None:
            return PackResult(True, placed, area_used, area_cap, 0.0, "packed")

    return PackResult(
        False, [], area_used, area_cap,
        max(0.0, area_used - area_cap),
        "no feasible 2D packing",
    )
