"""Small non-I/O tests for the preregistered progress batch and quality gates."""
from copy import deepcopy

import analyze_eight_neighbor_progress as analysis
import run_eight_neighbor_progress as runner


def test_design_is_only_three_arm_single_factor():
    assert runner.DESIGN["methods"] == ["C0", "C0_PREFIX", "C0_PROGRESS"]
    assert runner.DESIGN["seconds"] == 30.0
    assert runner.DESIGN["repetitions"] == 3
    assert runner.DESIGN["progress_policy"]["activation"]["first_search_improvement_before_fraction"] == 0.20
    assert runner.DESIGN["progress_policy"]["reserved_every"] == 4


def test_preassigned_task_matrix_is_36():
    fake_hash = "x" * 64
    evidence = {"archive_hashes": {i: {"manifest_sha256": fake_hash} for i in runner.DESIGN["instances"]},
                "references": {i: {"waypoints": [1, 2, 3]} for i in runner.DESIGN["instances"]}}
    a, b = runner.make_tasks(evidence), runner.make_tasks(evidence)
    assert a == b and len(a) == 36
    assert len({runner.task_id(x) for x in a}) == 36


def _dummy_comparisons(gains):
    data = []
    for i, gain in enumerate(gains):
        data.append(dict(pair="progress_vs_control", instance=analysis.INSTANCES[i],
                         region=analysis.INSTANCES[i].split("_", 1)[0],
                         threshold_0p1=gain >= 0.001, threshold_0p5=gain >= 0.005,
                         J_nonregression=gain >= -1e-8, Pd_guard=True))
    return data


def test_screen_requires_both_regions_and_no_regression():
    assert analysis.screen(_dummy_comparisons([0.002, 0.006, 0.0, 0.002]),
                           "progress_vs_control")["passed"]
    assert not analysis.screen(_dummy_comparisons([0.002, 0.006, -0.01, 0.002]),
                               "progress_vs_control")["passed"]
    assert not analysis.screen(_dummy_comparisons([0.002, 0.006, 0.0, 0.0]),
                               "progress_vs_control")["passed"]
