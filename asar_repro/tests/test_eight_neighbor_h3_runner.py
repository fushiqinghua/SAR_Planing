"""Exercise H3 study gates and local replay without a real-data benchmark."""
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_eight_neighbor_h3 as study
from h3_protocol import REGISTRY, ROOT, digest, instances_for, read, save
from report_eight_neighbor_h3 import date_screen, per_seed
from asar_repro.grid import GridGraph
from asar_repro.motion import ParticleMotion
from asar_repro.physical_search import diagnostic_cases, problem_from_case


def test_matrix_freezes_12_common_routes_and_36_adjacent_randomized_pairs():
    registry = read(ROOT / REGISTRY)
    cases = {row["id"]: dict(case=row, manifest_sha256=row["id"], input_sha256=str(row["seed"]))
             for row in instances_for(registry["blocks"][:6])}
    matrix = study.make_tasks(cases, registry["method"])
    assert matrix == study.make_tasks(dict(reversed(list(cases.items()))), registry["method"])
    assert len(matrix["S30"]) == 12 and len(matrix["E30"]) == 72
    assert len({study.task_id(row) for rows in matrix.values() for row in rows}) == 84
    assert sum(row["seconds"] for rows in matrix.values() for row in rows) == 2520
    assert {row["method"] for row in matrix["S30"]} == {"PT_then_original_paper_greedy"}
    assert {"C0", "Lazy"} == {row["method"] for row in matrix["E30"][::2]}
    for a, b in zip(matrix["E30"][::2], matrix["E30"][1::2], strict=True):
        assert {a["method"], b["method"]} == {"C0", "Lazy"}
        for key in ("date", "seed", "repetition", "manifest_sha256", "particle_sha256", "instance"):
            assert a[key] == b[key]
        assert a["footprint"] == b["footprint"] == "heading_square"
        assert a["connectivity"] == b["connectivity"] == 8


def test_s30_and_e30_stop_before_launch_when_protocol_is_missing(tmp_path, monkeypatch):
    launched = []
    monkeypatch.setattr(study, "launch_task", lambda *_: launched.append("unexpected"))
    for stage in ("S30", "E30"):
        with pytest.raises(FileNotFoundError, match="protocol.json"):
            study.run_stage(tmp_path, stage)
    assert not launched and not (tmp_path / "runs").exists()


def test_e30_refuses_to_launch_before_all_s30_records(tmp_path, monkeypatch):
    s30 = dict(stage="S30", instance="fixture")
    monkeypatch.setattr(study, "verify_protocol", lambda *_args, **_kw: ({}, {"S30":[s30], "E30":[{}]}))
    monkeypatch.setattr(study, "launch_task", lambda *_: pytest.fail("A missing S30 was bypassed"))
    with pytest.raises(FileNotFoundError, match="record.json"):
        study.run_stage(tmp_path, "E30")
    assert not (tmp_path / "s30_lock.json").exists()


def test_dual_replay_rejects_illegal_route_and_preserves_special_mass():
    case = next(row for row in diagnostic_cases() if row["id"] == "special_mass")
    problem = problem_from_case(case)
    original, independent = study.dual_replay(problem, case["initial_waypoints"], 8)
    assert original["J"] == pytest.approx(independent["J"], abs=1e-12)
    assert original["survival"] == pytest.approx(independent["survival"], abs=1e-12)
    assert original["survival"][-1] >= .4
    with pytest.raises(ValueError):
        study.dual_replay(problem, [4, 8, 0], 8)


@pytest.mark.parametrize("arm", ["C0", "Lazy"])
def test_e30_worker_scores_the_frozen_solver_and_persists_original_and_scalar_replay(tmp_path, monkeypatch, arm):
    registry = read(ROOT / REGISTRY)
    prior = read(ROOT / study.P1_PROTOCOL)["config"]
    case = next(row for row in diagnostic_cases() if row["id"] == "diagonal_intercept")
    toy = problem_from_case(dict(case, cell_width_m=20., speed_m_s=20.,
                                 positions_xy=(20 * np.array(case["positions_xy"])).tolist()))
    method = registry["method"]
    task = dict(stage="E30", instance="fixture", seconds=30, method=arm, connectivity=8,
                footprint="heading_square", manifest_sha256="fixture manifest", particle_sha256="fixture archive")
    reference_score = toy.replay(case["initial_waypoints"], connectivity=8)
    reference = dict(waypoints=case["initial_waypoints"], J=reference_score["J"], Pd=reference_score["pd_final"],
                     observation_times_s=reference_score["observation_times_s"], particle_sha256=task["particle_sha256"])
    evidence = dict(study="test fixture")
    info = dict(case=case, h3_evidence=evidence, manifest_sha256=task["manifest_sha256"],
                particle_sha256=task["particle_sha256"], forcing_kind="historical_real", opendrift_runs_in_search=0)
    config = dict(solver=prior["solver"], search={name: prior["search"][name] for name in
                                               ("triggers", "anchor_guard_s", "solver_reserve_s")},
                  registered=method, progress_policy=study.lazy.DESIGN["progress_policy"], threads={})
    protocol = dict(config=config, cases={"fixture": dict(case=case, h3_evidence=evidence)},
                    environment=study.legacy.environment())
    identity = study.task_id(task)
    folder = tmp_path / "runs" / identity
    save(folder / "task.json", task)
    save(tmp_path / "protocol.json", {"fixture": True})
    save(tmp_path / "s30_lock.json", dict(status="shared_S30_locked", references={"fixture":reference},
                                          protocol_sha256=digest(tmp_path / "protocol.json")))
    monkeypatch.setenv("ASAR_OFFLINE", "1")
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    monkeypatch.setattr(study, "verify_protocol", lambda *_: (protocol, {"E30":[task]}))
    monkeypatch.setattr(study, "load_h3_input", lambda *_: (toy, None, None, info))
    study.run_worker(tmp_path, identity)
    result = read(folder / "result.json")["result"]
    assert result["status"] == "valid"
    assert result["J"] <= reference["J"]
    assert result["physical_replay"]["survival"] == pytest.approx(result["independent_replay"]["survival"])
    assert result["raw"]["phases"][0]["inner"]["algorithm"] == method["control" if arm == "C0" else "candidate"]


