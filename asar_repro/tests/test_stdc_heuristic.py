"""Oracle and regression tests for the STDC research heuristics.

Runs WITHIN the existing asar_repro package after apply_stdc_patch.py.
Never requires historical GRIB/NetCDF or OpenDrift integration.
"""
import numpy as np
import pytest

from asar_repro.grid import GridGraph
from asar_repro.heuristic import Heuristic, BOUND_MODES
from asar_repro.motion import MatrixMotion, ParticleMotion
from asar_repro.objective import score_path
from asar_repro.oracle import enumerate_oracle
from asar_repro.search import search_asar
from asar_repro.stdc_heuristic import STDC_MODES


@pytest.mark.parametrize('mode', STDC_MODES)
def test_terminal_returns_zero(mode):
    grid = GridGraph(3, 3)
    h = Heuristic(grid, budget=4, q=.78, motion=MatrixMotion.identity(9), mode=mode)
    assert h(4, 4, np.ones(9)/9) == 0.
    assert mode in BOUND_MODES


def test_exact_k_parity_and_radius_ablation():
    grid = GridGraph(3, 3)
    exact = Heuristic(grid, budget=4, q=1., motion=MatrixMotion.identity(9), mode='stdc_lb')._stdc
    radius = Heuristic(grid, budget=4, q=1., motion=MatrixMotion.identity(9), mode='stdc_radius_lb')._stdc
    assert set(exact.reachable(4, 1)) == {1, 3, 5, 7}
    assert set(exact.reachable(4, 2)) == {0, 2, 4, 6, 8}
    assert set(radius.reachable(4, 2)) == set(range(9))
    assert 4 not in exact.reachable(4, 1)
    assert 4 in exact.reachable(4, 2)


def test_static_reference_example_and_input_unchanged():
    grid = GridGraph(3, 3)
    p = np.zeros(9)
    p[[0, 5, 7]] = [.2, .3, .5]
    p_before = p.copy()
    motion = MatrixMotion.identity(9)
    args = dict(start=0, budget=4, p=p, q=.78, motion=motion)
    opt = enumerate_oracle(grid, **args).J
    values = {mode: Heuristic(grid, budget=4, q=.78, motion=motion, mode=mode)(0, 0, p)
              for mode in ('mass_lb', *STDC_MODES)}
    np.testing.assert_array_equal(p, p_before)
    assert opt == pytest.approx(3.22, abs=1e-10)
    # Frozen theoretical example, catches time-index and parity mistakes.
    assert values['stdc_lb'] == pytest.approx(2.596, abs=1e-10)
    assert values['stdc_radius_lb'] == pytest.approx(2.1656896, abs=1e-9)
    for mode in STDC_MODES:
        assert 0 <= values[mode] <= opt + 1e-10
    assert values['stdc_lb'] >= values['stdc_radius_lb'] - 1e-10
    assert values['stdc_lb'] >= max(values['mass_lb'], values['reach_lb'],
                                    values['capacity_lb'], values['stepwise_lb']) - 1e-10


def _all_prefixes(grid, start, budget):
    stack = [(start,)]
    while stack:
        path = stack.pop()
        yield path
        if len(path) <= budget:
            stack.extend(path + (u,) for u in grid.neighbors(path[-1]))


def _markov(grid, T, seed, stationary):
    rng = np.random.default_rng(seed)
    p = rng.dirichlet(np.ones(grid.size) * .9)
    q = rng.uniform(.2, 1., size=grid.size)
    if stationary:
        motion = MatrixMotion.identity(grid.size)
    else:
        # Local, stochastic motion with stay-or-step; all rows conserve mass.
        mats = []
        for _ in range(T):
            P = np.zeros((grid.size, grid.size))
            for i in range(grid.size):
                nodes = (i, *grid.neighbors(i))
                P[i, list(nodes)] = rng.dirichlet(np.ones(len(nodes)))
            mats.append(P)
        motion = MatrixMotion.time_varying(mats)
    return p, q, motion


