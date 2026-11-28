"""Toy and fixed-work checks for the lazy prefix scheduler."""

import heapq
from types import SimpleNamespace

import pytest

from asar_repro import (
    physical_accel, physical_lazy_prefix, physical_progress_prefix,
    physical_refinement, physical_search,
)


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    value = Clock()
    for module in (
        physical_accel, physical_lazy_prefix, physical_progress_prefix,
        physical_refinement, physical_search,
    ):
        monkeypatch.setattr(module, "perf_counter", value, raising=False)
    return value


def _case_options(case, connectivity=8):
    return dict(
        connectivity=connectivity,
        initial_waypoints=case["initial_waypoints"],
        max_seconds=30.0,
        completion="none",
    )


def _entry(priority, serial, tick):
    return priority, serial, SimpleNamespace(tick=tick), (serial,)


def _assert_valid_solution(problem, solution, connectivity):
    assert solution["error"] is None
    assert not solution["global_optimality_certified"]
    for replay in (
        problem.replay(solution["waypoints"], connectivity=connectivity),
        physical_search.independent_replay(
            problem, solution["waypoints"], connectivity=connectivity
        ),
    ):
        assert replay["J"] == pytest.approx(solution["J"], abs=1e-8)
        assert replay["pd_final"] == pytest.approx(solution["pd_final"], abs=1e-8)
        assert replay["survival"] == pytest.approx(solution["survival"], abs=1e-8)
        assert replay["physical_duration_s"] == pytest.approx(problem.horizon_s, abs=1e-8)
    return replay


@pytest.mark.parametrize("case", physical_search.diagnostic_cases(), ids=lambda case: case["id"])
@pytest.mark.parametrize("connectivity", (4, 8))
def test_lazy_solver_exhaustion_matches_independent_oracle(case, connectivity, clock):
    problem = physical_search.problem_from_case(case, footprint="heading_square")
    options = _case_options(case, connectivity)
    oracle = physical_search.enumerate_physical(problem, connectivity=connectivity, max_seconds=30.0)
    solution = physical_lazy_prefix.solve_physical_lazy_prefix(problem, **options)

    assert oracle["enumeration_complete"]
    assert solution["stop_reason"] == "frontier_exhausted"
    assert solution["J"] == pytest.approx(oracle["J"], abs=1e-8)
    replay = _assert_valid_solution(problem, solution, connectivity)
    assert replay["observation_count"] == problem.tick_count
    if case["id"] == "special_mass":
        assert replay["final_weights"][2:] == pytest.approx([0.2, 0.2], abs=1e-8)


def test_native_open_limit_before_activation(clock):
    case = next(item for item in physical_search.diagnostic_cases()
                if item["id"] == "repeat_detection")
    problem = physical_search.problem_from_case(case)
    solution = physical_lazy_prefix.solve_physical_lazy_prefix(
        problem, max_open=3, **_case_options(case)
    )

    assert solution["stop_reason"] == "max_open"
    assert solution["open_count"] == solution["peak_open"] == 3
    assert solution["waypoints"] == case["initial_waypoints"]
    _assert_valid_solution(problem, solution, 8)


@pytest.mark.parametrize("heaps", (1, 3))
@pytest.mark.parametrize("statistics", (False, True))
@pytest.mark.parametrize("trace_pops", (False, True))
def test_factorial_preserves_native_fixed_work(heaps, statistics, trace_pops, clock):
    case = next(item for item in physical_search.diagnostic_cases()
                if item["id"] == "late_drift")
    problem = physical_search.problem_from_case(case)
    options = dict(_case_options(case), max_expansions=12, completion="greedy")
    reference = physical_refinement.solve_physical_refinement(problem, **options)
    ablation = physical_lazy_prefix.solve_physical_lazy_prefix(
        problem, diagnostic_heaps=heaps, diagnostic_statistics=statistics,
        trace_pops=trace_pops, **options
    )

    assert reference["stop_reason"] == "max_expansions"
    assert ablation["error"] is None
    for key in ("stop_reason", "expanded", "generated", "peak_open", "open_count",
                "history", "waypoints", "J", "pd_final", "survival"):
        assert ablation[key] == reference[key]
    assert ablation["diagnostics"]["histograms"] == reference["diagnostics"]["histograms"]
    assert reference["diagnostics"]["pop_trace"]
    assert ablation["diagnostics"]["pop_trace"] == (
        reference["diagnostics"]["pop_trace"] if trace_pops else []
    )


def test_first_activation_partition_keeps_exact_keys_items_and_global_order(clock):
    entries = [
        _entry(2.0, 0, 3), _entry(2.0, 1, 5), _entry(2.0, 2, 15),
        _entry(1.0, 3, 19), _entry(0.0, 4, 14), _entry(3.0, 5, 4),
    ]
    heap = list(reversed(entries))
    heapq.heapify(heap)
    budget = physical_refinement._Budget(clock.now, 30.0)
    frontier = physical_lazy_prefix._LazyFrontier.from_single_heap(20, heap, budget)

    assert len(frontier) == len(entries)
    assert frontier.statistics()["final_band_sizes"] == [2, 2, 2]
    removed = [
        frontier.pop(n, allow_reserved=False)
        for n in range(len(entries))
    ]
    expected = sorted(entries)
    assert [item[:2] for item in removed] == [item[:2] for item in expected]
    assert all(actual is wanted for actual, wanted in zip(removed, expected))
    assert not frontier


