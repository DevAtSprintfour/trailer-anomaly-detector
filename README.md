# Trailer Slot Anomaly Detector (2026 season)

Flags equipment whose **stored dimensions are likely wrong**. Premise: the 2026 load
sheet (which equipment goes in which trailer slot) is **trusted** — it's used in the
field without problems. Trailer slot geometry is **fixed**. So if the equipment
assigned to a slot *overflows* that slot on paper, the equipment's stored length/width
is the suspect. Those become a **pass/fail list for manual scanner verification**.

## Layout
```
trailer-anomaly/
├── .venv/                 Python virtualenv
├── data/                  exported CSVs (the analysis input)
│   ├── loadsheet_2026.csv    5,613 assignments, dims joined
│   ├── equipment_2026.csv    284 distinct equipment
│   ├── trailers_2026.csv     30 trailers + view class
│   └── slots_2026.csv        slot occupancy
├── app/                   the analyzer
│   ├── geometry.py           slot dims + fit math (rotation, gaps)
│   ├── analysis.py           load-sheet-as-truth engine + blame isolation
│   ├── test_logic.py         unit tests for the above
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

## How it works — load sheets are the source of truth
- **Premise**: if a slot was used on a load sheet, its equipment *did* fit. We do not
  trust the stored dimensions; each used slot is a **constraint** the true sizes satisfy.
- **Trailer model**: two columns of slots. Slots 1–2 = dancefloor, 3–10 = general
  floor. Each slot's usable **length** and **width** are **tunable in the sidebar**
  (defaults are the even-split reading of the diagram: width = trailer width ÷ 2), and
  act as an outer ceiling — the load sheets tighten the real per-item bound.
- **Anomaly**: an equipment is flagged when its **stored** size contradicts a load
  sheet that worked — its stored width exceeds a slot it fit in, or its stored length
  makes a used slot overflow. Per-item 90° rotation and a tunable harness gap (between
  items only) are allowed before calling a contradiction.
- **Buckets**: `PASS` (consistent) · `FAIL` (stored dim wrong, unique blame) ·
  `AMBIGUOUS` (shared-slot overflow, blame not separable) · `UNKNOWN` (missing dims).
- **Blame isolation**: the item whose removal reconciles a shared slot is blamed;
  an item already proven wrong elsewhere absorbs blame and exonerates its slot-mates.

## Tuning
The even-split defaults over-flag (a 146-in cart can't fit a 120×48 slot). Set the
four slot dimensions to the **real trailer numbers** in the sidebar; the KPIs and
good-fail list update live. What still fails at correct dimensions is a genuine
anomaly to scan.

## Data sources
The committed `data/*.csv` were produced from two internal databases:
- **Champschedule** (PostgreSQL): the load sheet (race → trailer → slot → equipment).
- **WMS** (MySQL): equipment physical dimensions.
Joined on `equipment_id`. The extraction script and its credentials live outside this
repository; only the resulting read-only snapshots are committed.
