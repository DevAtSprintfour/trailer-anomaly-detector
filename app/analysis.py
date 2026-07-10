"""Analysis engine — LOAD SHEETS ARE THE SOURCE OF TRUTH.

Premise: if equipment appeared on a load sheet floor, it DID physically fit on
that floor. We do NOT trust stored WMS dimensions. We pool every item that rode
on the dance floor (slots 1–2) into one bin and every item on the general floor
(slots 3–10) into another, then 2D-pack each bin. If stored sizes cannot pack
into a floor that worked in reality, at least one stored size is wrong.

Blame: leave-one-out + cross-race isolation when possible; else AMBIGUOUS.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import pandas as pd

from floor_geom import Item, floor_for_slot, floor_geometry, pack_floor

PASS = "PASS"
FAIL = "FAIL"
AMBIGUOUS = "AMBIGUOUS"
UNKNOWN = "UNKNOWN"


@dataclass
class UsedFloor:
    race_id: int
    trailer_id: int
    trailer_name: str
    view: str
    floor: str                 # 'dance' | 'general'
    cap_length: float
    cap_width: float
    items: List[Item] = field(default_factory=list)
    n_total: int = 0
    has_missing: bool = False


def build_used_floors(df: pd.DataFrame, geom: dict) -> List[UsedFloor]:
    """Group load-sheet rows into (race, trailer, floor) bins."""
    work = df.copy()
    work["floor"] = work["slot"].map(floor_for_slot)
    keys = ["race_id", "trailer_id", "trailer_name", "trailer_view", "floor"]
    floors: List[UsedFloor] = []
    for (race, tid, tname, view, floor), g in work.groupby(keys, sort=False):
        fg = floor_geometry(str(floor), geom)
        items, missing = [], False
        # One row per equipment_id on this floor (dedupe if multi-slot noise)
        seen = set()
        for _, r in g.iterrows():
            eid = int(r["equipment_id"]) if pd.notna(r["equipment_id"]) else None
            if eid is None or eid in seen:
                continue
            seen.add(eid)
            usable = (not r["dims_missing"] and pd.notna(r["eq_length"])
                      and pd.notna(r["eq_width"]) and r["eq_length"] > 0
                      and r["eq_width"] > 0)
            if usable:
                items.append(Item(eid, float(r["eq_length"]), float(r["eq_width"]),
                                  str(r.get("equipment_desc") or eid)))
            else:
                missing = True
        floors.append(UsedFloor(
            int(race), int(tid), str(tname), str(view), str(floor),
            fg.length, fg.width, items, len(seen), missing,
        ))
    return floors


def _floor_fits(items: List[Item], cap_len: float, cap_wid: float, gap: float) -> bool:
    return pack_floor(items, cap_len, cap_wid, gap).fits


def analyze(df: pd.DataFrame, gap: float, geom: dict, tolerance: float = 0.0,
            cross_reference: bool = True) -> Dict[int, dict]:
    """Return {equipment_id: verdict dict} using floor-level 2D packing."""
    floors = build_used_floors(df, geom)

    appears: Dict[int, List[UsedFloor]] = {}
    for f in floors:
        for it in f.items:
            appears.setdefault(it.equipment_id, []).append(f)

    missing_ids = set(df.loc[df["dims_missing"], "equipment_id"].dropna().astype(int))
    eq_ids = set(df["equipment_id"].dropna().astype(int))

    # 1) Single-item width: shorter side > floor width → impossible.
    width_bad: Dict[int, dict] = {}

    def flag_width(eid, excess, **info):
        cur = width_bad.get(eid)
        if cur is None or excess > cur["excess"]:
            width_bad[eid] = dict(excess=round(excess, 1), **info)

    for f in floors:
        for it in f.items:
            short = min(it.length, it.width)
            if short > f.cap_width + tolerance:
                flag_width(
                    it.equipment_id, short - f.cap_width,
                    floor=f.floor, race=f.race_id, trailer=f.trailer_name,
                    cap_width=f.cap_width, stored_short=short,
                    kind_detail=f"wider than the {f.floor} floor width",
                )

    # 2) Floor packing overflow + leave-one-out blame.
    pack_bad: Dict[int, dict] = {}
    ambiguous: set = set()
    known_bad = set(width_bad)

    for f in floors:
        if len(f.items) == 0:
            continue
        result = pack_floor(f.items, f.cap_length, f.cap_width, gap)
        if result.fits:
            continue

        resolvers = []
        for it in f.items:
            rest = [x for x in f.items if x.equipment_id != it.equipment_id]
            if _floor_fits(rest, f.cap_length, f.cap_width, gap):
                resolvers.append(it.equipment_id)

        # Prefer area overflow; fall back to a nominal 1.0 so UI has a number.
        overflow = round(result.area_overflow, 1) if result.area_overflow > 0 else 1.0
        info = dict(
            floor=f.floor, race=f.race_id, trailer=f.trailer_name,
            overflow=overflow, n_items=len(f.items),
            cap_length=f.cap_length, cap_width=f.cap_width,
            detail=result.detail,
        )
        known_resolvers = [e for e in resolvers if e in known_bad]

        if not cross_reference:
            for it in f.items:
                ambiguous.add(it.equipment_id)
        elif len(f.items) == 1:
            eid = f.items[0].equipment_id
            # alone and doesn't pack → already caught as width, or too long
            if eid not in width_bad:
                cur = pack_bad.get(eid)
                if cur is None or overflow > cur["overflow"]:
                    pack_bad[eid] = info
        elif len(resolvers) == 1:
            eid = resolvers[0]
            cur = pack_bad.get(eid)
            if cur is None or overflow > cur["overflow"]:
                pack_bad[eid] = info
            known_bad.add(eid)
        elif len(known_resolvers) == 1:
            eid = known_resolvers[0]
            cur = pack_bad.get(eid)
            if cur is None or overflow > cur["overflow"]:
                pack_bad[eid] = info
        else:
            for it in f.items:
                ambiguous.add(it.equipment_id)

    definite = set(width_bad) | set(pack_bad)
    ambiguous -= definite

    verdict: Dict[int, dict] = {}
    for eid in eq_ids:
        eid = int(eid)
        n_floors = len(appears.get(eid, []))
        if eid in width_bad:
            wb = width_bad[eid]
            floor = wb.get("floor", "floor")
            verdict[eid] = dict(
                status=FAIL, unique=True, kind="width",
                reason=(f"stored width {wb['stored_short']:.0f}in can't fit the "
                        f"{floor} floor (width {wb['cap_width']:.0f}in), but the "
                        f"load sheet shows it fit → stored width is wrong"),
                excess_in=wb["excess"],
                worst_floor=wb, floors_used=n_floors,
            )
        elif eid in pack_bad:
            pb = pack_bad[eid]
            verdict[eid] = dict(
                status=FAIL, unique=True, kind="pack",
                reason=(f"on the {pb['floor']} floor the stored sizes cannot 2D-pack "
                        f"into {pb['cap_length']:.0f}×{pb['cap_width']:.0f}in and only "
                        f"this item's removal resolves it, but the load sheet shows "
                        f"the set fit → its stored size is wrong"),
                excess_in=pb["overflow"],
                worst_floor=pb, floors_used=n_floors,
            )
        elif eid in ambiguous:
            verdict[eid] = dict(
                status=AMBIGUOUS, unique=False, kind="group",
                reason=("stored sizes of a shared floor overflow but blame can't "
                        "be pinned to one item"),
                excess_in=None, worst_floor=None, floors_used=n_floors,
            )
        elif eid in missing_ids:
            verdict[eid] = dict(
                status=UNKNOWN, unique=False, kind="missing",
                reason="missing/zero stored dimensions — cannot verify against load sheets",
                excess_in=None, worst_floor=None, floors_used=n_floors,
            )
        else:
            verdict[eid] = dict(
                status=PASS, unique=False, kind="consistent",
                reason="stored dimensions are consistent with every floor load sheet it appears in",
                excess_in=0.0, worst_floor=None, floors_used=n_floors,
            )
    return verdict


def summarize(verdict: Dict[int, dict]) -> Dict[str, int]:
    counts = {PASS: 0, FAIL: 0, AMBIGUOUS: 0, UNKNOWN: 0}
    for v in verdict.values():
        counts[v["status"]] += 1
    return counts


# Back-compat for anything still importing the old name
build_used_slots = build_used_floors
