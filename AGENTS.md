## Learned User Preferences

- Packing and anomaly analysis must be floor-level (dance vs general), not per-slot; slot numbers only classify which floor an item rode on.
- Streamlit UI should expose prominent race and trailer filters supporting three scopes: one race + all trailers, all races + one trailer, and one race + one trailer.
- Prefer a simplified UI centered on two floor categories with fail/ambiguous counts and equipment drill-down, not slot-centric tabs or tables.
- When design options are clear, prefer agentic decisions over long option menus; the user often locks the recommended option quickly.

## Learned Workspace Facts

- trailer-anomaly is a Streamlit + Pandas dimension anomaly detector (not a packing/assignment engine): load sheets are ground truth, and overflow means stored WMS dimensions are wrong.
- Analysis unit is `(race, trailer, floor)`: dance = slots 1–2 (default 129×98 in), general = slots 3–10 (default 483×98 in).
- Floor packing uses 2D rectangle packing with per-item 90° rotation and harness gap (default 2 in); blame uses leave-one-out and cross-race isolation into PASS / FAIL / AMBIGUOUS / UNKNOWN.
- Core modules are `app/floor_geom.py`, `app/analysis.py`, and `app/streamlit_app.py`; design is locked in `docs/DESIGN.md`; primary data is `data/loadsheet_2026.csv`.
- Trailer categories are name-pattern based (T-Series, T-Series Top, F-Series, Other) via `app/trailer_categories.py`; each category has independently tunable dance/general floor dimensions in the sidebar, all defaulting to the original global values.
- Race/trailer selection is multi-select (`st.multiselect`, all races selected by default) and triggers full reprocessing (`analyze()` re-run on exactly the selected subset), not just display filtering; trailer options are re-derived from the race selection to keep them in sync.
- Verified/resolved equipment is tracked in `data/checklist.db` (SQLite, `app/checklist_store.py`) and excluded from blame candidacy in `analyze()`, forcing a `RESOLVED` status distinct from `PASS`. Dimension corrections (edited L×W) live in the same DB's `dimension_correction` table, feed `dim_overrides` into `analyze()`/`build_used_floors()`, and export as a downloadable WMS corrections CSV.
- Packing is visualized as one continuous trailer strip per race (dance nose end-to-end with general rear; no stacked/separate floor boxes) via Plotly (`app/packing_viz.py`, `render_trailer_figure`). Boxes label name, ID, and on-file L×W. Per-trailer detail (equipment table + diagram + verify/dim-edit controls) is rendered lazily behind an Expand/Collapse toggle tracked in `st.session_state["expanded_trailers"]`, since Streamlit's `st.expander` always renders its children regardless of collapsed state and rendering all ~30 trailers' full detail at once made the page unresponsive.
