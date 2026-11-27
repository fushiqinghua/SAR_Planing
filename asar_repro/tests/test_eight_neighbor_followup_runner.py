"""Protocol risk checks for local execution; all rows and replays are synthetic.

These tests do not launch a search, generate particle drift, or import generation
dependencies. They were prepared without running pytest or importing the runner.
"""
from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "physical_followup_runner_for_tests", ROOT / "scripts/run_eight_neighbor_followup.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def config():
    return json.loads((ROOT / "configs/eight_neighbor_followup.json").read_text(encoding="utf-8"))


def development_rows():
    cfg = config()
    rows = []
    for task in runner.tasks_for(cfg, "D5"):
        target = next((t for t in cfg["development_targets"]
                       if all(task[k] == t[k] for k in ("scene", "footprint", "connectivity"))), None)
        initial_j = target["J"] + 1.0 if target else 100.0
        rows.append(dict(task=task, result=dict(J=initial_j, history=[
            dict(elapsed_s=0.01, J=initial_j, pd_final=0.5, source="initial_route")
        ])))
    return rows


def set_hits(rows, target_index, backend, times):
    """Set three coherent incumbent histories; None means target not reached."""
    target = config()["development_targets"][target_index]
    for row in rows:
        task = row["task"]
        if task["backend"] != backend or any(
                task[k] != target[k] for k in ("scene", "footprint", "connectivity")):
            continue
        initial_j = target["J"] + 1.0
        result = dict(J=initial_j, history=[dict(
            elapsed_s=0.01, J=initial_j, pd_final=0.5, source="initial_route")])
        elapsed = times[task["repetition"]]
        if elapsed is not None:
            result["J"] = target["J"]
            result["history"].append(dict(elapsed_s=elapsed, J=target["J"],
                                          pd_final=0.6, source="search"))
        row["result"] = result


def holdout_rows(*, heading=(99.0, 100.0, 99.0, 100.0),
                 axis=(99.5, 100.0, 100.0, 100.0), backend="original"):
    cfg = config()
    case_ids = [case["id"] for case in cfg["cases"]]
    rows = []
    for task in runner.tasks_for(cfg, "H30"):
        index = case_ids.index(task["case"])
        eight = heading[index] if task["footprint"] == "heading_square" else axis[index]
        rows.append(dict(task=task, result=dict(
            J=100.0 if task["connectivity"] == 4 else eight, backend=backend)))
    return rows


def ready_generation_environment():
    return dict(packages={"opendrift": "1.14.0", "xarray": "2025.1.0",
                          "PyYAML": "6.0.2", "netCDF4": "1.7.2", "shapely": "2.0.6"})


def stub_development_evidence(monkeypatch, rows):
    monkeypatch.setattr(runner, "verify_dev", lambda *args: {})
    monkeypatch.setattr(runner, "require_complete", lambda out, stage:
                        [dict(result=dict(audit=dict(passed=True)))] if stage == "P0" else rows)
    monkeypatch.setattr(runner, "evidence_for_rows", lambda *args: {})


class ReplayStub:
    def __init__(self, scores):
        self.scores = scores
        self.calls = []

    def replay(self, route, connectivity):
        key = tuple(route)
        self.calls.append((key, connectivity))
        return dict(self.scores[key])


def test_registered_matrix_has_100_tasks_1800_seconds_and_separate_p0():
    cfg = config()
    result = runner.plan(cfg)
    assert result["formal_tasks"] == 100
    assert result["formal_algorithm_budget_s"] == 1800
    assert result["stages"] == {
        "D5": dict(tasks=48, algorithm_budget_s=240),
        "S30": dict(tasks=4, algorithm_budget_s=120),
        "H30": dict(tasks=48, algorithm_budget_s=1440),
    }
    assert result["P0"] == dict(paired_audits=8, expansion_cap_each=128,
                               wall_cap_each_s=30, performance_evidence=False)
    assert result["H2"] == result["long_budget"] == "not_enabled"
    for stage, seconds, count in (("P0", 30, 8), ("D5", 5, 48), ("S30", 30, 4), ("H30", 30, 48)):
        tasks = runner.tasks_for(cfg, stage)
        assert len(tasks) == count
        assert {t["seconds"] for t in tasks} == {seconds}
        assert len({runner.task_id(t) for t in tasks}) == count
        assert tasks == runner.tasks_for(cfg, stage)
    assert {t["backend"] for t in runner.tasks_for(cfg, "P0")} == {"paired_audit"}
    assert {t["backend"] for t in runner.tasks_for(cfg, "H30")} == {"selected"}


