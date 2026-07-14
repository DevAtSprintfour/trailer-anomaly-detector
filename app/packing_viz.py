"""Render a trailer's packing as one continuous Plotly strip.

ONE outer trailer rectangle: dance (nose, left) + general (rear, right)
end-to-end. Packer coordinates are (x along floor WIDTH, y along floor
LENGTH) — this module maps them onto the strip as (X=length, Y=width).

Every equipment item is drawn inside that one outline. Items that cannot
pack are stacked along the floor-width axis inside their section (and drawn
last so they stay visible on top of packed items).
"""
from __future__ import annotations

from typing import Dict, List, Tuple

import plotly.graph_objects as go

from floor_geom import (
    FloorGeom, Item, Placement, PackResult, pack_floor, pack_floor_best_effort,
)

STATUS_FILL = {
    "PASS": "#d7f0dd",
    "RESOLVED": "#d7e8f0",
    "FAIL": "#f9d7d7",
    "AMBIGUOUS": "#f7e6b8",
    "UNKNOWN": "#e2e2e2",
}
STATUS_LINE = {
    "PASS": "#1a7f37",
    "RESOLVED": "#1568a8",
    "FAIL": "#cf222e",
    "AMBIGUOUS": "#bf8700",
    "UNKNOWN": "#6e7781",
}

OVERFLOW_FILL = "#f9d7d7"
OVERFLOW_LINE = "#cf222e"


def _item_by_id(items: List[Item], eid: int) -> Item | None:
    for it in items:
        if it.equipment_id == eid:
            return it
    return None


def _item_colors(status: str, is_overflow: bool) -> Tuple[str, str]:
    if status in STATUS_FILL:
        return STATUS_FILL[status], STATUS_LINE[status]
    if is_overflow:
        return OVERFLOW_FILL, OVERFLOW_LINE
    return "#e2e2e2", "#6e7781"


def display_pack(
    items: List[Item], length: float, width: float, gap: float,
    verdict: Dict[int, dict],
) -> Tuple[List[Placement], List[Item], PackResult]:
    """Pack for visualization: fit everything that can; return unplaced separately.

    'Unplaced' is a packing outcome (won't fit), not a table status — those
    items keep their analysis verdict (FAIL / AMBIGUOUS / …).
    """
    exact = pack_floor(items, length, width, gap)
    if exact.fits:
        return exact.placements, [], exact

    fail_items = [
        it for it in items
        if verdict.get(it.equipment_id, {}).get("status") == "FAIL"
    ]
    fail_ids = {it.equipment_id for it in fail_items}
    keep = [it for it in items if it.equipment_id not in fail_ids]
    if fail_items and keep:
        without = pack_floor(keep, length, width, gap)
        if without.fits:
            return without.placements, fail_items, exact

    placed, unplaced = pack_floor_best_effort(items, length, width, gap)
    return placed, unplaced, exact


def _placement_to_strip(p: Placement, x_offset: float) -> Tuple[float, float, float, float]:
    """Map packer (x=width-axis, y=length-axis) → strip (X=length, Y=width)."""
    x0 = x_offset + p.y
    y0 = p.x
    x1 = x_offset + p.y + p.h
    y1 = p.x + p.w
    return x0, y0, x1, y1


def _orient_for_width(it: Item, floor_width: float) -> Tuple[float, float]:
    """Return (w along width, h along length), preferring to fit in floor_width."""
    orientations = [
        (min(it.length, it.width), max(it.length, it.width)),
        (max(it.length, it.width), min(it.length, it.width)),
    ]
    for ow, oh in orientations:
        if ow <= floor_width + 1e-9:
            return ow, oh
    return orientations[0]


