"""Trailer Floor Anomaly Detector — Streamlit UI.

Run from the project root:
    source .venv/bin/activate
    streamlit run app/streamlit_app.py
"""
import os
import pandas as pd
import streamlit as st

from geometry import (
    DEFAULT_GEOM, Item, pack_floor, floor_geometry, floor_for_slot,
    FLOOR_DANCE, FLOOR_GENERAL,
)
from analysis import (
    analyze, summarize, build_used_floors,
    PASS, FAIL, AMBIGUOUS, UNKNOWN,
)

DATA = os.path.join(os.path.dirname(__file__), "..", "data")
STATUS_COLOR = {PASS: "#1a7f37", FAIL: "#cf222e", AMBIGUOUS: "#bf8700", UNKNOWN: "#6e7781"}
ALL = "All"

st.set_page_config(page_title="Trailer Floor Anomaly Detector", layout="wide")


@st.cache_data
def load_data():
    ls = pd.read_csv(os.path.join(DATA, "loadsheet_2026.csv"))
    return ls


ls = load_data()

# ------------------------------------------------------------------ sidebar
st.sidebar.title("Controls")
st.sidebar.caption("2026 season · load sheet trusted · floor-level 2D packing")

views = sorted(ls["trailer_view"].dropna().unique())
default_views = [v for v in views if v != "Awning"]
sel_views = st.sidebar.multiselect(
    "Trailer views", views, default=default_views,
    help="Awning view is excluded by default.",
)

gap = st.sidebar.slider(
    "Harness gap between items (in)", 0.0, 12.0, 2.0, 0.5,
    help="Gap reserved between adjacent equipment on a floor.",
)

cross_ref = st.sidebar.toggle(
    "Cross-reference blame isolation", value=True,
    help="On: pin blame to a specific item where possible. "
         "Off: flag the whole overflowing floor group.",
)

with st.sidebar.expander("Floor dimensions (tunable)", expanded=False):
    st.caption("Two floors only — dance and general. Slot numbers only classify which floor.")
    st.markdown("**Dance floor** (slots 1–2)")
    da, db = st.columns(2)
    dl = da.number_input("Length (in)", value=float(DEFAULT_GEOM["dancefloor_length"]),
                         min_value=1.0, step=1.0, key="dl")
    dw = db.number_input("Width (in)", value=float(DEFAULT_GEOM["dancefloor_width"]),
                         min_value=1.0, step=1.0, key="dw")
    st.markdown("**General floor** (slots 3–10)")
    ga, gb = st.columns(2)
    gl = ga.number_input("Length (in)", value=float(DEFAULT_GEOM["general_length"]),
                         min_value=1.0, step=1.0, key="gl")
    gw = gb.number_input("Width (in)", value=float(DEFAULT_GEOM["general_width"]),
                         min_value=1.0, step=1.0, key="gw")
    geom = dict(dancefloor_length=dl, dancefloor_width=dw,
                general_length=gl, general_width=gw)
    if st.button("Reset to defaults"):
        for k in ("dl", "dw", "gl", "gw"):
            st.session_state.pop(k, None)
        st.rerun()

# ------------------------------------------------------------------ filter + analyze
work = ls[ls["trailer_view"].isin(sel_views)].copy()
work["floor"] = work["slot"].map(floor_for_slot)

# Race / trailer selectors (All allowed)
race_labels = {}
for rid, g in work.groupby("race_id"):
    dates = g["race_date"].dropna().unique()
    if len(dates):
        d = str(dates[0])[:10]
        race_labels[int(rid)] = f"Race {rid} ({d})"
    else:
        race_labels[int(rid)] = f"Race {rid}"

race_options = [ALL] + [race_labels[r] for r in sorted(race_labels)]
sel_race_label = st.sidebar.selectbox("Race", race_options, index=0)
if sel_race_label == ALL:
    race_filter = None
else:
    race_filter = next(r for r, lab in race_labels.items() if lab == sel_race_label)

trailers_available = work if race_filter is None else work[work.race_id == race_filter]
trailer_options = [ALL] + sorted(trailers_available["trailer_name"].dropna().unique().tolist())
sel_trailer = st.sidebar.selectbox("Trailer", trailer_options, index=0)

scoped = work.copy()
if race_filter is not None:
    scoped = scoped[scoped.race_id == race_filter]
if sel_trailer != ALL:
    scoped = scoped[scoped.trailer_name == sel_trailer]

# Analyze on the view-filtered season (blame needs cross-race), then scope display
verdict = analyze(work, gap=gap, geom=geom, cross_reference=cross_ref)
counts = summarize(verdict)

eq_meta = (work[["equipment_id", "serial_number", "equipment_desc",
                 "eq_length", "eq_width"]]
           .drop_duplicates("equipment_id").set_index("equipment_id"))

