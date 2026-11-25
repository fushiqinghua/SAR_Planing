"""Window bounds checked with independent DFS and the frozen path evaluator."""

from dataclasses import replace
import math

import numpy as np
import pytest

from asar_repro.grid import GridGraph
from asar_repro.motion import MatrixMotion, ParticleMotion
from asar_repro.window_bounds import WindowHeuristic, exact_reachable, suffix_coefficients
from audit_window_bounds import (
    MODES, ToyCase, audit_case, enumerate_window_oracle, legal_window_prefixes,
    make_random_case, replay,
)


def static_case(*, q=1.0):
    return ToyCase("matrix", 0, GridGraph(2, 2), (0, 1, 3, 1), 0, 2,
                   np.array([0.0, 0.5, 0.5, 0.0]), q,
                   MatrixMotion.identity(4), "hand_calculated_static")


def dynamic_case():
    grid = GridGraph(2, 2)
    base = np.array([[1, 2, 3, 4], [4, 1, 1, 2],
                     [0, 2, 7, 1], [1, 0, 1, 6]], dtype=float)
    base /= base.sum(axis=1, keepdims=True)
    matrices = [np.roll(np.roll(base, step % 4, axis=0), (2 * step + 1) % 4, axis=1)
                for step in range(5)]
    return ToyCase("matrix", 1, grid, (0, 1, 3, 2, 0, 1), 1, 3,
                   np.array([0.1, 0.2, 0.3, 0.4]),
                   np.array([0.0, 0.25, 0.6, 1.0]),
                   MatrixMotion.time_varying(matrices), "asymmetric_absolute_time")


def particle_case(*, q=None):
    # IDs deliberately differ from array positions. Last four columns retain
    # mass in distinct special bins; observations may only act on grid cells.
    cells = np.array([
        [0, 1, 2, 3, 4, 5, 6, 7],
        [1, 0, 3, 2, 4, 5, 6, 7],
        [2, 3, 0, 1, 4, 5, 6, 7],
        [1, 2, 3, 0, 4, 5, 6, 7],
        [0, 1, 2, 3, 4, 5, 6, 7],
    ])
    motion = ParticleMotion(cells, 4, np.array([91, 17, 64, 3, 58, 2, 101, 11]))
    sensor = np.array([0.0, 0.25, 0.78, 1.0]) if q is None else q
    return ToyCase("particle", 2, GridGraph(2, 2), (0, 1, 3, 2, 0), 1, 3,
                   np.array([0.1, 0.2, 0.15, 0.05, 0.1, 0.1, 0.2, 0.1]),
                   sensor, motion, "hand_particle_special_bins")


def assert_suffix_replays(case):
    coefficients = suffix_coefficients(case.grid, case.reference_path,
                                       q=case.q, motion=case.motion)
    assert coefficients.cost.shape == (case.horizon + 1, case.motion.state_size)
    assert coefficients.survival.shape == coefficients.cost.shape
    assert not coefficients.cost.flags.writeable
    assert not coefficients.survival.flags.writeable
    np.testing.assert_array_equal(coefficients.cost[-1], 0)
    np.testing.assert_array_equal(coefficients.survival[-1], 1)
    assert np.all(coefficients.cost >= 0)
    assert np.all(coefficients.survival >= 0)
    # Point masses also check all source coordinates, avoiding a coincidental
    # cancellation for one particular initial probability vector.
    for initial in [case.p, *np.eye(case.motion.state_size)]:
        score = replay(replace(case, p=initial), case.reference_path)
        for depth in range(case.horizon + 1):
            assert score.g[depth] + coefficients.cost[depth] @ score.beliefs[depth] == pytest.approx(score.J, abs=1e-12, rel=0)
            assert coefficients.survival[depth] @ score.beliefs[depth] == pytest.approx(score.survival[-1], abs=1e-12, rel=0)
    return coefficients


