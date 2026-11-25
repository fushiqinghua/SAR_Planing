"""Independent diagnostic tests: original DFS truth and original path replay."""

from dataclasses import asdict
import json
from types import SimpleNamespace

import numpy as np
import pytest
from scipy import sparse

import asar_repro.particle_diagnostic as diagnostic
from asar_repro.grid import GridGraph
from asar_repro.motion import MatrixMotion, ParticleMotion
from asar_repro.objective import score_path
from asar_repro.oracle import enumerate_oracle
from asar_repro.particle_diagnostic import solve_diagnostic
from asar_repro.research_particle import FutureEquivalentMotion


def fixture(dynamic=True):
    grid = GridGraph(2, 2)
    cells = np.array([[0, 1, 2, 3, 4], [3, 2, 1, 0, 4],
                      [2, 1, 3, 4, 1], [1, 3, 4, 2, 0]])
    if not dynamic:
        cells[:] = cells[0]
    p = np.array([.1, .2, .25, .15, .3])
    return grid, p, ParticleMotion(cells, 4, [11, 22, 33, 44, 55])


Q_CASES = (0.0, .78, 1.0, (.1, .3, .7, 1.0))


@pytest.mark.parametrize("method", ("lp", "milp"))
@pytest.mark.parametrize("dynamic", (False, True))
@pytest.mark.parametrize("q", Q_CASES)
def test_independent_small_oracle_bounds_and_complete_replay(method, dynamic, q):
    grid, p, motion = fixture(dynamic)
    truth = enumerate_oracle(grid, start=0, budget=3, p=p, q=q, motion=motion)
    before = (p.copy(), np.asarray(q).copy(), motion.cell_ids.copy())
    result = solve_diagnostic(grid, start=0, budget=3, p=p, q=q, motion=motion,
                              method=method, initial_path=truth.path, max_seconds=10)
    assert result.status == "completed", result
    assert result.lower_bound <= truth.J + 1e-10
    assert abs(result.J-truth.J) <= 1e-8
    assert result.gap >= 0 and not result.theory_certified
    replay = score_path(grid, result.path, start=0, budget=3, p=p, q=q, motion=motion)
    assert replay.J == result.J and replay.pd_final == result.Pd
    assert result.metadata["lp_primal_used_as_lower_bound"] is False
    assert result.model_size["particles"] == 5
    if method == "lp":
        assert result.dual_verification["verified"]
        assert result.lower_bound_source == "verified_box_corrected_lp_dual"
        assert result.lower_bound <= result.solver_primal_objective + 1e-10
    else:
        assert abs(result.metadata["milp_replayed_J"]-truth.J) <= 1e-8
        assert abs(result.solver_primal_objective-truth.J) <= 1e-8
        assert result.solver_dual_bound_estimate is not None
    np.testing.assert_array_equal(p, before[0])
    np.testing.assert_array_equal(np.asarray(q), before[1])
    np.testing.assert_array_equal(motion.cell_ids, before[2])
    json.dumps(asdict(result), allow_nan=False)


@pytest.mark.parametrize("prefix", ((0,), (0, 1), (0, 2, 3)))
@pytest.mark.parametrize("method", ("lp", "milp"))
def test_prefix_uses_absolute_archive_clock_and_original_big_m(prefix, method):
    grid, p, motion = fixture()
    q = (.2, .8, 1., .4)
    truth = enumerate_oracle(grid, start=0, budget=3, p=p, q=q, motion=motion, prefix=prefix)
    result = solve_diagnostic(grid, start=0, budget=3, p=p, q=q, motion=motion,
        method=method, prefix_path=prefix, initial_path=truth.path, max_seconds=10)
    assert result.status == "completed"
    assert result.lower_bound <= truth.J + 1e-10
    assert abs(result.J-truth.J) <= 1e-8
    assert result.model_size["absolute_depth"] == len(prefix)-1
    assert result.model_size["remaining_steps"] == 4-len(prefix)
    assert result.metadata["fixed_original_big_m"] is True
    prefix_score = score_path(grid, prefix, start=0, budget=len(prefix)-1, p=p, q=q, motion=motion)
    assert result.lower_bound >= prefix_score.J


