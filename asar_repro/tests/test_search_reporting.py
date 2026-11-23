"""B4: exercise each exit with actual searches and independently replay the path."""

from dataclasses import replace
from itertools import count
import json

import numpy as np
import pytest

from asar_repro.grid import GridGraph
from asar_repro.gridding import ParticleGrid
from asar_repro.motion import MatrixMotion
from asar_repro.oracle import enumerate_oracle
from asar_repro.planner_adapter import plan_particle_path
from asar_repro.search import search_asar
from asar_repro.search_reporting import (
    REQUIRED_FIELDS,
    classify_result,
    search_record,
    summarize_records,
)


@pytest.fixture
def case():
    return GridGraph(2, 2), dict(
        start=0, budget=2, p=[0.25] * 4, q=0.5, motion=MatrixMotion.identity(4)
    )


def record(result, grid, args, **kw):
    row = search_record(
        result,
        grid,
        **args,
        planner_wall_s=0.25,
        warm_start_s=0.125,
        initial_source="ParallelTrack",
        **kw
    )
    assert set(REQUIRED_FIELDS) <= row.keys()
    assert row["total_wall_s"] == 0.375
    assert row["discrete_model_certified"] == result.theory_certified
    json.dumps(row, allow_nan=False)
    return row


@pytest.mark.parametrize("mode", ["zero", "mass_lb", "paper_greedy", "paper_literal_abs_time"])
@pytest.mark.parametrize("prune", [False, True])
def test_goal_pop_is_completed_and_matches_oracle(case, mode, prune):
    grid, args = case
    events = []
    r = search_asar(grid, **args, heuristic=mode, prune=prune, trace=events.append)
    assert events[-1]["event"] == "pop" and events[-1]["depth"] == args["budget"]
    row = record(r, grid, args)
    assert row["result_class"] == "completed_search" and row["incumbent_source"] == "search"
    assert row["J"] == pytest.approx(enumerate_oracle(grid, **args).J)
    assert row["search_completed"] and row["found_feasible_path"]
    assert (
        row["theoretical_bound_applicable"]
        == row["completed_for_certificate"]
        == (mode in ("zero", "mass_lb"))
    )


@pytest.mark.parametrize("mode", ["zero", "mass_lb", "paper_greedy"])
@pytest.mark.parametrize("limit", ["max_expansions", "max_open", "max_seconds"])
@pytest.mark.parametrize("warm", [False, True])
def test_root_and_loop_resource_stops(case, mode, limit, warm):
    grid, args = case
    path = (0, 1, 0) if warm else None
    r = search_asar(grid, **args, heuristic=mode, initial_path=path, prune=False, **{limit: 0})
    row = record(r, grid, args, limits={limit: 0})
    assert row["search_status"] == "budget_exceeded" and row["stop_reason"] == limit
    assert row["theoretical_bound_applicable"] == (mode in ("zero", "mass_lb"))
    assert not row["completed_for_certificate"] and not row["search_completed"]
    assert row["incumbent_source"] == ("ParallelTrack" if warm else None)
    assert row["found_feasible_path"] == warm
    if not warm:
        assert all(row[k] is None for k in ("path", "J", "Pd_T", "M_T", "M_0_to_T"))


@pytest.mark.parametrize("boundary", [1, 2, 3, 4, 5])
def test_deterministic_timeout_before_after_heuristic_and_loop(case, monkeypatch, boundary):
    grid, args = case
    ticks = count()
    monkeypatch.setattr("asar_repro.search.perf_counter", lambda: float(next(ticks)))
    r = search_asar(grid, **args, max_seconds=boundary)
    row = record(r, grid, args)
    assert row["stop_reason"] == "max_seconds"
    assert row["result_class"] == "aborted_without_path"


def test_goal_is_saved_before_timeout_during_enqueue(case, monkeypatch):
    grid, args = case
    args["budget"] = 1
    ticks = count()
    monkeypatch.setattr("asar_repro.search.perf_counter", lambda: float(next(ticks)))
    r = search_asar(grid, **args, max_seconds=4)
    row = record(r, grid, args)
    assert row["stop_reason"] == "max_seconds" and row["incumbent_source"] == "search"
    assert row["J"] == 0.875 and row["result_class"] == "aborted_feasible_incumbent"


def test_new_improved_goal_is_saved_before_open_rejection():
    grid = GridGraph(2, 2)
    args = dict(start=0, budget=1, p=[0, 0.25, 0.75, 0], q=1, motion=MatrixMotion.identity(4))
    r = search_asar(grid, **args, initial_path=(0, 1), max_open=1, prune=False)
    row = record(r, grid, args)
    assert row["stop_reason"] == "max_open" and row["incumbent_source"] == "search"
    assert row["path"] == [0, 2] and row["J"] == 0.25
    assert not row["discrete_model_certified"]


