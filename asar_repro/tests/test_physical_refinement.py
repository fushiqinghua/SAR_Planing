"""Pending local validation of the physical refinement batch.

These tests have not been executed at delivery.  They compare the instrumented
control against the unchanged cached solver, exercise the J/Pd tradeoff on a
hand-computable dynamic fixture, and protect deadline and candidate provenance.
"""
from __future__ import annotations

import hashlib

import numpy as np
import pytest

from asar_repro import physical_accel as accel
from asar_repro import physical_refinement as refinement
from asar_repro import physical_search as original
from asar_repro.physical_model import PhysicalProblem


class _Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


@pytest.fixture
def clock(monkeypatch):
    value = _Clock()
    for module in (refinement, accel, original):
        monkeypatch.setattr(module, "perf_counter", value)
    return value


def _case(name="diagonal_intercept"):
    return next(case for case in original.diagnostic_cases() if case["id"] == name)


def _tradeoff():
    # At t=1, 0.7 mass is at the east neighbour.  At t=2, 0.9 mass
    # is at the north-west corner, unreachable from that east neighbour.
    # Early interception: S=(1,.454,.454), J=.908, Pd=.546.
    # Late interception:  S=(1,1,.298),    J=1.298, Pd=.702.
    # All positions and paths have cardinal movements in the fixture.
    return PhysicalProblem(
        rows=3, cols=3, cell_width_m=1.0, speed_m_s=1.0,
        times_s=np.asarray([0.0, 1.0, 2.0]),
        positions_xy=np.asarray([
            [[0.0, 0.0], [0.0, 0.0], [5.0, 5.0]],
            [[1.0, 0.0], [5.0, 5.0], [5.0, 5.0]],
            [[-1.0, 1.0], [-1.0, 1.0], [5.0, 5.0]],
        ]),
        searchable=np.ones((3, 3), dtype=bool),
        initial_weights=np.asarray([0.7, 0.2, 0.1]),
        start=4, q=0.78, footprint="axis_square",
        trajectory_ids=np.asarray([101, 102, 103]),
    )


@pytest.mark.parametrize("name", [
    "diagonal_intercept", "late_drift", "repeat_detection",
    "special_mass", "coverage_tradeoff", "turning_footprint",
])
@pytest.mark.parametrize("footprint", ["heading_square", "axis_square"])
@pytest.mark.parametrize("connectivity", [4, 8])
def test_instrumented_control_preserves_finite_toy_decisions(name, footprint, connectivity, clock):
    case = _case(name)
    problem = original.problem_from_case(case, footprint)
    options = dict(connectivity=connectivity, initial_waypoints=case["initial_waypoints"], max_seconds=30)
    reference = accel.solve_physical_accel(problem, **options)
    candidate = refinement.solve_physical_refinement(problem, **options)
    assert reference["status"] == candidate["status"] == "completed"
    for key in ("stop_reason", "best", "J", "pd_final", "path", "survival", "history",
                "expanded", "generated", "peak_open", "open_count"):
        assert candidate[key] == reference[key], key
    for key in ("safe_pruned", "terminal_candidates", "replayed_candidates", "guide_calls"):
        assert candidate["stats"][key] == reference["stats"][key], key
    hist = candidate["diagnostics"]["histograms"]
    assert sum(hist["expanded_depth"].values()) == candidate["expanded"]
    assert sum(hist["expanded_tick"].values()) == candidate["expanded"]
    assert sum(hist["generated_depth"].values()) == candidate["generated"]
    assert sum(hist["frontier_depth"].values()) == candidate["open_count"]
    assert sum(hist["frontier_tick"].values()) == candidate["open_count"]
    assert candidate["pareto_archive"] == []
    assert candidate["diagnostics"]["pop_trace"] == []
    assert not candidate["global_optimality_certified"]


