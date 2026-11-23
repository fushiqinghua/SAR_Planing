"""B5 isolated, bounded search measurements on the frozen B3 archive. No drift runs."""

import argparse
import cProfile
from collections import Counter
import csv
import io
import json
import os
from pathlib import Path
import platform
import pstats
import subprocess
import sys
from time import perf_counter
import tracemalloc

THREAD_KEYS = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")
for key in THREAD_KEYS:
    os.environ[key] = "1"

import numpy as np
import psutil

from asar_repro.grid import GridGraph
from asar_repro.motion import ParticleMotion
from asar_repro.objective import score_path
from asar_repro.opendrift_adapter import planning_times
from asar_repro.scenario_baselines import parallel_track
from asar_repro.scenarios import config_digest, digest
from asar_repro.search import search_asar
from asar_repro.search_reporting import REQUIRED_FIELDS, environment_versions, search_record

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / "configs/b5_budget_scan.json"


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temp.replace(path)


def load_input(spec, root=ROOT):
    """Validate frozen identities, UTC and particle alignment before timing search."""
    archive, meta_path = root / spec["archive"], root / spec["metadata"]
    if digest(archive) != spec["archive_sha256"] or digest(meta_path) != spec["metadata_sha256"]:
        raise ValueError("B3 frozen input SHA-256 mismatch")
    meta = read_json(meta_path)
    if meta["status"] != "passed" or meta["forcing_kind"] != "historical_real":
        raise ValueError("B5 requires a passed historical-real B3 archive")
    cfg = meta["provenance"]["config"]
    if meta["artifacts_sha256"]["particles.npz"] != spec["archive_sha256"]:
        raise ValueError("B3 metadata archive fingerprint mismatch")
    graph = GridGraph(*cfg["grid_rows_cols"])
    times = planning_times(cfg["cst_utc"], cfg["budget"], cfg["step_s"])
    with np.load(archive, allow_pickle=False) as data:
        if data["config_hash"].item() != meta["config_hash"]:
            raise ValueError("B3 particle config identity mismatch")
        if not np.array_equal(data["time_utc"], times):
            raise ValueError("B3 UTC mismatch")
        if data["cell_ids"].shape != (cfg["budget"] + 1, cfg["particles"]):
            raise ValueError("B3 particle count or horizon mismatch")
        motion = ParticleMotion(data["cell_ids"], graph.size, data["trajectory_id"])
        p = data["initial_weights"].copy()
    start = graph.vertex(graph.rows // 2, graph.cols // 2)
    return graph, dict(start=start, budget=cfg["budget"], p=p, q=cfg["audit_q"], motion=motion), meta


def prepare_warm(spec, output):
    graph, args, meta = load_input(spec)
    started = perf_counter()
    path = parallel_track(graph, **args)
    elapsed = perf_counter() - started
    score = score_path(graph, path, **args)
    warm = dict(path=list(path), J=score.J, Pd_T=score.pd_final, warm_start_s=elapsed,
                particle_archive_sha256=spec["archive_sha256"], metadata_sha256=spec["metadata_sha256"],
                source="ParallelTrack", computed_once=True,
                timing="measured once; same unamortized construction cost charged to each run")
    save_json(output / "warm_start.json", warm)
    return warm


def run_options(spec):
    return [dict(heuristic=h, epsilon=e, max_expansions=n, max_seconds=s, max_open=spec["max_open"])
            for h in spec["heuristics"] for e in spec["epsilon"]
            for n in spec["max_expansions"] for s in spec["max_seconds"]]


def run_worker(spec, options, warm, *, diagnostics=None, artifact_prefix=None):
    graph, args, meta = load_input(spec)
    if (warm["particle_archive_sha256"] != spec["archive_sha256"] or
            warm["metadata_sha256"] != spec["metadata_sha256"]):
        raise ValueError("warm-start input identity mismatch")
    check = score_path(graph, warm["path"], **args)
    if abs(check.J - warm["J"]) > 1e-10:
        raise ValueError("warm-start replay differs")
    proc = psutil.Process()
    before = proc.memory_info().rss / 2**20
    limits = {k: options[k] for k in ("max_expansions", "max_open", "max_seconds")}
    profiler = cProfile.Profile() if diagnostics == "cprofile" else None
    if diagnostics == "memory":
        tracemalloc.start()
    if profiler:
        profiler.enable()
    started = perf_counter()
    result = search_asar(graph, **args, heuristic=options["heuristic"], epsilon=options["epsilon"],
                         initial_path=warm["path"], **limits)
    elapsed = perf_counter() - started
    if profiler:
        profiler.disable()
    memory = proc.memory_info()
    peak = memory.peak_wset / 2**20 if sys.platform == "win32" else None
    allocation_peak = None
    if diagnostics == "memory":
        _, allocation_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        allocation_peak /= 2**20
    if profiler:
        profiler.dump_stats(str(artifact_prefix) + ".prof")
        with Path(str(artifact_prefix) + ".txt").open("w", encoding="utf-8") as handle:
            pstats.Stats(profiler, stream=handle).strip_dirs().sort_stats("cumulative").print_stats(40)
        stats = pstats.Stats(profiler)
        hotspots = [dict(file=k[0], line=k[1], function=k[2], primitive_calls=v[0], calls=v[1],
                         self_s=v[2], cumulative_s=v[3]) for k, v in stats.stats.items()]
        save_json(Path(str(artifact_prefix) + "_stats.json"), sorted(hotspots, key=lambda x: -x["cumulative_s"]))
    context = dict(scenario_id=meta["scenario"], forcing_kind=meta["forcing_kind"],
                   source_manifest_sha256=meta["provenance"]["input_fingerprints"]["manifest_sha256"],
                   particle_archive_sha256=spec["archive_sha256"], seed=meta["provenance"]["config"]["seed"],
                   config_hash=config_digest(dict(spec=spec, options=options, warm_path=warm["path"], diagnostics=diagnostics)),
                   git_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip())
    row = search_record(result, graph, **args, planner_wall_s=elapsed, warm_start_s=warm["warm_start_s"],
                        limits=limits, provenance=context, initial_source="ParallelTrack")
    # Independent ID-mask replay does not reuse the search's sorted member index.
    w, curve = args["p"].copy(), [float(args["p"].sum())]
    for t, vertex in enumerate(result.path[1:], 1):
        w[args["motion"].cell_ids[t] == vertex] *= 1 - args["q"]
        curve.append(float(w.sum()))
    replay_error = abs(sum(curve[1:]) - row["J"])
    if replay_error > 1e-10 or not np.allclose(curve, row["M_0_to_T"], atol=1e-12, rtol=0):
        raise AssertionError("independent particle replay differs")
    if "opendrift" in sys.modules:
        raise AssertionError("planning imported OpenDrift")
    row.update(experiment_label=meta["experiment_label"], shoreline_policy=meta["shoreline_policy"],
               diagnostics=diagnostics, peak_process_MiB=peak, rss_before_search_MiB=before,
               search_allocation_peak_MiB=allocation_peak, memory_scope="isolated process lifetime peak working set through search return",
               frontier_belief_lower_bound_MiB=result.peak_open * args["p"].nbytes / 2**20,
               peak_open_does_not_count="ancestors retained by parent links or heuristic temporaries",
               warm_start_accounting=warm["timing"], warm_path_sha256=config_digest(warm["path"]),
               J_over_PT=row["J"] / warm["J"], independent_replay_error=replay_error,
               thread_environment={k: os.environ[k] for k in THREAD_KEYS}, cpu_affinity=proc.cpu_affinity(),
               opendrift_imported=False, timed_out=result.stop_reason == "max_seconds")
    return row


def failed_worker_row(spec, options, reason, details, elapsed):
    """Watchdog/crash is never a zero-cost, completed or certified plan."""
    row = dict.fromkeys(REQUIRED_FIELDS)
    row.update(options, scenario_id="lake_ontario", forcing_kind="historical_real",
               algorithm="ASAR_paper" if options["heuristic"] == "paper_greedy" else "ASAR_mass_lb",
               search_status="budget_exceeded" if reason == "worker_watchdog" else "worker_failed",
               stop_reason=reason, found_feasible_path=False, theoretical_bound_applicable=False,
               completed_for_certificate=False, discrete_model_certified=False, search_completed=False,
               result_class="aborted_without_path", path=None, J=None, Pd_T=None, M_T=None,
               worker_wall_s=elapsed, error=details, particle_archive_sha256=spec["archive_sha256"],
               peak_process_MiB=None, timed_out=reason == "worker_watchdog")
    return row


def isolated_run(spec, config_path, output, options, name, diagnostics=None):
    prefix = output / name
    options_path = output / "requests" / (name + ".json")
    save_json(options_path, options)
    cmd = [sys.executable, str(Path(__file__).resolve()), "--config", str(config_path.resolve()),
           "--output-dir", str(output), "--worker", str(options_path), "--name", name]
    if diagnostics:
        cmd += ["--diagnostics", diagnostics]
    started = perf_counter()
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                   timeout=options["max_seconds"] + spec["watchdog_grace_s"])
        if completed.returncode:
            row = failed_worker_row(spec, options, "worker_error", completed.stderr, perf_counter() - started)
        else:
            row = read_json(prefix.with_suffix(".json"))
            row["worker_wall_s"] = perf_counter() - started
    except subprocess.TimeoutExpired:
        row = failed_worker_row(spec, options, "worker_watchdog", "worker killed after search limit plus grace", perf_counter() - started)
    save_json(prefix.with_suffix(".json"), row)
    print(name, row["search_status"], row["stop_reason"], "J", row["J"], "expanded", row.get("expanded"), flush=True)
    return row


