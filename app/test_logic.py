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

# --- Cross-race isolation must not depend on floor iteration order:
#     item 1000 rides on TWO floors, both general, with the SAME stored
#     dims (400x90) throughout:
#       Floor A (race 10): 1000 + 1001, symmetric overflow — ambiguous
#         unless 1000 is already known-bad.
#       Floor B (race 11): 1000 + two small mates (1002, 1003) — pairwise
#         leave-one-out proves 1000 the sole resolver, standalone (no
#         cross-race info needed).
#     Floor A is inserted first, so a single forward pass processes A
#     before B proves 1000 guilty, stranding 1001 as AMBIGUOUS. A
#     fixed-point pass must re-examine A afterward and clear 1001.
df = mk([
    row(10, 20, "T-10", "Cup", 5, 1000, 400, 90, desc="repeat-offender"),
    row(10, 20, "T-10", "Cup", 7, 1001, 400, 90, desc="innocent-mate"),
    row(11, 21, "T-11", "Cup", 5, 1000, 400, 90, desc="repeat-offender"),
    row(11, 21, "T-11", "Cup", 7, 1002, 100, 90, desc="small-a"),
    row(11, 21, "T-11", "Cup", 9, 1003, 100, 90, desc="small-b"),
])
v = analyze(df, gap=2, geom={}, cross_reference=True)
check("order-independent cross-race: repeat offender stays FAIL", v[1000]["status"] == FAIL)
check("order-independent cross-race: innocent mate cleared to PASS", v[1001]["status"] == PASS)
check("order-independent cross-race: small mates PASS",
      v[1002]["status"] == PASS and v[1003]["status"] == PASS)

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

# --- Packing diagram: continuous trailer strip; on-floor with hatched overlaps ---
from packing_viz import render_trailer_figure, display_pack, DANCE_FILL, GENERAL_FILL
from floor_geom import pack_floor_best_effort
import plotly.graph_objects as go

_BG = {DANCE_FILL, GENERAL_FILL, "rgba(0,0,0,0)"}


def _item_traces(fig):
    return [tr for tr in fig.data
            if getattr(tr, "fill", None) == "toself"]


def _ann_blob(fig):
    return " ".join(str(a.text) for a in (fig.layout.annotations or []))


def _trace_bbox(tr):
    xs = list(tr.x)
    ys = list(tr.y)
    return min(xs), min(ys), max(xs), max(ys)


def _rects_overlap(a, b, pad=0.5):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return (ax0 < bx1 - pad and ax1 > bx0 + pad
            and ay0 < by1 - pad and ay1 > by0 + pad)


dance_fg = floor_geometry(FLOOR_DANCE)
general_fg = floor_geometry(FLOOR_GENERAL)
trailer_w = max(dance_fg.width, general_fg.width)
trailer_l = dance_fg.length + general_fg.length
dance_items = [Item(9001, 60, 38, "CTS1 TB Stack")]
general_items = [Item(9002, 200, 40, "widget-a"), Item(9003, 200, 40, "widget-b")]

fig = render_trailer_figure(
    dance_fg, dance_items,
    general_fg, general_items,
    verdict={9001: {"status": "PASS"}, 9002: {"status": "PASS"}, 9003: {"status": "PASS"}},
    gap=2.0,
)
check("render_trailer_figure returns a plotly Figure", isinstance(fig, go.Figure))
check("figure draws every placed item on the floor", len(_item_traces(fig)) == 3)
outline = next(s for s in fig.layout.shapes
               if s.type == "rect" and s.fillcolor == "rgba(0,0,0,0)")
check("trailer outline spans dance+general length",
      abs(outline.x1 - trailer_l) < 0.01)
for tr in _item_traces(fig):
    x0, y0, x1, y1 = _trace_bbox(tr)
    check("every placed box stays on the trailer floor (Y)",
          y0 >= -0.1 and y1 <= trailer_w + 0.1)
    check("every placed box stays inside the trailer (X)",
          x0 >= -0.1 and x1 <= trailer_l + 0.1)
labels = _ann_blob(fig)
check("figure labels include equipment name and id on boxes",
      "CTS1 TB Stack" in labels and "9001" in labels)
check("figure labels include on-file dimensions on boxes",
      "60×38" in labels or "60x38" in labels)

big_general_items = [Item(9004, 500, 90, "oversized"), Item(9005, 40, 30, "ok")]
placed, overflow, exact = display_pack(
    big_general_items, general_fg.length, general_fg.width, 2.0,
    verdict={9004: {"status": "FAIL"}, 9005: {"status": "PASS"}},
)
check("display_pack leaves FAIL item as overflow",
      [it.equipment_id for it in overflow] == [9004])
check("display_pack packs the OK mate inside",
      [p.equipment_id for p in placed] == [9005])
