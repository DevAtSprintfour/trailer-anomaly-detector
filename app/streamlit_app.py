"""Trailer Slot Anomaly Detector — Streamlit UI.

Run from the project root:
    source .venv/bin/activate
    streamlit run app/streamlit_app.py
"""
import os
import pandas as pd
import streamlit as st

from geometry import DEFAULT_GEOM, DANCEFLOOR_SLOTS, slot_geometry, Item, evaluate_slot
from analysis import (analyze, summarize, build_used_slots, _fits_axis,
                      PASS, FAIL, AMBIGUOUS, UNKNOWN)

DATA = os.path.join(os.path.dirname(__file__), "..", "data")
STATUS_COLOR = {PASS: "#1a7f37", FAIL: "#cf222e", AMBIGUOUS: "#bf8700", UNKNOWN: "#6e7781"}

st.set_page_config(page_title="Trailer Slot Anomaly Detector", layout="wide")


@st.cache_data
def load_data():
    ls = pd.read_csv(os.path.join(DATA, "loadsheet_2026.csv"))
    eq = pd.read_csv(os.path.join(DATA, "equipment_2026.csv"))
    return ls, eq


ls, eq = load_data()

# ------------------------------------------------------------------ sidebar
st.sidebar.title("Controls")
st.sidebar.caption("2026 season · load sheet is trusted · flagging suspect equipment dims")

views = sorted(ls["trailer_view"].dropna().unique())
default_views = [v for v in views if v != "Awning"]
sel_views = st.sidebar.multiselect("Trailer views", views, default=default_views,
                                    help="Awning view is excluded by default per spec.")

gap = st.sidebar.slider("Harness gap between items (in)", 0.0, 12.0, 2.0, 0.5,
                        help="Gap reserved between adjacent equipment in a shared slot. "
                             "N items → (N−1) gaps.")

cross_ref = st.sidebar.toggle("Cross-reference blame isolation", value=True,
                              help="On: pin blame to a specific item where possible. "
                                   "Off: flag the whole overflowing slot group.")

with st.sidebar.expander("Trailer slot dimensions (tunable)", expanded=True):
    st.caption("Usable size **per slot**. Defaults are the even-split reading of the "
               "diagram (width = total ÷ 2). Adjust to match the real trailer and watch "
               "pass/fail converge.")
    st.markdown("**Dancefloor slots (1, 2)**")
    da, db = st.columns(2)
    dl = da.number_input("Length (in)", value=float(DEFAULT_GEOM["dancefloor_length"]),
                         min_value=1.0, step=1.0, key="dl")
    dw = db.number_input("Width (in)", value=float(DEFAULT_GEOM["dancefloor_width"]),
                         min_value=1.0, step=1.0, key="dw")
    st.markdown("**General slots (3–10)**")
    ga, gb = st.columns(2)
    gl = ga.number_input("Length (in)", value=float(DEFAULT_GEOM["general_length"]),
                         min_value=1.0, step=1.0, key="gl")
    gw = gb.number_input("Width (in)", value=float(DEFAULT_GEOM["general_width"]),
                         min_value=1.0, step=1.0, key="gw")
    geom = dict(dancefloor_length=dl, dancefloor_width=dw,
                general_length=gl, general_width=gw)
    if st.button("↺ Reset to even-split defaults"):
        for k in ("dl", "dw", "gl", "gw"):
            st.session_state.pop(k, None)
        st.rerun()

# ------------------------------------------------------------------ compute
work = ls[ls["trailer_view"].isin(sel_views)].copy()

verdict = analyze(work, gap=gap, geom=geom, cross_reference=cross_ref)
counts = summarize(verdict)

# per-equipment table
eq_meta = (work[["equipment_id", "serial_number", "equipment_desc",
                 "eq_length", "eq_width", "eq_height"]]
           .drop_duplicates("equipment_id").set_index("equipment_id"))
rows = []
for eid, v in verdict.items():
    meta = eq_meta.loc[eid] if eid in eq_meta.index else None
    ws = v["worst_slot"] or {}
    rows.append(dict(
        equipment_id=eid,
        serial=(meta["serial_number"] if meta is not None else None),
        description=(meta["equipment_desc"] if meta is not None else None),
        stored_L=(meta["eq_length"] if meta is not None else None),
        stored_W=(meta["eq_width"] if meta is not None else None),
        status=v["status"], anomaly_kind=v["kind"], unique_blame=v["unique"],
        inconsistency_in=v["excess_in"], slots_used=v["slots_used"],
        reason=v["reason"],
        evidence_race=ws.get("race"), evidence_trailer=ws.get("trailer"),
        evidence_slot=ws.get("slot"),
    ))
table = pd.DataFrame(rows).sort_values(
    ["status", "inconsistency_in"],
    key=lambda s: s.map({FAIL: 0, AMBIGUOUS: 1, UNKNOWN: 2, PASS: 3}) if s.name == "status" else s,
    ascending=[True, False])

# ------------------------------------------------------------------ header + KPIs
st.title("🚛 Trailer Slot Anomaly Detector")
st.caption("**Load sheets are the source of truth.** A slot that was used means its "
           "equipment fit. When an equipment's *stored* dimensions contradict a load "
           "sheet that worked, the stored dimensions are wrong — flagged here for "
           "manual scanner verification.")

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Equipment evaluated", len(table))
k2.metric("✅ Consistent", counts[PASS])
k3.metric("❌ Stored dim wrong", counts[FAIL])
k4.metric("⚠️ Ambiguous", counts[AMBIGUOUS])
k5.metric("❔ No stored dims", counts[UNKNOWN])

