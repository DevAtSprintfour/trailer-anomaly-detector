"""Trailer name -> category classification, and per-category floor geometry.

Trailer names follow a handful of patterns (see data/trailers_2026.csv):
  T-NN       -> standard T-series (e.g. T-02, T-07, T-38)
  T-NN Top   -> a "Top" variant of the T-series (e.g. T-12 Top)
  F-NN       -> F-series (e.g. F-10)
  everything else (e.g. "01- Big", "03-Awn") -> Other

Categories exist so each pattern can have its own dance/general floor
dimensions instead of one global size for every trailer.
"""
from __future__ import annotations

import re
from typing import Dict

from floor_geom import DEFAULT_GEOM

CATEGORY_T_SERIES = "T-Series"
CATEGORY_T_SERIES_TOP = "T-Series Top"
CATEGORY_F_SERIES = "F-Series"
CATEGORY_OTHER = "Other"

ALL_CATEGORIES = [CATEGORY_T_SERIES, CATEGORY_T_SERIES_TOP, CATEGORY_F_SERIES, CATEGORY_OTHER]

_T_TOP_RE = re.compile(r"^T-\d+\s+Top$", re.IGNORECASE)
_T_RE = re.compile(r"^T-\d+$", re.IGNORECASE)
_F_RE = re.compile(r"^F-\d+$", re.IGNORECASE)


def classify_trailer(name: str) -> str:
    """Classify a trailer name into a category by pattern."""
    n = (name or "").strip()
    if _T_TOP_RE.match(n):
        return CATEGORY_T_SERIES_TOP
    if _T_RE.match(n):
        return CATEGORY_T_SERIES
    if _F_RE.match(n):
        return CATEGORY_F_SERIES
    return CATEGORY_OTHER


# Every category defaults to today's global dance/general size until a user
# tunes it per category in the sidebar.
DEFAULT_CATEGORY_GEOM: Dict[str, dict] = {
    cat: dict(DEFAULT_GEOM) for cat in ALL_CATEGORIES
}
