"""Local validation gate; deliberately not executed in the preparation session."""

import json
from types import SimpleNamespace

import numpy as np
import pytest

from asar_repro.count_oracle import (
    diagnostic_cases,
    diagnostic_case_metadata,
    solve_count_oracle,
)
from asar_repro.grid import GridGraph
from asar_repro.motion import ParticleMotion
from asar_repro.objective import score_path
from asar_repro.oracle import enumerate_oracle


def _instance(dynamic):
    grid = GridGraph(1, 4)
    cells = np.tile([0, 3, grid.size], (5, 1))
    if dynamic:
        cells[:, 0] = [0, 0, 1, 2, 3]
        cells[:, 1] = [3, 2, 2, 1, 0]
    return dict(grid=grid, start=1, budget=4, p=[0.45, 0.45, 0.10],
                q=0.78, motion=ParticleMotion(cells, grid.size, [5, 8, 11]))


@pytest.mark.parametrize("dynamic", [False, True])
def test_full_count_model_matches_independent_dfs(dynamic):
    instance = _instance(dynamic)
    truth = enumerate_oracle(**instance)
    answer = solve_count_oracle(**instance, max_seconds=15.0)
    assert not answer["fatal"], answer
    assert answer["status"] == "optimal_numeric", answer
    assert answer["J"] == pytest.approx(truth.J, abs=1e-8)
    assert answer["lower_bound"] <= truth.J + 1e-8
    assert answer["global_numeric_gap_absolute"] <= 1e-8
    replay = score_path(instance["grid"], answer["path"],
                        **{key: value for key, value in instance.items() if key != "grid"})
    assert answer["survival"] == pytest.approx(replay.survival, abs=1e-12)
    assert answer["survival"][-1] >= 0.10
    assert answer["formal_certificate"] is False
    json.dumps(answer, allow_nan=False)


def test_resource_gate_never_calls_milp(monkeypatch):
    import scipy.optimize

    def forbidden(*args, **kwargs):
        raise AssertionError("MILP must not execute after a resource gate")

    monkeypatch.setattr(scipy.optimize, "milp", forbidden)
    answer = solve_count_oracle(**_instance(False), max_seconds=1.0,
                                options={"max_particles": 2})
    assert answer["status"] == "blocked_resource_limit"
    assert answer["lower_bound"] is None
    assert answer["solver_status"] is None
    assert answer["numerical_optimality_checked"] is False


def test_infeasible_status_conflicting_with_verified_route_is_fatal(monkeypatch):
    import scipy.optimize

    monkeypatch.setattr(scipy.optimize, "milp", lambda *args, **kwargs:
                        SimpleNamespace(status=2, message="infeasible", x=None))
    answer = solve_count_oracle(**_instance(False), max_seconds=2.0)
    assert answer["status"] == "fatal_numerical_inconsistency"
    assert answer["fatal"]
    assert answer["lower_bound"] is None


def test_solver_limit_without_candidate_does_not_claim_optimal(monkeypatch):
    import scipy.optimize

    monkeypatch.setattr(scipy.optimize, "milp", lambda *args, **kwargs:
                        SimpleNamespace(status=1, message="time limit", x=None,
                                        mip_dual_bound=0.0, mip_gap=np.inf))
    answer = solve_count_oracle(**_instance(False), max_seconds=2.0)
    assert answer["status"] == "solver_limit"
    assert answer["solver_gap_raw"] is None
    assert not answer["numerical_optimality_checked"]
    assert answer["candidate"] is None
    json.dumps(answer, allow_nan=False)


@pytest.mark.parametrize("epigraph, fatal", [(0.50, False), (0.10, True)])
def test_primal_epigraph_slack_and_underestimate_are_distinguished(monkeypatch, epigraph, fatal):
    import scipy.optimize

    grid = GridGraph(1, 2)
    motion = ParticleMotion(np.array([[0], [1]]), grid.size, [7])
    # One legal arc, one count, one epigraph variable. The actual survival is
    # 0.22: z=0.50 is valid slack; z=0.10 violates the mathematical epigraph.
    monkeypatch.setattr(scipy.optimize, "milp", lambda *args, **kwargs:
                        SimpleNamespace(status=1, message="limit", x=np.array([1., 1., epigraph]),
                                        fun=epigraph, mip_dual_bound=0., mip_gap=1.))
    answer = solve_count_oracle(grid, start=0, budget=1, p=[1.], q=.78,
                                motion=motion, max_seconds=2.)
    assert answer["fatal"] is fatal
    if not fatal:
        assert answer["status"] == "solver_limit"
        assert answer["J"] == pytest.approx(.22)
        assert answer["objective_epigraph_slack"] == pytest.approx(.28)
        assert not answer["numerical_optimality_checked"]


@pytest.mark.parametrize("q", [0.0, 1.0, float("nan"), [0.78] * 4])
def test_unsupported_sensor_input_fails_explicitly(q):
    instance = _instance(False)
    instance["q"] = q
    with pytest.raises(ValueError, match="q"):
        solve_count_oracle(**instance)


def test_zero_horizon_is_scored_without_milp(monkeypatch):
    import scipy.optimize

    def forbidden(*args, **kwargs):
        raise AssertionError("zero horizon does not require an optimizer")

    monkeypatch.setattr(scipy.optimize, "milp", forbidden)
    instance = _instance(False)
    instance["budget"] = 0
    answer = solve_count_oracle(**instance)
    assert answer["path"] == [1]
    assert answer["J"] == 0.0
    assert answer["lower_bound"] == 0.0
    assert answer["status"] == "trivial_optimal"


def test_diagnostic_definitions_are_fixed_and_json_serializable():
    for tier, horizons in (("tiny", {4, 5, 6}), ("medium", {12, 14, 16})):
        cases = diagnostic_cases(tier)
        assert len(cases) == 9
        assert len({case["id"] for case in cases}) == 9
        assert {case["budget"] for case in cases} == horizons
        assert {case["family"] for case in cases} == {"order", "transfer", "repeat"}
        for case in cases:
            case["grid"].validate_path(case["initial_path"], start=case["start"],
                                      budget=case["budget"])
            assert case["metadata"] == diagnostic_case_metadata(case)
            json.dumps(case["metadata"], allow_nan=False)
            assert np.sum(case["p"]) == pytest.approx(1.0)
    # Repeated-detection family intentionally retains unsearchable mass.
    repeat = [case for case in diagnostic_cases("tiny") if case["family"] == "repeat"]
    assert all((case["motion"].cell_ids[:, -1] == case["grid"].size).all()
               for case in repeat)
