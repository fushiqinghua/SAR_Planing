"""Free-endpoint tail repair checked with the frozen full-path DFS Oracle."""

import numpy as np
import pytest

import asar_repro.tail_repair as tail_module
from asar_repro.grid import GridGraph
from asar_repro.motion import MatrixMotion, ParticleMotion
from asar_repro.objective import score_path
from asar_repro.oracle import enumerate_oracle
from asar_repro.window_search import solve_window


MODES = ("zero", "mass_lb", "stdc_lb")


def endpoint_case():
    grid = GridGraph(1, 3)
    cfg = dict(start=0, budget=2, p=np.array([0.0, 0.0, 1.0]), q=1.0,
               motion=MatrixMotion.identity(3))
    return grid, cfg, (0, 1, 0)


def assert_result(grid, cfg, initial, result, *, a=None, exact=None):
    score = score_path(grid, result.path, **cfg)
    assert result.J == pytest.approx(score.J, abs=1e-10, rel=0)
    assert result.Pd == pytest.approx(score.pd_final, abs=1e-10, rel=0)
    assert result.J <= score_path(grid, initial, **cfg).J + 1e-10
    assert result.theory_certified is False
    assert result.stats["state_merging"] is False
    assert result.stats["endpoint_free"] is True
    assert result.stats["seed_search_run"] is False
    assert result.stats["bound_is_unweighted"] is True
    assert result.stats["objective"] == "sum M[1:T+1]"
    if a is not None:
        assert result.path[:a+1] == initial[:a+1]
    if exact is not None:
        assert result.status == "completed"
        assert result.stop_reason is None
        assert result.J == pytest.approx(exact.J, abs=1e-10, rel=0)
    assert result.history is result.incumbent_history
    assert result.history[0]["source"] == "initial_path"
    assert tuple(result.history[0]["path"]) == initial
    previous = float("inf")
    for row in result.history:
        replay = score_path(grid, row["path"], **cfg)
        assert row["J"] == pytest.approx(replay.J, abs=1e-10, rel=0)
        assert row["Pd"] == pytest.approx(replay.pd_final, abs=1e-10, rel=0)
        assert row["J"] < previous
        previous = row["J"]
    assert previous == pytest.approx(result.J, abs=1e-10, rel=0)
    assert result.expanded == sum(row["expanded"] for row in result.phases)
    assert result.generated == sum(row["generated"] for row in result.phases)
    assert result.pruned == sum(row["pruned"] for row in result.phases)
    return score


@pytest.mark.parametrize("mode", MODES)
def test_fixed_endpoint_cannot_improve_but_free_endpoint_can(mode):
    grid, cfg, initial = endpoint_case()
    fixed = solve_window(grid, **cfg, path=initial, a=1, b=2, mode="stdc_endpoint_lb")
    assert fixed.path == initial
    assert fixed.J == 2.0 and fixed.Pd == 0.0
    result = tail_module.repair_suffix(grid, **cfg, initial_path=initial, a=1, bound_mode=mode)
    exact = enumerate_oracle(grid, **cfg, prefix=initial[:2])
    assert_result(grid, cfg, initial, result, a=1, exact=exact)
    assert result.path == (0, 1, 2)
    assert result.J == 1.0 and result.Pd == 1.0
    assert result.path[-1] != initial[-1]


@pytest.mark.parametrize("mode", MODES)
def test_prefix_joint_weights_and_cost_are_not_renormalized_or_double_counted(mode):
    grid = GridGraph(1, 3)
    cfg = dict(start=0, budget=4, p=np.array([0.2, 0.3, 0.5]), q=1.0,
               motion=MatrixMotion.identity(3))
    initial = (0, 1, 0, 1, 0)
    prefix = score_path(grid, initial[:3], **{**cfg, "budget": 2})
    assert prefix.J == pytest.approx(1.2, abs=1e-12, rel=0)
    assert prefix.survival[-1] == 0.5
    result = tail_module.repair_suffix(grid, **cfg, initial_path=initial, a=2, bound_mode=mode)
    assert_result(grid, cfg, initial, result, a=2,
                  exact=enumerate_oracle(grid, **cfg, prefix=initial[:3]))
    assert result.path == (0, 1, 0, 1, 2)
    assert result.J == pytest.approx(1.7, abs=1e-12, rel=0)
    assert result.Pd == 1.0


