from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_eight_neighbor_h2 as study


@pytest.fixture
def config():
    return study.read(study.DEFAULT_CONFIG)


def cases_from_config(config):
    return [
        dict(id=f"{block[0]}_s{seed}", block_id=block[0], base_scene=site,
             seed=seed, date=block[1])
        for site, data in config["datasets"].items()
        for block in data["primary"]
        for seed in block[2:]
    ]


def test_registered_matrix_has_one_shared_seed_and_three_search_repetitions(config):
    cases = cases_from_config(config)
    manifests = {case["id"]: str(case["seed"]) for case in cases}
    matrix = study.make_tasks(config, cases, manifests)
    assert study.plan(config)["total_algorithm_budget_s"] == 4680
    assert {stage: len(rows) for stage, rows in matrix.items()} == {"S30": 12, "H30": 144}
    assert matrix == study.make_tasks(config, list(reversed(cases)), manifests)
    assert len({study.task_id(row) for rows in matrix.values() for row in rows}) == 156
    assert {row["method"] for row in matrix["H30"]} == {"completion_J"}
    for case in cases:
        s30 = [row for row in matrix["S30"] if row["instance"] == case["id"]]
        h30 = [row for row in matrix["H30"] if row["instance"] == case["id"]]
        assert len(s30) == 1
        assert s30[0]["connectivity"] == 4 and s30[0]["footprint"] == "axis_square"
        assert {(row["footprint"], row["connectivity"], row["repetition"]) for row in h30} == {
            (footprint, graph, rep)
            for footprint in ("heading_square", "axis_square") for graph in (4, 8) for rep in range(3)
        }
        assert all(row["seconds"] == 30 and row["manifest_sha256"] == str(case["seed"]) for row in s30 + h30)


def test_registered_matrix_refuses_incomplete_duplicate_or_replaced_seed(config):
    cases = cases_from_config(config)
    with pytest.raises(ValueError, match="three independently verified"):
        study.registered_instances(config, cases[2:])
    with pytest.raises(ValueError, match="Duplicate"):
        study.registered_instances(config, cases + [cases[0]])
    with pytest.raises(ValueError, match="preregistered seeds"):
        study.registered_instances(config, [
            dict(cases[0], id=f"{cases[0]['block_id']}_s9999", seed=9999), *cases[1:]])
    with pytest.raises(ValueError, match="must bind"):
        study.registered_instances(config, [dict(cases[0], id="../.."), *cases[1:]])


def arm(case, footprint, graph, samples):
    return [
        dict(task=dict(instance=case["id"], footprint=footprint, connectivity=graph,
                       block_id=case["block_id"], base_scene=case["base_scene"],
                       seed=case["seed"], repetition=rep),
             result=dict(J=j, pd_final=pd, algorithm_wall_s=10.0 + rep),
             record=dict(peak_rss_bytes=50 + rep), run_id=f"{graph}-{rep}")
        for rep, (j, pd) in enumerate(samples)
    ]


def test_seed_gain_pairs_pd_to_actual_median_j_route(config):
    case = cases_from_config(config)[0]
    four = arm(case, study.PRIMARY, 4, [(6, .90), (4, .80), (5, .70)])
    eight = arm(case, study.PRIMARY, 8, [(4.8, .81), (4.7, .95), (4.9, .77)])
    rows = study.paired_seed_scores(config, four + eight)
    assert len(rows) == 1
    result = rows[0]
    assert result["four"]["run_id"] == "4-2" and result["eight"]["run_id"] == "8-0"
    assert result["four"]["Pd"] == .70 and result["eight"]["Pd"] == .81
    assert result["relative_J_gain"] == pytest.approx(.04)
    assert result["delta_Pd_pp"] == pytest.approx(11.0)
    assert study.paired_seed_scores(config, four + eight[:2]) == []
    with pytest.raises(ValueError, match="distinct repetitions"):
        study.paired_seed_scores(config, four + eight[:2] + eight[1:2])


def test_seed_gain_preserves_undefined_zero_reference_and_absolute_tolerance(config):
    case = cases_from_config(config)[0]
    four = arm(case, study.PRIMARY, 4, [(0.0, 1.0)] * 3)
    eight = arm(case, study.PRIMARY, 8, [(0.02, .98)] * 3)
    [result] = study.paired_seed_scores(config, four + eight)
    assert result["absolute_J_gain"] == -.02 and result["relative_J_gain"] is None
    assert result["decision_relative_J_gain"] is None
    four = arm(case, study.PRIMARY, 4, [(1.0, .9)] * 3)
    eight = arm(case, study.PRIMARY, 8, [(1.0 - 1e-9, .91)] * 3)
    [result] = study.paired_seed_scores(config, four + eight)
    assert 0 < result["relative_J_gain"] < 1e-8
    assert result["decision_relative_J_gain"] == 0


