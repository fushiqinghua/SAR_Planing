"""Midpoint proposals: independent full replay, Oracle and budget checks."""

import numpy as np
import pytest

import asar_repro.midpoint_rollout as midpoint
from asar_repro.grid import GridGraph
from asar_repro.heuristic import Heuristic
from asar_repro.motion import MatrixMotion, ParticleMotion
from asar_repro.objective import score_path
from asar_repro.oracle import enumerate_oracle
from asar_repro.research_particle import FutureEquivalentMotion
from asar_repro.tail_repair import repair_suffix


def middle_case():
    grid = GridGraph(1, 4)
    cfg = dict(start=0, budget=4, p=np.array([0.0, 0.0, 0.0, 1.0]), q=1.0,
               motion=MatrixMotion.identity(4))
    return grid, cfg, (0, 1, 0, 1, 0)


def assert_replay(grid, cfg, initial, result):
    score = score_path(grid, result.path, **cfg)
    assert result.J == pytest.approx(score.J, abs=1e-10, rel=0)
    assert result.Pd == pytest.approx(score.pd_final, abs=1e-10, rel=0)
    assert result.J <= score_path(grid, initial, **cfg).J+1e-10
    assert result.theory_certified is False
    assert result.stats["state_merging"] is False
    assert result.stats["guide_used_for_pruning"] is False
    assert result.stats["guide_used_for_termination"] is False
    assert result.stats["bound_is_unweighted"] is True
    assert result.stats["seed_search_run"] is False
    assert result.expanded == sum(a["expanded"] for a in result.anchors)
    assert result.generated == sum(a["generated"] for a in result.anchors)
    assert result.pruned == sum(a["pruned"] for a in result.anchors)
    assert result.stats["beam_discarded"] == sum(a["beam_discarded"] for a in result.anchors)
    assert result.stats["physical_frontier_remaining"] == sum(a["frontier_remaining"] for a in result.anchors)
    assert result.history is result.incumbent_history
    previous = float("inf")
    for item in result.incumbent_history:
        replay = score_path(grid, item["path"], **cfg)
        assert item["J"] == pytest.approx(replay.J, abs=1e-10, rel=0)
        assert item["Pd"] == pytest.approx(replay.pd_final, abs=1e-10, rel=0)
        assert item["J"] < previous
        previous = item["J"]
    assert previous == pytest.approx(result.J, abs=1e-10, rel=0)
    return score


def test_middle_rewrite_improves_when_last_step_repair_cannot():
    grid, cfg, initial = middle_case()
    tail = repair_suffix(grid, **cfg, initial_path=initial, a=3)
    assert tail.J == 4.0
    result = midpoint.search_midpoint(grid, **cfg, initial_path=initial,
                                      anchor_depths=(1,), beam_width=24)
    assert_replay(grid, cfg, initial, result)
    assert result.path == (0, 1, 2, 3, 2)
    assert result.path[:2] == initial[:2]
    assert result.J == 2.0 and result.Pd == 1.0
    assert result.status == "completed"


def test_diversity_keeps_different_detectable_beliefs_not_just_directions(monkeypatch):
    grid = GridGraph(2, 2)
    last = np.eye(4)
    last[2] = [1.0, 0.0, 0.0, 0.0]
    cfg = dict(start=0, budget=3, p=[0.0, 0.5, 0.5, 0.0], q=1.0,
               motion=MatrixMotion.time_varying([np.eye(4), np.eye(4), last]))
    initial = (0, 1, 0, 1)

    class MisleadingGuide:
        def __init__(self, *args, **kwargs):
            pass

        def __call__(self, vertex, depth, belief):
            return 100.0 if depth == 2 and belief[1] > 0 else 0.0

    monkeypatch.setattr(midpoint, "ParticleGuide", MisleadingGuide)
    common = dict(initial_path=initial, anchor_depths=(0,), beam_width=2, bound_mode="zero")
    quality = midpoint.search_midpoint(grid, **cfg, **common, diversity=False)
    diverse = midpoint.search_midpoint(grid, **cfg, **common, diversity=True)
    assert_replay(grid, cfg, initial, quality)
    assert_replay(grid, cfg, initial, diverse)
    assert quality.J == 1.5
    assert diverse.J == 1.0
    assert diverse.J == enumerate_oracle(grid, **cfg).J
    assert diverse.stats["diversity_selections_outside_quality_beam"] >= 1
    assert quality.stats["beam_discarded"] == diverse.stats["beam_discarded"] == 2
    assert quality.expanded == diverse.expanded


