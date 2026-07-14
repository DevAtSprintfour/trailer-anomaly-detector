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

# --- build_used_floors carries trailer_category; analyze() takes category_geom ---
from analysis import build_used_floors

df = mk([row(9, 50, "T-09", "Cup", 5, 1000, 400, 90, desc="a")])
floors = build_used_floors(df, geom={})
check("UsedFloor has trailer_category field",
      hasattr(floors[0], "trailer_category") and floors[0].trailer_category == CATEGORY_T_SERIES)

# category_geom widens T-Series general floor so a normally-fine item still fits,
# and narrows F-Series so the same shape would fail there (different category = different result)
category_geom = {
    CATEGORY_T_SERIES: dict(dancefloor_length=129.0, dancefloor_width=98.0,
                            general_length=483.0, general_width=98.0),
    "F-Series": dict(dancefloor_length=129.0, dancefloor_width=40.0,
                     general_length=483.0, general_width=40.0),
}
df2 = mk([row(10, 60, "F-10", "Cup", 5, 1001, 90, 60, desc="b")])  # 60 > 40 width -> should FAIL
v = analyze(df2, gap=2, geom={}, cross_reference=True, category_geom=category_geom)
check("F-Series narrow width triggers FAIL via category_geom", v[1001]["status"] == FAIL)

# --- Checklist store (SQLite) ---
import tempfile
from checklist_store import ChecklistStore

_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
store = ChecklistStore(_tmp_db)

check("nothing verified initially", store.get_verified_ids() == set())

store.mark_verified(equipment_id=200, race_id=1, trailer_id=9, floor="general",
                    note="physically checked, dims correct")
check("mark_verified persists", 200 in store.get_verified_ids())

store2 = ChecklistStore(_tmp_db)  # reopen same file -> state survives
check("verification survives reopen", 200 in store2.get_verified_ids())

store2.unmark_verified(200)
check("unmark_verified removes it", 200 not in store2.get_verified_ids())

store2.mark_verified(equipment_id=201, race_id=2, trailer_id=10, floor="dance", note="")
records = store2.list_records()
check("list_records returns entries", any(r["equipment_id"] == 201 for r in records))

# Dimension corrections
check("no corrections initially", store2.get_dimension_corrections() == {})
store2.set_dimension_correction(500, corrected_length=100, corrected_width=40,
                                original_length=400, original_width=90)
check("set_dimension_correction persists",
      store2.get_dimension_corrections()[500] == (100.0, 40.0))
store3 = ChecklistStore(_tmp_db)
check("corrections survive reopen",
      store3.get_dimension_corrections()[500] == (100.0, 40.0))
listed = store3.list_dimension_corrections()
check("list_dimension_corrections has original dims",
      any(r["equipment_id"] == 500 and r["original_length"] == 400 for r in listed))
store3.clear_dimension_correction(500)
check("clear_dimension_correction removes it",
      500 not in store3.get_dimension_corrections())

import os as _os
_os.unlink(_tmp_db)

# --- Verified equipment: excluded from ambiguous blame, forced to RESOLVED ---
from analysis import RESOLVED

# Symmetric-overflow case (two 400x90 items don't both fit on a 483x98 floor),
# but now verify item 302. Excluding it from blame leaves only 303, which fits
# alone -> 303 is fully exonerated (PASS), not just re-blamed.
df = mk([row(20, 9, "T-20", "Cup", 5, 302, 400, 90, desc="a"),
         row(20, 9, "T-20", "Cup", 7, 303, 400, 90, desc="b")])
v = analyze(df, gap=2, geom={}, cross_reference=True, verified={302})
check("verified item forced to RESOLVED", v[302]["status"] == RESOLVED)
check("verified item excluded from blame -> mate exonerated PASS",
      v[303]["status"] == PASS)

