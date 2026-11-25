"""Independent full-path replays for the per-particle DP relaxation."""
from math import inf
from pathlib import Path

import numpy as np
import pytest

import asar_repro.particle_dp as dp_module
from asar_repro.grid import GridGraph
from asar_repro.heuristic import Heuristic
from asar_repro.motion import MatrixMotion, ParticleMotion
from asar_repro.objective import score_path
from asar_repro.particle_dp import ParticleDP
from asar_repro.research_particle import FutureEquivalentMotion

ATOL = 1e-10


def paths(grid, start, budget):
    """Independent legal DFS, with no DP coefficients or planner decisions."""
    def walk(prefix):
        if len(prefix) == budget + 1:
            yield tuple(prefix)
        else:
            for nxt in grid.neighbors(prefix[-1]):
                yield from walk(prefix + [nxt])
    yield from walk([start])


def prefix_oracles(grid, cfg):
    result = {}
    for route in paths(grid, cfg["start"], cfg["budget"]):
        score = score_path(grid, route, **cfg, record_beliefs=True)
        for depth in range(cfg["budget"] + 1):
            prefix = route[:depth + 1]
            row = result.setdefault(prefix, dict(J=inf, Pd=-inf, belief=score.beliefs[depth].copy()))
            row["J"] = min(row["J"], score.J-float(score.g[depth]))
            row["Pd"] = max(row["Pd"], score.pd_final)
    return result


def tiny_motion():
    return ParticleMotion(np.array([[0, 1], [1, 2], [3, 0], [2, 3]]), 4, [17, 93])


@pytest.mark.parametrize("q_kind", ["zero", "one", "vector"])
@pytest.mark.parametrize("seed", [4, 21])
def test_single_particle_all_prefixes_are_exact_for_each_separate_objective(q_kind, seed):
    rng = np.random.default_rng(seed)
    grid, T = GridGraph(2, 3), 4
    motion = ParticleMotion(rng.integers(0, grid.size, (T+1, 1)), grid.size, [409])
    q = {"zero": 0.0, "one": 1.0, "vector": np.array([0.1, 0.3, 0.8, 1.0, 0.6, 0.2])}[q_kind]
    cfg = dict(start=0, budget=T, p=np.array([1.0]), q=q, motion=motion)
    estimate = ParticleDP(grid, budget=T, q=q, motion=motion, with_pd_bound=True)
    assert estimate.ready and estimate.status == "completed" and estimate.stop_reason is None
    for prefix, oracle in prefix_oracles(grid, cfg).items():
        vertex, depth = prefix[-1], len(prefix)-1
        assert estimate(vertex, depth, oracle["belief"]) == pytest.approx(oracle["J"], abs=ATOL, rel=0)
        assert estimate.pd_upper_bound(vertex, depth, oracle["belief"]) == pytest.approx(oracle["Pd"], abs=ATOL, rel=0)
    assert estimate.validate_compatibility(grid, budget=T, q=q, motion=motion)
    assert not estimate.cost_table.flags.writeable
    assert not estimate.survival_table.flags.writeable
    assert not estimate.feasible_table.flags.writeable
    assert np.array_equal(estimate.trajectory_ids, [409])


@pytest.mark.parametrize("seed", [0, 12])
@pytest.mark.parametrize("q", [0.78, np.array([0.0, 1.0, 0.35, 0.8])])
def test_multiple_particles_all_prefixes_bound_a_common_legal_route(seed, q):
    rng = np.random.default_rng(seed)
    grid, T, N = GridGraph(2, 2), 4, 8
    cells = rng.integers(0, grid.size, (T+1, N))
    cells[:, -4:] = grid.size + np.arange(4)
    ids = rng.permutation(np.arange(N) + 80)
    motion = ParticleMotion(cells, grid.size, ids)
    p = rng.dirichlet(np.ones(N))
    cfg = dict(start=0, budget=T, p=p, q=q, motion=motion)
    estimate = ParticleDP(grid, budget=T, q=q, motion=motion, with_pd_bound=True)
    for prefix, oracle in prefix_oracles(grid, cfg).items():
        b = oracle["belief"]
        before = b.copy()
        h = estimate(prefix[-1], len(prefix)-1, b)
        pd = estimate.pd_upper_bound(prefix[-1], len(prefix)-1, b)
        assert 0 <= h <= oracle["J"] + ATOL
        assert pd + ATOL >= oracle["Pd"]
        assert np.array_equal(b, before)
    assert np.array_equal(motion.cell_ids, cells)
    assert np.array_equal(motion.trajectory_ids, ids)


