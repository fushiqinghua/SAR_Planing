"""Toy/Oracle regressions for the H3 bounded-continuation arm."""
from __future__ import annotations

import heapq
from types import SimpleNamespace

import numpy as np
import pytest

from asar_repro import physical_accel as accel
from asar_repro import physical_lazy_prefix as lazy
from asar_repro import physical_refinement as c0
from asar_repro import physical_search as original
import gated_solver as gated


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    clock = Clock()
    for mod in (accel, c0, lazy, original, gated):
        monkeypatch.setattr(mod, "perf_counter", clock, raising=False)
    return clock


def problem(name="late_drift", *, footprint="heading_square"):
    case = next(case for case in original.diagnostic_cases() if case["id"] == name)
    return original.problem_from_case(case, footprint=footprint), case["initial_waypoints"]


def verify_replay(problem, candidate, connectivity):
    route = candidate["waypoints"]
    a = problem.replay(route, connectivity=connectivity)
    b = original.independent_replay(problem, route, connectivity=connectivity)
    for score in (a, b):
        assert score["J"] == pytest.approx(candidate["J"], abs=1e-8)
        assert score["pd_final"] == pytest.approx(candidate["pd_final"], abs=1e-8)
        assert score["survival"] == pytest.approx(candidate["survival"], abs=1e-8)
        assert score["physical_duration_s"] == pytest.approx(problem.horizon_s, abs=1e-8)
        assert score["observation_count"] == problem.tick_count
    return a


@pytest.mark.parametrize("case", original.diagnostic_cases(), ids=lambda c: c["id"])
@pytest.mark.parametrize("connectivity", (4, 8))
def test_global_arm_preserves_frozen_c0_and_matches_exhaustive_oracle(case, connectivity, clock, monkeypatch):
    p = original.problem_from_case(case, footprint="heading_square")
    monkeypatch.setattr(gated, "entry_mode", lambda _survival: "single_global")
    kwargs = dict(connectivity=connectivity, initial_waypoints=case["initial_waypoints"],
                  max_seconds=30, completion="greedy", archive=True)
    source_ids = p.trajectory_ids.copy()
    forcing = p.positions_xy.copy()
    scoring = p.q, p.speed_m_s, p.footprint
    expected = c0.solve_physical_refinement(p, **kwargs)
    got = gated.solve_gated(p, **kwargs)
    oracle = original.enumerate_physical(p, connectivity=connectivity, max_seconds=30)
    assert oracle["enumeration_complete"]
    assert got["error"] is None
    assert not got["global_optimality_certified"]
    assert got["stop_reason"] == expected["stop_reason"] == "frontier_exhausted"
    assert got["J"] == pytest.approx(oracle["J"], abs=1e-8)
    for key in ("J", "pd_final", "initial_score", "waypoints", "survival", "history",
                "expanded", "generated", "peak_open", "open_count"):
        assert got[key] == expected[key], key
    replay = verify_replay(p, got, connectivity)
    assert p.q == scoring[0] and p.speed_m_s == scoring[1] and p.footprint == scoring[2]
    np.testing.assert_array_equal(p.trajectory_ids, source_ids)
    np.testing.assert_array_equal(p.positions_xy, forcing)
    if case["id"] == "special_mass":
        assert replay["final_weights"][2:] == pytest.approx([0.2, 0.2], abs=1e-8)


def test_fixed_global_trace_matches_original_c0(clock, monkeypatch):
    p, init = problem()
    monkeypatch.setattr(gated, "entry_mode", lambda _survival: "single_global")
    kwargs = dict(connectivity=8, initial_waypoints=init, max_seconds=30,
                  max_expansions=8, completion="greedy")
    expected = c0.solve_physical_refinement(p, **kwargs)
    got = gated.solve_gated(p, **kwargs)
    assert got["stop_reason"] == expected["stop_reason"] == "max_expansions"
    assert got["diagnostics"]["pop_trace"] == expected["diagnostics"]["pop_trace"]
    assert got["initial_score"]["waypoints"] == list(init)


def test_coverage_gate_uses_detection_relative_to_same_s30_terminal_mass():
    # Four observation steps, including a 0.4 detection mass in the first quarter.
    early = [1, .6, .4, .3, .2]
    late = [1, 1, .9, .8, .75]
    assert gated.coverage_ratio(early) == pytest.approx(.5)
    assert gated.coverage_ratio(late) == pytest.approx(0)
    assert gated.coverage_ratio([1, 1, 1, 1, 1]) == pytest.approx(0)
    assert gated.entry_mode(early) == "lazy"
    assert gated.entry_mode(late) == "single_global"


