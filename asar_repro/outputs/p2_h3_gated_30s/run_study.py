"""Freeze and run the three-arm H3 study in serial, sampled worker processes."""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import csv
import math
import os
from pathlib import Path
import random
import subprocess
import sys
from time import perf_counter, perf_counter_ns, process_time, sleep
from unittest.mock import patch
from xml.etree import ElementTree

import psutil
import run_eight_neighbor_h3 as h3
import run_eight_neighbor_rolling as legacy
from h3_protocol import digest, read, save
from prepare_eight_neighbor_h3 import load_h3_input
from asar_repro import physical_rolling as rolling
from gated_solver import settings as gated_settings, solve_gated, solve_original_lazy


HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "results" / "local_r1"
SOURCE = h3.DEFAULT_OUT
HISTORICAL_SUMMARY = SOURCE / "reports/20261128T152733015237Z/summary.json"
SEEDS = (3401, 4401, 4402, 4501, 4601)
ARMS = ("C0", "Lazy", "Gated")
REPS = 3
ORDER_SEED = 2026112902
TOTAL_SECONDS = 30.0
SOLVER_RESERVE_S = 2.0
LAZY_CUTOFF_S = 5.95
RSS_LIMIT = 2**31
SAMPLE_INTERVAL_S = 0.05
PROCESS_GRACE_S = 30.0
TOL = 1e-8
ACCEPTANCE = dict(
    J_4601_max=55.828347528, Pd_4601_min=.1968046, rss_4501_factor_max=1.10,
    J_3401_max=11.343163824, Pd_loss_3401_pp_max=.5, numerical_tolerance=TOL,
)


def source_locks():
    files = ("protocol.json", "s30_lock.json", "method_lock.json", "date_lock.json",
             "inputs_lock.json", "tasks.json")
    sha = {name: digest(SOURCE / name) for name in files}
    sha[HISTORICAL_SUMMARY.relative_to(SOURCE).as_posix()] = digest(HISTORICAL_SUMMARY)
    return sha


def implementation():
    return {name: digest(HERE / name) for name in ("run_study.py", "gated_solver.py")}


def verify_files(root, hashes):
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError("The evidence manifest is empty")
    root = root.resolve()
    for name, sha in hashes.items():
        relative = Path(name)
        path = (root / relative).resolve()
        if relative.is_absolute() or not path.is_relative_to(root) or digest(path) != sha:
            raise ValueError(f"Evidence fingerprint differs at {name}")


def preflight(out):
    root = out / "preflight"
    gates = {}
    for gate in ("validation", "fixed_work"):
        path = root / f"{gate}.json"
        evidence = read(path)
        sha = evidence.get("implementation_sha256", {})
        if evidence.get("status") != "passed" or "gated_solver.py" not in sha:
            raise ValueError(f"Missing passing, implementation-bound evidence for {gate}")
        verify_files(HERE, sha)
        verify_files(root, evidence.get("files", {}))
        if gate == "validation":
            cases = [
                case for name in evidence["files"] if name.endswith(".xml")
                for case in ElementTree.parse(root / name).findall(".//testcase")
            ]
            if not cases or any(case.find(tag) is not None for case in cases
                                for tag in ("failure", "error", "skipped")):
                raise ValueError("Toy/Oracle pytest evidence did not pass")
        gates[gate] = dict(sha256=digest(path), evidence=evidence)
    return gates


def make_tasks():
    rng = random.Random(ORDER_SEED)
    pairs = [(seed, rep) for seed in SEEDS for rep in range(REPS)]
    rng.shuffle(pairs)
    tasks = []
    for seed, rep in pairs:
        arms = list(ARMS)
        rng.shuffle(arms)
        tasks.extend(dict(seed=seed, rep=rep, arm=arm) for arm in arms)
    return tasks


def ident(task):
    return f"s{task['seed']}_r{task['rep']}_{task['arm']}"