@pytest.mark.parametrize("method", ("lp", "milp"))
def test_hand_calculated_no_detection_t0_and_no_wait(method):
    grid = GridGraph(1, 2)
    motion = ParticleMotion(np.array([[0], [0]]), 2, [87])
    result = solve_diagnostic(grid, start=0, budget=1, p=[1.], q=1., motion=motion,
        method=method, initial_path=(0, 1), max_seconds=10)
    assert result.J == 1.0 and result.Pd == 0.0  # No t=0 observation; waiting forbidden.
    assert abs(result.lower_bound-1.0) < 1e-10 if method == "lp" else result.lower_bound == 0.0
    zero = solve_diagnostic(grid, start=0, budget=0, p=[1.], q=1., motion=motion,
                            method=method, max_seconds=10)
    assert zero.path == (0,) and zero.J == zero.Pd == zero.lower_bound == 0.0
    assert zero.incumbent_source == "terminal_prefix"


@pytest.mark.parametrize("method", ("lp", "milp"))
def test_special_mass_returns_and_compressed_candidate_replays_original_ids(method):
    grid = GridGraph(1, 2)
    motion = ParticleMotion(np.array([[2, 2, 3], [2, 2, 3], [1, 1, 3]]), 2, [10, 20, 30])
    grouped = FutureEquivalentMotion(motion, [.2, .3, .5])
    result = solve_diagnostic(grid, start=1, budget=2, p=grouped.initial_weights,
        q=[0., 1.], motion=grouped, method=method, initial_path=(1, 0, 1), max_seconds=10)
    assert result.J == 1.5 and result.Pd == .5
    assert result.model_size["particles"] == 2
    assert result.metadata["original_archive_replay_count"] >= 2
    assert result.lower_bound <= 1.5 + 1e-10
    if method == "lp":
        assert abs(result.lower_bound-1.5) < 1e-10


def tiny_model(*, inequality=False):
    return diagnostic._Model(np.array([1.]),
        sparse.csr_matrix([[-1.]]) if inequality else sparse.csr_matrix((0, 1)),
        np.array([-.4]) if inequality else np.array([]),
        sparse.csr_matrix((0, 1)) if inequality else sparse.csr_matrix([[1.]]),
        np.array([]) if inequality else np.array([.4]), np.array([1.]), np.array([0.]),
        np.array([0]), 0, {})


def test_dual_residual_correction_prevents_infeasible_dual_overclaim():
    model = tiny_model()
    # eta=2 has uncorrected objective .8 > true minimum .4; box residual is -1.
    bound, report = diagnostic._verified_dual_bound(model, [2.], [])
    assert bound <= -.2 + 1e-15
    assert report["verified"] and report["box_correction_lower"] <= -1.
    exact, _ = diagnostic._verified_dual_bound(model, [1.], [])
    assert exact <= .4 and abs(exact-.4) < 1e-14


def test_dual_wrong_sign_is_projected_and_nonfinite_is_rejected():
    model = tiny_model(inequality=True)
    lower, report = diagnostic._verified_dual_bound(model, [], [100.])
    assert lower <= 0 and report["inequality_sign_projection"] == 100.
    exact, _ = diagnostic._verified_dual_bound(model, [], [-1.])
    assert exact <= .4 and abs(exact-.4) < 1e-14
    with pytest.raises(ValueError, match="nonfinite"):
        diagnostic._verified_dual_bound(model, [], [np.nan])


def test_lp_primal_objective_never_becomes_a_lower_bound(monkeypatch):
    original = diagnostic.linprog

    def fake(*args, **kwargs):
        result = original(*args, **kwargs)
        result.fun = 123456.0  # A primal number must not enter lower-bound logic.
        return result

    monkeypatch.setattr(diagnostic, "linprog", fake)
    grid, p, motion = fixture()
    truth = enumerate_oracle(grid, start=0, budget=3, p=p, q=.78, motion=motion)
    result = solve_diagnostic(grid, start=0, budget=3, p=p, q=.78, motion=motion,
                              initial_path=truth.path, max_seconds=10)
    assert result.solver_primal_objective == 123456.
    assert result.lower_bound <= truth.J + 1e-10
    assert result.dual_verification["verified"]


