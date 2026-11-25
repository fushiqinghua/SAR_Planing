"""Global anytime search: ordering is heuristic, pruning uses valid bounds."""

from pathlib import Path

import numpy as np
import pytest

import asar_repro.anytime_search as anytime_module
from asar_repro.grid import GridGraph
from asar_repro.heuristic import Heuristic
from asar_repro.motion import MatrixMotion, ParticleMotion
from asar_repro.objective import score_path
from asar_repro.oracle import enumerate_oracle


BOUND_MODES = ("zero", "mass_lb", "stdc_lb")


def simple_case():
    return GridGraph(2, 2), dict(start=0, budget=2,
                                p=np.array([0.0, 0.1, 0.8, 0.1]), q=1.0,
                                motion=MatrixMotion.identity(4))


def inject_misleading_guide(monkeypatch):
    """Make the better first move look arbitrarily expensive for ordering."""
    original = anytime_module.Heuristic

    def factory(grid, *, budget, q, motion, mode):
        if mode == "paper_greedy":
            return lambda vertex, depth, belief: 1_000_000.0 if depth == 1 and vertex == 2 else 0.0
        return original(grid, budget=budget, q=q, motion=motion, mode=mode)

    monkeypatch.setattr(anytime_module, "Heuristic", factory)


def assert_replayed(grid, cfg, result, *, oracle=None):
    assert result.path is not None
    score = score_path(grid, result.path, **cfg)
    assert result.J == pytest.approx(score.J, abs=1e-10, rel=0)
    assert result.Pd == pytest.approx(score.pd_final, abs=1e-10, rel=0)
    assert result.theory_certified is False
    assert result.stats["guide_used_for_pruning"] is False
    assert result.stats["guide_used_for_termination"] is False
    assert result.stats["state_merging"] is False
    assert result.stats["bound_is_unweighted"] is True
    if oracle is not None:
        assert result.status == "completed"
        assert result.stop_reason is None
        assert result.J == pytest.approx(oracle.J, abs=1e-10, rel=0)
    assert result.incumbent_history
    previous = float("inf")
    for item in result.incumbent_history:
        replay = score_path(grid, item["path"], **cfg)
        assert item["J"] == pytest.approx(replay.J, abs=1e-10, rel=0)
        assert item["Pd"] == pytest.approx(replay.pd_final, abs=1e-10, rel=0)
        assert item["J"] < previous
        previous = item["J"]
    assert previous == pytest.approx(result.J, abs=1e-10, rel=0)
    return score


@pytest.mark.parametrize("mode", BOUND_MODES)
@pytest.mark.parametrize("guide_weight", [1.04, 100.0])
def test_continues_after_first_goal_and_never_prunes_on_misleading_guide(monkeypatch, mode, guide_weight):
    grid, cfg = simple_case()
    inject_misleading_guide(monkeypatch)
    events = []
    replayed_paths = []
    original_score = anytime_module.score_path

    def recording_score(graph, path, **kwargs):
        replayed_paths.append(tuple(path))
        return original_score(graph, path, **kwargs)

    monkeypatch.setattr(anytime_module, "score_path", recording_score)
    result = anytime_module.search_anytime(grid, **cfg, guide_weight=guide_weight,
                                           bound_mode=mode, trace=events.append)
    oracle = enumerate_oracle(grid, **cfg)
    assert_replayed(grid, cfg, result, oracle=oracle)
    # Hand calculation: visiting 1 first finds costs 1.8 or 1.7; the best
    # route 0->2->3 has M1=.2, M2=.1, J=.3, and Pd=.9.
    assert result.path == (0, 2, 3)
    assert result.J == pytest.approx(0.3, abs=1e-12, rel=0)
    assert result.Pd == pytest.approx(0.9, abs=1e-12, rel=0)
    assert result.incumbent_history[0]["J"] >= 1.7 - 1e-12
    assert len(result.incumbent_history) >= 2
    assert any(event["event"] == "candidate" and event["g"] > result.J + 1.0 for event in events)
    assert any(event["event"] == "pop" and event["depth"] == 1 and event["vertex"] == 2
               for event in events)
    assert all(tuple(item["path"]) in replayed_paths for item in result.incumbent_history)


@pytest.mark.parametrize("mode", BOUND_MODES)
def test_equal_depth_vertex_and_g_keep_different_beliefs(monkeypatch, mode):
    grid = GridGraph(2, 2)
    last = np.eye(4)
    last[2] = [1.0, 0.0, 0.0, 0.0]
    cfg = dict(start=0, budget=3, p=np.array([0.0, 0.5, 0.5, 0.0]), q=1.0,
               motion=MatrixMotion.time_varying([np.eye(4), np.eye(4), last]))
    left_prefix = score_path(grid, (0, 1, 0), **{**cfg, "budget": 2})
    right_prefix = score_path(grid, (0, 2, 0), **{**cfg, "budget": 2})
    assert left_prefix.J == right_prefix.J == 1.0
    assert left_prefix.survival[-1] == right_prefix.survival[-1] == 0.5
    assert not np.array_equal(left_prefix.final_belief, right_prefix.final_belief)
    # P3 sends the surviving cell-2 target into inaccessible cell 0. The
    # surviving cell-1 target remains searchable, so histories are not merged.
    assert score_path(grid, (0, 1, 0, 1), **cfg).J == 1.5
    assert score_path(grid, (0, 2, 0, 1), **cfg).J == 1.0
    inject_misleading_guide(monkeypatch)
    events = []
    result = anytime_module.search_anytime(grid, **cfg, bound_mode=mode, trace=events.append)
    assert_replayed(grid, cfg, result, oracle=enumerate_oracle(grid, **cfg))
    assert result.J == 1.0
    popped = {tuple(event["path"]) for event in events if event["event"] == "pop"}
    assert (0, 1, 0) in popped
    assert (0, 2, 0) in popped


