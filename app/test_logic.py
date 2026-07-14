"""Tests for floor-level 2D packing + blame. Run: python test_logic.py"""
import pandas as pd
from floor_geom import floor_geometry, pack_floor, Item, FLOOR_DANCE, FLOOR_GENERAL
from analysis import analyze, PASS, FAIL, AMBIGUOUS, UNKNOWN


def check(name, cond):
    print(f"[{'OK' if cond else 'FAIL'}] {name}")
    assert cond, name


def mk(rows):
    return pd.DataFrame(rows)


def row(rid, tid, tname, view, slot, eid, L, W, miss=False, desc=""):
    return dict(race_id=rid, trailer_id=tid, trailer_name=tname, trailer_view=view,
                slot=slot, equipment_id=eid,
                eq_length=(None if miss else L), eq_width=(None if miss else W),
                dims_missing=miss, equipment_desc=desc or f"e{eid}")


# --- Floor geometry ---
dance = floor_geometry(FLOOR_DANCE)
check("dance floor", (dance.length, dance.width) == (129.0, 98.0))
gen = floor_geometry(FLOOR_GENERAL)
check("general floor", (gen.length, gen.width) == (483.0, 98.0))

# --- Packer: empty / single item ---
r = pack_floor([], 100, 50, gap=2)
check("empty floor packs", r.fits)

r = pack_floor([Item(1, 40, 30)], 100, 50, gap=2)
check("single item packs", r.fits)

r = pack_floor([Item(1, 200, 200)], 100, 50, gap=2)
check("oversized alone fails", not r.fits)

# Two items side-by-side with rotation on a small floor
r = pack_floor([Item(1, 40, 30), Item(2, 40, 30)], length=50, width=80, gap=2)
check("two items 2D-pack with rotation", r.fits)

# --- WIDTH anomaly: shorter side 110 > floor width 98 ---
df = mk([row(1, 9, "T-1", "Cup", 5, 100, 120, 110, desc="too-wide")])
v = analyze(df, gap=2, geom={}, cross_reference=True)
check("width anomaly -> FAIL unique", v[100]["status"] == FAIL and v[100]["kind"] == "width")

df = mk([row(1, 9, "T-1", "Cup", 5, 101, 40, 30, desc="fine")])
v = analyze(df, gap=2, geom={}, cross_reference=True)
check("consistent item -> PASS", v[101]["status"] == PASS)

# --- PACK anomaly with unique blame: oversized item (500>483 alone) + small mate.
#     Only removing the oversized one resolves the floor; removing the small one
#     still leaves the oversized item which cannot pack alone.
df = mk([row(1, 9, "T-1", "Cup", 5, 200, 500, 90, desc="oversized"),
         row(1, 9, "T-1", "Cup", 7, 201, 40, 30, desc="ok")])
v = analyze(df, gap=2, geom={}, cross_reference=True)
check("pack anomaly -> oversized item FAIL",
      v[200]["status"] == FAIL and v[200]["unique"])
check("floor-mate exonerated -> PASS", v[201]["status"] == PASS)

# --- AMBIGUOUS: two large items that each alone fit but together don't;
#     removing either fixes it -> both ambiguous.
df = mk([row(2, 9, "T-2", "Cup", 5, 300, 400, 90, desc="a"),
         row(2, 9, "T-2", "Cup", 7, 301, 400, 90, desc="b")])
v = analyze(df, gap=2, geom={}, cross_reference=True)
check("symmetric overflow -> AMBIGUOUS both",
      v[300]["status"] == AMBIGUOUS and v[301]["status"] == AMBIGUOUS)

# --- UNKNOWN ---
df = mk([row(3, 9, "T-3", "Cup", 5, 400, None, None, miss=True, desc="nodata")])
v = analyze(df, gap=2, geom={}, cross_reference=True)
check("missing dims -> UNKNOWN", v[400]["status"] == UNKNOWN)

