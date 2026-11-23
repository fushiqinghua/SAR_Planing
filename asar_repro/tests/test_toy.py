from collections import Counter
from pathlib import Path

import numpy as np
import pytest
import yaml

from asar_repro.grid import GridGraph
from asar_repro.motion import MatrixMotion
from asar_repro.objective import score_path
from asar_repro.search import search_asar
from asar_repro.toy import baseline_path, order_control, toy_problem


def config(name):
    filename = Path(__file__).resolve().parents[1] / "configs" / f"toy_{name}.yaml"
    return yaml.safe_load(filename.read_text(encoding="utf-8"))


def test_common_prior_is_seeded_and_normalized():
    static, dynamic = config("static"), config("dynamic")
    _, a = toy_problem(static)
    _, b = toy_problem(dynamic)
    np.testing.assert_array_equal(a["p"], b["p"])
    assert np.all(a["p"] > 0) and a["p"].sum() == pytest.approx(1)
    _, other = toy_problem({**static, "seed": 42})
    assert not np.array_equal(a["p"], other["p"])


def test_drift_clock_and_boundary_preserve_local_mass():
    grid, args = toy_problem(config("dynamic"))
    b = np.zeros(grid.size)
    b[0] = 1
    for t, expected in [(1, [.71, .22, .07]), (15, [.71, .22, .07]),
                        (16, [.75, .05, .20]), (30, [.75, .05, .20])]:
        prior = args["motion"].propagate(b, step=t)
        assert np.flatnonzero(prior).tolist() == [0, 1, 7]
        np.testing.assert_allclose(prior[[0, 1, 7]], expected)
        assert prior.sum() == pytest.approx(1)


@pytest.mark.parametrize("target,expected_turn", [(0, 2), (8, 8)])
def test_dynamic_serpentine_selects_adjacent_row_by_prior(target, expected_turn):
    grid = GridGraph(3, 3)
    p = np.zeros(9)
    p[target] = 1
    path = baseline_path(grid, start=3, budget=3, p=p, q=1, motion=MatrixMotion.identity(9),
                         method="serpentine")
    assert path == (3, 4, 5, expected_turn)


def test_greedy_uses_next_step_prior_and_only_adjacent_cells():
    grid = GridGraph(2, 2)
    P = np.tile([0, .1, .2, .7], (4, 1))
    path = baseline_path(grid, start=0, budget=1, p=[0, 1, 0, 0], q=1,
                         motion=MatrixMotion.stationary(P), method="greedy")
    assert path == (0, 2)


@pytest.mark.parametrize("scenario", ["static", "dynamic"])
def test_all_three_methods_share_replay_and_budget(scenario):
    cfg = config(scenario)
    grid, args = toy_problem(cfg)
    search = search_asar(grid, **args, **cfg["asar"])
    paths = {k: baseline_path(grid, **args, method=k) for k in ("greedy", "serpentine")}
    paths["asar"] = search.path
    for method, path in paths.items():
        grid.validate_path(path, start=args["start"], budget=30)
        assert len(path) == 31
        s = score_path(grid, path, **args, record_beliefs=True)
        assert s.beliefs.shape == (31, 49)
        np.testing.assert_array_equal(s.beliefs[0], args["p"])
        np.testing.assert_allclose(s.beliefs.sum(axis=1), s.survival)
        np.testing.assert_allclose(s.g[1:], s.survival[1:].cumsum())
        assert np.all(np.diff(s.survival) <= 1e-12)
        assert s.pd_final == pytest.approx(s.delta_pd.sum())
        if scenario == "static":
            for t, v in enumerate(path[1:], 1):
                assert s.beliefs[t, v] == 0
                assert np.all(s.beliefs[t] <= s.beliefs[t-1])
        if method == "asar":
            assert search.J == pytest.approx(s.J)
            assert not search.theory_certified


def test_same_visits_and_tail_different_truncated_cost():
    grid, args = toy_problem(config("static"))
    snake = baseline_path(grid, **args, method="serpentine")
    paths, reunion = order_control(grid, snake)
    east, north = paths["east_first"], paths["north_first"]
    assert Counter(east) == Counter(north) and east[reunion:] == north[reunion:]
    a, b = [score_path(grid, path, **args, record_beliefs=True) for path in (east, north)]
    np.testing.assert_array_equal(a.beliefs[reunion:], b.beliefs[reunion:])
    assert a.pd_final == b.pd_final
    assert a.J < b.J - 1e-6
    assert b.J - a.J == pytest.approx(np.sum(b.survival[1:reunion] - a.survival[1:reunion]))
