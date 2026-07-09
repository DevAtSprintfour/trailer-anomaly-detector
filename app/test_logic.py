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


# geometry defaults (general slot 480 x 49, dancefloor 120 x 48)
gen = slot_geometry(5)
check("general slot", (gen.length, gen.width) == (480.0, 49.0))

# --- WIDTH anomaly: item stored 60 wide (shorter side 60) in a 49-wide slot that
#     was USED -> impossible -> its stored width is wrong (unique). ---
df = mk([row(1, 9, "T-1", "Cup", 5, 100, 100, 60, desc="too-wide")])
v = analyze(df, gap=2, geom={}, cross_reference=True)
check("width anomaly -> FAIL unique", v[100]["status"] == FAIL and v[100]["kind"] == "width")

# a normal item (40x30) in the same kind of slot is consistent -> PASS
df = mk([row(1, 9, "T-1", "Cup", 5, 101, 40, 30, desc="fine")])
v = analyze(df, gap=2, geom={}, cross_reference=True)
check("consistent item -> PASS", v[101]["status"] == PASS)

# --- LENGTH anomaly with unique blame: slot 5 (cap 480). Items 500 + 40 stored.
#     Only removing the 500 makes stored sizes fit -> the 500's stored length wrong.
df = mk([row(1, 9, "T-1", "Cup", 5, 200, 500, 30, desc="long-bad"),
         row(1, 9, "T-1", "Cup", 5, 201, 40, 30, desc="ok")])
v = analyze(df, gap=2, geom={}, cross_reference=True)
check("length anomaly -> long item FAIL unique",
      v[200]["status"] == FAIL and v[200]["kind"] == "length" and v[200]["unique"])
check("slot-mate exonerated -> PASS", v[201]["status"] == PASS)

# --- AMBIGUOUS: two 300-long items in cap-480 slot. Removing EITHER fixes it
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

# --- Cross-reference exoneration across slots: item 500 is width-bad (proven wrong
#     in slot 5). It also shares slot 6 with item 501 where stored sizes overflow.
#     501 should not be blamed just for sharing a slot with the known-bad 500. ---
df = mk([
    row(4, 9, "T-4", "Cup", 5, 500, 100, 60, desc="wide-bad"),         # width anomaly
    row(4, 9, "T-4", "Cup", 6, 500, 460, 40, desc="wide-bad"),         # also long here
    row(4, 9, "T-4", "Cup", 6, 501, 60, 40, desc="innocent"),          # 460+60 > 480
])
v = analyze(df, gap=2, geom={}, cross_reference=True)
check("known-bad item stays FAIL", v[500]["status"] == FAIL)
# removing 500 from slot 6 (460) leaves 60 which fits -> 500 is the unique resolver,
# so 501 is exonerated (PASS), not dragged in.
check("innocent slot-mate exonerated -> PASS", v[501]["status"] == PASS)

# --- tunable geometry: widen slots so nothing is width-bad ---
df = mk([row(5, 9, "T-5", "Cup", 5, 600, 100, 60, desc="wide")])
v = analyze(df, gap=2, geom=dict(general_width=96, general_length=480,
                                 dancefloor_width=96, dancefloor_length=160),
            cross_reference=True)
check("wider slot -> width anomaly disappears -> PASS", v[600]["status"] == PASS)

print("\nALL TESTS PASSED")