@pytest.mark.parametrize("damage", ["missing", "duplicate", "nan", "infinite", "wrong_budget"])
def test_d5_requires_complete_finite_exact_task_identity(damage):
    rows = development_rows()
    if damage == "missing":
        rows.pop()
    elif damage == "duplicate":
        rows[-1] = deepcopy(rows[0])
    elif damage == "wrong_budget":
        rows[0]["task"]["seconds"] = 30
    else:
        rows[0]["result"]["J"] = math.nan if damage == "nan" else math.inf
    decision = runner.development_decision(config(), rows, True)
    assert decision["status"] == "incomplete_or_invalid"
    assert decision["selected_backend"] is None


def test_d5_incomplete_gate_cannot_select_a_backend():
    decision = runner.development_decision(config(), development_rows(), False)
    assert decision == dict(status="incomplete_or_invalid", selected_backend=None)


def test_d5_no_signal_falls_back_to_original_and_preserves_censoring():
    decision = runner.development_decision(config(), development_rows(), True)
    assert decision["status"] == "acceleration_screen_not_passed"
    assert decision["selected_backend"] == "original"
    assert decision["quality_protected"] and decision["target_hit_counts_protected"]
    for target in decision["targets"]:
        assert target["relative_time_reduction"] is None
        for backend in ("original", "cached"):
            values = target["backends"][backend]
            assert values["hit_count"] == 0
            assert values["times_s"] == [None, None, None]
            assert values["median_if_all_hit_s"] is None
            assert values["non_hit"] == "right_censored_at_5s_not_a_measured_target_time"


def test_d5_one_extra_target_hit_can_select_cached_without_fabricated_speed():
    rows = development_rows()
    set_hits(rows, 0, "cached", (2.0, None, None))
    decision = runner.development_decision(config(), rows, True)
    assert decision["status"] == "acceleration_screen_passed"
    assert decision["selected_backend"] == "cached"
    assert decision["improved_hit_groups"] == 1
    assert decision["full_hit_faster_groups"] == 0
    assert decision["targets"][0]["relative_time_reduction"] is None


def test_d5_quality_loss_in_any_of_eight_groups_blocks_extra_hits():
    rows = development_rows()
    set_hits(rows, 0, "cached", (2.0, None, None))
    for row in rows:
        task = row["task"]
        if (task["scene"], task["footprint"], task["connectivity"], task["backend"]) == (
                "arctic_ocean", "axis_square", 4, "cached"):
            row["result"]["J"] += 0.1
            row["result"]["history"][0]["J"] += 0.1
    decision = runner.development_decision(config(), rows, True)
    assert not decision["quality_protected"]
    assert decision["improved_hit_groups"] == 1
    assert decision["selected_backend"] == "original"


def test_d5_hit_count_loss_cannot_be_offset_by_another_target_gain():
    rows = development_rows()
    set_hits(rows, 0, "cached", (2.0, None, None))
    set_hits(rows, 1, "original", (2.0, 2.5, 3.0))
    set_hits(rows, 1, "cached", (1.0, 1.5, None))
    decision = runner.development_decision(config(), rows, True)
    assert decision["quality_protected"]
    assert not decision["target_hit_counts_protected"]
    assert decision["improved_hit_groups"] == 1
    assert decision["selected_backend"] == "original"


def test_d5_two_full_hit_groups_at_exact_ten_percent_select_cached():
    rows = development_rows()
    for target in (0, 1):
        set_hits(rows, target, "original", (3.8, 4.0, 4.2))
        set_hits(rows, target, "cached", (3.4, 3.6, 3.8))
    decision = runner.development_decision(config(), rows, True)
    assert decision["improved_hit_groups"] == 0
    assert decision["full_hit_faster_groups"] == 2
    assert decision["selected_backend"] == "cached"
    assert decision["targets"][0]["relative_time_reduction"] == pytest.approx(0.1)


def test_d5_one_full_hit_faster_group_is_insufficient():
    rows = development_rows()
    set_hits(rows, 0, "original", (3.8, 4.0, 4.2))
    set_hits(rows, 0, "cached", (1.8, 2.0, 2.2))
    decision = runner.development_decision(config(), rows, True)
    assert decision["full_hit_faster_groups"] == 1
    assert decision["selected_backend"] == "original"


def test_d5_two_full_hit_groups_below_ten_percent_are_insufficient():
    rows = development_rows()
    for target in (0, 1):
        set_hits(rows, target, "original", (3.8, 4.0, 4.2))
        set_hits(rows, target, "cached", (3.5, 3.61, 3.8))
    decision = runner.development_decision(config(), rows, True)
    assert decision["full_hit_faster_groups"] == 0
    assert decision["selected_backend"] == "original"


