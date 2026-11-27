"""Protocol tests delivered for local execution; no experiments run at import."""
from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "physical_study_runner_for_tests", ROOT / "scripts/run_eight_neighbor_physical.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def config():
    return json.loads((ROOT / "configs/eight_neighbor_physical.json").read_text(encoding="utf-8"))


def real_rows(stage="B5", heading=(99.0, 100.0), axis=(99.5, 100.0)):
    cfg = config()
    rows = []
    for task in runner.tasks_for(cfg, stage, []):
        index = cfg["primary_scenes"].index(task["scene"])
        eight = heading[index] if task["footprint"] == "heading_square" else axis[index]
        rows.append(dict(task=task, result=dict(J=100.0 if task["connectivity"] == 4 else eight)))
    return rows


def diagnostic_rows():
    cfg = config()
    cases = ["diagonal_intercept", "late_drift", "repeat_detection",
             "special_mass", "coverage_tradeoff", "turning_footprint"]
    rows = []
    for task in runner.tasks_for(cfg, "A", cases):
        optimum = 1.0 if task["connectivity"] == 4 else 0.9
        if task["method"] == "oracle":
            result = dict(J=optimum, numerical_optimum_complete=True)
        else:
            result = dict(J=1.1, history=[dict(J=1.2)])
        rows.append(dict(task=task, result=result))
    return rows


def test_registered_budgets_and_same_budget_controls():
    cfg = config()
    design = runner.plan(cfg)
    assert design["total_tasks"] == 96
    assert design["algorithm_budget_s"] == 1128
    assert design["stages"]["A"] == dict(tasks=48, algorithm_budget_s=288)
    for stage, seconds in (("B5", 5), ("B30", 30)):
        tasks = runner.tasks_for(cfg, stage, [])
        assert len(tasks) == 24
        assert {t["seconds"] for t in tasks} == {seconds}
        assert {t["footprint"] for t in tasks} == {"heading_square", "axis_square"}
        assert len({runner.task_id(t) for t in tasks}) == len(tasks)
        assert tasks == runner.tasks_for(cfg, stage, [])


def test_late_incumbent_and_conservative_offset_are_excluded():
    raw = dict(history=[
        dict(elapsed_s=5.001, J=1.0, pd_final=0.9),
        dict(elapsed_s=4.99, J=2.0, pd_final=0.8),
        dict(elapsed_s=0.01, J=3.0, pd_final=0.7)])
    accepted = runner.selected_history(raw, seconds=5.0, offset=0.02)
    assert [r["J"] for r in accepted] == [3.0]
    assert accepted[0]["elapsed_s"] == pytest.approx(0.03)


@pytest.mark.parametrize("field,value", [
    ("elapsed_s", math.nan), ("elapsed_s", math.inf), ("elapsed_s", -0.1),
    ("J", math.nan), ("pd_final", math.inf)])
def test_invalid_history_is_not_silently_cleaned(field, value):
    row = dict(elapsed_s=0.1, J=1.0, pd_final=0.5)
    row[field] = value
    with pytest.raises(ValueError):
        runner.selected_history(dict(history=[row]), seconds=5.0, offset=0.0)


def test_primary_and_same_budget_sensor_pass():
    decision = runner.paired_decision(config(), real_rows(), True, stage="B5")
    assert decision["status"] == "screen_passed_pending_holdout"
    assert decision["main_quality_pass"] and decision["sensitivity_pass"]


def test_proxy_dependent_improvement_is_labeled_sensor_sensitive():
    rows = real_rows(axis=(100.0, 100.0))
    decision = runner.paired_decision(config(), rows, True)
    assert decision["status"] == "sensor_sensitive"
    assert not decision["sensitivity_pass"]


def test_main_other_scene_regression_blocks_quality_even_with_large_gain():
    rows = real_rows(heading=(90.0, 100.1), axis=(90.0, 100.0))
    decision = runner.paired_decision(config(), rows, True)
    assert decision["status"] == "screen_not_passed"


