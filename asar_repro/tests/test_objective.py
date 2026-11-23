import numpy as np
import pytest
from scipy import sparse

from asar_repro.grid import GridGraph
from asar_repro.motion import MatrixMotion
from asar_repro.objective import score_path


@pytest.mark.parametrize("path,mass,prefix", [
    ([4, 5, 4, 1], [1, 0.3, 0.3, 0], [0, 0.3, 0.6, 0.6]),
    ([4, 1, 4, 5], [1, 0.7, 0.7, 0], [0, 0.7, 1.4, 1.4]),
])
def test_hand_scored_order(path, mass, prefix):
    p = np.zeros(9)
    p[[5, 1]] = [0.7, 0.3]
    score = score_path(GridGraph(3, 3), path, start=4, budget=3, p=p,
                       q=1, motion=MatrixMotion.identity(9))
    np.testing.assert_allclose(score.survival, mass)
    np.testing.assert_allclose(score.g, prefix)
    np.testing.assert_allclose(score.delta_pd, -np.diff(mass))
    assert score.J == pytest.approx(prefix[-1])
    assert score.pd_final == 1


@pytest.mark.parametrize("path", [[0, 1, 0, 2], [0, 2, 3, 1]])
def test_no_detection(path):
    P = np.full((4, 4), 0.25)
    score = score_path(GridGraph(2, 2), path, start=0, budget=3, p=[1, 0, 0, 0],
                       q=0, motion=MatrixMotion.stationary(P))
    np.testing.assert_array_equal(score.survival, np.ones(4))
    np.testing.assert_array_equal(score.delta_pd, np.zeros(3))
    assert score.J == 3
    assert score.pd_final == 0


@pytest.mark.parametrize("q,mass", [(1, [1, 0, 0, 0]), (0.25, [1, 0.75, 0.75, 0.75**2])])
def test_repeated_visits(q, mass):
    score = score_path(GridGraph(1, 2), [0, 1, 0, 1], start=0, budget=3,
                       p=[0, 1], q=q, motion=MatrixMotion.identity(2))
    np.testing.assert_allclose(score.survival, mass)
    assert score.pd_final == pytest.approx(1 - mass[-1])


def test_dynamic_move_then_sense_first_and_last_frame():
    motion = MatrixMotion.time_varying([
        sparse.csr_matrix([[0, 1], [0, 1]]),
        [[1, 0], [0.25, 0.75]],
    ])
    score = score_path(GridGraph(1, 2), [0, 1, 0], start=0, budget=2,
                       p=[1, 0], q=[1, 0.5], motion=motion)
    np.testing.assert_allclose(score.survival, [1, 0.5, 0.375])
    np.testing.assert_allclose(score.delta_pd, [0.5, 0.125])
    np.testing.assert_allclose(score.final_belief, [0, 0.375])
    assert score.J == 0.875
    assert score.pd_final == 0.625


def test_zero_budget_skips_initial_detection():
    score = score_path(GridGraph(1, 1), [0], start=0, budget=0,
                       p=[1], q=1, motion=MatrixMotion.identity(1))
    np.testing.assert_array_equal(score.final_belief, [1])
    assert score.J == score.pd_final == 0
    assert score.delta_pd.size == 0


def test_scorer_checks_all_inputs_even_at_zero_budget():
    for q, n in ((np.nan, 2), (1, 3)):
        with pytest.raises(ValueError):
            score_path(GridGraph(1, 2), [0], start=0, budget=0, p=[1, 0],
                       q=q, motion=MatrixMotion.identity(n))
    with pytest.raises(ValueError):
        score_path(GridGraph(1, 2), [0, 0], start=0, budget=1, p=[1, 0],
                   q=0, motion=MatrixMotion.identity(2))


def test_fixed_seed_mass_and_prefix_invariants():
    rng = np.random.default_rng(7)
    grid = GridGraph(2, 3)
    budget = 8
    matrices = rng.dirichlet(np.ones(grid.size), size=(budget, grid.size))
    p = rng.dirichlet(np.ones(grid.size))
    q = rng.uniform(size=grid.size)
    path = [0, 1, 4, 5, 2, 1, 0, 3, 4]
    score = score_path(grid, path, start=0, budget=budget, p=p, q=q,
                       motion=MatrixMotion.time_varying(matrices))

    # Independent reference: split each source mass across destinations.
    # Accumulate removed mass directly to check the survival-difference result.
    b = p.copy()
    prefix_cost = 0.0
    for t, dest in enumerate(path[1:], 1):
        prior = sum(b[u] * matrices[t - 1, u] for u in range(grid.size))
        np.testing.assert_allclose(prior.sum(), b.sum(), atol=1e-14, rtol=0)
        removed = q[dest] * prior[dest]
        b = prior.copy()
        b[dest] -= removed
        prefix_cost += b.sum()
        np.testing.assert_allclose(
            [score.delta_pd[t - 1], score.survival[t], score.g[t]],
            [removed, b.sum(), prefix_cost], atol=1e-14, rtol=0,
        )
    assert np.all(np.diff(score.survival) <= 1e-14)
    assert np.all((score.survival >= 0) & (score.survival <= 1 + 1e-14))
    np.testing.assert_allclose(score.final_belief, b, atol=1e-14, rtol=0)
    assert score.pd_final == pytest.approx(score.delta_pd.sum(), abs=1e-14)