def unplaced_placements(
    unplaced: List[Item], floor_width: float, gap: float = 2.0,
) -> List[Placement]:
    """Stack unplaced items along the WIDTH axis at length=0.

    Two too-long dance items (e.g. 140×48) become two side-by-side strips
    in the dance section (both starting at the nose) instead of chaining
    end-to-end into general where packed green boxes cover them.
    """
    out: List[Placement] = []
    cursor_w = 0.0
    row_y = 0.0  # along length
    row_h = 0.0
    for it in unplaced:
        ow, oh = _orient_for_width(it, floor_width)
        if cursor_w > 0 and cursor_w + ow > floor_width + 1e-9:
            row_y += row_h + gap
            cursor_w = 0.0
            row_h = 0.0
        out.append(Placement(it.equipment_id, x=cursor_w, y=row_y, w=ow, h=oh))
        cursor_w += ow + gap
        row_h = max(row_h, oh)
    return out


def _draw_box(
    fig: go.Figure, x0: float, y0: float, x1: float, y1: float,
    fill: str, line: str, label: str, eid: int, file_L: float, file_W: float,
    status: str, placed_w: float, placed_h: float, wont_pack: bool,
) -> None:
    fig.add_shape(
        type="rect", x0=x0, y0=y0, x1=x1, y1=y1,
        line=dict(color=line, width=1.5), fillcolor=fill,
    )
    pack_note = " · stored dims won't pack into this floor" if wont_pack else ""
    fig.add_trace(go.Scatter(
        x=[(x0 + x1) / 2], y=[(y0 + y1) / 2],
        mode="text",
        text=[f"{label}<br>#{eid}<br>{file_L:.0f}×{file_W:.0f}"],
        textfont=dict(size=9, color="#1a1a1a"),
        hovertext=[
            f"{label} (#{eid}) — {status}{pack_note}<br>"
            f"on file: {file_L:.0f}×{file_W:.0f} in<br>"
            f"drawn: {placed_w:.0f}×{placed_h:.0f} in"
        ],
        hoverinfo="text", showlegend=False,
    ))


def _draw_placements(
    fig: go.Figure, items: List[Item], placements: List[Placement],
    verdict: Dict[int, dict], x_offset: float, wont_pack: bool,
) -> Tuple[float, float]:
    min_y, max_y = 0.0, 0.0
    first = True
    for p in placements:
        eid = p.equipment_id
        status = verdict.get(eid, {}).get("status", "UNKNOWN")
        fill, line = _item_colors(status, is_overflow=wont_pack)
        it = _item_by_id(items, eid)
        label = it.label if it else str(eid)
        file_L = it.length if it else p.h
        file_W = it.width if it else p.w
        x0, y0, x1, y1 = _placement_to_strip(p, x_offset)
        _draw_box(
            fig, x0, y0, x1, y1, fill, line, label, eid,
            file_L, file_W, status, p.w, p.h, wont_pack=wont_pack,
        )
        if first:
            min_y, max_y = y0, y1
            first = False
        else:
            min_y = min(min_y, y0)
            max_y = max(max_y, y1)
    return min_y, max_y