def test_s30_worker_uses_original_pt_bridge_and_preserves_one_legal_seed(tmp_path, monkeypatch):
    case = next(row for row in diagnostic_cases() if row["id"] == "diagonal_intercept")
    positions = np.array(case["positions_xy"])
    scaled = dict(case, cell_width_m=20., speed_m_s=20., positions_xy=(20 * positions).tolist())
    problems = {key: problem_from_case(scaled, key) for key in ("heading_square", "axis_square")}
    grid = GridGraph(3, 3)
    cell_ids = ((1 - positions[:, :, 1]) * 3 + (positions[:, :, 0] + 1)).astype(int)
    discrete = dict(start=4, budget=2, p=np.array(case["initial_weights"]), q=.78,
                    motion=ParticleMotion(cell_ids, grid.size, np.arange(4)))
    task = dict(stage="S30", instance="fixture", seconds=30, method="PT_then_original_paper_greedy",
                connectivity=4, footprint="axis_square", manifest_sha256="manifest", particle_sha256="archive")
    evidence = dict(study="test fixture")
    info = dict(case=case, h3_evidence=evidence, manifest_sha256=task["manifest_sha256"],
                particle_sha256=task["particle_sha256"], forcing_kind="historical_real", opendrift_runs_in_search=0)
    protocol = dict(config=dict(threads={}), cases={"fixture":dict(case=case, h3_evidence=evidence)},
                    environment=study.legacy.environment())
    identity = study.task_id(task)
    folder = tmp_path / "runs" / identity
    save(folder / "task.json", task)
    monkeypatch.setenv("ASAR_OFFLINE", "1")
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    monkeypatch.setattr(study, "verify_protocol", lambda *_: (protocol, {"S30":[task]}))
    monkeypatch.setattr(study, "load_h3_input", lambda *args: (problems[args[-1]], grid, discrete, info))
    study.run_worker(tmp_path, identity)
    recorded = read(folder / "result.json")["result"]
    assert recorded["algorithm_wall_s"] <= 30
    assert recorded["initialization"]["history"][0]["source"] == "parallel_track"
    assert recorded["initialization"]["bridge"]["physical_J"] == pytest.approx(recorded["axis_independent_replay"]["J"])
    assert recorded["physical_replay"]["waypoints"] == recorded["axis_independent_replay"]["waypoints"]


def test_seed_summary_takes_pd_from_same_route_as_median_j():
    def rows(arm, samples):
        return [
            dict(task=dict(site="arctic_ocean", date="2025-08-08", seed=4401, method=arm, repetition=i),
                 result=dict(J=j, pd_final=pd, algorithm_wall_s=29.5, algorithm_cpu_s=28.0),
                 record=dict(peak_rss_bytes=2**20), run_id=f"{arm}-{i}")
            for i, (j, pd) in enumerate(samples)
        ]
    trials = rows("C0", [(32,.96), (31,.80), (33,.60)]) + rows("Lazy", [(31.9,.76), (31.8,.90), (31.6,.95)])
    [outcome] = per_seed(trials)
    assert outcome["C0"]["run_id"] == "C0-0" and outcome["C0"]["Pd"] == .96
    assert outcome["Lazy"]["run_id"] == "Lazy-1" and outcome["Lazy"]["Pd"] == .90
    assert outcome["J_gain"] == pytest.approx(.00625)
    assert outcome["delta_Pd_pp"] == pytest.approx(-6)
    assert per_seed(trials[:-1]) == []
    with pytest.raises(ValueError, match="distinct repetitions"):
        per_seed([*trials[:-1], trials[-2]])


def test_date_thresholds_and_endpoint_guard_remain_distinct():
    rows = [
        dict(site=site, date=str(date), seed=region * 100 + date * 10 + i, J_gain=gain, delta_Pd_pp=0)
        for region, site in enumerate(("lake_ontario", "arctic_ocean"))
        for date, gain in enumerate((.002, .006, -.001))
        for i in range(2)
    ]
    assert date_screen(rows, complete=False)["status"] == "incomplete"
    value = date_screen(rows, complete=True)
    assert value["wins_0_1_pct"] == 4 and value["wins_0_5_pct"] == 2
    assert value["status"] == "date_J_screen_passed" and value["dual_J_Pd_screen_passed"]
    rows[1]["delta_Pd_pp"] = -.5001
    value = date_screen(rows, complete=True)
    assert value["status"] == "date_J_screen_passed"
    assert value["pd_risk_seeds"] == [1] and not value["dual_J_Pd_screen_passed"]
    rows[-1]["J_gain"] = -.0101
    assert date_screen(rows, complete=True)["status"] == "date_J_screen_failed"
