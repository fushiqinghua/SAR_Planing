"""Exact-state reuse is optional and must preserve the discrete guarantees."""
from dataclasses import asdict

import numpy as np
import pytest

from asar_repro.grid import GridGraph
from asar_repro.heuristic import Heuristic
from asar_repro.motion import MatrixMotion, ParticleMotion
from asar_repro.objective import score_path
from asar_repro.oracle import enumerate_oracle
from asar_repro.search import search_asar
import asar_repro.search as search_module


def scenario(kind, budget=4):
    grid = GridGraph(2, 3)
    rng = np.random.default_rng(615)
    q = np.array([0.1, 0.5, 0.8, 0.4, 0.7, 0.9])
    if kind == 'particles':
        cells = rng.integers(0, grid.size + 4, size=(budget + 1, 12))
        cells[:, 0] = grid.size
        p = rng.dirichlet(np.ones(12))
        motion = ParticleMotion(cells, grid.size, np.arange(12))
    else:
        p = rng.dirichlet(np.ones(grid.size))
        motion = (MatrixMotion.identity(grid.size) if kind == 'static' else
                  MatrixMotion.time_varying(rng.dirichlet(np.ones(grid.size), size=(budget, grid.size))))
    return grid, dict(start=1, budget=budget, p=p, q=q, motion=motion)


@pytest.mark.parametrize('kind', ['static', 'dynamic', 'particles'])
@pytest.mark.parametrize('mode', ['zero', 'mass_lb', 'stdc_lb', 'paper_greedy'])
def test_h_cache_preserves_complete_reference_result_and_trace(kind, mode):
    grid, cfg = scenario(kind)
    before, after, stats = [], [], {}
    reference = search_asar(grid, **cfg, heuristic=mode, epsilon=1.1, trace=before.append)
    cached = search_asar(grid, **cfg, heuristic=mode, epsilon=1.1, trace=after.append,
                         heuristic_cache_size=8, reuse_stats=stats)
    assert asdict(cached) == asdict(reference)
    assert after == before
    assert stats['heuristic_cache_peak_entries'] <= 8
    assert stats['heuristic_cache_peak_key_bytes'] <= 8 * cfg['motion'].state_size * 8
    assert stats['heuristic_requests'] == stats['heuristic_evaluations'] + stats['heuristic_cache_hits']


@pytest.mark.parametrize('kind', ['static', 'dynamic', 'particles'])
@pytest.mark.parametrize('epsilon', [1.0, 1.1])
@pytest.mark.parametrize('prune', [False, True])
def test_exact_dominance_with_oracle(kind, epsilon, prune):
    grid, cfg = scenario(kind)
    optimum = enumerate_oracle(grid, **cfg).J
    stats = {}
    result = search_asar(grid, **cfg, heuristic='stdc_lb', epsilon=epsilon, prune=prune,
                         exact_dominance=True, heuristic_cache_size=16, reuse_stats=stats)
    replay = score_path(grid, result.path, **cfg)
    assert result.status == 'completed' and result.theory_certified
    assert optimum - 1e-10 <= result.J <= epsilon * optimum + 1e-10
    assert result.J == pytest.approx(replay.J, abs=1e-10)
    assert stats['state_records'] == stats['state_records_peak']


def test_same_depth_vertex_with_different_belief_is_not_merged():
    # The lower-g prefix at (depth=4, vertex=6) loses after the next observation.
    # This regression detects the invalid (depth, vertex)-only dominance rule.
    grid = GridGraph(3, 3)
    cfg = dict(start=0, budget=5, p=np.array([8, 2, 1, 1, 0, 0, 8, 8, 1]) / 29,
               q=1, motion=MatrixMotion.identity(9))
    optimum = enumerate_oracle(grid, **cfg)
    result = search_asar(grid, **cfg, exact_dominance=True, heuristic_cache_size=64)
    assert result.path == optimum.path == (0, 1, 0, 3, 6, 7)
    assert result.J == pytest.approx(76 / 29, abs=1e-12)