def test_axis_large_regression_blocks_sensitivity():
    rows = real_rows(axis=(99.0, 100.6))
    decision = runner.paired_decision(config(), rows, True)
    assert decision["status"] == "sensor_sensitive"


def test_b30_cannot_report_b5_screen_pass_or_mix_budgets():
    cfg = config()
    long_rows = real_rows(stage="B30")
    decision = runner.paired_decision(cfg, long_rows, True, stage="B30")
    assert decision["status"] == "longer_budget_signal_pending_followup"
    assert runner.paired_decision(cfg, long_rows, True, stage="B5")["status"] == "incomplete_or_invalid"
    assert runner.paired_decision(cfg, real_rows(), False)["status"] == "incomplete_or_invalid"


@pytest.mark.parametrize("damage", ["missing", "duplicate", "nan"])
def test_real_decision_requires_complete_valid_matrix(damage):
    rows = real_rows()
    if damage == "missing":
        rows.pop()
    elif damage == "duplicate":
        rows[-1] = deepcopy(rows[0])
    else:
        rows[0]["result"]["J"] = math.nan
    assert runner.paired_decision(config(), rows, True)["status"] == "incomplete_or_invalid"


def test_a_needs_complete_enumeration_and_strict_diagonal_witness():
    cfg = config()
    rows = diagnostic_rows()
    assert runner.diagnostic_gate(cfg, rows, True)["passed"]
    assert not runner.diagnostic_gate(cfg, rows, False)["passed"]
    for row in rows:
        if row["task"]["case"] == "diagonal_intercept" and row["task"]["method"] == "oracle":
            row["result"]["J"] = 1.0
    decision = runner.diagnostic_gate(cfg, rows, True)
    assert not decision["passed"]
    assert not decision["same_speed_diagonal_witness"]


def test_a_cannot_treat_timeout_or_better_than_oracle_as_proof():
    cfg = config()
    rows = diagnostic_rows()
    oracle = next(r for r in rows if r["task"]["method"] == "oracle")
    oracle["result"]["numerical_optimum_complete"] = False
    assert not runner.diagnostic_gate(cfg, rows, True)["passed"]
    rows = diagnostic_rows()
    search = next(r for r in rows if r["task"]["method"] == "search")
    search["result"]["J"] = 0.1
    assert not runner.diagnostic_gate(cfg, rows, True)["passed"]


def test_a_rejects_missing_or_duplicate_records():
    cfg = config()
    rows = diagnostic_rows()
    assert not runner.diagnostic_gate(cfg, rows[:-1], True)["passed"]
    rows[-1] = deepcopy(rows[0])
    assert not runner.diagnostic_gate(cfg, rows, True)["passed"]


def test_incomplete_and_failed_evidence_is_preserved(tmp_path):
    task = runner.tasks_for(config(), "B5", [])[0]
    folder = tmp_path / "runs" / runner.task_id(task)
    folder.mkdir(parents=True)
    (folder / "stdout.log").write_text("existing evidence", encoding="utf-8")
    with pytest.raises(ValueError, match="Incomplete run directory preserved"):
        runner.load_record(config(), tmp_path, task, "protocol-hash")
    runner.save(folder / "record.json", dict(task=task, protocol_sha256="protocol-hash", status="failed"))
    with pytest.raises(ValueError, match="Failed/blocked run is preserved"):
        runner.load_record(config(), tmp_path, task, "protocol-hash")
    assert (folder / "stdout.log").read_text(encoding="utf-8") == "existing evidence"


def test_changed_raw_result_is_rejected(tmp_path):
    task = runner.tasks_for(config(), "B5", [])[0]
    folder = tmp_path / "runs" / runner.task_id(task)
    runner.save(folder / "result.json", dict(task=task, result=dict(status="valid")))
    runner.save(folder / "record.json", dict(task=task, protocol_sha256="protocol-hash",
        status="completed", result_sha256=runner.digest(folder / "result.json")))
    assert runner.load_record(config(), tmp_path, task, "protocol-hash") is not None
    (folder / "result.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="Raw result changed"):
        runner.load_record(config(), tmp_path, task, "protocol-hash")

