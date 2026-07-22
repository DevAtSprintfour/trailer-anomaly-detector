"""Exact 2D trailer packer built on OR-Tools CP-SAT.

The whole trailer is ONE container laid along its length axis:

    X: 0 ............ dance_length ............ dance_length + general_length
       |<--- dance chamber --->|<---------- general chamber ---------->|
    Y: 0 ............................................ width (interior)

The floors are packed front-to-back as one continuous rectangle. Dance items
pack first, from the front against the whole trailer length, and may overhang the
nominal ``dance_length`` line. General items then pack in the general floor: if a dance item
overflows the ``dance_length`` line, general starts one harness gap after the
dance equipment's real extent; otherwise it starts one harness gap after the
line — so every item stays strictly in its assigned floor. Items may rotate 90° unless rotation is disabled for that floor (per-floor
``dance_rotation`` / ``general_rotation`` flags). The harness ``padding`` gap is
kept between items AND against the trailer walls, and between the dance equipment
and the general floor. An item that cannot fit its floor is an *overflow* — returned
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
    dance_rotation: bool = True  # may dance-floor items be rotated 90°?
    general_rotation: bool = True  # may general-floor items be rotated 90°?

    @property
    def total_length(self) -> float:
        return self.dance_length + self.general_length

    @property
    def exclusion_x(self) -> float:
        return self.dance_length

    def chamber_length(self, side: str) -> float:
        return self.dance_length if side == SIDE_DANCE else self.general_length

    def rotation_for(self, side: str) -> bool:
        return self.dance_rotation if side == SIDE_DANCE else self.general_rotation

    def general_start(self, dance_extent: float) -> float:
        """Where the general floor begins along X, given the dance equipment's
        real rightmost extent. If a dance item overflows the ``dance_length``
        line, general items pack one harness gap after that real extent;
        otherwise they pack one harness gap after the line. Either way the gap
        sits after whichever boundary is further back, so the reserved margin
        never eats into the dance chamber."""
        return max(self.dance_length, dance_extent) + self.padding


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
        allow_rotation: bool = True,
    ) -> PackResult:
        """Pack ONE floor rectangle (length x width). The harness gap is kept
        both between items AND against every edge of the rectangle, so an item
        must be at least one gap shorter than the floor on each axis to fit.
        When ``allow_rotation`` is False, items keep their load-sheet orientation
        (no 90° turn). Overflowing items are reported in ``unplaced``
        (best-effort) or make ``fits`` False (mandatory)."""
        key = (
            "rect",
            best_effort,
            allow_rotation,
            _as_int(length),
            _as_int(width),
            _as_int(gap),
            tuple(sorted((it.equipment_id, _as_int(it.length), _as_int(it.width)) for it in items)),
        )
        if key in self._cache:
            return self._cache[key]
        result = self._solve_floor(
            items, _as_int(length), _as_int(width), _as_int(gap), best_effort, allow_rotation
        )
        self._cache[key] = result
        return result

    def diagnose(self, items: list[PackItem], container: ContainerSpec) -> AnomalyReport:
        return self._build_report(items, container)

    def fits(self, items: list[PackItem], container: ContainerSpec) -> bool:
        return self.pack(items, container).fits

    # ---- internals ------------------------------------------------------
    def _combine(self, items, container, best_effort) -> PackResult:
        """Pack the trailer as ONE continuous rectangle, front to back.

        Dance items pack first, from the front against the whole trailer length
        (they may overhang the nominal ``dance_length`` line). General items then
        pack in the general floor, which begins after the dance equipment's real
        extent plus one harness gap — but never before the ``dance_length`` line,
        so every item stays strictly in its assigned floor. Both floors keep the
        harness gap against the trailer walls."""
        gap, width = container.padding, container.width
        total = container.total_length
        placements: list[Placement] = []
        unplaced: list[PackItem] = []
        fits = True

        dance_items = [it for it in items if it.side == SIDE_DANCE]
        general_items = [it for it in items if it.side == SIDE_GENERAL]

        dance_extent = 0.0
        if dance_items:
            res = self.pack_floor(
                dance_items,
                total,
                width,
                gap,
                best_effort=best_effort,
                allow_rotation=container.dance_rotation,
            )
            placements.extend(res.placements)  # dance floor is offset 0
            unplaced.extend(res.unplaced)
            fits = fits and res.fits
            dance_extent = max((p.x + p.w for p in res.placements), default=0.0)

        if general_items:
            # General begins one harness gap after whichever is further back:
            # the dance extent (when a dance item overflows the line) or the
            # dividing line itself. Offset the floor so its own front-wall gap
            # lands the first general item exactly at that start.
            gen_start = container.general_start(dance_extent)
            gen_off = gen_start - gap
            gen_len = max(0.0, total - gen_off)
            res = self.pack_floor(
                general_items,
                gen_len,
                width,
                gap,
                best_effort=best_effort,
                allow_rotation=container.general_rotation,
            )
            for p in res.placements:
                placements.append(
                    Placement(p.equipment_id, p.x + gen_off, p.y, p.w, p.h, SIDE_GENERAL, p.rotated)
                )
            unplaced.extend(res.unplaced)
            fits = fits and res.fits

        used = max((p.x + p.w for p in placements), default=0.0)
        report = None if fits else self._build_report(items, container)
        status = "OPTIMAL" if fits else "OVERFLOW"
        if not best_effort and not fits:
            placements = []  # mandatory pack returns nothing on overflow
        return PackResult(fits, placements, unplaced, used, report, status)

    def _solve_floor(
        self, items, length, width, gap, best_effort, allow_rotation=True
    ) -> PackResult:
        """Solve one floor rectangle (hard length cap via the inflate trick).

        The gap is reserved against the walls too: we pack into a rectangle
        shrunk by ``gap`` on every edge, then shift every placement out by
        ``gap`` so the reserved margin sits between the equipment and the
        chamber boundary. Inside that shrunk region the classic inflate trick
        (bin +gap, each item +gap) keeps the same gap between neighbours."""
        if not items:
            return PackResult(True, [], [], 0.0, None, "EMPTY")

        # Usable interior after reserving a wall gap on both ends of each axis.
        usable_len = length - 2 * gap
        usable_wid = width - 2 * gap
        if usable_len < 0 or usable_wid < 0:
            # Chamber can't even hold the wall margins — nothing fits.
            return PackResult(not items, [], list(items), 0.0, None, "INFEASIBLE")

        W = usable_len + gap  # inflated bin over the shrunk interior
        H = usable_wid + gap

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

            r = model.NewBoolVar(f"r_{i}") if allow_rotation else model.NewConstant(0)
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
                    # Shift out by the reserved wall gap so the margin sits
                    # between the equipment and the chamber boundary.
                    x=float(solver.Value(v["x"])) + gap,
                    y=float(solver.Value(v["y"])) + gap,
                    w=_as_int(it.width) if rot else _as_int(it.length),
                    h=_as_int(it.length) if rot else _as_int(it.width),
                    side=it.side,
                    rotated=rot,
                )
            )
        used_len = float(solver.Value(max_len)) + gap
        fits = not unplaced if best_effort else True
        return PackResult(fits, placements, unplaced, used_len, None, status_name)

    def _build_report(self, items: list[PackItem], container: ContainerSpec) -> AnomalyReport:
        """Explain a failure. The trailer is one continuous rectangle with the
        harness gap reserved against the walls, so usable height is the width
        minus twice the gap. A dance item may overhang, so it fits anywhere in
        the trailer length; a general item is bounded by the general floor."""
        gap = container.padding
        usable_h = container.width - 2 * gap
        left_w = container.total_length - 2 * gap  # dance may use the whole trailer
        right_w = container.general_length - 2 * gap
        total_usable = (container.total_length - 2 * gap) * usable_h

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
