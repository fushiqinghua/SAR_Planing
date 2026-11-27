"""Local protocol-risk tests, prepared without executing pytest or the runner.

Synthetic records exercise accounting and decision boundaries; they are not
experimental results. No real-data search or drift generation is launched.
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
    "physical_confirmation_runner_for_tests", ROOT / "scripts/run_eight_neighbor_confirmation.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def config():
    return json.loads((ROOT / "configs/eight_neighbor_confirmation.json").read_text(encoding="utf-8"))


def rows_for(stage, J=100.0, pd=0.95):
    rows = []
    for task in runner.tasks_for(config(), stage):
        rows.append(dict(task=task, run_id=runner.task_id(task), result=dict(
            J=J, pd_final=pd, stop_reason="max_seconds",
            history=[dict(elapsed_s=0.1, J=J, pd_final=pd, source="initial_route")])))
    return rows


def improve_one_primary(rows, J=99.0):
    for row in rows:
        task = row["task"]
        if (task["case"], task["footprint"], task["connectivity"], task["method"]) == (
                "hudson_window_early", "heading_square", 4, "completion_J"):
            row["result"]["J"] = J
            row["result"]["history"].append(dict(elapsed_s=1.0, J=J, pd_final=0.95, source="completion"))


def set_hits(rows, method, times, target_index=0):
    target = config()["development_targets"][target_index]
    for row in rows:
        task = row["task"]
        if task["method"] != method or any(task[k] != target[k] for k in ("case", "footprint", "connectivity")):
            continue
        value = times[task["repetition"]]
        if value is not None:
            row["result"]["J"] = target["J"]
            row["result"]["history"].append(dict(elapsed_s=value, J=target["J"], pd_final=0.95, source="search"))


def test_registered_identity_and_bounded_matrix():
    cfg = config()
    assert runner.object_digest(cfg) == runner.REGISTERED_CONFIG_HASH
    result = runner.plan(cfg)
    assert result["status"] == "plan_not_results"
    assert result["formal_tasks"] == 112
    assert result["formal_algorithm_budget_s"] == 3120
    assert result["stages"] == {
        "D5": dict(tasks=24, algorithm_budget_s=120),
        "D30": dict(tasks=72, algorithm_budget_s=2160),
        "G30": dict(tasks=12, algorithm_budget_s=360),
        "R120": dict(tasks=4, algorithm_budget_s=480),
    }
    for stage in runner.STAGES:
        tasks = runner.tasks_for(cfg, stage)
        assert len(tasks) == len({runner.task_id(t) for t in tasks})
        assert tasks == runner.tasks_for(cfg, stage)
        assert {t["connectivity"] for t in tasks} == {4, 8}
    assert {t["method"] for t in runner.tasks_for(cfg, "R120")} == {"diagnostic_cached"}
    assert {t["repetition"] for t in runner.tasks_for(cfg, "R120")} == {0}
    assert "not_ready" in result["H2"]
    with pytest.raises(ValueError):
        runner.tasks_for(cfg, "H2")


def test_no_method_is_selected_without_a_new_gain():
    result = runner.method_decision(config(), rows_for("D5"), rows_for("D30"), True)
    assert result["quality_protected"]
    assert result["selected_method_for_H2"] == "cached_reference_v2"
    assert result["improved_primary_groups"] == 0


def test_one_primary_gain_is_sufficient_only_with_every_group_protected():
    d5, d30 = rows_for("D5"), rows_for("D30")
    improve_one_primary(d30)
    result = runner.method_decision(config(), d5, d30, True)
    assert result["selected_method_for_H2"] == "completion_J"
    assert len(result["comparisons"]) == 12
    for row in d30:
        if row["task"]["method"] == "completion_J" and row["task"]["footprint"] == "axis_square":
            row["result"]["J"] = 100.01
    assert runner.method_decision(config(), d5, d30, True)["selected_method_for_H2"] == "cached_reference_v2"


@pytest.mark.parametrize("damage", ["missing", "duplicate", "nan", "infinite", "wrong_budget"])
def test_invalid_or_incomplete_matrix_cannot_select_method(damage):
    rows = rows_for("D30")
    improve_one_primary(rows)
    if damage == "missing":
        rows.pop()
    elif damage == "duplicate":
        rows[-1] = deepcopy(rows[0])
    elif damage == "wrong_budget":
        rows[0]["task"]["seconds"] = 300
    else:
        rows[0]["result"]["J"] = math.nan if damage == "nan" else math.inf
    assert runner.method_decision(config(), rows_for("D5"), rows, True) == dict(
        status="incomplete_or_invalid", selected_method_for_H2=None)


def test_incomplete_flag_blocks_even_structurally_complete_rows():
    assert runner.method_decision(config(), rows_for("D5"), rows_for("D30"), False)["selected_method_for_H2"] is None


def test_hit_count_regression_blocks_quality_winner_without_imputing_censoring():
    d5, d30 = rows_for("D5"), rows_for("D30")
    improve_one_primary(d30)
    set_hits(d5, "diagnostic_cached", [1.0, 2.0, 3.0])
    set_hits(d5, "completion_J", [1.0, None, 2.0])
    result = runner.method_decision(config(), d5, d30, True)
    assert result["quality_protected"] and not result["target_hit_counts_protected"]
    assert result["selected_method_for_H2"] == "cached_reference_v2"
    target = result["targets"][0]
    assert target["relative_time_reduction"] is None
    assert target["methods"]["completion_J"]["times_s"] == [1.0, None, 2.0]
    assert target["methods"]["completion_J"]["median_if_all_hit_s"] is None


def test_full_hits_have_a_measured_median_speed_comparison():
    rows = rows_for("D5")
    set_hits(rows, "diagnostic_cached", [2.0, 2.1, 2.2])
    set_hits(rows, "completion_J", [1.0, 1.1, 1.2])
    result = runner.target_report(config(), rows)[0]
    assert result["relative_time_reduction"] == pytest.approx(1 - 1.1 / 2.1)


def guard_rows(*, gain_eight=0.0, delta_pd=0.0):
    rows = rows_for("G30")
    for row in rows:
        ref = runner.reference_for(config(), row["task"]["case"], row["task"]["footprint"])
        g = gain_eight if row["task"]["connectivity"] == 8 else 0.0
        row["result"].update(J=ref["J"] * (1 - g), pd_final=ref["pd_final"] + delta_pd)
    return rows


def test_returning_reference_is_feasible_but_is_not_joint_gain():
    result = runner.guard_decision(config(), guard_rows(), rows_for("D30"), True)
    assert result["all_repetitions_feasible"]
    assert not result["primary_joint_gain"]
    assert result["status"] == "feasible_without_required_joint_graph_gain"


def test_guard_joint_gain_requires_the_floor_in_every_repetition():
    rows = guard_rows(gain_eight=0.01)
    result = runner.guard_decision(config(), rows, rows_for("D30"), True)
    assert result["status"] == "guarded_joint_gain_development_signal"
    rows[0]["result"]["pd_final"] -= 1e-5
    result = runner.guard_decision(config(), rows, rows_for("D30"), True)
    assert result["status"] == "invalid_guard_violation"


def test_guard_still_compares_eight_with_the_same_guarded_four_method():
    rows = guard_rows(gain_eight=0.01)
    for row in rows:
        if row["task"]["connectivity"] == 4:
            row["result"]["J"] *= 0.98
    result = runner.guard_decision(config(), rows, rows_for("D30"), True)
    assert result["primary_joint_gain"] and not result["guarded_graph_signal"]
    assert result["status"] != "guarded_joint_gain_development_signal"


def point(J, pd, elapsed, route):
    return dict(J=J, pd_final=pd, elapsed_s=elapsed, waypoints=route, source="search")


def test_outer_clock_rebuild_restores_earlier_point_removed_by_later_dominator():
    early = point(10, 0.8, 1.0, [0, 1])
    late = point(9, 0.9, 4.9, [0, 2])
    raw = dict(archive_enabled=True, pareto_archive=[late], pareto_archive_history=[early, late])
    front, count = runner.timely_pareto(raw, 5, 0.2)
    assert len(front) == count == 1
    assert front[0]["J"] == 10
    assert front[0]["elapsed_s"] == pytest.approx(1.2)
    front, count = runner.timely_pareto(raw, 5, 0.0)
    assert count == 2 and [r["J"] for r in front] == [9]


@pytest.mark.parametrize("damage", ["no_history", "nan", "decreasing_time", "infinite_metric"])
def test_invalid_archive_evidence_is_blocked(damage):
    raw = dict(archive_enabled=True, pareto_archive_history=[point(10, .8, 1, [0, 1])])
    if damage == "no_history":
        raw.pop("pareto_archive_history")
    elif damage == "nan":
        raw["pareto_archive_history"][0]["elapsed_s"] = math.nan
    elif damage == "infinite_metric":
        raw["pareto_archive_history"][0]["J"] = math.inf
    else:
        raw["pareto_archive_history"].append(point(9, .9, 0.1, [0, 2]))
    with pytest.raises(ValueError):
        runner.timely_pareto(raw, 5, 0)


class ReplayStub:
    def __init__(self, scores):
        self.scores = scores

    def replay(self, route, connectivity):
        return dict(self.scores[tuple(route)], waypoints=list(route))


def audit_fixture(method="completion_pd_guard"):
    cfg = config()
    task = next(t for t in runner.tasks_for(cfg, "G30" if method == "completion_pd_guard" else "D5")
                if t["method"] == method and t["footprint"] == "heading_square" and t["connectivity"] == 8)
    ref = dict(J=10, pd_final=.8, waypoints=[0, 1], run_id="frozen", waypoints_sha256=runner.object_digest([0, 1]))
    options = runner.options_for(cfg, task, ref)
    raw = dict(options, connectivity=8, footprint="heading_square", max_seconds=task["seconds"],
               max_expansions=None, status="budget_exceeded", stop_reason="max_seconds", wall_s=float(task["seconds"]),
               history=[dict(point(10, .8, .1, [0, 1]), source="initial_route"), point(9, .82, 1, [0, 2])],
               pareto_archive_history=[], diagnostics=dict(first_terminal_generated_s=.5, first_new_complete_replay_s=1.0))
    raw["archive_enabled"] = raw.pop("archive")
    problem = ReplayStub({(0, 1): dict(J=10, pd_final=.8), (0, 2): dict(J=9, pd_final=.82)})
    return cfg, task, ref, raw, problem


def test_audit_applies_same_outer_clock_to_diagnostic_times_and_incumbents():
    cfg, task, ref, raw, problem = audit_fixture()
    result = runner.audit_result(cfg, problem, ref, task, raw, task["seconds"] + .2, 1)
    assert result["J"] == 9
    assert result["diagnostic_times"]["first_terminal_generated_s"] == pytest.approx(.7)
    assert result["diagnostic_times"]["first_new_complete_replay_s"] == pytest.approx(1.2)
    raw["diagnostics"]["first_terminal_generated_s"] = task["seconds"] - .1
    result = runner.audit_result(cfg, problem, ref, task, raw, task["seconds"] + .2, 1)
    assert result["diagnostic_times"]["first_terminal_generated_s"] is None


@pytest.mark.parametrize("key,value", [("connectivity", 4), ("pd_floor", .79),
    ("completion", "none"), ("objective", "J"), ("max_expansions", 128),
    ("archive_enabled", False), ("max_seconds", 300)])
def test_worker_cannot_mislabel_backend_options(key, value):
    cfg, task, ref, raw, problem = audit_fixture()
    raw[key] = value
    with pytest.raises(ValueError, match="Backend options"):
        runner.audit_result(cfg, problem, ref, task, raw, task["seconds"], 1)


def test_guard_audit_checks_every_credited_incumbent_not_only_final():
    cfg, task, ref, raw, problem = audit_fixture()
    raw["history"].insert(1, point(9.5, .7, .5, [0, 3]))
    problem.scores[(0, 3)] = dict(J=9.5, pd_final=.7)
    with pytest.raises(ValueError, match="probability floor"):
        runner.audit_result(cfg, problem, ref, task, raw, task["seconds"], 1)


def test_late_best_route_cannot_be_reported_as_the_budgeted_result():
    cfg, task, ref, raw, problem = audit_fixture()
    raw["history"][-1]["elapsed_s"] = task["seconds"] - .1
    result = runner.audit_result(cfg, problem, ref, task, raw, task["seconds"] + .2, 1)
    assert result["J"] == ref["J"]
    assert len(result["history"]) == 1


def test_stronger_four_reference_is_labelled_mixed_budget_and_r120_pair_is_explicit():
    rows = [r for stage in runner.STAGES for r in rows_for(stage)]
    result = runner.reference_diagnostics(config(), rows, True)
    assert result["status"] == "diagnostic_only"
    assert len(result["r120_paired_comparisons"]) == 2
    assert all(r["repetitions"] == 1 and not r["significance_claim"] for r in result["r120_paired_comparisons"])
    assert "upper bound" in result["meaning"] and "mixed" in result["budget_warning"]


def test_stage_gate_does_not_launch_when_an_earlier_stage_is_incomplete(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "verify", lambda *args: {})
    called = []
    def incomplete(*args):
        raise ValueError("D5 is incomplete")
    monkeypatch.setattr(runner, "require_complete", incomplete)
    monkeypatch.setattr(runner, "launch_task", lambda *args: called.append(args))
    with pytest.raises(ValueError):
        runner.run_stage(config(), runner.DEFAULT_CONFIG, tmp_path, "D30")
    assert called == []


def test_failed_or_partial_run_directory_is_preserved(monkeypatch, tmp_path):
    task = runner.tasks_for(config(), "D5")[0]
    folder = tmp_path / "runs" / runner.task_id(task)
    folder.mkdir(parents=True)
    marker = folder / "stdout.log"
    marker.write_text("incomplete evidence", encoding="utf-8")
    with pytest.raises(ValueError, match="Incomplete"):
        runner.load_record(config(), tmp_path, task)
    assert marker.read_text(encoding="utf-8") == "incomplete evidence"


def test_aggregation_keeps_user_analysis_and_writes_all_stage_rows(monkeypatch, tmp_path):
    import csv
    manual = tmp_path / "ANALYSIS.md"
    manual.write_text("User interpretation must be retained", encoding="utf-8")
    monkeypatch.setattr(runner, "verify", lambda *args: {})
    def synthetic_collect(cfg, out, stage):
        rows = rows_for(stage)
        for row in rows:
            # The method occurs in both task and result in real records.
            row["result"].update(method=row["task"]["method"], raw_solver={})
            row["record"] = dict(peak_rss_bytes=1234)
        return dict(stage=stage, planned=len(rows), completed=len(rows), status="complete", missing=[], errors=[]), rows
    monkeypatch.setattr(runner, "collect", synthetic_collect)
    runner.analyze(config(), runner.DEFAULT_CONFIG, tmp_path)
    assert manual.read_text(encoding="utf-8") == "User interpretation must be retained"
    assert (tmp_path / "REPORT.md").is_file()
    assert json.loads((tmp_path / "summary.json").read_text())["status"] == "complete"
    with (tmp_path / "comparison.csv").open(encoding="utf-8-sig", newline="") as stream:
        assert len(list(csv.DictReader(stream))) == 112