@pytest.mark.parametrize("method", ("lp", "milp"))
def test_zero_time_preserves_provided_complete_incumbent_without_solver(monkeypatch, method):
    def forbidden(*args, **kwargs):
        pytest.fail("solver called after zero global time allowance")

    monkeypatch.setattr(diagnostic, "linprog", forbidden)
    monkeypatch.setattr(diagnostic, "milp", forbidden)
    grid, p, motion = fixture()
    path = (0, 1, 3, 2)
    truth = score_path(grid, path, start=0, budget=3, p=p, q=.78, motion=motion)
    result = solve_diagnostic(grid, start=0, budget=3, p=p, q=.78, motion=motion,
                              method=method, initial_path=path, max_seconds=0)
    assert result.status == "budget_exhausted"
    assert result.path == path and result.J == truth.J and result.Pd == truth.pd_final
    assert result.incumbent_source == "initial_path"
    assert result.model_size == {} and result.timings["solver_s"] == 0


def test_missing_duals_and_time_limit_are_explicit_and_keep_safe_fallback(monkeypatch):
    monkeypatch.setattr(diagnostic, "linprog", lambda *args, **kwargs: SimpleNamespace(
        status=1, message="test time limit", fun=999., eqlin=None, ineqlin=None))
    grid, p, motion = fixture()
    result = solve_diagnostic(grid, start=0, budget=3, p=p, q=.78, motion=motion,
                              initial_path=(0, 1, 3, 2), prefix_path=(0, 1), max_seconds=10)
    prefix = score_path(grid, (0, 1), start=0, budget=1, p=p, q=.78, motion=motion)
    assert result.status == "budget_exhausted" and result.stop_reason == "test time limit"
    assert not result.dual_verification["verified"]
    assert result.lower_bound == prefix.J
    assert result.lower_bound_source == "nonnegative_remaining_objective"


def test_milp_time_limit_retains_independently_replayed_incumbent(monkeypatch):
    original = diagnostic.milp

    def fake(*args, **kwargs):
        result = original(*args, **kwargs)
        result.status, result.message = 1, "test time limit with incumbent"
        result.mip_dual_bound = 123456.0  # Estimate is not promoted to a checked LB.
        return result

    monkeypatch.setattr(diagnostic, "milp", fake)
    grid, p, motion = fixture()
    truth = enumerate_oracle(grid, start=0, budget=3, p=p, q=.78, motion=motion)
    result = solve_diagnostic(grid, start=0, budget=3, p=p, q=.78, motion=motion,
                              method="milp", max_seconds=10)
    assert result.status == "budget_exhausted"
    assert abs(result.J-truth.J) < 1e-8 and result.incumbent_source == "milp_independent_replay"
    assert result.lower_bound == 0.0 and result.solver_dual_bound_estimate == 123456.
    assert result.theory_certified is False


def test_single_cell_without_wait_is_infeasible():
    grid = GridGraph(1, 1)
    motion = ParticleMotion(np.array([[0], [0]]), 1, [4])
    result = solve_diagnostic(grid, start=0, budget=1, p=[1.], q=1., motion=motion, max_seconds=10)
    assert result.status == "infeasible" and result.path is None
    assert result.J is None and not result.theory_certified


@pytest.mark.parametrize("override", ({"method": "bad"}, {"max_seconds": -1},
    {"max_seconds": np.inf}, {"mip_rel_gap": -1}, {"prefix_path": (0, 3)},
    {"initial_path": (0, 1, 3, 2), "prefix_path": (0, 2)}))
def test_invalid_inputs_fail_before_solver(override):
    grid, p, motion = fixture()
    with pytest.raises(ValueError):
        solve_diagnostic(grid, start=0, budget=3, p=p, q=.78, motion=motion, **override)


def test_matrix_motion_is_not_silently_substituted():
    with pytest.raises(ValueError, match="ParticleMotion"):
        solve_diagnostic(GridGraph(1, 2), start=0, budget=1, p=[.5, .5], q=.78,
                         motion=MatrixMotion.identity(2))