@pytest.mark.parametrize("mode", BOUND_MODES)
def test_original_paper_dynamic_overestimate_is_retained_but_not_used_as_bound(mode):
    fixture = Path(__file__).resolve().parents[1] / "data/fixtures/heuristic_dynamic_counterexample.npz"
    with np.load(fixture, allow_pickle=False) as data:
        cfg = dict(start=int(data["start"]), budget=int(data["T"]),
                   p=data["p"].copy(), q=float(data["q"]),
                   motion=MatrixMotion.time_varying(data["P"]))
    grid = GridGraph(3, 3)
    oracle = enumerate_oracle(grid, **cfg)
    paper = Heuristic(grid, budget=cfg["budget"], q=cfg["q"],
                      motion=cfg["motion"], mode="paper_greedy")
    assert paper(cfg["start"], 0, cfg["p"]) > oracle.J + 0.07
    result = anytime_module.search_anytime(grid, **cfg, guide_weight=1.1, bound_mode=mode)
    assert_replayed(grid, cfg, result, oracle=oracle)


@pytest.mark.parametrize("mode", BOUND_MODES)
@pytest.mark.parametrize("guide_weight", [1.0, 1.04, 1.1])
def test_seed213_real_paper_order_can_improve_beyond_first_goal(mode, guide_weight):
    # Frozen historical regression: the original paper search at epsilon=1
    # returns (0,1,0,1,3), over .01 worse than the exhaustive global optimum.
    grid = GridGraph(2, 2)
    rng = np.random.default_rng(213)
    p = rng.dirichlet(np.full(4, 0.5))
    matrices = rng.dirichlet(np.full(4, 0.4), size=(4, 4))
    cfg = dict(start=0, budget=4, p=p, q=0.78, motion=MatrixMotion.time_varying(matrices))
    initial = (0, 1, 0, 1, 3)
    oracle = enumerate_oracle(grid, **cfg)
    assert score_path(grid, initial, **cfg).J > oracle.J + 0.01
    result = anytime_module.search_anytime(grid, **cfg, initial_path=initial,
                                           bound_mode=mode, guide_weight=guide_weight)
    assert_replayed(grid, cfg, result, oracle=oracle)
    assert tuple(result.incumbent_history[0]["path"]) == initial
    assert len(result.incumbent_history) >= 2


def particle_case():
    grid = GridGraph(2, 2)
    cells = np.array([
        [0, 1, 2, 3, 4, 5, 6, 7],
        [1, 0, 3, 2, 4, 5, 6, 7],
        [2, 3, 0, 1, 4, 5, 6, 7],
        [1, 2, 3, 0, 4, 5, 6, 7],
        [0, 1, 2, 3, 4, 5, 6, 7],
    ])
    cfg = dict(start=0, budget=4, p=np.array([0.1, 0.2, 0.15, 0.05, 0.1, 0.1, 0.2, 0.1]),
               q=np.array([0.0, 0.25, 0.78, 1.0]),
               motion=ParticleMotion(cells, 4, [91, 17, 64, 3, 58, 2, 101, 11]))
    return grid, cfg


@pytest.mark.parametrize("mode", BOUND_MODES)
@pytest.mark.parametrize("q", [0.0, 1.0, np.array([0.0, 0.25, 0.78, 1.0])])
def test_particle_absolute_time_ids_and_special_bins_match_oracle(mode, q):
    grid, cfg = particle_case()
    cfg["q"] = q
    before_p = cfg["p"].copy()
    before_cells = cfg["motion"].cell_ids.copy()
    before_ids = cfg["motion"].trajectory_ids.copy()
    result = anytime_module.search_anytime(grid, **cfg, bound_mode=mode)
    score = assert_replayed(grid, cfg, result, oracle=enumerate_oracle(grid, **cfg))
    assert score.survival[-1] >= cfg["p"][-4:].sum() - 1e-12
    np.testing.assert_array_equal(score.final_belief[-4:], cfg["p"][-4:])
    np.testing.assert_array_equal(cfg["p"], before_p)
    np.testing.assert_array_equal(cfg["motion"].cell_ids, before_cells)
    np.testing.assert_array_equal(cfg["motion"].trajectory_ids, before_ids)


