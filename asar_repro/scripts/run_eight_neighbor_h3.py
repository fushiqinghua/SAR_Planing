#!/usr/bin/env python3
"""Run the frozen P2/H3 S30 and E30 stages against qualified historical archives."""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import math
import os
from pathlib import Path
import random
import subprocess
import sys
import time
import traceback
from unittest.mock import patch
import xml.etree.ElementTree as ET

import run_eight_neighbor_h2 as h2
import run_eight_neighbor_lazy_prefix as lazy
import run_eight_neighbor_rolling as legacy
import run_lazy_robustness_p1 as p1
from h3_protocol import (
    DEFAULT_OUT, H2_CONFIG, P1_COMMIT, ROOT, batch_directory, digest,
    method_lock, read, save, stamp, verify_commit_file, verify_method,
)
from prepare_eight_neighbor_h3 import checked_file, load_h3_input, verify_inputs


ORDER_SEED = 2026112823
SCORE_TOL = 1e-8
P1_PROTOCOL = "outputs/second_innovation_p1_20261128/local_r1/protocol.json"
TARGETED = (
    "tests/test_h3_forcing.py", "tests/test_eight_neighbor_h3_runner.py",
    "tests/test_h2_acquire.py", "tests/test_h2_hycom.py", "tests/test_eight_neighbor_h2_inputs.py",
    "tests/test_historical_drift.py", "tests/test_physical_search.py", "tests/test_physical_lazy_prefix.py",
    "tests/test_physical_refinement.py", "tests/test_physical_rolling.py",
)


def configuration(out):
    registered = verify_method(out)["method"]
    paths = set(p1.PROTECTED) | {
        P1_PROTOCOL, "scripts/run_eight_neighbor_rolling.py", "scripts/run_eight_neighbor_followup.py",
        "src/asar_repro/objective.py", "src/asar_repro/search.py",
        "src/asar_repro/physical_followup_data.py", "src/asar_repro/historical_drift.py",
    }
    protected = {path: verify_commit_file(path, P1_COMMIT) for path in sorted(paths)}
    prior = read(ROOT / P1_PROTOCOL)["config"]
    h2_config = read(ROOT / H2_CONFIG)
    solver = dict(prior["solver"])
    if (solver != {"completion": "greedy", **{key: registered[key] for key in solver if key != "completion"}}
            or prior["search"]["seconds"] != registered["seconds"]
            or prior["search"]["repetitions"] != registered["repetitions"]):
        raise ValueError("The frozen P1 solver and H3 registered options differ")
    return dict(registered=registered, solver=solver, protected_sha256=protected,
                search={name: prior["search"][name] for name in
                        ("triggers", "anchor_guard_s", "solver_reserve_s")},
                initialization=h2_config["initialization"], threads=h2_config["thread_environment"],
                watchdog=prior["watchdog"], progress_policy=lazy.DESIGN["progress_policy"],
                task_order_seed=ORDER_SEED)