def test_particle_diversity_key_excludes_permanent_special_but_allows_reentry():
    grid = GridGraph(1, 3)
    cells = np.array([[0, 3, 4], [1, 3, 4], [2, 3, 2]])
    motion = ParticleMotion(cells, 3, [31, 91, 7])
    weights = np.array([0.05, 0.8, 0.15])
    keys = midpoint._FutureDetectable(grid, budget=2, q=[0.0, 1.0, 1.0], motion=motion)
    np.testing.assert_array_equal(keys.eligible(0, 0), [True, False, True])
    assert keys.representative(0, 0, weights) == 2
    assert keys.representative(2, 1, weights) == -1  # No waiting: cell 2 cannot be visited in one move.
    zeros = midpoint._FutureDetectable(grid, budget=2, q=0.0, motion=motion)
    assert zeros.representative(0, 0, weights) == -1
    np.testing.assert_array_equal(weights, [0.05, 0.8, 0.15])
    np.testing.assert_array_equal(motion.cell_ids, cells)


def test_matrix_diversity_key_uses_future_positive_transition_support():
    grid = GridGraph(1, 3)
    matrix = np.eye(3)
    matrix[2] = [0.0, 1.0, 0.0]
    keys = midpoint._FutureDetectable(grid, budget=1, q=[0.0, 1.0, 0.0],
                                     motion=MatrixMotion.stationary(matrix))
    np.testing.assert_array_equal(keys.eligible(0, 0), [False, True, True])
    assert keys.representative(0, 0, np.array([0.7, 0.1, 0.2])) == 2


def toy_case(kind):
    grid = GridGraph(2, 2)
    rng = np.random.default_rng(213)
    p = rng.dirichlet(np.full(4, 0.5))
    motion = MatrixMotion.time_varying(rng.dirichlet(np.full(4, 0.4), size=(4, 4)))
    if kind == "static":
        motion = MatrixMotion.identity(4)
    elif kind == "particle":
        cells = np.array([[0, 1, 4, 5], [1, 2, 4, 5], [3, 3, 4, 1],
                          [2, 1, 4, 0], [0, 2, 4, 5]])
        motion = ParticleMotion(cells, 4, [91, 5, 72, 34])
    return grid, dict(start=0, budget=4, p=p, q=[0.2, 0.78, 1.0, 0.4], motion=motion), (0, 1, 0, 1, 3)


@pytest.mark.parametrize("kind", ["static", "dynamic", "particle"])
@pytest.mark.parametrize("mode", ["zero", "stdc_lb"])
@pytest.mark.parametrize("diversity", [False, True])
def test_wide_beam_without_discard_matches_independent_global_oracle(kind, mode, diversity):
    grid, cfg, initial = toy_case(kind)
    p_before = cfg["p"].copy()
    result = midpoint.search_midpoint(grid, **cfg, initial_path=initial, anchor_depths=(0,),
                                      beam_width=1000, diversity=diversity, bound_mode=mode)
    assert_replay(grid, cfg, initial, result)
    assert result.status == "completed"
    assert result.stats["beam_discarded"] == 0
    assert result.J == pytest.approx(enumerate_oracle(grid, **cfg).J, abs=1e-10, rel=0)
    np.testing.assert_array_equal(cfg["p"], p_before)
    if kind == "particle":
        score = score_path(grid, result.path, **cfg)
        assert score.final_belief[2] == cfg["p"][2]


