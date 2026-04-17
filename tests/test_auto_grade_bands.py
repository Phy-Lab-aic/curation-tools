from backend.datasets.services.auto_grade_service import (
    compute_bands,
    unify_key,
    MIN_SEVERE_RUN,
)


def test_empty_inputs_return_no_bands():
    assert compute_bands([], []) == []
    assert compute_bands([1.0], []) == []


def test_constant_series_returns_no_bands():
    obs = [0.5] * 20
    act = [0.5] * 20
    assert compute_bands(obs, act) == []


def test_pure_noise_under_threshold_returns_no_bands():
    obs = [i * 0.01 for i in range(100)]
    act = [i * 0.01 + 0.001 for i in range(100)]
    assert compute_bands(obs, act) == []


def test_short_severe_run_is_demoted_to_moderate():
    # range = 1.0, 3-frame severe at 40% (below MIN_SEVERE_RUN)
    obs = [0.0] * 10
    act = [0.0, 0.0, 0.4, 0.4, 0.4, 0.0, 0.0, 0.0, 0.0, 1.0]
    bands = compute_bands(obs, act)
    severe_runs = [b for b in bands if b["level"] == "severe"]
    moderate_runs = [b for b in bands if b["level"] == "moderate"]
    assert severe_runs == []
    assert any(r["start"] == 2 and r["end"] == 4 for r in moderate_runs)


def test_long_severe_run_stays_severe():
    # range = 1.0, 6-frame severe at 40%
    obs = [0.0] * 15
    act = [0.0, 0.0, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]
    bands = compute_bands(obs, act)
    severe_runs = [b for b in bands if b["level"] == "severe"]
    assert len(severe_runs) == 1
    run = severe_runs[0]
    assert run["start"] == 2 and run["end"] == 7
    assert (run["end"] - run["start"] + 1) >= MIN_SEVERE_RUN


def test_uneven_lengths_use_min():
    obs = [0.0] * 5
    act = [0.0] * 3
    # Range over the min-length region is 0, so no bands
    assert compute_bands(obs, act) == []


def test_unify_key_index_form():
    assert unify_key("observation.state[0]") == "[0]"
    assert unify_key("action[12]") == "[12]"


def test_unify_key_dotted_form():
    assert unify_key("observation.state.joint1") == "joint1"
    assert unify_key("action.joint1") == "joint1"