def test_expansion_limit_can_return_a_search_incumbent(case):
    grid, args = case
    r = search_asar(grid, **args, max_expansions=2)
    row = record(r, grid, args)
    assert row["stop_reason"] == "max_expansions"
    assert row["incumbent_source"] == "search" and row["J"] == 1.625


@pytest.mark.parametrize("mode", ["mass_lb", "paper_greedy"])
def test_open_exhaustion_after_root_bound_keeps_initial_route(case, mode):
    grid, args = case
    args["q"] = 0
    events = []
    r = search_asar(grid, **args, heuristic=mode, initial_path=(0, 1, 0), trace=events.append)
    assert [e["event"] for e in events] == ["prune"]
    row = record(r, grid, args)
    assert row["J"] == 2 and row["incumbent_source"] == "ParallelTrack"
    assert row["discrete_model_certified"] == (mode == "mass_lb")
    assert r.expanded == 0 and r.peak_open == 0


def test_zero_horizon_and_infeasible_open_exhaustion():
    grid = GridGraph(1, 1)
    args = dict(start=0, budget=0, p=[1], q=1, motion=MatrixMotion.identity(1))
    row = record(search_asar(grid, **args), grid, args)
    assert row["path"] == [0] and row["J"] == 0 and row["Pd_T"] == 0 and row["M_T"] == 1
    with pytest.raises(ValueError, match="no feasible path"):
        search_asar(grid, **(args | dict(budget=1)))


def test_unverified_model_and_corrupt_result_cannot_get_certificate(case):
    grid, args = case
    r = search_asar(grid, **args)
    flags = classify_result(r, model_assumptions_verified=False)
    assert not flags["theoretical_bound_applicable"] and not flags["discrete_model_certified"]
    with pytest.raises(ValueError, match="replay"):
        record(replace(r, J=r.J + 1), grid, args)
    with pytest.raises(ValueError, match="path and J"):
        classify_result(replace(r, path=None))
    with pytest.raises(ValueError, match="stop reason"):
        classify_result(replace(r, stop_reason="max_seconds"))
    with pytest.raises(ValueError, match="timings"):
        search_record(r, grid, **args, planner_wall_s=float("nan"))


@pytest.mark.parametrize("mode", ["zero", "mass_lb", "paper_greedy"])
def test_adapter_full_schema_timing_hash_and_provenance(mode):
    kw = dict(
        grid=ParticleGrid(GridGraph(1, 2), (-76.5, 44.2), 100),
        start=0,
        cell_ids=[[0, 3], [1, 3], [0, 3]],
        trajectory_ids=[7, 9],
        initial_weights=[0.6, 0.4],
        q=0.5,
        time_utc=np.array(
            ["2025-01-01T00:00:00", "2025-01-01T00:00:01", "2025-01-01T00:00:02"],
            dtype="datetime64[ns]",
        ),
        heuristic=mode,
        epsilon=1,
        provenance=dict(scenario_id="toy", forcing_kind="toy", seed=12),
    )
    a = plan_particle_path(**kw)
    b = plan_particle_path(**kw)
    stopped = plan_particle_path(**kw, max_expansions=0, warm_start=False)
    assert set(REQUIRED_FIELDS) <= a.keys()
    assert a["config_hash"] == b["config_hash"] != stopped["config_hash"]
    assert a["J"] == pytest.approx(1.25) and a["M_T"] == pytest.approx(0.55)
    assert (
        a["algorithm"]
        == {"zero": "ASAR_zero", "mass_lb": "ASAR_mass_lb", "paper_greedy": "ASAR_paper"}[mode]
    )
    assert a["total_wall_s"] == a["warm_start_s"] + a["planner_wall_s"]
    assert a["scenario_id"] == "toy" and a["forcing_kind"] == "toy" and a["seed"] == 12
    assert a["particle_archive_sha256"] is None and a["git_commit"] is None
    assert stopped["J"] is None and stopped["Pd_T"] is None and stopped["M_T"] is None
    assert not stopped["completed_for_certificate"]
    json.dumps(a, allow_nan=False)
    groups = summarize_records([a, stopped, dict(a, forcing_kind="historical_real")])
    assert len(groups) == 2 and groups[0]["completion_rate"] == 0.5
    assert groups[0]["aborted_without_path"] == 1 and groups[1]["runs"] == 1