@pytest.mark.parametrize("mode", MODES)
def test_asymmetric_dynamic_tail_uses_absolute_times(monkeypatch, mode):
    grid = GridGraph(2, 2)
    base = np.array([[1, 2, 3, 4], [4, 1, 1, 2], [0, 2, 7, 1], [1, 0, 1, 6]], dtype=float)
    base /= base.sum(axis=1, keepdims=True)
    matrices = [np.roll(np.roll(base, t % 4, axis=0), (2*t+1) % 4, axis=1)
                for t in range(4)]
    motion = MatrixMotion.time_varying(matrices)
    cfg = dict(start=0, budget=4, p=np.array([0.1, 0.2, 0.3, 0.4]),
               q=np.array([0.0, 0.25, 0.6, 1.0]), motion=motion)
    initial = (0, 1, 3, 2, 0)
    exact = enumerate_oracle(grid, **cfg, prefix=initial[:3])
    expected_step = [None]
    expansion_steps = []
    propagate = motion.propagate

    def trace(event):
        if event["event"] == "expand":
            expected_step[0] = event["depth"] + 1

    def checked_propagate(belief, *, step):
        if expected_step[0] is not None:
            assert step == expected_step[0]
            expansion_steps.append(step)
            expected_step[0] = None
        return propagate(belief, step=step)

    monkeypatch.setattr(motion, "propagate", checked_propagate)
    result = tail_module.repair_suffix(grid, **cfg, initial_path=initial, a=2,
                                       bound_mode=mode, trace=trace)
    assert_result(grid, cfg, initial, result, a=2, exact=exact)
    assert expansion_steps and min(expansion_steps) == 3
    assert set(expansion_steps).issubset({3, 4})


def particle_case(q):
    grid = GridGraph(2, 2)
    cells = np.array([
        [0, 1, 2, 3, 4, 5, 6, 7],
        [1, 0, 3, 2, 4, 5, 6, 7],
        [2, 3, 0, 1, 4, 5, 6, 7],
        [1, 2, 3, 0, 4, 5, 6, 7],
        [0, 1, 2, 3, 4, 5, 6, 7],
    ])
    cfg = dict(start=0, budget=4, p=np.array([0.1, 0.2, 0.15, 0.05, 0.1, 0.1, 0.2, 0.1]), q=q,
               motion=ParticleMotion(cells, 4, [91, 17, 64, 3, 58, 2, 101, 11]))
    return grid, cfg, (0, 1, 3, 2, 0)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("q", [0.0, 1.0, np.array([0.0, 0.25, 0.78, 1.0])])
def test_particle_special_mass_absolute_frames_and_id_preservation(mode, q):
    grid, cfg, initial = particle_case(q)
    p_before = cfg["p"].copy()
    cells_before = cfg["motion"].cell_ids.copy()
    ids_before = cfg["motion"].trajectory_ids.copy()
    result = tail_module.repair_suffix(grid, **cfg, initial_path=initial, a=2, bound_mode=mode)
    score = assert_result(grid, cfg, initial, result, a=2,
                          exact=enumerate_oracle(grid, **cfg, prefix=initial[:3]))
    np.testing.assert_array_equal(score.final_belief[-4:], cfg["p"][-4:])
    assert score.survival[-1] >= cfg["p"][-4:].sum() - 1e-12
    np.testing.assert_array_equal(cfg["p"], p_before)
    np.testing.assert_array_equal(cfg["motion"].cell_ids, cells_before)
    np.testing.assert_array_equal(cfg["motion"].trajectory_ids, ids_before)
    if np.ndim(q) == 0 and q == 0:
        assert result.path == initial
        assert result.J == pytest.approx(4.0, abs=1e-12, rel=0)
        assert result.Pd == pytest.approx(0.0, abs=1e-12, rel=0)