def test_custom_bound_receives_absolute_depth_and_unnormalised_prefix():
    grid, cfg, initial = toy_case("dynamic")
    estimate = Heuristic(grid, budget=cfg["budget"], q=cfg["q"], motion=cfg["motion"], mode="stdc_lb")
    calls = []

    def bound(vertex, depth, belief):
        calls.append((vertex, depth, belief.copy()))
        return estimate(vertex, depth, belief)

    result = midpoint.search_midpoint(grid, **cfg, initial_path=initial, anchor_depths=(2,),
                                      beam_width=100, bound=bound, bound_mode="stdc_dp")
    prefix = score_path(grid, initial[:3], **{**cfg, "budget": 2})
    assert calls[0][1] == 2
    np.testing.assert_array_equal(calls[0][2], prefix.final_belief)
    assert calls[0][2].sum() < 1.0
    assert all(depth in (2, 3) for _, depth, _ in calls)
    assert_replay(grid, cfg, initial, result)
    assert result.J == pytest.approx(enumerate_oracle(grid, **cfg, prefix=initial[:3]).J, abs=1e-10, rel=0)


def test_auto_anchors_are_detected_mass_quantiles_not_fixed_real_times():
    grid = GridGraph(1, 4)
    cfg = dict(start=0, budget=3, p=[0.0, 0.2, 0.3, 0.5], q=1.0, motion=MatrixMotion.identity(4))
    initial = (0, 1, 2, 3)
    result = midpoint.search_midpoint(grid, **cfg, initial_path=initial, max_expansions=0)
    assert result.stats["anchor_depths"] == [1, 2]
    assert [r["event_depth"] for r in result.stats["anchor_selection"]] == [2, 2, 3]
    assert [r["fraction"] for r in result.stats["anchor_selection"]] == [0.25, 0.5, 0.75]
    cfg["q"] = 0.0
    result = midpoint.search_midpoint(grid, **cfg, initial_path=initial, max_expansions=0)
    assert result.stats["anchor_depths"] == [0]


def test_anchors_share_expansion_budget_and_advance_round_robin():
    grid, cfg, initial = toy_case("static")
    cfg["q"] = 0.0
    result = midpoint.search_midpoint(grid, **cfg, initial_path=initial, anchor_depths=(0, 2),
                                      beam_width=1, max_expansions=2)
    assert_replay(grid, cfg, initial, result)
    assert result.status == "budget_exceeded" and result.stop_reason == "max_expansions"
    assert result.expanded == 2
    assert [task["expanded"] for task in result.anchors] == [1, 1]


def test_open_budget_counts_other_anchor_and_next_layer_buffers():
    grid, cfg, initial = toy_case("static")
    cfg["q"] = 0.0
    result = midpoint.search_midpoint(grid, **cfg, initial_path=initial, anchor_depths=(0, 2),
                                      beam_width=24, max_open=2)
    assert_replay(grid, cfg, initial, result)
    assert result.status == "budget_exceeded" and result.stop_reason == "max_open"
    assert result.peak_open == 2
    assert result.expanded == 1


@pytest.mark.parametrize("limit", ["max_expansions", "max_seconds", "max_open"])
def test_zero_budgets_keep_complete_initial_incumbent(limit):
    grid, cfg, initial = middle_case()
    result = midpoint.search_midpoint(grid, **cfg, initial_path=initial,
                                      anchor_depths=(1,), **{limit: 0})
    assert_replay(grid, cfg, initial, result)
    assert result.path == initial
    assert result.status == "budget_exceeded" and result.stop_reason == limit


def test_deadline_after_accepted_candidate_retains_route_and_marks_anchor_interrupted(monkeypatch):
    grid = GridGraph(1, 3)
    cfg = dict(start=0, budget=2, p=[0.0, 0.0, 1.0], q=1.0, motion=MatrixMotion.identity(3))
    initial = (0, 1, 0)
    now = [0.0]
    monkeypatch.setattr(midpoint, "perf_counter", lambda: now[0])

    def trace(event):
        if event["event"] == "incumbent" and event["incumbent_J"] < 2.0:
            now[0] = 2.0

    result = midpoint.search_midpoint(grid, **cfg, initial_path=initial, anchor_depths=(1,),
                                      max_seconds=1.0, trace=trace)
    assert_replay(grid, cfg, initial, result)
    assert result.path == (0, 1, 2) and result.J == 1.0
    assert result.status == "budget_exceeded" and result.stop_reason == "max_seconds"
    assert result.anchors[0]["frontier_remaining"] == 0
    assert result.anchors[0]["status"] == "budget_exceeded"
    assert result.anchors[0]["stop_reason"] == "max_seconds"