def test_independent_routes_are_a_relaxation_not_an_achievable_shared_route():
    grid = GridGraph(2, 2)
    motion = ParticleMotion([[1, 2], [1, 2]], 4, [10, 20])
    cfg = dict(start=0, budget=1, p=np.array([0.5, 0.5]), q=1.0, motion=motion)
    estimate = ParticleDP(grid, budget=1, q=1, motion=motion, with_pd_bound=True)
    oracle = prefix_oracles(grid, cfg)[(0,)]
    assert estimate(0, 0, cfg["p"]) == 0.0
    assert estimate.pd_upper_bound(0, 0, cfg["p"]) == 1.0
    assert oracle["J"] == 0.5 and oracle["Pd"] == 0.5


def test_minimum_J_and_maximum_Pd_may_use_different_single_particle_routes():
    grid = GridGraph(3, 3)
    motion = ParticleMotion([[4], [1], [8]], 9, [71])
    q = np.zeros(9)
    q[1], q[8] = 0.6, 0.9
    cfg = dict(start=4, budget=2, p=np.array([1.0]), q=q, motion=motion)
    estimate = ParticleDP(grid, budget=2, q=q, motion=motion, with_pd_bound=True)
    early = score_path(grid, (4, 1, 0), **cfg)
    late = score_path(grid, (4, 5, 8), **cfg)
    assert (early.J, early.pd_final) == pytest.approx((0.8, 0.6))
    assert (late.J, late.pd_final) == pytest.approx((1.1, 0.9))
    assert estimate(4, 0, [1]) == pytest.approx(0.8)
    assert estimate.pd_upper_bound(4, 0, [1]) == pytest.approx(0.9)
    scores = [score_path(grid, path, **cfg) for path in paths(grid, 4, 2)]
    assert not any(abs(s.J-0.8) <= ATOL and abs(s.pd_final-0.9) <= ATOL for s in scores)


def test_absolute_frames_and_no_t0_sensing_hand_calculation():
    grid = GridGraph(1, 3)
    motion = ParticleMotion([[0], [1], [2], [0]], 3, [63])
    q = np.array([0.1, 0.7, 0.8])
    estimate = ParticleDP(grid, budget=3, q=q, motion=motion, with_pd_bound=True)
    assert estimate(0, 0, [1]) == pytest.approx(0.42, abs=ATOL, rel=0)
    # After t1 the weight is .3. At absolute t2, observation at cell2 leaves
    # .06; at t3 the target is cell0 but the searcher must move 2->1.
    assert estimate(1, 1, [0.3]) == pytest.approx(0.12, abs=ATOL, rel=0)
    assert estimate.pd_upper_bound(1, 1, [0.3]) == pytest.approx(0.94, abs=ATOL, rel=0)
    assert estimate(2, 2, [0.06]) == pytest.approx(0.06, abs=ATOL, rel=0)
    assert estimate(1, 3, [0.06]) == 0.0
    assert estimate.pd_upper_bound(1, 3, [0.06]) == pytest.approx(0.94, abs=ATOL, rel=0)


def test_unnormalized_weights_and_all_special_bins_keep_their_mass():
    grid = GridGraph(1, 2)
    cells = np.tile(np.arange(6), (4, 1))
    motion = ParticleMotion(cells, 2, [90, 13, 8, 21, 50, 72])
    p = np.array([0.1, 0.2, 0.3, 0.1, 0.1, 0.2])
    estimate = ParticleDP(grid, budget=3, q=0, motion=motion, with_pd_bound=True)
    assert estimate(0, 0, p) == pytest.approx(3)
    assert estimate(1, 1, p*0.3) == pytest.approx(0.6)
    assert estimate.pd_upper_bound(1, 1, p*0.3) == pytest.approx(0.7)
    full_detection = ParticleDP(grid, budget=2, q=1, motion=motion, with_pd_bound=True)
    assert full_detection(0, 0, p) == pytest.approx(1.5)
    assert full_detection.pd_upper_bound(0, 0, p) == pytest.approx(0.3)
    assert np.all(full_detection.cost_table[0, 0, 2:] == 2.0)
    assert np.all(full_detection.survival_table[0, 0, 2:] == 1.0)


def exact_markov_particles(initial, matrices):
    """Enumerate the entire finite Markov law; no sampled particle surrogate."""
    rows, weights = [], []
    def visit(route, weight):
        step = len(route)-1
        if step == len(matrices):
            rows.append(route)
            weights.append(weight)
        else:
            for cell in np.flatnonzero(matrices[step, route[-1]] > 0):
                visit(route + [int(cell)], weight * matrices[step, route[-1], cell])
    for cell in np.flatnonzero(initial > 0):
        visit([int(cell)], float(initial[cell]))
    return np.asarray(rows, dtype=np.intp).T, np.asarray(weights)


def test_original_dynamic_counterexample_retained_with_exact_particle_law():
    fixture = Path(__file__).resolve().parents[1] / "data/fixtures/heuristic_dynamic_counterexample.npz"
    with np.load(fixture, allow_pickle=False) as data:
        initial, matrices = data["p"].copy(), data["P"].copy()
        T, start, q = int(data["T"]), int(data["start"]), float(data["q"])
    grid = GridGraph(3, 3)
    matrix_cfg = dict(start=start, budget=T, p=initial, q=q,
                      motion=MatrixMotion.time_varying(matrices))
    oracle = prefix_oracles(grid, matrix_cfg)
    paper = Heuristic(grid, budget=T, q=q, motion=matrix_cfg["motion"], mode="paper_greedy")
    assert paper(start, 0, initial) > oracle[(start,)]["J"] + 0.07
    cells, weights = exact_markov_particles(initial, matrices)
    assert abs(float(weights.sum())-1.0) <= 1e-12
    motion = ParticleMotion(cells, grid.size, np.arange(len(weights)) + 1000)
    estimate = ParticleDP(grid, budget=T, q=q, motion=motion)
    for prefix, target in oracle.items():
        depth = len(prefix)-1
        particle_score = score_path(grid, prefix, start=start, budget=depth, p=weights, q=q, motion=motion)
        matrix_score = score_path(grid, prefix, **{**matrix_cfg, "budget": depth})
        assert particle_score.J == pytest.approx(matrix_score.J, abs=ATOL, rel=0)
        assert estimate(prefix[-1], depth, particle_score.final_belief) <= target["J"] + ATOL