def test_original_J_objective_can_accept_lower_Pd_without_new_constraint():
    grid = GridGraph(1, 4)
    cfg = dict(start=1, budget=3, p=[0.45, 0.0, 0.0, 0.55], q=1.0,
               motion=MatrixMotion.identity(4))
    initial = (1, 2, 3, 2)
    old = score_path(grid, initial, **cfg)
    assert old.J == pytest.approx(1.9, abs=1e-12, rel=0)
    assert old.pd_final == pytest.approx(0.55, abs=1e-12, rel=0)
    result = tail_module.repair_suffix(grid, **cfg, initial_path=initial, a=0)
    assert_result(grid, cfg, initial, result, exact=enumerate_oracle(grid, **cfg))
    assert result.J == pytest.approx(1.65, abs=1e-12, rel=0)
    assert result.Pd == pytest.approx(0.45, abs=1e-12, rel=0)
    assert result.J < old.J and result.Pd < old.pd_final


@pytest.mark.parametrize("mode", MODES)
def test_same_depth_vertex_and_cost_histories_are_not_merged(mode):
    grid = GridGraph(2, 2)
    last = np.eye(4)
    last[2] = [1.0, 0.0, 0.0, 0.0]
    cfg = dict(start=0, budget=3, p=[0.0, 0.5, 0.5, 0.0], q=1.0,
               motion=MatrixMotion.time_varying([np.eye(4), np.eye(4), last]))
    initial = (0, 1, 0, 1)
    bad = score_path(grid, (0, 1, 0), **{**cfg, "budget": 2})
    good = score_path(grid, (0, 2, 0), **{**cfg, "budget": 2})
    assert bad.J == good.J == 1.0
    assert not np.array_equal(bad.final_belief, good.final_belief)
    result = tail_module.repair_suffix(grid, **cfg, initial_path=initial, a=0, bound_mode=mode)
    assert_result(grid, cfg, initial, result, exact=enumerate_oracle(grid, **cfg))
    assert result.J == 1.0


@pytest.mark.parametrize("limit", ["max_expansions", "max_seconds", "max_open"])
def test_zero_budget_keeps_original_complete_legal_incumbent(limit):
    grid, cfg, initial = endpoint_case()
    result = tail_module.repair_tail(grid, **cfg, initial_path=initial,
                                     lengths=(1, 2), **{limit: 0})
    assert result.status == "budget_exceeded"
    assert result.stop_reason == limit
    assert result.path == initial
    assert_result(grid, cfg, initial, result)


def test_expansion_budget_is_shared_across_different_tail_lengths():
    grid, cfg, initial = endpoint_case()
    result = tail_module.repair_tail(grid, **cfg, initial_path=initial,
                                     lengths=(1, 2), max_expansions=1)
    assert_result(grid, cfg, initial, result)
    assert result.path == (0, 1, 2)
    assert result.expanded == 1
    assert result.status == "budget_exceeded"
    assert result.stop_reason == "max_expansions"
    assert result.stats["requested_starts"] == [1, 0]
    assert result.stats["completed_phases"] == 1
    assert result.stats["unstarted_phases"] == 1
    assert len(result.phases) == 1 and result.phases[0]["status"] == "completed"


def test_improvement_is_retained_if_deadline_fires_after_candidate_replay(monkeypatch):
    grid, cfg, initial = endpoint_case()
    now = [0.0]
    monkeypatch.setattr(tail_module, "perf_counter", lambda: now[0])

    def trace(event):
        if event["event"] == "incumbent" and event["incumbent_J"] < 2.0:
            now[0] = 2.0

    result = tail_module.repair_tail(grid, **cfg, initial_path=initial,
                                     lengths=(1, 2), max_seconds=1.0, trace=trace)
    assert_result(grid, cfg, initial, result)
    assert result.path == (0, 1, 2)
    assert result.J == 1.0
    assert result.status == "budget_exceeded" and result.stop_reason == "max_seconds"
    assert len(result.history) == 2


