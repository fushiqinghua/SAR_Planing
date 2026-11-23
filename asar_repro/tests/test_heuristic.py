import numpy as np
import pytest

from asar_repro.grid import GridGraph
from asar_repro.heuristic import MODES, Heuristic
from asar_repro.motion import MatrixMotion
from asar_repro.objective import score_path
from asar_repro.oracle import enumerate_oracle
from asar_repro.search import search_asar


def line_estimator(q, mode):
    return Heuristic(GridGraph(1, 5), budget=3, q=q, motion=MatrixMotion.identity(5), mode=mode)


@pytest.mark.parametrize("mode", MODES)
def test_terminal_is_zero(mode):
    assert line_estimator(.78, mode)(2, 3, np.ones(5) / 10) == 0


@pytest.mark.parametrize("q,expected", [(0, 1.), (1, 0.), (.5, .375), ([0, .5, 0, 0, 0], .375)])
def test_mass_bound_two_steps_with_half_mass(q, expected):
    assert line_estimator(q, "mass_lb")(2, 1, [.5, 0, 0, 0, 0]) == expected


def test_relaxed_choices_anchor_relative_radius_and_leave_input_intact():
    b = np.array([.35, .1, 0., .30, .25])
    choices = []
    h = line_estimator(1, "paper_greedy")(2, 1, b, choices=choices)
    assert choices == [3, 0]  # The simulated jump has distance 3.
    assert h == pytest.approx(.70 + .35)
    absolute_choices = []
    line_estimator(1, "paper_literal_abs_time")(2, 1, b, choices=absolute_choices)
    assert absolute_choices == [0, 3]
    np.testing.assert_array_equal(b, [.35, .1, 0., .30, .25])


def test_argmax_uses_q_and_includes_origin_with_stable_id_ties():
    b = [.0, .5, .25, .25, 0]
    choices = []
    line_estimator([1, .1, 1, 1, 1], "paper_greedy")(2, 2, b, choices=choices)
    assert choices == [2]


def test_motion_uses_absolute_step_on_partial_state():
    grid = GridGraph(1, 2)
    motion = MatrixMotion.time_varying([np.eye(2), [[0, 1], [0, 1]]])
    h = Heuristic(grid, budget=2, q=[0, 1], motion=motion, mode="paper_greedy")
    choices = []
    assert h(0, 1, [.4, 0], choices=choices) == 0
    assert choices == [1]


@pytest.mark.parametrize("dynamic", [False, True])
def test_every_prefix_against_constrained_oracle(dynamic):
    grid = GridGraph(2, 2)
    rng = np.random.default_rng(22)
    motion = (MatrixMotion.time_varying(rng.dirichlet(np.ones(4), size=(3, 4)))
              if dynamic else MatrixMotion.identity(4))
    args = dict(start=0, budget=3, p=[.2, .4, .15, .25], q=.78 if dynamic else 1, motion=motion)
    stack = [(0,)]
    while stack:
        path = stack.pop()
        d = len(path) - 1
        prefix = score_path(grid, path, **{**args, "budget": d})
        exact = enumerate_oracle(grid, **args, prefix=path).J - prefix.J
        for mode in (("zero", "mass_lb") if dynamic else ("zero", "mass_lb", "paper_greedy")):
            estimate = Heuristic(grid, budget=3, q=args["q"], motion=motion, mode=mode)
            assert estimate(path[-1], d, prefix.final_belief) <= exact + 1e-10
        if d < 3:
            stack.extend(path + (u,) for u in grid.neighbors(path[-1]))


@pytest.mark.parametrize("eps", [1, 1.02, 1.1])
@pytest.mark.parametrize("mode", ["zero", "mass_lb", "paper_greedy"])
def test_weighted_scores_bounds_and_reproducible_queue(eps, mode):
    grid = GridGraph(2, 3)
    args = dict(start=1, budget=4, p=np.arange(1, 7) / 21, q=.4, motion=MatrixMotion.identity(6))
    oracle = enumerate_oracle(grid, **args)
    traces = [[], []]
    results = [search_asar(grid, **args, epsilon=eps, heuristic=mode, trace=t.append) for t in traces]
    assert results[0] == results[1] and traces[0] == traces[1]
    assert all(event["f_weighted"] == event["g"] + eps * event["h"] for event in traces[0])
    result = results[0]
    assert result.J == pytest.approx(score_path(grid, result.path, **args).J)
    assert result.J <= eps * oracle.J + 1e-10
    assert result.theory_certified == (mode in ("zero", "mass_lb"))


@pytest.mark.parametrize("eps", [.99, np.inf, np.nan])
def test_invalid_weight(eps):
    with pytest.raises(ValueError, match="epsilon"):
        search_asar(GridGraph(1, 1), start=0, budget=0, p=[1], q=1,
                    motion=MatrixMotion.identity(1), epsilon=eps)