check("exact pack reports does-not-fit", not exact.fits)

fig2 = render_trailer_figure(
    dance_fg, [],
    general_fg, big_general_items,
    verdict={9004: {"status": "FAIL"}, 9005: {"status": "PASS"}},
    gap=2.0,
)
check("overflow figure still valid", isinstance(fig2, go.Figure))
check("overflow figure draws all equipment on the floor", len(_item_traces(fig2)) == 2)
for tr in _item_traces(fig2):
    x0, y0, x1, y1 = _trace_bbox(tr)
    check("FAIL/PASS boxes stay on trailer floor (Y)",
          y0 >= -0.1 and y1 <= trailer_w + 0.1)
    check("FAIL/PASS boxes stay inside the trailer (X)",
          x0 >= -0.1 and x1 <= trailer_l + 0.1)
# Oversized FAIL should hatch when it overlaps the PASS mate
hatched = [tr for tr in _item_traces(fig2)
           if getattr(tr, "fillpattern", None) and tr.fillpattern.shape]
check("overlapping won't-pack box uses hatch pattern", len(hatched) >= 1)

pair = [Item(9010, 400, 90, "a"), Item(9011, 400, 90, "b")]
be_placed, be_unplaced = pack_floor_best_effort(pair, general_fg.length, general_fg.width, gap=2)
check("best_effort places one of two large items", len(be_placed) == 1)
check("best_effort leaves one of two large items unplaced", len(be_unplaced) == 1)

# F-10: both AMBIGUOUS on-floor; may overlap packed tiles — hatch, no gutter.
f10_dance = [Item(7217, 140, 48, "Monster 145"), Item(7218, 140, 48, "Monster 146")]
f10_gen = [
    Item(7381, 156, 72, "tele"), Item(7220, 140, 48, "m"),
    Item(7399, 128, 48, "m2"), Item(7014, 115, 45, "gc"), Item(7309, 140, 46, "p"),
]
v_f10 = {7217: {"status": "AMBIGUOUS"}, 7218: {"status": "AMBIGUOUS"},
         7381: {"status": "PASS"}, 7220: {"status": "PASS"}, 7399: {"status": "PASS"},
         7014: {"status": "PASS"}, 7309: {"status": "PASS"}}
fig3 = render_trailer_figure(dance_fg, f10_dance, general_fg, f10_gen, v_f10, gap=2)
check("F-10 style draws all 7 equipment on the floor", len(_item_traces(fig3)) == 7)
for tr in _item_traces(fig3):
    x0, y0, x1, y1 = _trace_bbox(tr)
    check("F-10 boxes stay on trailer floor (Y)",
          y0 >= -0.1 and y1 <= trailer_w + 0.1)
    check("F-10 boxes stay inside the trailer (X)",
          x0 >= -0.1 and x1 <= trailer_l + 0.1)
hatched3 = [tr for tr in _item_traces(fig3)
            if getattr(tr, "fillpattern", None) and tr.fillpattern.shape]
check("F-10 won't-pack overlaps are hatched", len(hatched3) >= 1)
labels3 = _ann_blob(fig3)
check("F-10 box labels include equipment names without hover",
      "Monster 145" in labels3 and "Monster 146" in labels3)

# T-07: both AMBIGUOUS on-floor at dance nose.
t07_dance = [Item(7145, 134, 60, "88 pit"), Item(7066, 135, 37, "24 Utility")]
v_t07 = {7145: {"status": "AMBIGUOUS"}, 7066: {"status": "AMBIGUOUS"}}
placed_t, unpl_t, exact_t = display_pack(
    t07_dance, dance_fg.length, dance_fg.width, 2.0, v_t07,
)
check("T-07 dance exact pack fails", not exact_t.fits)
check("T-07 dance display places nothing inside (same as packer)",
      placed_t == [] and {i.equipment_id for i in unpl_t} == {7145, 7066})
fig4 = render_trailer_figure(dance_fg, t07_dance, general_fg, [], v_t07, gap=2)
check("T-07 draws both AMBIGUOUS on the floor", len(_item_traces(fig4)) == 2)
for tr in _item_traces(fig4):
    x0, y0, x1, y1 = _trace_bbox(tr)
    check("T-07 boxes stay on trailer floor (Y)",
          y0 >= -0.1 and y1 <= trailer_w + 0.1)
    check("T-07 boxes stay inside the trailer (X)",
          x0 >= -0.1 and x1 <= trailer_l + 0.1)
labels4 = _ann_blob(fig4)
check("T-07 box labels show names and dims on the boxes",
      "88 pit" in labels4 and "24 Utility" in labels4
      and ("134×60" in labels4 or "134x60" in labels4))

print("\nALL TESTS PASSED")
