"""Render a trailer's packing as one continuous Plotly strip.

ONE outer trailer rectangle: dance (nose, left) + general (rear, right).
Packer coordinates are (x along floor WIDTH, y along floor LENGTH) — mapped
onto the strip as (X=length, Y=width).

Display packing uses the SAME pack_floor / pack_floor_best_effort logic as
analysis. Unplaced items go in a gutter under their floor section so they
never cover packed tiles. Any remaining overlaps use translucent fills.
Every box has name / id / dims printed on it (no hover required).
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

DANCE_FILL = "#fff6e8"
GENERAL_FILL = "#f0f4f8"

_GUTTER_GAP = 10.0  # in, between trailer bottom and first overflow row
_BOX_GAP = 4.0


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


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return f"rgba(200,200,200,{alpha})"
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def display_pack(
    items: List[Item], length: float, width: float, gap: float,
    verdict: Dict[int, dict],
) -> Tuple[List[Placement], List[Item], PackResult]:
    """Pack for visualization using the same packer as analysis."""
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


def _orient_for_display(it: Item, floor_width: float, floor_length: float) -> Tuple[float, float]:
    """Orientation preference matching the packer (fit width first, then length)."""
    orientations = [
        (min(it.length, it.width), max(it.length, it.width)),
        (max(it.length, it.width), min(it.length, it.width)),
    ]
    for ow, oh in orientations:
        if ow <= floor_width + 1e-9 and oh <= floor_length + 1e-9:
            return ow, oh
    for ow, oh in orientations:
        if ow <= floor_width + 1e-9:
            return ow, oh
    for ow, oh in orientations:
        if oh <= floor_length + 1e-9:
            return ow, oh
    return orientations[0]


def _rects_overlap(a: Tuple[float, float, float, float],
                   b: Tuple[float, float, float, float],
                   pad: float = 0.5) -> bool:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return (ax0 < bx1 - pad and ax1 > bx0 + pad
            and ay0 < by1 - pad and ay1 > by0 + pad)


def unplaced_gutter_boxes(
    unplaced: List[Item], x_offset: float, floor_width: float,
    floor_length: float, gutter_top: float,
) -> Tuple[List[Tuple[float, float, float, float, Item]], float]:
    """Lay out unplaced items in a non-overlapping gutter under their floor.

    Returns (list of (x0,y0,x1,y1,item), lowest_y_used).
    Stacks left-to-right under the floor's length span; wraps to a new row
    downward when the next item would exceed that span.
    """
    boxes: List[Tuple[float, float, float, float, Item]] = []
    cursor_x = x_offset
    row_top = gutter_top
    row_height = 0.0
    band_right = x_offset + max(floor_length, 40.0)
    lowest = gutter_top

    for it in unplaced:
        ow, oh = _orient_for_display(it, floor_width, floor_length)
        # oh along strip-X (length), ow along strip-Y (width).
        if cursor_x > x_offset and cursor_x + oh > band_right + 1e-9:
            cursor_x = x_offset
            row_top -= row_height + _BOX_GAP
            row_height = 0.0
        x0, y1 = cursor_x, row_top
        x1, y0 = cursor_x + oh, row_top - ow
        boxes.append((x0, y0, x1, y1, it))
        cursor_x = x1 + _BOX_GAP
        row_height = max(row_height, ow)
        lowest = min(lowest, y0)

    return boxes, lowest


def _label_font_size(x0: float, y0: float, x1: float, y1: float) -> int:
    bw, bh = abs(x1 - x0), abs(y1 - y0)
    # Rough readable size from box area in inches.
    return int(max(8, min(13, min(bw, bh) * 0.18)))


def _short_label(label: str, max_chars: int = 18) -> str:
    s = (label or "").strip()
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 1] + "…"


def _draw_box(
    fig: go.Figure, x0: float, y0: float, x1: float, y1: float,
    fill: str, line: str, label: str, eid: int, file_L: float, file_W: float,
    status: str, wont_pack: bool, alpha: float = 1.0,
) -> None:
    fill_draw = fill if alpha >= 0.99 else _hex_to_rgba(fill, alpha)
    fig.add_shape(
        type="rect", x0=x0, y0=y0, x1=x1, y1=y1,
        line=dict(color=line, width=2 if alpha < 0.99 else 1.5),
        fillcolor=fill_draw,
    )
    pack_note = " · won't pack" if wont_pack else ""
    overlap_note = " · OVERLAP" if alpha < 0.99 else ""
    text = (
        f"<b>{_short_label(label)}</b><br>"
        f"#{eid}<br>"
        f"{file_L:.0f}×{file_W:.0f}"
    )
    fig.add_annotation(
        x=(x0 + x1) / 2, y=(y0 + y1) / 2,
        text=text,
        showarrow=False,
        font=dict(size=_label_font_size(x0, y0, x1, y1), color="#111111"),
        bgcolor="rgba(255,255,255,0.82)",
        bordercolor=line,
        borderwidth=1,
        borderpad=2,
        align="center",
    )
    # Invisible marker keeps a hover tooltip with full name/status.
    fig.add_trace(go.Scatter(
        x=[(x0 + x1) / 2], y=[(y0 + y1) / 2],
        mode="markers",
        marker=dict(size=1, opacity=0),
        hovertext=[
            f"{label} (#{eid}) — {status}{pack_note}{overlap_note}<br>"
            f"on file: {file_L:.0f}×{file_W:.0f} in"
        ],
        hoverinfo="text",
        showlegend=False,
    ))


def _draw_placed(
    fig: go.Figure, items: List[Item], placements: List[Placement],
    verdict: Dict[int, dict], x_offset: float,
    occupied: List[Tuple[float, float, float, float]],
) -> Tuple[float, float]:
    """Draw packed items; mark translucent if they collide with prior boxes."""
    min_y, max_y = 0.0, 0.0
    first = True
    for p in placements:
        eid = p.equipment_id
        status = verdict.get(eid, {}).get("status", "UNKNOWN")
        fill, line = _item_colors(status, is_overflow=False)
        it = _item_by_id(items, eid)
        label = it.label if it else str(eid)
        file_L = it.length if it else p.h
        file_W = it.width if it else p.w
        x0, y0, x1, y1 = _placement_to_strip(p, x_offset)
        rect = (x0, y0, x1, y1)
        overlaps = any(_rects_overlap(rect, o) for o in occupied)
        alpha = 0.55 if overlaps else 1.0
        _draw_box(
            fig, x0, y0, x1, y1, fill, line, label, eid,
            file_L, file_W, status, wont_pack=False, alpha=alpha,
        )
        occupied.append(rect)
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
    """One continuous trailer rectangle; gutter for won't-pack; labels on boxes."""
    fig = go.Figure()
    total_length = dance_geom.length + general_geom.length
    total_width = max(dance_geom.width, general_geom.width)

    fig.add_shape(
        type="rect", x0=0, y0=0, x1=dance_geom.length, y1=total_width,
        line=dict(width=0), fillcolor=DANCE_FILL, layer="below",
    )
    fig.add_shape(
        type="rect", x0=dance_geom.length, y0=0,
        x1=total_length, y1=total_width,
        line=dict(width=0), fillcolor=GENERAL_FILL, layer="below",
    )
    fig.add_shape(
        type="rect", x0=0, y0=0, x1=total_length, y1=total_width,
        line=dict(color="#666", width=2), fillcolor="rgba(0,0,0,0)",
    )
    fig.add_shape(
        type="line", x0=dance_geom.length, y0=0,
        x1=dance_geom.length, y1=total_width,
        line=dict(color="#888", width=1.5, dash="dot"),
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

    occupied: List[Tuple[float, float, float, float]] = []
    extents: List[Tuple[float, float]] = [(0.0, total_width)]

    if dance_placed:
        extents.append(_draw_placed(
            fig, dance_items, dance_placed, verdict, 0.0, occupied,
        ))
    if general_placed:
        extents.append(_draw_placed(
            fig, general_items, general_placed, verdict,
            dance_geom.length, occupied,
        ))

    # Unplaced → gutter under each floor (never covers packed tiles).
    gutter_top = -_GUTTER_GAP
    lowest = 0.0
    if dance_unplaced:
        fig.add_annotation(
            x=0, y=gutter_top + 2,
            text="dance — won't pack (shown below floor, not overlapping)",
            showarrow=False, xanchor="left", yanchor="bottom",
            font=dict(size=10, color=OVERFLOW_LINE),
        )
        boxes, low = unplaced_gutter_boxes(
            dance_unplaced, 0.0, dance_geom.width, dance_geom.length, gutter_top,
        )
        for x0, y0, x1, y1, it in boxes:
            status = verdict.get(it.equipment_id, {}).get("status", "FAIL")
            fill, line = _item_colors(status, is_overflow=True)
            rect = (x0, y0, x1, y1)
            overlaps = any(_rects_overlap(rect, o) for o in occupied)
            _draw_box(
                fig, x0, y0, x1, y1, fill, line, it.label, it.equipment_id,
                it.length, it.width, status, wont_pack=True,
                alpha=0.55 if overlaps else 1.0,
            )
            occupied.append(rect)
        lowest = min(lowest, low)

    if general_unplaced:
        g_top = lowest - _GUTTER_GAP if dance_unplaced else gutter_top
        fig.add_annotation(
            x=dance_geom.length, y=g_top + 2,
            text="general — won't pack (shown below floor, not overlapping)",
            showarrow=False, xanchor="left", yanchor="bottom",
            font=dict(size=10, color=OVERFLOW_LINE),
        )
        boxes, low = unplaced_gutter_boxes(
            general_unplaced, dance_geom.length, general_geom.width,
            general_geom.length, g_top,
        )
        for x0, y0, x1, y1, it in boxes:
            status = verdict.get(it.equipment_id, {}).get("status", "FAIL")
            fill, line = _item_colors(status, is_overflow=True)
            rect = (x0, y0, x1, y1)
            overlaps = any(_rects_overlap(rect, o) for o in occupied)
            _draw_box(
                fig, x0, y0, x1, y1, fill, line, it.label, it.equipment_id,
                it.length, it.width, status, wont_pack=True,
                alpha=0.55 if overlaps else 1.0,
            )
            occupied.append(rect)
        lowest = min(lowest, low)

    dmin = min(e[0] for e in extents)
    dmax = max(e[1] for e in extents)
    dmin = min(dmin, lowest)

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
        x=0, y=dmin - 6,
        text=("Packed successfully — " if all_ok else "") + " · ".join(parts),
        showarrow=False, xanchor="left", yanchor="top",
        font=dict(size=11, color="#1a7f37" if all_ok else "#cf222e"),
    )

    y_lo = dmin - 18
    y_hi = max(total_width, dmax) + 14
    max_x = total_length
    for x0, y0, x1, y1 in occupied:
        max_x = max(max_x, x1)
    x_lo, x_hi = -8, max_x + 8
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
    height = max(200, int(plot_area * (y_range / x_range)) + 2 * margin)

    fig.update_layout(
        height=height,
        margin=dict(l=margin, r=margin, t=margin, b=margin),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig
