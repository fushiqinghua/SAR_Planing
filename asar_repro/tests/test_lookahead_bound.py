"""Independent full-path Oracle checks for budget-aware STDC prefix lifting."""
from math import inf

import numpy as np
import pytest

import asar_repro.lookahead_bound as module
from asar_repro.grid import GridGraph
from asar_repro.heuristic import Heuristic
from asar_repro.lookahead_bound import LookaheadBound
from asar_repro.motion import MatrixMotion, ParticleMotion
from asar_repro.objective import score_path

ATOL = 1e-10


def legal_paths(grid, start, steps):
    """Independent DFS: never calls a bound or planner to choose branches."""
    def walk(path):
        if len(path) == steps + 1:
            yield tuple(path)
            return
        for nxt in grid.neighbors(path[-1]):
            yield from walk(path + [nxt])
    yield from walk([start])


def all_prefix_oracle(grid, cfg):
    minima = {}
    for path in legal_paths(grid, cfg["start"], cfg["budget"]):
        full = score_path(grid, path, **cfg)
        for depth in range(cfg["budget"] + 1):
            prefix = path[:depth + 1]
            current = score_path(grid, prefix, **{**cfg, "budget": depth})
            remaining = full.J - current.J
            minima[prefix] = min(minima.get(prefix, inf), remaining)
    return minima


def random_case(kind, seed):
    rng = np.random.default_rng(seed)
    grid = GridGraph(2, 3)
    T = 4
    q = rng.uniform(0.05, 0.95, grid.size)
    if kind == "particle":
        N = 10
        cells = rng.integers(0, grid.size, (T + 1, N))
        cells[:, -4:] = grid.size + np.arange(4)
        motion = ParticleMotion(cells, grid.size, rng.permutation(np.arange(N) + 20))
        p = rng.dirichlet(np.ones(N))
    else:
        p = rng.dirichlet(np.ones(grid.size))
        if kind == "identity":
            motion = MatrixMotion.identity(grid.size)
        elif kind == "stationary":
            motion = MatrixMotion.stationary(rng.dirichlet(np.ones(grid.size), size=grid.size))
        else:
            matrices = rng.dirichlet(np.ones(grid.size), size=(T, grid.size))
            motion = MatrixMotion.time_varying(matrices)
    return grid, dict(start=0, budget=T, p=p, q=q, motion=motion)


@pytest.mark.parametrize("kind", ["identity", "stationary", "dynamic", "particle"])
@pytest.mark.parametrize("seed", [73, 219])
def test_every_legal_prefix_matches_independent_admissibility_oracle(kind, seed):
    grid, cfg = random_case(kind, seed)
    estimator = LookaheadBound(grid, budget=cfg["budget"], q=cfg["q"], motion=cfg["motion"])
    original = Heuristic(grid, budget=cfg["budget"], q=cfg["q"], motion=cfg["motion"], mode="stdc_lb")
    p_before = cfg["p"].copy()
    q_before = cfg["q"].copy()
    totals = dict(aux_expanded=0, aux_generated=0, leaf_evaluations=0)
    for prefix, optimum in all_prefix_oracle(grid, cfg).items():
        d = len(prefix) - 1
        prefix_score = score_path(grid, prefix, **{**cfg, "budget": d})
        belief = prefix_score.final_belief
        before = belief.copy()
        result = estimator.evaluate(prefix[-1], d, belief)
        assert result.status == "completed"
        assert result.stop_reason is None
        assert not result.cutoff_reached
        assert 0 <= result.value <= optimum + ATOL
        assert result.value + ATOL >= original(prefix[-1], d, belief)
        if cfg["budget"] - d <= 2:
            assert result.value == pytest.approx(optimum, abs=ATOL, rel=0)
        if d < cfg["budget"]:
            assert result.lookahead_completed
            assert result.lookahead_value is not None
            assert result.value == max(result.base_value, result.lookahead_value)
            assert result.leaf_evaluations == len(list(legal_paths(grid, prefix[-1], min(2, cfg["budget"] - d))))
        for key in totals:
            totals[key] += getattr(result, key)
        assert np.array_equal(belief, before)
    assert np.array_equal(cfg["p"], p_before)
    assert np.array_equal(cfg["q"], q_before)
    for key, total in totals.items():
        assert estimator.stats[key] == total


def continuity_gap_case():
    grid = GridGraph(3, 3)
    p = np.zeros(9)
    p[1], p[8] = 0.6, 0.4
    return grid, dict(start=4, budget=2, p=p, q=1.0, motion=MatrixMotion.identity(9))


@pytest.mark.parametrize("steps", [1, 2])
def test_hand_calculation_restores_continuity_ignored_by_relaxation(steps):
    grid, cfg = continuity_gap_case()
    estimate = LookaheadBound(grid, budget=2, q=1, motion=cfg["motion"], steps=steps)
    result = estimate.evaluate(4, 0, cfg["p"])
    # Relaxation takes .6 at vertex 1 then .4 at vertex 8: .4+0=.4.
    # A legal route cannot move 1->8. Taking vertex 1 first instead leaves
    # .4 at both steps, cost .8; going via 5/7 to 8 costs 1+.6=1.6.
    assert result.base_value == pytest.approx(0.4, abs=1e-12, rel=0)
    assert result.lookahead_value == pytest.approx(0.8, abs=1e-12, rel=0)
    assert result.value == pytest.approx(0.8, abs=1e-12, rel=0)
    assert score_path(grid, (4, 1, 0), **cfg).J == pytest.approx(0.8)
    assert min(score_path(grid, path, **cfg).J for path in legal_paths(grid, 4, 2)) == pytest.approx(0.8)


def dynamic_absolute_case():
    grid = GridGraph(1, 3)
    p1, p2, p3 = (np.eye(3) for _ in range(3))
    p1[0] = [0, 1, 0]
    p2[1] = [0, 0, 1]
    p3[2] = [1, 0, 0]
    return grid, dict(start=0, budget=3, p=np.array([1.0, 0.0, 0.0]),
                     q=np.array([0.1, 0.7, 0.8]), motion=MatrixMotion.time_varying([p1, p2, p3]))


@pytest.mark.parametrize("prefix,expected", [((0, 1), 0.12), ((0, 1, 2), 0.06)])
def test_nonzero_depth_uses_absolute_transition_and_remaining_horizon(prefix, expected):
    grid, cfg = dynamic_absolute_case()
    depth = len(prefix) - 1
    score = score_path(grid, prefix, **{**cfg, "budget": depth})
    estimate = LookaheadBound(grid, budget=3, q=cfg["q"], motion=cfg["motion"])
    result = estimate.evaluate(prefix[-1], depth, score.final_belief)
    # Before the window .3 mass remains at cell1. P2 moves it to cell2,
    # observing cell2 leaves .06; P3 moves it to inaccessible cell0, so .06
    # remains again. Using relative P1 instead of absolute P2 is incorrect.
    assert result.value == pytest.approx(expected, abs=1e-12, rel=0)
    assert result.lookahead_completed
    assert result.value == pytest.approx(all_prefix_oracle(grid, cfg)[prefix], abs=1e-12, rel=0)


@pytest.mark.parametrize("kind", ["identity", "dynamic", "particle"])
def test_no_detection_preserves_remaining_mass_and_truncated_cost(kind):
    grid, cfg = random_case(kind, 91)
    cfg["q"] = 0.0
    estimate = LookaheadBound(grid, budget=4, q=0, motion=cfg["motion"])
    prefix = (0, 1)
    score = score_path(grid, prefix, **{**cfg, "budget": 1})
    result = estimate.evaluate(1, 1, score.final_belief)
    assert result.base_value == pytest.approx(3.0, abs=1e-12, rel=0)
    assert result.value == pytest.approx(3.0, abs=1e-12, rel=0)
    assert score.pd_final == pytest.approx(0.0, abs=1e-12, rel=0)


