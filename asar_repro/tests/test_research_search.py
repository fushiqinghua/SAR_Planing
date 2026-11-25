"""Research integration: exact guide, budgets, replay and diagnostic archive."""
import numpy as np
import pytest

from asar_repro.anytime_search import search_anytime
from asar_repro.grid import GridGraph
from asar_repro.motion import MatrixMotion, ParticleMotion
from asar_repro.objective import score_path
from asar_repro.oracle import enumerate_oracle
from asar_repro.research_particle import FutureEquivalentMotion
from asar_repro.research_search import search_research


def case(kind):
    grid = GridGraph(2, 2)
    rng = np.random.default_rng(213)
    p = rng.dirichlet(np.full(4, .5))
    motion = MatrixMotion.time_varying(rng.dirichlet(np.full(4, .4), size=(4, 4)))
    if kind == "static":
        motion = MatrixMotion.identity(4)
    if kind == "particle":
        cells = np.array([[0, 0, 4, 5], [1, 1, 4, 2], [3, 3, 0, 5],
                          [2, 2, 4, 1], [0, 0, 3, 5]])
        motion = ParticleMotion(cells, 4, [33, 91, 72, 45])
    return grid, dict(start=0, budget=4, p=p, q=.78, motion=motion)


def check(grid, cfg, result):
    replay = score_path(grid, result.path, **cfg)
    assert result.J == pytest.approx(replay.J, abs=1e-10, rel=0)
    assert result.Pd == pytest.approx(replay.pd_final, abs=1e-10, rel=0)
    assert not result.theory_certified
    assert not result.stats["state_merging"]
    assert not result.stats["guide_used_for_pruning"]
    previous = float("inf")
    for event in result.incumbent_history:
        r = score_path(grid, event["path"], **cfg)
        assert r.J == pytest.approx(event["J"], abs=1e-10)
        assert r.pd_final == pytest.approx(event["Pd"], abs=1e-10)
        assert event["J"] < previous
        previous = event["J"]
    for a in result.candidate_archive:
        r = score_path(grid, a["path"], **cfg)
        assert r.J == pytest.approx(a["J"], abs=1e-10)
        assert r.pd_final == pytest.approx(a["Pd"], abs=1e-10)
        assert not any(b is not a and b["J"] <= a["J"] and b["Pd"] >= a["Pd"]
                       for b in result.candidate_archive)


@pytest.mark.parametrize("kind", ["static", "dynamic", "particle"])
@pytest.mark.parametrize("mode", ["zero", "mass_lb", "stdc_lb", "lookahead"])
@pytest.mark.parametrize("portfolio", [False, True])
def test_global_oracle_and_replay(kind, mode, portfolio):
    grid, cfg = case(kind)
    result = search_research(grid, **cfg, bound_mode=mode, portfolio=portfolio,
                             cascade=True, initial_path=(0, 1, 0, 1, 3))
    check(grid, cfg, result)
    assert result.status == "completed"
    assert result.J == pytest.approx(enumerate_oracle(grid, **cfg).J, abs=1e-10, rel=0)


@pytest.mark.parametrize("kind", ["static", "dynamic", "particle"])
@pytest.mark.parametrize("mode", ["zero", "mass_lb", "stdc_lb"])
def test_fast_guide_preserves_reference_search(kind, mode):
    grid, cfg = case(kind)
    old = search_anytime(grid, **cfg, bound_mode=mode)
    new = search_research(grid, **cfg, bound_mode=mode, archive_candidates=False)
    for attr in ("path", "J", "Pd", "expanded", "generated", "pruned", "peak_open", "status"):
        assert getattr(new, attr) == getattr(old, attr)


@pytest.mark.parametrize("cap", [0, 1, 3, 10, 30])
def test_lookahead_work_is_not_free(cap):
    grid, cfg = case("dynamic")
    result = search_research(grid, **cfg, bound_mode="lookahead", max_expansions=cap,
                             initial_path=(0, 1, 0, 1, 3))
    check(grid, cfg, result)
    assert result.stats["work_expanded"] <= cap
    assert result.stats["work_expanded"] == result.expanded+result.stats["aux_expanded"]
    if result.status == "budget_exceeded":
        assert result.stop_reason == "max_expansions"


@pytest.mark.parametrize("limits", [dict(max_seconds=0), dict(max_open=0), dict(max_open=1)])
def test_portfolio_physical_open_and_time_are_global(limits):
    grid, cfg = case("particle")
    result = search_research(grid, **cfg, portfolio=True, initial_path=(0, 1, 0, 1, 3), **limits)
    check(grid, cfg, result)
    assert result.status == "budget_exceeded"
    assert result.stop_reason in limits
    if "max_open" in limits:
        assert result.peak_open <= limits["max_open"]


def test_compressed_search_uses_original_replay():
    grid, cfg = case("particle")
    motion = FutureEquivalentMotion(cfg["motion"], cfg["p"])
    compressed = dict(cfg, motion=motion, p=motion.initial_weights)
    result = search_research(grid, **compressed, replay_cfg=cfg)
    check(grid, cfg, result)
    assert motion.state_size < cfg["motion"].state_size
    assert result.J == pytest.approx(enumerate_oracle(grid, **cfg).J, abs=1e-10)


@pytest.mark.parametrize("change", ["q", "budget", "motion", "p"])
def test_replay_guard_rejects_different_model(change):
    grid,cfg=case("particle")
    motion=FutureEquivalentMotion(cfg["motion"],cfg["p"])
    replay=dict(cfg)
    replay[change]={"q":.2,"budget":3,"motion":MatrixMotion.identity(4),
                    "p":np.ones(4)/4}[change]
    with pytest.raises(ValueError,match="exact original"):
        search_research(grid,**dict(cfg,motion=motion,p=motion.initial_weights),replay_cfg=replay)


@pytest.mark.parametrize("mode", ["zero", "stdc_lb", "lookahead"])
def test_no_detection_and_t0(mode):
    grid, cfg = case("particle")
    cfg["q"] = 0.
    result = search_research(grid, **cfg, bound_mode=mode)
    check(grid, cfg, result)
    assert result.J == pytest.approx(4.)
    assert result.Pd == pytest.approx(0.)


def test_original_dynamic_counterexample():
    from pathlib import Path
    from asar_repro.heuristic import Heuristic
    path = Path(__file__).resolve().parents[1]/"data/fixtures/heuristic_dynamic_counterexample.npz"
    with np.load(path) as d:
        cfg = dict(start=int(d["start"]), budget=int(d["T"]), p=d["p"], q=float(d["q"]),
                   motion=MatrixMotion.time_varying(d["P"]))
    grid = GridGraph(3, 3)
    oracle = enumerate_oracle(grid, **cfg)
    assert Heuristic(grid, budget=cfg["budget"], q=cfg["q"], motion=cfg["motion"],
                     mode="paper_greedy")(cfg["start"], 0, cfg["p"]) > oracle.J+.07
    result = search_research(grid, **cfg, bound_mode="lookahead", portfolio=True)
    check(grid, cfg, result)
    assert result.J == pytest.approx(oracle.J, abs=1e-10)
