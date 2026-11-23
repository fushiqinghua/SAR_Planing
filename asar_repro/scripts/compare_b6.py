"""B6: same frozen historical particles, independent replay, no drift or legacy writes."""

import argparse
import csv
from pathlib import Path
import sys

import numpy as np

from benchmark_b5 import ROOT, load_input, prepare_warm, isolated_run, manifest, read_json, save_json
from report_b5 import export_csv
from asar_repro.objective import score_path
from asar_repro.opendrift_adapter import planning_times
from asar_repro.scenarios import config_digest, digest
from asar_repro.search_reporting import REQUIRED_FIELDS


def csv_records(path, rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def check_output(output):
    output = output.resolve()
    if output.is_relative_to((ROOT / "outputs/stage7").resolve()):
        raise ValueError("Stage 7 output is protected")
    if any((output / p).exists() for p in ("run_manifest.json", "metrics.csv", "b6_workers", "runs.json", "step_metrics.csv", "paths.png", "probability_snapshots.png", "survival_curves.png", "runtime_expansions.png", "environment_inputs.png", "environment_comparison.json", "environment_mass.csv", "comparison.md")):
        raise FileExistsError("B6 result exists; use a fresh --output-dir, never overwrite frozen results")
    return output


def replay(row, graph, args, times, archive_hash):
    """Validate the exact clock/input contract then replay with scorer AND ID masks."""
    if row["particle_archive_sha256"] != archive_hash or row["T"] != args["budget"] or row["q"] != args["q"]:
        raise ValueError("run input identity or T/q mismatch")
    expected_clock = config_digest([str(t) for t in times])
    if row["time_utc_sha256"] != expected_clock or len(times) != args["budget"] + 1:
        raise ValueError("run UTC identity mismatch")
    if row["path"] is None:
        if any(row[k] is not None for k in ("J", "Pd_T", "M_T")):
            raise ValueError("missing route has non-null scores")
        return [], None
    score = score_path(graph, row["path"], **args, record_beliefs=True)
    if not np.allclose([row["J"], row["Pd_T"], row["M_T"]],
                       [score.J, score.pd_final, score.survival[-1]], atol=1e-10, rtol=0):
        raise ValueError("recorded J/Pd/M differs from independent score_path replay")
    w = args["p"].copy()
    manual = [float(w.sum())]
    for t, vertex in enumerate(row["path"][1:], 1):
        w[args["motion"].cell_ids[t] == vertex] *= 1 - args["q"]
        manual.append(float(w.sum()))
    np.testing.assert_allclose(manual, score.survival, atol=1e-12, rtol=0)
    np.testing.assert_allclose(sum(manual[1:]), row["J"], atol=1e-10, rtol=0)
    ledger = []
    mass_error = 0.
    for t, vertex in enumerate(row["path"]):
        cells = args["motion"].cell_mass(score.beliefs[t], t)
        mass_error = max(mass_error, abs(float(cells.sum()) - score.survival[t]))
        entry = dict(run_id=row["run_id"], algorithm=row["algorithm"], heuristic=row["heuristic"],
                     epsilon=row["epsilon"], search_status=row["search_status"],
                     incumbent_source=row["incumbent_source"], forcing_kind="historical_real",
                     t=t, utc=np.datetime_as_string(times[t], unit="ns") + "Z", vertex=vertex,
                     M_t=float(score.survival[t]), Pd_t=float(1 - score.survival[t]), J_t=float(score.g[t]),
                     delta_Pd=0. if t == 0 else float(score.delta_pd[t-1]),
                     searchable=float(cells[:graph.size].sum()))
        entry.update({k: float(cells[graph.size+i]) for i, k in enumerate(("land", "outside", "inactive", "unknown"))})
        ledger.append(entry)
    if np.max(np.diff(score.survival)) > 1e-12 or mass_error > 1e-12:
        raise AssertionError("replay violates mass conservation")
    row.update(legal=True, start_vertex=args["start"], replay_J_error=abs(sum(manual[1:]) - row["J"]),
               replay_Pd_error=abs(1-manual[-1]-row["Pd_T"]), max_mass_error=mass_error,
               replay_validated=True)
    return ledger, score


def environment_comparison(spec, meta, output):
    """Input contrast only; never mix synthetic scores with the real ranking."""
    old = read_json(ROOT / spec["synthetic_report"])["metadata"]
    cfg = meta["provenance"]["config"]
    synthetic = ROOT / old["archive"].replace("\\", "/")
    if digest(synthetic) != old["archive_sha256"]:
        raise ValueError("frozen synthetic input hash mismatch")
    comparable = ("seed", "radius_m", "particles", "incident_utc", "cst_utc", "lkp_lon_lat",
                  "csp_lon_lat", "object_key", "budget", "grid_rows_cols", "integration_s", "step_s", "cell_width_m")
    for k in comparable:
        if cfg[k] != old["drift_config"][k]:
            raise ValueError(f"environment comparison differs in mission parameter {k}")
    grid_size = int(np.prod(cfg["grid_rows_cols"]))
    from asar_repro.grid import GridGraph
    from asar_repro.gridding import ParticleGrid
    grid = ParticleGrid(GridGraph(*cfg["grid_rows_cols"]), cfg["csp_lon_lat"], cfg["cell_width_m"])
    summary, clouds, special_rows = {}, {}, []
    for kind, archive in (("historical_real", ROOT/spec["archive"]), ("constant_synthetic", synthetic)):
        with np.load(archive, allow_pickle=False) as a:
            expected_times = planning_times(cfg["cst_utc"], cfg["budget"], cfg["step_s"])
            np.testing.assert_array_equal(a["time_utc"], expected_times)
            w = a["initial_weights"]
            x, y = grid.projection.transform(a["lon"], a["lat"])
            rx, ry = grid.projection.transform(a["raw_lon"], a["raw_lat"])
            clouds[kind] = dict(x=x, y=y, raw_x=rx, raw_y=ry, weights=w)
            stats = []
            for t, frame in enumerate(a["cell_ids"]):
                mass = np.bincount(frame, weights=w, minlength=grid_size+4)
                if abs(mass.sum()-1) > 1e-12:
                    raise AssertionError("input special-bin mass lost")
                item = dict(forcing_kind=kind, t=t, utc=str(a["time_utc"][t])+"Z", searchable=float(mass[:grid_size].sum()))
                item.update({k:float(mass[grid_size+i]) for i,k in enumerate(("land","outside","inactive","unknown"))})
                special_rows.append(item)
            for t in (0, cfg["budget"]):
                valid = np.isfinite(x[t]) & np.isfinite(y[t])
                valid_mass = float(w[valid].sum())
                stats.append(dict(t=t, located_mass=valid_mass,
                                  centroid_east_north_m=[float(np.average(z[t, valid], weights=w[valid])) for z in (x,y)],
                                  radial_distance_quantiles_m=np.quantile(np.hypot(x[t,valid],y[t,valid]), [.05,.5,.95]).tolist()))
            summary[kind] = dict(archive_sha256=digest(archive), position_statistics=stats)
    audit_path = ROOT / "outputs/baseline_v1.1/b2/forcing_audit.json"
    if digest(audit_path) != meta["provenance"]["input_fingerprints"]["b2_audit_sha256"]:
        raise ValueError("B2 audit hash mismatch")
    audit = read_json(audit_path)
    summary["historical_real"]["forcing_samples"] = audit["samples"]
    summary["historical_real"]["sample_sites_in_order"] = list(audit["sample_sites"])
    summary["historical_real"]["cycle_policy"] = audit["cycle_policy"]
    forcing = old["drift_config"]["forcing"]
    summary["constant_synthetic"]["constant_forcing_m_s"] = forcing
    for name, cols in (("wind", ("x_wind", "y_wind")), ("current", ("x_sea_water_velocity", "y_sea_water_velocity"))):
        vals = np.asarray([sample["east_north_m_s"] for event in audit["samples"] for sample in event[name][:2] if sample["status"] == "ok"])
        summary["historical_real"][name+"_site_event_stats"] = dict(count=len(vals),
            east_north_min_m_s=vals.min(axis=0).tolist(), east_north_mean_m_s=vals.mean(axis=0).tolist(),
            east_north_max_m_s=vals.max(axis=0).tolist(), speed_range_m_s=[float(np.linalg.norm(vals,axis=1).min()),float(np.linalg.norm(vals,axis=1).max())],
            scope="LKP and CSP at 4 B2 events; not domain or particle-weighted average")
    summary["interpretation"] = "Matched mission parameters, different environment inputs; no cross-forcing algorithm ranking"
    summary["matched_parameters"] = {k:cfg[k] for k in comparable}
    save_json(output / "environment_comparison.json", summary)
    csv_records(output / "environment_mass.csv", special_rows)
    return summary, clouds


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/b6_comparison.json")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/baseline_v1.1/lake_ontario_real")
    opts = parser.parse_args()
    spec = read_json(opts.config)
    output = check_output(opts.output_dir)
    graph, args, meta = load_input(spec)
    cfg = meta["provenance"]["config"]
    times = planning_times(cfg["cst_utc"], cfg["budget"], cfg["step_s"])
    protected = list((ROOT / "outputs/stage7").rglob("*"))
    protected += list((ROOT / "outputs/baseline_v1.1/lake_ontario_real").glob("*"))
    protected += [ROOT / "outputs/particles/stage5_leeway.npz"]
    hashes = {str(p.relative_to(ROOT)):digest(p) for p in protected if p.is_file()}
    raw = meta["provenance"]["input_fingerprints"]["sources"]
    verified = []
    for kind, sources in raw.items():
        for source in sources:
            path = ROOT / source["local_path"]
            actual = digest(path)
            if actual != source["sha256"]:
                raise ValueError("original forcing hash mismatch: " + str(path))
            verified.append(dict(kind=kind, path=source["local_path"], sha256=actual))
    workers = output / "b6_workers"
    workers.mkdir(parents=True)
    warm = prepare_warm(spec, workers)
    run_manifest = manifest(spec, opts.config, warm)
    run_manifest.update(stage="B6", status="running", scenario=meta["scenario"], mission=cfg,
                        experiment_label=meta["experiment_label"], shoreline_policy=meta["shoreline_policy"],
                        forcing_sources=raw, verified_raw_sources=verified,
                        protected_before_sha256=hashes, aco_inspired_run=False,
                        command=[sys.executable,str(Path(__file__).resolve()),"--config",str(opts.config.resolve()),"--output-dir",str(output)],
                        time_utc=[str(t)+"Z" for t in times], scope="B6 same-input real reconstruction comparison")
    for name in ("compare_b6.py", "plot_b6.py", "report_b5.py"):
        run_manifest["code_sha256"]["scripts/"+name] = digest(ROOT / "scripts" / name)
    save_json(output / "run_manifest.json", run_manifest)
    pt = dict.fromkeys(REQUIRED_FIELDS)
    pt.update(scenario_id=meta["scenario"], forcing_kind="historical_real", algorithm="ParallelTrack",
              heuristic=None, epsilon=None, T=args["budget"], q=args["q"], search_status="completed",
              stop_reason=None, incumbent_source="ParallelTrack", found_feasible_path=True,
              theoretical_bound_applicable=False, completed_for_certificate=False, discrete_model_certified=False,
              search_completed=False, result_class="completed_baseline", path=warm["path"], J=warm["J"], Pd_T=warm["Pd_T"],
              M_T=1-warm["Pd_T"], planner_wall_s=warm["warm_start_s"], warm_start_s=0., total_wall_s=warm["warm_start_s"],
              particle_archive_sha256=spec["archive_sha256"], source_manifest_sha256=meta["provenance"]["input_fingerprints"]["manifest_sha256"],
              config_hash=config_digest(dict(config=spec, method="ParallelTrack")), seed=cfg["seed"],
              environment_versions=run_manifest["environment"], git_commit=run_manifest["git_commit"],
              experiment_label=meta["experiment_label"], shoreline_policy=meta["shoreline_policy"],
              J_over_PT=1., run_id="PT", timing_scope="PT construction; excludes preprocessing and replay")
    rows = [pt]
    for mode in spec["heuristics"]:
        for eps in spec["epsilon"]:
            name = f"{mode}_eps_{eps:g}".replace(".", "p")
            row = isolated_run(spec, opts.config, workers, dict(heuristic=mode,epsilon=eps,**spec["limits"]), name)
            row["run_id"] = name
            rows.append(row)
            save_json(output / "runs.json", rows)
            if row["stop_reason"] in ("worker_watchdog", "worker_error"):
                run_manifest["status"] = "failed"
                save_json(output / "run_manifest.json", run_manifest)
                raise RuntimeError("B6 worker failure recorded; no completed comparison claimed")
    ledger = []
    for row in rows:
        row["time_utc_sha256"] = config_digest([str(t) for t in times])
        steps, score = replay(row, graph, args, times, spec["archive_sha256"])
        ledger.extend(steps)
        row["M_0_to_T"] = None if score is None else score.survival.tolist()
    save_json(output / "runs.json", rows)
    export_csv(output / "metrics.csv", rows)
    csv_records(output / "step_metrics.csv", ledger)
    env, clouds = environment_comparison(spec, meta, output)
    from plot_b6 import generate
    generate(output, graph, args, times, cfg, rows, spec, env, clouds)
    if any(digest(ROOT/k) != v for k,v in hashes.items()):
        raise AssertionError("protected Stage 7 or frozen B3 artifact changed")
    run_manifest.update(status="passed", protected_after_unchanged=True,
                        max_replay_J_error=max(r["replay_J_error"] for r in rows),
                        max_replay_Pd_error=max(r["replay_Pd_error"] for r in rows),
                        search_completed=sum(r["search_completed"] for r in rows),
                        search_aborted=sum(r["search_status"]=="budget_exceeded" for r in rows),
                        artifacts_sha256={p.name:digest(p) for p in output.iterdir() if p.is_file() and p.name not in ("run_manifest.json",)})
    save_json(output / "run_manifest.json", run_manifest)
    print(dict(status="passed", runs=len(rows), search_completed=run_manifest["search_completed"],
               search_aborted=run_manifest["search_aborted"], max_replay_J_error=run_manifest["max_replay_J_error"]))


if __name__ == "__main__":
    main()
