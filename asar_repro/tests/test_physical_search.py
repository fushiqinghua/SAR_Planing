"""Pending local checks for the physical search study; not executed at delivery.

These tests check scoring independence, fair warm starts and budget handling.
They are not a substitute for the frozen A/B5/B30 experiment manifest.
"""

import copy
import json

import numpy as np
import pytest

import asar_repro.physical_search as search
from asar_repro.physical_model import PhysicalProblem


def _case(name):
    return next(case for case in search.diagnostic_cases() if case["id"] == name)


class _Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


def test_cases_are_fixed_json_complete_common_seeds():
    cases = search.diagnostic_cases()
    assert len(cases) == 6
    assert len({case["id"] for case in cases}) == 6
    assert json.loads(json.dumps(cases, allow_nan=False)) == cases
    for case in cases:
        assert len(case["initial_weights"]) == 4
        assert len(case["times_s"]) - 1 <= 4
        for footprint in ("heading_square", "axis_square"):
            problem = search.problem_from_case(case, footprint)
            score4 = problem.replay(case["initial_waypoints"], connectivity=4)
            score8 = problem.replay(case["initial_waypoints"], connectivity=8)
            assert score4["J"] == pytest.approx(score8["J"], abs=1e-12)
            assert score4["physical_duration_s"] == problem.horizon_s
            assert score4["observation_count"] == problem.tick_count
    # Fixtures returned to callers must not share mutable containers.
    cases[0]["positions_xy"][0][0][0] = 123.0
    assert search.diagnostic_cases()[0]["positions_xy"][0][0][0] == 1.0


@pytest.mark.parametrize("footprint", ["heading_square", "axis_square"])
@pytest.mark.parametrize("connectivity", [4, 8])
def test_independent_oracle_closes_and_matches_model(footprint, connectivity, monkeypatch):
    monkeypatch.setattr(search, "perf_counter", _Clock())
    problem = search.problem_from_case(_case("diagonal_intercept"), footprint)
    result = search.enumerate_physical(problem, connectivity=connectivity, max_seconds=10.0)
    assert result["status"] == "optimal_enumerated"
    assert result["enumeration_complete"] is True
    assert result["proof_elapsed_s"] <= result["max_seconds"]
    assert result["stats"]["complete_routes"] == result["stats"]["scored_routes"]
    assert result["stats"]["scored_routes"] > 0
    replay = problem.replay(result["path"], connectivity=connectivity)
    assert result["J"] == pytest.approx(replay["J"], abs=1e-8)
    assert result["pd_final"] == pytest.approx(replay["pd_final"], abs=1e-8)
    assert result["survival"] == pytest.approx(replay["survival"], abs=1e-8)
    assert result["lower_bound"] == result["J"]
    assert result["formal_certificate"] is False


@pytest.mark.parametrize("footprint", ["heading_square", "axis_square"])
def test_diagonal_intercept_has_strict_equal_clock_witness(footprint, monkeypatch):
    monkeypatch.setattr(search, "perf_counter", _Clock())
    problem = search.problem_from_case(_case("diagonal_intercept"), footprint)
    oracle4 = search.enumerate_physical(problem, connectivity=4, max_seconds=10.0)
    oracle8 = search.enumerate_physical(problem, connectivity=8, max_seconds=10.0)
    assert oracle4["enumeration_complete"] and oracle8["enumeration_complete"]
    assert oracle8["J"] < oracle4["J"] - 1e-8
    diagonal = problem.replay([4, 2, 1], connectivity=8)
    assert diagonal["survival"][1] == pytest.approx(1.0 - 0.7 * 0.78)
    # Both fly for H at v; the diagonal is not given a free shorter mission.
    assert diagonal["physical_duration_s"] == problem.horizon_s
    assert diagonal["distance_m"] == pytest.approx(problem.speed_m_s * problem.horizon_s)


@pytest.mark.parametrize("footprint", ["heading_square", "axis_square"])
def test_shorter_transit_does_not_ensure_better_search_objective(footprint):
    problem = search.problem_from_case(_case("coverage_tradeoff"), footprint)
    via_east = search.independent_replay(problem, [4, 5, 2], connectivity=4)
    via_diagonal = search.independent_replay(problem, [4, 2, 5], connectivity=8)
    # Hand-computed fixed-clock survival: cardinal (.337,.298), diagonal (.961,.298).
    assert via_east["J"] == pytest.approx(0.635, abs=1e-12)
    assert via_diagonal["J"] == pytest.approx(1.259, abs=1e-12)
    assert via_diagonal["planned_arrival_times_s"][1] < via_east["planned_arrival_times_s"][2]
    assert via_diagonal["J"] > via_east["J"]
    assert via_diagonal["pd_final"] == pytest.approx(via_east["pd_final"], abs=1e-12)
    assert via_diagonal["distance_m"] == pytest.approx(via_east["distance_m"], abs=1e-12)


