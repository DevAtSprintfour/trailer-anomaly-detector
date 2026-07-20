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
dim_overrides = checklist.get_dimension_corrections()

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
season_floors = build_used_floors(work, geom, category_geom, dim_overrides)
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


def status_badge(status: str) -> str:
    """Inline HTML badge matching table STATUS_COLOR."""
    color = STATUS_COLOR.get(status, "#6e7781")
    return (
        f'<span style="color:{color};font-weight:700;padding:0.1rem 0.45rem;'
        f'border:1px solid {color};border-radius:4px;font-size:0.85em">'
        f"{status}</span>"
    )


FLOOR_BADGE_COLOR = {FLOOR_DANCE: "#a56b00", FLOOR_GENERAL: "#1568a8"}


def floor_badge(floor_key: str) -> str:
    """Inline HTML badge distinguishing dance vs general floor."""
    color = FLOOR_BADGE_COLOR.get(floor_key, "#6e7781")
    return (
        f'<span style="color:{color};font-weight:700;padding:0.1rem 0.45rem;'
        f'border:1px solid {color};border-radius:4px;font-size:0.85em">'
        f"{floor_key} floor</span>"
    )


def effective_dims(eid):
    """Return (L, W) after applying any user dimension correction."""
    if eid in dim_overrides:
        return dim_overrides[eid]
    if eid in eq_meta.index:
        return (eq_meta.loc[eid]["eq_length"], eq_meta.loc[eid]["eq_width"])
    return (None, None)