def test_d5_partial_hits_do_not_qualify_as_time_reductions():
    rows = development_rows()
    for target in (0, 1):
        set_hits(rows, target, "original", (4.0, 4.5, None))
        set_hits(rows, target, "cached", (0.5, 0.6, None))
    decision = runner.development_decision(config(), rows, True)
    assert decision["quality_protected"] and decision["target_hit_counts_protected"]
    assert decision["full_hit_faster_groups"] == decision["improved_hit_groups"] == 0
    assert decision["selected_backend"] == "original"
    assert all(t["relative_time_reduction"] is None for t in decision["targets"])


def test_target_time_uses_first_hit_and_fixed_absolute_tolerance():
    result = dict(history=[dict(J=10.0, elapsed_s=0.1),
                           dict(J=9.000000005, elapsed_s=2.0),
                           dict(J=8.0, elapsed_s=4.0)])
    assert runner.time_to_target(result, 9.0, 1e-8) == 2.0
    assert runner.time_to_target(result, 7.0, 1e-8) is None


@pytest.mark.parametrize("backend", ["original", "cached"])
def test_h1_pass_requires_one_backend_and_reports_within_forcing_scope(backend):
    decision = runner.holdout_decision(config(), holdout_rows(backend=backend), True)
    assert decision["status"] == "within_forcing_transfer_signal"
    assert decision["main_quality_pass"] and decision["sensitivity_pass"]
    assert decision["winners_by_scene"] == {"lake_ontario": 1, "arctic_ocean": 1}
    assert decision["backend"] == backend
    assert decision["independence_level"] == "same_forcing_shifted_window_new_seed"
    assert decision["independent_weather_generalization"] is False


def test_h1_single_scene_winners_are_not_called_both_scene_transfer():
    rows = holdout_rows(heading=(99.0, 99.0, 100.0, 100.0))
    decision = runner.holdout_decision(config(), rows, True)
    assert decision["status"] == "within_forcing_scene_specific_signal"
    assert decision["winners_by_scene"] == {"lake_ontario": 2, "arctic_ocean": 0}


def test_h1_at_least_two_primary_winners_are_required():
    decision = runner.holdout_decision(
        config(), holdout_rows(heading=(99.0, 100.0, 100.0, 100.0)), True)
    assert decision["status"] == "within_forcing_screen_not_passed"
    assert not decision["main_quality_pass"]


def test_h1_primary_regression_is_not_cancelled_by_other_large_gains():
    decision = runner.holdout_decision(
        config(), holdout_rows(heading=(90.0, 100.1, 99.0, 100.0)), True)
    assert len(decision["primary_winners"]) == 2
    assert not decision["main_quality_pass"]
    assert decision["status"] == "within_forcing_screen_not_passed"


def test_h1_no_axis_positive_gain_is_sensor_sensitive():
    decision = runner.holdout_decision(
        config(), holdout_rows(axis=(100.0, 100.0, 100.0, 100.0)), True)
    assert decision["main_quality_pass"] and not decision["sensitivity_pass"]
    assert decision["status"] == "within_forcing_sensor_sensitive"


def test_h1_axis_positive_must_be_on_a_primary_winner():
    decision = runner.holdout_decision(
        config(), holdout_rows(axis=(100.0, 99.0, 100.0, 100.0)), True)
    assert decision["main_quality_pass"] and not decision["sensitivity_pass"]
    assert decision["status"] == "within_forcing_sensor_sensitive"


@pytest.mark.parametrize("worst_axis,expected", [
    (100.5, "within_forcing_transfer_signal"),
    (100.6, "within_forcing_sensor_sensitive"),
])
def test_h1_half_percent_axis_regression_limit_is_inclusive(worst_axis, expected):
    decision = runner.holdout_decision(
        config(), holdout_rows(axis=(99.5, worst_axis, 100.0, 100.0)), True)
    assert decision["main_quality_pass"]
    assert decision["status"] == expected


def test_h1_uses_per_instance_medians_not_best_repetition():
    rows = holdout_rows()
    for row in rows:
        task = row["task"]
        if (task["case"], task["footprint"], task["connectivity"]) == (
                "lake_window_early", "heading_square", 8):
            row["result"]["J"] = (98.0, 100.0, 100.0)[task["repetition"]]
    decision = runner.holdout_decision(config(), rows, True)
    assert decision["comparisons"]["heading_square"]["lake_window_early"]["J8"] == 100.0
    assert not decision["main_quality_pass"]


