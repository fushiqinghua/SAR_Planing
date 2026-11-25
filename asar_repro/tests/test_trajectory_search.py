"""DP-bound integration against unchanged exhaustive truth and heap controls."""

from types import SimpleNamespace

import numpy as np
import pytest

import asar_repro.trajectory_search as trajectory
from asar_repro.grid import GridGraph
from asar_repro.motion import ParticleMotion
from asar_repro.objective import score_path
from asar_repro.oracle import enumerate_oracle
from asar_repro.particle_dp import ParticleDP
from asar_repro.research_particle import FutureEquivalentMotion
from asar_repro.research_search import search_research
from asar_repro.trajectory_search import search_trajectory


MODES = ("stdc_lb", "dp_only", "stdc_dp")


def case(dynamic=True):
    grid = GridGraph(2, 2)
    cells = np.array([[0, 0, 2, 4, 5], [1, 1, 3, 4, 0],
                      [3, 3, 1, 2, 5], [2, 2, 4, 1, 5], [0, 0, 3, 4, 2]])
    if not dynamic:
        cells[:] = cells[0]
    return grid, dict(start=0, budget=4, p=np.array([.1, .2, .3, .25, .15]),
        q=.78, motion=ParticleMotion(cells, 4, [11, 22, 33, 44, 55]))


def check(grid, cfg, result):
    assert result.theory_certified is False
    assert not result.stats["state_merging"]
    assert not result.stats["guide_used_for_pruning"]
    assert not result.stats["guide_used_for_termination"]
    assert result.stats["bound_is_unweighted"]
    assert result.stats["work_expanded"] == result.expanded
    if result.path is not None:
        score = score_path(grid, result.path, **cfg)
        assert abs(score.J-result.J) <= 1e-10
        assert abs(score.pd_final-result.Pd) <= 1e-10
    previous = float("inf")
    for event in result.incumbent_history:
        score = score_path(grid, event["path"], **cfg)
        assert abs(score.J-event["J"]) <= 1e-10
        assert abs(score.pd_final-event["Pd"]) <= 1e-10
        assert event["J"] < previous
        previous = event["J"]
    for event in result.candidate_archive:
        score = score_path(grid, event["path"], **cfg)
        assert abs(score.J-event["J"]) <= 1e-10
        assert abs(score.pd_final-event["Pd"]) <= 1e-10


@pytest.mark.parametrize("dynamic", (False, True))
@pytest.mark.parametrize("q", (0., .78, (.2, .7, 1., .4)))
@pytest.mark.parametrize("mode", MODES)
def test_complete_particle_search_matches_independent_oracle(dynamic, q, mode):
    grid, cfg = case(dynamic)
    cfg["q"] = q
    before = (cfg["p"].copy(), cfg["motion"].cell_ids.copy(), np.asarray(q).copy())
    result = search_trajectory(grid, **cfg, bound_mode=mode, initial_path=(0, 1, 0, 1, 3))
    check(grid, cfg, result)
    assert result.status == "completed"
    assert result.completion_reason == "frontier_exhausted_at_tolerance"
    assert abs(result.J-enumerate_oracle(grid, **cfg).J) <= 1e-10
    assert result.stats["dp_calls"] == (0 if mode == "stdc_lb" else result.stats["bound_calls"])
    assert result.stats["stdc_calls"] == (0 if mode == "dp_only" else result.stats["bound_calls"])
    if mode != "stdc_lb":
        assert result.stats["dp_ready"] and result.stats["dp_build_wall_s"] >= 0
        assert result.wall_s >= result.stats["dp_build_wall_s"]
    if np.all(np.asarray(q) == 0):
        assert abs(result.J-4.) <= 1e-10 and abs(result.Pd) <= 1e-10
    np.testing.assert_array_equal(cfg["p"], before[0])
    np.testing.assert_array_equal(cfg["motion"].cell_ids, before[1])
    np.testing.assert_array_equal(np.asarray(q), before[2])