# Equipment that appears in the current race/trailer scope
scoped_eids = set(scoped["equipment_id"].dropna().astype(int))


def status_rank(s):
    return s.map({FAIL: 0, AMBIGUOUS: 1, UNKNOWN: 2, PASS: 3})


def color_status(v):
    return f"color: {STATUS_COLOR.get(v, '#000')}; font-weight:600"


def equipment_table(eids):
    rows = []
    for eid in eids:
        if eid not in verdict:
            continue
        v = verdict[eid]
        meta = eq_meta.loc[eid] if eid in eq_meta.index else None
        wf = v.get("worst_floor") or {}
        rows.append(dict(
            equipment_id=eid,
            serial=(meta["serial_number"] if meta is not None else None),
            description=(meta["equipment_desc"] if meta is not None else None),
            stored_L=(meta["eq_length"] if meta is not None else None),
            stored_W=(meta["eq_width"] if meta is not None else None),
            status=v["status"],
            anomaly_kind=v["kind"],
            inconsistency_in=v["excess_in"],
            floors_used=v["floors_used"],
            evidence_floor=wf.get("floor"),
            evidence_race=wf.get("race"),
            evidence_trailer=wf.get("trailer"),
            reason=v["reason"],
        ))
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(
        ["status", "inconsistency_in"],
        key=lambda s: status_rank(s) if s.name == "status" else s,
        ascending=[True, False],
    )


# ------------------------------------------------------------------ header
st.title("Trailer Floor Anomaly Detector")
st.caption(
    "Load sheets are ground truth. Equipment is pooled into **dance floor** "
    "(slots 1–2) and **general floor** (slots 3–10). Stored dims that cannot "
    "2D-pack into a floor that worked are flagged for re-scan."
)

scope_bits = []
scope_bits.append("all races" if race_filter is None else race_labels[race_filter])
scope_bits.append("all trailers" if sel_trailer == ALL else sel_trailer)
st.info(f"Viewing: **{' · '.join(scope_bits)}**")

k1, k2, k3, k4, k5 = st.columns(5)
# KPIs for equipment in scope
scoped_verdicts = {e: verdict[e] for e in scoped_eids if e in verdict}
scoped_counts = summarize(scoped_verdicts) if scoped_verdicts else {PASS: 0, FAIL: 0, AMBIGUOUS: 0, UNKNOWN: 0}
k1.metric("Equipment in scope", len(scoped_verdicts))
k2.metric("Consistent", scoped_counts[PASS])
k3.metric("Stored dim wrong", scoped_counts[FAIL])
k4.metric("Ambiguous", scoped_counts[AMBIGUOUS])
k5.metric("No stored dims", scoped_counts[UNKNOWN])

st.divider()

# ------------------------------------------------------------------ floor cards
floors = build_used_floors(scoped, geom)
# Aggregate floor outcomes in scope
floor_stats = {
    FLOOR_DANCE: {"bins": 0, "overflow": 0, "fail_eq": set(), "amb_eq": set(), "items": 0},
    FLOOR_GENERAL: {"bins": 0, "overflow": 0, "fail_eq": set(), "amb_eq": set(), "items": 0},
}

for f in floors:
    stt = floor_stats[f.floor]
    stt["bins"] += 1
    stt["items"] += len(f.items)
    result = pack_floor(f.items, f.cap_length, f.cap_width, gap) if f.items else None
    overflowed = result is not None and not result.fits
    if overflowed:
        stt["overflow"] += 1
    for it in f.items:
        vs = verdict.get(it.equipment_id, {}).get("status")
        if vs == FAIL:
            stt["fail_eq"].add(it.equipment_id)
        elif vs == AMBIGUOUS:
            stt["amb_eq"].add(it.equipment_id)

c_dance, c_gen = st.columns(2)


def render_floor_card(col, floor_key, title):
    fg = floor_geometry(floor_key, geom)
    stt = floor_stats[floor_key]
    n_fail = len(stt["fail_eq"])
    n_amb = len(stt["amb_eq"])
    with col:
        st.subheader(title)
        st.caption(f"{fg.length:.0f} × {fg.width:.0f} in · {stt['bins']} load(s) in scope")
        m1, m2, m3 = st.columns(3)
        m1.metric("Overflowing loads", stt["overflow"])
        m2.metric("Failed equipment", n_fail)
        m3.metric("Ambiguous", n_amb)

        suspect_ids = stt["fail_eq"] | stt["amb_eq"]
        with st.expander(f"Equipment details ({len(suspect_ids)} suspect)", expanded=n_fail + n_amb > 0):
            if not suspect_ids:
                st.write("No failed or ambiguous equipment on this floor in the current scope.")
            else:
                tbl = equipment_table(suspect_ids)
                st.dataframe(
                    tbl.style.map(color_status, subset=["status"]),
                    use_container_width=True, hide_index=True,
                )
                st.download_button(
                    f"Download {title} suspects (CSV)",
                    tbl.to_csv(index=False),
                    f"{floor_key}_suspects.csv",
                    "text/csv",
                    key=f"dl_{floor_key}",
                )

        with st.expander("All equipment on this floor", expanded=False):
            all_ids = set()
            for f in floors:
                if f.floor == floor_key:
                    for it in f.items:
                        all_ids.add(it.equipment_id)
            # also include missing-dim equipment from scoped rows
            miss = scoped[(scoped.floor == floor_key) & scoped.dims_missing]
            for eid in miss["equipment_id"].dropna().astype(int):
                all_ids.add(eid)
            if not all_ids:
                st.write("No equipment on this floor in scope.")
            else:
                tbl = equipment_table(all_ids)
                st.dataframe(
                    tbl.style.map(color_status, subset=["status"]),
                    use_container_width=True, hide_index=True,
                )