# Three-item case: verify one 400x90 item, leaving two 400x90 items that
# still can't both fit on the 483x98 general floor together -> the remaining
# pair should still hit the ambiguous/unique-blame path on their own.
df2 = mk([row(21, 9, "T-21", "Cup", 5, 310, 400, 90, desc="verified-a"),
          row(21, 9, "T-21", "Cup", 6, 311, 400, 90, desc="b"),
          row(21, 9, "T-21", "Cup", 7, 312, 400, 90, desc="c")])
v2 = analyze(df2, gap=2, geom={}, cross_reference=True, verified={310})
check("verified item (3-way) forced to RESOLVED", v2[310]["status"] == RESOLVED)
check("remaining floor-mates re-blamed without verified item -> AMBIGUOUS",
      v2[311]["status"] == AMBIGUOUS and v2[312]["status"] == AMBIGUOUS)

# --- Dimension overrides: correcting one oversized item lets the floor pack ---
df3 = mk([row(22, 9, "T-22", "Cup", 5, 320, 500, 90, desc="oversized"),
          row(22, 9, "T-22", "Cup", 7, 321, 40, 30, desc="ok")])
v_bad = analyze(df3, gap=2, geom={}, cross_reference=True)
check("before override oversized is FAIL", v_bad[320]["status"] == FAIL)
v_fixed = analyze(df3, gap=2, geom={}, cross_reference=True,
                  dim_overrides={320: (100.0, 40.0)})
check("dim override on oversized -> PASS", v_fixed[320]["status"] == PASS)
check("mate still PASS after override", v_fixed[321]["status"] == PASS)

# --- Packing diagram: continuous trailer strip (dance nose + general rear) ---
from packing_viz import render_trailer_figure
import plotly.graph_objects as go

dance_fg = floor_geometry(FLOOR_DANCE)
general_fg = floor_geometry(FLOOR_GENERAL)
dance_items = [Item(9001, 60, 38, "CTS1 TB Stack")]
dance_result = pack_floor(dance_items, dance_fg.length, dance_fg.width, gap=2)
general_items = [Item(9002, 200, 40, "widget-a"), Item(9003, 200, 40, "widget-b")]
general_result = pack_floor(general_items, general_fg.length, general_fg.width, gap=2)

fig = render_trailer_figure(
    dance_fg, dance_items, dance_result,
    general_fg, general_items, general_result,
    verdict={9001: {"status": "PASS"}, 9002: {"status": "PASS"}, 9003: {"status": "PASS"}},
)
check("render_trailer_figure returns a plotly Figure", isinstance(fig, go.Figure))
n_rects = sum(1 for s in fig.layout.shapes if s.type == "rect")
# One continuous trailer outline + one rect per placed item (no separate floors).
check("figure has one trailer outline + one rect per placed item",
      n_rects == 1 + len(dance_result.placements) + len(general_result.placements))
outline = next(s for s in fig.layout.shapes
               if s.type == "rect" and abs(s.x1 - (dance_fg.length + general_fg.length)) < 0.01)
check("trailer outline spans dance+general length",
      abs(outline.x1 - (dance_fg.length + general_fg.length)) < 0.01)
labels_blob = " ".join(str(getattr(tr, "text", "")) for tr in fig.data)
check("figure labels include equipment name and id",
      "CTS1 TB Stack" in labels_blob and "9001" in labels_blob)
check("figure labels include on-file dimensions",
      "60×38" in labels_blob or "60x38" in labels_blob)

# Overflow case: item too big to fit at all -> renderer should still return a
# valid figure (drawing the trailer outline + an overflow annotation), not crash.
big_general_items = [Item(9004, 900, 90, "oversized")]
big_general_result = pack_floor(big_general_items, general_fg.length, general_fg.width, gap=2)
fig2 = render_trailer_figure(
    dance_fg, [], pack_floor([], dance_fg.length, dance_fg.width, gap=2),
    general_fg, big_general_items, big_general_result,
    verdict={9004: {"status": "FAIL"}},
)
check("overflow figure still valid", isinstance(fig2, go.Figure))

print("\nALL TESTS PASSED")