@pytest.mark.parametrize("mode", BOUND_MODES)
@pytest.mark.parametrize("q", [0.0, 1.0, np.array([0.0, 0.25, 0.78, 1.0])])
def test_static_sensor_extremes_and_no_detection(mode, q):
    grid, cfg = simple_case()
    cfg.update(budget=4, q=q)
    result = anytime_module.search_anytime(grid, **cfg, bound_mode=mode)
    score = assert_replayed(grid, cfg, result, oracle=enumerate_oracle(grid, **cfg))
    assert score.g[0] == 0.0
    assert score.survival[0] == pytest.approx(1.0, abs=1e-14, rel=0)
    if np.ndim(q) == 0 and q == 0:
        assert result.J == pytest.approx(4.0, abs=1e-12, rel=0)
        assert result.Pd == pytest.approx(0.0, abs=1e-12, rel=0)


@pytest.mark.parametrize("limit", ["max_expansions", "max_seconds", "max_open"])
def test_zero_budget_preserves_independently_replayed_complete_incumbent(limit):
    grid, cfg = simple_case()
    initial = (0, 1, 0)
    result = anytime_module.search_anytime(grid, **cfg, initial_path=initial, **{limit: 0})
    assert result.status == "budget_exceeded"
    assert result.stop_reason == limit
    assert result.path == initial
    assert_replayed(grid, cfg, result)
    assert result.incumbent_history[0]["source"] == "initial_path"


@pytest.mark.parametrize("limit", ["max_expansions", "max_seconds", "max_open"])
def test_zero_budget_without_incumbent_is_explicit(limit):
    grid, cfg = simple_case()
    result = anytime_module.search_anytime(grid, **cfg, **{limit: 0})
    assert result.status == "budget_exceeded"
    assert result.stop_reason == limit
    assert result.path is None and result.J is None and result.Pd is None
    assert result.incumbent_history == []
    assert result.theory_certified is False


def test_improved_complete_incumbent_survives_deadline_immediately_after_replay(monkeypatch):
    grid, cfg = simple_case()
    initial = (0, 1, 0)
    initial_J = score_path(grid, initial, **cfg).J
    now = [0.0]
    monkeypatch.setattr(anytime_module, "perf_counter", lambda: now[0])
    inject_misleading_guide(monkeypatch)

    def expire_after_improvement(event):
        if (event["event"] == "incumbent"
                and event["incumbent_J"] < initial_J - 1e-12):
            now[0] = 2.0

    result = anytime_module.search_anytime(grid, **cfg, initial_path=initial,
                                           max_seconds=1.0, trace=expire_after_improvement)
    assert result.status == "budget_exceeded"
    assert result.stop_reason == "max_seconds"
    assert result.J < initial_J - 1e-12
    assert_replayed(grid, cfg, result)
    assert len(result.incumbent_history) >= 2
    assert result.incumbent_history[-1]["source"] != "initial_path"


def test_admissible_bound_is_lazy_and_not_evaluated_for_unpopped_nodes():
    grid, cfg = simple_case()
    events = []
    result = anytime_module.search_anytime(grid, **cfg, max_open=1, trace=events.append)
    assert result.status == "budget_exceeded"
    assert result.stop_reason == "max_open"
    assert result.stats["bound_calls"] == 1
    assert result.stats["popped"] == 1
    assert result.stats["guide_calls"] > result.stats["bound_calls"]
    assert [event["path"] for event in events if event["event"] == "pop"] == [(0,)]
    assert result.theory_certified is False


def test_no_observation_at_t0_and_zero_horizon():
    grid = GridGraph(1, 1)
    cfg = dict(start=0, budget=0, p=[1.0], q=1.0, motion=MatrixMotion.identity(1))
    result = anytime_module.search_anytime(grid, **cfg)
    assert result.path == (0,)
    assert result.J == 0.0 and result.Pd == 0.0
    assert_replayed(grid, cfg, result, oracle=enumerate_oracle(grid, **cfg))


@pytest.mark.parametrize("guide_weight", [-1.0, 0.0, 0.99, float("nan"), float("inf")])
def test_invalid_guide_weight_is_rejected(guide_weight):
    grid, cfg = simple_case()
    with pytest.raises(ValueError):
        anytime_module.search_anytime(grid, **cfg, guide_weight=guide_weight)


@pytest.mark.parametrize("mode", ["paper_greedy", "paper_literal_abs_time", "unknown"])
def test_nonadmissible_or_unknown_pruning_mode_is_rejected(mode):
    grid, cfg = simple_case()
    with pytest.raises(ValueError):
        anytime_module.search_anytime(grid, **cfg, bound_mode=mode)


@pytest.mark.parametrize("kwargs", [
    {"max_expansions": -1}, {"max_open": -1}, {"max_seconds": -1.0},
    {"max_seconds": float("nan")}, {"max_seconds": float("inf")},
    {"initial_path": (0, 3, 0)}, {"initial_path": (0, 1)},
])
def test_invalid_limits_or_incumbent_are_rejected(kwargs):
    grid, cfg = simple_case()
    with pytest.raises(ValueError):
        anytime_module.search_anytime(grid, **cfg, **kwargs)
