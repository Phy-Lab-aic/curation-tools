"""Cycle-boundary detection and stamping helpers for gripper state traces."""

from __future__ import annotations

import numpy as np

LEFT_GRIPPER_IDX = 7
RIGHT_GRIPPER_IDX = 15
CLOSED_THRESHOLD = 0.5
OPEN_THRESHOLD = 0.8


def _detect_arm_cycle_ends(gripper_values: np.ndarray) -> list[int]:
    """Return frame indices where one gripper finishes a close-to-open cycle."""
    if gripper_values.size == 0:
        return []

    cycle_ends: list[int] = []
    searching_for_open = bool(gripper_values[0] < CLOSED_THRESHOLD)

    for frame_idx, value in enumerate(gripper_values):
        if searching_for_open:
            if value > OPEN_THRESHOLD:
                cycle_ends.append(frame_idx)
                searching_for_open = False
        elif value < CLOSED_THRESHOLD:
            searching_for_open = True

    return cycle_ends


def detect_cycle_ends(states: np.ndarray) -> list[int]:
    """Detect and merge cycle-end frame indices from the left and right grippers."""
    left_cycle_ends = _detect_arm_cycle_ends(states[:, LEFT_GRIPPER_IDX])
    right_cycle_ends = _detect_arm_cycle_ends(states[:, RIGHT_GRIPPER_IDX])
    return sorted(set(left_cycle_ends + right_cycle_ends))
