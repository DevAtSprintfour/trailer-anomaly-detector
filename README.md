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
│   └── slots_2026.csv        slot occupancy (reference)
├── app/                   the analyzer
│   ├── geometry.py           floor dims + 2D packer (rotation, gaps)
│   ├── analysis.py           floor-level engine + blame isolation
│   ├── test_logic.py         unit tests
│   └── streamlit_app.py      the UI
└── docs/DESIGN.md         full design + locked decisions
```

> The data-export step (which connects to the production databases with credentials)
> is intentionally **not** part of this repository. The `data/*.csv` snapshots it
> produced are committed so the app runs standalone.

## Run

```bash
cd trailer-anomaly
python3 -m venv .venv && source .venv/bin/activate
pip install streamlit pandas
streamlit run app/streamlit_app.py
```

Open the local URL Streamlit prints. To run the tests: `python app/test_logic.py`.

## How it works
- **Premise**: load sheets are ground truth. Stored WMS dims are tested against them.
- **Two floors**: dance (129×98 in) and general (483×98 in), tunable in the sidebar.
  Items from slots 1–2 pool into dance; slots 3–10 into general — per race + trailer.
- **Packing**: MaxRects 2D packing with per-item 90° rotation and a harness gap.
- **Buckets**: `PASS` · `FAIL` (unique blame) · `AMBIGUOUS` · `UNKNOWN`.
- **Blame**: leave-one-out + cross-race isolation when possible.
- **UI**: pick race (or All) and trailer (or All); see dance vs general fail counts
  and expandable equipment details.

## Data sources
The committed `data/*.csv` were produced from two internal databases:
- **Champschedule** (PostgreSQL): the load sheet (race → trailer → slot → equipment).
- **WMS** (MySQL): equipment physical dimensions.
Joined on `equipment_id`. The extraction script and its credentials live outside this
repository; only the resulting read-only snapshots are committed.
