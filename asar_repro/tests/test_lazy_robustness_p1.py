"""Frozen-P1 timing robustness protocol: allocation and qualitative gate checks."""
import run_lazy_robustness_p1 as study


def test_trial_allocation_and_reproducibility():
    tasks=study.task_matrix()
    assert tasks==study.task_matrix()
    assert len(tasks)==48
    assert len(set(study.task_id(t) for t in tasks))==48
    assert sum(t["instance"]=="hudson_h2_d1_s4101" for t in tasks)==36
    assert sum(t["instance"]=="hudson_h2_d2_s4201" for t in tasks)==12
    for name,count in study.DESIGN["cases"].items():
        for method in study.DESIGN["arms"][name]:
            assert sum(t["instance"]==name and t["method"]==method for t in tasks)==count
    assert all(t["seconds"]==30.0 for t in tasks)


def test_nearest_rank_is_conservative():
    assert study.nearest_rank([1,5,3,2,4],.9)==5
    assert study.nearest_rank([1]*12,.9)==1


def test_control_arms_use_original_solver():
    assert set(study.DESIGN["arms"]["hudson_h2_d1_s4101"])=={"C0_A","C0_B","C0_LAZY"}
    assert set(study.DESIGN["arms"]["hudson_h2_d2_s4201"])=={"C0","C0_LAZY"}
    assert study.DESIGN["target"]["hudson_h2_d1_s4101"]<study.DESIGN["baseline_initial_j"]["hudson_h2_d1_s4101"]
