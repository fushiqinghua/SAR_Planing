import numpy as np
import pytest

from asar_repro.grid import GridGraph
from asar_repro.heuristic import Heuristic
from asar_repro.motion import MatrixMotion, ParticleMotion
from asar_repro.objective import score_path
from asar_repro.oracle import enumerate_oracle
from asar_repro.search import search_asar


@pytest.mark.parametrize("mode", ["zero", "mass_lb", "paper_greedy"])
@pytest.mark.parametrize("eps", [1, 1.1])
def test_eight_particles_vs_matrix_and_dfs(mode, eps):
    grid = GridGraph(2, 2)
    # Deterministic local permutations; all particles starting in a cell share its motion.
    cells = [np.repeat(np.arange(4), 2)]
    matrices = []
    for perm in ([1, 0, 3, 2], [2, 3, 0, 1], [0, 1, 2, 3], [1, 0, 3, 2]):
        matrices.append(np.eye(4)[perm])
        cells.append(np.asarray(perm)[cells[-1]])
    w = np.array([1, 1, 2, 4, 4, 4, 8, 8]) / 32
    args = dict(start=0, budget=4, q=[.25, .5, .75, 1])
    particle = dict(**args, p=w, motion=ParticleMotion(cells, 4, np.arange(8)[::-1]))
    matrix = dict(**args, p=np.bincount(cells[0], weights=w), motion=MatrixMotion.time_varying(matrices))
    a, b = (enumerate_oracle(grid, **kw) for kw in (particle, matrix))
    assert a.complete_paths == b.complete_paths == 16
    assert a.J == b.J and a.tied_paths == b.tied_paths
    u, v = (search_asar(grid, **kw, heuristic=mode, epsilon=eps) for kw in (particle, matrix))
    assert u.path == v.path and u.J == v.J
    assert u.status == "completed" and u.J <= eps * a.J
    replay = score_path(grid, u.path, **matrix)
    np.testing.assert_allclose(score_path(grid, u.path, **particle).survival, replay.survival)
    assert u.J == replay.J


def test_particle_identity_and_special_cells_survive_a_split():
    cells = np.array([[0, 1, 3], [1, 1, 2], [0, 1, 0]])
    motion = ParticleMotion(cells, 2, [72, 4, 20])
    cells[:] = 0
    assert not motion.cell_ids.flags.writeable
    p = np.array([.5, .25, .25])
    grid = GridGraph(1, 2)
    score = score_path(grid, [0, 1, 0], start=0, budget=2, q=.5, motion=motion, p=p)
    np.testing.assert_allclose(score.final_belief, [.125, .125, .125])
    np.testing.assert_allclose(score.survival, [1, .625, .375])
    choices = []
    h = Heuristic(grid, budget=2, q=.5, motion=motion, mode="paper_greedy")
    assert h(0, 0, p, choices=choices) == 1 and choices == [1, 0]
    np.testing.assert_array_equal(p, [.5, .25, .25])
    with pytest.raises(ValueError, match="frames"):
        search_asar(grid, start=0, budget=3, q=.5, motion=motion, p=p)


@pytest.mark.parametrize("limit", ["max_open", "max_expansions", "max_seconds"])
@pytest.mark.parametrize("warm", [False, True])
def test_stop_reports_incumbent_or_no_path(limit, warm):
    grid = GridGraph(2, 2)
    path = (0, 1, 0) if warm else None
    result = search_asar(grid, start=0, budget=2, q=0, p=[1, 0, 0, 0],
                         motion=MatrixMotion.identity(4), initial_path=path, **{limit: 0})
    assert (result.status, result.stop_reason, result.path) == ("budget_exceeded", limit, path)
    assert result.J == (2 if warm else None)
    assert not result.theory_certified


def test_new_goal_survives_open_limit_without_initial_solution():
    r = search_asar(GridGraph(2, 2), start=0, budget=1, q=1, p=[0, .25, .75, 0],
                    motion=MatrixMotion.identity(4), max_open=1)
    assert r.path == (0, 2) and r.J == .25 and r.peak_open == 1
    assert r.stop_reason == "max_open" and r.incumbent_source == "search"
