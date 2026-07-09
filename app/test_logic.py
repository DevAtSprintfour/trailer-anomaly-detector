"""Tests for the load-sheet-as-truth model. Run: python test_logic.py"""
import pandas as pd
from geometry import slot_geometry
from analysis import analyze, summarize, build_used_slots, PASS, FAIL, AMBIGUOUS, UNKNOWN


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


# geometry defaults: general slot 483 x 98, dancefloor 129 x 98 (width shared per row)
gen = slot_geometry(5)
check("general slot", (gen.length, gen.width) == (483.0, 98.0))
dance = slot_geometry(1)
check("dancefloor slot", (dance.length, dance.width) == (129.0, 98.0))

# --- WIDTH anomaly (single item): stored shorter side 110 > full width 98, in a
#     slot that was USED -> impossible -> stored width wrong (unique). ---
df = mk([row(1, 9, "T-1", "Cup", 5, 100, 120, 110, desc="too-wide")])
v = analyze(df, gap=2, geom={}, cross_reference=True)
check("width anomaly -> FAIL unique", v[100]["status"] == FAIL and v[100]["kind"] == "width")

# a normal item (40x30) is consistent -> PASS
df = mk([row(1, 9, "T-1", "Cup", 5, 101, 40, 30, desc="fine")])
v = analyze(df, gap=2, geom={}, cross_reference=True)
check("consistent item -> PASS", v[101]["status"] == PASS)

# --- LENGTH anomaly with unique blame: slot 5 (cap 483). Items 500 + 40 stored.
#     Only removing the 500 makes stored sizes fit -> the 500's stored length wrong.
df = mk([row(1, 9, "T-1", "Cup", 5, 200, 500, 30, desc="long-bad"),
         row(1, 9, "T-1", "Cup", 5, 201, 40, 30, desc="ok")])
v = analyze(df, gap=2, geom={}, cross_reference=True)
check("length anomaly -> long item FAIL unique",
      v[200]["status"] == FAIL and v[200]["kind"] == "length" and v[200]["unique"])
check("slot-mate exonerated -> PASS", v[201]["status"] == PASS)

# --- AMBIGUOUS: two 300-long items in cap-483 slot. Removing EITHER fixes it
#     (2 resolvers) -> can't uniquely blame -> both ambiguous. ---
df = mk([row(2, 9, "T-2", "Cup", 5, 300, 300, 30, desc="a"),
         row(2, 9, "T-2", "Cup", 5, 301, 300, 30, desc="b")])
v = analyze(df, gap=2, geom={}, cross_reference=True)
check("symmetric overflow -> AMBIGUOUS both",
      v[300]["status"] == AMBIGUOUS and v[301]["status"] == AMBIGUOUS)

# --- UNKNOWN: missing dims ---
df = mk([row(3, 9, "T-3", "Cup", 5, 400, None, None, miss=True, desc="nodata")])
v = analyze(df, gap=2, geom={}, cross_reference=True)
check("missing dims -> UNKNOWN", v[400]["status"] == UNKNOWN)

# --- Cross-reference exoneration across slots: item 500 is width-bad (stored
#     shorter side 110 > full width 98 in slot 3). It also shares slot 5 with item
#     501 where stored LENGTHS overflow. 501 must not be blamed for sharing with
#     the known-bad 500. ---
df = mk([
    row(4, 9, "T-4", "Cup", 3, 500, 120, 110, desc="wide-bad"),        # width anomaly (110>98)
    row(4, 9, "T-4", "Cup", 5, 500, 470, 40, desc="wide-bad"),         # also long here
    row(4, 9, "T-4", "Cup", 5, 501, 60, 40, desc="innocent"),          # 470+60 > 483
])
v = analyze(df, gap=2, geom={}, cross_reference=True)
check("known-bad item stays FAIL", v[500]["status"] == FAIL)
# removing 500 from slot 5 (470) leaves 60 which fits -> 500 is the unique resolver,
# so 501 is exonerated (PASS), not dragged in.
check("innocent slot-mate exonerated -> PASS", v[501]["status"] == PASS)

# --- tunable geometry: a paired 60+60=120 overflow at width 98 becomes fine if the
#     user widens the trailer to 130. ---
df = mk([row(5, 9, "T-5", "Cup", 5, 600, 100, 60, desc="L"),
         row(5, 9, "T-5", "Cup", 6, 601, 100, 60, desc="R")])
v = analyze(df, gap=2, geom=dict(general_width=130, general_length=483,
                                 dancefloor_width=130, dancefloor_length=129),
            cross_reference=True)
check("wider trailer -> paired overflow disappears -> PASS",
      v[600]["status"] == PASS and v[601]["status"] == PASS)

# --- PAIRED-COLUMN width (new model): slots 5 (left) & 6 (right) share width 98.
#     Left item 60 wide + right item 60 wide = 120 > 98 -> overflow. Neither alone
#     exceeds 98, both would reconcile -> ambiguous pair. ---
df = mk([row(6, 9, "T-6", "Cup", 5, 700, 100, 60, desc="L60"),
         row(6, 9, "T-6", "Cup", 6, 701, 100, 60, desc="R60")])
v = analyze(df, gap=2, geom={}, cross_reference=True)  # general_width default now 98
check("paired 60+60>98 -> AMBIGUOUS both",
      v[700]["status"] == AMBIGUOUS and v[701]["status"] == AMBIGUOUS)

# paired unique blame: left 90 (alone >? no, 90<=98) + right 30. 90+30=120>98, but
# dropping the left (90) leaves 30 (fits), dropping right (30) leaves 90 (fits) ->
# both reconcile -> ambiguous. To get UNIQUE, make one side alone exceed width:
# left 100-wide can't fit even alone -> single-item width anomaly (kind=width).
df = mk([row(7, 9, "T-7", "Cup", 5, 800, 120, 100, desc="tooWide"),
         row(7, 9, "T-7", "Cup", 6, 801, 40, 30, desc="ok")])
v = analyze(df, gap=2, geom={}, cross_reference=True)
check("100>98 full width -> FAIL width unique", v[800]["status"] == FAIL and v[800]["kind"] == "width")
check("its row-mate exonerated -> PASS", v[801]["status"] == PASS)

# lone column item up to 90 wide fits full 98 width -> PASS (the whole point)
df = mk([row(8, 9, "T-8", "Cup", 1, 900, 120, 90, desc="wide-but-lone")])
v = analyze(df, gap=2, geom={}, cross_reference=True)
check("lone 90-wide item fits full width -> PASS", v[900]["status"] == PASS)

print("\nALL TESTS PASSED")