def equipment_table(eids, verdict):
    rows = []
    for eid in eids:
        if eid not in verdict:
            continue
        v = verdict[eid]
        meta = eq_meta.loc[eid] if eid in eq_meta.index else None
        wf = v.get("worst_floor") or {}
        L, W = effective_dims(eid)
        rows.append(dict(
            equipment_id=eid,
            serial=(meta["serial_number"] if meta is not None else None),
            description=(meta["equipment_desc"] if meta is not None else None),
            stored_L=L,
            stored_W=W,
            dims_corrected=(eid in dim_overrides),
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

# ------------------------------------------------------------------ race + trailer filter + reprocess
st.subheader("Filter")
st.caption(
    "Select **one race** and one or more trailers. The trailer list updates "
    "to match the race, and changing the selection **reprocesses** analysis "
    "on exactly that subset — it does not just re-filter a season-wide result."
)

all_race_ids = sorted(race_labels)
# Migrate old multi-race session key if present.
if "filter_races" in st.session_state and "filter_race" not in st.session_state:
    _old = st.session_state.pop("filter_races")
    if isinstance(_old, list) and _old:
        st.session_state["filter_race"] = _old[0]
    elif isinstance(_old, int):
        st.session_state["filter_race"] = _old
elif "filter_races" in st.session_state:
    st.session_state.pop("filter_races", None)

default_race = all_race_ids[0] if all_race_ids else None
# Prefer Chicago 2026-07-05 (race_id 446) when present in the filtered set.
DEFAULT_RACE_ID = 446
if DEFAULT_RACE_ID in all_race_ids:
    default_race = DEFAULT_RACE_ID
elif all_race_ids:
    # Fallback: first race that has a floor overflow badge.
    for rid in all_race_ids:
        if rid in overflow_races:
            default_race = rid
            break

f1, f2 = st.columns(2)
with f1:
    if st.session_state.get("filter_race") not in all_race_ids:
        st.session_state["filter_race"] = default_race
    sel_race = st.selectbox(
        "Race", all_race_ids,
        format_func=lambda r: race_labels.get(r, str(r)),
        key="filter_race",
    )
sel_race_ids = [sel_race] if sel_race is not None else []

trailers_available = work[work.race_id.isin(sel_race_ids)]
trailer_names_all = sorted(trailers_available["trailer_name"].dropna().unique().tolist())


def _trailer_sort_key(t):
    has = (sel_race, t) in overflow_pairs if sel_race is not None else False
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

# --- Reprocess (not just filter) on exactly the selected race + trailers ---
scoped = work[work.race_id.isin(sel_race_ids) & work.trailer_name.isin(sel_trailers)].copy()
verdict = analyze(scoped, gap=gap, geom=geom, cross_reference=cross_ref,
                  category_geom=category_geom, verified=verified_ids,
                  dim_overrides=dim_overrides)
scoped_eids = set(scoped["equipment_id"].dropna().astype(int))

st.info(
    f"Reprocessed: **{race_labels.get(sel_race, sel_race)}** · "
    f"**{len(sel_trailers)}** trailer(s) of {len(trailer_names_all)}  \n"
    f"({len(scoped)} load-sheet rows · {scoped['equipment_id'].nunique()} equipment)"
)

st.divider()

# ------------------------------------------------------------------ per-trailer detail (lazy)
st.subheader("Trailers")
st.caption(
    "One row per selected trailer with fail/ambiguous counts up front. Click "
    "**Expand** to see every piece of equipment on that trailer for the "
    "selected race. Everything is drawn on the trailer floor rectangle; "
    "overlaps use translucent hatch + dashed outlines. Every box shows name, "
    "ID, and L×W. Dance (warm) / general (cool) share one outline. Check "
    "**Verified** or edit L×W inline; download WMS corrections at the bottom."
)

floors_by_trailer: Dict[str, list] = {}
for f in build_used_floors(scoped, geom, category_geom, dim_overrides):
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
            st.write("No load-sheet rows for this trailer in the selected race.")
            st.divider()
            continue

        trailer_resolved_geom = category_geom.get(category, geom)
        dance_fg = floor_geometry(FLOOR_DANCE, trailer_resolved_geom)
        general_fg = floor_geometry(FLOOR_GENERAL, trailer_resolved_geom)
        trailer_id = tfloors[0].trailer_id
        rid = int(sel_race)

        dance_f = next((f for f in tfloors if f.floor == FLOOR_DANCE), None)
        general_f = next((f for f in tfloors if f.floor == FLOOR_GENERAL), None)

        dance_items = dance_f.items if dance_f else []
        general_items = general_f.items if general_f else []
        dance_result = pack_floor(dance_items, dance_fg.length, dance_fg.width, gap)
        general_result = pack_floor(general_items, general_fg.length, general_fg.width, gap)

        dance_ids = {it.equipment_id for it in dance_items}
        general_ids = {it.equipment_id for it in general_items}
        ids_here = dance_ids | general_ids

        dance_tbl = equipment_table(dance_ids, verdict)
        general_tbl = equipment_table(general_ids, verdict)
        tbl_l, tbl_r = st.columns(2)
        with tbl_l:
            st.markdown(f"**Dance floor** ({len(dance_ids)})")
            if not dance_tbl.empty:
                st.dataframe(
                    dance_tbl.style.map(color_status, subset=["status"]),
                    use_container_width=True, hide_index=True,
                )
            else:
                st.caption("No equipment on this floor.")
        with tbl_r:
            st.markdown(f"**General floor** ({len(general_ids)})")
            if not general_tbl.empty:
                st.dataframe(
                    general_tbl.style.map(color_status, subset=["status"]),
                    use_container_width=True, hide_index=True,
                )
            else:
                st.caption("No equipment on this floor.")

        fig = render_trailer_figure(
            dance_fg, dance_items,
            general_fg, general_items,
            verdict, gap=gap,
            dance_result=dance_result,
            general_result=general_result,
        )
        st.plotly_chart(fig, use_container_width=True,
                        key=f"chart_{tname}_{rid}")

        for eid in sorted(ids_here):
            v = verdict.get(eid)
            if v is None:
                continue
            needs_action = v["status"] in (FAIL, AMBIGUOUS) or eid in dim_overrides
            if not needs_action:
                continue
            floor_key = FLOOR_DANCE if any(it.equipment_id == eid for it in dance_items) else FLOOR_GENERAL
            meta = eq_meta.loc[eid] if eid in eq_meta.index else None
            orig_L = float(meta["eq_length"]) if meta is not None and pd.notna(meta["eq_length"]) else 0.0
            orig_W = float(meta["eq_width"]) if meta is not None and pd.notna(meta["eq_width"]) else 0.0
            cur_L, cur_W = dim_overrides.get(eid, (orig_L, orig_W))
            desc = meta["equipment_desc"] if meta is not None else eid
            st.markdown(
                f"**#{eid}** — {desc} · {status_badge(v['status'])} · "
                f"{floor_badge(floor_key)}",
                unsafe_allow_html=True,
            )

            c_L, c_W, c_reset = st.columns([1, 1, 1])
            new_L = c_L.number_input(
                "Length (in)", min_value=0.0, step=1.0, value=float(cur_L or 0.0),
                key=f"dimL_{eid}_{rid}_{trailer_id}",
            )
            new_W = c_W.number_input(
                "Width (in)", min_value=0.0, step=1.0, value=float(cur_W or 0.0),
                key=f"dimW_{eid}_{rid}_{trailer_id}",
            )
            if c_reset.button("Reset dims", key=f"dimReset_{eid}_{rid}_{trailer_id}"):
                checklist.clear_dimension_correction(eid)
                st.session_state.pop(f"dimL_{eid}_{rid}_{trailer_id}", None)
                st.session_state.pop(f"dimW_{eid}_{rid}_{trailer_id}", None)
                st.rerun()

            target = (float(new_L), float(new_W))
            current = dim_overrides.get(eid)
            original = (float(orig_L), float(orig_W))
            if current is None and target != original and new_L > 0 and new_W > 0:
                checklist.set_dimension_correction(
                    eid, new_L, new_W, orig_L, orig_W,
                )
                st.rerun()
            elif current is not None and target != (float(current[0]), float(current[1])):
                if target == original or new_L <= 0 or new_W <= 0:
                    checklist.clear_dimension_correction(eid)
                else:
                    checklist.set_dimension_correction(
                        eid, new_L, new_W, orig_L, orig_W,
                    )
                st.rerun()

            if v["status"] in (FAIL, AMBIGUOUS):
                already = eid in verified_ids
                c_check, c_note = st.columns([1, 3])
                checked = c_check.checkbox(
                    f"Verified #{eid} (dims correct as stored)",
                    value=already,
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

# ------------------------------------------------------------------ WMS dimension corrections export
st.subheader("WMS dimension corrections")
corr_rows = checklist.list_dimension_corrections()
if corr_rows:
    corr_df = pd.DataFrame(corr_rows)
    # Enrich with serial / description from the load sheet when available.
    meta_cols = eq_meta.reset_index()[["equipment_id", "serial_number", "equipment_desc"]]
    corr_df = corr_df.merge(meta_cols, on="equipment_id", how="left")
    export_cols = [
        "equipment_id", "serial_number", "equipment_desc",
        "original_length", "original_width",
        "corrected_length", "corrected_width",
        "note", "corrected_at",
    ]
    export_df = corr_df[[c for c in export_cols if c in corr_df.columns]]
    st.write(
        f"**{len(export_df)}** equipment dimension(s) to update in WMS. "
        "Apply these corrected L×W values in the main database."
    )
    st.dataframe(export_df, use_container_width=True, hide_index=True)
    st.download_button(
        "Download WMS corrections (CSV)",
        export_df.to_csv(index=False),
        "wms_dimension_corrections.csv",
        "text/csv",
        type="primary",
    )
else:
    st.info(
        "No dimension corrections yet. Expand a trailer with fails/ambiguous "
        "items and edit Length/Width inline — corrections appear here for download."
    )

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
