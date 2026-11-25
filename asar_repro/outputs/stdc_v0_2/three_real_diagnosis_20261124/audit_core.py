"""Read-only diagnosis of the frozen three-scene benchmark; no search rerun."""
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SCENES = {
    "lake_ontario": "trajectory_20261124",
    "arctic_ocean": "additional_real_20261124",
    "bay_of_fundy": "fundy_repair_20261124",
}
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

files = [ROOT / "outputs/stdc_v0_2" / folder / "benchmark/results.json"
         for folder in SCENES.values()]
aggregate_path = ROOT / "outputs/stdc_v0_2/three_real_20261124/aggregate.csv"
dp_path = ROOT / "outputs/stdc_v0_2/three_real_20261124/dp_preprocessing_audit.json"
files += [aggregate_path, dp_path]
sources = [ROOT / p for p in (
    "scripts/run_trajectory_experiments.py", "src/asar_repro/trajectory_search.py",
    "src/asar_repro/research_search.py", "src/asar_repro/research_particle.py",
    "src/asar_repro/midpoint_rollout.py", "src/asar_repro/particle_dp.py",
    "src/asar_repro/stdc_heuristic.py", "src/asar_repro/objective.py")]
before = {str(p.relative_to(ROOT)): digest(p) for p in files + sources}
aggregates = list(csv.DictReader(aggregate_path.open(encoding="utf-8-sig", newline="")))
report = {
    "date_local": "2026-11-24",
    "scope": "read-only diagnosis of existing runs; no algorithm, evaluator, forcing or old result edits",
    "protocol": {"work": "5000 expansions / 30 s / OPEN 20000",
                 "wall": "5 s / OPEN 20000", "repeats": 3,
                 "independent_archives": 3, "independent_repeated_particle_seeds": False},
    "scenes": {}, "input_source_sha256": before,
    "new_planner_runs": 0, "historical_full_pytest_rerun": False,
}
for scene, folder in SCENES.items():
    rows = json.loads((ROOT / "outputs/stdc_v0_2" / folder / "benchmark/results.json").read_text(encoding="utf-8"))["rows"]
    assert len(rows) == 48
    assert all(r["legal"] and not r["theory_certified"] for r in rows)
    profiles = []
    for r in rows:
        if r["variant"] != "prior_stdc" or r["protocol"] != "work":
            continue
        s = r["stats"]
        first_best = next(e for e in r["incumbent_history"] if abs(e["J"] - r["J"]) <= 1e-10)
        profiles.append({
            "repeat": r["repeat"], "J": r["J"], "Pd_T": r["Pd_T"],
            "first_best_expanded": first_best["expanded"],
            "first_best_elapsed_s": first_best["elapsed_s"],
            "search_wall_s": r["search_wall_s"],
            "guide_calls": s["guide_calls"], "guide_wall_s": s["guide_wall_s"],
            "bound_calls": s["bound_calls"], "bound_wall_s": s["bound_wall_s"],
            "guide_plus_bound_fraction": (s["guide_wall_s"] + s["bound_wall_s"]) / r["search_wall_s"],
            "candidate_replay_wall_s": s["candidate_replay_wall_s"],
            "candidate_replay_fraction": s["candidate_replay_wall_s"] / r["search_wall_s"],
            "frontier_remaining": s["frontier_remaining"],
        })
    medians = []
    for a in aggregates:
        if a["scenario"] != scene:
            continue
        medians.append({k: a[k] for k in ("protocol", "variant", "J_median", "Pd_T_median",
            "search_wall_s_median", "process_peak_memory_mib_median", "completed", "budget_exceeded")})
    strict_better = []
    for protocol in ("work", "wall"):
        baseline = next(float(a["J_median"]) for a in medians if a["protocol"] == protocol and a["variant"] == "prior_stdc")
        strict_better += [dict(protocol=protocol, variant=a["variant"]) for a in medians
            if a["protocol"] == protocol and a["variant"] not in ("prior_stdc", "paper_baseline")
            and float(a["J_median"]) < baseline - 1e-10]
    dp_stops = [r for r in rows if r["variant"] in ("dp_only", "stdc_dp", "mid_dp")
                and r["stop_reason"] == "dp_max_memory_bytes"]
    assert all(r["work_expanded"] == 0 for r in dp_stops)
    report["scenes"][scene] = {
        "physical_direction_unverified": scene == "bay_of_fundy",
        "particle_sha256": sorted(set(r["particle_sha256"] for r in rows)),
        "medians": medians, "direct_stdc_work_profiles": profiles,
        "strictly_better_latest_median_J": strict_better,
        "dp_memory_aborts": len(dp_stops),
        "dp_memory_aborts_have_zero_expansion": all(r["work_expanded"] == 0 for r in dp_stops),
    }
assert all(not v["strictly_better_latest_median_J"] for v in report["scenes"].values())
report["dp_memory"] = json.loads(dp_path.read_text(encoding="utf-8"))
report["preservation"] = {"checked_files": len(before),
    "all_analyzed_sources_unchanged": all(digest(ROOT / p) == sha for p, sha in before.items()),
    "scope": "the analyzed benchmark inputs and implementation files only; not a fresh complete baseline audit"}
assert report["preservation"]["all_analyzed_sources_unchanged"]
target = OUT / "core_audit.json"
if target.exists():
    raise FileExistsError(target)
target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"status": "passed", "rows_checked": 144,
    "strictly_better_latest_median_J": 0, "new_planner_runs": 0,
    "input_files_unchanged": len(before), "output": str(target)}, ensure_ascii=False))

