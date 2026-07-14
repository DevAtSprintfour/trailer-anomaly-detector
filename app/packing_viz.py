"""Render a trailer's packing as one continuous Plotly strip.

Dance floor (nose) and general floor (rear) are sections of the same trailer
drawn end-to-end with no visual gap or stacked boxes — one outline spanning
dance.length + general.length by shared width. Items pack independently per
floor; general placements are offset by dance.length on the x-axis.
"""
from __future__ import annotations

from typing import Dict, List

import plotly.graph_objects as go

from floor_geom import FloorGeom, Item, PackResult

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


def _item_by_id(items: List[Item], eid: int) -> Item | None:
    for it in items:
        if it.equipment_id == eid:
            return it
    return None


def _draw_placements(
    fig: go.Figure, items: List[Item], result: PackResult,
    verdict: Dict[int, dict], x_offset: float, y_bottom: float,
) -> None:
    for p in result.placements:
        eid = p.equipment_id
        status = verdict.get(eid, {}).get("status", "UNKNOWN")
        fill = STATUS_FILL.get(status, "#e2e2e2")
        line = STATUS_LINE.get(status, "#6e7781")
        it = _item_by_id(items, eid)
        label = it.label if it else str(eid)
        # On-file (or corrected) dims — not the post-rotation placement size.
        file_L = it.length if it else p.w
        file_W = it.width if it else p.h
        x0, y0 = x_offset + p.x, y_bottom + p.y
        x1, y1 = x_offset + p.x + p.w, y_bottom + p.y + p.h
        fig.add_shape(
            type="rect", x0=x0, y0=y0, x1=x1, y1=y1,
            line=dict(color=line, width=1.5), fillcolor=fill,
        )
        fig.add_trace(go.Scatter(
            x=[(x0 + x1) / 2], y=[(y0 + y1) / 2],
            mode="text",
            text=[f"{label}<br>#{eid}<br>{file_L:.0f}×{file_W:.0f}"],
            textfont=dict(size=9, color="#1a1a1a"),
            hovertext=[
                f"{label} (#{eid}) — {status}<br>"
                f"on file: {file_L:.0f}×{file_W:.0f} in<br>"
                f"placed: {p.w:.0f}×{p.h:.0f} in"
            ],
            hoverinfo="text", showlegend=False,
        ))


def _overflow_names(items: List[Item], result: PackResult) -> str:
    placed = {p.equipment_id for p in result.placements}
    unplaced = [it for it in items if it.equipment_id not in placed]
    if not unplaced:
        return result.detail or "overflow"
    names = ", ".join(f"{it.label} (#{it.equipment_id})" for it in unplaced[:6])
    more = f" (+{len(unplaced) - 6} more)" if len(unplaced) > 6 else ""
    return f"{names}{more}"


def render_trailer_figure(
    dance_geom: FloorGeom, dance_items: List[Item], dance_result: PackResult,
    general_geom: FloorGeom, general_items: List[Item], general_result: PackResult,
    verdict: Dict[int, dict],
) -> go.Figure:
    """One continuous trailer strip: dance (left/nose) + general (right/rear)."""
    fig = go.Figure()
    total_length = dance_geom.length + general_geom.length
    # Widths should match per trailer category; take max so a mistuned width
    # still draws everything inside the outline.
    total_width = max(dance_geom.width, general_geom.width)
    y_bottom, y_top = 0.0, total_width

    # Single outer trailer outline — no separate boxes, no visual split.
    fig.add_shape(
        type="rect", x0=0, y0=y_bottom, x1=total_length, y1=y_top,
        line=dict(color="#666", width=2), fillcolor="#fafafa", layer="below",
    )

    _draw_placements(fig, dance_items, dance_result, verdict, 0.0, y_bottom)
    _draw_placements(
        fig, general_items, general_result, verdict, dance_geom.length, y_bottom,
    )

    # Compact status caption under the strip (not per-floor stacked boxes).
    parts = []
    if dance_result.fits:
        parts.append("dance OK")
    else:
        parts.append(f"dance overflow: {_overflow_names(dance_items, dance_result)}")
    if general_result.fits:
        parts.append("general OK")
    else:
        parts.append(f"general overflow: {_overflow_names(general_items, general_result)}")
    all_ok = dance_result.fits and general_result.fits
    fig.add_annotation(
        x=0, y=y_bottom - 4,
        text=("Packed successfully — " if all_ok else "Overflow — ") + " · ".join(parts),
        showarrow=False, xanchor="left", yanchor="top",
        font=dict(size=11, color="#1a7f37" if all_ok else "#cf222e"),
    )

    x_lo, x_hi = -8, total_length + 8
    y_lo, y_hi = y_bottom - 18, y_top + 8
    x_range = x_hi - x_lo
    y_range = y_hi - y_lo

    fig.update_xaxes(range=[x_lo, x_hi], showgrid=False, zeroline=False, visible=False)
    fig.update_yaxes(
        range=[y_lo, y_hi], showgrid=False, zeroline=False,
        visible=False, scaleanchor="x", scaleratio=1,
    )

    margin = 10
    assumed_width = 900
    plot_area = assumed_width - 2 * margin
    height = max(120, int(plot_area * (y_range / x_range)) + 2 * margin)

    fig.update_layout(
        height=height,
        margin=dict(l=margin, r=margin, t=margin, b=margin),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig
