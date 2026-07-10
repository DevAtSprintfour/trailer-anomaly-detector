# Trailer Floor Anomaly Detector — Design

## Premise (LOAD SHEETS ARE THE SOURCE OF TRUTH)
If equipment appears on a 2026 load sheet, it physically fit on that trailer floor.
We do NOT trust stored WMS dimensions. Slot numbers (1–10) only classify which
**floor** an item rode on; they are not packing units.

## Two floors (not ten slots)
| Floor   | Slots | Default size (in) |
|---------|-------|-------------------|
| Dance   | 1–2   | 129 × 98          |
| General | 3–10  | 483 × 98          |

For each `(race, trailer, floor)`, pool every assigned item into one rectangle and
2D-pack. If stored sizes cannot pack into a floor that worked → anomaly.

## Fit algorithm
- Full 2D rectangle packing (MaxRects / Best Short Side Fit), several sort orders.
- Per-item 90° rotation allowed.
- Harness gap `G` (default 2 in) between items (inflated packing into L+G × W+G).
- Tunable floor L/W in the UI.

## Blame isolation
1. Single-item floor that cannot pack → that item FAIL (width or pack).
2. Leave-one-out: if removing exactly one item makes the floor pack → that item FAIL.
3. Cross-race: a known-bad item absorbs blame and exonerates floor-mates.
4. Else → AMBIGUOUS group.
5. Missing/zero dims → UNKNOWN.

## Output buckets (per equipment)
- PASS / FAIL / AMBIGUOUS / UNKNOWN

## UI (Streamlit)
- Sidebar: race (All or one), trailer (All or one), views, gap, cross-ref, floor dims.
- Two floor cards: dance + general — overflowing loads, failed/ambiguous counts,
  expandable equipment details.
- Good-fail list for the current scope.
- Optional drill-down: one race · trailer · floor pack check.

## Data
- `data/loadsheet_2026.csv` (primary), joined WMS dims.
- Scale: ~5.6k assignments, 27 races, 30 trailers, ~284 equipment; ≤15 items/floor.

## Decisions locked
- Floor-level bins only (no per-slot packing, no paired-column model).
- Dance 129×98, general 483×98 (Option A).
- Optimal 2D packing with rotation + gap (Option A).
- Pinpoint blame when possible (Option A).
- Simplified race × trailer UI with two floor categories.
