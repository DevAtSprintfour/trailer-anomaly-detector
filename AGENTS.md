## Learned User Preferences

- Packing and anomaly analysis must be floor-level (dance vs general), not per-slot; slot numbers only classify which floor an item rode on.
- Streamlit UI should expose prominent race and trailer filters supporting three scopes: one race + all trailers, all races + one trailer, and one race + one trailer.
- Prefer a simplified UI centered on two floor categories with fail/ambiguous counts and equipment drill-down, not slot-centric tabs or tables.
- When design options are clear, prefer agentic decisions over long option menus; the user often locks the recommended option quickly.

## Learned Workspace Facts

- trailer-anomaly is a Streamlit + Pandas dimension anomaly detector (not a packing/assignment engine): load sheets are ground truth, and overflow means stored WMS dimensions are wrong.
- Analysis unit is `(race, trailer, floor)`: dance = slots 1–2 (default 129×98 in), general = slots 3–10 (default 483×98 in).
- Floor packing uses 2D rectangle packing with per-item 90° rotation and harness gap (default 2 in); blame uses leave-one-out and cross-race isolation into PASS / FAIL / AMBIGUOUS / UNKNOWN.
- Core modules are `app/geometry.py`, `app/analysis.py`, and `app/streamlit_app.py`; design is locked in `docs/DESIGN.md`; primary data is `data/loadsheet_2026.csv`.
