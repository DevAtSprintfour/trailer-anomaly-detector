"""Analysis engine — LOAD SHEETS ARE THE SOURCE OF TRUTH.

Premise (from the user): if a slot was used on a load sheet, its equipment DID
fit. So every used slot is a *satisfied constraint* on the equipment's TRUE
sizes. We do NOT trust the stored dimensions; we test them against these
constraints. An equipment whose STORED size is bigger than what its tightest
successful slot could physically have allowed has a WRONG stored size -> anomaly.

Model (per orientation axis; we take the most-forgiving axis, i.e. rotation is
allowed):
  For a used slot with capacity L (along-slot) and width W:
    (a) every item's cross-dimension <= W                      (width constraint)
    (b) sum(item along-dimension) + (n-1)*gap <= L             (length constraint)
  These are KNOWN TRUE for the real sizes. We check whether the STORED sizes can
  satisfy them. If an item's stored size alone already breaks (a) or (b) in a way
  that can't be explained by anyone else, its stored size is the anomaly.

Inferred bound: for equipment e in slot s with capacity L and slot-mates M, the
most e's true along-dimension could be is  L - gap*(n-1) - sum(min possible of M).
Taking the *tightest* such bound across all of e's slots gives max_plausible[e].
If stored_along[e] > max_plausible[e] (beyond tolerance) -> stored size too big.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import pandas as pd

from geometry import Item, SlotGeom, slot_geometry

PASS = "PASS"
FAIL = "FAIL"
AMBIGUOUS = "AMBIGUOUS"
UNKNOWN = "UNKNOWN"


@dataclass
class UsedSlot:
    race_id: int
    trailer_id: int
    trailer_name: str
    view: str
    slot: int
    cap_length: float          # along-slot capacity (in)
    cap_width: float           # slot width (in)
    items: List[Item] = field(default_factory=list)   # items WITH usable dims
    n_total: int = 0           # total items assigned (incl. missing-dim ones)
    has_missing: bool = False


def _min_footprint(it: Item):
    """The smallest the item's along-slot dimension can be (its shorter side),
    given rotation is allowed. Used as the most-generous assumption about a
    slot-mate when bounding another item."""
    return min(it.length, it.width)


def _fits_axis(items, cap_len, cap_wid, gap):
    """Does this item set satisfy the length+width constraints on some axis?
    Rotation allowed per item. Returns (fits, best_used_len)."""
    best_used = None
    for axis in ("along_is_length", "along_is_width"):
        used = 0.0
        wid_ok = True
        for it in items:
            # (along, across) pairings
            opts = [(it.length, it.width), (it.width, it.length)]
            valid = [(a, c) for (a, c) in opts if c <= cap_wid + 1e-9]
            if not valid:
                wid_ok = False
                used += min(a for a, _ in opts)
            else:
                used += min(a for a, _ in valid)
        used += max(0, len(items) - 1) * gap
        if best_used is None or used < best_used:
            best_used = used
        if wid_ok and used <= cap_len + 1e-9:
            return True, used
    return False, best_used


def build_used_slots(df: pd.DataFrame, geom: dict) -> List[UsedSlot]:
    keys = ["race_id", "trailer_id", "trailer_name", "trailer_view", "slot"]
    slots = []
    for (race, tid, tname, view, slot), g in df.groupby(keys, sort=False):
        sg = slot_geometry(int(slot), geom)
        items, missing = [], False
        for _, r in g.iterrows():
            usable = (not r["dims_missing"] and pd.notna(r["eq_length"])
                      and pd.notna(r["eq_width"]) and r["eq_length"] > 0
                      and r["eq_width"] > 0)
            if usable:
                items.append(Item(int(r["equipment_id"]), float(r["eq_length"]),
                                  float(r["eq_width"]),
                                  str(r.get("equipment_desc") or r["equipment_id"])))
            else:
                missing = True
        slots.append(UsedSlot(int(race), int(tid), str(tname), str(view), int(slot),
                              sg.length, sg.width, items, len(g), missing))
    return slots


def analyze(df: pd.DataFrame, gap: float, geom: dict, tolerance: float = 0.0,
            cross_reference: bool = True) -> Dict[int, dict]:
    """Return {equipment_id: verdict dict}.

    An equipment is FLAGGED when its STORED size is inconsistent with a load sheet
    that is assumed to have worked:
      * width anomaly: its stored shorter side > the slot width of a slot it was
        used in (it could not have physically fit sideways either) — a slot that
        worked proves its true width <= slot width.
      * length anomaly: in a slot that worked, sum of stored along-dims exceeds
        capacity, AND this item is the one that can't be reconciled (uniquely the
        overflow driver) — its stored along-dim is too big vs its inferred bound.
    """
    slots = build_used_slots(df, geom)

    # Per-equipment: collect every slot it appears in, and the tightest inferred
    # upper bound on its along-slot footprint.
    appears: Dict[int, List[UsedSlot]] = {}
    for s in slots:
        for it in s.items:
            appears.setdefault(it.equipment_id, []).append(s)

    missing_ids = set(df.loc[df["dims_missing"], "equipment_id"].dropna().astype(int))
    eq_ids = set(df["equipment_id"].dropna().astype(int))

    # 1a) Single-item width: a used slot proves each item's true width <= total
    #     row width (a lone item may occupy the full width). If stored shorter-side
    #     exceeds even the full width, that stored dim is physically impossible.
    width_bad: Dict[int, dict] = {}

    def flag_width(eid, excess, **info):
        cur = width_bad.get(eid)
        if cur is None or excess > cur["excess"]:
            width_bad[eid] = dict(excess=round(excess, 1), **info)

    for s in slots:
        for it in s.items:
            short = min(it.length, it.width)
            if short > s.cap_width + tolerance:
                flag_width(it.equipment_id, short - s.cap_width, slot=s.slot,
                           race=s.race_id, trailer=s.trailer_name,
                           cap_width=s.cap_width, stored_short=short,
                           kind_detail="wider than the full trailer width")

    # 1b) Paired-column width: slots pair into rows (1&2, 3&4, ...) that SHARE the
    #     total width. When both columns of a row are occupied, the left and right
    #     items must fit side-by-side: min-side(left) + min-side(right) <= width.
    #     A used row proves this held for the true sizes, so if the STORED shorter
    #     sides overflow it, >=1 stored width is inflated. Unique blame: the item
    #     whose removal reconciles the pair.
    by_row: Dict[tuple, Dict[str, UsedSlot]] = {}
    for s in slots:
        row = (s.slot + 1) // 2                 # 1,2->1 ; 3,4->2 ; ...
        side = "L" if s.slot % 2 == 1 else "R"
        by_row.setdefault((s.race_id, s.trailer_id, s.trailer_name, row, s.cap_width),
                          {})[side] = s

    pair_ambiguous: set = set()
    for (race, tid, tname, row, cap_w), sides in by_row.items():
        if "L" not in sides or "R" not in sides:
            continue                            # lone column: covered by 1a
        left = [(it, min(it.length, it.width)) for it in sides["L"].items]
        right = [(it, min(it.length, it.width)) for it in sides["R"].items]
        if not left or not right:
            continue
        # widest item in each column defines the side-by-side footprint
        lmax_it, lmax = max(left, key=lambda x: x[1])
        rmax_it, rmax = max(right, key=lambda x: x[1])
        total = lmax + rmax
        if total <= cap_w + tolerance:
            continue                            # pair fits — consistent
        excess = total - cap_w
        # Which side is the culprit? The side whose width alone already exceeds the
        # full trailer width can't be right; the other side is exonerable.
        left_over = lmax > cap_w + tolerance    # left too wide even alone
        right_over = rmax > cap_w + tolerance
        info = dict(slot=None, race=race, trailer=tname, cap_width=cap_w,
                    kind_detail=f"paired row {row}: {lmax:.0f}+{rmax:.0f} > {cap_w:.0f}")
        if cross_reference and left_over and not right_over:
            flag_width(lmax_it.equipment_id, lmax - cap_w, stored_short=lmax, **info)
        elif cross_reference and right_over and not left_over:
            flag_width(rmax_it.equipment_id, rmax - cap_w, stored_short=rmax, **info)
        else:
            # both fit alone but not together (either could be inflated), or both
            # exceed alone -> can't uniquely blame one -> ambiguous pair.
            pair_ambiguous.add(lmax_it.equipment_id)
            pair_ambiguous.add(rmax_it.equipment_id)

    # 2) Length anomalies via reconciliation. For each used slot whose STORED sizes
    #    overflow capacity, try to attribute. A slot that worked means the true
    #    sizes DID fit, so an overflow of stored sizes means >=1 stored size is
    #    inflated. Unique culprit = the single item whose removal makes stored
    #    sizes fit (mirrors: its stored along-dim exceeds its inferred bound).
    length_bad: Dict[int, dict] = {}
    ambiguous: set = set()
    # Items already proven wrong independently (width anomaly) can absorb blame for
    # a shared-slot overflow, exonerating innocent slot-mates.
    known_bad = set(width_bad)
    for s in slots:
        if len(s.items) == 0:
            continue
        fits, used = _fits_axis(s.items, s.cap_length, s.cap_width, gap)
        if fits:
            continue
        # stored sizes overflow a slot that (in reality) worked -> anomaly here.
        # find items whose removal individually resolves the length overflow
        resolvers = []
        for it in s.items:
            rest = [x for x in s.items if x.equipment_id != it.equipment_id]
            rfits, _ = _fits_axis(rest, s.cap_length, s.cap_width, gap)
            if rfits:
                resolvers.append(it.equipment_id)
        overflow = round((used or 0) - s.cap_length, 1)
        info = dict(slot=s.slot, race=s.race_id, trailer=s.trailer_name,
                    overflow=overflow, n_items=len(s.items), cap_length=s.cap_length)

        # Cross-reference: if exactly one resolver is already a known-bad item,
        # attribute the overflow to it (it's the demonstrable cause) — this
        # exonerates the innocent slot-mates instead of marking everyone ambiguous.
        known_resolvers = [e for e in resolvers if e in known_bad]

        if not cross_reference:
            for it in s.items:
                ambiguous.add(it.equipment_id)
        elif len(resolvers) == 1:
            eid = resolvers[0]
            cur = length_bad.get(eid)
            if cur is None or overflow > cur["overflow"]:
                length_bad[eid] = info
        elif len(known_resolvers) == 1:
            # multiple removals fix it, but only one is independently proven bad
            # -> pin blame there, exonerate the rest.
            eid = known_resolvers[0]
            cur = length_bad.get(eid)
            if cur is None or overflow > cur["overflow"]:
                length_bad[eid] = info
        else:
            # can't separate (symmetric, or no single removal fixes it, or several
            # known-bad candidates) -> whole group ambiguous.
            for it in s.items:
                ambiguous.add(it.equipment_id)

    # Merge paired-column ambiguity, then let definite anomalies win over ambiguous.
    ambiguous |= pair_ambiguous
    definite = set(width_bad) | set(length_bad)
    ambiguous -= definite

    verdict: Dict[int, dict] = {}
    for eid in eq_ids:
        eid = int(eid)
        n_slots = len(appears.get(eid, []))
        if eid in width_bad:
            wb = width_bad[eid]
            where = (f"slot {wb['slot']}" if wb.get("slot") is not None
                     else wb.get("kind_detail", "a paired row"))
            verdict[eid] = dict(
                status=FAIL, unique=True, kind="width",
                reason=(f"stored width {wb['stored_short']:.0f}in can't fit {where} "
                        f"(width {wb['cap_width']:.0f}in), but the load sheet shows it fit "
                        f"→ stored width is wrong"),
                excess_in=wb["excess"], worst_slot=wb, slots_used=n_slots)
        elif eid in length_bad:
            lb = length_bad[eid]
            verdict[eid] = dict(
                status=FAIL, unique=True, kind="length",
                reason=(f"in slot {lb['slot']} the stored sizes overflow by "
                        f"{lb['overflow']:.0f}in and only this item's removal resolves it, "
                        f"but the load sheet shows the set fit → its stored length is wrong"),
                excess_in=lb["overflow"], worst_slot=lb, slots_used=n_slots)
        elif eid in ambiguous:
            verdict[eid] = dict(
                status=AMBIGUOUS, unique=False, kind="group",
                reason="stored sizes of a shared slot overflow but blame can't be pinned to one item",
                excess_in=None, worst_slot=None, slots_used=n_slots)
        elif eid in missing_ids:
            verdict[eid] = dict(
                status=UNKNOWN, unique=False, kind="missing",
                reason="missing/zero stored dimensions — cannot verify against load sheets",
                excess_in=None, worst_slot=None, slots_used=n_slots)
        else:
            verdict[eid] = dict(
                status=PASS, unique=False, kind="consistent",
                reason="stored dimensions are consistent with every load sheet it appears in",
                excess_in=0.0, worst_slot=None, slots_used=n_slots)
    return verdict


def summarize(verdict: Dict[int, dict]) -> Dict[str, int]:
    counts = {PASS: 0, FAIL: 0, AMBIGUOUS: 0, UNKNOWN: 0}
    for v in verdict.values():
        counts[v["status"]] += 1
    return counts
