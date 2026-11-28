"""Progress-gated prefix search: causal policy, OPEN semantics, and tiny oracle."""
from types import SimpleNamespace

import pytest

from asar_repro import (
    physical_accel, physical_progress_prefix, physical_refinement, physical_search,
)


def _entry(priority, serial, tick):
    return (priority, serial, SimpleNamespace(tick=tick), (serial,))


def test_unarmed_pop_uses_original_global_minimum():
    frontier = physical_progress_prefix._ProgressFrontier(20)
    frontier.push(_entry(99, 1, 3))
    frontier.push(_entry(1, 2, 15))
    assert frontier.pop(3, allow_reserved=False)[1] == 2
    assert frontier.pop(3, allow_reserved=False)[1] == 1


def test_armed_pop_can_reserve_early_and_fallback_when_empty():
    frontier = physical_progress_prefix._ProgressFrontier(20)
    frontier.push(_entry(99, 1, 3))
    frontier.push(_entry(1, 2, 15))
    assert frontier.pop(3, allow_reserved=True)[1] == 1
    assert frontier.pop(4, allow_reserved=True)[1] == 2
    assert frontier.statistics()["reserved_early_pops"] == 1


def test_no_future_information_and_late_complete_protection():
    control = physical_progress_prefix._ProgressController(50, 30.0)
    for _ in range(512):
        control.observe_expansion(49)
    assert not control.should_reserve(10.0, 1.0)
    control.register_search_improvement(7.0)
    assert not control.should_reserve(20.0, 7.0)
    assert control.statistics()["activations"] == 0


def test_early_search_improvement_and_stall_activate_then_hysteresis_release():
    control = physical_progress_prefix._ProgressController(50, 30.0)
    for _ in range(512):
        control.observe_expansion(49)
    control.register_search_improvement(1.0)
    assert not control.should_reserve(2.5, 1.0)
    assert control.should_reserve(3.5, 1.0)
    assert control.statistics()["activations"] == 1
    assert not control.should_reserve(3.6, 3.4)
    for _ in range(512):
        control.observe_expansion(5)
    assert not control.should_reserve(9.0, 1.0)
    assert control.statistics()["deactivations"] >= 1


@pytest.fixture
def clock(monkeypatch):
    for module in (physical_accel, physical_progress_prefix, physical_refinement, physical_search):
        monkeypatch.setattr(module, "perf_counter", lambda: 0.0)


@pytest.mark.parametrize("case", physical_search.diagnostic_cases(), ids=lambda case: case["id"])
@pytest.mark.parametrize("connectivity", [4, 8])
def test_progress_solver_exhaustion_matches_independent_oracle(case, connectivity, clock):
    problem = physical_search.problem_from_case(case, footprint="heading_square")
    oracle = physical_search.enumerate_physical(problem, connectivity=connectivity,
                                               max_seconds=30.0)
    solution = physical_progress_prefix.solve_physical_progress_prefix(
        problem, connectivity=connectivity, initial_waypoints=case["initial_waypoints"],
        max_seconds=30.0, completion="none",
    )
    assert oracle["enumeration_complete"]
    assert solution["error"] is None
    assert solution["stop_reason"] == "frontier_exhausted"
    assert solution["J"] == pytest.approx(oracle["J"], abs=1e-8)
    assert not solution["global_optimality_certified"]
    replay = physical_search.independent_replay(problem, solution["waypoints"],
                                                 connectivity=connectivity)
    assert replay["J"] == pytest.approx(solution["J"], abs=1e-8)
    assert replay["pd_final"] == pytest.approx(solution["pd_final"], abs=1e-8)
    assert len(replay["survival"]) == problem.tick_count + 1
    assert solution["diagnostics"]["progress_schedule"]["activations"] == 0


def test_max_open_is_global_not_per_band(clock):
    case = next(item for item in physical_search.diagnostic_cases()
                if item["id"] == "repeat_detection")
    problem = physical_search.problem_from_case(case)
    solution = physical_progress_prefix.solve_physical_progress_prefix(
        problem, connectivity=8, initial_waypoints=case["initial_waypoints"],
        max_seconds=30.0, max_open=3,
    )
    assert solution["error"] is None
    assert solution["stop_reason"] == "max_open"
    assert solution["open_count"] == solution["peak_open"] == 3