def test_no_detection_reuses_states_and_preserves_path_and_cost():
    grid = GridGraph(2, 2)
    cfg = dict(start=0, budget=7, p=[1, 0, 0, 0], q=0, motion=MatrixMotion.identity(4))
    reference = search_asar(grid, **cfg, prune=False)
    stats = {}
    result = search_asar(grid, **cfg, prune=False, exact_dominance=True, reuse_stats=stats)
    assert result.J == reference.J == 7
    assert result.path == reference.path
    assert result.expanded < reference.expanded
    assert stats['dominance_pruned'] > 0
    assert stats['dominance_key_bytes'] == stats['state_records'] * 4 * 8


def test_cache_hits_and_eviction_are_bounded_without_state_pruning():
    grid = GridGraph(2, 2)
    cfg = dict(start=0, budget=6, p=[1, 0, 0, 0], q=0, motion=MatrixMotion.identity(4))
    reference = search_asar(grid, **cfg, prune=False)
    stats = {}
    cached = search_asar(grid, **cfg, prune=False, heuristic_cache_size=8, reuse_stats=stats)
    assert asdict(cached) == asdict(reference)
    assert stats['heuristic_cache_hits'] > 0
    assert stats['heuristic_cache_evictions'] > 0
    assert stats['heuristic_cache_peak_entries'] == 8
    assert stats['state_records'] == stats['dominance_pruned'] == 0


def test_lower_g_reopens_state_and_stale_copies_are_skipped(monkeypatch):
    # Subsampling a valid mass bound produces an admissible but inconsistent h.
    # Reopen handling must not depend on heuristic consistency or FIFO luck.
    grid = GridGraph(2, 3)
    mask = np.random.default_rng(0).integers(0, 2, size=(8, grid.size))
    cfg = dict(start=1, budget=7, p=np.random.default_rng(0).dirichlet(np.ones(grid.size)),
               q=0.5, motion=MatrixMotion.identity(grid.size))
    def factory(*args, **kwargs):
        estimate = Heuristic(*args, **{**kwargs, 'mode': 'mass_lb'})
        return lambda v, d, b: float(mask[d, v]) * estimate(v, d, b)
    monkeypatch.setattr(search_module, 'Heuristic', factory)
    stats, events = {}, []
    result = search_asar(grid, **cfg, heuristic='mass_lb', prune=False,
                         exact_dominance=True, heuristic_cache_size=64,
                         reuse_stats=stats, trace=events.append)
    assert result.J == pytest.approx(enumerate_oracle(grid, **cfg).J, abs=1e-10)
    assert stats['improved_state_records'] > 0
    assert stats['stale_pops'] > 0
    assert stats['stale_pops'] == sum(e['event'] == 'stale' for e in events)
    assert result.expanded == sum(e['event'] == 'pop' and e['depth'] < cfg['budget'] for e in events)


@pytest.mark.parametrize('limit,reason', [
    ({'max_expansions': 0}, 'max_expansions'),
    ({'max_open': 0}, 'max_open'),
    ({'max_seconds': 0}, 'max_seconds'),
])
def test_reuse_budget_stop_preserves_initial_incumbent_and_is_uncertified(limit, reason):
    grid, cfg = scenario('particles')
    path = (1, 0, 1, 0, 1)
    stats = {}
    result = search_asar(grid, **cfg, heuristic='stdc_lb', initial_path=path,
                         exact_dominance=True, heuristic_cache_size=8,
                         reuse_stats=stats, **limit)
    assert result.status == 'budget_exceeded' and result.stop_reason == reason
    assert not result.theory_certified
    assert result.incumbent_source == 'initial_path' and result.path == path
    assert result.J == pytest.approx(score_path(grid, path, **cfg).J, abs=1e-12)


def test_paper_reproduction_remains_uncertified_with_reuse():
    grid, cfg = scenario('dynamic')
    result = search_asar(grid, **cfg, heuristic='paper_greedy',
                         exact_dominance=True, heuristic_cache_size=8)
    assert result.status == 'completed' and not result.theory_certified


@pytest.mark.parametrize('kwargs', [
    {'exact_dominance': 1}, {'heuristic_cache_size': -1},
    {'heuristic_cache_size': 1.5}, {'heuristic_cache_size': True}, {'reuse_stats': []},
])
def test_invalid_reuse_options(kwargs):
    grid, cfg = scenario('static')
    with pytest.raises(ValueError):
        search_asar(grid, **cfg, **kwargs)