@pytest.mark.parametrize(("terminal", "old", "new", "expected"),
                         ((None, 10, 11, True), (0.0, 10, 100, False),
                          (0.1, 10, 100, False), (None, 10, 10, False), (None, 11, 10, False)))
def test_gate_requires_absent_main_terminal_and_growing_open(terminal, old, new, expected):
    assert gated.rescue_eligible(first_terminal=terminal, previous_open=old, current_open=new) is expected


def test_selector_keeps_original_handles_and_tick_diversity():
    specifications = [
        (0., 0, 18, 2),  # Outside the shortlisted tick interval.
        (2., 1, 22, 8),
        (4., 2, 22, 8),  # Same tick and vertex as entry 1; remains in original OPEN.
        (1., 3, 21, 5),
        (3., 4, 23, 6),
        (5., 5, 22, 9),
    ]
    entries = [
        (priority, serial, SimpleNamespace(tick=tick, vertex=vertex, terminal=False), (99, vertex))
        for priority, serial, tick, vertex in specifications
    ]
    heapq.heapify(entries)
    original_handles = tuple(entries)
    chosen = gated.select_prefixes(entries, max_tick=22, per_tick=2, band_radius=1)
    assert {item[1] for item in chosen} == {1, 3, 4, 5}
    assert {item[2].tick for item in chosen} == {21, 22, 23}
    assert len(entries) == len(original_handles)
    assert all(a is b for a, b in zip(entries, original_handles))
    assert all(any(item is actual for actual in original_handles) for item in chosen)


def continuation_fixture(clock):
    p, _ = problem("late_drift")
    cached = accel.CachedPhysicalProblem(p)
    guide = accel._CoarseCellGuide(cached, c0._Budget(clock(), 30))
    initial = cached.initial_state()
    roots = []
    for serial, vertex in enumerate(cached.neighbors(initial.vertex, 8)):
        child = cached.advance(initial, vertex, 8)
        if not child.terminal:
            roots.append((child.J + 1.04 * guide.remaining_cost(child),
                          serial, child, (initial.vertex, vertex)))
    assert roots
    return p, cached, guide, roots


def test_bounded_completion_replays_legal_descendant_with_same_state_and_clock(clock):
    p, cached, guide, roots = continuation_fixture(clock)
    weight_snapshots = [entry[2].weights.copy() for entry in roots]
    selected, info = gated.bounded_completion(
        cached, guide, roots, connectivity=8, guide_weight=1.04, width=8,
        deadline=30, incumbent_j=p.tick_count + 1,
    )
    assert selected is not None
    assert any(tuple(selected["waypoints"][:len(item[3])]) == item[3] for item in roots)
    replay = verify_replay(p, selected, 8)
    assert replay["survival"][0] == pytest.approx(1, abs=1e-8)
    for item, old in zip(roots, weight_snapshots):
        np.testing.assert_array_equal(item[2].weights, old)
        assert not item[2].terminal
    # An already feasible bound cannot be overwritten by a higher objective.
    rejected, _ = gated.bounded_completion(
        cached, guide, roots, connectivity=8, guide_weight=1.04, width=8,
        deadline=30, incumbent_j=-1,
    )
    assert rejected is None


def test_bounded_completion_after_deadline_returns_no_route(clock):
    p, cached, guide, roots = continuation_fixture(clock)
    clock.now = .1
    route, _ = gated.bounded_completion(
        cached, guide, roots, connectivity=8, guide_weight=1.04, width=8,
        deadline=.05, incumbent_j=p.tick_count + 1,
    )
    assert route is None


def test_bounded_completion_checks_deadline_after_frozen_replay(clock, monkeypatch):
    p, cached, guide, roots = continuation_fixture(clock)
    real_replay = accel.CachedPhysicalProblem.replay
    visited = []

    def late_replay(self, route, connectivity=4):
        score = real_replay(self, route, connectivity=connectivity)
        visited.append(score)
        clock.now = 2
        return score

    monkeypatch.setattr(accel.CachedPhysicalProblem, "replay", late_replay)
    route, _ = gated.bounded_completion(
        cached, guide, roots, connectivity=8, guide_weight=1.04, width=8,
        deadline=1, incumbent_j=p.tick_count + 1,
    )
    assert visited, "straddling test must exercise the original scorer"
    assert route is None
