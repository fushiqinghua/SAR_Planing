"""Dense DP equivalence and independent complete-path Oracle checks."""
from math import inf

import numpy as np
import pytest

import asar_repro.compact_particle_dp as compact_module
from asar_repro.compact_particle_dp import CompactParticleDP
from asar_repro.grid import GridGraph
from asar_repro.motion import MatrixMotion, ParticleMotion
from asar_repro.objective import score_path
from asar_repro.oracle import enumerate_oracle
from asar_repro.particle_dp import ParticleDP

ATOL = 1e-10


def fixture(seed=17, shape=(2, 2), T=4):
    rng = np.random.default_rng(seed)
    grid = GridGraph(*shape)
    cells = rng.integers(0, grid.size+4, (T+1, 8))
    cells[2:, 1] = cells[2:, 0]  # Past columns may differ; future coefficients match.
    cells[:, -2:] = grid.size + np.arange(2)
    motion = ParticleMotion(cells, grid.size, rng.permutation(np.arange(8)*13+9))
    p = rng.dirichlet(np.ones(8))
    return grid, motion, p


def prefixes(grid, start, T):
    pending = [(start,)]
    while pending:
        route = pending.pop()
        yield route
        if len(route) <= T:
            pending.extend(route+(v,) for v in grid.neighbors(route[-1]))