def test_hand_calculated_static_suffix_and_t0():
    case = ToyCase("matrix", 3, GridGraph(1, 3), (0, 1, 2, 1), 0, 2,
                   np.array([0.5, 0.3, 0.2]), 1.0,
                   MatrixMotion.identity(3), "hand_static")
    score = replay(case, case.reference_path)
    np.testing.assert_allclose(score.survival, [1.0, 0.7, 0.5, 0.5])
    assert score.J == pytest.approx(1.7)
    assert score.pd_final == pytest.approx(0.5)
    coefficients = assert_suffix_replays(case)
    np.testing.assert_array_equal(coefficients.cost[0], [3.0, 0.0, 1.0])
    np.testing.assert_array_equal(coefficients.cost[1], [2.0, 1.0, 0.0])
    np.testing.assert_array_equal(coefficients.survival[0], [1.0, 0.0, 0.0])


def test_same_endpoint_and_mass_do_not_determine_suffix_cost():
    case = static_case()
    first = replay(case, (0, 1, 3, 1))
    second = replay(case, (0, 2, 3, 1))
    assert first.g[2] == second.g[2] == 1.0
    assert first.survival[2] == second.survival[2] == 0.5
    assert not np.array_equal(first.beliefs[2], second.beliefs[2])
    assert first.J == 1.5
    assert second.J == 1.0
    assert first.pd_final == 0.5
    assert second.pd_final == 1.0
    tail = suffix_coefficients(case.grid, case.reference_path, q=case.q,
                               motion=case.motion).cost[2]
    assert tail @ first.beliefs[2] == 0.5
    assert tail @ second.beliefs[2] == 0.0
    oracle = enumerate_window_oracle(case)
    assert len(oracle.candidates) == 2
    assert oracle.best_full_path_by_prefix[(0,)] == (0, 2, 3, 1)
    assert oracle.best_full_J_by_prefix[(0,)] == 1.0


@pytest.mark.parametrize("mode", MODES)
def test_terminal_returns_exact_suffix_including_zero_mode(mode):
    case = static_case()
    tail = suffix_coefficients(case.grid, case.reference_path, q=case.q,
                               motion=case.motion).cost[2]
    heuristic = WindowHeuristic(case.grid, end_vertex=3, end_depth=2, q=case.q,
                                motion=case.motion, tail_cost=tail, mode=mode)
    for full_path in ((0, 1, 3, 1), (0, 2, 3, 1)):
        score = replay(case, full_path)
        assert heuristic(3, 2, score.beliefs[2]) == pytest.approx(score.J - score.g[2])


@pytest.mark.parametrize("case", [dynamic_case(), particle_case()])
def test_absolute_time_asymmetric_or_particle_suffix_replay(case):
    assert_suffix_replays(case)
    result = audit_case(case)
    assert result["status"] == "passed"
    assert result["feasible_prefixes"] > 0
    assert result["infeasible_prefixes"] > 0


@pytest.mark.parametrize("case", [static_case(q=0.0), particle_case(q=0.0)])
def test_no_detection_exact_mass_and_suffix_cost(case):
    score = replay(case, case.reference_path)
    np.testing.assert_allclose(score.survival, 1.0, rtol=0, atol=1e-14)
    assert score.J == pytest.approx(case.horizon)
    assert score.pd_final == pytest.approx(0.0, abs=1e-14)
    coefficients = assert_suffix_replays(case)
    for depth in range(case.horizon + 1):
        np.testing.assert_allclose(coefficients.cost[depth], case.horizon - depth)
        np.testing.assert_allclose(coefficients.survival[depth], 1.0)
    for mode in MODES:
        heuristic = WindowHeuristic(case.grid,
                                    end_vertex=case.reference_path[case.window_end],
                                    end_depth=case.window_end, q=0.0,
                                    motion=case.motion,
                                    tail_cost=coefficients.cost[case.window_end], mode=mode)
        root = case.reference_path[:case.window_start + 1]
        prefix_score = replay(case, root)
        expected = 0.0 if mode == "zero" else case.horizon - case.window_start
        assert heuristic(root[-1], case.window_start, prefix_score.final_belief) == pytest.approx(expected)
    assert audit_case(case)["status"] == "passed"