def manifest(spec, config_path, warm):
    source = [Path(__file__).resolve(), config_path.resolve()]
    source += [ROOT / "src/asar_repro" / (name + ".py") for name in (
        "search", "heuristic", "motion", "belief", "objective", "grid", "search_reporting", "scenario_baselines")]
    stream = io.StringIO()
    from contextlib import redirect_stdout
    with redirect_stdout(stream):
        np.show_config()
    proc = psutil.Process()
    return dict(stage="B5", config=spec, environment=environment_versions(), cpu=platform.processor(),
                logical_cpus=psutil.cpu_count(), physical_cpus=psutil.cpu_count(logical=False), cpu_affinity=proc.cpu_affinity(),
                thread_environment={k: os.environ[k] for k in THREAD_KEYS}, numpy_build=stream.getvalue(),
                memory_total_MiB=psutil.virtual_memory().total / 2**20,
                code_sha256={str(p.relative_to(ROOT)): digest(p) for p in source},
                git_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                git_commit_scope="base HEAD plus exact executing source fingerprints",
                warm_start=warm, cache_policy="fresh child per search; frozen NPZ, fresh ParticleMotion indexes; no result cache",
                caveat="one timing per cell, normal Windows scheduling; no dedicated CPU reservation",
                scope="B5 performance audit, not a reproduction of author forcing or manual PT")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/baseline_v1.1/b5")
    parser.add_argument("--phase", choices=("pilot", "scan"), default="pilot")
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--name", help=argparse.SUPPRESS)
    parser.add_argument("--diagnostics", choices=("cprofile", "memory"), help=argparse.SUPPRESS)
    opts = parser.parse_args()
    spec, output = read_json(opts.config), opts.output_dir.resolve()
    if spec["threads"] != 1:
        raise ValueError("this experiment fixes numerical thread pools to one")
    output.mkdir(parents=True, exist_ok=True)
    if opts.worker:
        row = run_worker(spec, read_json(opts.worker), read_json(output / "warm_start.json"),
                         diagnostics=opts.diagnostics, artifact_prefix=output / opts.name)
        save_json(output / (opts.name + ".json"), row)
        return
    warm_file = output / "warm_start.json"
    warm = read_json(warm_file) if warm_file.exists() else prepare_warm(spec, output)
    save_json(output / (opts.phase + "_manifest.json"), manifest(spec, opts.config, warm))
    rows = []
    if opts.phase == "pilot":
        for key in ("profile", "mass_profile"):
            options = spec[key]
            rows.append(isolated_run(spec, opts.config, output, options, key + "_plain"))
            rows.append(isolated_run(spec, opts.config, output, options, key + "_cprofile", "cprofile"))
            rows.append(isolated_run(spec, opts.config, output, options, key + "_memory", "memory"))
    else:
        for i, options in enumerate(run_options(spec)):
            rows.append(isolated_run(spec, opts.config, output, options, f"scan_{i:02d}"))
            save_json(output / "scan_runs.json", rows)
        for h in spec["heuristics"]:
            options = dict(heuristic=h, epsilon=1., max_expansions=5000, max_seconds=60,
                           max_open=spec["historical_max_open_probe"])
            rows.append(isolated_run(spec, opts.config, output, options, "open_probe_" + h))
    save_json(output / (opts.phase + "_runs.json"), rows)
    if any(r["stop_reason"] in ("worker_watchdog", "worker_error") for r in rows):
        raise SystemExit("Explicit worker failure recorded; inspect run JSON")


if __name__ == "__main__":
    main()
