"""Trailer Floor Anomaly Detector — Streamlit UI.

Run from the project root:
    source .venv/bin/activate
    streamlit run app/streamlit_app.py
"""
import os
from typing import Dict

import pandas as pd
import streamlit as st

from floor_geom import (
    DEFAULT_GEOM, Item, pack_floor, floor_geometry, floor_for_slot,
    FLOOR_DANCE, FLOOR_GENERAL,
)
from analysis import (
    analyze, summarize, build_used_floors,
    PASS, FAIL, AMBIGUOUS, UNKNOWN, RESOLVED,
)
from trailer_categories import (
    classify_trailer, DEFAULT_CATEGORY_GEOM, ALL_CATEGORIES,
)
from checklist_store import ChecklistStore
from packing_viz import render_trailer_figure

DATA = os.path.join(os.path.dirname(__file__), "..", "data")
STATUS_COLOR = {PASS: "#1a7f37", FAIL: "#cf222e", AMBIGUOUS: "#bf8700",
                UNKNOWN: "#6e7781", RESOLVED: "#1568a8"}

st.set_page_config(page_title="Trailer Floor Anomaly Detector", layout="wide")


@st.cache_data
def load_data(_ls_mtime: float, _races_mtime: float):
    """Load loadsheet and always attach race_name from races_2026.csv.

    mtime args bust Streamlit's cache when the CSVs change on disk.
    """
    ls = pd.read_csv(os.path.join(DATA, "loadsheet_2026.csv"))
    races_path = os.path.join(DATA, "races_2026.csv")
    if os.path.exists(races_path):
        races = pd.read_csv(races_path)[["race_id", "race_name"]].drop_duplicates("race_id")
        if "race_name" in ls.columns:
            ls = ls.drop(columns=["race_name"])
        ls = ls.merge(races, on="race_id", how="left")
    return ls


_ls_path = os.path.join(DATA, "loadsheet_2026.csv")
_races_path = os.path.join(DATA, "races_2026.csv")
ls = load_data(
    os.path.getmtime(_ls_path),
    os.path.getmtime(_races_path) if os.path.exists(_races_path) else 0.0,
)

CHECKLIST_DB = os.path.join(DATA, "checklist.db")
checklist = ChecklistStore(CHECKLIST_DB)
verified_ids = checklist.get_verified_ids()

# ------------------------------------------------------------------ sidebar
st.sidebar.title("Controls")
st.sidebar.caption("2026 season · load sheet trusted · floor-level 2D packing")
if st.sidebar.button("Reload data (clear cache)"):
    st.cache_data.clear()
    st.rerun()

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

category_geom: dict = {}
with st.sidebar.expander("Floor dimensions by trailer category (tunable)", expanded=False):
    st.caption(
        "Each trailer-name pattern (see trailer_categories.py) gets its own "
        "dance/general floor size. All categories start at the same default "
        "and can be tuned independently."
    )
    for cat in ALL_CATEGORIES:
        st.markdown(f"**{cat}**")
        defaults = DEFAULT_CATEGORY_GEOM[cat]
        ca, cb = st.columns(2)
        dl = ca.number_input("Dance length (in)", value=float(defaults["dancefloor_length"]),
                             min_value=1.0, step=1.0, key=f"dl_{cat}")
        dw = cb.number_input("Dance width (in)", value=float(defaults["dancefloor_width"]),
                             min_value=1.0, step=1.0, key=f"dw_{cat}")
        cc, cd = st.columns(2)
        gl = cc.number_input("General length (in)", value=float(defaults["general_length"]),
                             min_value=1.0, step=1.0, key=f"gl_{cat}")
        gw = cd.number_input("General width (in)", value=float(defaults["general_width"]),
                             min_value=1.0, step=1.0, key=f"gw_{cat}")
        category_geom[cat] = dict(dancefloor_length=dl, dancefloor_width=dw,
                                  general_length=gl, general_width=gw)
    if st.button("Reset all categories to defaults"):
        for cat in ALL_CATEGORIES:
            for prefix in ("dl_", "dw_", "gl_", "gw_"):
                st.session_state.pop(f"{prefix}{cat}", None)
        st.rerun()