def test_interrupted_partition_leaves_original_heap_intact():
    class DeadlineOnSecondCheck:
        def __init__(self):
            self.checks = 0

        def check(self):
            self.checks += 1
            if self.checks == 2:
                raise physical_refinement._Deadline

    entries = [_entry(i % 3, i, i % 19) for i in range(600)]
    heapq.heapify(entries)
    original = tuple(entries)

    with pytest.raises(physical_refinement._Deadline):
        physical_lazy_prefix._LazyFrontier.from_single_heap(
            20, entries, DeadlineOnSecondCheck()
        )

    assert tuple(entries) == original
    assert all(item is before for item, before in zip(entries, original))


def test_never_qualified_run_does_not_split_the_native_heap(monkeypatch, clock):
    def unexpected_split(*args, **kwargs):
        pytest.fail("The native OPEN was split before a valid activation")

    monkeypatch.setattr(physical_lazy_prefix._LazyFrontier, "from_single_heap", unexpected_split)
    case = next(item for item in physical_search.diagnostic_cases()
                if item["id"] == "late_drift")
    problem = physical_search.problem_from_case(case)
    solved = physical_lazy_prefix.solve_physical_lazy_prefix(
        problem, max_expansions=12, trace_pops=True, **_case_options(case)
    )
    reference = physical_refinement.solve_physical_refinement(
        problem, max_expansions=12, **_case_options(case)
    )

    assert solved["error"] is None
    assert solved["diagnostics"]["pop_trace"] == reference["diagnostics"]["pop_trace"]


def test_exact_window_entry_exit_and_pause_hysteresis():
    gate = physical_lazy_prefix._LazyProgressController(50, 30.0)
    for tick in [15] * 102 + [49] * 409:
        gate.observe_expansion(tick)
    gate.register_search_improvement(1.0)
    assert not gate.should_reserve(2.5, 1.0)
    gate.observe_expansion(15)
    assert gate.tail_count == 409
    assert not gate.should_reserve(2.999, 1.0)
    assert not gate.should_reserve(3.0, 1.0)

    gate.observe_expansion(49)
    assert gate.tail_count == 410
    assert gate.should_reserve(3.001, 1.0)
    assert gate.should_reserve(4.0, 3.0)
    assert not gate.should_reserve(4.001, 4.0)
    assert not gate.should_reserve(5.999, 4.0)
    assert gate.should_reserve(6.0, 4.0)

    for _ in range(229):
        gate.observe_expansion(15)
    assert gate.tail_count == 282
    assert gate.should_reserve(7.0, 4.0)
    gate.observe_expansion(15)
    assert gate.tail_count == 281
    assert not gate.should_reserve(7.1, 4.0)
    evidence = gate.statistics()
    assert [e["event"] for e in evidence["events"]] == ["on", "off", "on", "off"]


def test_cutoff_is_inclusive_and_expiry_permanent():
    eligible = physical_lazy_prefix._LazyProgressController(50, 30.0)
    eligible.expire_if_unqualified(6.0)
    eligible.register_search_improvement(6.0)
    assert eligible.eligible
    assert not eligible.expired

    expired = physical_lazy_prefix._LazyProgressController(50, 30.0)
    for _ in range(512):
        expired.observe_expansion(49)
    expired.expire_if_unqualified(6.001)
    tail_count = expired.tail_count
    for _ in range(512):
        expired.observe_expansion(20)
    expired.register_search_improvement(6.1)
    assert expired.expired
    assert not expired.eligible
    assert expired.tail_count == tail_count
    assert not expired.should_reserve(20.0, 6.1)
    assert expired.statistics()["activations"] == 0


def test_migration_cost_is_charged_before_next_pop(monkeypatch, clock):
    calls = []
    original_controller = physical_lazy_prefix._LazyProgressController
    original_migration = physical_lazy_prefix._LazyFrontier.from_single_heap

    class TriggeredController(original_controller):
        def __init__(self, tick_count, total_seconds):
            super().__init__(tick_count, total_seconds)
            self.register_search_improvement(0.0)

        def should_reserve(self, elapsed, best_elapsed):
            return True

    def expensive_migration(tick_count, heap, budget):
        calls.append(len(heap))
        migrated = original_migration(tick_count, heap, budget)
        clock.now = 30.25
        return migrated

    monkeypatch.setattr(physical_lazy_prefix, "_LazyProgressController", TriggeredController)
    monkeypatch.setattr(physical_lazy_prefix._LazyFrontier, "from_single_heap", expensive_migration)
    case = next(item for item in physical_search.diagnostic_cases()
                if item["id"] == "late_drift")
    problem = physical_search.problem_from_case(case)
    solved = physical_lazy_prefix.solve_physical_lazy_prefix(problem, **_case_options(case))

    assert calls == [1]
    assert solved["stop_reason"] == "max_seconds"
    assert solved["expanded"] == solved["generated"] == 0
    assert solved["open_count"] == 1
    assert solved["deadline_overshoot_s"] == pytest.approx(0.25)
    assert solved["waypoints"] == case["initial_waypoints"]
    _assert_valid_solution(problem, solved, 8)
