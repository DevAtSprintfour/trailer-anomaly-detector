"""Render a trailer's packing in the style of ``anomaly-detection/plot.py``.

One dashed container rectangle (0..total_length × 0..width), a solid blue
exclusion line at ``x = dance_length`` with a light buffer corridor, a red
dotted "bounding length" line at the packed length, and one tab20-coloured
box per equipment placed at its CP-SAT solver position. Each box is labelled
``#id / name / L×W``. Width-impossible items (short side > interior width) can't
be placed and are drawn hatched at the nose.

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
# Overflow colours by floor: general -> FAIL (red), dance -> AMBIGUOUS (amber).
OVERFLOW_FILL = {SIDE_GENERAL: "#f9d7d7", SIDE_DANCE: "#f7e6b8"}
OVERFLOW_EDGE = {SIDE_GENERAL: "#cf222e", SIDE_DANCE: "#bf8700"}


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

    def _unplaced_layout(
        self, unplaced: list[PackItem], container: ContainerSpec
    ) -> list[Placement]:
        """Root overflow items at their floor's nose (dance at 0, general behind
        the line), stacked across the width."""
        out: list[Placement] = []
        cursor = {SIDE_DANCE: 0.0, SIDE_GENERAL: 0.0}
        nose = {SIDE_DANCE: 0.0, SIDE_GENERAL: container.exclusion_x}
        for it in unplaced:
            w = max(it.length, it.width)
            h = min(it.length, it.width)
            y = cursor[it.side]
            if y > 0 and y + h > container.width:
                y = 0.0
            out.append(Placement(it.equipment_id, nose[it.side], y, w, h, it.side))
            cursor[it.side] = y + h + container.padding
        return out

    def _draw_box(self, ax, p: Placement, item: PackItem | None, color, wont_pack: bool) -> None:
        if wont_pack:
            face = OVERFLOW_FILL.get(p.side, "#f9d7d7")
            edge = OVERFLOW_EDGE.get(p.side, "#cf222e")
        else:
            face, edge = color, "black"
        ax.add_patch(
            Rectangle(
                (p.x, p.y),
                p.w,
                p.h,
                facecolor=face,
                edgecolor=edge,
                alpha=0.85,
                linewidth=1.5,
                linestyle="--" if wont_pack else "-",
                hatch="///" if wont_pack else None,
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
        bound = result.total_width_used or total_len
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

        # Placed boxes in tab20 colours; width-impossible ones hatched at nose.
        for idx, p in enumerate(result.placements):
            self._draw_box(ax, p, by_id.get(p.equipment_id), cmap(idx % 20), wont_pack=False)
        for p in self._unplaced_layout(result.unplaced, container):
            self._draw_box(ax, p, by_id.get(p.equipment_id), None, wont_pack=True)

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

        ax.set_xlim(-15, max(total_len, bound) + 15)
        ax.set_ylim(-10, width + 10)
        ax.set_aspect("equal")
        ax.grid(True, linestyle=":", alpha=0.4)
        ax.legend(loc="upper right", fontsize=8)
        fig.tight_layout()
        return fig