# geom stays as the flat legacy fallback for any category not in category_geom
# (shouldn't happen since every ALL_CATEGORIES entry is always populated above,
# but build_used_floors/analyze still accept a fallback for safety).
geom = dict(DEFAULT_GEOM)

# ------------------------------------------------------------------ data + season-wide hints
work = ls[ls["trailer_view"].isin(sel_views)].copy()
work["floor"] = work["slot"].map(floor_for_slot)

# Season-wide overflow hints for dropdown ⚠ badges only — NOT the reprocessing
# scope. These are computed once over every race/trailer so a badge can say
# "this trailer has an overflow somewhere" before you even select it.
season_floors = build_used_floors(work, geom, category_geom)
overflow_pairs = set()  # (race_id, trailer_name)
overflow_trailers = set()
overflow_races = set()
for f in season_floors:
    if not f.items:
        continue
    if not pack_floor(f.items, f.cap_length, f.cap_width, gap).fits:
        overflow_pairs.add((f.race_id, f.trailer_name))
        overflow_trailers.add(f.trailer_name)
        overflow_races.add(f.race_id)

eq_meta = (work[["equipment_id", "serial_number", "equipment_desc",
                 "eq_length", "eq_width"]]
           .drop_duplicates("equipment_id").set_index("equipment_id"))

race_labels = {}
race_label_to_id = {}
for rid, g in work.groupby("race_id"):
    rid = int(rid)
    names = []
    if "race_name" in g.columns:
        names = [n for n in g["race_name"].dropna().unique().tolist() if str(n).strip()]
    name = str(names[0]).strip() if names else f"Race {rid}"
    dates = g["race_date"].dropna().unique()
    date = str(dates[0])[:10] if len(dates) else None
    mark = " ⚠" if rid in overflow_races else ""
    if date:
        label = f"{name} ({date}){mark}"
    else:
        label = f"{name}{mark}"
    race_labels[rid] = label
    race_label_to_id[label] = rid


def trailer_option_label(tname: str) -> str:
    """Mark trailers that have a floor overflow in ANY race this season."""
    has = tname in overflow_trailers
    return f"{tname} ⚠ overflow" if has else tname


def status_rank(s):
    return s.map({FAIL: 0, AMBIGUOUS: 1, UNKNOWN: 2, RESOLVED: 3, PASS: 4})


def color_status(v):
    return f"color: {STATUS_COLOR.get(v, '#000')}; font-weight:600"


def equipment_table(eids, verdict):
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

# ------------------------------------------------------------------ multi-select filter + reprocess
st.subheader("Filter")
st.caption(
    "Select one or more races and one or more trailers. All races are "
    "selected by default. The trailer list updates to match your race "
    "selection, and changing the selection **reprocesses** analysis on "
    "exactly that subset — it does not just re-filter a season-wide result."
)

all_race_ids = sorted(race_labels)
f1, f2 = st.columns(2)
with f1:
    prev_races = st.session_state.get("filter_races")
    if prev_races is not None:
        valid = [r for r in prev_races if r in all_race_ids]
        if valid != prev_races:
            st.session_state["filter_races"] = valid or all_race_ids
    sel_race_ids = st.multiselect(
        "Races", all_race_ids, default=all_race_ids,
        format_func=lambda r: race_labels.get(r, str(r)),
        key="filter_races",
    )
if not sel_race_ids:
    sel_race_ids = all_race_ids  # never allow an empty race scope

trailers_available = work[work.race_id.isin(sel_race_ids)]
trailer_names_all = sorted(trailers_available["trailer_name"].dropna().unique().tolist())


def _trailer_sort_key(t):
    has = any((rid, t) in overflow_pairs for rid in sel_race_ids)
    return (0 if has else 1, t)


trailer_names_all = sorted(trailer_names_all, key=_trailer_sort_key)

with f2:
    prev_trailers = st.session_state.get("filter_trailers")
    if prev_trailers is not None:
        valid_t = [t for t in prev_trailers if t in trailer_names_all]
        if valid_t != prev_trailers:
            st.session_state["filter_trailers"] = valid_t or trailer_names_all
    sel_trailers = st.multiselect(
        "Trailers", trailer_names_all, default=trailer_names_all,
        format_func=trailer_option_label,
        key="filter_trailers",
    )