@pytest.mark.parametrize("dynamic", (False, True))
@pytest.mark.parametrize("cap", (None, 5))
@pytest.mark.parametrize("archive", (False, True))
def test_stdc_control_preserves_frozen_heap_path_counts_and_status(dynamic, cap, archive):
    grid, cfg = case(dynamic)
    options = dict(initial_path=(0, 1, 0, 1, 3), max_expansions=cap,
                   archive_candidates=archive, bound_mode="stdc_lb")
    old = search_research(grid, **cfg, **options)
    new = search_trajectory(grid, **cfg, **options)
    for name in ("path", "J", "Pd", "expanded", "generated", "pruned", "peak_open", "status", "stop_reason"):
        assert getattr(new, name) == getattr(old, name), name
    for name in ("guide_calls", "bound_calls", "complete_candidates", "candidate_replays",
                 "accepted_improvements", "bound_pruned", "cheap_pruned", "popped"):
        assert new.stats[name] == old.stats[name], name
    check(grid, cfg, new)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("limit", ({"max_seconds": 0}, {"max_expansions": 0}, {"max_open": 0}))
def test_zero_budget_keeps_provided_incumbent_and_reports_exact_cause(mode, limit):
    grid, cfg = case()
    initial = (0, 1, 0, 1, 3)
    result = search_trajectory(grid, **cfg, bound_mode=mode, initial_path=initial, **limit)
    check(grid, cfg, result)
    assert result.status == "budget_exceeded" and result.stop_reason in limit
    assert result.path == initial and result.incumbent_source == "initial_path"
    assert result.expanded == 0 and result.completion_reason is None
    if "max_seconds" in limit:
        assert result.stats["dp_build_wall_s"] == 0 and result.peak_open == 0


@pytest.mark.parametrize("mode", MODES)
def test_misleading_nonadmissible_guide_does_not_prune_or_stop_at_first_goal(monkeypatch, mode):
    grid = GridGraph(2, 2)
    cfg = dict(start=0, budget=2, p=np.array([0., .1, .8, .1]), q=1.,
               motion=ParticleMotion(np.array([[0, 1, 2, 3]]*3), 4, [1, 2, 3, 4]))
    def misleading(vertex, depth, belief):
        return 1e6 if depth == 1 and vertex == 2 else 0.
    monkeypatch.setattr(trajectory, "ParticleGuide", lambda *a, **k: misleading)
    result = search_trajectory(grid, **cfg, bound_mode=mode, guide_weight=100.)
    check(grid, cfg, result)
    assert result.incumbent_history[0]["J"] >= 1.7-1e-10
    assert result.path == (0, 2, 3)
    assert abs(result.J-.3) <= 1e-10 and abs(result.Pd-.9) <= 1e-10


@pytest.mark.parametrize("mode", MODES)
def test_equal_depth_vertex_and_cost_do_not_merge_different_particle_histories(monkeypatch, mode):
    grid = GridGraph(2, 2)
    cfg = dict(start=0, budget=3, p=np.array([.5, .5]), q=1.,
               motion=ParticleMotion(np.array([[1, 2], [1, 2], [1, 2], [1, 0]]), 4, [7, 8]))
    monkeypatch.setattr(trajectory, "ParticleGuide", lambda *a, **k:
        lambda vertex, depth, belief: 1e6 if depth == 1 and vertex == 2 else 0.)
    left = score_path(grid, (0, 1, 0), **dict(cfg, budget=2))
    right = score_path(grid, (0, 2, 0), **dict(cfg, budget=2))
    assert left.J == right.J == 1.
    assert not np.array_equal(left.final_belief, right.final_belief)
    result = search_trajectory(grid, **cfg, bound_mode=mode)
    check(grid, cfg, result)
    assert result.status == "completed" and abs(result.J-1.) <= 1e-10


@pytest.mark.parametrize("mode", ("dp_only", "stdc_dp"))
def test_prebuilt_dp_matches_automatic_and_records_external_preprocessing(mode):
    grid, cfg = case()
    dp = ParticleDP(grid, budget=cfg["budget"], q=cfg["q"], motion=cfg["motion"])
    prebuilt = search_trajectory(grid, **cfg, dp=dp, bound_mode=mode)
    automatic = search_trajectory(grid, **cfg, bound_mode=mode)
    for key in ("path", "J", "Pd", "expanded", "generated", "pruned", "peak_open"):
        assert getattr(prebuilt, key) == getattr(automatic, key)
    assert prebuilt.stats["dp_prebuilt"] and prebuilt.stats["dp_build_wall_s"] == 0
    assert "external invocation" in prebuilt.stats["preprocessing_scope"]
    assert not automatic.stats["dp_prebuilt"]