@pytest.mark.parametrize("q", [0.0, 1.0, np.array([0.0, 0.2, 0.78, 1.0])])
def test_particle_special_bins_retain_id_and_undetected_mass(q):
    case = particle_case(q=q)
    ids_before = case.motion.trajectory_ids.copy()
    cells_before = case.motion.cell_ids.copy()
    p_before = case.p.copy()
    coefficients = assert_suffix_replays(case)
    score = replay(case, case.reference_path)
    np.testing.assert_allclose(score.beliefs[:, -4:], np.broadcast_to(case.p[-4:], (case.horizon + 1, 4)))
    for depth in range(case.horizon + 1):
        np.testing.assert_array_equal(coefficients.cost[depth, -4:], case.horizon - depth)
        np.testing.assert_array_equal(coefficients.survival[depth, -4:], 1.0)
    assert score.survival[-1] >= case.p[-4:].sum() - 1e-14
    np.testing.assert_array_equal(case.motion.trajectory_ids, ids_before)
    np.testing.assert_array_equal(case.motion.cell_ids, cells_before)
    np.testing.assert_array_equal(case.p, p_before)
    assert audit_case(case)["status"] == "passed"


def test_full_detection_at_t1_and_no_sensing_at_t0():
    grid = GridGraph(1, 2)
    motion = MatrixMotion.identity(2)
    start_mass = ToyCase("matrix", 4, grid, (0, 1), 0, 1,
                        np.array([1.0, 0.0]), 1.0, motion, "t0_no_sense")
    score = replay(start_mass, start_mass.reference_path)
    assert score.J == 1.0
    assert score.pd_final == 0.0
    target_mass = replace(start_mass, p=np.array([0.0, 1.0]))
    score = replay(target_mass, target_mass.reference_path)
    assert score.J == 0.0
    assert score.pd_final == 1.0
    assert audit_case(start_mass)["status"] == "passed"
    assert audit_case(target_mass)["status"] == "passed"


def test_exact_reachable_zero_parity_and_single_cell():
    grid = GridGraph(2, 3)
    np.testing.assert_array_equal(exact_reachable(grid, 0, 0), [0])
    np.testing.assert_array_equal(exact_reachable(grid, 0, 1), [1, 3])
    np.testing.assert_array_equal(exact_reachable(grid, 0, 2), [0, 2, 4])
    np.testing.assert_array_equal(exact_reachable(grid, 0, 3), [1, 3, 5])
    np.testing.assert_array_equal(exact_reachable(grid, 0, 10), [0, 2, 4])
    single = GridGraph(1, 1)
    np.testing.assert_array_equal(exact_reachable(single, 0, 0), [0])
    assert exact_reachable(single, 0, 1).size == 0
    assert exact_reachable(single, 0, 2).size == 0


def test_zero_horizon_single_cell_has_no_observation():
    case = ToyCase("matrix", 5, GridGraph(1, 1), (0,), 0, 0,
                   np.array([1.0]), 1.0, MatrixMotion.identity(1), "zero_horizon")
    score = replay(case, case.reference_path)
    assert score.J == 0.0
    assert score.pd_final == 0.0
    coefficients = assert_suffix_replays(case)
    np.testing.assert_array_equal(coefficients.cost, [[0.0]])
    np.testing.assert_array_equal(coefficients.survival, [[1.0]])
    assert audit_case(case)["status"] == "passed"


