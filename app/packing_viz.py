"""Render a PackResult as an inline SVG floor diagram.

Pure function, no Streamlit dependency — returns an SVG string the caller
embeds via st.markdown(svg, unsafe_allow_html=True). No external plotting
library: floors are simple 2D rectangles with a handful of placed items, and
raw SVG keeps the app's only runtime dependencies at streamlit + pandas.
"""
from __future__ import annotations

from typing import Dict, List
from html import escape

from floor_geom import FloorGeom, Item, PackResult

STATUS_FILL = {
    "PASS": "#d7f0dd",
    "RESOLVED": "#d7e8f0",
    "FAIL": "#f9d7d7",
    "AMBIGUOUS": "#f7e6b8",
    "UNKNOWN": "#e2e2e2",
}
STATUS_STROKE = {
    "PASS": "#1a7f37",
    "RESOLVED": "#1568a8",
    "FAIL": "#cf222e",
    "AMBIGUOUS": "#bf8700",
    "UNKNOWN": "#6e7781",
}

_PADDING = 20
_SCALE_TARGET_W = 760  # px, floor length maps onto this


def render_floor_svg(fg: FloorGeom, items: List[Item], result: PackResult,
                     verdict: Dict[int, dict]) -> str:
    """fg is the floor's (length, width) capacity; items is everything that
    was asked to pack; result is pack_floor()'s output for those items."""
    scale = _SCALE_TARGET_W / max(fg.length, 1.0)
    floor_w_px = fg.length * scale
    floor_h_px = fg.width * scale
    svg_w = floor_w_px + 2 * _PADDING
    svg_h = floor_h_px + 2 * _PADDING + 30  # extra for a caption row

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {svg_w:.0f} {svg_h:.0f}" '
        f'width="100%" height="auto" font-family="sans-serif" font-size="11">',
        f'<rect x="{_PADDING}" y="{_PADDING}" width="{floor_w_px:.1f}" '
        f'height="{floor_h_px:.1f}" fill="#fafafa" stroke="#999" stroke-width="1.5" />',
    ]

    placed_ids = {p.equipment_id for p in result.placements}
    for p in result.placements:
        eid = p.equipment_id
        status = verdict.get(eid, {}).get("status", "UNKNOWN")
        fill = STATUS_FILL.get(status, "#e2e2e2")
        stroke = STATUS_STROKE.get(status, "#6e7781")
        # p.x/p.y/p.w/p.h are in floor coordinates (width axis, length axis)
        rx = _PADDING + p.x * scale
        ry = _PADDING + p.y * scale
        rw = p.w * scale
        rh = p.h * scale
        label = next((it.label for it in items if it.equipment_id == eid), str(eid))
        parts.append(
            f'<rect x="{rx:.1f}" y="{ry:.1f}" width="{max(rw - 1, 1):.1f}" '
            f'height="{max(rh - 1, 1):.1f}" fill="{fill}" stroke="{stroke}" stroke-width="1.5" />'
        )
        if rw > 30 and rh > 14:
            parts.append(
                f'<text x="{rx + rw / 2:.1f}" y="{ry + rh / 2:.1f}" '
                f'text-anchor="middle" dominant-baseline="middle">{escape(label)[:16]}</text>'
            )

    # Items that could not be placed at all (overflow) — list them below the floor.
    unplaced = [it for it in items if it.equipment_id not in placed_ids]
    caption_y = _PADDING + floor_h_px + 18
    if not result.fits and unplaced:
        names = ", ".join(escape(it.label or str(it.equipment_id)) for it in unplaced[:6])
        more = f" (+{len(unplaced) - 6} more)" if len(unplaced) > 6 else ""
        parts.append(
            f'<text x="{_PADDING}" y="{caption_y:.1f}" fill="#cf222e">'
            f'Overflow — could not place: {names}{more}</text>'
        )
    elif not result.fits:
        parts.append(
            f'<text x="{_PADDING}" y="{caption_y:.1f}" fill="#cf222e">'
            f'Overflow — {result.detail}</text>'
        )
    else:
        parts.append(
            f'<text x="{_PADDING}" y="{caption_y:.1f}" fill="#1a7f37">'
            f'Packed successfully — {result.detail}</text>'
        )

    parts.append("</svg>")
    return "".join(parts)
