"""Compare planners on one frozen particle ensemble per Table I mission."""

import argparse
import json
from pathlib import Path
from time import perf_counter

import numpy as np
import yaml

from asar_repro.objective import score_path
from asar_repro.scenario_baselines import aco_inspired, parallel_track
from asar_repro.scenarios import config_digest, prepare_input, drift_config
from asar_repro.search import search_asar


ROOT = Path(__file__).resolve().parents[1]


def compare(root, folder, spec, name):
    folder.mkdir(parents=True, exist_ok=True)
    case = spec["scenarios"][name]
    cfg = drift_config(spec, case)
    grid, motion, p, times, meta = prepare_input(root, folder, name, cfg)
    args = dict(start=grid.vertex(grid.rows // 2, grid.cols // 2), budget=cfg["budget"],
                p=p, q=spec["q"], motion=motion)
    common = dict(scenario=name, config_hash=config_digest({k: v for k, v in spec.items()
                  if k != "scenarios"} | {"case": case}), archive_sha256=meta["archive_sha256"],
                  drift_seed=cfg["seed"], forcing_kind=cfg["forcing_kind"],
                  data_availability=spec["data_availability"], T=cfg["budget"], q=spec["q"],
                  start=args["start"], steps_s=cfg["step_s"])
    rows = []

    def record(method, path, elapsed, *, epsilon=None, algorithm_seed=None, status="completed",
               stop_reason=None, source=None, expanded=None, generated=None, pruned=None,
               peak_open=None, paper_cpp_s=None, warm_start_s=0.):
        score = score_path(grid, path, **args)
        if np.any(np.diff(score.survival) > 1e-12):
            raise AssertionError("undetected mass increased")
        np.testing.assert_allclose(score.survival[1:].sum(), score.J, rtol=0, atol=1e-12)
        rows.append(dict(common, method=method, epsilon=epsilon, algorithm_seed=algorithm_seed,
                         J=score.J, Pd_T=score.pd_final, M_T=float(score.survival[-1]),
                         J_over_PT=score.J / rows[0]["J"] if rows else 1.,
                         legal=True, moves=len(path)-1, planner_wall_s=elapsed, warm_start_s=warm_start_s,
                         total_wall_s=elapsed+warm_start_s, status=status, stop_reason=stop_reason,
                         timed_out=stop_reason == "max_seconds", incumbent_source=source,
                         certified=False, expanded=expanded, generated=generated, pruned=pruned,
                         peak_open=peak_open, paper_cpp_s=paper_cpp_s, path=list(map(int, path)),
                         M_0_to_T=score.survival.tolist()))
        return score

    start = perf_counter()
    pt = parallel_track(grid, **args)
    pt_wall = perf_counter() - start
    record("ParallelTrack", pt, pt_wall, source="dynamic_parallel_track")
    for epsilon, paper_s in zip(spec["epsilon"], case["table_ii_s"], strict=True):
        start = perf_counter()
        result = search_asar(grid, **args, heuristic="paper_greedy", epsilon=epsilon,
                             initial_path=pt, **spec["search_limits"])
        elapsed = perf_counter() - start
        score = record("ASAR_paper", result.path, elapsed, epsilon=epsilon, status=result.status,
                       stop_reason=result.stop_reason, source="ParallelTrack" if
                       result.incumbent_source == "initial_path" else result.incumbent_source,
                       expanded=result.expanded, generated=result.generated, pruned=result.pruned,
                       peak_open=result.peak_open, paper_cpp_s=paper_s, warm_start_s=pt_wall)
        np.testing.assert_allclose(result.J, score.J, atol=1e-12, rtol=0)
    settings = spec["aco"]
    for seed in range(settings["first_seed"], settings["first_seed"] + settings["trials"]):
        start = perf_counter()
        path = aco_inspired(grid, args, settings, seed)
        record("ACO_inspired", path, perf_counter() - start, algorithm_seed=seed, source="ant_system")
    costs = np.array([row["J"] for row in rows if row["method"] == "ACO_inspired"])
    rng = np.random.default_rng(settings["bootstrap_seed"])
    medians = np.median(rng.choice(costs, size=(settings["bootstrap_draws"], len(costs))), axis=1)
    meta.update(case, scenario=name, paper_source=spec["paper_source"], paper_url=spec["paper_url"],
                catalogs={k: spec["archive_catalogs"][k] for k in (case["wind"], case["current"])},
                forcing_kind=spec["forcing_kind"], data_availability=spec["data_availability"],
                altitude_ft=spec["altitude_ft"], speed_m_s=spec["speed_m_s"],
                search_limits=spec["search_limits"], aco_settings=settings, q=spec["q"],
                time_utc=[np.datetime_as_string(t, unit="ms") + "Z" for t in times],
                aco_median_J=float(np.median(costs)), aco_median_J_ci99=np.quantile(medians,[.005,.995]).tolist())
    report = dict(metadata=meta, runs=rows)
    tmp = folder / "results.tmp.json"
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=1, allow_nan=False), encoding="utf-8")
    tmp.replace(folder / "results.json")
    print(name, "runs", len(rows), "PT", rows[0]["J"], "ASAR", rows[1]["J"],
          rows[1]["status"], "ACO median", meta["aco_median_J"], flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/stage7_scenarios.yaml")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/stage7")
    parser.add_argument("--scenario", help="one scenario ID; default runs all in guide order")
    opts = parser.parse_args()
    spec = yaml.safe_load(opts.config.read_bytes())
    if opts.scenario and opts.scenario not in spec["scenarios"]:
        parser.error("unknown scenario ID")
    for name in ([opts.scenario] if opts.scenario else spec["scenarios"]):
        compare(ROOT, opts.output_dir.resolve() / name, spec, name)


if __name__ == "__main__":
    main()