render_floor_card(c_dance, FLOOR_DANCE, "Dance floor")
render_floor_card(c_gen, FLOOR_GENERAL, "General floor")

st.divider()

# ------------------------------------------------------------------ good-fail list (scoped)
st.subheader("Good-fail list — re-scan these")
fails = equipment_table({e for e in scoped_eids if verdict.get(e, {}).get("status") == FAIL})
if fails.empty:
    st.success("No uniquely blamed failures in this scope.")
else:
    st.write(f"**{len(fails)}** equipment with stored sizes that contradict a working floor load.")
    st.dataframe(fails.style.map(color_status, subset=["status"]),
                 use_container_width=True, hide_index=True)
    st.download_button("Download good-fail list (CSV)",
                       fails.to_csv(index=False), "good_fail_list_2026.csv", "text/csv")

amb_ids = {e for e in scoped_eids if verdict.get(e, {}).get("status") == AMBIGUOUS}
if amb_ids:
    with st.expander(f"Ambiguous ({len(amb_ids)}) — scan the group"):
        amb = equipment_table(amb_ids)
        st.dataframe(amb.style.map(color_status, subset=["status"]),
                     use_container_width=True, hide_index=True)

unk_ids = {e for e in scoped_eids if verdict.get(e, {}).get("status") == UNKNOWN}
if unk_ids:
    with st.expander(f"Unknown dims ({len(unk_ids)})"):
        unk = equipment_table(unk_ids)
        st.dataframe(unk[["equipment_id", "serial", "description", "reason"]],
                     use_container_width=True, hide_index=True)

st.divider()

# ------------------------------------------------------------------ floor drill-down (optional)
with st.expander("Inspect one race · trailer · floor", expanded=False):
    races = sorted(scoped["race_id"].unique()) if len(scoped) else []
    if not races:
        st.write("Nothing in scope.")
    else:
        d1, d2, d3 = st.columns(3)
        race = d1.selectbox("Race id", races, key="drill_race")
        trailers = sorted(scoped[scoped.race_id == race]["trailer_name"].unique())
        trailer = d2.selectbox("Trailer", trailers, key="drill_trailer")
        floor = d3.selectbox("Floor", [FLOOR_DANCE, FLOOR_GENERAL], key="drill_floor")
        sub = scoped[(scoped.race_id == race) & (scoped.trailer_name == trailer)
                     & (scoped.floor == floor)]
        fg = floor_geometry(floor, geom)
        items = []
        seen = set()
        for _, r in sub.iterrows():
            if r.dims_missing or pd.isna(r.eq_length) or pd.isna(r.eq_width):
                continue
            if r.eq_length <= 0 or r.eq_width <= 0:
                continue
            eid = int(r.equipment_id)
            if eid in seen:
                continue
            seen.add(eid)
            items.append(Item(eid, float(r.eq_length), float(r.eq_width),
                              str(r.equipment_desc)))
        result = pack_floor(items, fg.length, fg.width, gap) if items else None
        st.write(f"**{floor}** floor: **{fg.length:.0f} × {fg.width:.0f} in** · "
                 f"{len(items)} item(s) · gap {gap} in")
        if not items:
            st.write("No items with dimensions on this floor.")
        elif result.fits:
            st.success(f"Stored sizes pack successfully ({result.detail}).")
        else:
            st.error(f"Stored sizes cannot pack — {result.detail}. "
                     f"Area overflow ≈ {result.area_overflow:.0f} in².")
        st.dataframe(
            sub[["equipment_id", "serial_number", "equipment_desc",
                 "eq_length", "eq_width", "slot", "dims_missing"]],
            use_container_width=True, hide_index=True,
        )

st.caption(
    "Data: Champschedule (load sheet) ⋈ WMS (equipment dims), 2026. "
    "Season-wide analysis runs for blame isolation; the race/trailer selectors "
    "scope what you see."
)