@pytest.mark.parametrize("change", ("q", "budget", "motion", "grid", "unready", "type"))
def test_prebuilt_dp_must_be_ready_and_match_exact_context(change):
    grid, cfg = case()
    dp_options = dict(budget=cfg["budget"], q=cfg["q"], motion=cfg["motion"])
    other_grid = grid
    if change == "q":
        dp_options["q"] = .1
    elif change == "budget":
        dp_options["budget"] = 3
    elif change == "motion":
        dp_options["motion"] = ParticleMotion(cfg["motion"].cell_ids, 4, cfg["motion"].trajectory_ids)
    elif change == "grid":
        other_grid = GridGraph(1, 4)
    elif change == "unready":
        dp_options["max_seconds"] = 0
    dp = object() if change == "type" else ParticleDP(other_grid, **dp_options)
    with pytest.raises(ValueError):
        search_trajectory(grid, **cfg, dp=dp, bound_mode="stdc_dp")


@pytest.mark.parametrize("mode", ("dp_only", "stdc_dp"))
def test_invalid_dp_values_are_not_hidden_by_maximum(monkeypatch, mode):
    grid, cfg = case()
    dp = ParticleDP(grid, budget=cfg["budget"], q=cfg["q"], motion=cfg["motion"])
    monkeypatch.setattr(ParticleDP, "__call__", lambda *a, **k: np.nan)
    with pytest.raises(ValueError, match="invalid particle DP"):
        search_trajectory(grid, **cfg, dp=dp, bound_mode=mode)


