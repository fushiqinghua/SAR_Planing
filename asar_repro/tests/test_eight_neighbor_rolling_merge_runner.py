"""Local protocol checks prepared for the user; not executed at delivery."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "rolling_merge_runner_under_test", ROOT / "scripts/run_eight_neighbor_rolling_merge.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def config():
    return json.loads((ROOT / "configs/eight_neighbor_rolling_merge.json").read_text(encoding="utf-8"))


def merge_raw(variant, *, children=2000, duplicates=100):
    cfg = config()
    counts = {name: 0 for name in runner.MERGE_COUNTS}
    counts.update(mode=runner.MERGE_MODE[variant], max_entries=16384, max_payload_bytes=67108864,
        nonterminal_children=children, mergeable_children=duplicates, equal_J_duplicates=duplicates,
        discarded_children=duplicates if variant != "D0" else 0,
        entries=10, entries_peak=10, payload_bytes=40000, payload_bytes_peak=40000,
        lookup_s=0.01, key_build_s=0.005)
    return dict(method=runner.BASE_METHOD[variant], variant=variant,
        merging=dict(cfg["merging"], mode=runner.MERGE_MODE[variant]),
        phases=[dict(stage_index=0, inner=dict(state_merge=counts))])


def diagnostic_rows(*, children=2000, duplicates=100):
    return [dict(run_id=f"D0_fake_{index}", record={"result_sha256": str(index)},
        task=dict(stage="D0", instance=instance, method="D0", repetition=0),
        result=dict(raw=merge_raw("D0", children=children, duplicates=duplicates)))
        for index, instance in enumerate(runner.SELECTED)]


def formal_rows(values):
    rows = []
    for index, instance in enumerate(runner.SELECTED):
        for method in config()["methods"]:
            for repetition in range(3):
                J, pd = values[index][method]
                rows.append(dict(run_id=f"F30_{index}_{method}_{repetition}",
                    task=dict(stage="F30", instance=instance, method=method, repetition=repetition,
                        seconds=30, connectivity=8, footprint="heading_square",
                        base_scene="lake_ontario" if instance.startswith("lake_") else "arctic_ocean"),
                    result=dict(J=J, pd_final=pd)))
    return rows


def test_registered_configuration_and_frozen_stage_totals():
    cfg = config()
    assert runner.check_config(cfg) is cfg
    plan = runner.plan(cfg)
    assert plan["D0_algorithm_budget_s"] == 120
    assert plan["F30_conditional_algorithm_budget_s"] == 1440
    assert plan["maximum_algorithm_budget_s"] == 1560
    cfg["diagnostic_gate"]["minimum_mergeable_fraction"] = 0.01
    with pytest.raises(ValueError, match="Unregistered"):
        runner.check_config(cfg)


def test_two_stage_matrix_has_distinct_stable_ids():
    cfg = config()
    evidence = dict(instances={}, archive_hashes={}, references={})
    for index, identity in enumerate(runner.SELECTED):
        evidence["instances"][identity] = dict(base_scene="lake_ontario" if identity.startswith("lake_") else "arctic_ocean",
            block_id=identity.rsplit("_s", 1)[0], seed=3101 + index)
        evidence["archive_hashes"][identity] = {"manifest_sha256": str(index)}
        evidence["references"][identity] = {"waypoints": [index]}
    d0 = runner.make_tasks(cfg, evidence, "D0")
    f30 = runner.make_tasks(cfg, evidence, "F30")
    assert len(d0) == 4 and len(f30) == 48
    assert {task["method"] for task in d0} == {"D0"}
    assert {task["method"] for task in f30} == {"C0", "C1", "C0_M", "C1_M"}
    assert len({runner.task_id(task) for task in d0 + f30}) == 52
    assert runner.make_tasks(cfg, evidence, "F30") == f30
    assert sum(task["seconds"] for task in d0 + f30) == 1560


def test_diagnostic_requires_fraction_and_count_in_same_instance():
    rows = diagnostic_rows(children=4000, duplicates=100)
    assert not runner.diagnostic_gate(config(), rows, complete=True)["passed"]
    rows = diagnostic_rows(children=1000, duplicates=99)
    assert not runner.diagnostic_gate(config(), rows, complete=True)["passed"]
    rows = diagnostic_rows(children=2000, duplicates=0)
    rows[0]["result"]["raw"] = merge_raw("D0", children=2000, duplicates=100)
    decision = runner.diagnostic_gate(config(), rows, complete=True)
    assert decision["passed"] and decision["qualifying_instances"] == 1
    assert decision["instances"][0]["mergeable_fraction"] == 0.05


def test_diagnostic_missing_duplicate_or_invalid_matrix_cannot_admit():
    rows = diagnostic_rows()
    assert not runner.diagnostic_gate(config(), rows[:3], complete=True)["passed"]
    assert not runner.diagnostic_gate(config(), [rows[0]] * 4, complete=True)["passed"]
    assert not runner.diagnostic_gate(config(), rows, complete=False)["passed"]
    zero = diagnostic_rows(children=0, duplicates=0)
    assert not runner.diagnostic_gate(config(), zero, complete=True)["passed"]


def test_shadow_pruning_and_counter_tampering_are_rejected():
    raw = merge_raw("D0")
    raw["phases"][0]["inner"]["state_merge"]["discarded_children"] = 1
    with pytest.raises(ValueError, match="Shadow"):
        runner.validate_merge_evidence(raw, "D0", config())
    raw = merge_raw("C0_M")
    raw["phases"][0]["inner"]["state_merge"]["payload_bytes_peak"] = 67108865
    with pytest.raises(ValueError, match="storage limits"):
        runner.validate_merge_evidence(raw, "C0_M", config())
    raw = merge_raw("D0")
    raw["phases"][0]["inner"]["state_merge"]["nonterminal_children"] = True
    with pytest.raises(ValueError, match="counter"):
        runner.validate_merge_evidence(raw, "D0", config())


def test_controls_cannot_silently_enable_merging():
    with pytest.raises(ValueError, match="unchanged pilot"):
        runner.validate_merge_evidence(dict(method="C0", merging={}), "C0", config())
    with pytest.raises(ValueError, match="unchanged pilot"):
        runner.validate_merge_evidence(dict(method="C1", variant="C1_M"), "C1", config())


def test_variant_mapping_reuses_original_auditor_without_altering_raw(monkeypatch):
    cfg = config()
    raw = merge_raw("C1_M")
    task = dict(stage="F30", method="C1_M")
    result = dict(method="C1_M", raw=raw)
    calls = []
    monkeypatch.setattr(runner._legacy, "verify_result", lambda t, r, p: calls.append((t, r, p)))
    protocol = dict(config=cfg)
    runner.verify_result(task, result, protocol)
    assert calls[0][0]["method"] == calls[0][1]["method"] == "C1"
    assert calls[0][1]["raw"] is raw
    assert calls[0][2] is protocol
    assert task["method"] == result["method"] == "C1_M"
    result["raw"]["method"] = "C0"
    with pytest.raises(ValueError, match="underlying pilot"):
        runner.verify_result(task, result, protocol)


def test_original_audit_failure_remains_fatal(monkeypatch):
    def failed(*args):
        raise ValueError("original causal audit failure")
    monkeypatch.setattr(runner._legacy, "verify_result", failed)
    with pytest.raises(ValueError, match="original causal audit failure"):
        runner.verify_result(dict(stage="D0", method="D0"),
            dict(method="D0", raw=merge_raw("D0")), dict(config=config()))


def test_all_pair_gates_do_not_misattribute_generic_merging_to_rolling():
    # Both M methods beat their old counterparts, but rolling adds nothing over C0_M.
    values = [dict(C0=(10.0, .9), C1=(10.1, .9), C0_M=(9.8, .9), C1_M=(9.8, .9)) for _ in runner.SELECTED]
    answer = runner.decision(config(), formal_rows(values), complete=True)
    assert answer["pair_gates"]["C0_M_vs_C0"]["screen_passed"]
    assert answer["pair_gates"]["C1_M_vs_C1"]["screen_passed"]
    assert not answer["pair_gates"]["C1_M_vs_C0_M"]["screen_passed"]
    assert not answer["rolling_candidate_continue"]


def test_rolling_must_also_beat_original_strong_control():
    values = [dict(C0=(10.0, .9), C1=(10.5, .9), C0_M=(10.4, .9), C1_M=(10.2, .9)) for _ in runner.SELECTED]
    answer = runner.decision(config(), formal_rows(values), complete=True)
    assert answer["pair_gates"]["C1_M_vs_C0_M"]["screen_passed"]
    assert not answer["pair_gates"]["C1_M_vs_C0"]["screen_passed"]
    assert not answer["rolling_candidate_continue"]


def test_original_quality_gate_keeps_lake_ties_and_pd_guard():
    values = [dict(C0=(10.0, .9), C1=(10.0, .9), C0_M=(10.0, .9), C1_M=(10.0, .9)) for _ in runner.SELECTED]
    for index in (2, 3):
        values[index]["C1_M"] = (9.8, .9)
    answer = runner.decision(config(), formal_rows(values), complete=True)
    assert answer["pair_gates"]["C1_M_vs_C0_M"]["instance_winners"] == 2
    assert not answer["rolling_candidate_continue"]
    for value in values:
        value["C1_M"] = (9.8, .89)
    answer = runner.decision(config(), formal_rows(values), complete=True)
    assert not answer["pair_gates"]["C1_M_vs_C0_M"]["pd_protected"]
    assert not answer["rolling_candidate_continue"]


def test_actual_median_J_run_supplies_its_own_pd():
    values = [dict(C0=(10.0, .9), C1=(10.0, .9), C0_M=(10.0, .9), C1_M=(9.8, .9)) for _ in runner.SELECTED]
    rows = formal_rows(values)
    selected = [row for row in rows if row["task"]["instance"] == runner.SELECTED[0]
                and row["task"]["method"] == "C1_M"]
    selected[0]["result"] = dict(J=9.7, pd_final=.99)
    selected[1]["result"] = dict(J=9.8, pd_final=.89)
    selected[2]["result"] = dict(J=9.9, pd_final=.98)
    answer = runner.decision(config(), rows, complete=True)
    pair = answer["pair_gates"]["C1_M_vs_C0"]["comparisons"][0]
    assert pair["pd_candidate"] == .89 and pair["pd_drop_flag"]
    assert not answer["rolling_candidate_continue"]


def test_failed_or_duplicate_formal_matrix_has_no_adoption_decision():
    values = [dict(C0=(10.0, .9), C1=(10.0, .9), C0_M=(10.0, .9), C1_M=(9.8, .9)) for _ in runner.SELECTED]
    rows = formal_rows(values)
    assert runner.decision(config(), rows, complete=True)["rolling_candidate_continue"]
    assert not runner.decision(config(), rows[:-1], complete=True)["rolling_candidate_continue"]
    assert not runner.decision(config(), rows[:-1] + [rows[0]], complete=True)["rolling_candidate_continue"]
    assert not runner.decision(config(), rows, complete=False)["rolling_candidate_continue"]


def test_f30_gate_binds_raw_records_and_cannot_be_flipped(tmp_path, monkeypatch):
    cfg, rows = config(), diagnostic_rows()
    runner.save(tmp_path / "protocol.json", {"identity": "fixed"})
    status = dict(status="complete", planned=4, valid=4, missing=[], errors=[])
    protocol, tasks = dict(config=cfg), {"D0": [], "F30": []}
    monkeypatch.setattr(runner, "collect", lambda *args: (status, rows))
    with pytest.raises(ValueError, match="F30 blocked"):
        runner.require_d0_gate(tmp_path, protocol, tasks)
    payload = runner.gate_payload(tmp_path, cfg, status, rows)
    runner.save(tmp_path / "D0_gate.json", payload)
    assert runner.require_d0_gate(tmp_path, protocol, tasks)["decision"]["passed"]
    rows[0]["record"]["result_sha256"] = "altered"
    with pytest.raises(ValueError, match="F30 blocked"):
        runner.require_d0_gate(tmp_path, protocol, tasks)


def test_negative_d0_gate_is_preserved_but_blocks_f30(tmp_path, monkeypatch):
    cfg, rows = config(), diagnostic_rows(children=2000, duplicates=0)
    runner.save(tmp_path / "protocol.json", {"identity": "fixed"})
    status = dict(status="complete", planned=4, valid=4, missing=[], errors=[])
    monkeypatch.setattr(runner, "collect", lambda *args: (status, rows))
    payload = runner.gate_payload(tmp_path, cfg, status, rows)
    runner.save(tmp_path / "D0_gate.json", payload)
    with pytest.raises(ValueError, match="F30 blocked"):
        runner.require_d0_gate(tmp_path, dict(config=cfg), {})
    assert not runner.read(tmp_path / "D0_gate.json")["decision"]["passed"]


def test_failed_or_partial_record_is_not_automatically_retried(tmp_path):
    task = dict(stage="D0", method="D0", instance=runner.SELECTED[0], repetition=0)
    folder = tmp_path / "runs" / runner.task_id(task)
    folder.mkdir(parents=True)
    runner.save(folder / "task.json", task)
    with pytest.raises(ValueError, match="no automatic retry"):
        runner.load_record(tmp_path, task, dict(config=config()))


def test_completed_label_cannot_hide_recorded_verification_error(tmp_path, monkeypatch):
    task = dict(stage="D0", method="D0", instance=runner.SELECTED[0], repetition=0)
    folder = tmp_path / "runs" / runner.task_id(task)
    folder.mkdir(parents=True)
    runner.save(tmp_path / "protocol.json", {"identity": "fixed"})
    runner.save(folder / "task.json", task)
    runner.save(folder / "result.json", dict(task=task, result={"sentinel": "retained"}))
    runner.save(folder / "record.json", dict(task=task, status="completed", returncode=0,
        watchdog=None, verification_error="original physical audit failed",
        result_sha256=runner.digest(folder / "result.json"),
        frozen_evidence=runner.frozen_evidence(tmp_path, task)))

    def must_not_reaudit(*args):
        raise AssertionError("A recorded verification failure must be rejected before re-audit")

    monkeypatch.setattr(runner, "verify_result", must_not_reaudit)
    with pytest.raises(ValueError, match="Failed or altered run retained"):
        runner.load_record(tmp_path, task, dict(config=config()))


def test_old_output_directory_is_rejected():
    with pytest.raises(ValueError, match="rolling_merge"):
        runner.output_path(ROOT / "outputs/eight_neighbor_rolling_20261128/local_r1")