@pytest.mark.parametrize('grid,T,seed,stationary', [
    (GridGraph(2,2), 4, 5, False),
    (GridGraph(2,3), 4, 7, False),
    (GridGraph(3,3), 4, 11, True),
    (GridGraph(3,3), 5, 13, False),
])
def test_all_prefixes_matrix_oracle(grid, T, seed, stationary):
    start = grid.size // 2
    p, q, motion = _markov(grid, T, seed, stationary)
    estimators = {mode: Heuristic(grid, budget=T, q=q, motion=motion, mode=mode)
                  for mode in ('mass_lb', *STDC_MODES)}
    args = dict(start=start, budget=T, p=p, q=q, motion=motion)
    for path in _all_prefixes(grid, start, T):
        d = len(path)-1
        b = score_path(grid, path, **{**args, 'budget': d}).final_belief
        oracle = enumerate_oracle(grid, **args, prefix=path).J - score_path(
            grid, path, **{**args, 'budget': d}).J
        hs = {mode: h(path[-1], d, b) for mode, h in estimators.items()}
        for mode, value in hs.items():
            assert value >= -1e-10, (path, mode, value)
            assert value <= oracle + 1e-10, (path, mode, value, oracle)
        assert hs['stdc_lb'] >= hs['mass_lb'] - 1e-10
        assert hs['stdc_lb'] >= hs['stdc_radius_lb'] - 1e-10
        assert hs['stdc_lb'] >= hs['stepwise_lb'] - 1e-10


def test_particle_id_and_special_bin_oracle():
    grid = GridGraph(2, 3)
    T = 4
    rng = np.random.default_rng(93)
    # Special-bin indices 6,7,8,9 remain unsensed but retain mass.
    cell_ids = rng.integers(0, grid.size + 4, size=(T + 1, 16), dtype=np.int64)
    cell_ids[:, 0] = grid.size  # permanently outside
    w = rng.dirichlet(np.ones(cell_ids.shape[1]))
    motion = ParticleMotion(cell_ids, grid.size, np.arange(w.size))
    q = np.linspace(.1, .95, grid.size)
    args = dict(start=1, budget=T, p=w, q=q, motion=motion)
    estimators = {mode: Heuristic(grid, budget=T, q=q, motion=motion, mode=mode)
                  for mode in ('mass_lb', *STDC_MODES)}
    for path in _all_prefixes(grid, 1, T):
        d = len(path)-1
        prefix = score_path(grid, path, **{**args, 'budget': d})
        exact = enumerate_oracle(grid, **args, prefix=path).J - prefix.J
        for mode, est in estimators.items():
            value = est(path[-1], d, prefix.final_belief)
            assert value <= exact + 1e-10, (path, mode, value, exact)
            assert value >= -1e-10
        stdc = estimators['stdc_lb'](path[-1], d, prefix.final_belief)
        assert stdc >= estimators['mass_lb'](path[-1], d, prefix.final_belief) - 1e-10


@pytest.mark.parametrize('eps', [1.0, 1.04, 1.1])
@pytest.mark.parametrize('motion_type', ['matrix', 'particles'])
def test_certification_with_oracle(eps, motion_type):
    grid, T = GridGraph(2, 3), 4
    rng = np.random.default_rng(12)
    if motion_type == 'matrix':
        p, q, motion = _markov(grid, T, 12, False)
    else:
        cells = rng.integers(0, grid.size + 4, size=(T+1, 12), dtype=np.int64)
        p = rng.dirichlet(np.ones(12))
        q = .78
        motion = ParticleMotion(cells, grid.size, np.arange(12))
    args = dict(start=1, budget=T, p=p, q=q, motion=motion)
    optimum = enumerate_oracle(grid, **args).J
    for mode in ('mass_lb', 'reach_lb', 'capacity_lb', 'stepwise_lb', 'stdc_lb'):
        res = search_asar(grid, **args, heuristic=mode, epsilon=eps)
        assert res.status == 'completed'
        assert res.theory_certified is True
        assert res.J <= eps * optimum + 1e-10
        assert score_path(grid, res.path, **args).J == pytest.approx(res.J, abs=1e-10)


def test_no_faked_certificate_on_budget_stop():
    grid, T = GridGraph(2, 2), 4
    p = [.1, .2, .3, .4]
    args = dict(start=0, budget=T, p=p, q=.78, motion=MatrixMotion.identity(4))
    initial_path = (0, 1, 0, 1, 0)
    result = search_asar(grid, **args, heuristic='stdc_lb', epsilon=1.0,
                         initial_path=initial_path, max_expansions=0)
    assert result.status == 'budget_exceeded'
    assert result.stop_reason == 'max_expansions'
    assert not result.theory_certified
    assert result.path == initial_path