def compressed_case():
    grid = GridGraph(2, 2)
    cells = np.tile([2, 2, 4, 5], (5, 1))
    cfg = dict(start=0, budget=4, p=np.array([0.3, 0.2, 0.2, 0.3]), q=0.78,
               motion=ParticleMotion(cells, 4, [17, 93, 62, 8]))
    motion = FutureEquivalentMotion(cfg["motion"], cfg["p"])
    return grid, cfg, dict(cfg, p=motion.initial_weights, motion=motion), (0, 1, 0, 1, 0)


def test_compressed_accepted_and_final_paths_use_original_id_scorer(monkeypatch):
    grid, cfg, compressed, initial = compressed_case()
    observed = []
    scorer = midpoint.score_path

    def record(graph, path, **kwargs):
        observed.append((tuple(path), kwargs["motion"]))
        return scorer(graph, path, **kwargs)

    monkeypatch.setattr(midpoint, "score_path", record)
    result = midpoint.search_midpoint(grid, **compressed, initial_path=initial,
                                      anchor_depths=(0,), beam_width=100, replay_cfg=cfg)
    assert_replay(grid, cfg, initial, result)
    assert result.J < 4.0
    assert result.J == pytest.approx(enumerate_oracle(grid, **cfg).J, abs=1e-10, rel=0)
    assert observed[0][1] is cfg["motion"] and observed[-1][1] is cfg["motion"]
    assert sum(m is compressed["motion"] for _, m in observed) == 1
    assert all(any(path == tuple(event["path"]) and motion is cfg["motion"] for path, motion in observed)
               for event in result.history)


@pytest.mark.parametrize("change", ["omitted", "q", "budget", "p", "motion"])
def test_compression_replay_guard_rejects_model_changes(change):
    grid, cfg, compressed, initial = compressed_case()
    replay = dict(cfg)
    if change == "omitted":
        replay = None
    else:
        replay[change] = {"q": 0.2, "budget": 3, "p": np.ones(4)/4,
                          "motion": MatrixMotion.identity(4)}[change]
    with pytest.raises(ValueError):
        midpoint.search_midpoint(grid, **compressed, initial_path=initial, replay_cfg=replay)


def test_zero_width_is_explicit_greedy_control_and_zero_horizon_has_no_observation():
    grid, cfg, initial = middle_case()
    zero = midpoint.search_midpoint(grid, **cfg, initial_path=initial, anchor_depths=(1,), beam_width=0)
    one = midpoint.search_midpoint(grid, **cfg, initial_path=initial, anchor_depths=(1,), beam_width=1,
                                   diversity=False)
    assert zero.path == one.path and zero.J == one.J
    assert zero.stats["effective_beam_width"] == 1 and zero.stats["diversity"] is False
    singleton = GridGraph(1, 1)
    result = midpoint.search_midpoint(singleton, start=0, budget=0, p=[1.0], q=1.0,
                                      motion=MatrixMotion.identity(1), initial_path=(0,))
    assert result.status == "completed" and result.path == (0,)
    assert result.J == 0.0 and result.Pd == 0.0


@pytest.mark.parametrize("kwargs", [
    {"beam_width": -1}, {"beam_width": True}, {"diversity": 1},
    {"anchor_depths": ()}, {"anchor_depths": (-1,)}, {"anchor_depths": (5,)},
    {"anchor_depths": (1, 1)}, {"bound_mode": "paper_greedy"}, {"bound": 1.0},
    {"guide_weight": 0.9}, {"guide_weight": float("inf")},
    {"max_expansions": -1}, {"max_open": -1}, {"max_seconds": -1},
])
def test_invalid_configuration_is_rejected(kwargs):
    grid, cfg, initial = middle_case()
    with pytest.raises(ValueError):
        midpoint.search_midpoint(grid, **cfg, initial_path=initial, **kwargs)