def registered_references(original, s30):
    historical = read(HISTORICAL_SUMMARY)["seed_comparisons"]
    reference = {}
    for seed in SEEDS:
        case, = (case for case in original["cases"].values() if case["case"]["seed"] == seed)
        metrics, = (row for row in historical if row["seed"] == seed)
        reference[str(seed)] = dict(case=case, S30=s30[case["case"]["id"]], E30=metrics)
    return reference


def freeze(out):
    gates = preflight(out)
    source_sha = source_locks()
    original, old_tasks = h3.verify_protocol(SOURCE, full=True)
    s30 = h3.freeze_s30(SOURCE, original, old_tasks["S30"])["references"]
    reference = registered_references(original, s30)
    if source_sha != source_locks():
        raise ValueError("H3 inputs changed while checking the frozen study")
    doc = dict(
        status="frozen_before_gated_trials",
        source=str(SOURCE),
        source_sha256=source_sha,
        source_inventory_sha256=original["source_sha256"],
        implementation_sha256=implementation(),
        preflight=gates,
        environment=original["environment"],
        threads=original["config"]["threads"],
        reference=reference,
        solver=original["config"]["solver"],
        search=dict(original["config"]["search"], solver_reserve_s=SOLVER_RESERVE_S),
        gated_settings=gated_settings(),
        total_seconds=TOTAL_SECONDS,
        solver_reserve_s=SOLVER_RESERVE_S,
        lazy_cutoff_s=LAZY_CUTOFF_S,
        watchdog_rss_bytes=RSS_LIMIT,
        sample_interval_s=SAMPLE_INTERVAL_S,
        process_grace_s=PROCESS_GRACE_S,
        order_seed=ORDER_SEED,
        tasks=make_tasks(),
        acceptance=ACCEPTANCE,
        acceptance_scope="post-search assessment only; original J remains the sole solver objective",
        timing_scope="original rolling C0 slot; input file loading and independent audits outside timing",
        warm_start="frozen S30 only",
        execution="serial processes; no retries of recorded outcomes",
    )
    path = out / "protocol.json"
    if path.exists():
        if read(path) != doc:
            raise ValueError("Existing frozen plan does not match the verified inputs")
    else:
        if (out / "runs").exists():
            raise ValueError("Cannot freeze after trial output exists")
        save(path, doc)
    print(f"Frozen {len(doc['tasks'])} serial paired trials at {out}", flush=True)


def lock(out):
    p = read(out / "protocol.json")
    original = read(SOURCE / "protocol.json")
    original_s30 = read(SOURCE / "s30_lock.json")["references"]
    if (p["status"] != "frozen_before_gated_trials" or p["tasks"] != make_tasks()
            or p["source"] != str(SOURCE) or p["source_sha256"] != source_locks()
            or p["source_inventory_sha256"] != h3._sources()
            or p["implementation_sha256"] != implementation() or p["preflight"] != preflight(out)
            or p["environment"] != legacy.environment()
            or p["reference"] != registered_references(original, original_s30)
            or p["solver"] != original["config"]["solver"]
            or p["threads"] != original["config"]["threads"]
            or p["search"] != dict(original["config"]["search"], solver_reserve_s=SOLVER_RESERVE_S)
            or p["gated_settings"] != gated_settings()
            or p["total_seconds"] != TOTAL_SECONDS or p["solver_reserve_s"] != SOLVER_RESERVE_S
            or p["lazy_cutoff_s"] != LAZY_CUTOFF_S or p["acceptance"] != ACCEPTANCE):
        raise ValueError("The frozen study, implementation or execution environment changed")
    return p


