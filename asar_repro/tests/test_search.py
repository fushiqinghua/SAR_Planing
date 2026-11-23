import numpy as np
import pytest

from asar_repro.grid import GridGraph
from asar_repro.motion import MatrixMotion
from asar_repro.objective import score_path
from asar_repro.oracle import enumerate_oracle
from asar_repro.search import search_zero


@pytest.mark.parametrize("prune", [False, True])
def test_higher_prefix_cost_can_win_at_same_vertex_and_depth(prune):
    grid = GridGraph(3, 3)
    parameters = dict(start=0, p=np.array([8, 2, 1, 1, 0, 0, 8, 8, 1]) / 29,
                      q=1, motion=MatrixMotion.identity(9))
    winning_prefix = (0, 1, 0, 3, 6)
    other_prefix = (0, 3, 6, 7, 6)
    a = score_path(grid, winning_prefix, budget=4, **parameters)
    b = score_path(grid, other_prefix, budget=4, **parameters)
    np.testing.assert_allclose([a.J, b.J], [74 / 29, 72 / 29])
    assert not np.array_equal(a.final_belief, b.final_belief)
    assert min(score_path(grid, other_prefix + (v,), budget=5, **parameters).J
               for v in grid.neighbors(6)) == pytest.approx(84 / 29)
    oracle = enumerate_oracle(grid, budget=5, **parameters)
    search = search_zero(grid, budget=5, prune=prune, **parameters)
    assert oracle.tied_paths == (winning_prefix + (7,),)
    assert search.path == oracle.path
    assert search.J == pytest.approx(76 / 29)


@pytest.mark.parametrize("size,T", [(2, 5), (3, 4), (4, 4)])
@pytest.mark.parametrize("dynamic", [False, True], ids=["static", "time_varying"])
def test_heap_variants_vs_exhaustion(size, T, dynamic):
    grid = GridGraph(size, size)
    rng = np.random.default_rng(211 + size)
    n = grid.size
    p, q = rng.dirichlet(np.ones(n)), rng.uniform(size=n)
    motion = (MatrixMotion.time_varying(rng.dirichlet(np.ones(n), size=(T, n)))
              if dynamic else MatrixMotion.identity(n))
    args = dict(start=size + 1, budget=T, p=p, q=q, motion=motion)
    oracle = enumerate_oracle(grid, **args)
    for prune in (False, True):
        result = search_zero(grid, **args, prune=prune)
        replay = score_path(grid, result.path, **args)
        assert result.path in oracle.tied_paths
        assert abs(result.J - oracle.J) <= 1e-10
        assert abs(result.J - replay.J) <= 1e-10


def test_pruning_reduces_frontier_when_all_goals_tie():
    grid = GridGraph(2, 2)
    args = dict(start=0, budget=4, p=[1, 0, 0, 0], q=0, motion=MatrixMotion.identity(4))
    reference = search_zero(grid, **args)
    bounded = search_zero(grid, **args, prune=True)
    assert reference.J == bounded.J == 4
    assert reference.path == bounded.path
    assert reference.expanded == bounded.expanded == 15
    assert reference.generated == bounded.generated == 30
    assert reference.pruned == 0 and bounded.pruned == 15
    assert bounded.peak_open < reference.peak_open


def test_sub_tolerance_improvement_replaces_first_generated_goal():
    grid = GridGraph(2, 2)
    args = dict(start=0, budget=1, p=[0, 0.5 - 2e-13, 0.5 + 2e-13, 0],
                q=1, motion=MatrixMotion.identity(4))
    oracle = enumerate_oracle(grid, **args, tie_atol=0)
    for prune in (False, True):
        result = search_zero(grid, **args, prune=prune)
        assert result.path == oracle.path == (0, 2)
        assert result.J == oracle.J < 0.5


@pytest.mark.parametrize("solver", [enumerate_oracle, search_zero])
def test_zero_budget_and_unreachable_positive_budget(solver):
    grid = GridGraph(1, 1)
    args = dict(start=0, p=[1], q=1, motion=MatrixMotion.identity(1))
    result = solver(grid, budget=0, **args)
    assert result.path == (0,) and result.J == 0
    assert result.expanded == result.generated == 0
    assert result.peak_open == 1
    with pytest.raises(ValueError, match="no feasible path"):
        solver(grid, budget=1, **args)