def test_each_accepted_full_path_and_final_incumbent_are_independently_replayed(monkeypatch):
    grid, cfg, initial = endpoint_case()
    called = []
    original_score = tail_module.score_path

    def recording_score(graph, path, **kwargs):
        assert kwargs["budget"] == cfg["budget"]
        called.append(tuple(path))
        return original_score(graph, path, **kwargs)

    monkeypatch.setattr(tail_module, "score_path", recording_score)
    result = tail_module.repair_tail(grid, **cfg, initial_path=initial, lengths=(1, 2))
    assert_result(grid, cfg, initial, result, exact=enumerate_oracle(grid, **cfg))
    assert all(tuple(row["path"]) in called for row in result.history)
    assert called[-1] == result.path
    assert result.stats["initial_replays"] == 1
    assert result.stats["final_replays"] == 1
    assert result.stats["candidate_replays"] >= result.stats["accepted_improvements"]
    assert result.stats["phase_replays"] == len(result.phases) == 2


def test_deterministic_variable_lengths_cap_to_horizon_and_deduplicate_actual_window():
    grid, cfg, initial = endpoint_case()
    first = tail_module.repair_tail(grid, **cfg, initial_path=initial, lengths=(1, 2, 8))
    second = tail_module.repair_tail(grid, **cfg, initial_path=initial, lengths=(1, 2, 8))
    assert first.stats["requested_lengths"] == [1, 2, 8]
    assert first.stats["requested_starts"] == [1, 0]
    assert [phase["a"] for phase in first.phases] == [1, 0]
    assert first.path == second.path
    assert (first.expanded, first.generated, first.pruned) == (second.expanded, second.generated, second.pruned)
    assert_result(grid, cfg, initial, first, exact=enumerate_oracle(grid, **cfg))


def test_zero_length_suffix_and_zero_horizon_do_not_observe_at_time_zero():
    grid, cfg, initial = endpoint_case()
    unchanged = tail_module.repair_suffix(grid, **cfg, initial_path=initial, a=cfg["budget"])
    assert unchanged.path == initial and unchanged.expanded == 0
    assert_result(grid, cfg, initial, unchanged)
    single = GridGraph(1, 1)
    zero_cfg = dict(start=0, budget=0, p=[1.0], q=1.0, motion=MatrixMotion.identity(1))
    result = tail_module.repair_tail(single, **zero_cfg, initial_path=(0,))
    assert result.J == 0.0 and result.Pd == 0.0
    assert result.expanded == 0 and result.path == (0,)
    assert_result(single, zero_cfg, (0,), result, exact=enumerate_oracle(single, **zero_cfg))


@pytest.mark.parametrize("kwargs", [
    {"lengths": ()}, {"lengths": (0,)}, {"lengths": (-1,)},
    {"lengths": (True,)}, {"lengths": (1.5,)}, {"lengths": (1, 1)},
    {"bound_mode": "paper_greedy"}, {"bound_mode": "stdc_endpoint_lb"},
    {"max_expansions": -1}, {"max_open": -1},
    {"max_seconds": -1.0}, {"max_seconds": float("nan")},
    {"max_seconds": float("inf")},
])
def test_invalid_settings_are_rejected(kwargs):
    grid, cfg, initial = endpoint_case()
    with pytest.raises(ValueError):
        tail_module.repair_tail(grid, **cfg, initial_path=initial, **kwargs)


@pytest.mark.parametrize("a", [-1, 3])
def test_suffix_start_must_be_absolute_time_in_horizon(a):
    grid, cfg, initial = endpoint_case()
    with pytest.raises(ValueError):
        tail_module.repair_suffix(grid, **cfg, initial_path=initial, a=a)
