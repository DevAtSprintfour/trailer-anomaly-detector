"""Render a trailer's packing in the style of ``anomaly-detection/plot.py``.

One dashed container rectangle (0..total_length × 0..width), a solid blue
exclusion line at ``x = dance_length`` with a light buffer corridor, a red
dotted "bounding length" line at the packed length, and one tab20-coloured
box per equipment placed at its CP-SAT solver position. Each box is labelled
``#id / name / L×W``. Overflow items that cannot be placed have no valid
position on the floor, so they are drawn INSIDE the trailer, hatched and
coloured by cause: dance overflow (orange / ambiguous) in the dance floor from
the front wall, general overflow (red / FAIL) after the packed-length line —
and summarised in the title. They may run past the rear wall, which is the
visual signal that they overflow.

Uses the same :class:`cp_packer.CpPacker` engine as analysis.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # headless / Streamlit-safe backend
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle

from cp_packer import (
    SIDE_DANCE,
    SIDE_GENERAL,
    ContainerSpec,
    CpPacker,
    PackItem,
    PackResult,
    Placement,
)

CONTAINER_EDGE = "black"
EXCLUSION_COLOR = "#1f77b4"
BUFFER_COLOR = "#87ceeb"
BOUND_COLOR = "#d62728"
FAIL_COLOR = "#cf222e"  # general overflow (FAIL)
AMBIGUOUS_COLOR = "#f0883e"  # dance overflow (ambiguous)


def _short(label: str, n: int = 18) -> str:
    s = (label or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


class TrailerRenderer:
    """Draws one trailer container with its packed equipment, plot.py-style."""

    def __init__(self, packer: CpPacker | None = None):
        self.packer = packer or CpPacker(time_limit=5.0)

    def display_pack(self, items: list[PackItem], container: ContainerSpec) -> PackResult:
        """Full pack when feasible; otherwise best-effort so the fitting items
        sit at real positions and any width-impossible ones come back unplaced."""
        exact = self.packer.pack(items, container)
        if exact.fits:
            return exact
        return self.packer.pack_best_effort(items, container)

    def _draw_box(self, ax, p: Placement, item: PackItem | None, color) -> None:
        ax.add_patch(
            Rectangle(
                (p.x, p.y),
                p.w,
                p.h,
                facecolor=color,
                edgecolor="black",
                alpha=0.85,
                linewidth=1.5,
                linestyle="-",
                zorder=3,
            )
        )
        L = item.length if item else p.h
        W = item.width if item else p.w
        name = _short(item.label) if item and item.label else ""
        fs = max(6, min(11, int(min(p.w, p.h) * 0.16)))
        label = f"#{p.equipment_id}"
        if name:
            label += f"\n{name}"
        label += f"\n{L:.0f}×{W:.0f}"
        ax.text(
            p.x + p.w / 2,
            p.y + p.h / 2,
            label,
            ha="center",
            va="center",
            fontsize=fs,
            fontweight="bold",
            color="#111",
            zorder=4,
        )

    def figure(
        self, container: ContainerSpec, items: list[PackItem], verdict: dict[int, dict]
    ) -> Figure:
        """Build a matplotlib Figure for one trailer container (plot.py style)."""
        result = self.display_pack(items, container)
        by_id = {it.equipment_id: it for it in items}
        total_len = container.total_length
        width = container.width
        # Packed length = rightmost packed edge PLUS one harness gap, since a
        # gap must follow the last item before anything else (or the wall) can
        # sit behind it. General overflow items then flow from this line.
        bound = (
            result.total_width_used + container.padding if result.total_width_used else total_len
        )
        cmap = plt.get_cmap("tab20")

        fig, ax = plt.subplots(figsize=(15, 3.5))

        # Dashed container outline (the real trailer floor).
        ax.add_patch(
            Rectangle(
                (0, 0),
                total_len,
                width,
                linewidth=2,
                edgecolor=CONTAINER_EDGE,
                facecolor="none",
                linestyle="--",
            )
        )
        # Exclusion line + buffer corridor.
        ax.axvspan(
            container.exclusion_x - container.padding,
            container.exclusion_x + container.padding,
            color=BUFFER_COLOR,
            alpha=0.3,
        )
        ax.axvline(
            container.exclusion_x,
            color=EXCLUSION_COLOR,
            linewidth=2,
            label=f"dance | general (x = {container.exclusion_x:.0f})",
        )
        # Red bounding-length line: how much floor the packing actually needs.
        ax.axvline(
            bound,
            color=BOUND_COLOR,
            linestyle=":",
            linewidth=2,
            label=f"packed length ({bound:.0f})",
        )

        # Placed boxes in tab20 colours.
        for idx, p in enumerate(result.placements):
            self._draw_box(ax, p, by_id.get(p.equipment_id), cmap(idx % 20))

        # Overflow (unplaced) items have no valid floor position. Draw them
        # INSIDE the trailer, hatched and marked "(did not fit)", by cause:
        # dance overflow (orange / ambiguous) in the dance floor, from the front
        # wall; general overflow (red / FAIL) after the packed-length line.
        # Items may run past the rear wall — that overrun signals the overflow.
        # Reserve the harness gap between overflow items and against the walls,
        # just like the real packing: dance overflow starts one gap off the
        # front wall, general overflow flows from the packed-length line (which
        # already includes the trailing gap), and each is held one gap below the
        # top wall.
        lane_right = 0.0
        gap = container.padding
        dance_cursor = gap
        general_cursor = bound

        def _draw_overflow(it, cursor_x, color):
            # Stick overflow items to the top wall (minus the harness gap).
            y0 = max(0.0, width - gap - it.width)
            ax.add_patch(
                Rectangle(
                    (cursor_x, y0),
                    it.length,
                    it.width,
                    facecolor=color,
                    edgecolor="black",
                    alpha=0.55,
                    linewidth=1.5,
                    linestyle="--",
                    hatch="xx",
                    zorder=5,
                )
            )
            fs = max(6, min(11, int(min(it.length, it.width) * 0.16)))
            name = _short(it.label) if it.label else ""
            label = f"#{it.equipment_id}"
            if name:
                label += f"\n{name}"
            label += f"\n{it.length:.0f}×{it.width:.0f}\n(did not fit)"
            ax.text(
                cursor_x + it.length / 2,
                y0 + it.width / 2,
                label,
                ha="center",
                va="center",
                fontsize=fs,
                fontweight="bold",
                color="#111",
                zorder=6,
            )
            return cursor_x + it.length + gap

        for it in result.unplaced:
            if it.side == SIDE_DANCE:
                dance_cursor = _draw_overflow(it, dance_cursor, AMBIGUOUS_COLOR)
                lane_right = max(lane_right, dance_cursor)
            else:
                general_cursor = _draw_overflow(it, general_cursor, FAIL_COLOR)
                lane_right = max(lane_right, general_cursor)

        title = f"Packed {len(result.placements)} items · bounding length {bound:.0f} of {total_len:.0f} in"
        if result.unplaced:
            n_d = sum(1 for it in result.unplaced if it.side == SIDE_DANCE)
            n_g = sum(1 for it in result.unplaced if it.side == SIDE_GENERAL)
            bits = []
            if n_g:
                bits.append(f"{n_g} general overflow (FAIL)")
            if n_d:
                bits.append(f"{n_d} dance overflow (ambiguous)")
            title += " · " + ", ".join(bits)
        ax.set_title(title, fontsize=11, pad=8)

        ax.set_xlim(-15, max(total_len, bound, lane_right) + 15)
        ax.set_ylim(-10, width + 10)
        ax.set_aspect("equal")
        ax.grid(True, linestyle=":", alpha=0.4)
        ax.legend(loc="upper right", fontsize=8)
        fig.tight_layout()
        return fig