def outcomes(config, gains):
    rows = []
    for i, case in enumerate(cases_from_config(config)):
        for footprint, value in ((study.PRIMARY, gains[i]), (study.AXIS, -1.0)):
            rows.append(dict(instance=case["id"], footprint=footprint, base_scene=case["base_scene"],
                             block_id=case["block_id"], seed=case["seed"], relative_J_gain=value,
                             decision_relative_J_gain=value))
    return rows


def test_date_gate_requires_both_regions_and_ignores_axis_for_adoption(config):
    values = [.02, .02, .02, .02, 0, 0, .02, .02, .02, .02, 0, 0]
    rows = outcomes(config, values)
    result = study.date_decision(config, rows, complete=True)
    assert result["status"] == "new_date_J_transfer_signal"
    assert result["winners_by_site"] == {"lake_ontario": 2, "arctic_ocean": 2}
    skewed = outcomes(config, [.02] * 6 + [.02, .02, 0, 0, 0, 0])
    assert study.date_decision(config, skewed, complete=True)["status"] == "new_date_screen_not_passed"
    values[-2:] = [-.006, -.006]
    assert study.date_decision(config, outcomes(config, values), complete=True)["status"] == "new_date_screen_not_passed"
    assert study.date_decision(config, rows, complete=False)["status"] == "evaluation_invalid"


def test_date_gate_tracks_seed_instability_independently(config):
    values = [-.011, .03, .005 - 5e-9, .005 - 5e-9, 0, 0, .02, .02, .02, .02, 0, 0]
    rows = outcomes(config, values)
    result = study.date_decision(config, rows, complete=True)
    assert result["status"] == "new_date_J_signal_with_seed_instability"
    assert result["seed_instability"] == [rows[0]["instance"]]
    for row in rows[:1]:
        row["relative_J_gain"] = row["decision_relative_J_gain"] = None
    invalid = study.date_decision(config, rows, complete=True)
    assert invalid["status"] == "evaluation_invalid"
    assert "Zero J4" in invalid["reason"]
    assert any(item["decision_relative_J_gain"] is None and not item["winner"] for item in invalid["date_rows"])


def verified_score(footprint, connectivity=4):
    return dict(J=.76, pd_final=.64, survival=[1.0, .4, .36], observation_times_s=[1.0, 2.0],
                physical_duration_s=2.0, distance_m=40.0, footprint=footprint,
                connectivity=connectivity, waypoints=[0, 1, 0])


def test_s30_result_binds_both_replays_to_same_route(config):
    case = cases_from_config(config)[0]
    optics = {key: verified_score(key) for key in (study.AXIS, study.PRIMARY)}
    task = dict(stage="S30", instance=case["id"], method="PT_then_original_paper_greedy",
                manifest_sha256="manifest", footprint=study.AXIS, connectivity=4, seconds=30)
    archive_hash = dict(manifest_sha256="manifest", particle_sha256="npz")
    protocol = dict(config=config, environment={}, archive_hashes={case["id"]: archive_hash},
                    instances={case["id"]: case})
    result = dict(status="valid", method=task["method"], inputs=dict(case=case, footprint=study.AXIS, **archive_hash),
                  J=.76, pd_final=.64, physical_replay=optics[study.AXIS], physical_replays=optics,
                  formal_optimality_certificate=False, environment={}, waypoints=[0, 1, 0],
                  history=[dict(elapsed_s=0.01)])
    study.verify_result(task, result, protocol)
    result["physical_replays"][study.PRIMARY]["waypoints"] = [0, 2, 0]
    with pytest.raises(ValueError, match="one independently replayed"):
        study.verify_result(task, result, protocol)


