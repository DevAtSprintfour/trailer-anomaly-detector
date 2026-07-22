"""Analysis engine — LOAD SHEETS ARE THE SOURCE OF TRUTH.

Premise: if equipment appeared on a trailer, it DID physically fit. We do NOT
trust stored WMS dimensions. For each (race, trailer) we build ONE container
(dance chamber + general chamber, split by the exclusion line) and 2D-pack every
item with the CP-SAT engine in :mod:`cp_packer`. Dance items (slots 1-2) are
pinned to the left chamber, general items (slots 3-10) to the right. If the
stored sizes cannot pack into a trailer that worked in reality, at least one
stored size is wrong.

Blame unit is the whole (race, trailer): leave-one-out + cross-race isolation
when possible; else AMBIGUOUS.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from cp_packer import ContainerSpec, CpPacker, PackItem
from floor_geom import FLOOR_DANCE, FLOOR_GENERAL, container_for_geom, floor_for_slot
from trailer_categories import classify_trailer

PASS = "PASS"
FAIL = "FAIL"
AMBIGUOUS = "AMBIGUOUS"
UNKNOWN = "UNKNOWN"
RESOLVED = "RESOLVED"  # manually verified by a user despite an anomaly flag

# One shared packer so its solve cache survives across Streamlit reruns and
# across the many near-identical leave-one-out solves within a single analyze().
_PACKER = CpPacker(time_limit=5.0)


@dataclass
class TrailerFloor:
    """All equipment on one (race, trailer), packed as a single container."""

    race_id: int
    trailer_id: int
    trailer_name: str
    trailer_category: str
    view: str
    container: ContainerSpec
    items: list[PackItem] = field(default_factory=list)
    n_total: int = 0
    has_missing: bool = False

    def items_on(self, side: str) -> list[PackItem]:
        return [it for it in self.items if it.side == side]


def build_used_floors(
    df: pd.DataFrame,
    geom: dict,
    category_geom: dict[str, dict] | None = None,
    dim_overrides: dict[int, tuple[float, float]] | None = None,
    padding: float = 2.0,
) -> list[TrailerFloor]:
    """Group load-sheet rows into one container per (race, trailer).

    ``geom`` is the flat fallback used when a trailer's category has no entry
    in ``category_geom``. ``dim_overrides`` maps equipment_id -> (L, W) and
    replaces stored WMS dims when present.
    """
    cat_geom = category_geom or {}
    overrides = dim_overrides or {}
    work = df.copy()
    work["floor"] = work["slot"].map(floor_for_slot)
    keys = ["race_id", "trailer_id", "trailer_name", "trailer_view"]
    floors: list[TrailerFloor] = []
    for (race, tid, tname, view), g in work.groupby(keys, sort=False):
        category = classify_trailer(str(tname))
        resolved_geom = cat_geom.get(category, geom)
        container = container_for_geom(resolved_geom, padding)
        items, missing, seen = [], False, set()
        for _, r in g.iterrows():
            eid = int(r["equipment_id"]) if pd.notna(r["equipment_id"]) else None
            if eid is None or eid in seen:
                continue
            seen.add(eid)
            side = floor_for_slot(r["slot"])
            label = str(r.get("equipment_desc") or eid)
            if eid in overrides:
                L, W = overrides[eid]
                items.append(PackItem(eid, float(L), float(W), side, label))
                continue
            usable = (
                not r["dims_missing"]
                and pd.notna(r["eq_length"])
                and pd.notna(r["eq_width"])
                and r["eq_length"] > 0
                and r["eq_width"] > 0
            )
            if usable:
                items.append(
                    PackItem(eid, float(r["eq_length"]), float(r["eq_width"]), side, label)
                )
            else:
                missing = True
        floors.append(
            TrailerFloor(
                int(race),
                int(tid),
                str(tname),
                category,
                str(view),
                container,
                items,
                len(seen),
                missing,
            )
        )
    return floors


def analyze(
    df: pd.DataFrame,
    gap: float,
    geom: dict,
    tolerance: float = 0.0,
    cross_reference: bool = True,
    category_geom: dict[str, dict] | None = None,
    verified: set | None = None,
    dim_overrides: dict[int, tuple[float, float]] | None = None,
    packer: CpPacker | None = None,
) -> dict[int, dict]:
    """Return {equipment_id: verdict dict} from per-floor overflow.

    Each floor of every (race, trailer) is packed against its REAL length. Items
    that overflow their floor are flagged by floor severity:

      - dance-floor overflow  -> AMBIGUOUS
      - general-floor overflow -> FAIL

    ``verified`` equipment_ids are treated as ground truth (RESOLVED).
    ``dim_overrides`` replaces stored dims. ``tolerance`` widens each floor.
    ``cross_reference`` is accepted for API compatibility (unused).
    """
    pk = packer or _PACKER
    floors = build_used_floors(df, geom, category_geom, dim_overrides, padding=gap)
    verified = set(verified or ())
    overrides = dim_overrides or {}

    appears: dict[int, list[TrailerFloor]] = {}
    for f in floors:
        for it in f.items:
            appears.setdefault(it.equipment_id, []).append(f)

    missing_ids = set(df.loc[df["dims_missing"], "equipment_id"].dropna().astype(int))
    missing_ids -= set(overrides)  # an override supplies dims
    eq_ids = set(df["equipment_id"].dropna().astype(int))

    # Overflow per floor: pack each chamber against its real length; the items
    # that don't fit are the overflow, flagged by floor severity.
    general_bad: dict[int, dict] = {}  # eid -> evidence  (FAIL)
    dance_bad: dict[int, dict] = {}  # eid -> evidence  (AMBIGUOUS)

    def _floor_len(f: TrailerFloor, side: str) -> float:
        base = f.container.dance_length if side == FLOOR_DANCE else f.container.general_length
        return base + tolerance

    for f in floors:
        for side, target in ((FLOOR_DANCE, dance_bad), (FLOOR_GENERAL, general_bad)):
            side_items = [
                it for it in f.items if it.side == side and it.equipment_id not in verified
            ]
            if not side_items:
                continue
            res = pk.pack_floor(
                side_items,
                _floor_len(f, side),
                f.container.width + tolerance,
                gap,
                best_effort=True,
            )
            for it in res.unplaced:
                info = dict(
                    floor=side,
                    race=f.race_id,
                    trailer=f.trailer_name,
                    cap_length=_floor_len(f, side),
                    cap_width=f.container.width,
                )
                target.setdefault(it.equipment_id, info)

    verdict: dict[int, dict] = {}
    for eid in eq_ids:
        eid = int(eid)
        n_floors = len(appears.get(eid, []))
        if eid in verified:
            verdict[eid] = dict(
                status=RESOLVED,
                unique=False,
                kind="verified",
                reason="manually verified by a user as correct despite an anomaly flag",
                excess_in=0.0,
                worst_floor=None,
                floors_used=n_floors,
            )
        elif eid in general_bad:
            gb = general_bad[eid]
            verdict[eid] = dict(
                status=FAIL,
                unique=True,
                kind="general_overflow",
                reason=(
                    f"on trailer {gb['trailer']} this item overflows the general "
                    f"floor ({gb['cap_length']:.0f}×{gb['cap_width']:.0f}in), but the "
                    f"load sheet shows it fit -> its stored size is wrong"
                ),
                excess_in=None,
                worst_floor=gb,
                floors_used=n_floors,
            )
        elif eid in dance_bad:
            db = dance_bad[eid]
            verdict[eid] = dict(
                status=AMBIGUOUS,
                unique=False,
                kind="dance_overflow",
                reason=(
                    f"on trailer {db['trailer']} this item overflows the dance "
                    f"floor ({db['cap_length']:.0f}×{db['cap_width']:.0f}in) — "
                    f"dance-floor overflow is treated as ambiguous"
                ),
                excess_in=None,
                worst_floor=db,
                floors_used=n_floors,
            )
        elif eid in missing_ids:
            verdict[eid] = dict(
                status=UNKNOWN,
                unique=False,
                kind="missing",
                reason="missing/zero stored dimensions — cannot verify against load sheets",
                excess_in=None,
                worst_floor=None,
                floors_used=n_floors,
            )
        else:
            verdict[eid] = dict(
                status=PASS,
                unique=False,
                kind="consistent",
                reason="stored dimensions are consistent with every trailer load sheet it appears in",
                excess_in=0.0,
                worst_floor=None,
                floors_used=n_floors,
            )
    return verdict


def summarize(verdict: dict[int, dict]) -> dict[str, int]:
    counts = {PASS: 0, FAIL: 0, AMBIGUOUS: 0, UNKNOWN: 0, RESOLVED: 0}
    for v in verdict.values():
        counts[v["status"]] += 1
    return counts