def test_independent_replay_does_not_use_model_geometry_or_sensing(monkeypatch):
    problem = search.problem_from_case(_case("coverage_tradeoff"))

    def forbidden(*args, **kwargs):
        raise AssertionError("independent scorer reused primary model implementation")

    for name in ("vertex_xy", "neighbors", "advance", "observation_mask", "replay"):
        monkeypatch.setattr(PhysicalProblem, name, forbidden)
    score = search.independent_replay(problem, [4, 5, 2], connectivity=4)
    assert score["J"] == pytest.approx(0.635, abs=1e-12)


@pytest.mark.parametrize("scale", [1e-20, 1e12])
@pytest.mark.parametrize("footprint", ["heading_square", "axis_square"])
@pytest.mark.parametrize("connectivity,route", [(4, [4, 5, 2]), (8, [4, 2, 5])])
def test_independent_replay_clock_tolerance_scales_with_horizon(scale, footprint, connectivity, route):
    case = _case("coverage_tradeoff")
    case["cell_width_m"] *= scale
    case["times_s"] = [value * scale for value in case["times_s"]]
    case["positions_xy"] = [[[value * scale for value in point] for point in frame]
                            for frame in case["positions_xy"]]
    problem = search.problem_from_case(case, footprint)
    independent = search.independent_replay(problem, route, connectivity=connectivity)
    primary = problem.replay(route, connectivity=connectivity)
    assert independent["J"] == pytest.approx(primary["J"], abs=1e-8)
    assert independent["pd_final"] == pytest.approx(primary["pd_final"], abs=1e-8)
    assert independent["observation_count"] == 2
    assert independent["physical_duration_s"] == pytest.approx(2.0 * scale, rel=1e-12, abs=0.0)


def test_oracle_does_not_discard_improvements_smaller_than_search_tolerance(monkeypatch):
    monkeypatch.setattr(search, "perf_counter", _Clock())
    case = _case("coverage_tradeoff")
    case["q"] = 1e-12
    problem = search.problem_from_case(case)
    result = search.enumerate_physical(problem, connectivity=4, max_seconds=10.0)
    known_better = search.independent_replay(problem, [4, 5, 2], connectivity=4)
    assert result["enumeration_complete"] is True
    assert result["J"] <= known_better["J"]
    assert result["lower_bound"] == result["J"]


@pytest.mark.parametrize("name", ["late_drift", "special_mass", "turning_footprint"])
@pytest.mark.parametrize("footprint", ["heading_square", "axis_square"])
def test_dynamic_special_and_footprint_fixtures_cross_replay(name, footprint):
    case = _case(name)
    problem = search.problem_from_case(case, footprint)
    independent = search.independent_replay(problem, case["initial_waypoints"], connectivity=4)
    primary = problem.replay(case["initial_waypoints"], connectivity=4)
    assert independent["J"] == pytest.approx(primary["J"], abs=1e-8)
    assert independent["survival"] == pytest.approx(primary["survival"], abs=1e-8)
    if name == "special_mass":
        assert min(independent["survival"]) >= 0.4 - 1e-12
        assert independent["final_weights"][2:] == pytest.approx([0.2, 0.2])


@pytest.mark.parametrize("connectivity", [4, 8])
def test_anytime_keeps_seed_and_scores_all_incumbents(connectivity, monkeypatch):
    monkeypatch.setattr(search, "perf_counter", _Clock())
    case = _case("diagonal_intercept")
    problem = search.problem_from_case(case)
    initial = problem.replay(case["initial_waypoints"], connectivity=connectivity)
    oracle = search.enumerate_physical(problem, connectivity=connectivity, max_seconds=10.0)
    result = search.solve_physical(problem, connectivity=connectivity,
                                   initial_waypoints=case["initial_waypoints"], max_seconds=2.0)
    assert result["status"] == "completed"
    assert oracle["J"] - 1e-8 <= result["J"] <= initial["J"] + 1e-8
    assert result["history"][0]["source"] == "initial_route"
    assert result["global_optimality_certified"] is False
    assert result["epsilon_certificate"] is None
    values = [entry["J"] for entry in result["history"]]
    assert values == sorted(values, reverse=True)
    for entry in result["history"]:
        assert entry["elapsed_s"] <= result["max_seconds"]
        replay = problem.replay(entry["path"], connectivity=connectivity)
        assert entry["J"] == pytest.approx(replay["J"], abs=1e-8)
        assert entry["pd_final"] == pytest.approx(replay["pd_final"], abs=1e-8)
    assert result["J"] == result["history"][-1]["J"]


def test_zero_budget_has_no_free_initial_solution(monkeypatch):
    monkeypatch.setattr(search, "perf_counter", _Clock())
    case = _case("diagonal_intercept")
    result = search.solve_physical(search.problem_from_case(case), connectivity=4,
                                   initial_waypoints=case["initial_waypoints"], max_seconds=0.0)
    assert result["status"] == "budget_exceeded"
    assert result["best"] is None
    assert result["history"] == []
    assert result["stats"]["replayed_candidates"] == 0