def test_interrupted_automatic_preprocessing_keeps_complete_initial_route(monkeypatch):
    grid, cfg = case()
    initial = (0, 1, 0, 1, 3)
    captured = {}
    def incomplete(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(ready=False, stop_reason="max_seconds", build_info={"wall_s": .01})
    monkeypatch.setattr(trajectory, "ParticleDP", incomplete)
    result = search_trajectory(grid, **cfg, initial_path=initial, max_seconds=10)
    check(grid, cfg, result)
    assert "deadline" in captured
    assert result.status == "budget_exceeded" and result.stop_reason == "max_seconds"
    assert result.path == initial and result.expanded == result.generated == 0
    assert not result.stats["dp_ready"]


@pytest.mark.parametrize("mode", MODES)
def test_compressed_search_replays_original_trajectory_ids(mode):
    grid, cfg = case()
    grouped = FutureEquivalentMotion(cfg["motion"], cfg["p"])
    assert grouped.state_size < cfg["motion"].state_size
    result = search_trajectory(grid, **dict(cfg, motion=grouped, p=grouped.initial_weights),
                               bound_mode=mode, replay_cfg=cfg)
    check(grid, cfg, result)
    assert abs(result.J-enumerate_oracle(grid, **cfg).J) <= 1e-10


@pytest.mark.parametrize("change", ("q", "budget", "motion", "p"))
def test_replay_guard_rejects_altered_original_model(change):
    grid, cfg = case()
    grouped = FutureEquivalentMotion(cfg["motion"], cfg["p"])
    replay = dict(cfg)
    replay[change] = {"q": .2, "budget": 3, "motion": grouped, "p": np.ones(5)/5}[change]
    with pytest.raises(ValueError, match="exact original"):
        search_trajectory(grid, **dict(cfg, motion=grouped, p=grouped.initial_weights), replay_cfg=replay)


@pytest.mark.parametrize("mode", MODES)
def test_zero_horizon_skips_dp_and_returns_unsensed_root(mode):
    grid, cfg = case()
    cfg["budget"] = 0
    result = search_trajectory(grid, **cfg, bound_mode=mode)
    check(grid, cfg, result)
    assert result.path == (0,) and result.J == 0.0 and abs(result.Pd) <= 1e-10
    assert result.expanded == result.stats["dp_calls"] == 0
    assert result.stats["dp_build_wall_s"] == 0.0


def test_deadline_after_new_complete_candidate_keeps_its_replayed_improvement(monkeypatch):
    grid = GridGraph(2, 2)
    cfg = dict(start=0, budget=2, p=np.array([0., .1, .8, .1]), q=1.,
               motion=ParticleMotion(np.array([[0, 1, 2, 3]]*3), 4, [1, 2, 3, 4]))
    initial = (0, 1, 0)
    initial_j = score_path(grid, initial, **cfg).J
    clock = [0.]
    monkeypatch.setattr(trajectory, "perf_counter", lambda: clock[0])
    original = trajectory.score_path
    def replay_then_timeout(*args, **kwargs):
        result = original(*args, **kwargs)
        if result.J < initial_j-1e-10:
            clock[0] = 2.
        return result
    monkeypatch.setattr(trajectory, "score_path", replay_then_timeout)
    result = search_trajectory(grid, **cfg, bound_mode="stdc_lb", initial_path=initial, max_seconds=1.)
    assert result.status == "budget_exceeded" and result.stop_reason == "max_seconds"
    assert result.J < initial_j-1e-10 and result.incumbent_source == "search"
    check(grid, cfg, result)


VARIANTS = ("paper_baseline", "prior_stdc", "compressed_stdc", "dp_only",
            "stdc_dp", "mid_plain", "mid_diverse", "mid_dp")


@pytest.mark.parametrize("variant", VARIANTS)
def test_common_invoke_shares_seed_rollout_expansion_and_open_caps(variant):
    from run_trajectory_experiments import invoke
    grid, cfg = case()
    initial = (0, 1, 0, 1, 3)
    limits = dict(max_expansions=7, max_open=32, max_seconds=20.)
    result, phases, preprocessing, elapsed = invoke(grid, cfg, initial, variant, limits)
    work = getattr(result, "stats", {}).get("work_expanded", result.expanded)
    assert 0 <= work <= limits["max_expansions"]
    assert result.peak_open <= limits["max_open"]
    assert elapsed >= 0 and result.path is not None
    replay = score_path(grid, result.path, **cfg)
    assert abs(replay.J-result.J) <= 1e-10
    if variant.startswith("mid_"):
        assert len(phases) == 2
        assert phases[0]["limits"]["max_expansions"] == 2
        used = [phase["result"]["stats"]["work_expanded"] for phase in phases]
        assert work == sum(used)
        assert phases[1]["limits"]["max_expansions"] == limits["max_expansions"]-used[0]
    if "dp" in preprocessing:
        assert preprocessing["dp"]["wall_s"] <= elapsed


@pytest.mark.parametrize("variant", VARIANTS)
def test_common_invoke_zero_time_retains_same_frozen_pt(variant):
    from run_trajectory_experiments import invoke
    grid, cfg = case()
    initial = (0, 1, 0, 1, 3)
    truth = score_path(grid, initial, **cfg)
    result, phases, preprocessing, elapsed = invoke(grid, cfg, initial, variant,
        dict(max_expansions=100, max_open=32, max_seconds=0.))
    assert result.status == "budget_exceeded" and result.stop_reason
    assert result.path == initial and abs(result.J-truth.J) <= 1e-10
    assert result.expanded == 0
    assert getattr(result, "stats", {}).get("work_expanded", 0) == 0
    assert elapsed >= 0
    if hasattr(result, "Pd"):
        assert abs(result.Pd-truth.pd_final) <= 1e-10


@pytest.mark.parametrize("variant", VARIANTS)
def test_common_invoke_outputs_and_histories_replay_original_particle_archive(variant):
    from run_trajectory_experiments import invoke
    grid, cfg = case()
    result, phases, preprocessing, elapsed = invoke(grid, cfg, (0, 1, 0, 1, 3), variant,
        dict(max_expansions=100, max_open=128, max_seconds=20.))
    replay = score_path(grid, result.path, **cfg)
    assert abs(replay.J-result.J) <= 1e-10 and not result.theory_certified
    if hasattr(result, "Pd"):
        assert abs(replay.pd_final-result.Pd) <= 1e-10
    if "compression" in preprocessing:
        compression = preprocessing["compression"]
        assert compression["original_trajectory_ids"] == cfg["motion"].trajectory_ids.tolist()
        assert sorted(i for group in compression["groups"] for i in group) == list(range(5))
        assert len(compression["groups"]) < 5
    previous = float("inf")
    for event in getattr(result, "incumbent_history", []):
        independent = score_path(grid, event["path"], **cfg)
        assert abs(independent.J-event["J"]) <= 1e-10
        assert abs(independent.pd_final-event["Pd"]) <= 1e-10
        assert event["J"] < previous-1e-10
        assert 0 <= event["elapsed_s"] <= elapsed+.01
        previous = event["J"]