def render_trailer_figure(
    dance_geom: FloorGeom, dance_items: List[Item],
    general_geom: FloorGeom, general_items: List[Item],
    verdict: Dict[int, dict],
    gap: float = 2.0,
    dance_result: PackResult = None,
    general_result: PackResult = None,
) -> go.Figure:
    """One continuous trailer rectangle; every item drawn inside it."""
    fig = go.Figure()
    total_length = dance_geom.length + general_geom.length
    total_width = max(dance_geom.width, general_geom.width)

    fig.add_shape(
        type="rect", x0=0, y0=0, x1=total_length, y1=total_width,
        line=dict(color="#888", width=2), fillcolor="#fafafa", layer="below",
    )
    fig.add_shape(
        type="line", x0=dance_geom.length, y0=0,
        x1=dance_geom.length, y1=total_width,
        line=dict(color="#bbb", width=1, dash="dot"),
    )
    fig.add_annotation(
        x=dance_geom.length / 2, y=total_width + 2,
        text=f"dance · {dance_geom.length:.0f}×{dance_geom.width:.0f}",
        showarrow=False, font=dict(size=10, color="#888"),
        yanchor="bottom",
    )
    fig.add_annotation(
        x=dance_geom.length + general_geom.length / 2, y=total_width + 2,
        text=f"general · {general_geom.length:.0f}×{general_geom.width:.0f}",
        showarrow=False, font=dict(size=10, color="#888"),
        yanchor="bottom",
    )

    dance_placed, dance_unplaced, dance_exact = display_pack(
        dance_items, dance_geom.length, dance_geom.width, gap, verdict,
    )
    general_placed, general_unplaced, general_exact = display_pack(
        general_items, general_geom.length, general_geom.width, gap, verdict,
    )
    if dance_result is not None:
        dance_exact = dance_result
    if general_result is not None:
        general_exact = general_result

    dance_overflow_pl = unplaced_placements(dance_unplaced, dance_geom.width, gap)
    general_overflow_pl = unplaced_placements(general_unplaced, general_geom.width, gap)

    # Draw packed items first, then unplaced on top so they aren't hidden under
    # a floor-mate in the neighboring section (e.g. too-long dance item spilling
    # into general under a green PASS box).
    extents: List[Tuple[float, float]] = [(0.0, total_width)]
    if dance_placed:
        extents.append(_draw_placements(
            fig, dance_items, dance_placed, verdict, 0.0, wont_pack=False,
        ))
    if general_placed:
        extents.append(_draw_placements(
            fig, general_items, general_placed, verdict,
            dance_geom.length, wont_pack=False,
        ))
    if dance_overflow_pl:
        extents.append(_draw_placements(
            fig, dance_items, dance_overflow_pl, verdict, 0.0, wont_pack=True,
        ))
    if general_overflow_pl:
        extents.append(_draw_placements(
            fig, general_items, general_overflow_pl, verdict,
            dance_geom.length, wont_pack=True,
        ))

    dmin = min(e[0] for e in extents)
    dmax = max(e[1] for e in extents)

    def _floor_caption(name: str, exact: PackResult, unplaced: List[Item]) -> str:
        if exact.fits:
            return f"{name} packs OK"
        counts: Dict[str, int] = {}
        for it in unplaced:
            st = verdict.get(it.equipment_id, {}).get("status", "unplaced")
            counts[st] = counts.get(st, 0) + 1
        if counts:
            detail = ", ".join(f"{n} {s}" for s, n in sorted(counts.items()))
            return f"{name} won't pack ({detail})"
        return f"{name} won't pack"

    parts = [
        _floor_caption("dance", dance_exact, dance_unplaced),
        _floor_caption("general", general_exact, general_unplaced),
    ]
    all_ok = dance_exact.fits and general_exact.fits
    fig.add_annotation(
        x=0, y=min(0.0, dmin) - 4,
        text=("Packed successfully — " if all_ok else "") + " · ".join(parts),
        showarrow=False, xanchor="left", yanchor="top",
        font=dict(size=11, color="#1a7f37" if all_ok else "#cf222e"),
    )

    y_lo = min(0.0, dmin) - 16
    y_hi = max(total_width, dmax) + 14
    x_lo, x_hi = -8, total_length + 8
    x_range = x_hi - x_lo
    y_range = max(y_hi - y_lo, 1.0)

    fig.update_xaxes(range=[x_lo, x_hi], showgrid=False, zeroline=False, visible=False)
    fig.update_yaxes(
        range=[y_lo, y_hi], showgrid=False, zeroline=False,
        visible=False, scaleanchor="x", scaleratio=1,
    )

    margin = 10
    assumed_width = 900
    plot_area = assumed_width - 2 * margin
    height = max(160, int(plot_area * (y_range / x_range)) + 2 * margin)

    fig.update_layout(
        height=height,
        margin=dict(l=margin, r=margin, t=margin, b=margin),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig
