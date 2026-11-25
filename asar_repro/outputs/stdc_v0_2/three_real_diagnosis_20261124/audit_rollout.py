"""Read-only audit of frozen midpoint runs; writes only a new diagnosis JSON.

Run with maritime-sar Python. No search, OpenDrift, or evaluator is invoked.
An existing output is refused so evidence is never silently overwritten.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


SCENES = (
    ("Lake Ontario", "trajectory_20261124", ""),
    ("Hudsons Bay", "additional_real_20261124", "arctic_ocean_"),
    ("Bay of Fundy", "fundy_repair_20261124", "bay_of_fundy_"),
)


def load(path):
    return json.loads(path.read_bytes())


def fingerprint(path):
    return dict(path=str(path.resolve()), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def phase_fields(phase):
    r = phase["result"]
    st = r["stats"]
    fields = ("expanded", "generated", "pruned", "J", "Pd", "wall_s", "status", "stop_reason",
              "incumbent_source", "completion_reason")
    counters = ("accepted_improvements", "complete_candidates", "beam_discarded",
                "diversity_selections_outside_quality_beam", "diversity_wall_s", "guide_wall_s",
                "bound_wall_s", "replay_wall_s", "guide_calls", "bound_calls", "anchor_depths",
                "diversity_geometry_entries", "physical_frontier_remaining")
    return dict(name=phase["name"], limits=phase["limits"], **{k: r.get(k) for k in fields},
                stats={k: st.get(k) for k in counters}, anchors=r.get("anchors", []),
                incumbent_history=r.get("incumbent_history", []), path=r["path"])


def audit(root):
    rows, comparisons = [], []
    for scene, directory, prefix in SCENES:
        base = root / "outputs/stdc_v0_2" / directory / "benchmark"
        direct_file = base / f"{prefix}prior_stdc_work_r0/raw_result.json"
        direct = load(direct_file)["result"]
        for cap in ("work", "wall"):
            for variant in ("mid_plain", "mid_diverse", "mid_dp"):
                for repeat in range(3):
                    folder = base / f"{prefix}{variant}_{cap}_r{repeat}"
                    raw = load(folder / "raw_result.json")
                    result = load(folder / "result.json")
                    command = load(folder / "command.json")
                    final = raw["result"]
                    phases = [phase_fields(p) for p in raw["phases"]]
                    limits = result["limits"]
                    work = final["stats"]["work_expanded"]
                    row = dict(scene=scene, protocol=cap, variant=variant, repeat=repeat,
                               source_files=[fingerprint(folder / f) for f in
                                             ("raw_result.json", "result.json", "command.json", "stderr.txt")],
                               command=command["command"], command_seed=command.get("seed"),
                               final={k: final.get(k) for k in
                                      ("J", "Pd", "wall_s", "status", "stop_reason", "incumbent_source")},
                               total_work_expanded=work, limits=limits,
                               unspent_work=None if limits["max_expansions"] is None else
                                   max(0, limits["max_expansions"] - work),
                               unspent_wall_s=max(0., limits["max_seconds"] - final["wall_s"]),
                               phases=phases, legal=result["legal"],
                               replay_error_J=result.get("replay_error_J", result.get("replay_error")),
                               guarantee=result["guarantee"], particle_sha256=result["particle_sha256"],
                               forcing_kind=result["forcing_kind"], experiment_label=result["experiment_label"],
                               particle_seed=result["particle_seed"],
                               rollout_improved=bool(phases and phases[1]["J"] < phases[0]["J"]-1e-10))
                    rows.append(row)
        plain_rows = [r for r in rows if r["scene"] == scene and r["protocol"] == "work"
                      and r["variant"] == "mid_plain"]
        diverse_rows = [r for r in rows if r["scene"] == scene and r["protocol"] == "work"
                        and r["variant"] == "mid_diverse"]
        for plain, diverse in zip(plain_rows, diverse_rows):
            seed = plain["phases"][0]
            other_seed = diverse["phases"][0]
            firstdiff = next((i for i, (a, b) in enumerate(zip(seed["path"], direct["path"]))
                              if a != b), None)
            comparisons.append(dict(scene=scene, repeat=plain["repeat"],
                same_seed_path=seed["path"] == other_seed["path"],
                same_seed_J=seed["J"] == other_seed["J"],
                same_seed_expanded=seed["expanded"] == other_seed["expanded"],
                seed_J=seed["J"], direct_work_r0_J=direct["J"],
                first_path_difference_seed_vs_direct_work_r0=firstdiff,
                direct_work_r0_source=fingerprint(direct_file),
                direct_work_r0_incumbent_history=direct["incumbent_history"],
                plain_final_J=plain["final"]["J"], diverse_final_J=diverse["final"]["J"],
                anchor_depths=plain["phases"][1]["stats"]["anchor_depths"]))
    non_dp = [r for r in rows if r["variant"] != "mid_dp"]
    summary = {}
    for cap in ("work", "wall"):
        cohort = [r for r in non_dp if r["protocol"] == cap]
        summary[cap] = dict(runs=len(cohort), improved_runs=sum(r["rollout_improved"] for r in cohort),
            accepted_improvement_events=sum(r["phases"][1]["stats"]["accepted_improvements"] for r in cohort),
            zero_complete_candidate_runs=sum(r["phases"][1]["stats"]["complete_candidates"] == 0 for r in cohort))
    return dict(schema="rollout_diagnosis_v1", artifact_type="read_only_frozen_result_audit",
        script=fingerprint(Path(__file__)), records=rows, same_seed_work_comparisons=comparisons,
        non_dp_summary=summary,
        qualifications=[
            "Complete candidates are terminal-depth nodes; zero does not imply every proposal is invalid.",
            "Scheduled beam completion is not exhaustive search completion or an optimality certificate.",
            "Existing runs have no node-level selection trace: exact loss of a winning prefix remains unverified.",
            "Bay of Fundy uses authorized official angle with physical direction unverified.",
            "Unspent budget is descriptive; final global status may still be budget_exceeded because seed stopped.",
        ])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("rollout_audit.json"))
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"Refusing to overwrite {args.output}; pass a new --output path.")
    report = audit(args.root.resolve())
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    print(json.dumps(dict(output=str(args.output.resolve()), records=len(report["records"]),
                         non_dp_summary=report["non_dp_summary"]), ensure_ascii=False))