@pytest.mark.parametrize("mode", MODES)
def test_infeasible_endpoint_returns_positive_infinity(mode):
    grid = GridGraph(2, 2)
    h = WindowHeuristic(grid, end_vertex=1, end_depth=2, q=0.78,
                        motion=MatrixMotion.identity(4), tail_cost=np.zeros(4), mode=mode)
    p = np.full(4, 0.25)
    assert h(0, 0, p) == math.inf  # Bipartite parity rules out two steps.
    assert h(0, 2, p) == math.inf  # Wrong endpoint at terminal depth.
    assert h(1, 2, p) == 0.0
    single = WindowHeuristic(GridGraph(1, 1), end_vertex=0, end_depth=1, q=0.0,
                             motion=MatrixMotion.identity(1), tail_cost=[0.0], mode=mode)
    assert single(0, 0, [1.0]) == math.inf


@pytest.mark.parametrize("mode", MODES)
def test_zero_length_window_uses_fixed_suffix_exactly(mode):
    case = static_case()
    case = replace(case, window_start=1, window_end=1)
    oracle = enumerate_window_oracle(case)
    assert tuple(oracle.candidates) == (case.reference_path,)
    coefficients = suffix_coefficients(case.grid, case.reference_path, q=case.q,
                                       motion=case.motion)
    prefix = replay(case, case.reference_path[:2])
    h = WindowHeuristic(case.grid, end_vertex=1, end_depth=1, q=case.q,
                        motion=case.motion, tail_cost=coefficients.cost[1], mode=mode)
    assert h(1, 1, prefix.final_belief) == pytest.approx(replay(case, case.reference_path).J - prefix.J)
    assert audit_case(case)["status"] == "passed"


@pytest.mark.parametrize("mode", ["mass_lb", "stdc_lb", "stdc_endpoint_lb"])
def test_heuristic_instance_caches_isolate_suffix_endpoint_and_time(mode):
    grid = GridGraph(2, 2)
    motion = MatrixMotion.identity(4)
    p = np.full(4, 0.25)
    tail = np.zeros(4)
    first = WindowHeuristic(grid, end_vertex=3, end_depth=2, q=0.0,
                            motion=motion, tail_cost=tail, mode=mode)
    with_tail = WindowHeuristic(grid, end_vertex=3, end_depth=2, q=0.0,
                                motion=motion, tail_cost=np.full(4, 5.0), mode=mode)
    other_time = WindowHeuristic(grid, end_vertex=1, end_depth=1, q=0.0,
                                 motion=motion, tail_cost=np.zeros(4), mode=mode)
    bad_parity = WindowHeuristic(grid, end_vertex=1, end_depth=2, q=0.0,
                                 motion=motion, tail_cost=np.zeros(4), mode=mode)
    assert first(0, 0, p) == 2.0
    assert with_tail(0, 0, p) == 7.0
    assert other_time(0, 0, p) == 1.0
    assert bad_parity(0, 0, p) == math.inf
    assert first(0, 0, p) == 2.0
    tail[:] = 9.0  # Caller mutation must not change an already-created bound.
    assert first(0, 0, p) == 2.0


def test_oracle_enumerates_all_paths_without_depth_vertex_merging():
    case = replace(static_case(), reference_path=(0, 1, 0, 1, 3),
                   window_start=0, window_end=4)
    oracle = enumerate_window_oracle(case)
    # A four-cycle has 2**4 walks from 0; half end at its opposite vertex.
    assert len(oracle.candidates) == 8
    assert (0, 1, 0) in oracle.best_full_J_by_prefix
    assert (0, 2, 0) in oracle.best_full_J_by_prefix
    assert len(list(legal_window_prefixes(case))) == 1 + 2 + 4 + 8 + 16
    assert all(path[0] == 0 and path[4] == 3 for path in oracle.candidates)
    assert audit_case(case)["status"] == "passed"


@pytest.mark.parametrize("kind", ["matrix", "particle"])
@pytest.mark.parametrize("seed", [100, 101, 102, 103])
def test_random_toy_every_legal_prefix_against_independent_window_oracle(kind, seed):
    case = make_random_case(kind, seed)
    result = audit_case(case)
    assert result["status"] == "passed"
    assert result["feasible_prefixes"] > 0
    assert result["candidate_paths"] > 0
    assert result["minimum_endpoint_minus_plain"] >= -1e-10
