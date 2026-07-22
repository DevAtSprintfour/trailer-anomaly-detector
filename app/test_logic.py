"""Tests for the CP-SAT trailer packer + blame. Run: python test_logic.py

Model note: each floor is packed against its REAL length (dance 129, general 483)
with the harness gap reserved both between items and against every chamber edge.
Items that overflow their floor are
flagged by floor severity: general-floor overflow -> FAIL, dance-floor overflow
-> AMBIGUOUS.
"""

import pandas as pd

from analysis import AMBIGUOUS, FAIL, PASS, RESOLVED, UNKNOWN, analyze, build_used_floors
from cp_packer import SIDE_DANCE, SIDE_GENERAL, CpPacker, PackItem
from floor_geom import container_for_geom

PK = CpPacker(time_limit=5.0)


def check(name, cond):
    print(f"[{'OK' if cond else 'FAIL'}] {name}")
    assert cond, name


def mk(rows):
    return pd.DataFrame(rows)


def row(rid, tid, tname, slot, eid, L, W, miss=False, desc=""):
    return dict(
        race_id=rid,
        trailer_id=tid,
        trailer_name=tname,
        trailer_view="Cup",
        slot=slot,
        equipment_id=eid,
        eq_length=(None if miss else L),
        eq_width=(None if miss else W),
        dims_missing=miss,
        equipment_desc=desc or f"e{eid}",
    )


# --- Container geometry ---
c = container_for_geom({})
check("default dance length", c.dance_length == 129.0)
check("default general length", c.general_length == 483.0)
check("default width", c.width == 98.0)
check("exclusion line at dance length", c.exclusion_x == 129.0)
check("total length is dance+general", c.total_length == 612.0)

# --- Packer basics (per floor) ---
check("empty container packs", PK.pack([], c).fits)
check("single item packs", PK.pack([PackItem(1, 40, 30, SIDE_GENERAL)], c).fits)

# pack_floor: the harness gap is reserved against the walls too, so an item must
# be at least one gap shorter than the floor on each axis. With gap=2 the 129
# floor admits up to 125; the full 129 no longer fits.
check(
    "item one gap shy of the floor fits",
    PK.pack_floor([PackItem(1, 125, 90)], 129, 98, 2).fits,
)
check(
    "floor-length item overflows (needs wall gap)",
    not PK.pack_floor([PackItem(1, 129, 90)], 129, 98, 2).fits,
)
check(
    "over-long item overflows its floor",
    not PK.pack_floor([PackItem(1, 140, 60)], 129, 98, 2).fits,
)
check("too-wide item overflows floor", not PK.pack_floor([PackItem(1, 120, 110)], 483, 98, 2).fits)

# Rotation toggle: a 55x95 item only fits a 100x60 floor if it may turn 90°.
check(
    "rotatable item fits when rotation allowed",
    PK.pack_floor([PackItem(1, 55, 95)], 100, 60, 0, allow_rotation=True).fits,
)
check(
    "same item overflows when rotation disallowed",
    not PK.pack_floor([PackItem(1, 55, 95)], 100, 60, 0, allow_rotation=False).fits,
)

# Container pack: dance item within 129 + general item within 483
check(
    "dance+general within their floors packs",
    PK.pack([PackItem(1, 120, 50, SIDE_DANCE), PackItem(2, 200, 40, SIDE_GENERAL)], c).fits,
)
# Two 400x90 can't both fit the 483 general floor (single-file 800 > 483)
check(
    "two long items overflow the general floor",
    not PK.pack([PackItem(1, 400, 90, SIDE_GENERAL), PackItem(2, 400, 90, SIDE_GENERAL)], c).fits,
)

# Best-effort keeps what fits, returns the overflow
be = PK.pack_best_effort([PackItem(9, 500, 40, SIDE_GENERAL), PackItem(8, 40, 30, SIDE_GENERAL)], c)
check("best-effort places the fitting item", 8 in [p.equipment_id for p in be.placements])
check("best-effort returns the overflow item", 9 in [u.equipment_id for u in be.unplaced])

# --- GENERAL overflow -> FAIL ---
v = analyze(mk([row(1, 9, "T-1", 5, 100, 500, 40, desc="too-long-general")]), gap=2, geom={})
check("general overflow -> FAIL", v[100]["status"] == FAIL and v[100]["kind"] == "general_overflow")