def worker(out, identity):
    p = lock(out)
    task, = (task for task in p["tasks"] if ident(task) == identity)
    folder = out / "runs" / identity
    if (read(folder / "task.json") != task or os.environ.get("ASAR_OFFLINE") != "1"
            or os.environ.get("PYTHONHASHSEED") != "0"
            or any(os.environ.get(key) != value for key, value in p["threads"].items())):
        raise ValueError("Trial registration or offline worker configuration changed")
    ref = p["reference"][str(task["seed"])]
    s30, archive = ref["S30"], ref["case"]
    started = perf_counter()
    problem, _, _, inputs = load_h3_input(SOURCE, archive["case"], archive["h3_evidence"], "heading_square")
    input_load_s = perf_counter() - started
    if (problem.q != .78 or problem.speed_m_s != 20
            or inputs["particle_sha256"] != s30["particle_sha256"]
            or inputs["forcing_kind"] != "historical_real" or inputs["opendrift_runs_in_search"] != 0):
        raise ValueError("Trial used a changed physical model or archive")
    legacy.assert_local_project_modules()

    alternate = {"Lazy": solve_original_lazy, "Gated": solve_gated}.get(task["arm"])
    with nullcontext() if alternate is None else patch.object(rolling, "solve_physical_refinement", alternate):
        start_ns = perf_counter_ns()
        started, cpu_started = perf_counter(), process_time()
        outer = rolling.run_physical_rolling(
            problem, method="C0", initial_waypoints=s30["waypoints"], total_seconds=TOTAL_SECONDS,
            solver_options=p["solver"], **p["search"],
        )
        wall, cpu = perf_counter() - started, process_time() - cpu_started
        end_ns = perf_counter_ns()
    phase, = outer["phases"]
    inner = phase["inner"]
    if (outer["status"] != "completed" or outer["error"] is not None
            or inner is None or inner["error"] is not None):
        save(folder / "failed_solver.json", legacy.failure_safe(dict(outer=outer)))
        raise ValueError("Solver did not produce an auditable result")
    result = dict(
        task=task, outer=outer, inner=inner, inputs=inputs, input_load_s=input_load_s,
        algorithm_wall_s=wall, algorithm_cpu_s=cpu, start_ns=start_ns, end_ns=end_ns,
        formal_optimality_certificate=False,
    )
    try:
        if (not (math.isfinite(wall) and wall > 0) or not (math.isfinite(cpu) and cpu >= 0)
                or inner["objective"] != "J" or inner.get("max_expansions") is not None
                or inner["initial_score"]["waypoints"] != s30["waypoints"]
                or outer["initial_score"]["waypoints"] != s30["waypoints"]
                or abs(outer["initial_score"]["J"] - s30["J"]) > TOL
                or abs(outer["initial_score"]["pd_final"] - s30["Pd"]) > TOL
                or outer["solver_options"] != p["solver"]
                or outer["solver_reserve_s"] != SOLVER_RESERVE_S
                or outer["total_seconds"] != TOTAL_SECONDS):
            raise ValueError("Trial used a changed objective, initial route or budget")
        if task["arm"] == "C0" and inner["algorithm"] != "physical_refinement_diagnostic_v1":
            raise ValueError("C0 did not use the frozen control")
        if task["arm"] == "Lazy":
            seen = inner["diagnostics"]["progress_schedule"]["qualification_cutoff_s"]
            if abs(seen - LAZY_CUTOFF_S) > TOL:
                raise ValueError("Original Lazy qualification cutoff changed")
        if task["arm"] == "Gated" and inner["diagnostics"]["gated"]["configuration"] != p["gated_settings"]:
            raise ValueError("Gated trial ran a changed continuation policy")
        started = perf_counter()
        legacy.validate_phase_ledger(outer, TOTAL_SECONDS, TOL)
        audit = legacy.audit_execution(problem, outer, s30, TOL)
        replay, independent = h3.dual_replay(problem, outer["waypoints"], 8)
        if (replay["observation_times_s"] != s30["observation_times_s"]
                or abs(replay["J"] - outer["J"]) > TOL
                or abs(replay["pd_final"] - outer["pd_final"]) > TOL):
            raise ValueError("Delivered route disagrees with the frozen scorer or clock")
        delivered = phase["acceptance_compute_s"]
        elapsed = max(wall, outer["wall_s"])
        within_budget = elapsed <= TOTAL_SECONDS
        result.update(
            status="valid" if within_budget else "overbudget", replay=replay, independent_replay=independent,
            execution_audit=audit, audit_wall_s=perf_counter() - started,
            delivery=dict(
                within_budget=within_budget, accepted=phase["accepted"], disposition=phase["reason"],
                fallback_s30=replay["waypoints"] == s30["waypoints"], acceptance_s=delivered,
                deadline_overshoot_s=max(0.0, elapsed - TOTAL_SECONDS),
            ),
        )
        save(folder / "result.json", legacy.failure_safe(result))
    except Exception as exc:
        save(folder / "rejected_result.json", legacy.failure_safe(dict(error=str(exc), **result)))
        raise


