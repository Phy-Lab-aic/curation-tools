"""Auto-grade service — runs once per dataset on first registration.

Detects severe divergence between paired observation.state[N] and action[N]
scalar columns and writes `grade='normal'` + a machine-written reason on
ungraded episodes. Idempotency guard is `datasets.auto_graded_at`.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Iterable, TypedDict

import pyarrow.parquet as pq

from backend.core.db import get_db

logger = logging.getLogger(__name__)


# Tuned against labelled good/normal/bad episodes — see spec for evidence.
MODERATE_RATIO = 0.15
SEVERE_RATIO = 0.30
MIN_SEVERE_RUN = 5


class Band(TypedDict):
    start: int
    end: int
    level: str  # 'moderate' | 'severe'


_IDX_RE = re.compile(r"\[(\d+)\]$")


def unify_key(key: str) -> str:
    """Reduce a scalar key to its pair-matching identifier.

    observation.state[0] <-> action[0]      -> '[0]'
    observation.state.joint1 <-> action.joint1 -> 'joint1'
    """
    m = _IDX_RE.search(key)
    if m:
        return m.group(0)
    return (
        key.replace("observation.state.", "")
        .replace("observation.state", "")
        .replace("observation.", "")
        .replace("action.", "")
        .replace("action", "")
    )


def _classify(ratio: float) -> str | None:
    if ratio > SEVERE_RATIO:
        return "severe"
    if ratio > MODERATE_RATIO:
        return "moderate"
    return None


def _range_of(series: list[float]) -> float:
    if not series:
        return 0.0
    lo = hi = series[0]
    for v in series[1:]:
        if v < lo:
            lo = v
        if v > hi:
            hi = v
    return hi - lo


def compute_bands(obs: list[float], act: list[float]) -> list[Band]:
    """Pairwise divergence bands for one joint. Returns merged runs."""
    n = min(len(obs), len(act))
    if n == 0:
        return []
    rng = max(_range_of(obs[:n]), _range_of(act[:n]))
    if rng == 0:
        return []

    # Per-frame level
    levels: list[str | None] = []
    for i in range(n):
        r = abs(act[i] - obs[i]) / rng
        levels.append(_classify(r))

    # Merge runs
    bands: list[Band] = []
    cur: str | None = None
    start = 0
    for i, lv in enumerate(levels):
        if lv != cur:
            if cur is not None:
                bands.append({"start": start, "end": i - 1, "level": cur})
            cur = lv
            start = i
    if cur is not None:
        bands.append({"start": start, "end": n - 1, "level": cur})

    # Downgrade short severe runs to moderate (gripper transients are NOT
    # data-quality problems; only sustained tracking error is).
    for b in bands:
        if b["level"] == "severe" and (b["end"] - b["start"] + 1) < MIN_SEVERE_RUN:
            b["level"] = "moderate"

    # Re-merge adjacent same-level runs after downgrade
    merged: list[Band] = []
    for b in bands:
        if merged and merged[-1]["level"] == b["level"] and merged[-1]["end"] + 1 == b["start"]:
            merged[-1] = {"start": merged[-1]["start"], "end": b["end"], "level": b["level"]}
        else:
            merged.append(dict(b))  # type: ignore[arg-type]
    return merged