# --- DANCE overflow -> AMBIGUOUS ---
# Dance items may overhang the dividing line, so a 140-long one now fits; a dance
# item overflows only if it can't fit the WHOLE trailer (612 long).
v = analyze(mk([row(1, 9, "T-1", 1, 110, 700, 60, desc="too-long-dance")]), gap=2, geom={})
check(
    "dance overflow -> AMBIGUOUS",
    v[110]["status"] == AMBIGUOUS and v[110]["kind"] == "dance_overflow",
)
# A dance item that overhangs the line but fits the trailer -> PASS.
v = analyze(mk([row(1, 9, "T-1", 1, 111, 140, 60, desc="overhangs-but-fits")]), gap=2, geom={})
check("dance item overhanging the line still fits -> PASS", v[111]["status"] == PASS)

# --- Too-wide item on the general floor -> FAIL (overflows the floor) ---
v = analyze(mk([row(1, 9, "T-1", 5, 120, 120, 110, desc="too-wide")]), gap=2, geom={})
check("too-wide general item -> FAIL", v[120]["status"] == FAIL)

# --- Consistent items PASS ---
v = analyze(mk([row(1, 9, "T-1", 5, 101, 40, 30, desc="fine")]), gap=2, geom={})
check("consistent item -> PASS", v[101]["status"] == PASS)

v = analyze(mk([row(1, 9, "T-1", 5, 102, 400, 90, desc="long-but-fits")]), gap=2, geom={})
check("400-long general item fits the 483 floor -> PASS", v[102]["status"] == PASS)

# --- UNKNOWN ---
v = analyze(mk([row(3, 9, "T-3", 5, 400, None, None, miss=True)]), gap=2, geom={})
check("missing dims -> UNKNOWN", v[400]["status"] == UNKNOWN)

# --- Dance + general on the same trailer both fit ---
v = analyze(
    mk(
        [
            row(5, 9, "T-5", 1, 600, 100, 80, desc="dance"),
            row(5, 9, "T-5", 5, 601, 100, 80, desc="general"),
        ]
    ),
    gap=2,
    geom={},
)
check("dance and general both PASS", v[600]["status"] == PASS and v[601]["status"] == PASS)

# --- FAIL takes precedence over AMBIGUOUS across floors ---
v = analyze(
    mk(
        [
            row(6, 9, "T-6", 1, 700, 700, 60, desc="dance-overflow-here"),
            row(6, 20, "T-6b", 5, 700, 500, 40, desc="general-overflow-there"),
        ]
    ),
    gap=2,
    geom={},
)
check("general overflow beats dance overflow -> FAIL", v[700]["status"] == FAIL)

# --- Tunable geometry: lengthen the general floor so a long item fits ---
v = analyze(
    mk([row(7, 9, "T-7", 5, 800, 500, 40, desc="long")]),
    gap=2,
    geom=dict(dance_length=129, general_length=600, width=98),
)
check("longer general floor -> former overflow becomes PASS", v[800]["status"] == PASS)

# --- Trailer category classification ---
from trailer_categories import (  # noqa: E402
    CATEGORY_F_SERIES,
    CATEGORY_OTHER,
    CATEGORY_T_SERIES,
    CATEGORY_T_SERIES_TOP,
    DEFAULT_CATEGORY_GEOM,
    classify_trailer,
)

check("T-02 -> T-Series", classify_trailer("T-02") == CATEGORY_T_SERIES)
check("T-12 Top -> T-Series Top", classify_trailer("T-12 Top") == CATEGORY_T_SERIES_TOP)
check("F-10 -> F-Series", classify_trailer("F-10") == CATEGORY_F_SERIES)
check("01- Big -> Other", classify_trailer("01- Big") == CATEGORY_OTHER)
check(
    "every category has default geom",
    set(DEFAULT_CATEGORY_GEOM.keys())
    == {CATEGORY_T_SERIES, CATEGORY_T_SERIES_TOP, CATEGORY_F_SERIES, CATEGORY_OTHER},
)

# --- build_used_floors carries category + container ---
floors = build_used_floors(mk([row(9, 50, "T-09", 5, 1000, 400, 90, desc="a")]), geom={})
check("TrailerFloor has trailer_category", floors[0].trailer_category == CATEGORY_T_SERIES)
check("TrailerFloor has a container", floors[0].container.width == 98.0)

