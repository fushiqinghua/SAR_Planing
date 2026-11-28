"""Independent oracle and matched-prefix tests for the diagnostic harness."""
import pytest

import frontier_probe as probe
from asar_repro import physical_refinement as refinement, physical_search as search


@pytest.mark.parametrize("case", search.diagnostic_cases(), ids=lambda c: c["id"])
@pytest.mark.parametrize("connectivity", (4, 8))
def test_all_representations_reach_the_oracle_on_toy(case, connectivity):
    problem = search.problem_from_case(case)
    oracle = search.enumerate_physical(problem, connectivity=connectivity, max_seconds=30)
    assert oracle["enumeration_complete"]
    checkpoints = []
    for mode in probe.MODES:
        result, evidence = probe.solve_probe(
            problem, mode=mode, checkpoint=1, connectivity=connectivity,
            max_seconds=30, initial_waypoints=case["initial_waypoints"],
        )
        assert result["stop_reason"] == "frontier_exhausted"
        assert result["J"] == pytest.approx(oracle["J"], abs=1e-8)
        independent = search.independent_replay(problem, result["waypoints"], connectivity=connectivity)
        assert result["survival"] == pytest.approx(independent["survival"], abs=1e-8)
        checkpoints.append(evidence["handoff"]["open_sha256"])
        assert bool(evidence["split"]) == (mode != "single_global")
    assert len(set(checkpoints)) == 1


def test_matched_global_sequence_and_original_c0():
    case = next(c for c in search.diagnostic_cases() if c["id"] == "late_drift")
    problem = search.problem_from_case(case)
    options = dict(connectivity=8, max_expansions=12, max_seconds=30, completion="greedy",
                   initial_waypoints=case["initial_waypoints"])
    reference = refinement.solve_physical_refinement(problem, **options)
    one, single = probe.solve_probe(problem, mode="single_global", checkpoint=3, **options)
    three, split = probe.solve_probe(problem, mode="three_global", checkpoint=3, **options)
    assert single["handoff"]["open_sha256"] == split["handoff"]["open_sha256"]
    assert single["handoff"]["prior_pops_sha256"] == split["handoff"]["prior_pops_sha256"]
    assert single["pop_sha256"] == split["pop_sha256"]
    assert split["split"]["rss_after_swap"] > 0
    for key in ("expanded", "generated", "peak_open", "open_count", "J", "pd_final", "waypoints"):
        assert one[key] == three[key] == reference[key]


def test_force_gate_only_in_toy_exercises_reservation_and_ancestry(monkeypatch):
    class ToyController(probe.core._LazyProgressController):
        def should_reserve(self, elapsed, best_elapsed):
            return True

    monkeypatch.setattr(probe.core, "_LazyProgressController", ToyController)
    case = next(c for c in search.diagnostic_cases() if c["id"] == "repeat_detection")
    problem = search.problem_from_case(case)
    options = dict(connectivity=8, max_expansions=30, max_seconds=30, completion="greedy",
                   initial_waypoints=case["initial_waypoints"])
    _, control = probe.solve_probe(problem, mode="three_global", checkpoint=2, **options)
    result, quota = probe.solve_probe(problem, mode="three_quota", checkpoint=2, **options)
    counts = result["diagnostics"]["prefix_order"]
    assert quota["handoff"]["open_sha256"] == control["handoff"]["open_sha256"]
    assert quota["pop_sha256"] != control["pop_sha256"]
    assert quota["reserved_distinct_paths"] > 0
    assert quota["reserved_distinct_paths"] <= counts["reserved_early_pops"] + counts["reserved_middle_pops"]
    assert not control["reserved_distinct_paths"]
    assert all(ancestor[1] <= item["elapsed_s"] for item in quota["incumbent_lineage"]
               for ancestor in item["reserved_ancestors"])
