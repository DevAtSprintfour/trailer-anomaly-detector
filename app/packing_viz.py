"""Render a trailer's packing as one continuous Plotly strip.

ONE outer trailer rectangle: dance (nose, left) + general (rear, right).
Every equipment box is drawn ON that floor — packed items at packer
positions, won't-pack items rooted at their floor nose. Overlaps stay on
the floor and are shown with translucent fill + diagonal hatch. Name / ID /
dims are printed on every box (no hover required).
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

_BOX_GAP = 2.0


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


def unplaced_placements(
    unplaced: List[Item], floor_width: float, floor_length: float,
    gap: float = 2.0,
) -> List[Placement]:
    """Root won't-pack items at the floor nose, stacked along width.

    Stay on the trailer floor (may overlap packed tiles and/or each other —
    overlaps are drawn with hatch). Spilling past the floor's length into
    the neighboring section is fine: still inside the one trailer strip.
    """
    out: List[Placement] = []
    cursor_w = 0.0
    for it in unplaced:
        ow, oh = _orient_for_display(it, floor_width, floor_length)
        # Keep width stack on the floor: wrap within floor_width by overlapping
        # at x=0 when the next item would leave the floor strip.
        if cursor_w > 0 and cursor_w + ow > floor_width + 1e-9:
            cursor_w = 0.0
        out.append(Placement(it.equipment_id, x=cursor_w, y=0.0, w=ow, h=oh))
        cursor_w += ow + gap
    return out


def _label_font_size(x0: float, y0: float, x1: float, y1: float) -> int:
    bw, bh = abs(x1 - x0), abs(y1 - y0)
    return int(max(8, min(13, min(bw, bh) * 0.18)))


def _short_label(label: str, max_chars: int = 18) -> str:
    s = (label or "").strip()
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 1] + "…"


def _draw_box(
    fig: go.Figure, x0: float, y0: float, x1: float, y1: float,
    fill: str, line: str, label: str, eid: int, file_L: float, file_W: float,
    status: str, wont_pack: bool, overlapping: bool,
) -> None:
    """Draw an on-floor box; hatch + translucency when overlapping."""
    alpha = 0.45 if overlapping else 0.85
    fill_rgba = _hex_to_rgba(fill, alpha)
    # Closed polygon so we can use Scatter fillpattern for hatch.
    xs = [x0, x1, x1, x0, x0]
    ys = [y0, y0, y1, y1, y0]
    flags = []
    if wont_pack:
        flags.append("won't pack")
    if overlapping:
        flags.append("OVERLAP")
    flag_txt = (" · " + " · ".join(flags)) if flags else ""
    hover = (
        f"{label} (#{eid}) — {status}{flag_txt}<br>"
        f"on file: {file_L:.0f}×{file_W:.0f} in"
    )
    trace_kwargs = dict(
        x=xs, y=ys,
        mode="lines",
        fill="toself",
        fillcolor=fill_rgba,
        line=dict(color=line, width=2.5 if overlapping else 1.5,
                  dash="dash" if overlapping else "solid"),
        hovertext=hover,
        hoverinfo="text",
        showlegend=False,
    )
    if overlapping:
        trace_kwargs["fillpattern"] = dict(
            shape="/", size=6, solidity=0.4, fgcolor=line, bgcolor=fill_rgba,
        )
    fig.add_trace(go.Scatter(**trace_kwargs))

    fig.add_annotation(
        x=(x0 + x1) / 2, y=(y0 + y1) / 2,
        text=(
            f"<b>{_short_label(label)}</b><br>"
            f"#{eid}<br>"
            f"{file_L:.0f}×{file_W:.0f}"
        ),
        showarrow=False,
        font=dict(size=_label_font_size(x0, y0, x1, y1), color="#111111"),
        bgcolor="rgba(255,255,255,0.85)",
        bordercolor=line,
        borderwidth=1,
        borderpad=2,
        align="center",
    )


def _clamp_to_trailer(
    x0: float, y0: float, x1: float, y1: float,
    trailer_length: float, trailer_width: float,
    fallback_w: float, fallback_h: float,
) -> Tuple[float, float, float, float]:
    """Keep the drawn box inside the trailer outline; never outside."""
    x0 = max(0.0, min(x0, trailer_length))
    x1 = max(0.0, min(x1, trailer_length))
    y0 = max(0.0, min(y0, trailer_width))
    y1 = max(0.0, min(y1, trailer_width))
    if x1 - x0 < 1e-6:
        x0 = max(0.0, min(x0, trailer_length - 1e-6))
        x1 = min(trailer_length, x0 + min(fallback_h, trailer_length))
    if y1 - y0 < 1e-6:
        y0 = 0.0
        y1 = min(fallback_w, trailer_width)
    return x0, y0, x1, y1


def _draw_items_on_floor(
    fig: go.Figure, items: List[Item], placements: List[Placement],
    verdict: Dict[int, dict], x_offset: float, wont_pack: bool,
    occupied: List[Tuple[float, float, float, float]],
    trailer_length: float, trailer_width: float,
) -> None:
    for p in placements:
        eid = p.equipment_id
        status = verdict.get(eid, {}).get("status", "UNKNOWN")
        fill, line = _item_colors(status, is_overflow=wont_pack)
        it = _item_by_id(items, eid)
        label = it.label if it else str(eid)
        file_L = float(it.length) if it else float(p.h)
        file_W = float(it.width) if it else float(p.w)
        x0, y0, x1, y1 = _placement_to_strip(p, x_offset)
        x0, y0, x1, y1 = _clamp_to_trailer(
            x0, y0, x1, y1, trailer_length, trailer_width,
            fallback_w=float(p.w), fallback_h=float(p.h),
        )
        rect = (x0, y0, x1, y1)
        overlapping = any(_rects_overlap(rect, o) for o in occupied)
        _draw_box(
            fig, x0, y0, x1, y1, fill, line, label, eid,
            file_L, file_W, status, wont_pack=wont_pack, overlapping=overlapping,
        )
        occupied.append(rect)


def render_trailer_figure(
    dance_geom: FloorGeom, dance_items: List[Item],
    general_geom: FloorGeom, general_items: List[Item],
    verdict: Dict[int, dict],
    gap: float = 2.0,
    dance_result: PackResult = None,
    general_result: PackResult = None,
) -> go.Figure:
    """One continuous trailer rectangle; all equipment on-floor; hatch overlaps."""
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

    dance_overflow_pl = unplaced_placements(
        dance_unplaced, dance_geom.width, dance_geom.length, gap,
    )
    general_overflow_pl = unplaced_placements(
        general_unplaced, general_geom.width, general_geom.length, gap,
    )

    occupied: List[Tuple[float, float, float, float]] = []
    # Draw packed first, then won't-pack on top so hatched overlaps stay readable.
    _draw_items_on_floor(
        fig, dance_items, dance_placed, verdict, 0.0, False,
        occupied, total_length, total_width,
    )
    _draw_items_on_floor(
        fig, general_items, general_placed, verdict,
        dance_geom.length, False, occupied, total_length, total_width,
    )
    _draw_items_on_floor(
        fig, dance_items, dance_overflow_pl, verdict, 0.0, True,
        occupied, total_length, total_width,
    )
    _draw_items_on_floor(
        fig, general_items, general_overflow_pl, verdict,
        dance_geom.length, True, occupied, total_length, total_width,
    )

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
    n_overlap = sum(
        1 for i in range(len(occupied))
        for j in range(i + 1, len(occupied))
        if _rects_overlap(occupied[i], occupied[j])
    )
    caption = ("Packed successfully — " if all_ok else "") + " · ".join(parts)
    if n_overlap:
        caption += f" · {n_overlap} overlap(s) — hatched / dashed outline"
    fig.add_annotation(
        x=0, y=-6,
        text=caption,
        showarrow=False, xanchor="left", yanchor="top",
        font=dict(size=11, color="#1a7f37" if all_ok and not n_overlap else "#cf222e"),
    )

    # Frame tightly around the trailer; captions sit just outside.
    x_lo, x_hi = -8, total_length + 8
    y_lo, y_hi = -18, total_width + 14
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
    height = max(180, int(plot_area * (y_range / x_range)) + 2 * margin)

    fig.update_layout(
        height=height,
        margin=dict(l=margin, r=margin, t=margin, b=margin),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig
