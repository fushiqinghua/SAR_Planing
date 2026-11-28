"""Local semantic tests for the strict merge pilot; prepared, not run at delivery.

No timed experiment is performed by collection. Fake clocks make the bounded
search checks deterministic; the small exhaustive oracle is only for toy maps.
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from asar_repro import physical_accel as accel
from asar_repro import physical_merge_solver as merge_solver
from asar_repro import physical_refinement as refinement
from asar_repro import physical_rolling as rolling
from asar_repro import physical_rolling_merge as merging
from asar_repro import physical_rolling_solver as prefix_solver
from asar_repro import physical_search as search
from asar_repro import physical_state_merge as labels
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
    for module in (accel, merge_solver, refinement, rolling, merging,
                   prefix_solver, search, labels):
        monkeypatch.setattr(module, "perf_counter", value)
    return value


def _state(**changes):
    data = dict(_owner=17, vertex=3, time_s=10.0, tick=1, J=1.0,
                weights=np.asarray([0.5, 0.5], dtype=np.float64),
                actual_xy=np.asarray([0.0, 0.0], dtype=np.float64),
                terminal=False, last_edge_partial=False)
    data.update(changes)
    return SimpleNamespace(**data)


@pytest.mark.parametrize("mode", ["shadow", "exact"])
def test_only_equal_future_state_with_no_lower_J_is_mergeable(mode):
    index = labels.ExactStateMerge(mode)
    assert not index.should_discard(_state(), source="root")
    assert index.should_discard(_state()) is (mode == "exact")
    assert index.should_discard(_state(J=1.25)) is (mode == "exact")
    stats = index.statistics()
    assert stats["root_considered"] == 1
    assert stats["nonterminal_children"] == stats["mergeable_children"] == 2
    assert stats["equal_J_duplicates"] == stats["higher_J_duplicates"] == 1
    assert stats["discarded_children"] == (2 if mode == "exact" else 0)


@pytest.mark.parametrize("mode", ["shadow", "exact"])
def test_cheaper_label_reopens_and_only_old_cost_becomes_stale(mode):
    index = labels.ExactStateMerge(mode)
    old, cheaper = _state(J=2.0), _state(J=1.0)
    assert not index.should_discard(old)
    assert not index.should_discard(cheaper)
    assert index.is_stale(old) is (mode == "exact")
    assert not index.is_stale(cheaper)
    stats = index.statistics()
    assert stats["replaced_entries"] == 1
    assert stats["stale_pop_candidates"] == 1
    assert stats["stale_pops"] == (1 if mode == "exact" else 0)


@pytest.mark.parametrize("change", [
    dict(_owner=18), dict(vertex=4), dict(tick=2),
    dict(time_s=np.nextafter(10.0, np.inf)),
    dict(actual_xy=np.asarray([np.nextafter(0.0, 1.0), 0.0])),
    dict(weights=np.asarray([0.4, 0.6])),  # same sum is not the same belief
    dict(weights=np.asarray([np.nextafter(0.5, 1.0), 0.5])),
    dict(weights=np.asarray([0.5, 0.5], dtype=np.float32)),
    dict(weights=np.asarray([[0.5, 0.5]], dtype=np.float64)),
])
def test_distinct_clock_geometry_particle_mass_or_identity_never_merges(change):
    index = labels.ExactStateMerge("exact")
    assert not index.should_discard(_state())
    assert not index.should_discard(_state(**change))
    assert index.statistics()["mergeable_children"] == 0


@pytest.mark.parametrize("limits", [dict(max_entries=1), dict(max_payload_bytes=32)])
def test_full_index_never_prunes_new_keys_and_still_updates_known_keys(limits):
    index = labels.ExactStateMerge("exact", **limits)
    assert not index.should_discard(_state(J=2.0))
    assert not index.should_discard(_state(vertex=4))
    assert not index.should_discard(_state(vertex=4))
    assert not index.should_discard(_state(J=1.0))
    assert index.should_discard(_state(J=2.0))
    stats = index.statistics()
    assert stats["entries"] == stats["entries_peak"] == 1
    assert stats["payload_bytes"] == stats["payload_bytes_peak"] == 32
    assert stats["capacity_skips"] == 2
    assert stats["replaced_entries"] == 1


def test_payload_too_small_disables_storage_without_discarding():
    index = labels.ExactStateMerge("exact", max_payload_bytes=1)
    assert not index.should_discard(_state())
    assert not index.should_discard(_state())
    assert index.statistics()["entries"] == 0
    assert index.statistics()["discarded_children"] == 0
    assert index.statistics()["capacity_skips"] == 2


def test_off_has_no_key_construction_or_state_access():
    index = labels.ExactStateMerge("off")
    assert not index.should_discard(object())
    assert not index.is_stale(object())
    assert index.statistics()["entries"] == 0
    assert index.statistics()["lookup_s"] == 0


@pytest.mark.parametrize("change", [dict(terminal=True), dict(last_edge_partial=True),
                                     dict(time_s=float("nan")), dict(J=float("inf"))])
def test_invalid_or_partial_terminal_state_is_rejected(change):
    with pytest.raises(ValueError):
        labels.ExactStateMerge("exact").should_discard(_state(**change))


@pytest.mark.parametrize("kwargs", [dict(mode="rounded"), dict(max_entries=True),
                                    dict(max_entries=0), dict(max_payload_bytes=1.5)])
def test_invalid_merge_configuration_is_rejected(kwargs):
    with pytest.raises(ValueError):
        labels.ExactStateMerge(**kwargs)


@pytest.mark.parametrize("mode", ["off", "shadow"])
@pytest.mark.parametrize("completion", ["none", "greedy"])
def test_off_and_shadow_keep_original_finite_expansion_trace(mode, completion, clock):
    case = next(item for item in search.diagnostic_cases() if item["id"] == "late_drift")
    problem = search.problem_from_case(case, "heading_square")
    options = dict(connectivity=8, initial_waypoints=case["initial_waypoints"],
                   root_prefix=(problem.start,), max_seconds=30,
                   completion=completion, archive=True, max_expansions=3)
    old = prefix_solver.solve_physical_prefix(problem, **options)
    new = merge_solver.solve_physical_prefix_merge(problem, merge_mode=mode, **options)
    assert old["error"] is None and new["error"] is None
    for key in ("J", "pd_final", "waypoints", "survival", "history", "best", "expanded",
                "generated", "peak_open", "open_count", "stop_reason", "pareto_archive_history"):
        assert old[key] == new[key], key
    assert old["diagnostics"]["pop_trace"] == new["diagnostics"]["pop_trace"]
    assert new["state_merge"]["discarded_children"] == new["state_merge"]["stale_pops"] == 0


def _toy_problem(moving):
    positions = np.full((5, 2, 2), 1000.0)
    searchable = np.zeros((5, 2), dtype=bool)
    if moving:
        positions[:, 0] = [[-5.0, -5.0], [-5.0, -5.0], [5.0, -5.0],
                           [5.0, 5.0], [-5.0, 5.0]]
        searchable[:, 0] = True
    problem = PhysicalProblem(
        rows=2, cols=2, cell_width_m=10.0, speed_m_s=1.0,
        times_s=np.arange(5, dtype=float) * 10.0,
        positions_xy=positions, searchable=searchable,
        initial_weights=np.asarray([0.8, 0.2]), start=0, q=.78,
        footprint="heading_square", trajectory_ids=np.asarray([71, 72]),
    )
    return problem, [0, 1, 0, 1, 0]


def _all_complete_scores(problem, prefix):
    root = problem.initial_state()
    for vertex in prefix[1:]:
        root = problem.advance(root, vertex, connectivity=4)
    pending, complete = [(root, tuple(prefix))], []
    while pending:
        state, path = pending.pop()
        for target in problem.neighbors(state.vertex, connectivity=4):
            child = problem.advance(state, target, connectivity=4)
            route = path + (target,)
            if child.terminal:
                complete.append(problem.replay(route, connectivity=4))
            else:
                pending.append((child, route))
    return complete


@pytest.mark.parametrize("moving", [False, True])
@pytest.mark.parametrize("prefix_length", [1, 2])
def test_tiny_exhaustive_oracle_preserves_best_J_and_original_mass(moving, prefix_length, clock):
    problem, seed = _toy_problem(moving)
    prefix = seed[:prefix_length]
    oracle = _all_complete_scores(problem, prefix)
    optimum = min(score["J"] for score in oracle)
    options = dict(connectivity=4, initial_waypoints=seed, root_prefix=prefix,
                   max_seconds=30, completion="none", archive=True)
    old = prefix_solver.solve_physical_prefix(problem, **options)
    new = merge_solver.solve_physical_prefix_merge(problem, merge_mode="exact", **options)
    assert old["stop_reason"] == new["stop_reason"] == "frontier_exhausted"
    assert old["error"] is None and new["error"] is None
    assert old["J"] == pytest.approx(optimum, abs=1e-12)
    assert new["J"] == pytest.approx(optimum, abs=1e-12)
    assert new["waypoints"][:prefix_length] == prefix
    assert new["best"]["physical_duration_s"] == 40.0
    assert new["best"]["final_weights"][1] == pytest.approx(.2)
    assert any(new["pd_final"] == pytest.approx(score["pd_final"], abs=1e-12)
               for score in oracle if abs(score["J"] - optimum) <= 1e-12)
    if not moving:
        assert new["state_merge"]["discarded_children"] > 0
        assert new["expanded"] < old["expanded"]


def test_index_work_cannot_extend_the_solver_deadline(monkeypatch, clock):
    problem, seed = _toy_problem(False)
    original = labels.ExactStateMerge.should_discard

    def expensive(self, state, **kwargs):
        value = original(self, state, **kwargs)
        clock.advance(2.0)
        return value

    monkeypatch.setattr(labels.ExactStateMerge, "should_discard", expensive)
    result = merge_solver.solve_physical_prefix_merge(
        problem, connectivity=4, initial_waypoints=seed, max_seconds=1.0,
        merge_mode="exact", completion="none")
    assert result["stop_reason"] == "max_seconds"
    assert result["expanded"] == result["generated"] == 0
    assert result["J"] == result["initial_score"]["J"]
    assert result["deadline_overshoot_s"] == pytest.approx(1.0)


def _long_problem():
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
        initial_weights=np.asarray([.8, .2]), start=4, q=.78,
        footprint="heading_square", trajectory_ids=np.asarray([71, 72]))
    return problem, [4, 3, 4, 3, 4, 3, 4, 3, 4, 3, 4]


def _east_suffix(prefix):
    route = list(prefix)
    while len(route) < 11:
        route.append(5 if route[-1] == 4 else 4)
    return route


def _raw(problem, route):
    score = problem.replay(route, connectivity=8)
    return dict(status="completed", error=None, best=score, J=score["J"],
                pd_final=score["pd_final"], waypoints=list(route),
                path=list(route), survival=score["survival"])


@pytest.mark.parametrize("variant,base,mode,count", [
    ("D0", "C0", "shadow", 1), ("C0_M", "C0", "exact", 1),
    ("C1_M", "C1", "exact", 5),
])
def test_variants_keep_base_schedule_and_committed_prefix(monkeypatch, clock, variant, base, mode, count):
    problem, seed = _long_problem()
    calls = []

    def inner(problem, **kwargs):
        calls.append(kwargs)
        clock.advance(1.0)
        route = (kwargs["initial_waypoints"] if len(kwargs["root_prefix"]) == 1
                 else _east_suffix(kwargs["root_prefix"]))
        return _raw(problem, route)

    monkeypatch.setattr(merging, "solve_physical_prefix_merge", inner)
    result = merging.run_physical_rolling_merge(
        problem, method=variant, initial_waypoints=seed,
        merge_max_entries=123, merge_max_payload_bytes=45678)
    assert result["status"] == "completed"
    assert result["variant"] == variant and result["method"] == base
    assert result["merging"]["mode"] == mode
    assert len(calls) == len(result["phases"]) == count
    for call, phase in zip(calls, result["phases"]):
        assert call["merge_mode"] == mode
        assert call["merge_max_entries"] == 123
        assert call["merge_max_payload_bytes"] == 45678
        assert list(call["root_prefix"]) == phase["committed_prefix_waypoints"]
        if phase["accepted"]:
            assert result["waypoints"][:len(call["root_prefix"])] == list(call["root_prefix"])
    assert result["phase_compute_sum_s"] + result["finalization_compute_s"] == pytest.approx(result["active_compute_s"])
    assert result["best"]["physical_duration_s"] == problem.horizon_s
    assert result["best"]["final_weights"][1] == pytest.approx(.2)


def test_late_merge_result_preserves_route_and_reduces_global_budget(monkeypatch, clock):
    problem, seed = _long_problem()
    calls = []

    def inner(problem, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            clock.advance(1.0)
            return _raw(problem, kwargs["initial_waypoints"])
        clock.advance(29.0)
        return _raw(problem, _east_suffix(kwargs["root_prefix"]))

    monkeypatch.setattr(merging, "solve_physical_prefix_merge", inner)
    result = merging.run_physical_rolling_merge(problem, method="C1_M", initial_waypoints=seed)
    assert result["status"] == "completed"
    assert result["waypoints"] == seed
    assert len(calls) == 2
    assert result["phases"][1]["reason"] == "returned_after_deadline"
    assert all(row["reason"] == "shared_budget_exhausted" for row in result["phases"][2:])
    assert not result["accepted_replans"]


def test_formal_wrapper_rejects_unregistered_method_and_expansion_limit(clock):
    problem, seed = _long_problem()
    with pytest.raises(ValueError, match="method"):
        merging.run_physical_rolling_merge(problem, method="C0", initial_waypoints=seed)
    with pytest.raises(ValueError, match="expansion"):
        merging.run_physical_rolling_merge(problem, method="C0_M", initial_waypoints=seed,
                                            solver_options={"max_expansions": 3})