def test_500_original_ids_and_exactly_342_groups_have_equivalent_coefficients():
    grid, T = GridGraph(2, 2), 4
    codes = np.arange(342)
    signatures = np.array([(codes // 4**(T-t)) % 4 for t in range(T+1)])
    columns = np.r_[np.arange(342), np.arange(158)]
    cells = signatures[:, columns]
    original = ParticleMotion(cells, grid.size, np.arange(500)*3 + 7)
    p = np.full(500, 1/500)
    grouped = FutureEquivalentMotion(original, p)
    assert grouped.state_size == 342
    raw_dp = ParticleDP(grid, budget=T, q=0.78, motion=original, with_pd_bound=True)
    grouped_dp = ParticleDP(grid, budget=T, q=0.78, motion=grouped, with_pd_bound=True)
    assert np.array_equal(raw_dp.cost_table[:, :, grouped.representative_columns], grouped_dp.cost_table)
    assert np.array_equal(raw_dp.survival_table[:, :, grouped.representative_columns], grouped_dp.survival_table)
    cfg = dict(start=0, budget=T, p=p, q=0.78, motion=original)
    for prefix, oracle in prefix_oracles(grid, cfg).items():
        vertex, depth = prefix[-1], len(prefix)-1
        b = oracle["belief"]
        compressed = grouped.aggregate_weights(b)
        assert raw_dp(vertex, depth, b) == pytest.approx(grouped_dp(vertex, depth, compressed), abs=ATOL, rel=0)
        assert raw_dp.pd_upper_bound(vertex, depth, b) == pytest.approx(
            grouped_dp.pd_upper_bound(vertex, depth, compressed), abs=ATOL, rel=0)
    assert grouped_dp.build_info["cost_table_bytes"] < raw_dp.build_info["cost_table_bytes"]
    assert np.array_equal(grouped.original_trajectory_ids, original.trajectory_ids)


@pytest.mark.parametrize("weights", [[1.0, 0.0], [0.0, 0.0]])
def test_infeasible_suffix_is_detected_before_zero_times_infinity(weights):
    grid = GridGraph(1, 1)
    motion = ParticleMotion([[0, 1], [0, 1], [0, 1]], 1, [12, 37])
    estimate = ParticleDP(grid, budget=2, q=1, motion=motion, with_pd_bound=True)
    with np.errstate(invalid="raise"):
        assert estimate(0, 0, weights) == inf
        assert estimate(0, 1, weights) == inf
        assert estimate.pd_upper_bound(0, 0, weights) is None
        assert estimate(0, 2, weights) == 0
    assert not np.any(estimate.feasible_table[:2])
    assert np.all(estimate.feasible_table[2])


def test_zero_horizon_has_no_sensing_and_optional_Pd_table_is_explicit():
    motion = ParticleMotion([[0, 1]], 2, [2, 9])
    grid = GridGraph(1, 2)
    estimate = ParticleDP(grid, budget=0, q=1, motion=motion)
    assert estimate(0, 0, [0.4, 0.2]) == 0
    assert estimate.build_info["edge_backups"] == 0
    assert estimate.survival_table is None
    with pytest.raises(RuntimeError, match="not requested"):
        estimate.pd_upper_bound(0, 0, [0.4, 0.2])


def assert_unpublished(estimate, reason):
    assert not estimate.ready and estimate.status == "budget_exceeded"
    assert estimate.stop_reason == reason
    assert estimate.cost_table is None and estimate.survival_table is None and estimate.feasible_table is None
    assert estimate.build_info["published_table_bytes"] == 0
    with pytest.raises(RuntimeError, match="partial tables"):
        estimate(0, 0, [0.5, 0.5])
    with pytest.raises(RuntimeError, match="partial tables"):
        estimate.pd_upper_bound(0, 0, [0.5, 0.5])
    with pytest.raises(ValueError, match="not ready"):
        estimate.validate_compatibility(estimate.grid, budget=estimate.budget, q=0.78, motion=estimate.motion)


def test_memory_budget_is_checked_before_DP_buffers_and_exact_boundary_is_allowed():
    grid, motion = GridGraph(2, 2), tiny_motion()
    full = ParticleDP(grid, budget=3, q=0.78, motion=motion, with_pd_bound=True)
    required = full.build_info["required_peak_managed_bytes"]
    stopped = ParticleDP(grid, budget=3, q=0.78, motion=motion,
                         with_pd_bound=True, max_memory_bytes=required-1)
    assert_unpublished(stopped, "max_memory_bytes")
    assert stopped.build_info["allocated_peak_managed_bytes"] == 0
    allowed = ParticleDP(grid, budget=3, q=0.78, motion=motion,
                         with_pd_bound=True, max_memory_bytes=required)
    assert allowed.ready
    assert allowed.build_info["allocated_peak_managed_bytes"] == required
    assert np.array_equal(allowed.cost_table, full.cost_table)


@pytest.mark.parametrize("limit", ["relative", "absolute"])
def test_expired_build_never_publishes_tables(monkeypatch, limit):
    monkeypatch.setattr(dp_module, "perf_counter", lambda: 5.0)
    kwargs = dict(max_seconds=0) if limit == "relative" else dict(deadline=5)
    estimate = ParticleDP(GridGraph(2, 2), budget=3, q=0.78, motion=tiny_motion(), **kwargs)
    assert_unpublished(estimate, "max_seconds")
    assert estimate.build_info["allocated_peak_managed_bytes"] == 0


def test_interrupted_partial_layer_is_discarded_and_later_queries_are_forbidden(monkeypatch):
    calls = {"count": 0}
    def clock():
        calls["count"] += 1
        return 0.0 if calls["count"] < 15 else 10.0
    monkeypatch.setattr(dp_module, "perf_counter", clock)
    estimate = ParticleDP(GridGraph(2, 2), budget=3, q=0.78,
                          motion=tiny_motion(), with_pd_bound=True, deadline=5)
    assert_unpublished(estimate, "max_seconds")
    assert estimate.build_info["allocated_peak_managed_bytes"] > 0
    assert estimate.build_info["edge_backups"] > 0
    assert estimate.build_info["completed_time_layers"] < 3


def test_compatibility_cannot_reuse_equal_size_but_different_inputs():
    grid, motion = GridGraph(2, 2), tiny_motion()
    q = np.array([0.1, 0.2, 0.3, 0.4])
    estimate = ParticleDP(grid, budget=3, q=q, motion=motion)
    assert estimate.validate_compatibility(GridGraph(2, 2), budget=3, q=q.copy(), motion=motion)
    for changed in (dict(grid=GridGraph(1, 4)), dict(budget=2), dict(q=q+0.1), dict(motion=tiny_motion())):
        args = dict(grid=grid, budget=3, q=q, motion=motion)
        args.update(changed)
        with pytest.raises(ValueError, match="mismatch|identity"):
            estimate.validate_compatibility(**args)
    q[:] = 0
    assert np.array_equal(estimate.q, [0.1, 0.2, 0.3, 0.4])


@pytest.mark.parametrize("overrides", [dict(depth=-1), dict(depth=4), dict(vertex=8),
                                      dict(belief=[1.0]), dict(belief=[-0.1, 0.1]),
                                      dict(belief=[0.7, 0.7])])
def test_invalid_queries_fail_explicitly(overrides):
    estimate = ParticleDP(GridGraph(2, 2), budget=3, q=0.78, motion=tiny_motion())
    args = dict(vertex=0, depth=0, belief=[0.5, 0.5])
    args.update(overrides)
    with pytest.raises(ValueError):
        estimate(**args)


@pytest.mark.parametrize("options", [dict(max_seconds=-1), dict(max_seconds=inf),
                                    dict(deadline=float("nan")), dict(max_memory_bytes=-1),
                                    dict(max_memory_bytes=1.5), dict(with_pd_bound=1)])
def test_invalid_construction_budgets_fail_explicitly(options):
    with pytest.raises(ValueError):
        ParticleDP(GridGraph(2, 2), budget=3, q=0.78, motion=tiny_motion(), **options)


def test_motion_type_grid_and_horizon_validation():
    with pytest.raises(ValueError, match="ParticleMotion"):
        ParticleDP(GridGraph(2, 2), budget=3, q=0.78, motion=MatrixMotion.identity(4))
    with pytest.raises(ValueError, match="grid size"):
        ParticleDP(GridGraph(1, 3), budget=3, q=0.78, motion=tiny_motion())
    with pytest.raises(ValueError, match="cover frames"):
        ParticleDP(GridGraph(2, 2), budget=4, q=0.78, motion=tiny_motion())
