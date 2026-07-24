# Trailer Floor Anomaly Detector (2026 season)

Flags equipment whose **stored dimensions are likely wrong**. Premise: the 2026 load
sheet is **trusted** — equipment that rode on a trailer *did* fit. Slot numbers only
classify **dance floor** (1–2) vs **general floor** (3–10). Each trailer is **one
continuous container** with a *soft* exclusion line at `x = dance_length`: dance items
anchor at the front, general items behind. We 2D-pack the stored sizes into it with an
**exact OR-Tools CP-SAT solve** (harness gap between items only). Each floor is packed
against its real length; an item that doesn't fit its floor is an overflow → its stored
dims are the suspect. Dance-floor overflow is flagged **ambiguous**, general-floor
overflow **failed** → pass/fail list for manual scanner verification.

The packing model is ported from `Champion/anomaly-detection/plot.py`.

## Layout
```
trailer-anomaly/
├── .venv/                 Python virtualenv
├── data/                  local state
│   └── checklist.db          local SQLite verification state (gitignored)
├── app/                   the analyzer
│   ├── loadsheet_source.py   reads the load sheet live from Postgres + MySQL
│   ├── cp_packer.py          OR-Tools CP-SAT container packer + AnomalyReport
│   ├── floor_geom.py         slot->side classification + ContainerSpec builder
│   ├── analysis.py           per-(race,trailer) engine + blame isolation
│   ├── trailer_categories.py trailer name -> category classification + per-category geometry
│   ├── checklist_store.py    SQLite-backed equipment verification store
│   ├── packing_viz.py        matplotlib packing diagram renderer (TrailerRenderer)
│   ├── test_logic.py         unit tests
│   └── streamlit_app.py      the UI
└── docs/DESIGN.md         full design + locked decisions
```

> The app reads its load sheet **directly from the production databases** at
> runtime (see [Data sources](#data-sources)); it needs credentials to start.

## Run

```bash
cd trailer-anomaly-detector
uv sync
uv run streamlit run app/streamlit_app.py
```

Open the local URL Streamlit prints. To run the tests: `uv run python app/test_logic.py`.

### Dev tooling
- **Lint + format**: `uv run ruff check` and `uv run ruff format`.
- **Type check**: `uv run ty check app/`.
- **Pre-commit**: `uv run pre-commit install` (runs ruff, ty, tests, and `uv-lock` on
  every commit); run manually with `uv run pre-commit run --all-files`.

## How it works
- **Premise**: load sheets are ground truth. Stored WMS dims are tested against them.
- **One container per trailer**: a `dance_length + general_length` × `width` rectangle
  (default `129 + 483` × `98` in) with a **soft** exclusion line at `x = dance_length`.
  Dance items (slots 1–2) are anchored at the nose but may extend past the line;
  general items (slots 3–10) start behind it. Trailers are classified into categories by
  name pattern (`T-Series`, `T-Series Top`, `F-Series`, `Other` — see
  `app/trailer_categories.py`), each with independently tunable dimensions in the sidebar.
- **Packing**: exact OR-Tools CP-SAT solve — each floor packed against its **real length**
  (dance 129, general 483), 90° rotation, harness gap **between items only** (never against
  walls, so a floor-length item fits). An item that doesn't fit its floor is an *overflow*.
- **Overflow severity by floor**: **dance-floor overflow → AMBIGUOUS**, **general-floor
  overflow → FAIL**. (Dance items are often longer than the 129-in dance floor, so dance
  overflow/ambiguous is common; widen a category's floor in the sidebar to clear it.)
- **Buckets**: `PASS` · `FAIL` (general-floor overflow) · `AMBIGUOUS` (dance-floor
  overflow) · `UNKNOWN` (missing dims) · `RESOLVED` (manually verified).
- **UI**: multi-select races and trailers (all selected by default); changing the
  selection **reprocesses** analysis on exactly that subset rather than filtering a
  season-wide result. Trailer options stay in sync with the race selection. Each
  selected trailer is a lazily-expandable row showing fail/ambiguous counts; expanding
  it shows the equipment table and a combined matplotlib packing diagram (one
  container: dance + general chambers) per race, plus checkboxes to mark equipment as
  manually verified.

## Data sources
The app reads the load sheet **live** (`app/loadsheet_source.py`) from two internal,
read-only databases, joined on `equipment_id`:
- **Champschedule** (PostgreSQL): the load sheet (race → trailer → slot → equipment).
- **WMS** (MySQL): equipment physical dimensions.

The result is cached for 10 minutes; the sidebar **"Reload data"** button re-queries on
demand.

### Credentials
Resolved from `st.secrets` first (for Streamlit Cloud), falling back to the repo-root
`.env` (local dev). Both are gitignored. Required keys:

```
# Champschedule (PostgreSQL)
DB_HOST=…      DB_NAME=…   DB_USER=…   DB_PASSWORD=…   DB_PORT=5432
# WMS / MODX (MySQL)
WMS_HOST=…     WMS_NAME=…  WMS_USER=…  WMS_PWD=…       WMS_PORT=3306
```

For Streamlit Cloud, put the same keys in `.streamlit/secrets.toml`:

```toml
DB_HOST = "…"
DB_NAME = "…"
# … etc.
```
