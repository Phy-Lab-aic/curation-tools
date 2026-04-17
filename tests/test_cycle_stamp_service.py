"""Tests for pure gripper cycle-boundary detection."""

import numpy as np

from backend.datasets.services.cycle_stamp_service import (
    LEFT_GRIPPER_IDX,
    RIGHT_GRIPPER_IDX,
    detect_cycle_ends,
)


def make_states(left_values, right_values):
    """Build a state array with only the gripper columns populated."""
    assert len(left_values) == len(right_values)
    states = np.zeros((len(left_values), RIGHT_GRIPPER_IDX + 1), dtype=np.float32)
    states[:, LEFT_GRIPPER_IDX] = left_values
    states[:, RIGHT_GRIPPER_IDX] = right_values
    return states


class TestDetectCycleEnds:
    """Verify cycle-end detection across the two gripper traces."""

    def test_detects_two_cycles_from_left_gripper_only(self):
        states = make_states(
            [0.9, 0.4, 0.3, 0.4, 0.81, 0.2, 0.1, 0.3, 0.81],
            [0.9] * 9,
        )

        assert detect_cycle_ends(states) == [4, 8]

    def test_detects_cycles_when_trace_starts_closed(self):
        states = make_states(
            [0.4, 0.3, 0.81, 0.2, 0.3, 0.81],
            [0.9] * 6,
        )

        assert detect_cycle_ends(states) == [2, 5]

    def test_merges_cycle_ends_from_both_arms(self):
        states = make_states(
            [0.9, 0.4, 0.81, 0.9, 0.9],
            [0.9, 0.9, 0.9, 0.2, 0.81],
        )

        assert detect_cycle_ends(states) == [2, 4]

    def test_returns_empty_when_grippers_are_always_open(self):
        states = make_states([0.9, 0.95, 0.85], [0.82, 0.9, 0.99])

        assert detect_cycle_ends(states) == []

    def test_returns_empty_when_grippers_are_always_closed(self):
        states = make_states([0.2, 0.3, 0.4], [0.1, 0.2, 0.49])

        assert detect_cycle_ends(states) == []

    def test_ignores_borderline_hysteresis_values(self):
        states = make_states(
            [0.5, 0.79, 0.8, 0.6, 0.5],
            [0.8, 0.79, 0.5, 0.6, 0.8],
        )

        assert detect_cycle_ends(states) == []