st.divider()

tab_fail, tab_all, tab_slot = st.tabs(
    ["🎯 Good-fail list (verify these)", "All equipment", "🔍 Slot drill-down"])

# --- Good-fail list ---
with tab_fail:
    st.subheader("Stored dimensions that contradict a working load sheet — scan these")
    fails = table[table.status == FAIL].copy()
    st.write(f"**{len(fails)}** equipment whose stored size is inconsistent with a load "
             f"sheet that was used successfully — blame pinned to this specific item.")
    st.dataframe(fails, use_container_width=True, hide_index=True)
    st.download_button("⬇ Download good-fail list (CSV)",
                       fails.to_csv(index=False), "good_fail_list_2026.csv", "text/csv")

    amb = table[table.status == AMBIGUOUS]
    if len(amb):
        st.subheader("Ambiguous (scan the whole group)")
        st.caption("Overflowing multi-item slots where blame can't be pinned to one item.")
        st.dataframe(amb, use_container_width=True, hide_index=True)
        st.download_button("⬇ Download ambiguous list (CSV)",
                           amb.to_csv(index=False), "ambiguous_list_2026.csv", "text/csv")

    unk = table[table.status == UNKNOWN]
    if len(unk):
        st.subheader("Unknown — missing/zero dimensions")
        st.caption("No usable dims in WMS. A missing measurement is itself a data-quality flag.")
        st.dataframe(unk[["equipment_id", "serial", "description", "reason"]],
                     use_container_width=True, hide_index=True)
        st.download_button("⬇ Download unknown-dims list (CSV)",
                           unk.to_csv(index=False), "unknown_dims_2026.csv", "text/csv")

# --- All equipment ---
with tab_all:
    status_filter = st.multiselect("Filter status", [FAIL, AMBIGUOUS, UNKNOWN, PASS],
                                   default=[FAIL, AMBIGUOUS, UNKNOWN, PASS])
    view = table[table.status.isin(status_filter)]
    def color(v):
        return f"color: {STATUS_COLOR.get(v, '#000')}; font-weight:600"
    st.dataframe(view.style.map(color, subset=["status"]),
                 use_container_width=True, hide_index=True)
    st.download_button("⬇ Download full results (CSV)",
                       view.to_csv(index=False), "all_equipment_verdicts_2026.csv", "text/csv")

# --- Slot drill-down ---
with tab_slot:
    st.subheader("Inspect a single slot: do the STORED sizes contradict this load sheet?")
    st.caption("This slot was used, so in reality the equipment fit. If the stored sizes "
               "here overflow, the stored sizes are wrong (not the load sheet).")
    c1, c2, c3 = st.columns(3)
    races = sorted(work["race_id"].unique())
    race = c1.selectbox("Race", races)
    trailers = sorted(work[work.race_id == race]["trailer_name"].unique())
    trailer = c2.selectbox("Trailer", trailers)
    slots = sorted(work[(work.race_id == race) & (work.trailer_name == trailer)]["slot"].unique())
    slot = c3.selectbox("Slot", slots)

    sub = work[(work.race_id == race) & (work.trailer_name == trailer) & (work.slot == slot)]
    sg = slot_geometry(int(slot), geom)
    items = [Item(int(r.equipment_id), float(r.eq_length), float(r.eq_width),
                  str(r.equipment_desc)) for _, r in sub.iterrows()
             if not r.dims_missing and pd.notna(r.eq_length) and r.eq_length > 0
             and pd.notna(r.eq_width) and r.eq_width > 0]
    fits, used = _fits_axis(items, sg.length, sg.width, gap) if items else (True, 0.0)

    kind = "dancefloor" if int(slot) in DANCEFLOOR_SLOTS else "general"
    st.write(f"**Slot {slot}** ({kind}): usable **{sg.length:.0f} × {sg.width:.0f} in** · "
             f"{len(items)} item(s) with dims · gap {gap} in")
    if fits:
        st.markdown(f"### ✅ Stored sizes are CONSISTENT  \n"
                    f"packed {used:.1f} in ≤ capacity {sg.length:.0f} in — no contradiction.")
    else:
        over = used - sg.length
        st.markdown(f"### ❌ Stored sizes CONTRADICT this load sheet by {over:.1f} in  \n"
                    f"stored packing needs {used:.1f} in but this slot (which worked) is "
                    f"{sg.length:.0f} in → at least one stored size here is too big.")
    # flag any item whose shorter side alone exceeds the slot width
    wide = [it for it in items if min(it.length, it.width) > sg.width + 1e-9]
    if wide:
        st.markdown("⚠️ Too wide for this slot even rotated (stored width must be wrong): "
                    + ", ".join(f"`{it.label}` ({it.length:.0f}×{it.width:.0f})" for it in wide))
    show = sub[["equipment_id", "serial_number", "equipment_desc",
                "eq_length", "eq_width", "eq_height", "dims_missing"]]
    st.dataframe(show, use_container_width=True, hide_index=True)

st.divider()
st.caption("Data: Champschedule (load sheet) ⋈ WMS/modx (equipment dims), 2026 season. "
           "Load sheet is assumed correct; flagged equipment should be physically re-scanned.")
