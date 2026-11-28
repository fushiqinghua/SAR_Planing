"""Prepared local protocol tests. Synthetic rows are not experimental results."""
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("rolling_runner_test_module", ROOT / "scripts/run_eight_neighbor_rolling.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def config():
    return json.loads((ROOT / "configs/eight_neighbor_rolling.json").read_text(encoding="utf-8"))


def evidence():
    result = dict(instances={}, references={}, archive_hashes={})
    for identity in runner.SELECTED:
        scene = "lake_ontario" if identity.startswith("lake") else "arctic_ocean"
        block, seed = identity.rsplit("_s", 1)
        result["instances"][identity] = dict(id=identity, block_id=block, seed=int(seed), base_scene=scene)
        result["references"][identity] = dict(waypoints=[0,1,0], J=2.0, pd_final=0.1)
        result["archive_hashes"][identity] = dict(manifest_sha256=hashlib.sha256(identity.encode()).hexdigest())
    return result


def rows():
    return [dict(task=task, run_id=runner.task_id(task), result=dict(J=100.0,pd_final=0.9))
            for task in runner.make_tasks(config(),evidence())]


def improve(values, identities=runner.SELECTED[:3], gain=0.01):
    for row in values:
        if row["task"]["method"] == "C1" and row["task"]["instance"] in identities:
            row["result"]["J"] = 100*(1-gain)


def test_registered_matrix_has_one_fixed_bounded_comparison():
    cfg = config()
    assert runner.object_digest(cfg) == runner.REGISTERED_CONFIG_HASH
    design = runner.plan(cfg)
    assert design["formal_tasks"] == 24
    assert design["total_algorithm_budget_s"] == 720
    assert design["C1_slots_s"] == [6.0]*5
    matrix = runner.make_tasks(cfg,evidence())
    assert matrix == runner.make_tasks(cfg,evidence())
    assert len({runner.task_id(task) for task in matrix}) == 24
    assert {task["connectivity"] for task in matrix} == {8}
    assert {task["footprint"] for task in matrix} == {"heading_square"}
    assert set(task["instance"] for task in matrix) == set(runner.SELECTED)
    assert "hudson_h2_d2_s4201" in runner.SELECTED
    assert all(task["seconds"] == 30 for task in matrix)


def test_configuration_change_requires_new_registration():
    cfg = config()
    cfg["search"]["seconds"] = 150
    with pytest.raises(ValueError,match="Unregistered"):
        runner.check_config(cfg)


def test_same_quality_is_not_a_successful_second_contribution():
    result = runner.decision(config(),rows(),complete=True)
    assert result["status"] == "rolling_development_screen_not_passed"
    assert result["quality_protected"] and result["pd_protected"]
    assert result["instance_winners"] == 0


def test_three_instance_winners_across_both_regions_pass_the_engineering_screen():
    values = rows()
    improve(values)
    result = runner.decision(config(),values,complete=True)
    assert result["screen_passed"]
    assert result["winners_by_scene"] == {"lake_ontario":2,"arctic_ocean":1}


@pytest.mark.parametrize("damage",["missing","duplicate","nonfinite","wrong_seconds","wrong_region","wrong_graph"])
def test_invalid_matrix_cannot_pass(damage):
    values = rows()
    improve(values)
    if damage == "missing":
        values.pop()
    elif damage == "duplicate":
        values[-1] = deepcopy(values[0])
    elif damage == "nonfinite":
        values[0]["result"]["J"] = math.nan
    elif damage == "wrong_seconds":
        values[0]["task"]["seconds"] = 150
    elif damage == "wrong_region":
        values[0]["task"]["base_scene"] = "another_scene"
    else:
        values[0]["task"]["connectivity"] = 4
    assert runner.decision(config(),values,complete=True)["status"] == "incomplete_or_invalid"


def test_missing_runtime_evidence_blocks_structurally_complete_rows():
    values = rows()
    improve(values)
    assert not runner.decision(config(),values,complete=False)["screen_passed"]


@pytest.mark.parametrize("metric,value",[("J",100.01),("pd_final",0.894)])
def test_one_regression_or_excessive_pd_drop_blocks_promotion(metric,value):
    values = rows()
    improve(values,runner.SELECTED)
    for row in values:
        if row["task"]["instance"] == runner.SELECTED[-1] and row["task"]["method"] == "C1":
            row["result"][metric] = value
    assert not runner.decision(config(),values,complete=True)["screen_passed"]


def test_pd_comes_from_actual_median_j_run_not_independent_pd_median():
    values = rows()
    improve(values)
    for row in values:
        if row["task"]["instance"] == runner.SELECTED[0] and row["task"]["method"] == "C1":
            i = row["task"]["repetition"]
            row["result"].update(J=[98,99,100][i],pd_final=[0.95,0.85,0.99][i])
    result = runner.decision(config(),values,complete=True)
    pair = result["comparisons"][0]
    assert pair["J_C1"] == 99
    assert pair["pd_C1"] == 0.85
    assert pair["pd_drop_flag"] and not result["screen_passed"]


def score():
    return dict(survival=[1.0,0.8,0.6],observation_times_s=[10.0,20.0],J=1.4,pd_final=0.4)


def test_original_mass_clock_and_objective_remain_coupled():
    runner.validate_score(score(),1e-8)
    for change in (dict(survival=[1.0,1.0,1.0]),dict(observation_times_s=[0.0,10.0]),
                   dict(J=1.0),dict(pd_final=0.6),dict(survival=[0.8,0.7,0.6])):
        damaged = score()
        damaged.update(change)
        with pytest.raises(ValueError):
            runner.validate_score(damaged,1e-8)


def phase_record():
    phases = []
    for index in range(5):
        phases.append(dict(stage_index=index,actual_compute_s=6.0,cumulative_compute_s=(index+1)*6.0,
             allocated_seconds=6.0,stage_start_compute_s=index*6.0,stage_deadline_compute_s=(index+1)*6.0,
             accepted=True,acceptance_compute_s=5.8,cumulative_acceptance_compute_s=index*6.0+5.8,
             request_time_s=100.0*index,ready_time_s=0.0 if index==0 else 100.0*index+5.8,
             anchor_time_s=0.0 if index==0 else 100.0*index+10.0))
    return dict(method="C1",active_compute_s=30.0,phase_compute_sum_s=30.0,finalization_compute_s=0.0,phases=phases)


def test_timely_acceptance_does_not_confuse_return_overhead_with_extra_search():
    value = phase_record()
    value["phases"][-1]["actual_compute_s"] = 6.1
    value["phases"][-1]["cumulative_compute_s"] = 30.1
    value["active_compute_s"] = 30.1
    value["phase_compute_sum_s"] = 30.1
    runner.validate_phase_ledger(value,30)


@pytest.mark.parametrize("damage",["late_phase","late_total","missed_anchor","unpaid_work","duplicate_phase"])
def test_online_latency_and_shared_budget_are_not_free(damage):
    value = phase_record()
    last = value["phases"][-1]
    if damage == "late_phase":
        last["acceptance_compute_s"] = 6.01
    elif damage == "late_total":
        last["cumulative_acceptance_compute_s"] = 30.01
    elif damage == "missed_anchor":
        last["ready_time_s"] = 410.01
    elif damage == "unpaid_work":
        last["cumulative_compute_s"] = 7.0
    else:
        last["stage_index"] = 0
    with pytest.raises(ValueError):
        runner.validate_phase_ledger(value,30)


@pytest.mark.parametrize("damage",["missing_stage","oversized_slot","unpaid_finalization"])
def test_phase_shape_and_finalization_cannot_change_the_registered_budget(damage):
    value = phase_record()
    if damage == "missing_stage":
        value["phases"].pop()
    elif damage == "oversized_slot":
        value["phases"][0]["allocated_seconds"] = 7
    else:
        value["finalization_compute_s"] = 0.1
    with pytest.raises(ValueError):
        runner.validate_phase_ledger(value,30)


def test_frozen_source_hashes_are_verified_without_git_or_network(tmp_path,monkeypatch):
    monkeypatch.setattr(runner,"ROOT",tmp_path)
    path = tmp_path/"source.py"
    path.write_bytes(b"# original\n")
    hashes = {"source.py":runner.git_blob_digest(path)}
    runner.verify_git_blobs(hashes)
    path.write_bytes(b"# changed\n")
    with pytest.raises(ValueError,match="Inherited source"):
        runner.verify_git_blobs(hashes)


def test_paths_cannot_escape_the_checkout(tmp_path,monkeypatch):
    monkeypatch.setattr(runner,"ROOT",tmp_path)
    with pytest.raises(ValueError):
        runner.rooted("../outside")
    with pytest.raises(ValueError):
        runner.rooted(str(tmp_path/"absolute"))


def test_existing_partial_run_is_preserved_instead_of_retried(tmp_path):
    task = runner.make_tasks(config(),evidence())[0]
    folder = tmp_path/"runs"/runner.task_id(task)
    folder.mkdir(parents=True)
    (folder/"task.json").write_text(json.dumps(task),encoding="utf-8")
    with pytest.raises(ValueError,match="Incomplete run retained"):
        runner.load_record(tmp_path,task,{})
    assert (folder/"task.json").exists()


class AuditFixture:
    """Small fixed event ledger for protocol tests, independent of optimizer."""
    start = 0
    horizon_s = 40.0
    time_tolerance_s = 1e-8
    q = 0.78

    def replay(self,route,connectivity):
        assert connectivity == 8
        assert list(route) == [0,1,2,3,4]
        return dict(waypoints=list(route),J=3.0,pd_final=0.4,
                    planned_arrival_times_s=[0.0,10.0,20.0,30.0,40.0],
                    observation_times_s=[10.0,20.0,30.0,40.0],survival=[1.0,0.9,0.8,0.7,0.6])


def audit_fixture():
    route = [0,1,2,3,4]
    phases = []
    events = [(0,0,[0],0,0,0),(10,20,[0,1,2],1,2,20),
              (20,30,[0,1,2,3],2,3,30),(30,None,[0,1,2,3],3,None,36),
              (None,None,[0,1,2,3],None,None,36)]
    for index,(request,anchor,prefix,ri,ai,execution) in enumerate(events):
        phase = dict(stage_index=index,request_time_s=request,anchor_time_s=anchor,
                     request_waypoint_index=ri,anchor_waypoint_index=ai,
                     committed_prefix_waypoints=prefix,accepted=False,inner=None,
                     active_J_after=3.0,active_pd_final_after=0.4,
                     allocated_seconds=6.0,actual_compute_s=6.0,
                     virtual_execution_time_after_s=execution,
                     ready_time_s=None if request is None else request+6.0,
                     reason="no_remaining_request_waypoint" if index==4 else
                            "no_remaining_commit_anchor" if index==3 else "no_strict_J_improvement")
        if index and request is not None:
            phase.update(execution_ready_compute_s=6.0,execution_ready_time_s=request+6.0)
        phases.append(phase)
    raw = dict(method="C1",triggers=[0.2,0.4,0.6,0.8],anchor_guard_s=0.25,
               phases=phases,waypoints=route,history=[dict(waypoints=route)],
               protected_prefix_waypoints=[0,1,2,3])
    return AuditFixture(),raw,dict(waypoints=route)


def test_independent_execution_audit_tracks_committed_old_motion():
    problem,raw,reference = audit_fixture()
    result = runner.audit_execution(problem,raw,reference,1e-8)
    assert result["status"] == "passed"
    assert result["candidate_selection_performed"] is False


@pytest.mark.parametrize("damage",["prefix","anchor","request","latency","skipped_request"])
def test_causal_execution_audit_rejects_free_motion_and_rewritten_prefix(damage):
    problem,raw,reference = audit_fixture()
    phase = raw["phases"][1]
    if damage == "prefix":
        phase["committed_prefix_waypoints"] = [0,2]
    elif damage == "anchor":
        phase["anchor_time_s"] = 15.0
    elif damage == "request":
        phase["request_time_s"] = 9.0
    elif damage == "latency":
        phase["execution_ready_time_s"] = 15.0
    else:
        phase["request_time_s"] = None
        phase["reason"] = "no_remaining_request_waypoint"
    with pytest.raises(ValueError):
        runner.audit_execution(problem,raw,reference,1e-8)


def test_initial_budget_stop_without_new_root_is_a_valid_recorded_fallback():
    problem,raw,reference = audit_fixture()
    raw["phases"][0]["inner"] = dict(status="budget_exceeded",stop_reason="max_seconds",error=None,
         initial_score=None,root_prefix=None,root_state=None,waypoints=None)
    assert runner.audit_execution(problem,raw,reference,1e-8)["status"] == "passed"


def test_loaded_project_modules_must_come_from_the_new_checkout(tmp_path,monkeypatch):
    import types
    monkeypatch.setattr(runner,"ROOT",tmp_path)
    fake = types.ModuleType("asar_repro.fake_for_protocol_test")
    fake.__file__ = str(tmp_path/"another_checkout"/"fake.py")
    monkeypatch.setitem(runner.sys.modules,fake.__name__,fake)
    with pytest.raises(ValueError,match="another checkout"):
        runner.assert_local_project_modules()


def test_failure_record_preserves_nonfinite_raw_values_without_invalid_json():
    value = runner.failure_safe(dict(raw=dict(J=float("nan"),points=(1,2)),error="failed"))
    assert value["raw"]["J"] == "nan"
    assert value["raw"]["points"] == [1,2]
    json.dumps(value,allow_nan=False)
