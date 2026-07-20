# Trailer Floor Anomaly Detector (2026 season)

Flags equipment whose **stored dimensions are likely wrong**. Premise: the 2026 load
sheet is **trusted** — equipment that rode on a trailer floor *did* fit. Slot numbers
only classify **dance floor** (1–2) vs **general floor** (3–10). Each floor is one
rectangle; we 2D-pack stored sizes into it. If they cannot pack, the stored dims are
the suspect → pass/fail list for manual scanner verification.

## Layout
```
trailer-anomaly/
├── .venv/                 Python virtualenv
├── data/                  exported CSVs (the analysis input)
│   ├── loadsheet_2026.csv    5,613 assignments, dims joined
│   ├── equipment_2026.csv    284 distinct equipment
│   ├── trailers_2026.csv     30 trailers + view class
│   ├── slots_2026.csv        slot occupancy (reference)
│   └── checklist.db          local SQLite verification state (gitignored)
├── app/                   the analyzer
│   ├── floor_geom.py         floor dims + 2D packer (rotation, gaps)
│   ├── analysis.py           floor-level engine + blame isolation
│   ├── trailer_categories.py trailer name -> category classification + per-category geometry
│   ├── checklist_store.py    SQLite-backed equipment verification store
│   ├── packing_viz.py        Plotly packing diagram renderer
│   ├── test_logic.py         unit tests
│   └── streamlit_app.py      the UI
└── docs/DESIGN.md         full design + locked decisions
```

> The data-export step (which connects to the production databases with credentials)
> is intentionally **not** part of this repository. The `data/*.csv` snapshots it
> produced are committed so the app runs standalone.

## Run

```bash
cd trailer-anomaly-detector
uv sync
uv run streamlit run app/streamlit_app.py
```

Open the local URL Streamlit prints. To run the tests: `uv run python app/test_logic.py`.

## How it works
- **Premise**: load sheets are ground truth. Stored WMS dims are tested against them.
- **Two floors**: dance (129×98 in) and general (483×98 in) by default. Trailers are
  classified into categories by name pattern (`T-Series`, `T-Series Top`, `F-Series`,
  `Other` — see `app/trailer_categories.py`), and each category's floor dimensions are
  independently tunable in the sidebar. Items from slots 1–2 pool into dance; slots
  3–10 into general — per race + trailer.
- **Packing**: MaxRects 2D packing with per-item 90° rotation and a harness gap.
- **Buckets**: `PASS` · `FAIL` (unique blame) · `AMBIGUOUS` · `UNKNOWN` · `RESOLVED`
  (manually verified — excluded from blame candidacy on the next reprocess).
- **Blame**: leave-one-out + cross-race isolation when possible.
- **UI**: multi-select races and trailers (all selected by default); changing the
  selection **reprocesses** analysis on exactly that subset rather than filtering a
  season-wide result. Trailer options stay in sync with the race selection. Each
  selected trailer is a lazily-expandable row showing fail/ambiguous counts; expanding
  it shows the equipment table and a combined Plotly packing diagram (dance + general
  floor) per race, plus checkboxes to mark equipment as manually verified.

## Data sources
The committed `data/*.csv` were produced from two internal databases:
- **Champschedule** (PostgreSQL): the load sheet (race → trailer → slot → equipment).
- **WMS** (MySQL): equipment physical dimensions.
Joined on `equipment_id`. The extraction script and its credentials live outside this
repository; only the resulting read-only snapshots are committed.
