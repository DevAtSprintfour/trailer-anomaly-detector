## Learned User Preferences

- Packing and anomaly analysis must be floor-level (dance vs general), not per-slot; slot numbers only classify which floor an item rode on.
- Streamlit UI exposes a single-race selectbox plus multi-select trailers (trailer options re-derived from the selected race) so analysis can be reprocessed for that exact subset.
- Prefer a simplified UI centered on two floor categories with fail/ambiguous counts and equipment drill-down, not slot-centric tabs or tables.
- When design options are clear, prefer agentic decisions over long option menus; the user often locks the recommended option quickly.
- Expanded packing viz must be one continuous trailer rectangle with dance (nose) and general (rear) sections inside — not two separate floor diagrams.
- Diagram labels must match table analysis statuses (FAIL/AMBIGUOUS), not a separate "OVERFLOW" vocabulary; pack failures are those same blame rows.
- Display packing must use the same `pack_floor` / best-effort placements as analysis — never invent alternate layouts that make non-fitting items look packed.

## Learned Workspace Facts

- trailer-anomaly is a Streamlit + Pandas dimension anomaly detector (not a packing/assignment engine): load sheets are ground truth, and overflow means stored WMS dimensions are wrong.
- Analysis unit is `(race, trailer, floor)`: dance = slots 1–2 (default 129×98 in), general = slots 3–10 (default 483×98 in).
- Floor packing uses 2D rectangle packing with per-item 90° rotation and harness gap (default 2 in); blame uses leave-one-out and cross-race isolation into PASS / FAIL / AMBIGUOUS / UNKNOWN.
- Core modules are `app/floor_geom.py`, `app/analysis.py`, and `app/streamlit_app.py`; design is locked in `docs/DESIGN.md`; primary data is `data/loadsheet_2026.csv`.
- Trailer categories are name-pattern based (T-Series, T-Series Top, F-Series, Other) via `app/trailer_categories.py`; each category has independently tunable dance/general floor dimensions in the sidebar, all defaulting to the original global values.
- Race selection is a single `st.selectbox` (exactly one race); trailer selection remains multi-select and triggers full reprocessing (`analyze()` re-run on exactly that race + trailer subset). Trailer options are re-derived from the race selection to keep them in sync.
- Verified/resolved equipment is tracked in `data/checklist.db` (SQLite, `app/checklist_store.py`) and excluded from blame candidacy in `analyze()`, forcing a `RESOLVED` status distinct from `PASS`. Dimension corrections (edited L×W) live in the same DB's `dimension_correction` table, feed `dim_overrides` into `analyze()`/`build_used_floors()`, and export as a downloadable WMS corrections CSV.
- Packing is visualized as one continuous trailer outline per expanded trailer (dance nose end-to-end with general rear, visually distinguished sections) via Plotly. Placements come from the same `pack_floor` / `pack_floor_best_effort` path as analysis (`display_pack`); every equipment box stays on the trailer rectangle, and overlaps use translucent hatch + dashed outlines. Per-trailer detail is lazy behind Expand/Collapse in `st.session_state["expanded_trailers"]`.