def test_h30_result_refuses_late_candidate_or_changed_particle_identity(config):
    case = cases_from_config(config)[0]
    task = dict(stage="H30", instance=case["id"], method="completion_J", footprint=study.PRIMARY,
                connectivity=8, seconds=30, manifest_sha256="manifest")
    archive_hash = dict(manifest_sha256="manifest", particle_sha256="npz")
    protocol = dict(config=config, environment={}, archive_hashes={case["id"]: archive_hash},
                    instances={case["id"]: case})
    reference = dict(J=.76, pd_final=.64, waypoints=[0, 1, 0], observation_times_s=[1.0, 2.0],
                     run_id="seed", waypoints_sha256="path")
    result = dict(status="valid", method=task["method"], inputs=dict(case=case, footprint=study.PRIMARY, **archive_hash),
                  J=.76, pd_final=.64, physical_replay=verified_score(study.PRIMARY, 8),
                  formal_optimality_certificate=False, environment={}, reference_J=reference["J"],
                  reference_pd=reference["pd_final"], reference_run_id="seed", reference_waypoints_sha256="path",
                  method_options=study.solve_options(config), history=[dict(elapsed_s=0.5, waypoints=[0, 1, 0])])
    study.verify_result(task, result, protocol, reference)
    late = deepcopy(result)
    late["history"].append(dict(elapsed_s=30.01, waypoints=[0, 1, 2]))
    with pytest.raises(ValueError, match="budget"):
        study.verify_result(task, late, protocol, reference)
    result["inputs"]["particle_sha256"] = "coincidental manifest"
    with pytest.raises(ValueError, match="input"):
        study.verify_result(task, result, protocol, reference)


def test_run_h30_requires_the_shared_initialization_lock(monkeypatch, tmp_path):
    monkeypatch.setattr(study, "verify_protocol", lambda *args, **kwargs: ({}, {"S30": [], "H30": [{}]}))
    monkeypatch.setattr(study, "launch_task", lambda *args: pytest.fail("A search was launched before its gate"))
    with pytest.raises(FileNotFoundError, match="s30_lock.json"):
        study.run_stage(study.DEFAULT_CONFIG, tmp_path, "H30")
    assert not (tmp_path / "execution.lock").exists()


def test_freeze_does_not_publish_a_matrix_without_the_scientific_lock(monkeypatch, tmp_path, config):
    import types

    def blocked(*args):
        raise ValueError("date qualification incomplete")

    monkeypatch.setitem(sys.modules, "h2_protocol", types.SimpleNamespace(
        verify_method=lambda *args: {"config": config}, verify_inputs=blocked))
    with pytest.raises(ValueError, match="date qualification incomplete"):
        study.freeze(study.DEFAULT_CONFIG, tmp_path)
    assert not (tmp_path / "protocol.json").exists()
    assert not (tmp_path / "tasks").exists()


def test_load_record_preserves_incomplete_attempt(tmp_path):
    task = dict(stage="S30", instance="test")
    folder = tmp_path / "runs" / study.task_id(task)
    folder.mkdir(parents=True)
    with pytest.raises(ValueError, match="Incomplete H2 run preserved"):
        study.load_record(tmp_path, task, {})
    assert folder.is_dir()


@pytest.mark.parametrize("graph", [4, 8])
def test_h2_completion_options_use_the_original_replay_on_a_toy(config, graph):
    import numpy as np

    from asar_repro.physical_model import PhysicalProblem
    from asar_repro.physical_refinement import solve_physical_refinement

    problem = PhysicalProblem(
        rows=3, cols=3, cell_width_m=20.0, speed_m_s=20.0, times_s=np.asarray([0.0, 1.0, 2.0]),
        positions_xy=np.asarray([[[0.0, 0.0]], [[20.0, 20.0]], [[20.0, 20.0]]]),
        searchable=np.ones((3, 1), dtype=bool), initial_weights=np.asarray([1.0]),
        start=4, q=.78, footprint=study.PRIMARY, trajectory_ids=np.asarray([1]))
    seed = [4, 5, 2]
    reference = dict(problem.replay(seed, 4), run_id="seed", waypoints_sha256=study.object_digest(seed))
    task = dict(stage="H30", method="completion_J", footprint=study.PRIMARY,
                connectivity=graph, seconds=30)
    raw = solve_physical_refinement(problem, connectivity=graph, initial_waypoints=seed,
                                    max_seconds=30, **study.solve_options(config))
    audited = study.confirmation.audit_result(
        study.audit_options(config), problem, reference, task, raw, raw["wall_s"], 0.0)
    score = audited["physical_replay"]
    assert audited["history"][0]["waypoints"] == seed
    assert study.score_is_consistent(score, 1e-8)
    assert score["J"] <= reference["J"]
    assert audited["formal_optimality_certificate"] is False