@pytest.mark.parametrize("seed", [7, 41])
@pytest.mark.parametrize("shape", [(1, 2), (2, 2), (2, 3)])
@pytest.mark.parametrize("q_kind", ["zero", "one", "vector"])
def test_all_legal_prefixes_equal_dense_and_bound_independent_oracle(seed, shape, q_kind):
    grid, motion, p = fixture(seed, shape)
    q = {"zero": 0., "one": 1., "vector": np.linspace(0., 1., grid.size)}[q_kind]
    cfg = dict(start=grid.size//2, budget=4, p=p, q=q, motion=motion)
    compact = CompactParticleDP(grid, start=cfg["start"], budget=4, q=q, motion=motion)
    dense = ParticleDP(grid, budget=4, q=q, motion=motion)
    assert compact.ready
    assert compact.build_info["allocated_peak_managed_bytes"] == compact.build_info["required_peak_managed_bytes"]
    assert compact.build_info["cost_table_bytes"] < dense.build_info["cost_table_bytes"]
    assert not compact.cost_table.flags.writeable
    assert not compact.suffix_group_table.flags.writeable
    assert not compact.vertex_row_table.flags.writeable
    for route in prefixes(grid, cfg["start"], 4):
        depth = len(route)-1
        scored = score_path(grid, route, **dict(cfg, budget=depth))
        b = scored.final_belief
        before = b.copy()
        expected = dense(route[-1], depth, b)
        actual = compact(route[-1], depth, b)
        assert actual == pytest.approx(expected, abs=ATOL, rel=0)
        oracle = enumerate_oracle(grid, **cfg, prefix=route)
        assert actual <= oracle.J-scored.J+ATOL
        assert np.array_equal(before, b)
    assert compact.validate_compatibility(grid, start=cfg["start"], budget=4, q=q, motion=motion)


def test_arbitrary_beliefs_and_nonmonotone_depth_queries_do_not_reuse_state_values():
    grid, motion, p = fixture()
    compact = CompactParticleDP(grid, start=0, budget=4, q=.78, motion=motion)
    dense = ParticleDP(grid, budget=4, q=.78, motion=motion)
    rng = np.random.default_rng(829)
    routes = list(prefixes(grid, 0, 4))
    for index in rng.permutation(len(routes)):
        route = routes[index]
        for _ in range(3):
            b = rng.dirichlet(np.ones(8)) * rng.random()
            assert compact(route[-1], len(route)-1, b) == pytest.approx(
                dense(route[-1], len(route)-1, b), abs=ATOL, rel=0)
    assert compact(0, 0, np.zeros(8)) == 0
    assert compact(0, 0, p) > 0


def test_suffix_groups_ignore_past_only_and_keep_special_bin_labels():
    grid = GridGraph(1, 2)
    motion = ParticleMotion([[0, 1, 2, 3], [0, 1, 2, 3], [1, 1, 2, 3], [0, 0, 2, 3]], 2, [7, 3, 20, 42])
    compact = CompactParticleDP(grid, start=0, budget=3, q=1., motion=motion)
    groups = compact.suffix_group_table
    assert groups[0, 0] != groups[0, 1]
    assert groups[1, 0] == groups[1, 1]
    assert groups[1, 2] != groups[1, 3]
    assert compact(1, 1, [.1, .2, .3, .4]) == pytest.approx(2.)
    dense = ParticleDP(grid, budget=3, q=1., motion=motion)
    for b in ([.1, .2, .3, .4], [.25, .05, .0, .2], [0, 0, .2, .3]):
        assert compact(0, 2, b) == dense(0, 2, b)
    assert np.array_equal(groups[3], np.zeros(4))


def test_absolute_time_and_t0_not_observed_hand_calculation():
    grid = GridGraph(1, 3)
    motion = ParticleMotion([[0], [1], [2], [0]], 3, [63])
    q = np.array([.1, .7, .8])
    compact = CompactParticleDP(grid, start=0, budget=3, q=q, motion=motion)
    assert compact(0, 0, [1.]) == pytest.approx(.42, abs=ATOL, rel=0)
    assert compact(1, 1, [.3]) == pytest.approx(.12, abs=ATOL, rel=0)
    assert compact(2, 2, [.06]) == pytest.approx(.06, abs=ATOL, rel=0)
    assert compact(1, 3, [.06]) == 0


def test_singleton_impossibility_and_zero_horizon():
    grid = GridGraph(1, 1)
    motion = ParticleMotion([[0, 1], [0, 1], [0, 1]], 1, [12, 37])
    compact = CompactParticleDP(grid, start=0, budget=2, q=1., motion=motion)
    with np.errstate(invalid="raise"):
        assert compact(0, 0, [0, 0]) == inf
        assert compact(0, 0, [1, 0]) == inf
    terminal = CompactParticleDP(grid, start=0, budget=0, q=1., motion=motion)
    assert terminal(0, 0, [.4, .2]) == 0
    assert terminal.build_info["cost_table_bytes"] == 0
    assert terminal.build_info["completed_time_layers"] == 0


def test_memory_exact_boundary_and_unpublished_partial_table():
    grid, motion, _ = fixture()
    full = CompactParticleDP(grid, start=0, budget=4, q=.78, motion=motion)
    required = full.build_info["required_peak_managed_bytes"]
    exact = CompactParticleDP(grid, start=0, budget=4, q=.78, motion=motion, max_memory_bytes=required)
    assert exact.ready
    assert exact.build_info["allocated_peak_managed_bytes"] <= required
    low = CompactParticleDP(grid, start=0, budget=4, q=.78, motion=motion, max_memory_bytes=required-1)
    assert not low.ready and low.stop_reason == "max_memory_bytes"
    assert low.cost_table is None and low.vertex_row_table is None and low.suffix_group_table is None
    assert low.build_info["published_table_bytes"] == 0
    assert low.build_info["allocated_peak_managed_bytes"] <= required-1
    with pytest.raises(RuntimeError, match="partial tables"):
        low(0, 0, np.zeros(8))
    tiny = CompactParticleDP(grid, start=0, budget=4, q=.78, motion=motion, max_memory_bytes=0)
    assert tiny.build_info["allocated_peak_managed_bytes"] == 0


@pytest.mark.parametrize("expire_at", [30, 62])
def test_expired_and_interrupted_builds_never_publish(monkeypatch, expire_at):
    grid, motion, _ = fixture()
    monkeypatch.setattr(compact_module, "perf_counter", lambda: 5.)
    expired = CompactParticleDP(grid, start=0, budget=4, q=.78, motion=motion, deadline=5.)
    assert not expired.ready and expired.stop_reason == "max_seconds"
    assert expired.build_info["allocated_peak_managed_bytes"] == 0
    calls = 0
    def clock():
        nonlocal calls
        calls += 1
        return 0. if calls < expire_at else 10.
    monkeypatch.setattr(compact_module, "perf_counter", clock)
    partial = CompactParticleDP(grid, start=0, budget=4, q=.78, motion=motion, deadline=5.)
    assert not partial.ready and partial.stop_reason == "max_seconds"
    assert partial.cost_table is None and partial.build_info["published_table_bytes"] == 0
    assert partial.build_info["allocated_peak_managed_bytes"] > 0
    if expire_at == 30:
        assert partial.build_info["edge_backups"] == 0
    else:
        assert 0 < partial.build_info["edge_backups"] < 14
    with pytest.raises(ValueError, match="not ready"):
        partial.validate_compatibility(grid, start=0, budget=4, q=.78, motion=motion)


def test_compatibility_and_root_cone_queries_are_checked():
    grid, motion, p = fixture()
    compact = CompactParticleDP(grid, start=0, budget=4, q=.78, motion=motion)
    args = dict(grid=grid, start=0, budget=4, q=.78, motion=motion)
    for change in (dict(start=1), dict(grid=GridGraph(1, 4)), dict(budget=3), dict(q=.5), dict(motion=fixture()[1])):
        with pytest.raises(ValueError, match="mismatch|identity"):
            compact.validate_compatibility(**dict(args, **change))
    for vertex, depth in ((1, 0), (0, 1), (3, 1)):
        with pytest.raises(ValueError, match="root-time reachability"):
            compact(vertex, depth, p)
    with pytest.raises(RuntimeError, match="not supported"):
        compact.pd_upper_bound(0, 0, p)


@pytest.mark.parametrize("options", [dict(max_seconds=-1), dict(max_seconds=inf),
    dict(deadline=float("nan")), dict(max_memory_bytes=-1), dict(max_memory_bytes=1.5),
    dict(with_pd_bound=True), dict(with_pd_bound=1), dict(start=-1), dict(q=1.1)])
def test_invalid_constructor_options_fail(options):
    grid, motion, _ = fixture()
    args = dict(start=0, budget=4, q=.78, motion=motion)
    with pytest.raises(ValueError):
        CompactParticleDP(grid, **dict(args, **options))


@pytest.mark.parametrize("options", [dict(vertex=8), dict(depth=-1), dict(depth=5),
    dict(belief=[1.]), dict(belief=np.full(8, -.1)), dict(belief=np.full(8, .2))])
def test_invalid_query_options_fail(options):
    grid, motion, p = fixture()
    compact = CompactParticleDP(grid, start=0, budget=4, q=.78, motion=motion)
    with pytest.raises(ValueError):
        compact(**dict(dict(vertex=0, depth=0, belief=p), **options))


def test_motion_type_size_and_horizon_fail():
    grid, motion, _ = fixture()
    for g, m, T in ((grid, MatrixMotion.identity(4), 4), (GridGraph(1, 3), motion, 4), (grid, motion, 5)):
        with pytest.raises(ValueError):
            CompactParticleDP(g, start=0, budget=T, q=.78, motion=m)
