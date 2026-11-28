#!/usr/bin/env python3
"""Run the preregistered, local H2 comparison on verified new-date inputs."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager
import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import random
from statistics import median
import subprocess
import sys
import time
import traceback
import xml.etree.ElementTree as ET

import run_eight_neighbor_confirmation as confirmation
import run_eight_neighbor_followup as followup
import run_solver_paradigm_study as common

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs/eight_neighbor_h2.json"
STAGES = ("S30", "H30")
PRIMARY = "heading_square"
AXIS = "axis_square"
INPUT_LOCKS = ("method_lock.json", "availability_audit.json", "date_lock.json", "inputs_lock.json")
read, save, digest, object_digest = common.read, common.save, common.digest, common.object_digest


def stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def task_id(task):
    return task["stage"] + "_" + object_digest(task)[:20]


def plan(config):
    settings = config["objective"]
    n_inputs = sum(len(site["primary"]) for site in config["datasets"].values()) * 2
    n_s30 = n_inputs * config["initialization"]["repetitions"]
    n_h30 = n_inputs * len(settings["footprints"]) * len(settings["connectivities"]) * config["search"]["repetitions"]
    return {
        "status": "planned_requires_verified_real_inputs",
        "method": config["method"],
        "date_blocks": n_inputs // 2,
        "particle_instances": n_inputs,
        "tasks": {"S30": n_s30, "H30": n_h30},
        "total_algorithm_budget_s": n_s30 * config["initialization"]["seconds"] + n_h30 * config["search"]["seconds"],
        "budget_scope": "algorithm only, excludes forcing acquisition, drift, loading and external audit",
    }


def registered_instances(config, instances):
    by_id = {}
    blocks = defaultdict(list)
    permitted = {
        (site, block[0]): set(block[2:])
        for site, dataset in config["datasets"].items()
        for block in dataset["primary"] + dataset["alternates"]
    }
    for instance in instances:
        identity = instance["id"]
        if identity != f"{instance['block_id']}_s{instance['seed']}":
            raise ValueError("H2 particle instance ID must bind its date and seed")
        if identity in by_id:
            raise ValueError("Duplicate registered H2 particle instance")
        by_id[identity] = instance
        blocks[instance["base_scene"], instance["block_id"]].append(instance["seed"])
    if Counter(site for site, _ in blocks) != {
        site: len(dataset["primary"]) for site, dataset in config["datasets"].items()
    }:
        raise ValueError("H2 needs exactly three independently verified dates per site")
    if any(len(seeds) != 2 or set(seeds) != permitted.get(block) for block, seeds in blocks.items()):
        raise ValueError("Every H2 date requires its own two preregistered seeds")
    return by_id


def make_tasks(config, instances, manifests):
    cases = registered_instances(config, instances)
    matrix = {stage: [] for stage in STAGES}
    for identity, case in sorted(cases.items()):
        base = dict(instance=identity, block_id=case["block_id"], base_scene=case["base_scene"],
                    seed=case["seed"], manifest_sha256=manifests[identity])
        matrix["S30"].append(dict(base, stage="S30", method="PT_then_original_paper_greedy",
                                  connectivity=4, footprint=AXIS, repetition=0,
                                  seconds=config["initialization"]["seconds"]))
        for footprint in config["objective"]["footprints"]:
            for connectivity in config["objective"]["connectivities"]:
                for repetition in range(config["search"]["repetitions"]):
                    matrix["H30"].append(dict(base, stage="H30", method=config["method"],
                                              footprint=footprint, connectivity=connectivity,
                                              repetition=repetition, seconds=config["search"]["seconds"]))
    for offset, stage in enumerate(STAGES):
        random.Random(config["task_order_seed"] + offset).shuffle(matrix[stage])
    if {stage: len(tasks) for stage, tasks in matrix.items()} != plan(config)["tasks"]:
        raise ValueError("The H2 matrix must contain 12 initializations and 144 searches")
    return matrix


def source_inventory(config_path):
    result = confirmation.source_inventory(config_path)
    roots = (ROOT / "docs/eight_neighbor_confirmation", ROOT / "docs/eight_neighbor_h2")
    for folder in roots:
        for path in sorted(folder.rglob("*")):
            if path.is_file() and path.suffix in {".md", ".json", ".py"}:
                result[path.relative_to(ROOT).as_posix()] = digest(path)
    return dict(sorted(result.items()))


def test_paths():
    original = read(confirmation.DEFAULT_CONFIG)["validation_tests"]
    additional = sorted({
        path.relative_to(ROOT).as_posix()
        for pattern in ("test_h2*.py", "test_eight_neighbor_h2*.py")
        for path in (ROOT / "tests").glob(pattern)
    })
    required = {"tests/test_eight_neighbor_h2_runner.py", "tests/test_eight_neighbor_h2_inputs.py",
                "tests/test_h2_acquire.py"}
    if not required.issubset(additional):
        raise ValueError("Required H2 runner, archive and forcing tests are missing")
    return [*original, *additional]


def validate(config_path, out):
    from h2_protocol import verify_method

    config = verify_method(config_path, out)["config"]
    sources, env = source_inventory(config_path), confirmation.environment()
    folder = out / "validation" / stamp()
    folder.mkdir(parents=True, exist_ok=False)
    xml = folder / "pytest.xml"
    paths = test_paths()
    command = [sys.executable, "-m", "pytest", "-q", *paths, f"--junitxml={xml}"]
    with (folder / "stdout.log").open("x", encoding="utf-8") as stdout, \
            (folder / "stderr.log").open("x", encoding="utf-8") as stderr:
        completed = subprocess.run(command, cwd=ROOT, env=common.child_environment(),
                                   stdout=stdout, stderr=stderr, check=False)
    cases = ET.parse(xml).getroot().findall(".//testcase") if xml.is_file() else []
    bad = [item for item in cases if any(item.find(tag) is not None for tag in ("failure", "error", "skipped"))]
    unchanged = sources == source_inventory(config_path) and env == confirmation.environment()
    passed = completed.returncode == 0 and bool(cases) and not bad and unchanged
    result = dict(status="passed" if passed else "failed", command=command, paths=paths, testcase_count=len(cases),
                  bad_or_skipped_count=len(bad), returncode=completed.returncode, environment=env,
                  source_sha256=sources, unchanged=unchanged, xml_sha256=digest(xml) if xml.is_file() else None)
    record = folder / "result.json"
    save(record, result)
    save(out / "validation/latest.json",
         dict(path=record.relative_to(out).as_posix(), sha256=digest(record)), replace=True)
    if not passed:
        raise ValueError("Actual H2 validation failed; see retained test evidence")
    print(f"Passed {len(cases)} tests: {folder}", flush=True)


def check_validation(out, sources, env, ref):
    result_path = out / ref["path"]
    result = read(result_path)
    if (digest(result_path) != ref["sha256"] or result["status"] != "passed"
            or result["returncode"] != 0 or result["testcase_count"] <= 0
            or result["bad_or_skipped_count"] or not result["unchanged"]
            or result["paths"] != test_paths() or result["source_sha256"] != sources
            or result["environment"] != env or digest(result_path.with_name("pytest.xml")) != result["xml_sha256"]):
        raise ValueError("Validation evidence does not bind this H2 configuration, code and runtime")


def freeze(config_path, out):
    from h2_protocol import verify_inputs, verify_method

    protocol_path = out / "protocol.json"
    if protocol_path.exists():
        verify_protocol(config_path, out, full=True)
        print("Existing H2 protocol verified", flush=True)
        return
    if (out / "runs").exists():
        raise ValueError("Cannot freeze after a run directory has been created")
    method = verify_method(config_path, out)
    inputs = verify_inputs(config_path, out)
    config = method["config"]
    solve_options(config)
    sources, env = source_inventory(config_path), confirmation.environment()
    validation = read(out / "validation/latest.json")
    check_validation(out, sources, env, validation)
    cases = registered_instances(config, inputs["instances"])
    archives = {identity: {
        name: inputs["archive_files"][f"inputs/{identity}/{filename}"]
        for name, filename in (("manifest_sha256", "manifest.json"), ("particle_sha256", "particles.npz"))
    } for identity in cases}
    manifests = {identity: data["manifest_sha256"] for identity, data in archives.items()}
    tasks = make_tasks(config, inputs["instances"], manifests)
    for stage in STAGES:
        save(out / "tasks" / f"{stage}.json", tasks[stage])
    save(protocol_path, dict(
        status="frozen_before_H2_search", created_utc=datetime.now(timezone.utc).isoformat(),
        config_sha256=digest(config_path), config=config, method_lock_object_sha256=object_digest(method),
        input_lock_object_sha256=object_digest(inputs), source_sha256=sources, environment=env,
        validation=validation, archive_hashes=archives, instances=cases,
        input_lock_file_sha256={name: digest(out / name) for name in INPUT_LOCKS},
        matrix_sha256={stage: object_digest(value) for stage, value in tasks.items()},
        design=plan(config)))
    print("Frozen 156 H2 jobs. S30 must complete before its results are locked and H30 can start.", flush=True)


def verify_protocol(config_path, out, *, full=False):
    protocol = read(out / "protocol.json")
    config = read(config_path)
    if (protocol["status"] != "frozen_before_H2_search" or config != protocol["config"]
            or digest(config_path) != protocol["config_sha256"]
            or protocol["source_sha256"] != source_inventory(config_path)
            or protocol["environment"] != confirmation.environment()):
        raise ValueError("H2 frozen configuration, code or runtime changed")
    check_validation(out, protocol["source_sha256"], protocol["environment"], protocol["validation"])
    if any(digest(out / name) != expected for name, expected in protocol["input_lock_file_sha256"].items()):
        raise ValueError("H2 method, availability, date or scientific input lock changed")
    if full:
        from h2_protocol import verify_inputs, verify_method

        if (object_digest(verify_method(config_path, out)) != protocol["method_lock_object_sha256"]
                or object_digest(verify_inputs(config_path, out)) != protocol["input_lock_object_sha256"]):
            raise ValueError("H2 method or scientific input lock changed")
    tasks = {stage: read(out / "tasks" / f"{stage}.json") for stage in STAGES}
    if any(object_digest(tasks[stage]) != protocol["matrix_sha256"][stage] for stage in STAGES):
        raise ValueError("H2 frozen task matrix changed")
    return protocol, tasks


def initialization_options(config):
    return {
        "tolerance": {"score_absolute": config["decision"]["score_absolute"]},
        "initialization": {
            "epsilon": config["initialization"]["epsilon"],
            "max_open": config["initialization"]["max_open"],
            "final_replay_reserve_seconds": config["initialization"]["final_reserve_s"],
            "generation_cost": "S30 charged separately; H30 charges common seed copying and replay",
        },
    }


def solve_options(config):
    control = dict(config["solver"])
    if (config["method"] != "completion_J" or control["completion"] != "greedy"
            or control["objective"] != "J" or not control["archive"]):
        raise ValueError("H2 requires frozen completion_J and J-only comparison")
    control["pd_floor"] = None
    return control


def audit_options(config):
    options = solve_options(config)
    return {
        "search": {key: options[key] for key in ("guide_weight", "max_open")},
        "refinement": {key: options[key] for key in ("completion_every", "completion_max_calls", "archive_limit",
                                                     "archive_history_limit", "pd_tolerance")},
        "methods": {config["method"]: {key: options[key] for key in ("completion", "objective", "archive")}},
        "decision": {"pd_guard_delta": 0.0},
        "tolerance": {"score_absolute": config["decision"]["score_absolute"]},
        "dataset_role": "new_date_historical_forcing",
    }


def frozen_evidence(out, stage):
    values = {"protocol_sha256": digest(out / "protocol.json")}
    if stage == "H30":
        values["s30_lock_sha256"] = digest(out / "s30_lock.json")
    return values


def score_is_consistent(score, tol):
    survival = score["survival"]
    times = score["observation_times_s"]
    return (bool(times) and len(survival) == len(times) + 1
            and all(math.isfinite(elapsed) for elapsed in times)
            and all(b > a for a, b in zip([0.0, *times], times))
            and abs(score["physical_duration_s"] - times[-1]) <= tol
            and abs(score["distance_m"] - score["physical_duration_s"] * 20.0) <= tol
            and all(math.isfinite(value) and -tol <= value <= 1 + tol for value in survival)
            and abs(survival[0] - 1) <= tol
            and all(b <= a + tol for a, b in zip(survival, survival[1:]))
            and abs(math.fsum(survival[1:]) - score["J"]) <= tol
            and abs(1 - survival[-1] - score["pd_final"]) <= tol)


def verify_result(task, result, protocol, reference=None):
    tol = protocol["config"]["decision"]["score_absolute"]
    score = result["physical_replay"]
    inputs = result["inputs"]
    archived = protocol["archive_hashes"][task["instance"]]
    if (result["status"] != "valid" or result["environment"] != protocol["environment"]
            or inputs["case"] != protocol["instances"][task["instance"]] or inputs["footprint"] != task["footprint"]
            or inputs["manifest_sha256"] != task["manifest_sha256"]
            or any(inputs[key] != expected for key, expected in archived.items())
            or result.get("formal_optimality_certificate") is not False
            or result["method"] != task["method"] or not result["history"]
            or score["connectivity"] != task["connectivity"] or score["footprint"] != task["footprint"]
            or not score_is_consistent(score, tol)
            or not all(math.isfinite(result[key]) for key in ("J", "pd_final"))
            or abs(result["J"] - score["J"]) > tol or abs(result["pd_final"] - score["pd_final"]) > tol
            or any(not 0 <= item["elapsed_s"] <= task["seconds"]
                   for item in result["history"] + result.get("pareto_archive", []))):
        raise ValueError("H2 replay, input, runtime or budget evidence failed")
    if task["stage"] == "S30":
        replays = result["physical_replays"]
        if (set(replays) != {PRIMARY, AXIS}
                or any(replays[key]["waypoints"] != result["waypoints"] or replays[key]["footprint"] != key
                       or replays[key]["connectivity"] != 4 or not score_is_consistent(replays[key], tol)
                       for key in replays)):
            raise ValueError("S30 did not preserve one independently replayed four-neighbor route")
    elif (reference is None or result["reference_run_id"] != reference["run_id"]
            or result["reference_waypoints_sha256"] != reference["waypoints_sha256"]
            or result["method_options"] != solve_options(protocol["config"])
            or score["observation_times_s"] != reference["observation_times_s"]
            or abs(result["reference_J"] - reference["J"]) > tol
            or abs(result["reference_pd"] - reference["pd_final"]) > tol
            or result["history"][0]["waypoints"] != reference["waypoints"]):
        raise ValueError("H30 did not start from the frozen shared S30 route and clock")


def score_reference(row, footprint):
    result = row["result"]
    score = result["physical_replays"][footprint]
    return dict(waypoints=result["waypoints"], J=score["J"], pd_final=score["pd_final"], run_id=row["run_id"],
                observation_times_s=score["observation_times_s"],
                waypoints_sha256=object_digest(result["waypoints"]))


def s30_reference(lock, task):
    return lock["references"][task["instance"]][task["footprint"]]


def worker(config_path, out, task_path, result_path):
    protocol, tasks = verify_protocol(config_path, out)
    config = protocol["config"]
    task = read(task_path)
    if task not in tasks.get(task.get("stage"), []):
        raise ValueError("Unregistered H2 worker task")
    folder = out / "runs" / task_id(task)
    if task_path != folder / "task.json" or result_path != folder / "result.json":
        raise ValueError("H2 worker must write only its registered run directory")
    evidence = frozen_evidence(out, task["stage"])
    case = protocol["instances"][task["instance"]]
    destination = out / "inputs" / task["instance"]
    if digest(destination / "manifest.json") != task["manifest_sha256"]:
        raise ValueError("Frozen particle manifest changed")
    from asar_repro.h2_inputs import load_h2_input

    problem, grid, discrete, info = load_h2_input(ROOT, case, destination, task["footprint"])
    if any(info.get(key) != expected for key, expected in protocol["archive_hashes"][task["instance"]].items()):
        raise ValueError("Loaded H2 particle archive has the wrong manifest")
    reference = None
    if task["stage"] == "S30":
        heading, _, _, other_info = load_h2_input(ROOT, case, destination, PRIMARY)
        if other_info.get("manifest_sha256") != info["manifest_sha256"]:
            raise ValueError("S30 replays do not share the same archive")
        result = followup.initialize_case(initialization_options(config), task, problem, grid, discrete, heading)
        paper = [item for item in result["history"] if item["source"] == "original_paper_greedy"]
        result["diagnostic_times"] = dict(first_new_complete_replay_s=paper[0]["elapsed_s"] if paper else None)
        result["first_new_complete_scope"] = "first returned new paper route with completed bridge replay"
    else:
        lock = verify_s30_lock(out, protocol, tasks["S30"], full=False)
        reference = s30_reference(lock, task)
        from asar_repro.physical_refinement import solve_physical_refinement

        options = solve_options(config)
        started, cpu = time.perf_counter(), time.process_time()
        raw = solve_physical_refinement(problem, connectivity=task["connectivity"],
                                        initial_waypoints=reference["waypoints"],
                                        max_seconds=task["seconds"], **options)
        wall, cpu_s = time.perf_counter() - started, time.process_time() - cpu
        result = confirmation.audit_result(audit_options(config), problem, reference, task, raw, wall, cpu_s)
    result.update(method=task["method"], environment=confirmation.environment(), inputs=info)
    verify_result(task, result, protocol, reference)
    if evidence != frozen_evidence(out, task["stage"]):
        raise ValueError("H2 protocol changed during the worker run")
    save(result_path, dict(task=task, result=result))


def load_record(out, task, protocol, lock=None):
    identity = task_id(task)
    folder = out / "runs" / identity
    if not folder.exists():
        return None
    record_path, result_path = folder / "record.json", folder / "result.json"
    if not record_path.is_file() or not result_path.is_file():
        raise ValueError(f"Incomplete H2 run preserved: {identity}")
    record, payload = read(record_path), read(result_path)
    if (record["status"] != "completed" or record["returncode"] != 0 or record["watchdog"] is not None
            or record["task"] != task or payload["task"] != task or read(folder / "task.json") != task
            or record["frozen_evidence"] != frozen_evidence(out, task["stage"])
            or record["result_sha256"] != digest(result_path)):
        raise ValueError(f"Invalid or failed H2 run preserved: {identity}")
    reference = s30_reference(lock, task) if task["stage"] == "H30" else None
    verify_result(task, payload["result"], protocol, reference)
    return dict(task=task, record=record, result=payload["result"], run_id=identity)


def collect(out, tasks, protocol, lock=None):
    rows, missing, errors = [], [], []
    for task in tasks:
        try:
            row = load_record(out, task, protocol, lock)
            if row is None:
                missing.append(task_id(task))
            else:
                rows.append(row)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            errors.append(dict(run_id=task_id(task), error=str(exc)))
    status = "evaluation_invalid" if errors else "pending" if missing else "complete"
    return dict(planned=len(tasks), completed=len(rows), status=status, missing=missing, errors=errors), rows


def freeze_s30(config_path, out):
    protocol, matrix = verify_protocol(config_path, out, full=True)
    if (out / "s30_lock.json").exists():
        verify_s30_lock(out, protocol, matrix["S30"])
        print("Existing shared S30 route lock verified", flush=True)
        return
    if any((out / "runs" / task_id(task)).exists() for task in matrix["H30"]):
        raise ValueError("Cannot create the shared S30 route lock after H30 has started")
    status, rows = collect(out, matrix["S30"], protocol)
    if status["status"] != "complete":
        raise ValueError("All 12 S30 routes must be complete and verified before H30")
    references = {row["task"]["instance"]: {key: score_reference(row, key) for key in (PRIMARY, AXIS)}
                  for row in rows}
    files = {}
    for row in rows:
        for name in ("record.json", "result.json"):
            relative = Path("runs") / row["run_id"] / name
            files[relative.as_posix()] = digest(out / relative)
    save(out / "s30_lock.json", dict(status="shared_S30_locked", protocol_sha256=digest(out / "protocol.json"),
                                    references=references, files=files))
    print("Frozen 12 common S30 routes", flush=True)


def verify_s30_lock(out, protocol, tasks, *, full=True):
    lock = read(out / "s30_lock.json")
    if (lock["status"] != "shared_S30_locked" or lock["protocol_sha256"] != digest(out / "protocol.json")
            or set(lock["references"]) != set(protocol["instances"])):
        raise ValueError("Invalid shared S30 route lock")
    if full:
        status, rows = collect(out, tasks, protocol)
        references = {row["task"]["instance"]: {key: score_reference(row, key) for key in (PRIMARY, AXIS)}
                      for row in rows}
        files = {f"runs/{task_id(task)}/{name}" for task in tasks for name in ("record.json", "result.json")}
        if (status["status"] != "complete" or references != lock["references"] or set(lock["files"]) != files
                or any(digest(out / path) != expected for path, expected in lock["files"].items())):
            raise ValueError("Shared S30 lock or its run evidence changed")
    return lock


def launch_task(config_path, out, task, protocol, lock=None):
    import psutil

    if load_record(out, task, protocol, lock) is not None:
        print(f"Verified existing {task_id(task)}", flush=True)
        return
    folder = out / "runs" / task_id(task)
    folder.mkdir(parents=True, exist_ok=False)
    save(folder / "task.json", task)
    evidence = frozen_evidence(out, task["stage"])
    result_path = folder / "result.json"
    command = [sys.executable, str(Path(__file__).resolve()), "_worker", "--config", str(config_path),
               "--out", str(out), "--task", str(folder / "task.json"), "--result", str(result_path)]
    policy = protocol["config"]["watchdog"]
    started, peak, killed = time.perf_counter(), 0, None
    with (folder / "stdout.log").open("x", encoding="utf-8") as stdout, \
            (folder / "stderr.log").open("x", encoding="utf-8") as stderr:
        child = subprocess.Popen(command, cwd=ROOT, env=common.child_environment(), stdout=stdout, stderr=stderr)
        process = None
        relatives = []
        try:
            while child.poll() is None:
                try:
                    if process is None:
                        process = psutil.Process(child.pid)
                    relatives = process.children(recursive=True)
                    rss = process.memory_info().rss + sum(p.memory_info().rss for p in relatives)
                    peak = max(peak, rss)
                    if rss > policy["rss_limit_bytes"]:
                        killed = "rss_limit"
                except psutil.NoSuchProcess:
                    pass
                if time.perf_counter() - started > task["seconds"] + policy["grace_seconds"]:
                    killed = killed or "process_watchdog"
                if killed:
                    break
                time.sleep(policy["poll_seconds"])
        except (KeyboardInterrupt, psutil.Error):
            killed = "interrupted_or_resource_monitor_failed"
        if killed and child.poll() is None:
            for descendant in reversed(relatives):
                try:
                    descendant.kill()
                except psutil.NoSuchProcess:
                    pass
            child.kill()
        returncode = child.wait()
    result_sha = digest(result_path) if result_path.is_file() else None
    valid = returncode == 0 and not killed and result_sha is not None
    if valid:
        reference = s30_reference(lock, task) if task["stage"] == "H30" else None
        try:
            payload = read(result_path)
            if payload["task"] != task:
                raise ValueError("Worker task identity changed")
            verify_result(task, payload["result"], protocol, reference)
        except (OSError, KeyError, ValueError, TypeError):
            valid = False
    record = dict(task=task, command=command, frozen_evidence=evidence, status="completed" if valid else "failed",
                  returncode=returncode, watchdog=killed, process_wall_s=time.perf_counter() - started,
                  peak_rss_bytes=peak, result_sha256=result_sha)
    save(folder / "record.json", record)
    if not valid:
        raise RuntimeError(f"Failed H2 run preserved; stopped at {folder}")
    print(f"Completed {task_id(task)}", flush=True)


@contextmanager
def exclusive_run(out):
    path = out / "execution.lock"
    with path.open("x", encoding="utf-8") as handle:
        handle.write(f"Started {datetime.now(timezone.utc).isoformat()}\n")
    try:
        yield
    finally:
        path.unlink()


def run_stage(config_path, out, stage):
    with exclusive_run(out):
        protocol, tasks = verify_protocol(config_path, out, full=True)
        lock = verify_s30_lock(out, protocol, tasks["S30"]) if stage == "H30" else None
        for task in tasks[stage]:
            launch_task(config_path, out, task, protocol, lock)
        summarize(config_path, out)


def representative(rows):
    ordered = sorted(rows, key=lambda row: (row["result"]["J"], row["task"]["repetition"]))
    if len(ordered) != 3 or {row["task"]["repetition"] for row in ordered} != {0, 1, 2}:
        raise ValueError("An H2 comparison requires three distinct repetitions")
    chosen = ordered[1]
    result = chosen["result"]
    return dict(J=result["J"], Pd=result["pd_final"], run_id=chosen["run_id"],
                J_range=[ordered[0]["result"]["J"], ordered[-1]["result"]["J"]],
                algorithm_wall_median_s=median(row["result"]["algorithm_wall_s"] for row in ordered),
                peak_rss_median_bytes=median(row["record"]["peak_rss_bytes"] for row in ordered))


def paired_seed_scores(config, rows):
    groups = defaultdict(list)
    for row in rows:
        task = row["task"]
        groups[task["instance"], task["footprint"], task["connectivity"]].append(row)
    comparisons = []
    for instance, footprint in sorted({key[:2] for key in groups}):
        if not all(len(groups.get((instance, footprint, graph), [])) == 3 for graph in (4, 8)):
            continue
        four, eight = [representative(groups[instance, footprint, graph]) for graph in (4, 8)]
        task = groups[instance, footprint, 4][0]["task"]
        delta = four["J"] - eight["J"]
        relative = delta / four["J"] if four["J"] != 0 else None
        resolved = (None if relative is None else
                    0.0 if abs(delta) <= config["decision"]["score_absolute"] else relative)
        comparisons.append(dict(instance=instance, footprint=footprint, block_id=task["block_id"],
                                base_scene=task["base_scene"], seed=task["seed"], four=four, eight=eight,
                                absolute_J_gain=delta, relative_J_gain=relative, decision_relative_J_gain=resolved,
                                delta_Pd_pp=100 * (eight["Pd"] - four["Pd"])))
    return comparisons


def date_decision(config, comparisons, *, complete):
    if not complete:
        return dict(status="evaluation_invalid", reason="H2 results missing or invalid", date_rows=[])
    settings = config["decision"]
    tol = settings["relative_tolerance"]
    main = [row for row in comparisons if row["footprint"] == PRIMARY]
    groups = defaultdict(list)
    for row in main:
        groups[row["base_scene"], row["block_id"]].append(row)
    if (len(main) != 12 or Counter(site for site, _ in groups) != {site: 3 for site in config["datasets"]}
            or any(len(rows) != 2 or len({row["seed"] for row in rows}) != 2 for rows in groups.values())):
        return dict(status="evaluation_invalid", reason="Expected six dates with two distinct seeds", date_rows=[])
    dates = []
    for (site, block), rows in sorted(groups.items()):
        raw = [row["relative_J_gain"] for row in rows]
        decided = [row["decision_relative_J_gain"] for row in rows]
        gamma = median(decided) if all(value is not None for value in decided) else None
        dates.append(dict(
            base_scene=site, block_id=block, seeds=[row["seed"] for row in rows],
            relative_J_gain=median(raw) if all(value is not None for value in raw) else None,
            decision_relative_J_gain=gamma,
            winner=gamma is not None and gamma >= settings["date_winner_min"] - tol,
            date_regression=None if gamma is None else gamma < -settings["max_date_regression"] - tol))
    unstable = [row["instance"] for row in main if row["decision_relative_J_gain"] is not None
                and row["decision_relative_J_gain"] < -settings["max_seed_regression"] - tol]
    if any(row["decision_relative_J_gain"] is None for row in dates):
        return dict(status="evaluation_invalid", reason="Zero J4 requires separate review of date gain",
                    date_rows=dates, seed_instability=unstable)
    winners = Counter(row["base_scene"] for row in dates if row["winner"])
    passed = (sum(winners.values()) >= settings["min_date_winners"]
              and all(winners[site] >= settings["min_winners_per_scene"] for site in config["datasets"])
              and not any(row["date_regression"] for row in dates))
    status = ("new_date_screen_not_passed" if not passed else
              "new_date_J_signal_with_seed_instability" if unstable else "new_date_J_transfer_signal")
    return dict(status=status, date_rows=dates, seed_instability=unstable,
                winners_by_site={site: winners[site] for site in config["datasets"]},
                tolerances=dict(absolute_score=settings["score_absolute"], relative_gain=tol),
                external_unit="date block; two seeds and three timing repetitions are nested")


def csv_output(path, rows, fields):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def comparison_row(row):
    task, result, process = row["task"], row["result"], row["record"]
    return dict(run_id=row["run_id"], stage=task["stage"], instance=task["instance"], block_id=task["block_id"],
                base_scene=task["base_scene"], seed=task["seed"], method=task["method"], footprint=task["footprint"],
                connectivity=task["connectivity"], repetition=task["repetition"], budget_s=task["seconds"],
                J=result["J"], Pd=result["pd_final"], physical_duration_s=result["physical_replay"]["physical_duration_s"],
                distance_m=result["physical_replay"]["distance_m"], best_found_elapsed_s=result["best_found_elapsed_s"],
                first_new_complete_replay_s=result["diagnostic_times"]["first_new_complete_replay_s"],
                initial_J=result["initial_J"], stop_reason=result.get("stop_reason"), watchdog=process["watchdog"],
                algorithm_wall_s=result["algorithm_wall_s"], algorithm_cpu_s=result["algorithm_cpu_s"],
                process_wall_s=process["process_wall_s"], peak_rss_bytes=process["peak_rss_bytes"],
                budget_overshoot_s=result["budget_overshoot_s"], result_path=f"runs/{row['run_id']}/result.json")


def survival_rows(row):
    result = row["result"]
    scores = result["physical_replays"] if row["task"]["stage"] == "S30" else {
        row["task"]["footprint"]: result["physical_replay"]}
    for footprint, score in scores.items():
        for tick, (seconds, remaining) in enumerate(zip(
                [0.0, *score["observation_times_s"]], score["survival"], strict=True)):
            yield dict(run_id=row["run_id"], instance=row["task"]["instance"], footprint=footprint,
                       connectivity=row["task"]["connectivity"], tick=tick, elapsed_physical_s=seconds,
                       remaining_mass=remaining, cumulative_Pd=1 - remaining)


def resources(rows):
    return dict(
        algorithm_wall_s=sum(row["result"]["algorithm_wall_s"] for row in rows),
        algorithm_cpu_s=sum(row["result"]["algorithm_cpu_s"] for row in rows),
        process_wall_s=sum(row["record"]["process_wall_s"] for row in rows),
        peak_sampled_rss_bytes=max((row["record"]["peak_rss_bytes"] for row in rows), default=0),
        max_budget_overshoot_s=max((row["result"]["budget_overshoot_s"] for row in rows), default=0.0),
        stop_counts=dict(Counter(str(row["result"].get("stop_reason")) for row in rows)))


def summarize(config_path, out):
    protocol, tasks = verify_protocol(config_path, out, full=True)
    lock = verify_s30_lock(out, protocol, tasks["S30"]) if (out / "s30_lock.json").exists() else None
    stages, rows_by_stage = {}, {}
    for stage in STAGES:
        stages[stage], rows_by_stage[stage] = collect(out, tasks[stage], protocol, lock)
    config = protocol["config"]
    complete = all(value["status"] == "complete" for value in stages.values()) and lock is not None
    comparisons = paired_seed_scores(config, rows_by_stage["H30"])
    decision = date_decision(config, comparisons, complete=True) if complete else dict(
        status="evaluation_invalid" if any(row["errors"] for row in stages.values()) else "pending",
        reason="All registered jobs and the S30 reference lock are required", date_rows=[])
    summary = dict(status=decision["status"], design=protocol["design"], stages=stages,
                   completed_protocol=complete, decision=decision, seed_comparisons=comparisons,
                   resources={stage: resources(rows) for stage, rows in rows_by_stage.items()},
                   formal_optimality_certificate=False, weather_scope="new-date historical forcing; fixed six date blocks")
    rows = [row for stage in STAGES for row in rows_by_stage[stage]]
    save(out / "summary.json", summary, replace=True)
    run_fields = ("run_id", "stage", "instance", "block_id", "base_scene", "seed", "method", "footprint",
                  "connectivity", "repetition", "budget_s", "J", "Pd", "physical_duration_s", "distance_m",
                  "best_found_elapsed_s", "first_new_complete_replay_s", "initial_J", "stop_reason", "watchdog",
                  "algorithm_wall_s", "algorithm_cpu_s", "process_wall_s", "peak_rss_bytes", "budget_overshoot_s",
                  "result_path")
    csv_output(out / "comparison.csv", (comparison_row(row) for row in rows), run_fields)
    csv_output(out / "survival.csv", (item for row in rows for item in survival_rows(row)),
               ("run_id", "instance", "footprint", "connectivity", "tick", "elapsed_physical_s",
                "remaining_mass", "cumulative_Pd"))
    seed_fields = ("instance", "block_id", "base_scene", "seed", "footprint", "J4", "J8", "Pd4", "Pd8",
                   "run4", "run8", "absolute_J_gain", "relative_J_gain", "decision_relative_J_gain", "delta_Pd_pp")
    csv_output(out / "seed_comparison.csv", ({
        **{key: row[key] for key in seed_fields if key in row},
        "J4": row["four"]["J"], "J8": row["eight"]["J"], "Pd4": row["four"]["Pd"], "Pd8": row["eight"]["Pd"],
        "run4": row["four"]["run_id"], "run8": row["eight"]["run_id"],
    } for row in comparisons), seed_fields)
    csv_output(out / "date_comparison.csv", ({
        **row, "seeds": " ".join(map(str, row["seeds"])),
    } for row in decision["date_rows"]),
        ("base_scene", "block_id", "seeds", "relative_J_gain", "decision_relative_J_gain", "winner", "date_regression"))
    print(f"H2 summary {decision['status']}: {out / 'summary.json'}", flush=True)
    return summary


def main(argv=None):
    from h2_protocol import DEFAULT_OUT

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "validate", "freeze", "run", "freeze-s30", "summarize", "_worker"))
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--stage", choices=STAGES)
    parser.add_argument("--task", type=Path)
    parser.add_argument("--result", type=Path)
    args = parser.parse_args(argv)
    config_path, out = args.config.resolve(), args.out.resolve()
    config = read(config_path)
    common.set_threads(config)
    if args.command == "plan":
        print(json.dumps(plan(config), ensure_ascii=False, indent=2))
        return
    if out == DEFAULT_OUT.parent.resolve() or not out.is_relative_to(DEFAULT_OUT.parent.resolve()):
        parser.error("Use a child directory of the registered H2 output root")
    if args.command == "_worker":
        if args.task is None or args.result is None:
            parser.error("_worker requires task and result paths")
        worker(config_path, out, args.task.resolve(), args.result.resolve())
        return
    path = out / "commands" / f"{stamp()}_{args.command}.json"
    record = dict(status="running", started_utc=datetime.now(timezone.utc).isoformat(),
                  directory=str(ROOT), command=[sys.executable, str(Path(__file__).resolve()),
                                                 *(sys.argv[1:] if argv is None else argv)])
    save(path, record)
    try:
        if args.command == "run":
            if args.stage is None:
                raise ValueError("run requires --stage")
            run_stage(config_path, out, args.stage)
        elif args.command in {"freeze", "freeze-s30", "summarize"}:
            actions = {"freeze": freeze, "freeze-s30": freeze_s30, "summarize": summarize}
            with exclusive_run(out):
                actions[args.command](config_path, out)
        else:
            validate(config_path, out)
        record.update(status="completed", returncode=0)
    except Exception:
        record.update(status="failed", returncode=1, traceback=traceback.format_exc())
        raise
    finally:
        record["finished_utc"] = datetime.now(timezone.utc).isoformat()
        save(path, record, replace=True)


if __name__ == "__main__":
    main()

