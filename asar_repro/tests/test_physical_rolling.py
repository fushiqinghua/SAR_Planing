"""Prepared local tests for the two-arm rolling experiment; not run at delivery.

They check a full-prefix root against independently replayed physical states,
the unchanged root search, virtual execution commitments, and shared deadlines.
Fake clocks avoid sleeps and make late-return/validation cases deterministic.
"""
from __future__ import annotations

import hashlib

import numpy as np
import pytest

from asar_repro import physical_accel as accel
from asar_repro import physical_refinement as refinement
from asar_repro import physical_rolling as rolling
from asar_repro import physical_rolling_solver as prefix_solver
from asar_repro import physical_search as search
from asar_repro.physical_model import PhysicalProblem


class _Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += float(seconds)


@pytest.fixture
def clock(monkeypatch):
    value = _Clock()
    for module in (accel, refinement, prefix_solver, search, rolling):
        monkeypatch.setattr(module, "perf_counter", value)
    return value


def _long_problem():
    # One target particle moves from west to east after the first observation.
    # The other 20% of mass is permanently unsearchable and must not disappear.
    positions = np.zeros((11, 2, 2), dtype=float)
    positions[:, 0, 0] = 10.0
    positions[:2, 0, 0] = -10.0
    positions[:, 1, :] = 1000.0
    searchable = np.ones((11, 2), dtype=bool)
    searchable[:, 1] = False
    problem = PhysicalProblem(
        rows=3, cols=3, cell_width_m=10.0, speed_m_s=1.0,
        times_s=np.arange(11, dtype=float) * 10.0,
        positions_xy=positions, searchable=searchable,
        initial_weights=np.asarray([0.8, 0.2]),
        start=4, q=0.78, footprint="heading_square",
        trajectory_ids=np.asarray([71, 72]),
    )
    return problem, [4, 3, 4, 3, 4, 3, 4, 3, 4, 3, 4]


def _east_suffix(prefix):
    route = list(prefix)
    while len(route) < 11:
        route.append(5 if route[-1] == 4 else 4)
    return route


def _raw(problem, route):
    score = problem.replay(route, connectivity=8)
    return dict(
        status="completed", error=None, best=score,
        J=score["J"], pd_final=score["pd_final"],
        waypoints=list(route), path=list(route), survival=score["survival"],
    )


@pytest.mark.parametrize("footprint", ["heading_square", "axis_square"])
@pytest.mark.parametrize("completion", ["none", "greedy"])
def test_empty_committed_prefix_preserves_frozen_search(footprint, completion, clock):
    case = next(item for item in search.diagnostic_cases() if item["id"] == "late_drift")
    problem = search.problem_from_case(case, footprint)
    options = dict(
        connectivity=8, initial_waypoints=case["initial_waypoints"], max_seconds=30,
        completion=completion, archive=True, max_expansions=3,
    )
    old = refinement.solve_physical_refinement(problem, **options)
    new = prefix_solver.solve_physical_prefix(problem, root_prefix=(problem.start,), **options)
    assert old["error"] is None and new["error"] is None
    for key in ("J", "pd_final", "waypoints", "survival", "history", "best", "expanded",
                "generated", "peak_open", "open_count", "stop_reason", "pareto_archive_history"):
        assert old[key] == new[key], key
    assert old["diagnostics"]["pop_trace"] == new["diagnostics"]["pop_trace"]