@pytest.mark.parametrize("connectivity", [4, 8])
def test_bounded_prefix_matches_unchanged_cached_heap_order(connectivity, clock, monkeypatch):
    case = _case("repeat_detection")
    problem = original.problem_from_case(case)
    options = dict(connectivity=connectivity, initial_waypoints=case["initial_waypoints"], max_seconds=30)
    reference_trace = []
    real_pop = accel.heapq.heappop

    def limited_pop(heap):
        if len(reference_trace) >= 2:
            raise accel._Deadline
        item = real_pop(heap)
        state, path = item[2], item[3]
        reference_trace.append(dict(
            priority=item[0], serial=item[1], path=list(path), vertex=state.vertex,
            time_s=state.time_s, tick=state.tick, J=state.J,
            weights_sha256=hashlib.sha256(state.weights.tobytes()).hexdigest(),
        ))
        return item

    with monkeypatch.context() as patch:
        patch.setattr(accel.heapq, "heappop", limited_pop)
        reference = accel.solve_physical_accel(problem, **options)
    assert reference["expanded"] == 2
    candidate = refinement.solve_physical_refinement(problem, **options, max_expansions=2)
    assert candidate["stop_reason"] == "max_expansions"
    assert candidate["diagnostics"]["pop_trace"] == reference_trace
    assert candidate["history"] == reference["history"]
    for key in ("expanded", "generated", "peak_open", "open_count"):
        assert candidate[key] == reference[key]
    assert candidate["formal_timed_task"] is False


@pytest.mark.parametrize("connectivity", [4, 8])
def test_small_open_limit_is_a_stop_and_not_beam_truncation(connectivity, clock):
    case = _case("repeat_detection")
    problem = original.problem_from_case(case)
    options = dict(connectivity=connectivity, initial_waypoints=case["initial_waypoints"],
                   max_seconds=30, max_open=3)
    reference = accel.solve_physical_accel(problem, **options)
    candidate = refinement.solve_physical_refinement(problem, **options)
    assert candidate["stop_reason"] == reference["stop_reason"] == "max_open"
    assert candidate["history"] == reference["history"]
    assert candidate["open_count"] == reference["open_count"] == 3


def test_hand_computed_tradeoff_and_feasible_guard_bound(clock):
    problem = _tradeoff()
    common_seed = [4, 1, 0]
    early = problem.replay([4, 5, 2], connectivity=4)
    late = problem.replay(common_seed, connectivity=4)
    assert early["J"] == pytest.approx(0.908)
    assert early["pd_final"] == pytest.approx(0.546)
    assert late["J"] == pytest.approx(1.298)
    assert late["pd_final"] == pytest.approx(0.702)
    options = dict(connectivity=4, initial_waypoints=common_seed, max_seconds=30,
                   completion="greedy", archive=True)
    unconstrained = refinement.solve_physical_refinement(problem, **options)
    guarded = refinement.solve_physical_refinement(
        problem, **options, objective="J_pd_guard", pd_floor=late["pd_final"], pd_tolerance=1e-8)
    assert unconstrained["J"] < guarded["J"]
    assert unconstrained["pd_final"] < late["pd_final"]
    assert guarded["J"] == pytest.approx(late["J"])
    assert guarded["pd_final"] >= late["pd_final"] - 1e-8
    # A low-J infeasible completion must not prune the higher-J feasible arm.
    assert guarded["expanded"] > unconstrained["expanded"]
    assert guarded["stats"]["guard_rejected_replayed"] > 0
    assert guarded["constraint_status"] == "feasible_incumbent"
    assert all(row["pd_final"] >= late["pd_final"] - 1e-8 for row in guarded["history"])
    assert any(row["pd_final"] < late["pd_final"] - 1e-8
               for row in guarded["pareto_archive"])
    assert any(row["pd_final"] >= late["pd_final"] - 1e-8
               for row in guarded["pareto_archive"])


@pytest.mark.parametrize("connectivity", [4, 8])
def test_completion_has_one_shared_rule_and_every_saved_route_replays(connectivity, clock):
    problem = _tradeoff()
    result = refinement.solve_physical_refinement(
        problem, connectivity=connectivity, initial_waypoints=[4, 1, 0], max_seconds=30,
        completion="greedy", archive=True, max_expansions=1)
    assert result["stats"]["completion_calls"] == result["stats"]["completion_finished"] == 1
    assert result["J"] == pytest.approx(0.908)
    assert result["history"][-1]["source"] == "completion"
    for entry in result["history"] + result["pareto_archive"]:
        replayed = problem.replay(entry["waypoints"], connectivity=connectivity)
        assert replayed["J"] == pytest.approx(entry["J"], abs=1e-12)
        assert replayed["pd_final"] == pytest.approx(entry["pd_final"], abs=1e-12)
        assert replayed["physical_duration_s"] == problem.horizon_s
        assert replayed["distance_m"] == pytest.approx(problem.speed_m_s * problem.horizon_s)
        assert entry["elapsed_s"] <= result["max_seconds"]
    assert not result["archive_global_complete"]
    assert result["archive_scope"].startswith("encountered_replayed_only")


def test_completion_calls_are_bounded_including_the_root(clock):
    case = _case("repeat_detection")
    result = refinement.solve_physical_refinement(
        original.problem_from_case(case), connectivity=4,
        initial_waypoints=case["initial_waypoints"], max_seconds=30,
        completion="greedy", completion_every=1, completion_max_calls=2, max_expansions=3)
    assert result["stats"]["completion_calls"] == 2
    assert result["stats"]["completion_finished"] == 2
    assert result["stats"]["completion_transitions"] > 0


def test_guard_rejects_an_infeasible_seed_instead_of_claiming_a_fallback(clock):
    result = refinement.solve_physical_refinement(
        _tradeoff(), connectivity=4, initial_waypoints=[4, 5, 2], max_seconds=30,
        completion="greedy", archive=True, objective="J_pd_guard", pd_floor=0.7)
    assert result["status"] == "failed"
    assert result["best"] is None and result["history"] == []
    assert result["pareto_archive"] == []
    assert "initial route does not satisfy" in result["error"]["message"]
    assert result["constraint_status"] == "no_feasible_incumbent"


def test_guard_tolerance_is_explicit_and_only_applied_to_terminal_feasibility(clock):
    problem = _tradeoff()
    seed = [4, 1, 0]
    pd_seed = problem.replay(seed, 4)["pd_final"]
    near = refinement.solve_physical_refinement(
        problem, connectivity=4, initial_waypoints=seed, max_seconds=30,
        objective="J_pd_guard", pd_floor=pd_seed + 0.5e-8, pd_tolerance=1e-8)
    far = refinement.solve_physical_refinement(
        problem, connectivity=4, initial_waypoints=seed, max_seconds=30,
        objective="J_pd_guard", pd_floor=pd_seed + 2e-8, pd_tolerance=1e-8)
    assert near["constraint_status"] == "feasible_incumbent"
    assert far["status"] == "failed"


def test_first_terminal_is_distinct_from_first_new_complete_replay(clock):
    case = _case("repeat_detection")
    case["q"] = 0.0
    result = refinement.solve_physical_refinement(
        original.problem_from_case(case), connectivity=4,
        initial_waypoints=case["initial_waypoints"], max_seconds=30, completion="greedy")
    assert len(result["history"]) == 1
    assert result["stats"]["terminal_candidates"] > 0
    assert result["diagnostics"]["first_terminal_generated_s"] == 0.0
    assert result["diagnostics"]["first_completion_terminal_generated_s"] == 0.0
    assert result["diagnostics"]["first_new_complete_replay_s"] is None
    assert result["stats"]["replayed_candidates"] == 1


def test_late_completion_cannot_replace_best_or_delete_a_timely_archive_point(clock, monkeypatch):
    real_replay = PhysicalProblem.replay
    calls = []

    def delayed(self, *args, **kwargs):
        score = real_replay(self, *args, **kwargs)
        calls.append(score)
        if len(calls) == 2:
            clock.value = 2.0
        return score

    monkeypatch.setattr(PhysicalProblem, "replay", delayed)
    result = refinement.solve_physical_refinement(
        _tradeoff(), connectivity=4, initial_waypoints=[4, 1, 0], max_seconds=1,
        completion="greedy", archive=True)
    assert result["stop_reason"] == "max_seconds"
    assert result["J"] == pytest.approx(1.298)
    assert len(result["history"]) == len(result["pareto_archive"]) == 1
    assert len(result["late_candidates"]) == 1
    assert result["late_candidates"][0]["source"] == "completion"
    assert result["late_candidates"][0]["score"]["J"] == pytest.approx(0.908)
    assert result["diagnostics"]["first_new_complete_replay_s"] is None


def test_replay_mismatch_is_a_failure_and_never_enters_the_archive(clock, monkeypatch):
    real_replay = PhysicalProblem.replay
    calls = 0

    def corrupted(self, *args, **kwargs):
        nonlocal calls
        score = real_replay(self, *args, **kwargs)
        calls += 1
        if calls == 2:
            score["J"] += 0.1
        return score

    monkeypatch.setattr(PhysicalProblem, "replay", corrupted)
    result = refinement.solve_physical_refinement(
        _tradeoff(), connectivity=4, initial_waypoints=[4, 1, 0], max_seconds=30,
        completion="greedy", archive=True)
    assert result["status"] == "failed"
    assert "full physical replay disagree" in result["error"]["message"]
    assert len(result["history"]) == len(result["pareto_archive"]) == 1