# --- Per-category geometry: narrow F-Series width -> general overflow -> FAIL ---
category_geom = {
    CATEGORY_T_SERIES: dict(dance_length=129.0, general_length=483.0, width=98.0),
    CATEGORY_F_SERIES: dict(dance_length=129.0, general_length=483.0, width=40.0),
}
v = analyze(
    mk([row(10, 60, "F-10", 5, 1001, 90, 60, desc="b")]),  # short 60 > 40 width -> overflow
    gap=2,
    geom={},
    category_geom=category_geom,
)
check("F-Series narrow width triggers FAIL via category_geom", v[1001]["status"] == FAIL)

# --- Verified equipment: a flagged item forced to RESOLVED ---
v = analyze(
    mk([row(20, 9, "T-20", 5, 302, 500, 40, desc="too-long-general")]),
    gap=2,
    geom={},
    verified={302},
)
check("verified item forced to RESOLVED", v[302]["status"] == RESOLVED)

# --- Dimension overrides: correcting an overflowing item makes it PASS ---
df3 = mk(
    [
        row(22, 9, "T-22", 5, 320, 500, 40, desc="too-long-general"),
        row(22, 9, "T-22", 7, 321, 40, 30, desc="ok"),
    ]
)
check("before override overflow is FAIL", analyze(df3, gap=2, geom={})[320]["status"] == FAIL)
v = analyze(df3, gap=2, geom={}, dim_overrides={320: (100.0, 40.0)})
check("dim override -> PASS", v[320]["status"] == PASS)
check("mate still PASS after override", v[321]["status"] == PASS)

# --- Checklist store (SQLite) ---
import os as _os  # noqa: E402
import tempfile  # noqa: E402

from checklist_store import ChecklistStore  # noqa: E402

_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
store = ChecklistStore(_tmp_db)
check("nothing verified initially", store.get_verified_ids() == set())
store.mark_verified(equipment_id=200, race_id=1, trailer_id=9, floor="general", note="checked")
check("mark_verified persists", 200 in store.get_verified_ids())
store2 = ChecklistStore(_tmp_db)
check("verification survives reopen", 200 in store2.get_verified_ids())
store2.unmark_verified(200)
check("unmark_verified removes it", 200 not in store2.get_verified_ids())
check("no corrections initially", store2.get_dimension_corrections() == {})
store2.set_dimension_correction(
    500, corrected_length=100, corrected_width=40, original_length=400, original_width=90
)
check("set_dimension_correction persists", store2.get_dimension_corrections()[500] == (100.0, 40.0))
store3 = ChecklistStore(_tmp_db)
check("corrections survive reopen", store3.get_dimension_corrections()[500] == (100.0, 40.0))
store3.clear_dimension_correction(500)
check("clear_dimension_correction removes it", 500 not in store3.get_dimension_corrections())
_os.unlink(_tmp_db)

# --- Packing diagram (matplotlib, plot.py style) ---
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

from packing_viz import TrailerRenderer  # noqa: E402

renderer = TrailerRenderer(packer=PK)
cont = container_for_geom({})
items = [
    PackItem(9001, 60, 38, SIDE_DANCE, "CTS1 TB Stack"),
    PackItem(9002, 200, 40, SIDE_GENERAL, "widget-a"),
    PackItem(9003, 200, 40, SIDE_GENERAL, "widget-b"),
]
fig = renderer.figure(cont, items, {})
check("figure is a matplotlib Figure", isinstance(fig, Figure))
boxes = [p for p in fig.axes[0].patches if isinstance(p, Rectangle)]
check("figure draws a box per item + container outline", len(boxes) >= 3 + 1)
labels = " ".join(t.get_text() for t in fig.axes[0].texts)
check(
    "figure labels include id/name/dims",
    "9001" in labels and "CTS1 TB Stack" in labels and ("60×38" in labels or "60x38" in labels),
)

# General overflow item comes back hatched
fig2 = renderer.figure(
    cont,
    [PackItem(9004, 500, 40, SIDE_GENERAL, "too-long"), PackItem(9005, 40, 30, SIDE_GENERAL, "ok")],
    {},
)
hatched = [p for p in fig2.axes[0].patches if isinstance(p, Rectangle) and p.get_hatch()]
check("general-overflow item is hatched", len(hatched) >= 1)

print("\nALL TESTS PASSED")