def test_particle_ids_and_permanently_unsearchable_mass_are_retained():
    grid = GridGraph(1, 2)
    cells = np.tile(np.arange(6), (3, 1))
    ids = np.array([31, 4, 92, 8, 15, 77])
    motion = ParticleMotion(cells, grid.size, ids)
    weights = np.array([0.1, 0.2, 0.3, 0.1, 0.1, 0.2])
    result = LookaheadBound(grid, budget=2, q=1, motion=motion).evaluate(0, 0, weights)
    # No t0 observation: M1=.8, M2=.7; the four special bins retain .7.
    assert result.value == pytest.approx(1.5, abs=1e-12, rel=0)
    score = score_path(grid, (0, 1, 0), start=0, budget=2, p=weights, q=1, motion=motion)
    assert result.value == pytest.approx(score.J, abs=1e-12, rel=0)
    assert score.survival[-1] == pytest.approx(0.7, abs=1e-12, rel=0)
    assert np.array_equal(motion.cell_ids, cells)
    assert np.array_equal(motion.trajectory_ids, ids)


def cheap_bad_first_branch():
    grid = GridGraph(2, 2)
    cfg = dict(start=0, budget=2, p=np.array([0.0, 0.1, 0.8, 0.1]),
               q=1.0, motion=MatrixMotion.identity(4))
    return grid, cfg


@pytest.mark.parametrize("limit,leaves", [(0, 0), (1, 0), (2, 2)])
def test_work_limit_discards_unsafe_partial_minimum(limit, leaves):
    grid, cfg = cheap_bad_first_branch()
    estimate = LookaheadBound(grid, budget=2, q=1, motion=cfg["motion"])
    result = estimate.evaluate(0, 0, cfg["p"], max_aux_expansions=limit)
    assert result.status == "interrupted"
    assert result.stop_reason == "max_aux_expansions"
    assert result.aux_expanded == limit
    assert result.leaf_evaluations == leaves
    assert not result.lookahead_completed
    assert result.lookahead_value is None
    assert result.value == pytest.approx(result.base_value, abs=1e-12, rel=0)
    assert result.value == pytest.approx(0.3, abs=1e-12, rel=0)
    if limit == 2:
        # Neighbor 1 is enumerated first; its cheapest leaf costs 1.7.
        # The not-yet-expanded neighbor 2 has true optimum .3. Using the
        # partially enumerated minimum would thus destroy admissibility.
        partial = min(score_path(grid, path, **cfg).J for path in ((0, 1, 0), (0, 1, 3)))
        assert partial == pytest.approx(1.7)
        assert partial > all_prefix_oracle(grid, cfg)[(0,)] + 1.0
    assert estimate.stats["work_interruptions"] == 1


def test_exact_auxiliary_budget_can_finish_without_a_false_interruption():
    grid, cfg = cheap_bad_first_branch()
    result = LookaheadBound(grid, budget=2, q=1, motion=cfg["motion"]).evaluate(
        0, 0, cfg["p"], max_aux_expansions=3)
    assert result.status == "completed"
    assert result.lookahead_completed
    assert (result.aux_expanded, result.aux_generated, result.leaf_evaluations) == (3, 6, 4)
    assert result.value == pytest.approx(0.3, abs=1e-12, rel=0)


def test_already_expired_deadline_returns_mass_without_calling_stdc(monkeypatch):
    grid, cfg = cheap_bad_first_branch()
    estimate = LookaheadBound(grid, budget=2, q=0.5, motion=cfg["motion"])
    monkeypatch.setattr(module, "perf_counter", lambda: 10.0)
    def forbidden(*args):
        raise AssertionError("expired call must not start STDC")
    monkeypatch.setattr(estimate, "_stdc", forbidden)
    result = estimate.evaluate(0, 0, cfg["p"], deadline=5.0)
    assert result.status == "interrupted" and result.stop_reason == "max_seconds"
    assert result.stage == "mass"
    assert result.value == pytest.approx(0.75, abs=1e-12, rel=0)
    assert result.aux_expanded == result.stdc_evaluations == 0


@pytest.mark.parametrize("expire_call", [1, 2])
def test_deadline_after_base_or_first_leaf_returns_only_completed_base(monkeypatch, expire_call):
    grid, cfg = cheap_bad_first_branch()
    estimate = LookaheadBound(grid, budget=3, q=1, motion=cfg["motion"])
    base = Heuristic(grid, budget=3, q=1, motion=cfg["motion"], mode="stdc_lb")(0, 0, cfg["p"])
    clock = {"now": 0.0, "calls": 0}
    monkeypatch.setattr(module, "perf_counter", lambda: clock["now"])
    original = estimate._stdc
    def expire(v, d, b):
        value = original(v, d, b)
        clock["calls"] += 1
        if clock["calls"] == expire_call:
            clock["now"] = 5.0
        return value
    monkeypatch.setattr(estimate, "_stdc", expire)
    result = estimate.evaluate(0, 0, cfg["p"], deadline=5.0)
    assert result.status == "interrupted" and result.stop_reason == "max_seconds"
    assert result.stage == "stdc"
    assert result.value == pytest.approx(base, abs=1e-12, rel=0)
    assert result.lookahead_value is None and not result.lookahead_completed
    assert result.leaf_evaluations == (0 if expire_call == 1 else 1)
    assert estimate.stats["deadline_interruptions"] == 1


@pytest.mark.parametrize("cutoff,stage,value", [(0.0, "mass", 0.0), (0.3, "stdc", 0.4), (0.7, "lookahead", 0.8)])
def test_cutoff_stops_only_after_an_already_safe_cascade_stage(cutoff, stage, value):
    grid, cfg = continuity_gap_case()
    estimate = LookaheadBound(grid, budget=2, q=1, motion=cfg["motion"])
    result = estimate.evaluate(4, 0, cfg["p"], cutoff=cutoff)
    assert result.status == "cutoff" and result.stop_reason is None
    assert result.stage == stage and result.cutoff_reached
    assert result.value == pytest.approx(value, abs=1e-12, rel=0)
    assert result.value <= all_prefix_oracle(grid, cfg)[(4,)] + ATOL
    if stage != "lookahead":
        assert result.aux_expanded == result.aux_generated == 0
        assert result.lookahead_value is None and not result.lookahead_completed
    assert estimate.stats[stage + "_cutoffs"] == 1


def test_terminal_and_no_successor_are_distinct():
    grid = GridGraph(1, 1)
    motion = MatrixMotion.identity(1)
    terminal = LookaheadBound(grid, budget=0, q=1, motion=motion).evaluate(0, 0, [1.0])
    assert terminal.value == 0.0 and terminal.stage == "terminal"
    assert terminal.aux_expanded == 0
    infeasible = LookaheadBound(grid, budget=1, q=1, motion=motion).evaluate(0, 0, [1.0])
    assert infeasible.value == inf and infeasible.stage == "infeasible"
    assert infeasible.status == "completed" and infeasible.aux_expanded == 0
    assert list(legal_paths(grid, 0, 1)) == []


@pytest.mark.parametrize("overrides", [dict(depth=-1), dict(depth=3), dict(vertex=7),
                                      dict(belief=[1.0]), dict(belief=[-0.1, 0.1, 0.5, 0.5]),
                                      dict(cutoff=float("nan")), dict(deadline=float("nan")),
                                      dict(max_aux_expansions=-1), dict(max_aux_expansions=1.5)])
def test_invalid_evaluation_inputs_fail_explicitly(overrides):
    grid, cfg = cheap_bad_first_branch()
    estimate = LookaheadBound(grid, budget=2, q=1, motion=cfg["motion"])
    args = dict(vertex=0, depth=0, belief=cfg["p"])
    args.update(overrides)
    with pytest.raises(ValueError):
        estimate.evaluate(**args)


@pytest.mark.parametrize("steps", [0, -1, 1.5, True])
def test_invalid_lookahead_depth_is_rejected(steps):
    with pytest.raises(ValueError):
        LookaheadBound(GridGraph(2, 2), budget=2, q=0.5, motion=MatrixMotion.identity(4), steps=steps)


def test_missing_dynamic_frames_fail_before_any_search():
    with pytest.raises(ValueError, match="missing P_t"):
        LookaheadBound(GridGraph(1, 2), budget=2, q=0.5,
                       motion=MatrixMotion.time_varying([np.eye(2)]))
    with pytest.raises(ValueError, match="cover frames"):
        LookaheadBound(GridGraph(1, 2), budget=2, q=0.5,
                       motion=ParticleMotion([[0, 1], [1, 0]], 2, [1, 2]))