def test_nonempty_root_keeps_absolute_time_past_cost_and_particle_mass(clock):
    problem, seed = _long_problem()
    prefix = seed[:4]
    expected = problem.initial_state()
    for vertex in prefix[1:]:
        expected = problem.advance(expected, vertex, connectivity=8)
    result = prefix_solver.solve_physical_prefix(
        problem, connectivity=8, initial_waypoints=seed, root_prefix=prefix,
        max_seconds=30, max_expansions=1, completion="greedy", archive=True,
    )
    assert result["error"] is None
    state = result["root_state"]
    assert state["time_s"] == 30.0
    assert state["tick"] == 3
    assert state["J"] == expected.J > 0
    assert state["survival"] == list(expected.survival)
    assert state["remaining_mass"] == pytest.approx(expected.weights.sum())
    assert state["remaining_mass"] < 1.0
    assert state["weights_sha256"] == hashlib.sha256(expected.weights.tobytes()).hexdigest()
    for entry in result["history"] + result["pareto_archive_history"]:
        assert entry["waypoints"][:len(prefix)] == prefix
        score = problem.replay(entry["waypoints"], connectivity=8)
        assert score["J"] == pytest.approx(entry["J"], abs=1e-12)
        assert score["observation_times_s"] == problem.times_s[1:].tolist()
        assert score["physical_duration_s"] == 100.0
        assert score["final_weights"][1] == pytest.approx(0.2)
    assert not result["global_optimality_certified"]


@pytest.mark.parametrize("prefix", [[4, 5], [3], [], [4, 3, 4, 3, 4, 3, 4, 3, 4, 3, 4]])
def test_invalid_or_terminal_prefix_is_not_silently_restarted(prefix, clock):
    problem, seed = _long_problem()
    result = prefix_solver.solve_physical_prefix(
        problem, connectivity=8, initial_waypoints=seed,
        root_prefix=prefix, max_seconds=30, max_expansions=1,
    )
    assert result["status"] == "failed"
    assert result["error"] is not None


def test_C0_uses_original_solver_once_and_same_full_clock(monkeypatch, clock):
    problem, seed = _long_problem()
    calls = []

    def original(problem, **kwargs):
        calls.append(kwargs)
        clock.advance(1.0)
        return _raw(problem, _east_suffix((problem.start,)))

    def forbidden(*args, **kwargs):
        raise AssertionError("C0 called prefix solver")

    monkeypatch.setattr(rolling, "solve_physical_refinement", original)
    monkeypatch.setattr(rolling, "solve_physical_prefix", forbidden)
    result = rolling.run_physical_rolling(problem, method="C0", initial_waypoints=seed)
    assert result["status"] == "completed"
    assert len(calls) == len(result["phases"]) == 1
    assert calls[0]["max_seconds"] == pytest.approx(29.75)
    assert result["phases"][0]["stage_kind"] == "pre_cst"
    assert result["best"]["physical_duration_s"] == problem.horizon_s
    assert result["planned_observation_times_s"] == problem.times_s[1:].tolist()


def test_C1_accepts_only_after_committed_prefix_and_before_anchor(monkeypatch, clock):
    problem, seed = _long_problem()
    calls = []

    def inner(problem, **kwargs):
        prefix = tuple(kwargs["root_prefix"])
        calls.append(kwargs)
        clock.advance(1.0)
        route = kwargs["initial_waypoints"] if len(prefix) == 1 else _east_suffix(prefix)
        return _raw(problem, route)

    monkeypatch.setattr(rolling, "solve_physical_prefix", inner)
    result = rolling.run_physical_rolling(problem, method="C1", initial_waypoints=seed)
    assert result["status"] == "completed"
    assert len(result["phases"]) == 5
    first_online = result["phases"][1]
    assert first_online["request_time_s"] == 20.0
    assert first_online["anchor_time_s"] == 30.0
    assert first_online["committed_prefix_waypoints"] == seed[:4]
    assert first_online["accepted"]
    assert first_online["ready_time_s"] == 21.0
    for phase in result["phases"]:
        assert phase["allocated_seconds"] <= 6.0
        if phase["accepted"]:
            assert phase["acceptance_compute_s"] <= phase["allocated_seconds"]
            assert phase["cumulative_acceptance_compute_s"] <= 30.0
            assert result["waypoints"][:len(phase["committed_prefix_waypoints"])] == phase["committed_prefix_waypoints"]
            if phase["stage_index"]:
                assert phase["ready_time_s"] <= phase["anchor_time_s"]
    assert result["best"]["observation_count"] == problem.tick_count
    assert result["best"]["final_weights"][1] == pytest.approx(0.2)
    assert result["phase_compute_sum_s"] + result["finalization_compute_s"] == pytest.approx(result["active_compute_s"])