@pytest.mark.parametrize("damage", ["missing", "duplicate", "nan", "infinite", "wrong_budget"])
def test_h1_rejects_incomplete_nonfinite_or_mismatched_tasks(damage):
    rows = holdout_rows()
    if damage == "missing":
        rows.pop()
    elif damage == "duplicate":
        rows[-1] = deepcopy(rows[0])
    elif damage == "wrong_budget":
        rows[0]["task"]["seconds"] = 5
    else:
        rows[0]["result"]["J"] = math.nan if damage == "nan" else math.inf
    assert runner.holdout_decision(config(), rows, True)["status"] == "incomplete_or_invalid"


@pytest.mark.parametrize("damage", ["mixed", "unknown"])
def test_h1_rejects_mixed_or_unknown_backends(damage):
    rows = holdout_rows()
    if damage == "mixed":
        rows[0]["result"]["backend"] = "cached"
    else:
        for row in rows:
            row["result"]["backend"] = "unregistered"
    assert runner.holdout_decision(config(), rows, True)["status"] == "incomplete_or_invalid"


def test_h1_incomplete_gate_never_reports_a_signal():
    assert runner.holdout_decision(config(), holdout_rows(), False)["status"] == "incomplete_or_invalid"


@pytest.mark.parametrize("missing", ["opendrift", "xarray", "PyYAML", "netCDF4", "shapely"])
def test_missing_generation_dependency_blocks_without_imports(monkeypatch, missing):
    env = ready_generation_environment()
    del env["packages"][missing]

    def forbidden_import(*args, **kwargs):
        raise AssertionError("check_imports=False must not import generation packages")

    monkeypatch.setattr(runner.importlib, "import_module", forbidden_import)
    result = runner.generation_dependencies(env, check_imports=False)
    assert result["status"] == "blocked"
    assert any(missing in error for error in result["errors"])
    assert result["imported"] == []
    assert not result["drift_generation_performed"]


def test_generation_dependency_version_gate_and_ready_metadata_only():
    env = ready_generation_environment()
    ready = runner.generation_dependencies(env, check_imports=False)
    assert ready["status"] == "ready" and ready["imported"] == []
    env["packages"]["shapely"] = "1.8.5"
    blocked = runner.generation_dependencies(env, check_imports=False)
    assert blocked["status"] == "blocked"
    assert any("Shapely 2+" in error for error in blocked["errors"])


def test_selection_cannot_be_created_after_new_inputs_exist(tmp_path, monkeypatch):
    stub_development_evidence(monkeypatch, development_rows())
    runner.save(tmp_path / "protocol.json", {})
    (tmp_path / "inputs").mkdir()
    with pytest.raises(ValueError, match="Backend must be locked before new particle preparation"):
        runner.select_backend(config(), ROOT / "configs/eight_neighbor_followup.json", tmp_path)
    assert not (tmp_path / "selection.json").exists()


def test_selection_cannot_change_after_it_is_locked(tmp_path, monkeypatch):
    rows = development_rows()
    stub_development_evidence(monkeypatch, rows)
    runner.save(tmp_path / "protocol.json", {})
    runner.select_backend(config(), ROOT / "configs/eight_neighbor_followup.json", tmp_path)
    before = (tmp_path / "selection.json").read_bytes()
    set_hits(rows, 0, "cached", (2.0, None, None))
    with pytest.raises(ValueError, match="Locked backend selection cannot be replaced"):
        runner.select_backend(config(), ROOT / "configs/eight_neighbor_followup.json", tmp_path)
    assert (tmp_path / "selection.json").read_bytes() == before


def test_failed_p0_cannot_fall_back_to_original_and_enter_holdout(tmp_path, monkeypatch):
    rows = development_rows()
    stub_development_evidence(monkeypatch, rows)
    monkeypatch.setattr(runner, "require_complete", lambda out, stage:
                        [dict(result=dict(audit=dict(passed=False)))] if stage == "P0" else rows)
    with pytest.raises(ValueError, match="Strict equivalence audit failed"):
        runner.select_backend(config(), ROOT / "configs/eight_neighbor_followup.json", tmp_path)
    assert not (tmp_path / "selection.json").exists()