def verify_record(folder, task):
    record = read(folder / "record.json")
    if record["task"] != task or read(folder / "task.json") != task:
        raise ValueError(f"Changed trial identity at {folder}")
    verify_files(folder, record["files"])
    if record["status"] in {"valid", "overbudget"}:
        path = folder / "result.json"
        result = read(path)
        if (record["result_sha256"] != digest(path) or result["task"] != task
                or result["status"] != record["status"]):
            raise ValueError(f"Changed solver result at {folder}")
    return record


def launch(out, task):
    identity = ident(task)
    folder = out / "runs" / identity
    if folder.exists():
        return verify_record(folder, task)
    folder.mkdir(parents=True)
    save(folder / "task.json", task)
    cmd = [sys.executable, str(Path(__file__).resolve()), "--out", str(out), "_worker", identity]
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    samples = []
    watchdog = None
    started = perf_counter()
    with (folder / "stdout.log").open("xb") as stdout, (folder / "stderr.log").open("xb") as stderr:
        with subprocess.Popen(cmd, cwd=legacy.ROOT, env=h3.worker_env(), stdout=stdout,
                              stderr=stderr, creationflags=flags) as child:
            try:
                process = psutil.Process(child.pid)
                while child.poll() is None:
                    samples.append((perf_counter_ns(), process.memory_info().rss))
                    if samples[-1][1] > RSS_LIMIT:
                        watchdog = "rss"
                        break
                    if perf_counter() - started > TOTAL_SECONDS + PROCESS_GRACE_S:
                        watchdog = "process_wall"
                        break
                    sleep(SAMPLE_INTERVAL_S)
            except psutil.NoSuchProcess:
                child.wait()
            finally:
                if child.poll() is None:
                    child.kill()
                rc = child.wait()
    with (folder / "rss.csv").open("x", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("monotonic_ns", "rss_bytes"))
        writer.writerows(samples)
    target = folder / "result.json"
    status = "watchdog" if watchdog else "failed"
    if not watchdog and rc == 0 and target.is_file():
        status = read(target)["status"]
    record = dict(
        task=task, status=status, watchdog=watchdog, returncode=rc, command=cmd,
        process_wall_s=perf_counter() - started,
        process_peak_rss_bytes=max((rss for _, rss in samples), default=0),
        result_sha256=digest(target) if target.is_file() else None,
        files={file.name: digest(file) for file in folder.iterdir() if file.is_file()},
    )
    save(folder / "record.json", record)
    return verify_record(folder, task)


def run(out):
    p = lock(out)
    with legacy.exclusive_run(out):
        for index, task in enumerate(p["tasks"], 1):
            record = launch(out, task)
            print(f"{index}/{len(p['tasks'])} {ident(task)} {record['status']}", flush=True)


def status(out):
    p = lock(out)
    counts = {}
    for task in p["tasks"]:
        folder = out / "runs" / ident(task)
        key = verify_record(folder, task)["status"] if (folder / "record.json").exists() else "pending"
        counts[key] = counts.get(key, 0) + 1
    print(counts, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("command", choices=("freeze", "run", "status", "_worker"))
    parser.add_argument("identity", nargs="?")
    args = parser.parse_args()
    out = args.out.resolve()
    if args.command == "_worker":
        worker(out, args.identity)
    elif args.identity is not None:
        parser.error("identity is only used in a worker process")
    else:
        {"freeze": freeze, "run": run, "status": status}[args.command](out)


if __name__ == "__main__":
    main()
