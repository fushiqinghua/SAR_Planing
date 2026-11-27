"""Pure protocol regression tests, supplied for LOCAL validation, not executed.

These tests do not run a search, MILP, benchmark, or subprocess. They exercise
budget filtering, task identity, censoring and fail-closed decision rules.
"""

from copy import deepcopy
import importlib.util
import json
import math
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "solver_paradigm_study_under_test", ROOT / "scripts/run_solver_paradigm_study.py")
study = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(study)


@pytest.fixture
def config():
    return json.loads((ROOT / "configs/solver_paradigm_study.json").read_text(encoding="utf-8"))


def records_for(config, stage="B5", *, new_j=9.9, control_j=10.0,
                new_time=0.5, control_time=1.0):
    rows = []
    for task in study.make_tasks(config, stage):
        stochastic = task["method"] in study.STOCHASTIC
        value = new_j if stochastic else control_j
        elapsed = new_time if stochastic else control_time
        rows.append(dict(
            task=task, status="completed",
            result=dict(status="valid", J=value, pd_final=0.8,
                        targets={name: dict(reached=True, time_s=elapsed,
                                            censored=False, censor_time_s=None)
                                 for name in config["quality_targets"]})))
    return rows


def test_frozen_plan_counts_and_budget_sums(config):
    answer = study.plan(config)
    assert answer["status"] == "plan_only_not_results"
    assert answer["A"] == dict(tasks=117, algorithm_budget_s=1125)
    assert answer["B5"] == dict(tasks=38, algorithm_budget_s=190)
    assert answer["B30"] == dict(tasks=38, algorithm_budget_s=1140)
    assert answer["C300_maximum"] == dict(tasks=8, algorithm_budget_s=2400, gated=True)


def test_b5_and_b30_are_separate_tasks_with_stable_order(config):
    short = study.make_tasks(config, "B5")
    long = study.make_tasks(config, "B30")
    assert short == study.make_tasks(config, "B5")
    assert long == study.make_tasks(config, "B30")
    assert not {study.task_id(t) for t in short} & {study.task_id(t) for t in long}
    identity = lambda t: (t["scene"], t["method"], t["seed"], t["repetition"])
    assert {identity(t) for t in short} == {identity(t) for t in long}
    assert {t["seconds"] for t in short} == {5}
    assert {t["seconds"] for t in long} == {30}


def test_long_tasks_use_only_first_two_frozen_seeds(config):
    scene = config["primary_scenes"][0]
    tasks = study.make_tasks(config, "C300", [("ils", scene)])
    assert len(tasks) == 2
    assert {t["seed"] for t in tasks} == set(config["optimizer_seeds"][:2])
    assert {t["seconds"] for t in tasks} == {300}
    with pytest.raises(ValueError, match="outside"):
        study.make_tasks(config, "C300", [("count_oracle", scene)])


def test_budget_filter_drops_late_and_invalid_scores_and_keeps_boundary():
    history = [
        dict(elapsed_s=5.01, J=1.0, source="late"),
        dict(elapsed_s=0.1, J=20.0, source="initial_replay"),
        dict(elapsed_s=0.2, J=21.0, source="not_better"),
        dict(elapsed_s=-0.1, J=0.0, source="negative_time"),
        dict(elapsed_s=0.3, J=math.nan, source="invalid_score"),
        dict(elapsed_s=math.inf, J=0.0, source="infinite_time"),
        dict(elapsed_s=5.0, J=10.0, source="boundary"),
    ]
    accepted = study.select_budget_history(history, 5.0)
    assert [row["source"] for row in accepted] == ["initial_replay", "boundary"]
    assert accepted[0]["elapsed_s"] > 0


def test_invalid_nan_time_does_not_disrupt_order_of_valid_history():
    history = [dict(elapsed_s=4.0, J=10.0),
               dict(elapsed_s=math.nan, J=1.0),
               dict(elapsed_s=0.1, J=20.0)]
    accepted = study.select_budget_history(history, 5.0)
    assert [row["elapsed_s"] for row in accepted] == [0.1, 4.0]


def test_unreached_target_is_censored_at_actual_observation_end():
    history = [dict(elapsed_s=0.1, J=20.0), dict(elapsed_s=2.0, J=12.0)]
    targets = study.quality_targets(history, {"target": 1.001}, 10.0, 3.2)
    answer = targets["target"]
    assert answer["reached"] is False
    assert answer["time_s"] is None
    assert answer["censored"] is True
    assert answer["censor_time_s"] == 3.2