def test_zero_budget_has_no_free_initial_route_or_cache(clock):
    result = refinement.solve_physical_refinement(
        _tradeoff(), connectivity=4, initial_waypoints=[4, 1, 0], max_seconds=0,
        completion="greedy", archive=True)
    assert result["stop_reason"] == "max_seconds"
    assert result["best"] is None and result["history"] == []
    assert result["pareto_archive"] == [] and result["cache_statistics"] is None


def test_rollout_transitions_are_charged(clock, monkeypatch):
    real_advance = accel.CachedPhysicalProblem.advance

    def delayed(self, *args, **kwargs):
        state = real_advance(self, *args, **kwargs)
        clock.value = 2.0
        return state

    monkeypatch.setattr(accel.CachedPhysicalProblem, "advance", delayed)
    result = refinement.solve_physical_refinement(
        _tradeoff(), connectivity=4, initial_waypoints=[4, 1, 0], max_seconds=1,
        completion="greedy", archive=True)
    assert result["stop_reason"] == "max_seconds"
    assert result["stats"]["completion_calls"] == 1
    assert result["stats"]["completion_finished"] == 0
    assert result["J"] == pytest.approx(1.298)
    assert len(result["pareto_archive"]) == 1


def test_cache_setup_is_charged_before_the_seed_can_be_replayed(clock, monkeypatch):
    real_init = accel.CachedPhysicalProblem.__init__

    def delayed(self, problem):
        real_init(self, problem)
        clock.value = 2.0

    monkeypatch.setattr(accel.CachedPhysicalProblem, "__init__", delayed)
    result = refinement.solve_physical_refinement(
        _tradeoff(), connectivity=4, initial_waypoints=[4, 1, 0], max_seconds=1,
        completion="greedy", archive=True)
    assert result["stop_reason"] == "max_seconds"
    assert result["history"] == result["pareto_archive"] == []
    assert result["stats"]["replayed_candidates"] == 0


def test_archive_limit_preserves_overflow_and_explicitly_stops(clock):
    result = refinement.solve_physical_refinement(
        _tradeoff(), connectivity=4, initial_waypoints=[4, 1, 0], max_seconds=30,
        completion="greedy", archive=True, archive_limit=1)
    assert result["stop_reason"] == "max_archive"
    assert result["archive_limit_reached"]
    assert len(result["pareto_archive"]) == 2
    assert result["J"] == pytest.approx(0.908)
    assert all(row["elapsed_s"] <= 30 for row in result["pareto_archive"])


def test_archive_history_limit_preserves_the_event_and_stops(clock):
    result = refinement.solve_physical_refinement(
        _tradeoff(), connectivity=4, initial_waypoints=[4, 1, 0], max_seconds=30,
        completion="greedy", archive=True, archive_history_limit=1)
    assert result["stop_reason"] == "max_archive_history"
    assert result["archive_history_limit_reached"]
    assert len(result["pareto_archive_history"]) == len(result["pareto_archive"]) == 2
    assert result["pareto_archive_history"][0]["source"] == "initial_route"
    assert result["pareto_archive_history"][1]["source"] == "completion"


@pytest.mark.parametrize("bad", [
    {"completion": "beam"}, {"objective": "weighted_sum"}, {"archive": 1},
    {"completion_every": 0}, {"completion_max_calls": 0}, {"archive_limit": 0},
    {"archive_history_limit": 0},
    {"max_expansions": 0}, {"max_expansions": True}, {"max_open": 0},
    {"guide_weight": 0.5}, {"pd_tolerance": -1}, {"pd_tolerance": float("nan")},
    {"pd_floor": 0.7}, {"objective": "J_pd_guard"},
    {"objective": "J_pd_guard", "pd_floor": float("inf")},
])
def test_invalid_policy_options_fail_before_any_search(bad, clock):
    with pytest.raises(ValueError):
        refinement.solve_physical_refinement(
            _tradeoff(), connectivity=4, initial_waypoints=[4, 1, 0], max_seconds=30, **bad)
