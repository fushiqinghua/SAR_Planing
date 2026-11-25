"""Resumption preserves exhaustive search, beliefs and pending successors."""
from math import inf
from time import perf_counter

import numpy as np
import pytest

from asar_repro.grid import GridGraph
from asar_repro.heuristic import Heuristic
from asar_repro.motion import MatrixMotion, ParticleMotion
from asar_repro.objective import score_path
from asar_repro.oracle import enumerate_oracle
from asar_repro.research_particle import FutureEquivalentMotion, ParticleGuide
from asar_repro.research_search import search_research
from asar_repro.resumable_search import SearchSession


def case(kind="particle", seed=123):
    grid = GridGraph(2, 3)
    rng = np.random.default_rng(seed)
    budget = 5
    if kind == "particle":
        cells = rng.integers(0, 8, size=(budget+1, 7))
        motion = ParticleMotion(cells, 6, np.arange(7)+30)
        p = rng.dirichlet(np.ones(7))
    else:
        p = rng.dirichlet(np.ones(6))
        motion = (MatrixMotion.identity(6) if kind == "static" else
                  MatrixMotion.time_varying(rng.dirichlet(np.ones(6), size=(budget, 6))))
    return grid, dict(start=0, budget=budget, p=p, q=.78, motion=motion)


def assert_replay(grid, cfg, result):
    if result.path is not None:
        replay = score_path(grid, result.path, **cfg)
        assert result.J == pytest.approx(replay.J, abs=1e-10, rel=0)
        assert result.Pd == pytest.approx(replay.pd_final, abs=1e-10, rel=0)
    assert not result.theory_certified
    assert result.stats["state_merging"] is False
    assert result.stats["guide_used_for_pruning"] is False
    last = inf
    for event in result.incumbent_history:
        replay = score_path(grid, event["path"], **cfg)
        assert event["J"] == pytest.approx(replay.J, abs=1e-10, rel=0)
        assert event["Pd"] == pytest.approx(replay.pd_final, abs=1e-10, rel=0)
        assert event["J"] < last
        last = event["J"]


@pytest.mark.parametrize("kind", ["static", "dynamic", "particle"])
@pytest.mark.parametrize("mode", ["zero", "mass_lb", "stdc_lb"])
@pytest.mark.parametrize("slice_work", [1, 3, 10])
def test_sliced_search_matches_unsliced_and_oracle(kind, mode, slice_work):
    grid, cfg = case(kind)
    whole = SearchSession(grid, **cfg, bound_mode=mode).advance()
    session = SearchSession(grid, **cfg, bound_mode=mode)
    assert session.finish().status == "paused"
    while True:
        before = session.expanded
        result = session.advance(max_expansions=slice_work)
        assert session.expanded-before <= slice_work
        assert_replay(grid, cfg, result)
        if result.status == "completed":
            break
        assert result.status == "paused"
        assert result.stop_reason == "slice_expansions"
        assert result.stats["frontier_remaining"] > 0
    for key in ("path", "J", "Pd", "expanded", "generated", "pruned", "peak_open"):
        assert getattr(result, key) == getattr(whole, key)
    assert result.J == pytest.approx(enumerate_oracle(grid, **cfg).J, abs=1e-10, rel=0)


@pytest.mark.parametrize("kind", ["static", "dynamic", "particle"])
def test_unsliced_matches_existing_reference(kind):
    grid, cfg = case(kind)
    old = search_research(grid, **cfg, bound_mode="stdc_lb")
    new = SearchSession(grid, **cfg).advance()
    for key in ("path", "J", "Pd", "expanded", "generated", "pruned", "peak_open", "status"):
        assert getattr(new, key) == getattr(old, key)