def test_prepare_inputs_requires_locked_selection_before_forcing_or_generation(tmp_path, monkeypatch):
    from asar_repro import physical_followup_data

    events = []
    monkeypatch.setattr(runner, "verify_dev", lambda *args: events.append("dev") or {})

    def missing_selection(out):
        events.append("selection")
        raise ValueError("missing locked selection")

    def forbidden_generation(*args, **kwargs):
        raise AssertionError("Input preparation ran before selection")

    monkeypatch.setattr(runner, "verify_selection", missing_selection)
    monkeypatch.setattr(physical_followup_data, "forcing_inventory", forbidden_generation)
    monkeypatch.setattr(physical_followup_data, "prepare_case", forbidden_generation)
    with pytest.raises(ValueError, match="missing locked selection"):
        runner.prepare_inputs(config(), ROOT / "configs/eight_neighbor_followup.json", tmp_path)
    assert events == ["dev", "selection"]
    assert not (tmp_path / "inputs").exists()


def test_freeze_holdout_requires_complete_common_initializations(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "verify_dev", lambda *args: {})
    monkeypatch.setattr(runner, "verify_prepared", lambda out: ({}, {}))

    def incomplete_initialization(out, stage):
        assert stage == "S30"
        raise ValueError("S30 must be complete and valid")

    monkeypatch.setattr(runner, "require_complete", incomplete_initialization)
    with pytest.raises(ValueError, match="S30 must be complete and valid"):
        runner.freeze_holdout(config(), ROOT / "configs/eight_neighbor_followup.json", tmp_path)
    assert not (tmp_path / "holdout_protocol.json").exists()


def test_result_audit_charges_conservative_offset_and_excludes_late_best():
    seed = [0, 1]
    problem = ReplayStub({(0, 1): dict(J=3.0, pd_final=0.7)})
    raw = dict(status="budget_exceeded", stop_reason="max_seconds", wall_s=5.0,
               J=1.0, history=[
                   dict(source="initial_route", waypoints=seed, elapsed_s=0.01, J=3.0, pd_final=0.7),
                   dict(source="search", waypoints=[0, 2], elapsed_s=4.99, J=2.0, pd_final=0.8),
                   dict(source="search", waypoints=[0, 3], elapsed_s=5.001, J=1.0, pd_final=0.9),
               ])
    result = runner.audit_search_result(problem, seed, dict(seconds=5, connectivity=8),
                                        raw, external_wall=5.02, cpu_s=4.9, tolerance=1e-8)
    assert result["status"] == "valid"
    assert result["J"] == 3.0
    assert len(result["history"]) == 1
    assert result["best_found_elapsed_s"] == pytest.approx(0.03)
    assert result["conservative_clock_offset_s"] == pytest.approx(0.02)
    assert result["budget_overshoot_s"] == pytest.approx(0.02)
    assert all(route == (0, 1) and connectivity == 8 for route, connectivity in problem.calls)


@pytest.mark.parametrize("status", ["failed", "blocked", "fatal", "invalid", "solver_error"])
def test_failed_backend_cannot_be_hidden_by_valid_initial_route(status):
    seed = [0, 1]
    problem = ReplayStub({(0, 1): dict(J=3.0, pd_final=0.7)})
    raw = dict(status=status, error="synthetic failure", wall_s=5.0, history=[
        dict(source="initial_route", waypoints=seed, elapsed_s=0.01, J=3.0, pd_final=0.7)])
    with pytest.raises(ValueError, match="cannot conceal error with initial route"):
        runner.audit_search_result(problem, seed, dict(seconds=5, connectivity=8),
                                   raw, external_wall=5.0, cpu_s=4.9, tolerance=1e-8)
    assert problem.calls == []


def test_initial_route_validated_after_deadline_is_not_a_fallback():
    seed = [0, 1]
    problem = ReplayStub({(0, 1): dict(J=3.0, pd_final=0.7)})
    raw = dict(status="budget_exceeded", wall_s=5.0, history=[
        dict(source="initial_route", waypoints=seed, elapsed_s=4.99, J=3.0, pd_final=0.7)])
    with pytest.raises(ValueError, match="Shared initial route not fully evaluated inside budget"):
        runner.audit_search_result(problem, seed, dict(seconds=5, connectivity=8),
                                   raw, external_wall=5.02, cpu_s=4.9, tolerance=1e-8)


def test_result_audit_rejects_replay_disagreement():
    seed = [0, 1]
    problem = ReplayStub({(0, 1): dict(J=3.1, pd_final=0.7)})
    raw = dict(status="completed", wall_s=1.0, history=[
        dict(source="initial_route", waypoints=seed, elapsed_s=0.01, J=3.0, pd_final=0.7)])
    with pytest.raises(ValueError, match="Physical replay or monotone-incumbent audit failed"):
        runner.audit_search_result(problem, seed, dict(seconds=5, connectivity=8),
                                   raw, external_wall=1.0, cpu_s=0.9, tolerance=1e-8)
