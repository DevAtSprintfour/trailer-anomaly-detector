# Trailer Slot Anomaly Detector — Design

## Premise (LOAD SHEETS ARE THE SOURCE OF TRUTH)
If a slot appears on a 2026 load sheet, it was USED and it WORKED — so the equipment in it
DID physically fit. That fact is ground truth. We do NOT trust the stored equipment dimensions.
Each used slot is therefore a *satisfied constraint* on the equipment's TRUE sizes. We test the
STORED sizes against these constraints: an equipment whose stored size is larger than what its
tightest successful slot could physically have allowed has a WRONG stored size → anomaly.
The slot geometry constants are a tunable outer ceiling, not per-item truth. Goal: a pass/fail
list, especially a trustworthy "good fail" list, blame pinned to an individual where possible.

## Trailer dimensions (shared 2026, tunable in UI)
  Dancefloor (slots 1,2): length 129, total width 98.
  General (slots 3-10):   length 483, total width 98.
Width is NOT split per column: field data shows single items up to 90in wide in one
column, so a lone item may use the full 98in. The two columns SHARE the width per row.

## Model — PAIRED COLUMNS
Slots pair into rows: (1,2),(3,4),(5,6),(7,8),(9,10). Left = odd, right = even.
For a used slot with along-capacity L, gap g, items i, and total row width W:
  (a) single-item width: each item's shorter side <= W (a lone item may use full W).
  (b) paired width: when both columns of a row are occupied, widest(left) +
      widest(right) <= W. A used row proves this held for the true sizes.
  (c) length: sum(item along-dim) + (n-1)*g <= L, per slot.
Blame: the side whose width alone exceeds W is the culprit (unique); both-fit-alone-
but-not-together or both-oversize -> ambiguous pair.
Rotation allowed per item; take the most-forgiving axis. These are KNOWN TRUE for real sizes.
We check the STORED sizes against them:
  - Width anomaly: stored shorter side > W of a slot it was used in → impossible → stored width
    wrong (unique, unambiguous).
  - Length anomaly: in a used slot the stored along-dims overflow L, and exactly one item's
    removal resolves it → that item's stored length is wrong. If a resolver is ALREADY proven
    bad elsewhere (width anomaly), attribute to it and exonerate innocent slot-mates.
  - Ambiguous: overflow but multiple/zero unique resolvers → whole group flagged.
  - Unknown: missing/zero stored dims → cannot verify.

## Data (exported to ../data/)
Two prod DBs, joined in pandas on equipment_id:
- Champschedule (postgres): `champschedule_raceequipment` = the load sheet
  (race_id, trailer_id, position=slot 1..10, equipment_id). Filter year=2026. View from trailer
  flags: is_awning->Awning (excluded), cup_equipment->Cup, nxs_equipment->NOAPS.
- WMS/modx (mysql, port 3306): `wms_equipment` = dimensions (id, length, width, height,
  dancefloor_restricted). equipment_id == wms_equipment.id.
Files: loadsheet_2026.csv, equipment_2026.csv, trailers_2026.csv, slots_2026.csv.
Scale: 5613 assignments, 27 races, 30 trailers, 284 distinct equipment (236 with usable dims,
48 without), up to 5 items/slot.

## Trailer geometry (fixed constants, from diagram; UI-overridable)
| Slot type   | Slots | Length in | Width/column in |
|-------------|-------|-----------|-----------------|
| Dancefloor  | 1, 2  | 120       | 48  (96 total/2)|
| General     | 3-10  | 480       | 49  (98 total/2)|

## Fit algorithm (per race+trailer+slot group)
Items = assigned equipment with (length, width). Harness gap G (tunable) placed BETWEEN items
only: N items -> (N-1) gaps. Per-item 90-degree rotation allowed. Slot passes if items pack in
EITHER arrangement:
- Lengthwise: sum(oriented length) + (N-1)*G <= slot_length AND each oriented width <= slot_width
- Widthwise:  sum(oriented width)  + (N-1)*G <= slot_length AND each oriented length <= slot_width
Choose per-item orientation minimizing the packed (summed) dimension while respecting the
cross-dimension cap. Documented single-row packing model (not full 2D bin-packing) so results
are explainable. PASS if fits with margin>=0 either way; else FAIL. Record overflow inches.

## Output buckets (per equipment)
- PASS: fits in every slot it appears in.
- FAIL (specific): uniquely blamed individual (see isolation).
- AMBIGUOUS (group): overflows in a multi-item slot, blame not uniquely separable.
- UNKNOWN: missing/zero dims (own bucket + own list; a zero dim is itself a data-quality flag).

## Blame isolation (avoid ambiguity)
1. Single-item slot overflow -> that item is the culprit (clean FAIL); exonerates slot-mates
   elsewhere.
2. Cross-reference across season: an item that fits everywhere except slots shared with a
   known-bad item is exonerated; an item overflowing across multiple INDEPENDENT partner-sets
   is the consistent culprit -> FAIL.
3. Subset test: if removing exactly one item makes an overflowing slot pass, blame that item.
4. Irreducible -> AMBIGUOUS group (listed together for manual scan).
Toggle in UI: cross-reference isolation (default) vs flag-whole-group.

## UI (Streamlit)
- Sidebar: harness-gap slider G (0-12 in); view multiselect (Cup/NOAPS on, Awning off); slot
  length/width overrides (prefilled); isolation-mode toggle.
- KPIs: PASS / FAIL / AMBIGUOUS / UNKNOWN counts, live on G change.
- Main table: per equipment — status, worst slot, overflow inches, race/trailer/slot, unique?;
  sortable, filterable, CSV download (the good-fail list).
- Slot drill-down: pick race/trailer/slot; show items, dims, gaps, fit math.

## Decisions locked with user
- Orientation: per-item rotation allowed.
- Column width: total/2 (dancefloor 48, general 49).
- Gaps: between items only.
- Missing dims: separate UNKNOWN bucket.
- Blame: cross-reference isolation (with whole-group toggle).
- Data source: read both prod DBs directly (Champschedule pg 5432, WMS mysql 3306).
