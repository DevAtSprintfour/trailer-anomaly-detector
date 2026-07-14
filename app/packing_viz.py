"""Render a trailer's packing as one continuous Plotly strip.

Dance floor (nose) and general floor (rear) are sections of the same trailer
drawn end-to-end — one outline spanning dance.length + general.length by
shared width. Every equipment on the trailer is drawn: items that pack go
inside the outline; overflow items are drawn in red below their floor zone.
FAIL/AMBIGUOUS items are always colored red (in or out).
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

# Overflow / blamed items always render red so problems stand out.
OVERFLOW_FILL = "#f9d7d7"
OVERFLOW_LINE = "#cf222e"


def _item_by_id(items: List[Item], eid: int) -> Item | None:
    for it in items:
        if it.equipment_id == eid:
            return it
    return None


def _is_overflow_status(status: str) -> bool:
    return status in ("FAIL", "AMBIGUOUS")


def _item_colors(status: str, is_overflow: bool) -> Tuple[str, str]:
    if is_overflow or _is_overflow_status(status):
        return OVERFLOW_FILL, OVERFLOW_LINE
    return STATUS_FILL.get(status, "#e2e2e2"), STATUS_LINE.get(status, "#6e7781")


def display_pack(
    items: List[Item], length: float, width: float, gap: float,
    verdict: Dict[int, dict],
) -> Tuple[List[Placement], List[Item], PackResult]:
    """Pack for visualization: fit everything that can, overflow the rest.

    Prefer excluding uniquely FAIL-blamed items so floor-mates pack cleanly
    and the blamed piece shows red outside. Falls back to best-effort partial
    packing so every equipment still gets a drawn box.
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


def _draw_box(
    fig: go.Figure, x0: float, y0: float, x1: float, y1: float,
    fill: str, line: str, label: str, eid: int, file_L: float, file_W: float,
    status: str, placed_w: float, placed_h: float, overflow: bool,
) -> None:
    fig.add_shape(
        type="rect", x0=x0, y0=y0, x1=x1, y1=y1,
        line=dict(color=line, width=1.5), fillcolor=fill,
    )
    tag = "OVERFLOW" if overflow else status
    fig.add_trace(go.Scatter(
        x=[(x0 + x1) / 2], y=[(y0 + y1) / 2],
        mode="text",
        text=[f"{label}<br>#{eid}<br>{file_L:.0f}×{file_W:.0f}"],
        textfont=dict(size=9, color="#1a1a1a"),
        hovertext=[
            f"{label} (#{eid}) — {tag}<br>"
            f"on file: {file_L:.0f}×{file_W:.0f} in<br>"
            f"placed: {placed_w:.0f}×{placed_h:.0f} in"
        ],
        hoverinfo="text", showlegend=False,
    ))


def _draw_floor_items(
    fig: go.Figure, items: List[Item], placements: List[Placement],
    overflow: List[Item], verdict: Dict[int, dict],
    x_offset: float, y_bottom: float, floor_length: float,
) -> float:
    """Draw placed items inside the floor strip; overflow in red below it.

    Returns the lowest y used (for figure ranging).
    """
    for p in placements:
        eid = p.equipment_id
        status = verdict.get(eid, {}).get("status", "UNKNOWN")
        fill, line = _item_colors(status, is_overflow=False)
        it = _item_by_id(items, eid)
        label = it.label if it else str(eid)
        file_L = it.length if it else p.w
        file_W = it.width if it else p.h
        x0, y0 = x_offset + p.x, y_bottom + p.y
        x1, y1 = x_offset + p.x + p.w, y_bottom + p.y + p.h
        _draw_box(
            fig, x0, y0, x1, y1, fill, line, label, eid,
            file_L, file_W, status, p.w, p.h, overflow=False,
        )

    if not overflow:
        return y_bottom

    cursor_x = x_offset
    cursor_y = y_bottom - 8
    row_height = 0.0
    lowest = y_bottom
    band_right = x_offset + max(floor_length, 40.0)

    fig.add_annotation(
        x=x_offset, y=cursor_y + 2,
        text=f"Overflow ({len(overflow)}) — cannot fit",
        showarrow=False, xanchor="left", yanchor="bottom",
        font=dict(size=10, color=OVERFLOW_LINE),
    )
    cursor_y -= 2

    for it in overflow:
        status = verdict.get(it.equipment_id, {}).get("status", "FAIL")
        fill, line = _item_colors(status, is_overflow=True)
        # Place with longer side along x so labels stay readable.
        ow = min(it.length, it.width)
        oh = max(it.length, it.width)
        if cursor_x + oh > band_right and cursor_x > x_offset:
            cursor_x = x_offset
            cursor_y -= row_height + 4
            row_height = 0.0
        x0, y0 = cursor_x, cursor_y - ow
        x1, y1 = cursor_x + oh, cursor_y
        _draw_box(
            fig, x0, y0, x1, y1, fill, line, it.label, it.equipment_id,
            it.length, it.width, status, oh, ow, overflow=True,
        )
        cursor_x = x1 + 4
        row_height = max(row_height, ow)
        lowest = min(lowest, y0)

    return lowest - 2


def render_trailer_figure(
    dance_geom: FloorGeom, dance_items: List[Item],
    general_geom: FloorGeom, general_items: List[Item],
    verdict: Dict[int, dict],
    gap: float = 2.0,
    dance_result: PackResult = None,
    general_result: PackResult = None,
) -> go.Figure:
    """One continuous trailer strip with every item drawn; overflow in red.

    dance_result / general_result are optional (kept for call-site compat);
    when omitted, display packing is computed here via display_pack().
    """
    fig = go.Figure()
    total_length = dance_geom.length + general_geom.length
    total_width = max(dance_geom.width, general_geom.width)
    y_bottom, y_top = 0.0, total_width

    fig.add_shape(
        type="rect", x0=0, y0=y_bottom, x1=total_length, y1=y_top,
        line=dict(color="#666", width=2), fillcolor="#fafafa", layer="below",
    )

    dance_placed, dance_overflow, dance_exact = display_pack(
        dance_items, dance_geom.length, dance_geom.width, gap, verdict,
    )
    general_placed, general_overflow, general_exact = display_pack(
        general_items, general_geom.length, general_geom.width, gap, verdict,
    )
    if dance_result is not None:
        dance_exact = dance_result
    if general_result is not None:
        general_exact = general_result

    low_d = _draw_floor_items(
        fig, dance_items, dance_placed, dance_overflow, verdict,
        0.0, y_bottom, dance_geom.length,
    )
    low_g = _draw_floor_items(
        fig, general_items, general_placed, general_overflow, verdict,
        dance_geom.length, y_bottom, general_geom.length,
    )
    lowest = min(low_d, low_g, y_bottom)

    parts = []
    if dance_exact.fits:
        parts.append("dance OK")
    else:
        parts.append(f"dance overflow ({len(dance_overflow)})")
    if general_exact.fits:
        parts.append("general OK")
    else:
        parts.append(f"general overflow ({len(general_overflow)})")
    all_ok = dance_exact.fits and general_exact.fits
    caption_y = lowest - 6
    fig.add_annotation(
        x=0, y=caption_y,
        text=("Packed successfully — " if all_ok else "Overflow — ") + " · ".join(parts),
        showarrow=False, xanchor="left", yanchor="top",
        font=dict(size=11, color="#1a7f37" if all_ok else "#cf222e"),
    )

    x_lo, x_hi = -8, total_length + 8
    y_lo, y_hi = caption_y - 12, y_top + 8
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