def test_late_initial_replay_is_raw_only(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(search, "perf_counter", clock)
    original = PhysicalProblem.replay

    def delayed(self, route, connectivity=4):
        score = original(self, route, connectivity)
        clock.value += 2.0
        return score

    monkeypatch.setattr(PhysicalProblem, "replay", delayed)
    case = _case("diagonal_intercept")
    result = search.solve_physical(search.problem_from_case(case), connectivity=4,
                                   initial_waypoints=case["initial_waypoints"], max_seconds=1.0)
    assert result["status"] == "budget_exceeded"
    assert result["best"] is None and result["history"] == []
    assert result["late_candidates"][0]["source"] == "initial_route"
    assert result["late_candidates"][0]["elapsed_s"] > result["max_seconds"]


def test_late_improvement_does_not_replace_valid_seed(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(search, "perf_counter", clock)
    original = PhysicalProblem.replay
    calls = 0

    def delayed_after_seed(self, route, connectivity=4):
        nonlocal calls
        score = original(self, route, connectivity)
        calls += 1
        if calls > 1:
            clock.value += 2.0
        return score

    case = _case("diagonal_intercept")
    problem = search.problem_from_case(case)
    seed = problem.replay(case["initial_waypoints"], connectivity=8)
    monkeypatch.setattr(PhysicalProblem, "replay", delayed_after_seed)
    result = search.solve_physical(problem, connectivity=8,
                                   initial_waypoints=case["initial_waypoints"], max_seconds=1.0)
    assert result["status"] == "budget_exceeded"
    assert result["J"] == seed["J"]
    assert len(result["history"]) == 1
    assert result["late_candidates"][0]["source"] == "search"
    assert result["late_candidates"][0]["score"]["J"] < seed["J"]


def test_late_oracle_final_audit_cannot_claim_closure(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(search, "perf_counter", clock)
    original = PhysicalProblem.replay

    def delayed(self, route, connectivity=4):
        result = original(self, route, connectivity)
        clock.value += 2.0
        return result

    monkeypatch.setattr(PhysicalProblem, "replay", delayed)
    problem = search.problem_from_case(_case("diagonal_intercept"))
    result = search.enumerate_physical(problem, connectivity=8, max_seconds=1.0)
    assert result["status"] == "budget_exceeded"
    assert result["enumeration_complete"] is False
    assert result["proof_elapsed_s"] > result["max_seconds"]
    assert result["lower_bound"] is None and result["gap"] is None
    assert result["history"] and result["best"] is not None
    assert result["late_candidates"][0]["source"] == "final_oracle_audit"


def test_open_limit_stops_instead_of_beam_truncation(monkeypatch):
    monkeypatch.setattr(search, "perf_counter", _Clock())
    case = _case("repeat_detection")
    problem = search.problem_from_case(case)
    seed = problem.replay(case["initial_waypoints"], connectivity=8)
    result = search.solve_physical(problem, connectivity=8,
                                   initial_waypoints=case["initial_waypoints"],
                                   max_seconds=2.0, max_open=1)
    assert result["stop_reason"] == "max_open"
    assert result["status"] == "budget_exceeded"
    assert result["peak_open"] == 1 and result["open_count"] == 1
    assert result["J"] <= seed["J"] + 1e-8


def test_guide_retains_state_and_has_no_connectivity_parameter(monkeypatch):
    monkeypatch.setattr(search, "perf_counter", _Clock())
    case = _case("special_mass")
    for frame in case["positions_xy"]:
        frame[3] = [float("nan"), float("nan")]
    problem = search.problem_from_case(case)
    state = problem.initial_state()
    before = state.weights.copy()
    guide = search._CoarseCellGuide(problem, search._Budget(0.0, 2.0))
    value = guide.remaining_cost(state)
    assert np.isfinite(value) and value >= 0.4 * problem.tick_count - 1e-12
    np.testing.assert_array_equal(state.weights, before)
    assert guide.remaining_cost(state) == value


def test_invalid_seed_cannot_silently_become_a_partial_route(monkeypatch):
    monkeypatch.setattr(search, "perf_counter", _Clock())
    problem = search.problem_from_case(_case("diagonal_intercept"))
    result = search.solve_physical(problem, connectivity=4, initial_waypoints=[4, 5], max_seconds=2.0)
    assert result["status"] == "failed"
    assert result["error"]["type"] == "ValueError"
    assert result["best"] is None and result["history"] == []


def test_oracle_size_guard_has_no_false_proof():
    case = copy.deepcopy(_case("repeat_detection"))
    case["times_s"] = list(range(8))
    case["positions_xy"] = [case["positions_xy"][0] for _ in range(8)]
    case["searchable"] = [[True] * 4 for _ in range(8)]
    result = search.enumerate_physical(search.problem_from_case(case), connectivity=8, max_seconds=10.0)
    assert result["status"] == "blocked"
    assert result["lower_bound"] is None
    assert result["proof_elapsed_s"] is None
    assert result["history"] == []
