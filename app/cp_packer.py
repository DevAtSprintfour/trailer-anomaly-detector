"""Exact 2D trailer packer built on OR-Tools CP-SAT.

The whole trailer is ONE container laid along its length axis:

    X: 0 ............ dance_length ............ dance_length + general_length
       |<--- dance chamber --->|<---------- general chamber ---------->|
    Y: 0 ............................................ width (interior)

The two floors are packed as SEPARATE rectangles against their real lengths:
the dance floor (``dance_length x width``) and the general floor
(``general_length x width``). Items may rotate 90°. The harness ``padding`` gap
is kept ONLY between items, never against the walls, so a floor-length item fits
its floor exactly. An item that cannot fit its floor is an *overflow* — returned
in ``unplaced`` (best-effort) or making ``fits`` False (mandatory). Callers apply
severity by floor: dance overflow is AMBIGUOUS, general overflow is FAIL.

The engine is a class, :class:`CpPacker`: :meth:`pack_floor` solves one floor,
:meth:`pack` / :meth:`pack_best_effort` pack both floors of a container. A
failing container carries an :class:`AnomalyReport` explaining why — a port of
the diagnostic logic from ``anomaly-detection/plot.py``.

Ported and generalised from ``Champion/anomaly-detection/plot.py``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ortools.sat.python import cp_model

SIDE_DANCE = "dance"
SIDE_GENERAL = "general"


def _as_int(value: float) -> int:
    """CP-SAT needs integer coordinates. Load-sheet dims are whole inches, so
    this is exact; a fractional correction is ceiled (conservative — never
    understates an item's size)."""
    f = float(value)
    return int(f) if f.is_integer() else math.ceil(f)


@dataclass
class PackItem:
    """One piece of equipment to place, pinned to a chamber by its floor."""

    equipment_id: int
    length: float  # extent along the trailer length axis (X)
    width: float  # extent across the trailer (Y)
    side: str = SIDE_GENERAL  # SIDE_DANCE | SIDE_GENERAL
    label: str = ""


@dataclass
class ContainerSpec:
    """Trailer container geometry (one continuous rectangle, split by a line)."""

    dance_length: float
    general_length: float
    width: float
    padding: float = 2.0

    @property
    def total_length(self) -> float:
        return self.dance_length + self.general_length

    @property
    def exclusion_x(self) -> float:
        return self.dance_length

    def chamber_length(self, side: str) -> float:
        return self.dance_length if side == SIDE_DANCE else self.general_length


@dataclass
class Placement:
    equipment_id: int
    x: float  # lower-left corner on the length axis
    y: float  # lower-left corner on the width axis
    w: float  # placed extent along X (after rotation choice)
    h: float  # placed extent along Y (after rotation choice)
    side: str
    rotated: bool = False


@dataclass
class OversizedItem:
    equipment_id: int
    label: str
    length: float
    width: float
    reason: str


@dataclass
class AnomalyReport:
    """Structured 'why did it fail' breakdown for one container."""

    usable_height: float
    left_chamber_w: float
    right_chamber_w: float
    total_usable_area: float
    total_item_area: float
    oversized_items: list[OversizedItem] = field(default_factory=list)

    @property
    def area_overflow(self) -> float:
        return max(0.0, self.total_item_area - self.total_usable_area)

    @property
    def utilization(self) -> float:
        if self.total_usable_area <= 0:
            return 0.0
        return 100.0 * self.total_item_area / self.total_usable_area

    def lines(self) -> list[str]:
        """Human-readable report lines (no emojis), mirroring plot.py."""
        out = [
            "DIAGNOSTIC REPORT: LAYOUT ANOMALIES DETECTED",
            f"Usable height: {self.usable_height:.0f}",
            f"Left (dance) chamber max width: {self.left_chamber_w:.0f}",
            f"Right (general) chamber max width: {self.right_chamber_w:.0f}",
            f"Total usable area: {self.total_usable_area:.0f} sq in",
        ]
        if self.oversized_items:
            out.append("Individual shapes violate their chamber limits:")
            for o in self.oversized_items:
                out.append(
                    f"  - #{o.equipment_id} {o.label} ({o.length:.0f}x{o.width:.0f}): {o.reason}"
                )
        else:
            out.append("All individual shapes physically fit their chamber.")
        out.append(f"Sum of item areas: {self.total_item_area:.0f} sq in")
        if self.area_overflow > 0:
            out.append(
                f"OVERFLOW: items need {self.area_overflow:.0f} more sq in "
                "than the container holds."
            )
        else:
            out.append(
                f"Area utilization {self.utilization:.1f}% — failure is a tight "
                "geometric packing conflict, not raw area."
            )
        return out

    def text(self) -> str:
        return "\n".join(self.lines())


@dataclass
class PackResult:
    fits: bool
    placements: list[Placement] = field(default_factory=list)
    unplaced: list[PackItem] = field(default_factory=list)
    total_width_used: float | None = None
    report: AnomalyReport | None = None
    status: str = ""  # solver status name

    @property
    def detail(self) -> str:
        if self.fits:
            return "packed"
        if self.report is not None:
            return self.report.text()
        return "no feasible layout"


class CpPacker:
    """CP-SAT trailer packer. Memoises solves so leave-one-out blame and
    season-wide hint passes don't re-solve identical floors."""

    def __init__(self, time_limit: float = 5.0, workers: int = 1):
        self.time_limit = time_limit
        self.workers = workers
        self._cache: dict[tuple, PackResult] = {}

    # ---- public API -----------------------------------------------------
    def pack(self, items: list[PackItem], container: ContainerSpec) -> PackResult:
        """Pack both chambers against their REAL lengths (dance_length,
        general_length). fits=True iff every item fits its own floor."""
        return self._combine(items, container, best_effort=False)

    def pack_best_effort(self, items: list[PackItem], container: ContainerSpec) -> PackResult:
        """Like :meth:`pack` but keeps the items that fit and returns the
        overflowing ones (the ones that don't fit their floor) in ``unplaced``."""
        return self._combine(items, container, best_effort=True)

    def pack_floor(
        self,
        items: list[PackItem],
        length: float,
        width: float,
        gap: float,
        best_effort: bool = False,
    ) -> PackResult:
        """Pack ONE floor rectangle (length x width). The harness gap is kept
        only between items (never against the walls), so a length-long item fits
        exactly. Overflowing items are reported in ``unplaced`` (best-effort) or
        make ``fits`` False (mandatory)."""
        key = (
            "rect",
            best_effort,
            _as_int(length),
            _as_int(width),
            _as_int(gap),
            tuple(sorted((it.equipment_id, _as_int(it.length), _as_int(it.width)) for it in items)),
        )
        if key in self._cache:
            return self._cache[key]
        result = self._solve_floor(
            items, _as_int(length), _as_int(width), _as_int(gap), best_effort
        )
        self._cache[key] = result
        return result

    def diagnose(self, items: list[PackItem], container: ContainerSpec) -> AnomalyReport:
        return self._build_report(items, container)

    def fits(self, items: list[PackItem], container: ContainerSpec) -> bool:
        return self.pack(items, container).fits

    # ---- internals ------------------------------------------------------
    def _combine(self, items, container, best_effort) -> PackResult:
        """Pack dance items in the front floor and general items in the rear
        floor, each against its real length; merge into one container view."""
        gap, width = container.padding, container.width
        placements: list[Placement] = []
        unplaced: list[PackItem] = []
        used = 0.0
        fits = True
        for side, length, x_off in (
            (SIDE_DANCE, container.dance_length, 0.0),
            (SIDE_GENERAL, container.general_length, container.dance_length),
        ):
            side_items = [it for it in items if it.side == side]
            if not side_items:
                continue
            res = self.pack_floor(side_items, length, width, gap, best_effort=best_effort)
            for p in res.placements:
                placements.append(
                    Placement(p.equipment_id, p.x + x_off, p.y, p.w, p.h, side, p.rotated)
                )
            unplaced.extend(res.unplaced)
            used = max(used, (res.total_width_used or 0.0) + x_off)
            fits = fits and res.fits
        report = None if fits else self._build_report(items, container)
        status = "OPTIMAL" if fits else "OVERFLOW"
        if not best_effort and not fits:
            placements = []  # mandatory pack returns nothing on overflow
        return PackResult(fits, placements, unplaced, used, report, status)

    def _solve_floor(self, items, length, width, gap, best_effort) -> PackResult:
        """Solve one floor rectangle (hard length cap via the inflate trick)."""
        if not items:
            return PackResult(True, [], [], 0.0, None, "EMPTY")

        W = length + gap  # inflated bin: an item of `length` fits exactly
        H = width + gap

        model = cp_model.CpModel()
        x_intervals, y_intervals, presences, vars_ = [], [], [], []
        max_len = model.NewIntVar(0, max(W, 0), "max_len")

        for i, it in enumerate(items):
            w = _as_int(it.length)
            h = _as_int(it.width)
            wp, hp = w + gap, h + gap
            big = max(wp, hp)

            present = model.NewBoolVar(f"p_{i}") if best_effort else model.NewConstant(1)
            presences.append(present)

            r = model.NewBoolVar(f"r_{i}")
            w_eff = model.NewIntVar(0, big, f"we_{i}")
            h_eff = model.NewIntVar(0, big, f"he_{i}")
            model.Add(w_eff == wp).OnlyEnforceIf([r.Not(), present])
            model.Add(h_eff == hp).OnlyEnforceIf([r.Not(), present])
            model.Add(w_eff == hp).OnlyEnforceIf([r, present])
            model.Add(h_eff == wp).OnlyEnforceIf([r, present])

            x = model.NewIntVar(0, max(W, 0), f"x_{i}")
            y = model.NewIntVar(0, max(H, 0), f"y_{i}")
            x_end = model.NewIntVar(0, max(W, 0), f"xe_{i}")
            y_end = model.NewIntVar(0, max(H, 0), f"ye_{i}")
            model.Add(x_end == x + w_eff).OnlyEnforceIf(present)
            model.Add(y_end == y + h_eff).OnlyEnforceIf(present)

            x_int = model.NewOptionalIntervalVar(x, w_eff, x_end, present, f"xi_{i}")
            y_int = model.NewOptionalIntervalVar(y, h_eff, y_end, present, f"yi_{i}")
            x_intervals.append(x_int)
            y_intervals.append(y_int)
            model.Add(max_len >= x_end).OnlyEnforceIf(present)
            vars_.append(dict(x=x, y=y, r=r, present=present, item=it))

        model.AddNoOverlap2D(x_intervals, y_intervals)
        if best_effort:
            model.Maximize(sum(presences) * (W + 1) - max_len)
        else:
            model.Minimize(max_len)

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = self.time_limit
        solver.parameters.num_search_workers = self.workers
        status = solver.Solve(model)
        status_name = solver.StatusName(status)

        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return PackResult(False, [], list(items), None, None, status_name)

        placements, unplaced = [], []
        for v in vars_:
            it = v["item"]
            if best_effort and solver.Value(v["present"]) == 0:
                unplaced.append(it)
                continue
            rot = solver.Value(v["r"]) == 1
            placements.append(
                Placement(
                    equipment_id=it.equipment_id,
                    x=float(solver.Value(v["x"])),
                    y=float(solver.Value(v["y"])),
                    w=_as_int(it.width) if rot else _as_int(it.length),
                    h=_as_int(it.length) if rot else _as_int(it.width),
                    side=it.side,
                    rotated=rot,
                )
            )
        used_len = float(solver.Value(max_len))
        fits = not unplaced if best_effort else True
        return PackResult(fits, placements, unplaced, used_len, None, status_name)

    def _build_report(self, items: list[PackItem], container: ContainerSpec) -> AnomalyReport:
        """Explain a failure. Usable length per chamber is the full chamber
        length (edge gaps don't count); usable height is the full width."""
        usable_h = container.width
        left_w = container.dance_length
        right_w = container.general_length
        total_usable = (left_w + right_w) * usable_h

        oversized: list[OversizedItem] = []
        total_area = 0.0
        for it in items:
            total_area += it.length * it.width
            long, short = max(it.length, it.width), min(it.length, it.width)
            chamber_w = left_w if it.side == SIDE_DANCE else right_w
            fits_h = short <= usable_h
            # fits if some orientation keeps length<=chamber and height<=usable_h
            fits_chamber = (it.length <= chamber_w and it.width <= usable_h) or (
                it.width <= chamber_w and it.length <= usable_h
            )
            if not fits_h:
                oversized.append(
                    OversizedItem(
                        it.equipment_id,
                        it.label,
                        it.length,
                        it.width,
                        f"shorter side {short:.0f} exceeds interior width {usable_h:.0f}",
                    )
                )
            elif not fits_chamber:
                oversized.append(
                    OversizedItem(
                        it.equipment_id,
                        it.label,
                        it.length,
                        it.width,
                        f"too long ({long:.0f}) for the {it.side} chamber ({chamber_w:.0f})",
                    )
                )
        return AnomalyReport(usable_h, left_w, right_w, total_usable, total_area, oversized)