if not sel_trailers:
    sel_trailers = trailer_names_all  # never allow an empty trailer scope

# --- Reprocess (not just filter) on exactly the selected races + trailers ---
scoped = work[work.race_id.isin(sel_race_ids) & work.trailer_name.isin(sel_trailers)].copy()
verdict = analyze(scoped, gap=gap, geom=geom, cross_reference=cross_ref,
                  category_geom=category_geom, verified=verified_ids)
scoped_eids = set(scoped["equipment_id"].dropna().astype(int))

st.info(
    f"Reprocessed: **{len(sel_race_ids)}** race(s) selected of {len(all_race_ids)} · "
    f"**{len(sel_trailers)}** trailer(s) selected of {len(trailer_names_all)}  \n"
    f"({len(scoped)} load-sheet rows · {scoped['equipment_id'].nunique()} equipment)"
)

st.divider()

# ------------------------------------------------------------------ per-trailer detail (lazy)
st.subheader("Trailers")
st.caption(
    "One row per selected trailer with fail/ambiguous counts up front. Click "
    "**Expand** to render its equipment list and packing diagram per floor "
    "— split per race when more than one race is selected. Only expanded "
    "trailers render tables/diagrams, so selecting many races/trailers stays "
    "fast. Check \"Verified\" on an item once you've physically confirmed "
    "its stored dimensions are correct; this reprocesses the rest of that "
    "floor excluding it from blame."
)

floors_by_trailer: Dict[str, list] = {}
for f in build_used_floors(scoped, geom, category_geom):
    floors_by_trailer.setdefault(f.trailer_name, []).append(f)

expanded_trailers = st.session_state.setdefault("expanded_trailers", set())

for tname in sorted(sel_trailers, key=_trailer_sort_key):
    tfloors = floors_by_trailer.get(tname, [])
    trailer_eids = set(scoped[scoped.trailer_name == tname]["equipment_id"].dropna().astype(int))
    t_verdicts = {e: verdict[e] for e in trailer_eids if e in verdict}
    n_fail = sum(1 for v in t_verdicts.values() if v["status"] == FAIL)
    n_amb = sum(1 for v in t_verdicts.values() if v["status"] == AMBIGUOUS)
    category = classify_trailer(tname)
    is_expanded = tname in expanded_trailers

    row_l, row_r = st.columns([5, 1])
    row_l.markdown(f"**{tname}** ({category}) — {n_fail} failed, {n_amb} ambiguous")
    btn_label = "Collapse ▴" if is_expanded else "Expand ▾"
    if row_r.button(btn_label, key=f"toggle_{tname}"):
        if is_expanded:
            expanded_trailers.discard(tname)
        else:
            expanded_trailers.add(tname)
        st.rerun()

    if not is_expanded:
        st.divider()
        continue

    with st.container(border=True):
        if not tfloors:
            st.write("No load-sheet rows for this trailer in the selected scope.")
            st.divider()
            continue

        races_here = sorted({f.race_id for f in tfloors})
        multi_race = len(races_here) > 1

        trailer_resolved_geom = category_geom.get(category, geom)
        dance_fg = floor_geometry(FLOOR_DANCE, trailer_resolved_geom)
        general_fg = floor_geometry(FLOOR_GENERAL, trailer_resolved_geom)
        # every UsedFloor for this trailer resolved geometry from the same
        # category, so any floor's trailer_id is the trailer's id
        trailer_id = tfloors[0].trailer_id

        for rid in races_here:
            if multi_race:
                st.markdown(f"##### {race_labels.get(rid, rid)}")
            race_floors = [f for f in tfloors if f.race_id == rid]
            dance_f = next((f for f in race_floors if f.floor == FLOOR_DANCE), None)
            general_f = next((f for f in race_floors if f.floor == FLOOR_GENERAL), None)

            dance_items = dance_f.items if dance_f else []
            general_items = general_f.items if general_f else []
            dance_result = pack_floor(dance_items, dance_fg.length, dance_fg.width, gap)
            general_result = pack_floor(general_items, general_fg.length, general_fg.width, gap)

            ids_here = {it.equipment_id for it in dance_items} | {it.equipment_id for it in general_items}
            tbl = equipment_table(ids_here, verdict)
            st.dataframe(
                tbl.style.map(color_status, subset=["status"]),
                use_container_width=True, hide_index=True,
            )

            fig = render_trailer_figure(
                dance_fg, dance_items, dance_result,
                general_fg, general_items, general_result,
                verdict,
            )
            st.plotly_chart(fig, use_container_width=True,
                            key=f"chart_{tname}_{rid}")

            for eid in sorted(ids_here):
                v = verdict.get(eid)
                if v is None or v["status"] not in (FAIL, AMBIGUOUS):
                    continue
                floor_key = FLOOR_DANCE if any(it.equipment_id == eid for it in dance_items) else FLOOR_GENERAL
                already = eid in verified_ids
                c_check, c_note = st.columns([1, 3])
                checked = c_check.checkbox(
                    f"Verified #{eid}", value=already,
                    key=f"verify_{eid}_{rid}_{trailer_id}_{floor_key}",
                )
                note = c_note.text_input(
                    "Note", value="", label_visibility="collapsed",
                    placeholder="why this is actually correct",
                    key=f"note_{eid}_{rid}_{trailer_id}_{floor_key}",
                )
                if checked and not already:
                    checklist.mark_verified(eid, rid, trailer_id, floor_key, note)
                    st.rerun()
                elif not checked and already:
                    checklist.unmark_verified(eid, rid, trailer_id, floor_key)
                    st.rerun()
    st.divider()

