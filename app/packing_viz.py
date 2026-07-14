"""Render a trailer's packing as one interactive Plotly figure.

Pure function, no Streamlit dependency — returns a plotly.graph_objects.Figure
the caller renders via st.plotly_chart(fig, use_container_width=True). Shows
the whole trailer (dance floor stacked above general floor) in a single
diagram, since dance/general are two physically separate floors an item
never spans, but the user wants one picture per trailer, not two.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

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

_GAP_BETWEEN_FLOORS = 30.0  # in, vertical whitespace reserved between the two floor drawings
_LABEL_HEADROOM = 14.0      # in, space reserved above each floor for its title annotation
_CAPTION_FOOTROOM = 14.0    # in, space reserved below each floor for its pack/overflow caption


def _add_floor(fig: go.Figure, fg: FloorGeom, items: List[Item], result: PackResult,
               verdict: Dict[int, dict], top: float, title: str) -> float:
    """Draw one floor's outline + placed items with its top edge at y=top
    (floor occupies [top - fg.width, top]). Returns the y to use as the next
    floor's top (below this floor's caption + the inter-floor gap)."""
    bottom = top - fg.width
    fig.add_shape(
        type="rect", x0=0, y0=bottom, x1=fg.length, y1=top,
        line=dict(color="#999", width=1.5), fillcolor="#fafafa", layer="below",
    )
    fig.add_annotation(
        x=2, y=top - 2, text=f"<b>{title}</b> · {fg.length:.0f}×{fg.width:.0f} in",
        showarrow=False, xanchor="left", yanchor="top",
        font=dict(size=12, color="#1a1a1a"),
    )

    placed_ids = {p.equipment_id for p in result.placements}
    for p in result.placements:
        eid = p.equipment_id
        status = verdict.get(eid, {}).get("status", "UNKNOWN")
        fill = STATUS_FILL.get(status, "#e2e2e2")
        line = STATUS_LINE.get(status, "#6e7781")
        label = next((it.label for it in items if it.equipment_id == eid), str(eid))
        x0, y0 = p.x, bottom + p.y
        x1, y1 = p.x + p.w, bottom + p.y + p.h
        fig.add_shape(
            type="rect", x0=x0, y0=y0, x1=x1, y1=y1,
            line=dict(color=line, width=1.5), fillcolor=fill,
        )
        fig.add_trace(go.Scatter(
            x=[(x0 + x1) / 2], y=[(y0 + y1) / 2],
            mode="text", text=[f"{label}<br>#{eid}"],
            textfont=dict(size=10, color="#1a1a1a"),
            hovertext=[f"{label} (#{eid}) — {status}<br>{p.w:.0f}×{p.h:.0f} in"],
            hoverinfo="text", showlegend=False,
        ))

    unplaced = [it for it in items if it.equipment_id not in placed_ids]
    caption_y = bottom - 6
    if not result.fits and unplaced:
        names = ", ".join(f"{it.label} (#{it.equipment_id})" for it in unplaced[:6])
        more = f" (+{len(unplaced) - 6} more)" if len(unplaced) > 6 else ""
        caption = f"Overflow — could not place: {names}{more}"
        color = "#cf222e"
    elif not result.fits:
        caption = f"Overflow — {result.detail}"
        color = "#cf222e"
    else:
        caption = f"Packed successfully — {result.detail}"
        color = "#1a7f37"
    fig.add_annotation(
        x=0, y=caption_y, text=caption, showarrow=False,
        xanchor="left", yanchor="top", font=dict(size=11, color=color),
    )

    return bottom - _CAPTION_FOOTROOM - _GAP_BETWEEN_FLOORS - _LABEL_HEADROOM


def render_trailer_figure(
    dance_geom: FloorGeom, dance_items: List[Item], dance_result: PackResult,
    general_geom: FloorGeom, general_items: List[Item], general_result: PackResult,
    verdict: Dict[int, dict],
) -> go.Figure:
    """One combined figure for a trailer: dance floor stacked above general
    floor, each packed independently but drawn as a single diagram."""
    fig = go.Figure()
    top = 0.0
    next_top = _add_floor(fig, dance_geom, dance_items, dance_result, verdict, top, "Dance floor")
    bottom = _add_floor(fig, general_geom, general_items, general_result, verdict, next_top, "General floor")

    max_length = max(dance_geom.length, general_geom.length)
    x_lo, x_hi = -10, max_length + 10
    y_lo, y_hi = bottom - 10, top + _LABEL_HEADROOM + 10
    x_range = x_hi - x_lo
    y_range = y_hi - y_lo

    fig.update_xaxes(range=[x_lo, x_hi], showgrid=False, zeroline=False, visible=False)
    fig.update_yaxes(range=[y_lo, y_hi], showgrid=False, zeroline=False,
                     visible=False, scaleanchor="x", scaleratio=1)

    # Streamlit stretches the figure to the container width (use_container_width=True),
    # so height must be derived from that same width to keep the 1:1 data aspect —
    # a mismatched height forces Plotly to letterbox (shrink the x-domain) instead.
    margin = 10
    assumed_width = 900
    plot_area = assumed_width - 2 * margin
    height = int(plot_area * (y_range / x_range)) + 2 * margin

    fig.update_layout(
        height=height,
        margin=dict(l=margin, r=margin, t=margin, b=margin),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig
