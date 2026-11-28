#!/usr/bin/env python3
"""Measure exact-merge work and trace changes at one fixed expansion count."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import os
import subprocess
import sys
import time
import traceback

import run_eight_neighbor_rolling_merge as inherited


ROOT = inherited.ROOT
OUTPUT_ROOT = ROOT / "outputs/eight_neighbor_prefix_order_20261128"
MODES = ("off", "shadow", "exact")
EXPANSIONS = 4096
WALL_CEILING_S = 120.0
SCORE_TOLERANCE = 1e-8
read = inherited.read
save = inherited.save
digest = inherited.digest
object_digest = inherited.object_digest


def checked_output(path):
    path = path.resolve()
    root = OUTPUT_ROOT.resolve()
    if path == root or not path.is_relative_to(root):
        raise ValueError(f"Use a fresh batch directory under {root}")
    return path


def make_protocol():
    config_path = inherited.DEFAULT_CONFIG
    config = inherited.check_config(read(config_path))
    return {
        "schema_version": 1,
        "stage": "equal_expansion_diagnostic",
        "instances": list(config["instances"]),
        "modes": list(MODES),
        "expected_expansions": EXPANSIONS,
        "wall_ceiling_s": WALL_CEILING_S,
        "score_tolerance": SCORE_TOLERANCE,
        "configuration_sha256": digest(config_path),
        "configuration": config,
        "source_sha256": inherited.source_inventory(config_path),
        "reference_evidence": inherited.reference_evidence(config, load_archives=True),
        "environment": inherited.environment(),
        "run_scope": "fixed expansion count with charged index and trace instrumentation",
    }


def verify_frozen(protocol):
    config_path = inherited.DEFAULT_CONFIG
    if (protocol["configuration_sha256"] != digest(config_path)
            or protocol["source_sha256"] != inherited.source_inventory(config_path)
            or protocol["environment"] != inherited.environment()):
        raise ValueError("Code, configuration or runtime changed during the diagnostic")
    reference = protocol["reference_evidence"]
    inherited.verify_files(reference["files"])
    inherited.verify_git_blobs(reference["git_blobs"])


def task_id(task):
    return f"{task['instance']}__{task['mode']}"


def semantic_records(records):
    return [
        {key: value for key, value in item.items() if key != "elapsed_s"}
        for item in records
    ]


def verify_result(task, result, protocol):
    config = protocol["configuration"]
    reference = protocol["reference_evidence"]
    seed = reference["references"][task["instance"]]
    hashes = reference["archive_hashes"][task["instance"]]
    solver = result["solver"]
    merge = solver["state_merge"]
    replay = result["physical_replay"]
    tolerance = protocol["score_tolerance"]

    inherited.validate_score(replay, tolerance)
    if (result["task"] != task
            or result["particle_sha256"] != hashes["particle_sha256"]
            or result["manifest_sha256"] != hashes["manifest_sha256"]
            or result["reference_sha256"] != object_digest(seed)
            or solver["algorithm"] != "physical_refinement_prefix_merge_v1"
            or solver["status"] != "budget_exceeded"
            or solver["error"] is not None
            or solver["stop_reason"] != "max_expansions"
            or solver["expanded"] != EXPANSIONS
            or solver["max_expansions"] != EXPANSIONS
            or solver["max_seconds"] != WALL_CEILING_S
            or not 0.0 <= solver["wall_s"] < WALL_CEILING_S
            or solver["formal_timed_task"] is not False
            or solver["global_optimality_certified"] is not False
            or solver["epsilon_certificate"] is not None
            or solver["root_prefix"] != seed["waypoints"][:1]
            or solver["initial_score"]["waypoints"] != seed["waypoints"]
            or solver["initial_score"]["J"] != seed["J"]
            or solver["initial_score"]["pd_final"] != seed["pd_final"]
            or solver["initial_score"]["observation_times_s"] != seed["observation_times_s"]
            or solver["connectivity"] != config["objective"]["connectivity"]
            or solver["footprint"] != config["objective"]["footprint"]
            or any(solver[key] != value for key, value in config["solver"].items()
                   if key != "archive")
            or solver["archive_enabled"] != config["solver"]["archive"]
            or merge["mode"] != task["mode"]
            or merge["max_entries"] != config["merging"]["max_entries"]
            or merge["max_payload_bytes"] != config["merging"]["max_payload_bytes"]):
        raise ValueError("Fixed-work run differs from the frozen task or did not reach the expansion cap")

    if (replay["waypoints"] != solver["waypoints"]
            or replay["observation_times_s"] != seed["observation_times_s"]
            or replay["physical_duration_s"] != ref_horizon(hashes)
            or replay["connectivity"] != config["objective"]["connectivity"]
            or replay["footprint"] != config["objective"]["footprint"]
            or abs(replay["J"] - solver["J"]) > tolerance
            or abs(replay["pd_final"] - solver["pd_final"]) > tolerance
            or len(replay["survival"]) != len(solver["survival"])
            or any(abs(a - b) > tolerance for a, b in zip(replay["survival"], solver["survival"]))):
        raise ValueError("Independent original replay disagrees with the fixed-work candidate")

    if (len(solver["diagnostics"]["pop_trace"]) < EXPANSIONS
            or not 0 <= merge["key_build_s"] <= merge["lookup_s"]
            or merge["equal_J_duplicates"] + merge["higher_J_duplicates"] != merge["mergeable_children"]
            or not 0 <= merge["discarded_children"] <= merge["mergeable_children"] <= merge["nonterminal_children"]
            or not 0 <= merge["entries"] <= merge["entries_peak"] <= merge["max_entries"]
            or not 0 <= merge["payload_bytes"] <= merge["payload_bytes_peak"] <= merge["max_payload_bytes"]
            or not 0 <= merge["stale_pops"] <= merge["stale_pop_candidates"] <= merge["pop_checks"]):
        raise ValueError("Search trace or exact index accounting is incomplete or invalid")
    if task["mode"] != "exact" and (merge["discarded_children"] or merge["stale_pops"]):
        raise ValueError("An off or shadow run removed search work")
    if task["mode"] == "off" and (merge["lookup_s"] or merge["entries"]):
        raise ValueError("The off arm unexpectedly built an index")


def ref_horizon(hashes):
    return hashes["physical_audit"]["horizon_s"]


def worker(out, identity, mode):
    from asar_repro.h2_inputs import load_h2_input
    from asar_repro.physical_merge_solver import solve_physical_prefix_merge

    diagnostic = out / "diagnostics"
    protocol = read(diagnostic / "protocol.json")
    verify_frozen(protocol)
    if (identity not in protocol["instances"] or mode not in protocol["modes"]
            or any(os.environ.get(key) != value
                   for key, value in protocol["configuration"]["thread_environment"].items())
            or os.environ.get("PYTHONHASHSEED") != "0"):
        raise ValueError("Worker task or reproducibility environment differs from the protocol")

    task = {"instance": identity, "mode": mode}
    run = diagnostic / "runs" / task_id(task)
    if read(run / "task.json") != task:
        raise ValueError("Worker task differs from the registered run")
    config = protocol["configuration"]
    references = protocol["reference_evidence"]
    case = references["instances"][identity]
    seed = references["references"][identity]
    archive = inherited.rooted(config["source_root"]) / "inputs" / identity
    connectivity = config["objective"]["connectivity"]
    load_started = time.perf_counter()
    problem, _, _, info = load_h2_input(ROOT, case, archive, config["objective"]["footprint"])
    load_s = time.perf_counter() - load_started
    inherited.assert_local_project_modules()
    if (problem.q != config["objective"]["q"]
            or problem.speed_m_s != config["objective"]["speed_m_s"]
            or info["opendrift_runs_in_search"] != 0):
        raise ValueError("Physical inputs differ from the frozen protocol")

    started, cpu_started = time.perf_counter(), time.process_time()
    solver = solve_physical_prefix_merge(
        problem,
        connectivity=connectivity,
        initial_waypoints=seed["waypoints"],
        root_prefix=(problem.start,),
        max_seconds=WALL_CEILING_S,
        max_expansions=EXPANSIONS,
        merge_mode=mode,
        merge_max_entries=config["merging"]["max_entries"],
        merge_max_payload_bytes=config["merging"]["max_payload_bytes"],
        **config["solver"],
    )
    wall_s, cpu_s = time.perf_counter() - started, time.process_time() - cpu_started
    started = time.perf_counter()
    score = None if solver["waypoints"] is None else problem.replay(solver["waypoints"], connectivity=connectivity)
    audit_s = time.perf_counter() - started
    result = {
        "task": task,
        "solver": solver,
        "physical_replay": score,
        "particle_sha256": info["particle_sha256"],
        "manifest_sha256": info["manifest_sha256"],
        "reference_sha256": object_digest(seed),
        "protocol_sha256": digest(diagnostic / "protocol.json"),
        "algorithm_wall_s": wall_s,
        "algorithm_cpu_s": cpu_s,
        "input_load_s": load_s,
        "independent_audit_s": audit_s,
    }
    # Retain the full raw search, including the reason, even if validation fails.
    save(run / "result.json", result)
    verify_result(task, result, protocol)


def run_task(out, task, protocol):
    import psutil

    run = out / "diagnostics" / "runs" / task_id(task)
    run.mkdir(parents=True, exist_ok=False)
    save(run / "task.json", task)
    cmd = [sys.executable, str(Path(__file__).resolve()), "--out", str(out),
           "--worker", task["instance"], task["mode"]]
    policy = protocol["configuration"]["watchdog"]
    env = inherited.child_environment()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PROJ_NETWORK"] = "OFF"
    started, peak_rss, watchdog = time.perf_counter(), 0, None
    with (run / "stdout.log").open("xb") as stdout, (run / "stderr.log").open("xb") as stderr:
        child = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=stdout, stderr=stderr)
        try:
            process = psutil.Process(child.pid)
            while child.poll() is None:
                try:
                    peak_rss = max(peak_rss, process.memory_info().rss)
                except psutil.NoSuchProcess:
                    break
                if peak_rss > policy["rss_limit_bytes"]:
                    watchdog = "rss_limit"
                    break
                if time.perf_counter() - started > WALL_CEILING_S + policy["grace_seconds"]:
                    watchdog = "process_watchdog"
                    break
                try:
                    child.wait(timeout=policy["poll_seconds"])
                except subprocess.TimeoutExpired:
                    pass
        except (KeyboardInterrupt, psutil.Error):
            watchdog = "interrupted_or_resource_monitor_failed"
        finally:
            if watchdog is not None and child.poll() is None:
                child.kill()
            returncode = child.wait()

    result_path = run / "result.json"
    valid = returncode == 0 and watchdog is None and result_path.is_file()
    result_sha = digest(result_path) if result_path.is_file() else None
    error = None
    if valid:
        try:
            result = read(result_path)
            if result["protocol_sha256"] != digest(out / "diagnostics" / "protocol.json"):
                raise ValueError("Result does not bind the fixed-work protocol")
            verify_result(task, result, protocol)
        except (OSError, KeyError, TypeError, ValueError) as exc:
            valid, error = False, str(exc)

    record = {
        "task": task,
        "status": "completed" if valid else "failed",
        "command": cmd,
        "result_sha256": result_sha,
        "process_wall_s": time.perf_counter() - started,
        "peak_rss_bytes": peak_rss,
        "returncode": returncode,
        "watchdog": watchdog,
        "verification_error": error,
    }
    save(run / "record.json", record)
    if not valid:
        raise RuntimeError(f"Fixed-work task failed and is retained at {run}")

    solver = result["solver"]
    merge = solver["state_merge"]
    summary = {
        **task,
        "path": run.relative_to(out).as_posix(),
        "result_sha256": result_sha,
        "record_sha256": digest(run / "record.json"),
        "J": solver["J"],
        "pd_final": solver["pd_final"],
        "expanded": solver["expanded"],
        "generated": solver["generated"],
        "guide_calls": solver["stats"]["guide_calls"],
        "terminal_candidates": solver["stats"]["terminal_candidates"],
        "peak_open": solver["peak_open"],
        "pop_count": len(solver["diagnostics"]["pop_trace"]),
        "pop_trace_sha256": object_digest(solver["diagnostics"]["pop_trace"]),
        "incumbent_sha256": object_digest(semantic_records(solver["history"])),
        "stop_reason": solver["stop_reason"],
        "state_merge": merge,
        "algorithm_wall_s": result["algorithm_wall_s"],
        "algorithm_cpu_s": result["algorithm_cpu_s"],
        "peak_rss_bytes": peak_rss,
    }
    print(f"{task_id(task)} {solver['expanded']} expansions, {solver['wall_s']:.3f} s", flush=True)
    return summary, result


def first_different_pop(first, second):
    for index, (left, right) in enumerate(zip(first, second), 1):
        if left != right:
            return index
    return min(len(first), len(second)) + 1 if len(first) != len(second) else None


def compare(instance, runs):
    off, shadow, exact = (runs[mode][1]["solver"] for mode in MODES)
    traces = [value["diagnostics"]["pop_trace"] for value in (off, shadow, exact)]
    same_pops = traces[0] == traces[1]
    same_history = semantic_records(off["history"]) == semantic_records(shadow["history"])
    same_archive = (
        semantic_records(off["pareto_archive"]) == semantic_records(shadow["pareto_archive"])
        and semantic_records(off["pareto_archive_history"]) == semantic_records(shadow["pareto_archive_history"])
    )
    same_work = (
        off["diagnostics"]["histograms"] == shadow["diagnostics"]["histograms"]
        and all(off[key] == shadow[key] for key in
                ("expanded", "generated", "peak_open", "open_count", "J", "pd_final", "waypoints", "survival"))
        and all(off["stats"][key] == shadow["stats"][key] for key in off["stats"]
                if not key.endswith("_s"))
    )
    return {
        "instance": instance,
        "off_shadow_pop_equal": same_pops,
        "off_shadow_incumbent_equal": same_history,
        "off_shadow_archive_equal": same_archive,
        "off_shadow_semantic_work_equal": same_work,
        "off_shadow_invariant_passed": all((same_pops, same_history, same_archive, same_work)),
        "exact_off_first_different_pop_1_based": first_different_pop(traces[0], traces[2]),
        "exact_minus_off_J": exact["J"] - off["J"],
        "exact_minus_off_pd": exact["pd_final"] - off["pd_final"],
        "shadow_minus_off_algorithm_wall_s": runs["shadow"][0]["algorithm_wall_s"] - runs["off"][0]["algorithm_wall_s"],
        "shadow_minus_off_peak_rss_bytes": runs["shadow"][0]["peak_rss_bytes"] - runs["off"][0]["peak_rss_bytes"],
    }


def diagnose(out):
    diagnostic = out / "diagnostics"
    gate_path = out / "equal-work.json"
    if gate_path.exists() or diagnostic.exists():
        raise FileExistsError("Retain prior equal-work artifacts and use a fresh batch directory")
    diagnostic.mkdir(parents=True, exist_ok=False)
    gate = {
        "status": "blocked",
        "admitted": False,
        "expected_expansions": EXPANSIONS,
        "wall_ceiling_s": WALL_CEILING_S,
        "start_utc": datetime.now(timezone.utc).isoformat(),
        "command": [sys.executable, str(Path(__file__).resolve()), "--out", str(out)],
        "run_count": 0,
        "runs": [],
        "comparisons": [],
        "inference_scope": "Equal-work index and ordering diagnostic only. Trace hashing adds charged work to all modes.",
    }
    try:
        sys.path.insert(0, str(ROOT / "src"))
        protocol = make_protocol()
        protocol_path = diagnostic / "protocol.json"
        save(protocol_path, protocol)
        gate["protocol_sha256"] = digest(protocol_path)
        gate["planned_runs"] = len(protocol["instances"]) * len(MODES)
        for identity in protocol["instances"]:
            observations = {}
            for mode in MODES:
                verify_frozen(protocol)
                task = {"instance": identity, "mode": mode}
                summary, result = run_task(out, task, protocol)
                observations[mode] = (summary, result)
                gate["runs"].append(summary)
                gate["run_count"] += 1
            comparison = compare(identity, observations)
            gate["comparisons"].append(comparison)
            if not comparison["off_shadow_invariant_passed"]:
                raise ValueError(f"Off and shadow differ semantically for {identity}")
        verify_frozen(protocol)
        if gate["run_count"] != gate["planned_runs"] or digest(protocol_path) != gate["protocol_sha256"]:
            raise ValueError("Equal-work evidence is incomplete or the recorded protocol changed")
        gate.update(status="passed", admitted=True)
        print(f"Equal-work gate passed ({gate['run_count']} runs)", flush=True)
    except BaseException as error:
        gate.update(error=str(error), traceback=traceback.format_exc())
        raise
    finally:
        gate["end_utc"] = datetime.now(timezone.utc).isoformat()
        save(gate_path, gate)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--worker", nargs=2, metavar=("INSTANCE", "MODE"), help=argparse.SUPPRESS)
    args = parser.parse_args()
    out = checked_output(args.out)
    if args.worker is None:
        diagnose(out)
    else:
        worker(out, *args.worker)


if __name__ == "__main__":
    main()