# ------------------------------------------------------------------ summary across selected scope
st.subheader("Summary across selected scope")
k1, k2, k3, k4, k5 = st.columns(5)
scoped_verdicts = {e: verdict[e] for e in scoped_eids if e in verdict}
scoped_counts = summarize(scoped_verdicts) if scoped_verdicts else {
    PASS: 0, FAIL: 0, AMBIGUOUS: 0, UNKNOWN: 0, RESOLVED: 0,
}
k1.metric("Equipment in scope", len(scoped_verdicts))
k2.metric("Consistent", scoped_counts[PASS])
k3.metric("Stored dim wrong", scoped_counts[FAIL])
k4.metric("Ambiguous", scoped_counts[AMBIGUOUS])
k5.metric("Resolved (verified)", scoped_counts[RESOLVED])

fails = equipment_table({e for e in scoped_eids if verdict.get(e, {}).get("status") == FAIL}, verdict)
if not fails.empty:
    st.write(f"**{len(fails)}** equipment with stored sizes that contradict a working floor load.")
    st.dataframe(fails.style.map(color_status, subset=["status"]),
                 use_container_width=True, hide_index=True)
    st.download_button("Download good-fail list (CSV)",
                       fails.to_csv(index=False), "good_fail_list_2026.csv", "text/csv")
else:
    st.success("No uniquely blamed failures in this scope.")

amb_ids = {e for e in scoped_eids if verdict.get(e, {}).get("status") == AMBIGUOUS}
if amb_ids:
    with st.expander(f"Ambiguous ({len(amb_ids)}) — scan the group"):
        amb = equipment_table(amb_ids, verdict)
        st.dataframe(amb.style.map(color_status, subset=["status"]),
                     use_container_width=True, hide_index=True)

unk_ids = {e for e in scoped_eids if verdict.get(e, {}).get("status") == UNKNOWN}
if unk_ids:
    with st.expander(f"Unknown dims ({len(unk_ids)})"):
        unk = equipment_table(unk_ids, verdict)
        st.dataframe(unk[["equipment_id", "serial", "description", "reason"]],
                     use_container_width=True, hide_index=True)

with st.expander("All verification history"):
    records = checklist.list_records()
    if records:
        st.dataframe(pd.DataFrame(records), use_container_width=True, hide_index=True)
    else:
        st.write("Nothing verified yet.")

st.caption(
    "Data: Champschedule (load sheet) ⋈ WMS (equipment dims), 2026. "
    "Selecting races/trailers reprocesses analysis on exactly that subset — "
    "it is not a display-only filter."
)
