"""Numerical equivalence to the pre-optimization STDC recurrence.

The reference below is independent of the optimized geometry cache and is
frozen from commit 4a01dee. Mathematical admissibility is separately tested
against the DFS Oracle in test_stdc_heuristic.py and the audit scripts.
"""
import numpy as np
import pytest

from asar_repro.belief import sensor_probabilities
from asar_repro.grid import GridGraph
from asar_repro.motion import MatrixMotion, ParticleMotion
from asar_repro.objective import score_path
from asar_repro.stdc_heuristic import STDCHeuristic, STDC_MODES


def legacy_value(grid, budget, q, motion, mode, vertex, depth, belief):
    """Original arithmetic, without calling any optimized STDC method."""
    if depth == budget:
        return 0.0
    q = sensor_probabilities(q, grid.size)
    distances = grid.distances_from(vertex)
    relaxed = belief.copy()
    no_search = belief.copy()
    capacity = coupled = float(np.sum(belief))
    total = 0.0
    for k in range(1, budget - depth + 1):
        t = depth + k
        mask = distances <= k
        if mode != 'stdc_radius_lb':
            mask &= ((k - distances) % 2 == 0)
        reach = np.flatnonzero(mask)
        if not reach.size:
            raise ValueError('no legal continuation')
        qr = q[reach]
        qmax = float(qr.max())
        if isinstance(motion, ParticleMotion):
            if mode != 'capacity_lb':
                factors = np.ones(motion.bin_count, dtype=np.float64)
                factors[reach] = 1.0 - qr
                relaxed *= factors[motion.cell_ids[t]]
                a = float(relaxed.sum())
            else:
                a = 0.0
            if mode != 'reach_lb':
                mu = motion.cell_mass(no_search, t)
                u = float(np.max(qr * mu[reach]))
            else:
                u = 0.0
        else:
            if mode != 'capacity_lb':
                relaxed = motion.propagate(relaxed, step=t)
                relaxed[reach] *= (1.0 - qr)
                a = float(relaxed.sum())
            else:
                a = 0.0
            if mode != 'reach_lb':
                no_search = motion.propagate(no_search, step=t)
                mu = motion.cell_mass(no_search, t)
                u = float(np.max(qr * mu[reach]))
            else:
                u = 0.0
        if mode == 'reach_lb':
            ell = a
        else:
            capacity = max((1.0 - qmax) * capacity, capacity - u)
            if mode == 'capacity_lb':
                ell = capacity
            elif mode == 'stepwise_lb':
                ell = max(a, capacity)
            else:
                coupled = max(a, (1.0 - qmax) * coupled, coupled - u)
                ell = coupled
        total += ell
    return float(total)


def case(kind, q_kind):
    grid, T = GridGraph(2, 3), 6
    rng = np.random.default_rng(4517)
    q = rng.uniform(.05, .95, grid.size) if q_kind == 'varying' else np.array([0., 1., .78, 0., 1., .35])
    if kind == 'particles':
        cells = rng.integers(0, grid.size + 4, size=(T + 1, 19))
        cells[:, :4] = np.arange(grid.size, grid.size + 4)
        motion = ParticleMotion(cells, grid.size, np.arange(19) + 213)
    elif kind == 'dynamic_matrix':
        motion = MatrixMotion.time_varying([
            rng.dirichlet(np.ones(grid.size), size=grid.size) for _ in range(T)])
    else:
        motion = MatrixMotion.identity(grid.size)
    p = rng.dirichlet(np.ones(motion.state_size))
    return rng, grid, T, p, q, motion


@pytest.mark.parametrize('mode', STDC_MODES)
@pytest.mark.parametrize('kind', ['static_matrix', 'dynamic_matrix', 'particles'])
@pytest.mark.parametrize('q_kind', ['varying', 'edge_probabilities'])
def test_cached_geometry_is_bitwise_equivalent_for_path_dependent_prefixes(mode, kind, q_kind):
    rng, grid, T, p, q, motion = case(kind, q_kind)
    estimator = STDCHeuristic(grid, budget=T, q=q, motion=motion, mode=mode)
    original_p, original_q = p.copy(), q.copy()
    for _ in range(8):
        path = [int(rng.integers(grid.size))]
        for _ in range(T):
            path.append(int(rng.choice(grid.neighbors(path[-1]))))
        score = score_path(grid, path, start=path[0], budget=T, p=p, q=q,
                           motion=motion, record_beliefs=True)
        for d, v in enumerate(path):
            b = score.beliefs[d]
            before = b.copy()
            expected = legacy_value(grid, T, q, motion, mode, v, d, b)
            assert estimator(v, d, b) == expected
            # Same geometry with a distinct belief must be recomputed.
            assert estimator(v, d, .5*b) == legacy_value(grid, T, q, motion, mode, v, d, .5*b)
            np.testing.assert_array_equal(b, before)
    np.testing.assert_array_equal(p, original_p)
    np.testing.assert_array_equal(q, original_q)
    info = estimator.geometry_cache_info()
    assert info['hits'] > 0
    assert info['array_bytes'] <= info['array_byte_limit']


@pytest.mark.parametrize('mode', STDC_MODES)
def test_saturated_reachability_reuses_geometry_without_losing_parity(mode):
    grid = GridGraph(2, 3)
    estimator = STDCHeuristic(grid, budget=100, q=.78,
                             motion=MatrixMotion.identity(grid.size), mode=mode)
    distances = grid.distances_from(0)
    for k in (1, 2, 3, 4, 5, 50, 51, 100):
        mask = distances <= k
        if mode != 'stdc_radius_lb':
            mask &= (k - distances) % 2 == 0
        np.testing.assert_array_equal(estimator.reachable(0, k), np.flatnonzero(mask))
    assert len(estimator._reach) <= 4
    for invalid_vertex in (True, -1, grid.size, 1.2):
        with pytest.raises(ValueError):
            estimator.reachable(invalid_vertex, 2)
    for invalid_step in (True, 0, -1, 1.2):
        with pytest.raises(ValueError):
            estimator.reachable(0, invalid_step)


def test_geometry_cache_eviction_preserves_particle_values_and_special_mass():
    _, grid, T, p, q, motion = case('particles', 'edge_probabilities')
    estimator = STDCHeuristic(grid, budget=T, q=q, motion=motion)
    estimator._geometry_limit = 120  # force eviction and oversized uncached entries
    for v in range(grid.size):
        for d in (0, 1, 4):
            assert estimator(v, d, p) == legacy_value(grid, T, q, motion, 'stdc_lb', v, d, p)
            assert estimator.geometry_cache_info()['array_bytes'] <= 120
    outside = np.zeros_like(p)
    outside[:4] = .25
    assert estimator(0, 0, outside) == T
    assert estimator(0, T, p) == 0.0


def test_particle_factor_cache_is_read_only_and_never_stores_beliefs():
    _, grid, T, p, q, motion = case('particles', 'varying')
    estimator = STDCHeuristic(grid, budget=T, q=q, motion=motion)
    estimator(0, 0, p)
    for (reach, qr, miss, _, factors), _ in estimator._geometry.values():
        for array in (reach, qr, miss, factors):
            assert not array.flags.writeable
            assert not np.shares_memory(array, p)
        np.testing.assert_array_equal(factors[grid.size:], np.ones(4))