def test_late_online_return_keeps_old_route_and_debits_later_slots(monkeypatch, clock):
    problem, seed = _long_problem()
    calls = []

    def inner(problem, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            clock.advance(1.0)
            return _raw(problem, kwargs["initial_waypoints"])
        clock.advance(29.0)
        return _raw(problem, _east_suffix(kwargs["root_prefix"]))

    monkeypatch.setattr(rolling, "solve_physical_prefix", inner)
    result = rolling.run_physical_rolling(problem, method="C1", initial_waypoints=seed)
    assert result["status"] == "completed"
    assert result["waypoints"] == seed
    assert len(calls) == 2
    assert result["phases"][1]["reason"] == "returned_after_deadline"
    assert result["phases"][1]["actual_compute_s"] == 29.0
    assert result["phases"][1]["ready_time_s"] == 49.0
    assert all(row["reason"] == "shared_budget_exhausted" for row in result["phases"][2:])
    assert all(not row["accepted"] for row in result["phases"])


def test_expensive_final_validation_cannot_accept_late_route(monkeypatch, clock):
    problem, seed = _long_problem()
    real_verify = rolling._verify_candidate

    def inner(problem, **kwargs):
        clock.advance(1.0)
        return _raw(problem, _east_suffix((problem.start,)))

    def delayed_verify(*args, **kwargs):
        result = real_verify(*args, **kwargs)
        clock.advance(30.0)
        return result

    monkeypatch.setattr(rolling, "solve_physical_refinement", inner)
    monkeypatch.setattr(rolling, "_verify_candidate", delayed_verify)
    result = rolling.run_physical_rolling(problem, method="C0", initial_waypoints=seed)
    assert result["waypoints"] == seed
    assert result["phases"][0]["reason"] == "validation_after_deadline"
    assert not result["phases"][0]["accepted"]
    assert result["deadline_overshoot_s"] == pytest.approx(1.0)


def test_partial_terminal_edge_is_never_used_as_anchor():
    score = dict(waypoints=[4, 0, 4], planned_arrival_times_s=[0.0, 14.142, 28.284])
    request, anchor, prefix = rolling._select_anchor(
        score, fraction=.7, horizon_s=20.0, execution_time_s=0.0,
        protected_prefix=[4], allocated_seconds=6.0, guard_s=.25, tolerance_s=1e-12,
    )
    assert request == (1, 14.142)
    assert anchor is None and prefix is None


def test_candidate_cannot_rewrite_an_executed_prefix(monkeypatch, clock):
    problem, seed = _long_problem()
    calls = []

    def inner(problem, **kwargs):
        calls.append(kwargs)
        clock.advance(1.0)
        route = seed if len(calls) == 1 else _east_suffix((problem.start,))
        return _raw(problem, route)

    monkeypatch.setattr(rolling, "solve_physical_prefix", inner)
    result = rolling.run_physical_rolling(problem, method="C1", initial_waypoints=seed)
    assert result["status"] == "failed"
    assert "prefix" in result["error"]["message"]
    assert result["waypoints"] == seed


def test_formal_api_rejects_expansion_limit_and_invalid_triggers(clock):
    problem, seed = _long_problem()
    with pytest.raises(ValueError, match="expansion"):
        rolling.run_physical_rolling(problem, method="C1", initial_waypoints=seed,
                                     solver_options={"max_expansions": 3})
    with pytest.raises(ValueError, match="triggers"):
        rolling.run_physical_rolling(problem, method="C1", initial_waypoints=seed, triggers=(.4, .2))