def test_target_uses_first_completed_hit_not_final_or_deadline():
    history = [dict(elapsed_s=0.1, J=20.0), dict(elapsed_s=1.5, J=9.9),
               dict(elapsed_s=4.0, J=9.0)]
    answer = study.quality_targets(history, {"target": 1.001}, 10.0, 5.0)["target"]
    assert answer["reached"] is True
    assert answer["time_s"] == 1.5
    assert answer["censored"] is False
    assert answer["censor_time_s"] is None


def test_complete_quality_and_time_witnesses_pass_defined_screens(config):
    decisions = study.engineering_decisions(config, records_for(config))
    for method in study.STOCHASTIC:
        assert decisions[method]["complete"]
        assert decisions[method]["quality_pass"]
        assert decisions[method]["time_pass"]


@pytest.mark.parametrize("missing_method", ["ils", "anytime_zero", "anytime_mass"])
def test_missing_required_run_cannot_pass(config, missing_method):
    rows = records_for(config)
    index = next(i for i, r in enumerate(rows) if r["task"]["method"] == missing_method)
    rows[index] = None
    decisions = study.engineering_decisions(config, rows)
    assert decisions["ils"]["complete"] is False
    assert decisions["ils"]["quality_pass"] is False
    assert decisions["ils"]["time_pass"] is False


def test_failed_run_is_not_an_extremely_good_valid_score(config):
    rows = records_for(config)
    failed = next(r for r in rows if r["task"]["method"] == "ils")
    failed["status"] = "failed"
    failed["result"]["J"] = 0.0
    decisions = study.engineering_decisions(config, rows)
    assert not decisions["ils"]["complete"]
    assert not decisions["ils"]["quality_pass"]
    assert not decisions["ils"]["time_pass"]


def test_one_censored_seed_blocks_speed_but_not_quality_screen(config):
    rows = records_for(config)
    candidate = next(r for r in rows if r["task"]["method"] == "ils")
    candidate["result"]["targets"][config["decision"]["time_target"]] = dict(
        reached=False, time_s=None, censored=True, censor_time_s=5.0)
    decisions = study.engineering_decisions(config, rows)
    assert decisions["ils"]["complete"]
    assert decisions["ils"]["quality_pass"]
    assert decisions["ils"]["time_pass"] is False


def test_other_primary_scene_regression_blocks_both_screens(config):
    rows = records_for(config, new_j=9.0)
    for row in rows:
        if row["task"]["method"] == "ils" and row["task"]["scene"] == config["primary_scenes"][1]:
            row["result"]["J"] = 10.1
    answer = study.engineering_decisions(config, rows)["ils"]
    assert answer["complete"]
    assert not answer["quality_pass"]
    assert not answer["time_pass"]


def test_one_best_seed_does_not_replace_median_quality(config):
    rows = records_for(config, new_j=11.0, new_time=2.0)
    for scene in config["primary_scenes"]:
        lucky = next(r for r in rows if r["task"]["method"] == "ils" and r["task"]["scene"] == scene)
        lucky["result"]["J"] = 1.0
    answer = study.engineering_decisions(config, rows)["ils"]
    assert answer["complete"]
    assert not answer["quality_pass"]
    assert not answer["time_pass"]
    assert all(v["median_J"] == 11.0 for v in answer["scenes"].values())


def test_long_selection_reads_b30_and_requires_two_strict_reference_wins(config, monkeypatch, tmp_path):
    config = deepcopy(config)
    for scene in config["primary_scenes"]:
        config["scenes"][scene]["reference_J"] = 10.0
    rows = records_for(config, stage="B30", new_j=10.5, control_j=9.0,
                       new_time=3.0, control_time=1.0)
    target_scene = config["primary_scenes"][0]
    candidates = [r for r in rows if r["task"]["method"] == "ils"
                  and r["task"]["scene"] == target_scene]
    candidates[0]["result"]["J"] = 9.8
    candidates[1]["result"]["J"] = 9.9
    observed = []

    def provide(_config, _out, stage, selected=None):
        observed.append(stage)
        return rows

    monkeypatch.setattr(study, "stage_records", provide)
    selected, decisions = study.select_long(config, tmp_path)
    assert observed == ["B30"]
    assert selected == [("ils", target_scene)]
    assert not decisions["ils"]["quality_pass"]
    assert not decisions["ils"]["time_pass"]
    candidates[1]["result"]["J"] = 10.0 - config["strict_improvement_absolute"]
    selected, _ = study.select_long(config, tmp_path)
    assert selected == []  # Equality at the numerical tolerance is not strict.