# --- Cross-reference: width-bad item also on an overflowing floor with an innocent mate ---
df = mk([
    row(4, 9, "T-4", "Cup", 3, 500, 120, 110, desc="wide-bad"),
    row(4, 9, "T-4", "Cup", 5, 500, 400, 90, desc="wide-bad"),
    row(4, 9, "T-4", "Cup", 7, 501, 400, 90, desc="innocent"),
])
v = analyze(df, gap=2, geom={}, cross_reference=True)
check("known-bad item stays FAIL", v[500]["status"] == FAIL)
check("innocent floor-mate exonerated -> PASS", v[501]["status"] == PASS)

# --- Dance vs general: items on slots 1 and 5 are separate floors ---
df = mk([
    row(5, 9, "T-5", "Cup", 1, 600, 100, 80, desc="dance"),
    row(5, 9, "T-5", "Cup", 5, 601, 100, 80, desc="general"),
])
v = analyze(df, gap=2, geom={}, cross_reference=True)
check("separate floors both PASS", v[600]["status"] == PASS and v[601]["status"] == PASS)

# --- Pooling: slots 5 and 7 both general — items share one bin ---
df = mk([
    row(6, 9, "T-6", "Cup", 5, 700, 200, 40, desc="a"),
    row(6, 9, "T-6", "Cup", 7, 701, 200, 40, desc="b"),
    row(6, 9, "T-6", "Cup", 9, 702, 200, 40, desc="c"),
])
v = analyze(df, gap=2, geom={}, cross_reference=True)
check("pooled general floor packs three mid-size items",
      v[700]["status"] == PASS and v[701]["status"] == PASS and v[702]["status"] == PASS)

# --- Tunable geometry: widen floor so a too-wide item passes ---
df = mk([row(7, 9, "T-7", "Cup", 5, 800, 120, 110, desc="wide")])
v = analyze(df, gap=2, geom=dict(general_width=120, general_length=483,
                                 dancefloor_width=120, dancefloor_length=129),
            cross_reference=True)
check("wider floor -> former width fail becomes PASS", v[800]["status"] == PASS)

# --- Lone wide item on dance floor (90 <= 98) ---
df = mk([row(8, 9, "T-8", "Cup", 1, 900, 120, 90, desc="wide-but-ok")])
v = analyze(df, gap=2, geom={}, cross_reference=True)
check("lone 90-wide on dance floor -> PASS", v[900]["status"] == PASS)

# --- Trailer category classification ---
from trailer_categories import (
    classify_trailer, DEFAULT_CATEGORY_GEOM,
    CATEGORY_T_SERIES, CATEGORY_T_SERIES_TOP, CATEGORY_F_SERIES, CATEGORY_OTHER,
)
check("T-02 -> T-Series", classify_trailer("T-02") == CATEGORY_T_SERIES)
check("T-38 -> T-Series", classify_trailer("T-38") == CATEGORY_T_SERIES)
check("T-12 Top -> T-Series Top", classify_trailer("T-12 Top") == CATEGORY_T_SERIES_TOP)
check("F-10 -> F-Series", classify_trailer("F-10") == CATEGORY_F_SERIES)
check("01- Big -> Other", classify_trailer("01- Big") == CATEGORY_OTHER)
check("03-Awn -> Other", classify_trailer("03-Awn") == CATEGORY_OTHER)
check("every category has default geom",
      set(DEFAULT_CATEGORY_GEOM.keys()) == {CATEGORY_T_SERIES, CATEGORY_T_SERIES_TOP,
                                            CATEGORY_F_SERIES, CATEGORY_OTHER})

# --- Per-category geometry override ---
cat_geom = {"T-Series": dict(dancefloor_length=150.0, dancefloor_width=100.0,
                             general_length=500.0, general_width=100.0)}
fg = floor_geometry(FLOOR_DANCE, geom=cat_geom.get("T-Series"))
check("category override changes dance length", fg.length == 150.0)
fg2 = floor_geometry(FLOOR_DANCE, geom=cat_geom.get("Other"))  # None -> falls back to default
check("missing category falls back to default", fg2.length == 129.0)

print("\nALL TESTS PASSED")