def worker_env():
    return dict(legacy.child_environment(), ASAR_OFFLINE="1", PYTHONUTF8="1",
                PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1", PROJ_NETWORK="OFF")


def make_tasks(cases, registered):
    rng = random.Random(ORDER_SEED)
    s30, blocks = [], []
    for identity, record in sorted(cases.items(), key=lambda item: item[1]["case"]["seed"]):
        case = record["case"]
        base = dict(instance=identity, seed=case["seed"], site=case["base_scene"], date=case["lkp_utc"][:10],
                    block_id=case["block_id"], manifest_sha256=record["manifest_sha256"],
                    particle_sha256=record["input_sha256"], seconds=registered["seconds"])
        s30.append(dict(base, stage="S30", method="PT_then_original_paper_greedy", repetition=0,
                        footprint="axis_square", connectivity=4))
        for repetition in range(registered["repetitions"]):
            pair = [dict(base, stage="E30", method=arm, repetition=repetition,
                         footprint=registered["footprint"], connectivity=registered["connectivity"])
                    for arm in ("C0", "Lazy")]
            rng.shuffle(pair)
            blocks.append(pair)
    rng.shuffle(blocks)
    return {"S30": s30, "E30": [task for pair in blocks for task in pair]}


def task_id(task):
    return task["stage"] + "_" + legacy.object_digest(task)[:20]


def _sources():
    return legacy.source_inventory(ROOT / H2_CONFIG)


def validate(out):
    verify_method(out)
    folder = out / "validation" / stamp()
    folder.mkdir(parents=True, exist_ok=False)
    sources, environment = _sources(), legacy.environment()
    evidence = []
    for name, paths in (("targeted", TARGETED), ("full", ("tests",))):
        xml = folder / f"{name}.xml"
        args = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={xml}"]
        scratch = os.environ.get("ASAR_H3_PYTEST_PARENT")
        if scratch:
            parent = Path(scratch).resolve(strict=True)
            args.append(f"--basetemp={parent / (folder.name + '_' + name)}")
        args.extend(paths)
        save(folder / f"{name}_command.json", dict(argv=args, cwd=str(ROOT), pythonhashseed=0))
        with (folder / f"{name}.stdout.log").open("xb") as stdout, (folder / f"{name}.stderr.log").open("xb") as stderr:
            proc = subprocess.run(args, cwd=ROOT, stdout=stdout, stderr=stderr, env=worker_env(), check=False)
        tree = ET.parse(xml) if xml.is_file() else None
        cases = tree.findall(".//testcase") if tree is not None else []
        bad = sum(any(case.find(tag) is not None for tag in ("failure", "error", "skipped")) for case in cases)
        status = "passed" if proc.returncode == 0 and cases and bad == 0 else "blocked"
        evidence.append(dict(scope=name, status=status, testcase_count=len(cases),
                             bad_or_skipped_count=bad, returncode=proc.returncode,
                             files={path.name: digest(path) for path in sorted(folder.glob(f"{name}*"))
                                    if path.is_file()}))
        print(f"{name}: {status}, {len(cases)} cases, {bad} failures/errors/skips", flush=True)
        if status != "passed":
            break
    unchanged = sources == _sources() and environment == legacy.environment()
    passed = unchanged and len(evidence) == 2 and all(row["status"] == "passed" for row in evidence)
    path = folder / "validation.json"
    save(path, dict(status="passed" if passed else "blocked", evidence=evidence,
                    source_sha256=sources, environment=environment, unchanged=unchanged,
                    method_lock_sha256=digest(method_lock(out))))
    if not passed:
        raise RuntimeError(f"Validation stopped; preserved at {path}")
    return path


def validation(out, path, sources, environment):
    value = read(path)
    if (value["status"] != "passed" or not value["unchanged"]
            or value["method_lock_sha256"] != digest(method_lock(out))
            or value["source_sha256"] != sources or value["environment"] != environment
            or [row["scope"] for row in value["evidence"]] != ["targeted", "full"]):
        raise ValueError("No passing targeted and full test evidence for the frozen H3 sources")
    for row in value["evidence"]:
        if (row["status"] != "passed" or row["returncode"] != 0
                or row["testcase_count"] <= 0 or row["bad_or_skipped_count"] != 0):
            raise ValueError("H3 validation is incomplete")
        for name, sha in row["files"].items():
            checked_file(path.parent, name, sha)
    return value


def freeze(out):
    if (out / "protocol.json").exists():
        return verify_protocol(out, full=True)
    if (out / "runs").exists():
        raise ValueError("H3 configuration must be frozen before any scored route")
    config = configuration(out)
    inputs = verify_inputs(out, full=True)
    sources, environment = _sources(), legacy.environment()
    candidates = sorted((out / "validation").glob("*/validation.json"))
    if not candidates:
        raise ValueError("Run the H3 targeted and full test suites before freezing")
    qualified = candidates[-1]
    validation(out, qualified, sources, environment)
    tasks = make_tasks(inputs["cases"], config["registered"])
    if ([len(tasks[stage]) for stage in ("S30", "E30")] != [12, 72]
            or len({task_id(t) for stage in tasks.values() for t in stage}) != 84):
        raise ValueError("P2/H3 task matrix differs from the registered 12 S30 and 72 E30 jobs")
    save(out / "tasks.json", tasks)
    protocol = dict(status="frozen_before_any_planning", config=config, environment=environment,
                    source_sha256=sources, cases=inputs["cases"], tasks_sha256=digest(out / "tasks.json"),
                    inputs_sha256=digest(out / "inputs_lock.json"), date_lock_sha256=digest(out / "date_lock.json"),
                    method_lock_sha256=digest(method_lock(out)),
                    validation_file=qualified.relative_to(out).as_posix(),
                    validation_sha256=digest(qualified), algorithm_budget_seconds=2520,
                    formal_optimality_certificate=False)
    save(out / "protocol.json", protocol)
    print(f"Frozen 12 S30 and 72 E30 tasks, order seed {ORDER_SEED}, 2520 s total", flush=True)
    return protocol, tasks


def verify_protocol(out, *, full=False):
    protocol = read(out / "protocol.json")
    path = checked_file(out, protocol["validation_file"], protocol["validation_sha256"])
    tasks = read(checked_file(out, "tasks.json", protocol["tasks_sha256"]))
    if (protocol["status"] != "frozen_before_any_planning"
            or protocol["inputs_sha256"] != digest(out / "inputs_lock.json")
            or protocol["date_lock_sha256"] != digest(out / "date_lock.json")
            or protocol["method_lock_sha256"] != digest(method_lock(out))
            or protocol["algorithm_budget_seconds"] != 2520
            or tasks != make_tasks(protocol["cases"], protocol["config"]["registered"])):
        raise ValueError("Frozen H3 protocol, source chain or tasks changed")
    if full:
        if (protocol["config"] != configuration(out) or protocol["environment"] != legacy.environment()
                or protocol["source_sha256"] != _sources()
                or protocol["cases"] != verify_inputs(out, full=True)["cases"]):
            raise ValueError("Frozen H3 methods, archives or runtime changed")
        validation(out, path, protocol["source_sha256"], protocol["environment"])
    return protocol, tasks


def dual_replay(problem, path, graph):
    from asar_repro.physical_search import independent_replay

    original = problem.replay(path, connectivity=graph)
    scalar = independent_replay(problem, path, connectivity=graph)
    legacy.validate_score(original, SCORE_TOL)
    legacy.validate_score(scalar, SCORE_TOL)
    for key in ("waypoints", "connectivity", "footprint", "observation_times_s", "last_edge_partial"):
        if original[key] != scalar[key]:
            raise ValueError(f"Independent route record differs at {key}")
    for key in ("J", "pd_final", "physical_duration_s", "distance_m"):
        if abs(original[key] - scalar[key]) > SCORE_TOL:
            raise ValueError(f"Independent score differs at {key}")
    for key in ("survival", "final_weights"):
        if any(abs(a - b) > SCORE_TOL for a, b in zip(original[key], scalar[key], strict=True)):
            raise ValueError(f"Independent replay differs at {key}")
    return original, scalar


def reference_for(out, task):
    lock = read(out / "s30_lock.json")
    if lock["protocol_sha256"] != digest(out / "protocol.json") or lock["status"] != "shared_S30_locked":
        raise ValueError("Frozen H3 S30 route lock is missing or changed")
    reference = lock["references"][task["instance"]]
    if reference["particle_sha256"] != task["particle_sha256"]:
        raise ValueError("E30 input differs from its shared S30 particle archive")
    return reference


def check_result(out, task, result, protocol):
    wall = result["algorithm_wall_s"]
    cpu = result["algorithm_cpu_s"]
    input_info = result["inputs"]
    archive = protocol["cases"][task["instance"]]
    if (result["status"] != "valid" or result["method"] != task["method"]
            or not 0 < wall <= task["seconds"] or not math.isfinite(cpu) or cpu < 0
            or result["formal_optimality_certificate"] is not False
            or input_info["manifest_sha256"] != task["manifest_sha256"]
            or input_info["particle_sha256"] != task["particle_sha256"]
            or input_info["h3_evidence"] != archive["h3_evidence"] or input_info["case"] != archive["case"]
            or input_info["forcing_kind"] != "historical_real" or input_info["opendrift_runs_in_search"] != 0):
        raise ValueError("H3 result identity, no-drift rule or algorithm budget failed")
    score = result["physical_replay"]
    scalar = result["independent_replay"]
    legacy.validate_score(score, SCORE_TOL)
    legacy.validate_score(scalar, SCORE_TOL)
    if (score["footprint"] != "heading_square" or score["connectivity"] != task["connectivity"]
            or any(score[k] != scalar[k] for k in ("waypoints", "footprint", "connectivity", "observation_times_s"))
            or not math.isclose(result["J"], score["J"], rel_tol=0, abs_tol=SCORE_TOL)
            or not math.isclose(result["pd_final"], score["pd_final"], rel_tol=0, abs_tol=SCORE_TOL)
            or any(abs(score[k] - scalar[k]) > SCORE_TOL for k in ("J", "pd_final"))
            or any(abs(a-b) > SCORE_TOL for a, b in zip(score["survival"], scalar["survival"], strict=True))):
        raise ValueError("H3 legality, score or full survival replay failed")
    if task["stage"] == "S30":
        seed = result["initialization"]
        axis = result["axis_independent_replay"]
        legacy.validate_score(axis, SCORE_TOL)
        if (seed["waypoints"] != score["waypoints"] or seed["status"] != "valid"
                or axis["waypoints"] != score["waypoints"] or axis["footprint"] != "axis_square"
                or axis["connectivity"] != 4 or axis["observation_times_s"] != score["observation_times_s"]
                or abs(axis["J"] - seed["J"]) > SCORE_TOL or abs(axis["pd_final"] - seed["pd_final"]) > SCORE_TOL
                or any(not 0 <= row["elapsed_s"] <= task["seconds"] for row in seed["history"])):
            raise ValueError("S30 result did not preserve the selected timely bridge route")
        return
    reference = reference_for(out, task)
    raw = result["raw"]
    legacy.validate_phase_ledger(raw, task["seconds"], SCORE_TOL)
    inner = raw["phases"][0]["inner"]
    config = protocol["config"]
    registered = config["registered"]
    expected = registered["candidate"] if task["method"] == "Lazy" else registered["control"]
    diagnostics = inner["diagnostics"]
    if (raw["status"] != "completed" or raw.get("error") is not None
            or raw["method"] != "C0" or raw["total_seconds"] != task["seconds"]
            or raw["solver_options"] != config["solver"] or raw["global_optimality_certified"] is not False
            or raw["epsilon_certificate"] is not None or raw["connectivity"] != 8
            or raw["footprint"] != "heading_square" or raw["source_base"] != legacy.BASE_COMMIT
            or any(raw[key] != value for key, value in config["search"].items())
            or inner["algorithm"] != expected or inner["error"] is not None
            or inner["stop_reason"] not in ("max_seconds", "frontier_exhausted", "max_open", "max_archive", "max_archive_history")
            or inner["max_expansions"] is not None or inner.get("state_merge") is not None
            or raw["initial_score"]["waypoints"] != reference["waypoints"]
            or result["reference_sha256"] != legacy.object_digest(reference)
            or abs(raw["initial_score"]["J"] - reference["J"]) > SCORE_TOL
            or abs(raw["initial_score"]["pd_final"] - reference["Pd"]) > SCORE_TOL
            or score["observation_times_s"] != reference["observation_times_s"]
            or score["waypoints"] != raw["waypoints"]
            or abs(score["J"] - raw["J"]) > SCORE_TOL or abs(score["pd_final"] - raw["pd_final"]) > SCORE_TOL
            or result["execution_audit"]["status"] != "passed"):
        raise ValueError("E30 result used a changed method, clock, incumbent or initial path")
    if task["method"] == "Lazy":
        frontier = diagnostics["lazy_frontier"]
        if (frontier["starting_heaps"] != 1 or frontier["migrations"] not in (0, 1)
                or frontier["migration_attempts"] not in (0, 1)
                or frontier["migrations"] > frontier["migration_attempts"]
                or frontier["ending_heaps"] != 1 + 2 * frontier["migrations"]
                or frontier["diagnostic_heaps"] is not None or frontier["diagnostic_statistics"] is not None
                or diagnostics["prefix_order"]["policy"] != config["progress_policy"]
                or diagnostics["progress_schedule"]["policy"] != config["progress_policy"]["activation"]):
            raise ValueError("E30 ran a changed Lazy schedule")
    elif diagnostics.get("lazy_frontier") is not None:
        raise ValueError("E30 control was exposed to Lazy")


def run_worker(out, identity):
    from asar_repro import physical_rolling as rolling
    from asar_repro.physical_lazy_prefix import solve_physical_lazy_prefix

    protocol, tasks = verify_protocol(out)
    task = next((row for stage in tasks.values() for row in stage if task_id(row) == identity), None)
    folder = out / "runs" / identity
    if task is None or read(folder / "task.json") != task:
        raise ValueError("Unregistered H3 worker task")
    config = protocol["config"]
    if (os.environ.get("PYTHONHASHSEED") != "0" or os.environ.get("ASAR_OFFLINE") != "1"
            or any(os.environ.get(key) != value for key, value in config["threads"].items())
            or legacy.environment() != protocol["environment"]):
        raise ValueError("H3 solver worker must have the frozen single-thread offline environment")
    record = protocol["cases"][task["instance"]]
    case, expected = record["case"], record["h3_evidence"]
    t0 = time.perf_counter()
    heading, _, _, info = load_h3_input(out, case, expected, "heading_square")
    if task["stage"] == "S30":
        axis, grid, discrete, axis_info = load_h3_input(out, case, expected, "axis_square")
        if axis_info["particle_sha256"] != info["particle_sha256"]:
            raise ValueError("S30 bridge used different particles")
    load_s = time.perf_counter() - t0
    if (heading.q != .78 or heading.speed_m_s != 20
            or info["manifest_sha256"] != task["manifest_sha256"]
            or info["particle_sha256"] != task["particle_sha256"]):
        raise ValueError("S30/E30 model or input differs from the frozen protocol")
    legacy.assert_local_project_modules()
    result = dict(status="valid", method=task["method"], inputs=info,
                  input_load_s=load_s, formal_optimality_certificate=False)
    try:
        if task["stage"] == "S30":
            options = h2.initialization_options(read(ROOT / H2_CONFIG))
            initial = h2.followup.initialize_case(options, task, axis, grid, discrete, heading)
            result.update(initialization=initial, algorithm_wall_s=initial["algorithm_wall_s"],
                          algorithm_cpu_s=initial["algorithm_cpu_s"])
            audit_started = time.perf_counter()
            original, scalar = dual_replay(heading, initial["waypoints"], 4)
            axis_original, axis_scalar = dual_replay(axis, initial["waypoints"], 4)
            if abs(axis_original["J"] - initial["J"]) > SCORE_TOL or abs(axis_original["pd_final"] - initial["pd_final"]) > SCORE_TOL:
                raise ValueError("S30 axis bridge differs from independent physical replay")
            result["axis_independent_replay"] = axis_scalar
        else:
            reference = reference_for(out, task)
            solver = patch.object(rolling, "solve_physical_refinement", solve_physical_lazy_prefix)
            with solver if task["method"] == "Lazy" else nullcontext():
                started, cpu = time.perf_counter(), time.process_time()
                raw = rolling.run_physical_rolling(
                    heading, method="C0", initial_waypoints=reference["waypoints"],
                    total_seconds=task["seconds"], solver_options=config["solver"], **config["search"],
                )
                wall, cpu_s = time.perf_counter() - started, time.process_time() - cpu
            result.update(raw=raw, algorithm_wall_s=wall, algorithm_cpu_s=cpu_s,
                          reference_sha256=legacy.object_digest(reference))
            audit_started = time.perf_counter()
            if raw["status"] != "completed" or raw.get("error") is not None:
                raise ValueError(f"E30 solver failed: {raw.get('error')}")
            original, scalar = dual_replay(heading, raw["waypoints"], 8)
            result["execution_audit"] = legacy.audit_execution(heading, raw, reference, SCORE_TOL)
        result.update(J=original["J"], pd_final=original["pd_final"],
                      physical_replay=original, independent_replay=scalar,
                      audit_wall_s=time.perf_counter() - audit_started)
        check_result(out, task, result, protocol)
        save(folder / "result.json", legacy.failure_safe(dict(task=task, result=result)))
    except BaseException as exc:
        save(folder / "rejected_result.json", legacy.failure_safe(dict(
            task=task, result=result, status="validation_rejected", error=str(exc),
            error_type=type(exc).__name__, traceback=traceback.format_exc(),
        )))
        raise


def frozen_evidence(out, stage):
    names = ["protocol.json", "inputs_lock.json", "date_lock.json"]
    if stage == "E30":
        names.append("s30_lock.json")
    return {name: digest(out / name) for name in names}


def saved_task(out, task, protocol):
    folder = out / "runs" / task_id(task)
    record = read(folder / "record.json")
    if (record["status"] != "completed" or record["returncode"] != 0
            or record["task"] != task or record["watchdog"] is not None or record["peak_rss_bytes"] <= 0
            or record["frozen_evidence"] != frozen_evidence(out, task["stage"])
            or set(record["files"]) != {"task.json", "stdout.log", "stderr.log", "result.json"}
            or read(folder / "task.json") != task):
        raise ValueError(f"Task is not a verified H3 result: {folder}")
    for name, sha in record["files"].items():
        checked_file(folder, name, sha)
    path = checked_file(folder, "result.json", record["files"]["result.json"])
    payload = read(path)
    if payload["task"] != task:
        raise ValueError("Worker result identity changed")
    check_result(out, task, payload["result"], protocol)
    return dict(task=task, record=record, result=payload["result"], run_id=folder.name)


def launch_task(out, task, protocol):
    import psutil

    identity = task_id(task)
    folder = out / "runs" / identity
    if folder.exists():
        saved_task(out, task, protocol)
        return
    watch = protocol["config"]["watchdog"]
    folder.mkdir(parents=True, exist_ok=False)
    save(folder / "task.json", task)
    args = [sys.executable, str(Path(__file__).resolve()), "_worker", "--out", str(out), "--run-id", identity]
    logs = ("stdout.log", "stderr.log")
    evidence = frozen_evidence(out, task["stage"])
    started = time.perf_counter()
    peak, reason, rc, error = 0, None, None, None
    try:
        with (folder / logs[0]).open("xb") as stdout, (folder / logs[1]).open("xb") as stderr:
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            with subprocess.Popen(args, cwd=ROOT, env=worker_env(), stdout=stdout, stderr=stderr,
                                  creationflags=flags) as child:
                try:
                    proc = psutil.Process(child.pid)
                    while child.poll() is None:
                        try:
                            peak = max(peak, proc.memory_info().rss)
                        except psutil.NoSuchProcess:
                            break
                        if peak > watch["rss_limit_bytes"]:
                            reason = "rss_limit"
                            break
                        if time.perf_counter() - started > task["seconds"] + watch["grace_seconds"]:
                            reason = "process_watchdog"
                            break
                        time.sleep(watch["poll_seconds"])
                except BaseException:
                    child.kill()
                    raise
                finally:
                    if reason and child.poll() is None:
                        child.kill()
                rc = child.wait()
        if rc != 0 or peak <= 0 or evidence != frozen_evidence(out, task["stage"]):
            rejected = folder / "rejected_result.json"
            raise ValueError(read(rejected)["error"] if rejected.exists() else "Worker or frozen evidence failed")
        payload = read(folder / "result.json")
        if payload["task"] != task:
            raise ValueError("H3 task identity changed during execution")
        check_result(out, task, payload["result"], protocol)
    except BaseException as exc:
        error = dict(type=type(exc).__name__, message=str(exc), traceback=traceback.format_exc())
    files = {path.name: digest(path) for path in folder.iterdir() if path.is_file()}
    save(folder / "record.json", dict(
        status="failed" if error or reason else "completed", command=args, task=task,
        returncode=rc, watchdog=reason, error=error, peak_rss_bytes=peak,
        process_wall_s=time.perf_counter() - started, files=files, frozen_evidence=evidence,
    ))
    if error or reason:
        raise RuntimeError(f"Preserved failed H3 trial at {folder}: {reason or error['message']}")


def freeze_s30(out, protocol, tasks):
    path = out / "s30_lock.json"
    if not path.exists() and (out / "runs").exists() and any((out / "runs").glob("E30_*")):
        raise ValueError("S30 routes cannot be frozen after any E30 trial")
    references = {}
    for task in tasks:
        run = saved_task(out, task, protocol)
        score = run["result"]["physical_replay"]
        references[task["instance"]] = dict(
            run_id=run["run_id"], waypoints=score["waypoints"], J=score["J"], Pd=score["pd_final"],
            observation_times_s=score["observation_times_s"], particle_sha256=task["particle_sha256"],
            record_sha256=digest(out / "runs" / run["run_id"] / "record.json"),
        )
    lock = dict(status="shared_S30_locked", references=references, protocol_sha256=digest(out / "protocol.json"))
    if path.exists() and read(path) != lock:
        raise ValueError("S30 shared route lock or run fingerprints changed")
    if not path.exists():
        save(path, lock)
        print("Frozen twelve independently replayed S30 routes", flush=True)
    return lock


def run_stage(out, stage):
    with h2.exclusive_run(out):
        protocol, tasks = verify_protocol(out, full=True)
        if stage == "E30":
            freeze_s30(out, protocol, tasks["S30"])
        for index, task in enumerate(tasks[stage], start=1):
            launch_task(out, task, protocol)
            print(f"{stage} {index}/{len(tasks[stage])} {task['instance']} {task['method']} rep={task['repetition']}", flush=True)
        if stage == "S30":
            freeze_s30(out, protocol, tasks["S30"])
        verify_protocol(out, full=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "freeze", "s30", "e30", "analyze", "_worker"))
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    out = batch_directory(args.out)
    if args.command == "validate":
        validate(out)
    elif args.command == "freeze":
        freeze(out)
    elif args.command in ("s30", "e30"):
        run_stage(out, args.command.upper())
    elif args.command == "_worker":
        run_worker(out, args.run_id)
    else:
        from report_eight_neighbor_h3 import analyze

        analyze(out)


if __name__ == "__main__":
    main()