def test_incomplete_b30_cannot_trigger_long_runs(config, monkeypatch, tmp_path):
    rows = records_for(config, stage="B30")
    rows[0] = None
    monkeypatch.setattr(study, "stage_records", lambda *args, **kwargs: rows)
    with pytest.raises(RuntimeError, match="Complete valid B30"):
        study.select_long(config, tmp_path)


def diagnostic_records(config):
    """Complete internally consistent mock evidence, without running solvers."""
    records = {}
    for task in study.make_tasks(config, "A"):
        method = task["method"]
        if method == "count_oracle":
            raw = dict(status="optimal_numeric", fatal=False, solver_status=0,
                       numerical_optimality_checked=True,
                       optimality_scope="full_fixed_particle_discrete_instance")
        elif method == "dfs":
            raw = dict(status="optimal_enumerated")
        else:
            raw = dict(status="completed")
        answer = dict(status="valid", J=10.0,
                      lower_bound=10.0 if method in ("count_oracle", "dfs") else None,
                      raw_solver=raw)
        records[study.task_id(task)] = dict(task=task, status="completed", result=answer)
    return records


def test_complete_consistent_diagnostic_evidence_passes(config, monkeypatch, tmp_path):
    records = diagnostic_records(config)
    monkeypatch.setattr(study, "read_record", lambda _out, task: records[study.task_id(task)])
    answer = study.diagnostic_gate(config, tmp_path)
    assert answer["passed"] is True
    assert len(answer["checks"]) == 18
    assert all(c["passed"] for c in answer["checks"])


def test_unclosed_tiny_count_interval_blocks_real_stages(config, monkeypatch, tmp_path):
    records = diagnostic_records(config)
    for record in records.values():
        if record["task"]["case"].startswith("tiny_") and record["task"]["method"] == "count_oracle":
            record["result"]["lower_bound"] = 9.0
    monkeypatch.setattr(study, "read_record", lambda _out, task: records[study.task_id(task)])
    answer = study.diagnostic_gate(config, tmp_path)
    assert answer["passed"] is False


def test_fatal_medium_result_cannot_be_masked_by_valid_initial_route(config, monkeypatch, tmp_path):
    records = diagnostic_records(config)
    for record in records.values():
        if record["task"]["case"].startswith("medium_") and record["task"]["method"] == "count_oracle":
            record["result"]["raw_solver"].update(status="fatal_numerical_inconsistency", fatal=True)
            record["result"]["lower_bound"] = None
    monkeypatch.setattr(study, "read_record", lambda _out, task: records[study.task_id(task)])
    answer = study.diagnostic_gate(config, tmp_path)
    assert answer["passed"] is False
    assert answer["reason"] == "A contains invalid solver evidence"
    assert answer["task"]["case"].startswith("medium_")


def test_medium_dual_must_respect_other_solvers_feasible_routes(config, monkeypatch, tmp_path):
    records = diagnostic_records(config)
    target_case = "medium_order_0"
    for record in records.values():
        if record["task"]["case"] == target_case and record["task"]["method"] == "ils":
            record["result"]["J"] = 9.0  # Count's own U=L=10 is locally consistent, globally impossible.
    monkeypatch.setattr(study, "read_record", lambda _out, task: records[study.task_id(task)])
    answer = study.diagnostic_gate(config, tmp_path)
    assert answer["passed"] is False
    bad = next(c for c in answer["checks"] if c["case"] == target_case)
    assert bad["best_feasible_J"] == 9.0
    assert bad["count_L"] == 10.0
    assert bad["bound_consistent_with_all_routes"] is False
    assert bad["passed"] is False
    assert all(c["passed"] for c in answer["checks"] if c["case"] != target_case)


@pytest.mark.parametrize("invalid_claim", [
    dict(status="solver_limit", solver_status=1),
    dict(numerical_optimality_checked=False),
    dict(optimality_scope="fixed_prefix_and_corridor"),
])
def test_closed_tiny_numbers_need_checked_full_domain_optimality(config, monkeypatch, tmp_path, invalid_claim):
    records = diagnostic_records(config)
    target_case = "tiny_order_0"
    for record in records.values():
        if record["task"]["case"] == target_case and record["task"]["method"] == "count_oracle":
            record["result"]["raw_solver"].update(invalid_claim)
    monkeypatch.setattr(study, "read_record", lambda _out, task: records[study.task_id(task)])
    answer = study.diagnostic_gate(config, tmp_path)
    assert answer["passed"] is False
    bad = next(c for c in answer["checks"] if c["case"] == target_case)
    assert bad["interval_closed"] is True
    assert bad["passed"] is False
    assert all(c["passed"] for c in answer["checks"] if c["case"] != target_case)