@pytest.mark.parametrize("cap", [0, 1, 3, 10])
def test_global_expansion_cap_is_not_reset_by_resume(cap):
    grid, cfg = case()
    initial = (0, 1, 2, 5, 4, 3)
    session = SearchSession(grid, **cfg, initial_path=initial, max_expansions=cap)
    while session.status not in ("budget_exceeded", "completed"):
        result = session.advance(max_expansions=1)
        assert result.expanded <= cap
        assert_replay(grid, cfg, result)
    if result.status == "completed":
        assert result.stop_reason is None
        assert result.J == pytest.approx(enumerate_oracle(grid, **cfg).J, abs=1e-10)
    else:
        assert result.stop_reason == "max_expansions"
        assert result.stats["frontier_remaining"] > 0
    before = result.expanded, result.generated
    result = session.advance()
    assert before == (result.expanded, result.generated)


@pytest.mark.parametrize("cap", [0, 1, 3])
def test_open_cap_is_explicit_and_retains_unenqueued_child(cap):
    grid, cfg = case()
    session = SearchSession(grid, **cfg, initial_path=(0, 1, 2, 5, 4, 3), max_open=cap)
    result = session.advance()
    assert result.status == "budget_exceeded"
    assert result.stop_reason == "max_open"
    assert result.peak_open <= cap
    assert result.stats["memory"]["held_open_cap_child"]
    assert_replay(grid, cfg, result)


def test_time_slice_keeps_partial_successors(monkeypatch):
    import asar_repro.resumable_search as module
    grid, cfg = case()
    baseline = SearchSession(grid, **cfg).advance()
    clock = [0.]
    monkeypatch.setattr(module, "perf_counter", lambda: clock[0])
    real_guide = ParticleGuide(grid, budget=cfg["budget"], q=cfg["q"], motion=cfg["motion"])
    def costly_guide(*args):
        value = real_guide(*args)
        clock[0] += 1.
        return value
    session = SearchSession(grid, **cfg, guide=costly_guide)
    paused = session.advance(deadline=1.5)
    assert paused.status == "paused"
    assert paused.stop_reason == "slice_seconds"
    assert paused.stats["memory"]["pending_expansion"]
    assert paused.expanded == 1
    assert paused.generated == 1
    result = session.advance()
    for key in ("path", "J", "Pd", "expanded", "generated", "pruned", "peak_open"):
        assert getattr(result, key) == getattr(baseline, key)


def test_time_slice_keeps_popped_bound_checked_node(monkeypatch):
    import asar_repro.resumable_search as module
    grid, cfg = case()
    baseline = SearchSession(grid, **cfg).advance()
    clock = [0.]
    monkeypatch.setattr(module, "perf_counter", lambda: clock[0])
    bound = Heuristic(grid, budget=cfg["budget"], q=cfg["q"], motion=cfg["motion"], mode="stdc_lb")
    def costly_bound(*args):
        value = bound(*args)
        clock[0] += 2.
        return value
    session = SearchSession(grid, **cfg, bound=costly_bound)
    result = session.advance(deadline=1.)
    assert result.status == "paused"
    assert result.expanded == 0
    assert result.stats["memory"]["pending_bound_checked_node"]
    result = session.advance()
    assert result.path == baseline.path
    assert result.J == baseline.J
    assert result.stats["bound_calls"] == baseline.stats["bound_calls"]


def test_global_deadline_stops_without_losing_incumbent():
    grid, cfg = case()
    session = SearchSession(grid, **cfg, initial_path=(0, 1, 2, 5, 4, 3),
                            deadline=perf_counter()-1)
    result = session.advance()
    assert result.status == "budget_exceeded"
    assert result.stop_reason == "max_seconds"
    assert result.expanded == 0
    assert result.stats["frontier_remaining"] == 1
    assert_replay(grid, cfg, result)


