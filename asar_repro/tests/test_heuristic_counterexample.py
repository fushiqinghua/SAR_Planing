from pathlib import Path

import numpy as np

from asar_repro.grid import GridGraph
from asar_repro.heuristic import Heuristic
from asar_repro.motion import MatrixMotion
from asar_repro.oracle import enumerate_oracle
from asar_repro.search import search_asar


def test_frozen_appendix_b_witness():
    fixture = Path(__file__).resolve().parents[1] / "data/fixtures/heuristic_dynamic_counterexample.npz"
    grid = GridGraph(3, 3)
    with np.load(fixture, allow_pickle=False) as data:
        P, p = data["P"], data["p"]
        assert P.shape == (4, 9, 9) and p.shape == (9,)
        assert tuple(int(data[k]) for k in ("seed", "trial", "T", "start")) == (5, 35, 4, 4)
        assert float(data["q"]) == .78
    for u in range(grid.size):
        allowed = {u, *grid.neighbors(u)}
        assert all(v in allowed for v in np.nonzero(P[:, u, :])[1])
    motion = MatrixMotion.time_varying(P)
    args = dict(start=4, budget=4, p=p, q=.78, motion=motion)
    exact = enumerate_oracle(grid, **args)
    assert exact.complete_paths == 96
    paper = Heuristic(grid, budget=4, q=.78, motion=motion, mode="paper_greedy")
    h = paper(4, 0, p)
    np.testing.assert_allclose([h, exact.J, h - exact.J],
                               [2.6170801771, 2.5417333379, .0753468392], atol=1e-10, rtol=0)
    assert h > exact.J
    for eps in (1, 1.02, 1.1):
        for mode in ("zero", "mass_lb", "paper_greedy"):
            result = search_asar(grid, **args, heuristic=mode, epsilon=eps)
            if mode == "paper_greedy":
                assert not result.theory_certified
            else:
                assert result.theory_certified and result.J <= eps * exact.J + 1e-10


def test_additional_dynamic_example_can_return_suboptimal_path_at_epsilon_one():
    grid = GridGraph(2, 2)
    rng = np.random.default_rng(213)
    p = rng.dirichlet(np.full(4, 0.5))
    P = rng.dirichlet(np.full(4, 0.4), size=(4, 4))
    args = dict(start=0, budget=4, p=p, q=.78, motion=MatrixMotion.time_varying(P))
    oracle = enumerate_oracle(grid, **args)
    result = search_asar(grid, **args, heuristic="paper_greedy", epsilon=1)
    assert result.path == (0, 1, 0, 1, 3)
    assert oracle.path == (0, 2, 0, 1, 3)
    assert result.J > oracle.J + .01
    assert not result.theory_certified
