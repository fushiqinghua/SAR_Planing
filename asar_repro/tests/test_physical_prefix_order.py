"""Check the prefix-only OPEN order against the frozen physical objective."""

from types import SimpleNamespace

import pytest

from asar_repro import physical_accel, physical_prefix_order, physical_refinement, physical_search


def _entry(priority, serial, tick):
    return priority, serial, SimpleNamespace(tick=tick), (serial,)


def test_fourth_expansion_reservation_alternates_early_and_middle():
    frontier = physical_prefix_order._BandedFrontier(20)
    tail = [_entry(i, i, 15) for i in range(7)]
    early = _entry(99, 7, 4)
    mid_first = _entry(98, 8, 5)
    mid_last = _entry(98, 9, 14)

    for item in reversed([*tail, early, mid_first, mid_last]):
        frontier.push(item)

    returned = [frontier.pop(expanded) for expanded in range(10)]

    assert [item[1] for item in returned] == [0, 1, 2, 7, 3, 4, 5, 8, 6, 9]
    assert len(frontier) == 0
    assert not frontier


@pytest.mark.parametrize("expanded", [3, 7])
def test_empty_reserved_band_preserves_global_tie_order(expanded):
    frontier = physical_prefix_order._BandedFrontier(20)
    other_band = 10 if expanded == 3 else 4

    frontier.push(_entry(1.0, 2, 18))
    frontier.push(_entry(1.0, 1, other_band))
    frontier.push(_entry(2.0, 0, other_band))

    assert len(frontier) == 3
    assert frontier.pop(expanded)[1] == 1
    assert frontier.pop(expanded + 1)[1] == 2
    assert frontier.pop(expanded + 2)[1] == 0


def test_pruned_pop_does_not_consume_reserved_expansion():
    frontier = physical_prefix_order._BandedFrontier(20)
    frontier.push(_entry(0.0, 0, 15))
    frontier.push(_entry(1.0, 1, 4))
    frontier.push(_entry(2.0, 2, 4))

    assert frontier.pop(3)[1] == 1
    assert frontier.pop(3)[1] == 2
    assert frontier.pop(4)[1] == 0


@pytest.fixture
def clock(monkeypatch):
    for module in (physical_accel, physical_prefix_order, physical_refinement, physical_search):
        monkeypatch.setattr(module, "perf_counter", lambda: 0.0)


@pytest.mark.parametrize("case", physical_search.diagnostic_cases(), ids=lambda case: case["id"])
@pytest.mark.parametrize("connectivity", [4, 8])
def test_banded_search_exhaustion_matches_independent_oracle(case, connectivity, clock):
    problem = physical_search.problem_from_case(case, footprint="heading_square")
    oracle = physical_search.enumerate_physical(
        problem, connectivity=connectivity, max_seconds=30.0
    )
    candidate = physical_prefix_order.solve_physical_prefix_order(
        problem,
        connectivity=connectivity,
        initial_waypoints=case["initial_waypoints"],
        max_seconds=30.0,
        completion="none",
    )

    assert oracle["enumeration_complete"]
    assert candidate["error"] is None
    assert candidate["stop_reason"] == "frontier_exhausted"
    assert candidate["open_count"] == 0
    assert candidate["J"] == pytest.approx(oracle["J"], abs=1e-8)
    assert candidate["global_optimality_certified"] is False

    route = candidate["waypoints"]
    for replay in (
        problem.replay(route, connectivity=connectivity),
        physical_search.independent_replay(problem, route, connectivity=connectivity),
    ):
        assert replay["J"] == pytest.approx(candidate["J"], abs=1e-8)
        assert replay["pd_final"] == pytest.approx(candidate["pd_final"], abs=1e-8)
        assert replay["survival"] == pytest.approx(candidate["survival"], abs=1e-8)
        assert replay["physical_duration_s"] == pytest.approx(problem.horizon_s, abs=1e-8)
        assert replay["observation_count"] == problem.tick_count
        if case["id"] == "special_mass":
            assert replay["final_weights"][2:] == pytest.approx([0.2, 0.2], abs=1e-8)


def test_combined_frontier_stops_at_original_size_cap(clock):
    case = next(case for case in physical_search.diagnostic_cases() if case["id"] == "repeat_detection")
    problem = physical_search.problem_from_case(case)
    candidate = physical_prefix_order.solve_physical_prefix_order(
        problem,
        connectivity=8,
        initial_waypoints=case["initial_waypoints"],
        max_seconds=30.0,
        max_open=3,
    )

    assert candidate["error"] is None
    assert candidate["stop_reason"] == "max_open"
    assert candidate["open_count"] == candidate["peak_open"] == 3
    assert candidate["waypoints"] == case["initial_waypoints"]
    assert candidate["global_optimality_certified"] is False