def test_external_incumbent_validated_and_does_not_replace_with_worse():
    grid, cfg = case()
    initial = (0, 1, 2, 5, 4, 3)
    oracle = enumerate_oracle(grid, **cfg)
    session = SearchSession(grid, **cfg, initial_path=initial)
    session.advance(max_expansions=1)
    frontier = session.frontier_count
    assert session.inject_incumbent(oracle.path, source="test_local")
    assert session.incumbent_source == "test_local"
    assert session.frontier_count == frontier
    assert not session.inject_incumbent(initial)
    assert not session.inject_incumbent(oracle.path)
    with pytest.raises(ValueError, match="illegal"):
        session.inject_incumbent((0, 5, 2, 5, 4, 3))
    result = session.advance()
    assert result.J == oracle.J
    assert_replay(grid, cfg, result)


def test_external_global_stop_is_explicit():
    grid, cfg = case()
    session = SearchSession(grid, **cfg, initial_path=(0, 1, 2, 5, 4, 3))
    session.advance(max_expansions=1)
    result = session.finish(stop_reason="max_expansions")
    assert result.status == "budget_exceeded"
    assert result.stop_reason == "max_expansions"
    assert result.stats["frontier_remaining"] > 0


def test_phase_open_peak_resets_instead_of_reusing_historical_peak():
    grid, cfg = case()
    cfg["q"] = 0.
    session = SearchSession(grid, **cfg)
    smaller_phase_seen = False
    while session.status != "completed":
        before = len(session.primary)
        result = session.advance(max_expansions=1)
        phase_peak = result.stats["advance_peak_open"]
        assert phase_peak >= max(before, len(session.primary))
        assert phase_peak <= result.peak_open
        smaller_phase_seen |= phase_peak < result.peak_open
    assert smaller_phase_seen


@pytest.mark.parametrize("q", [0., 1.])
def test_no_detection_and_perfect_detection(q):
    grid, cfg = case()
    cfg["q"] = q
    session = SearchSession(grid, **cfg)
    while session.status != "completed":
        result = session.advance(max_expansions=2)
    assert result.J == pytest.approx(enumerate_oracle(grid, **cfg).J, abs=1e-10)
    if q == 0:
        assert result.J == pytest.approx(cfg["budget"])
        assert result.Pd == pytest.approx(0.)
    assert_replay(grid, cfg, result)


def test_zero_horizon_does_not_detect_at_t0():
    grid, cfg = case()
    cfg["budget"] = 0
    result = SearchSession(grid, **cfg).advance()
    assert result.status == "completed"
    assert result.path == (0,)
    assert result.J == 0
    assert result.Pd == pytest.approx(0.)
    assert result.expanded == 0


def test_compressed_motion_replays_original_and_guards_model():
    grid, cfg = case()
    motion = FutureEquivalentMotion(cfg["motion"], cfg["p"])
    packed = dict(cfg, p=motion.initial_weights, motion=motion)
    session = SearchSession(grid, **packed, replay_cfg=cfg)
    result = session.advance()
    assert_replay(grid, cfg, result)
    with pytest.raises(ValueError, match="exact original"):
        SearchSession(grid, **packed, replay_cfg=dict(cfg, q=.1))


def test_supplied_cheap_bound_and_full_bound_remain_oracle_correct():
    grid, cfg = case()
    cheap = Heuristic(grid, budget=cfg["budget"], q=cfg["q"], motion=cfg["motion"], mode="mass_lb")
    session = SearchSession(grid, **cfg, cheap_bound=cheap)
    result = session.advance()
    assert result.J == pytest.approx(enumerate_oracle(grid, **cfg).J, abs=1e-10)
    assert result.stats["cheap_bound_calls"] > 0
    assert_replay(grid, cfg, result)


@pytest.mark.parametrize("bad", [dict(max_expansions=-1), dict(max_open=-1),
    dict(guide_weight=.5), dict(deadline=float("nan")), dict(bound_mode="paper_greedy")])
def test_invalid_configuration_rejected(bad):
    grid, cfg = case()
    with pytest.raises(ValueError):
        SearchSession(grid, **cfg, **bad)

