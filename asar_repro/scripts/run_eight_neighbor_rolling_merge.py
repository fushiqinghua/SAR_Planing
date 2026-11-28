#!/usr/bin/env python3
"""Shadow diagnosis followed, only if admitted, by a four-arm merging study.

This is an isolated protocol. It imports the frozen pilot's read-only scoring,
budget and execution auditors; it does not change its runner, data or records.
The preparer has not executed this CLI, project modules, tests or experiments.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import random
from statistics import median
import subprocess
import sys
import time
import traceback
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
BASE_COMMIT = "be048ea2304a25211be546c24cca506e87734049"
STUDY_BASE_COMMIT = "6084c7d6528a863709466e1dfbb0930459d95414"
REGISTERED_CONFIG_HASH = "9cf1093f00d8a458bb40ca6db4938bbbb8b8d090d1bbcd6091e5bba45b34a6a3"
DEFAULT_CONFIG = ROOT / "configs/eight_neighbor_rolling_merge.json"
DEFAULT_OUT = ROOT / "outputs/eight_neighbor_rolling_merge_20261128/local_r1"
OUTPUT_ROOT = ROOT / "outputs/eight_neighbor_rolling_merge_20261128"
SELECTED = ("lake_h2_d1_s3101", "lake_h2_d2_s3201",
            "hudson_h2_d1_s4101", "hudson_h2_d2_s4201")
BASE_METHOD = {"C0": "C0", "C1": "C1", "C0_M": "C0", "C1_M": "C1", "D0": "C0"}
MERGE_MODE = {"C0_M": "exact", "C1_M": "exact", "D0": "shadow"}
PRIMARY = "heading_square"
STAGES = ("D0", "F30")
TESTS = ("tests/test_physical_model.py", "tests/test_physical_search.py",
         "tests/test_physical_accel.py", "tests/test_physical_refinement.py",
         "tests/test_physical_rolling.py", "tests/test_eight_neighbor_rolling_runner.py",
         "tests/test_physical_state_merge.py", "tests/test_eight_neighbor_rolling_merge_runner.py")
MERGE_COUNTS = ("nonterminal_children", "mergeable_children", "discarded_children",
                "equal_J_duplicates", "higher_J_duplicates", "replaced_entries",
                "pop_checks", "stale_pop_candidates", "stale_pops", "capacity_skips",
                "entries", "entries_peak", "payload_bytes", "payload_bytes_peak")

_spec = importlib.util.spec_from_file_location(
    "_rolling_merge_frozen_auditors", ROOT / "scripts/run_eight_neighbor_rolling.py")
_legacy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_legacy)
read, save, digest = _legacy.read, _legacy.save, _legacy.digest
object_digest, stamp, rooted = _legacy.object_digest, _legacy.stamp, _legacy.rooted
environment, child_environment = _legacy.environment, _legacy.child_environment
verify_files, verify_git_blobs = _legacy.verify_files, _legacy.verify_git_blobs
finite_number, validate_score = _legacy.finite_number, _legacy.validate_score
assert_local_project_modules = _legacy.assert_local_project_modules
failure_safe, csv_output = _legacy.failure_safe, _legacy.csv_output
exclusive_run, representative = _legacy.exclusive_run, _legacy.representative


def check_config(config):
    if object_digest(config) != REGISTERED_CONFIG_HASH:
        raise ValueError("Unregistered merging-study configuration; use a new protocol for changes")
    if (config["base_commit"] != BASE_COMMIT or config["study_base_commit"] != STUDY_BASE_COMMIT
            or tuple(config["instances"]) != SELECTED
            or config["methods"] != ["C0", "C1", "C0_M", "C1_M"]
            or config["objective"]["connectivity"] != 8
            or config["objective"]["footprint"] != PRIMARY
            or config["search"]["seconds"] != 30.0
            or config["search"]["repetitions"] != 3):
        raise ValueError("Study identity differs from the registered design")
    for stage, methods, repetitions, count in (
            ("D0", ["D0"], 1, 4), ("F30", ["C0", "C1", "C0_M", "C1_M"], 3, 48)):
        spec = config["stages"][stage]
        if (spec["methods"] != methods or spec["repetitions"] != repetitions
                or spec["seconds"] != 30 or spec["tasks"] != count):
            raise ValueError("Stage identity or budget changed")
    return config


def output_path(path):
    result = Path(path).resolve()
    if not result.is_relative_to(OUTPUT_ROOT.resolve()):
        raise ValueError("Use a fresh directory under outputs/eight_neighbor_rolling_merge_20261128")
    return result


def plan(config):
    check_config(config)
    return dict(status="prepared_not_run", study_base_commit=STUDY_BASE_COMMIT,
        instances=list(SELECTED), stages=config["stages"], D0_algorithm_budget_s=120.0,
        F30_conditional_algorithm_budget_s=1440.0, maximum_algorithm_budget_s=1560.0,
        D0_gate=config["diagnostic_gate"], merging=config["merging"],
        comparisons=config["comparisons"], continuation=config["continuation"],
        data_role=config["data_role"], C0_slots_s=[30.0], C1_slots_s=[6.0] * 5,
        budget_scope="all method computation, including index; loading and independent audit separate",
        inference_scope="seen development cases; shadow admission is not a performance result")


def source_inventory(config_path):
    paths = set()
    for folder in ("src", "scripts", "tests"):
        paths.update((ROOT / folder).rglob("*.py"))
    paths.update((ROOT / "configs").glob("*.json"))
    paths.update(ROOT.glob("requirements*.txt"))
    for name in ("pyproject.toml", "README.md"):
        if (ROOT / name).is_file():
            paths.add(ROOT / name)
    for folder in ("eight_neighbor_rolling", "eight_neighbor_rolling_merge"):
        paths.update(path for path in (ROOT / "docs" / folder).rglob("*")
                     if path.is_file() and path.suffix in {".md", ".json", ".py"})
    paths.add(Path(config_path))
    required = (
        "scripts/run_eight_neighbor_rolling.py", "scripts/run_eight_neighbor_rolling_merge.py",
        "src/asar_repro/physical_state_merge.py", "src/asar_repro/physical_merge_solver.py",
        "src/asar_repro/physical_rolling_merge.py", *TESTS)
    if any(not (ROOT / name).is_file() for name in required):
        raise ValueError("Incomplete source checkout or local validation tests")
    return dict(sorted((p.relative_to(ROOT).as_posix(), digest(p)) for p in paths if p.is_file()))


def reference_evidence(config, *, load_archives=False):
    manifest = read(rooted(config["reference_manifest"]))
    required = {
        "src/asar_repro/physical_rolling.py", "src/asar_repro/physical_rolling_solver.py",
        "scripts/run_eight_neighbor_rolling.py", "configs/eight_neighbor_rolling.json"}
    if (manifest.get("study_base_commit") != STUDY_BASE_COMMIT
            or not required.issubset(manifest.get("files", {}))):
        raise ValueError("New manifest does not protect the reviewed pilot implementation")
    # The inherited routine still checks its original base and all archive/seed semantics.
    evidence = _legacy.reference_evidence(config, load_archives=load_archives)
    evidence["study_base_commit"] = STUDY_BASE_COMMIT
    return evidence


def preflight(config_path, out):
    config = check_config(read(config_path))
    evidence = reference_evidence(config, load_archives=True)
    sources, env = source_inventory(config_path), environment()
    if any(env["packages"][key] == "not_installed" for key in ("numpy", "scipy", "pytest", "psutil", "pyproj")):
        raise ValueError("Use the existing H2 runtime with its required dependencies")
    payload = dict(status="ready_for_local_validation", config_sha256=digest(config_path),
        source_sha256=sources, environment=env, references=evidence, design=plan(config))
    path = out / "preflight.json"
    if path.exists():
        if read(path) != payload:
            raise ValueError("Changed preflight; retain this directory and prepare a new one")
    else:
        save(path, payload)
    print("Four original inputs and seeds verified. No D0 or F30 search was run.")


def verify_preflight(config_path, out):
    pre = read(out / "preflight.json")
    config = check_config(read(config_path))
    if (pre["config_sha256"] != digest(config_path)
            or pre["source_sha256"] != source_inventory(config_path)
            or pre["environment"] != environment()):
        raise ValueError("Code, config or environment changed after preflight")
    verify_files(pre["references"]["files"])
    verify_git_blobs(pre["references"]["git_blobs"])
    if reference_evidence(config)["references"] != pre["references"]["references"]:
        raise ValueError("Common initial routes changed")
    return pre


def validate(config_path, out):
    if (out / "protocol.json").exists() or (out / "runs").exists():
        raise ValueError("Validation must precede freeze and both experiment stages")
    pre = verify_preflight(config_path, out)
    folder = out / "validation" / stamp()
    folder.mkdir(parents=True, exist_ok=False)
    xml = folder / "pytest.xml"
    command = [sys.executable, "-m", "pytest", "-q", *TESTS, f"--junitxml={xml}"]
    with (folder / "stdout.log").open("x", encoding="utf-8") as stdout, (folder / "stderr.log").open("x", encoding="utf-8") as stderr:
        completed = subprocess.run(command, cwd=ROOT, env=child_environment(), stdout=stdout, stderr=stderr, check=False)
    cases = ET.parse(xml).getroot().findall(".//testcase") if xml.is_file() else []
    bad = sum(any(item.find(tag) is not None for tag in ("failure", "error", "skipped")) for item in cases)
    unchanged = pre["source_sha256"] == source_inventory(config_path) and pre["environment"] == environment()
    passed = completed.returncode == 0 and bool(cases) and bad == 0 and unchanged
    result = dict(status="passed" if passed else "failed", command=command, paths=list(TESTS),
        returncode=completed.returncode, testcase_count=len(cases), bad_or_skipped_count=bad,
        unchanged=unchanged, source_sha256=pre["source_sha256"], environment=pre["environment"],
        xml_sha256=digest(xml) if xml.is_file() else None)
    save(folder / "result.json", result)
    save(out / "validation/latest.json", dict(path=(folder / "result.json").relative_to(out).as_posix(),
        sha256=digest(folder / "result.json")), replace=True)
    if not passed:
        raise ValueError("Local tests failed; all evidence retained")
    print(f"Local validation passed: {len(cases)} tests. No D0/F30 task has run.")


def check_validation(out, ref, sources, env):
    path = out / ref["path"]
    result = read(path)
    if (digest(path) != ref["sha256"] or result["status"] != "passed"
            or result["returncode"] != 0 or result["testcase_count"] <= 0
            or result["bad_or_skipped_count"] != 0 or not result["unchanged"]
            or result["paths"] != list(TESTS) or result["source_sha256"] != sources
            or result["environment"] != env or digest(path.with_name("pytest.xml")) != result["xml_sha256"]):
        raise ValueError("Passing local tests do not bind the frozen code and runtime")


def task_id(task):
    if task["stage"] not in STAGES:
        raise ValueError("Unregistered task stage")
    return task["stage"] + "_" + object_digest(task)[:20]


def make_tasks(config, evidence, stage):
    if stage not in STAGES:
        raise ValueError("Stage must be D0 or F30")
    spec, tasks = config["stages"][stage], []
    for identity in SELECTED:
        case = evidence["instances"][identity]
        for method in spec["methods"]:
            for repetition in range(spec["repetitions"]):
                tasks.append(dict(stage=stage, instance=identity, base_scene=case["base_scene"],
                    block_id=case["block_id"], seed=case["seed"], method=method, repetition=repetition,
                    seconds=spec["seconds"], connectivity=8, footprint=PRIMARY,
                    manifest_sha256=evidence["archive_hashes"][identity]["manifest_sha256"],
                    reference_sha256=object_digest(evidence["references"][identity])))
    random.Random(config["task_order_seed"] + STAGES.index(stage)).shuffle(tasks)
    return tasks


def freeze(config_path, out):
    if (out / "protocol.json").exists():
        verify_protocol(config_path, out)
        print("Existing two-stage frozen protocol verified")
        return
    if (out / "runs").exists() or (out / "D0_gate.json").exists():
        raise ValueError("Cannot freeze after experiment evidence exists")
    pre = verify_preflight(config_path, out)
    config = check_config(read(config_path))
    validation = read(out / "validation/latest.json")
    check_validation(out, validation, pre["source_sha256"], pre["environment"])
    tasks = {stage: make_tasks(config, pre["references"], stage) for stage in STAGES}
    for stage in STAGES:
        save(out / "tasks" / f"{stage}.json", tasks[stage])
    save(out / "protocol.json", dict(status="frozen_before_D0", created_utc=datetime.now(timezone.utc).isoformat(),
        config=config, config_sha256=digest(config_path), source_sha256=pre["source_sha256"],
        environment=pre["environment"], references=pre["references"], validation=validation,
        preflight_sha256=digest(out / "preflight.json"),
        tasks_sha256={stage: object_digest(tasks[stage]) for stage in STAGES}, design=plan(config)))
    print("Frozen 4 D0 and 48 conditional F30 tasks. Run D0 first; F30 requires its frozen passing gate.")


def verify_protocol(config_path, out):
    protocol = read(out / "protocol.json")
    config = check_config(read(config_path))
    if (protocol["status"] != "frozen_before_D0" or protocol["config"] != config
            or protocol["config_sha256"] != digest(config_path)
            or protocol["source_sha256"] != source_inventory(config_path)
            or protocol["environment"] != environment()
            or protocol["preflight_sha256"] != digest(out / "preflight.json")):
        raise ValueError("Frozen code, configuration, preflight or runtime changed")
    verify_files(protocol["references"]["files"])
    verify_git_blobs(protocol["references"]["git_blobs"])
    check_validation(out, protocol["validation"], protocol["source_sha256"], protocol["environment"])
    tasks = {stage: read(out / "tasks" / f"{stage}.json") for stage in STAGES}
    for stage in STAGES:
        if (object_digest(tasks[stage]) != protocol["tasks_sha256"][stage]
                or tasks[stage] != make_tasks(config, protocol["references"], stage)):
            raise ValueError("Frozen stage task identities or order changed")
    return protocol, tasks


def validate_merge_evidence(raw, variant, config):
    if variant in ("C0", "C1"):
        if raw.get("variant") is not None or raw.get("merging") is not None:
            raise ValueError("A control was not produced by the unchanged pilot wrapper")
        return
    expected = dict(config["merging"], mode=MERGE_MODE[variant])
    if raw.get("variant") != variant or raw.get("merging") != expected:
        raise ValueError("Variant or exact index policy differs from registration")
    for phase in raw["phases"]:
        inner = phase.get("inner")
        if inner is None:
            continue
        stats = inner.get("state_merge")
        if (not isinstance(stats, dict) or stats.get("mode") != MERGE_MODE[variant]
                or stats.get("max_entries") != config["merging"]["max_entries"]
                or stats.get("max_payload_bytes") != config["merging"]["max_payload_bytes"]):
            raise ValueError("Missing or changed per-call state-merge evidence")
        if any(isinstance(stats.get(key), bool) or not isinstance(stats.get(key), int)
               or stats[key] < 0 for key in MERGE_COUNTS):
            raise ValueError("Invalid state-merge counter")
        if (stats["mergeable_children"] > stats["nonterminal_children"]
                or stats["equal_J_duplicates"] + stats["higher_J_duplicates"] != stats["mergeable_children"]
                or stats["discarded_children"] > stats["mergeable_children"]
                or stats["stale_pops"] > stats["stale_pop_candidates"]
                or stats["stale_pop_candidates"] > stats["pop_checks"]
                or not stats["entries"] <= stats["entries_peak"] <= stats["max_entries"]
                or not stats["payload_bytes"] <= stats["payload_bytes_peak"] <= stats["max_payload_bytes"]):
            raise ValueError("State-merge counters or storage limits are inconsistent")
        if (not finite_number(stats.get("lookup_s")) or not finite_number(stats.get("key_build_s"))
                or not 0 <= stats["key_build_s"] <= stats["lookup_s"] + 1e-8):
            raise ValueError("State-merge charged-time evidence is invalid")
        if variant == "D0" and (stats["discarded_children"] != 0 or stats["stale_pops"] != 0):
            raise ValueError("Shadow diagnostic changed search through pruning")


def verify_result(task, result, protocol):
    variant = task["method"]
    spec = protocol["config"]["stages"].get(task["stage"])
    if (spec is None or variant not in spec["methods"]
            or result["method"] != variant or result["raw"]["method"] != BASE_METHOD[variant]):
        raise ValueError("Outer variant or underlying pilot method does not match task")
    validate_merge_evidence(result["raw"], variant, protocol["config"])
    # Only identity labels are adapted. Original score, clocks, history, budgets,
    # prefixes, source base and independent audit evidence are passed unchanged.
    mapped_task = dict(task, method=BASE_METHOD[variant])
    mapped_result = dict(result, method=BASE_METHOD[variant])
    _legacy.verify_result(mapped_task, mapped_result, protocol)


def diagnostic_gate(config, rows, *, complete):
    seen, metrics = [], []
    for row in rows:
        task, raw = row["task"], row["result"]["raw"]
        key = (task["instance"], task["method"], task["repetition"], task["stage"])
        seen.append(key)
        if task["method"] != "D0" or task["stage"] != "D0":
            complete = False
            continue
        validate_merge_evidence(raw, "D0", config)
        stats = [phase["inner"]["state_merge"] for phase in raw["phases"] if phase.get("inner") is not None]
        total = sum(item["nonterminal_children"] for item in stats)
        count = sum(item["mergeable_children"] for item in stats)
        fraction = count / total if total else 0.0
        rules = config["diagnostic_gate"]
        qualifies = (count >= rules["minimum_mergeable_children"]
                     and fraction >= rules["minimum_mergeable_fraction"])
        metrics.append(dict(instance=task["instance"], run_id=row["run_id"],
            nonterminal_children=total, mergeable_children=count, mergeable_fraction=fraction,
            qualifies=qualifies, capacity_skips=sum(item["capacity_skips"] for item in stats),
            lookup_s=sum(item["lookup_s"] for item in stats)))
    expected = {(identity, "D0", 0, "D0") for identity in SELECTED}
    valid = complete and len(seen) == 4 and set(seen) == expected
    passed = valid and sum(item["qualifies"] for item in metrics) >= config["diagnostic_gate"]["minimum_qualifying_instances"]
    return dict(status=("D0_admitted" if passed else "D0_not_admitted") if valid else "incomplete_or_invalid",
        all_instances_valid=valid, passed=passed, qualifying_instances=sum(item["qualifies"] for item in metrics),
        instances=sorted(metrics, key=lambda item: SELECTED.index(item["instance"])),
        scope="shadow duplicate opportunity; not active speed, quality, or optimality evidence")


def frozen_evidence(out, task):
    evidence = dict(protocol_sha256=digest(out / "protocol.json"))
    if task["stage"] == "F30":
        evidence["D0_gate_sha256"] = digest(out / "D0_gate.json")
    return evidence


def load_record(out, task, protocol):
    folder = out / "runs" / task_id(task)
    if not folder.exists():
        return None
    if not (folder / "record.json").is_file() or not (folder / "result.json").is_file():
        raise ValueError(f"Incomplete run retained: {folder.name}; no automatic retry")
    record, payload = read(folder / "record.json"), read(folder / "result.json")
    if (record["status"] != "completed" or record["returncode"] != 0 or record["watchdog"] is not None
            or record.get("verification_error") is not None
            or record["task"] != task or payload["task"] != task or read(folder / "task.json") != task
            or record["frozen_evidence"] != frozen_evidence(out, task)
            or record["result_sha256"] != digest(folder / "result.json")):
        raise ValueError(f"Failed or altered run retained: {folder.name}")
    verify_result(task, payload["result"], protocol)
    return dict(task=task, result=payload["result"], record=record, run_id=task_id(task))


def collect(out, tasks, protocol, stage):
    rows, missing, errors = [], [], []
    registered = {task_id(task) for entries in tasks.values() for task in entries}
    if (out / "runs").exists():
        extra = sorted(p.name for p in (out / "runs").iterdir() if p.is_dir() and p.name not in registered)
        errors.extend(dict(run_id=name, error="unregistered_run_directory") for name in extra)
    for task in tasks[stage]:
        try:
            row = load_record(out, task, protocol)
            if row is None:
                missing.append(task_id(task))
            else:
                rows.append(row)
        except (OSError, KeyError, ValueError, TypeError) as error:
            errors.append(dict(run_id=task_id(task), error=str(error)))
    return dict(status="complete" if not missing and not errors else "incomplete_or_invalid",
        planned=len(tasks[stage]), valid=len(rows), missing=missing, errors=errors), rows


def gate_payload(out, config, status, rows):
    return dict(schema_version=1, protocol_sha256=digest(out / "protocol.json"),
        decision=diagnostic_gate(config, rows, complete=status["status"] == "complete"),
        raw_evidence={row["run_id"]: row["record"]["result_sha256"] for row in rows})


def require_d0_gate(out, protocol, tasks):
    status, rows = collect(out, tasks, protocol, "D0")
    expected = gate_payload(out, protocol["config"], status, rows)
    path = out / "D0_gate.json"
    if not path.is_file() or read(path) != expected or not expected["decision"]["passed"]:
        raise ValueError("F30 blocked: all four valid D0 records and their frozen passing gate are required")
    return expected


def worker(config_path, out, task_path, result_path):
    protocol, tasks = verify_protocol(config_path, out)
    task = read(task_path)
    folder = out / "runs" / task_id(task)
    if (task not in tasks.get(task["stage"], []) or task_path != folder / "task.json"
            or result_path != folder / "result.json"):
        raise ValueError("Worker request is not a registered D0/F30 task")
    if task["stage"] == "F30":
        require_d0_gate(out, protocol, tasks)
    config = protocol["config"]
    if (any(os.environ.get(key) != value for key, value in config["thread_environment"].items())
            or os.environ.get("PYTHONHASHSEED") != "0"):
        raise ValueError("Use the registered single-thread worker launcher")
    from asar_repro.h2_inputs import load_h2_input
    from asar_repro.physical_rolling import run_physical_rolling
    from asar_repro.physical_rolling_merge import run_physical_rolling_merge
    assert_local_project_modules()
    reference = protocol["references"]["references"][task["instance"]]
    case = protocol["references"]["instances"][task["instance"]]
    load_started = time.perf_counter()
    problem, _, _, info = load_h2_input(ROOT, case, rooted(config["source_root"]) / "inputs" / case["id"], PRIMARY)
    load_s = time.perf_counter() - load_started
    if (info["manifest_sha256"] != task["manifest_sha256"] or problem.q != config["objective"]["q"]
            or problem.speed_m_s != config["objective"]["speed_m_s"]):
        raise ValueError("Loaded input differs from frozen task")
    started, cpu, raw = time.perf_counter(), time.process_time(), None
    try:
        options = dict(method=task["method"], initial_waypoints=reference["waypoints"],
            total_seconds=task["seconds"], triggers=config["search"]["triggers"],
            anchor_guard_s=config["search"]["anchor_guard_s"],
            solver_reserve_s=config["search"]["solver_reserve_s"], solver_options=config["solver"])
        if task["method"] in ("C0", "C1"):
            raw = run_physical_rolling(problem, **options)
        else:
            raw = run_physical_rolling_merge(problem, **options,
                merge_max_entries=config["merging"]["max_entries"],
                merge_max_payload_bytes=config["merging"]["max_payload_bytes"])
        wall, cpu_s = time.perf_counter() - started, time.process_time() - cpu
        audit_started = time.perf_counter()
        if raw.get("error") is not None or raw.get("status") != "completed":
            raise ValueError(f"Method failed: {raw.get('error')}")
        replay = problem.replay(raw["waypoints"], connectivity=8)
        execution_audit = _legacy.audit_execution(problem, raw, reference, config["decision"]["score_absolute"])
        audit_s = time.perf_counter() - audit_started
        result = dict(status="valid", method=task["method"], J=replay["J"], pd_final=replay["pd_final"],
            physical_replay=replay, raw=raw, inputs=info, environment=environment(), execution_audit=execution_audit,
            reference_sha256=object_digest(reference), formal_optimality_certificate=False,
            algorithm_wall_s=wall, algorithm_cpu_s=cpu_s, input_load_s=load_s, independent_audit_s=audit_s,
            audit_scope="unchanged independent original-model validation; never selects a candidate")
        verify_result(task, result, protocol)
        assert_local_project_modules()
        verify_protocol(config_path, out)
        if task["stage"] == "F30":
            require_d0_gate(out, protocol, tasks)
        save(result_path, dict(task=task, result=result))
    except BaseException as error:
        save(folder / "failure_result.json", failure_safe(dict(status="failed", task=task, raw=raw,
            error=str(error), traceback=traceback.format_exc(), elapsed_s=time.perf_counter() - started)))
        raise


def launch_task(config_path, out, task, protocol):
    import psutil
    if load_record(out, task, protocol) is not None:
        print(f"Verified existing {task_id(task)}", flush=True)
        return
    folder = out / "runs" / task_id(task)
    folder.mkdir(parents=True, exist_ok=False)
    save(folder / "task.json", task)
    result_path = folder / "result.json"
    command = [sys.executable, str(Path(__file__).resolve()), "_worker", "--config", str(config_path),
        "--out", str(out), "--task", str(folder / "task.json"), "--result", str(result_path)]
    policy = protocol["config"]["watchdog"]
    started, peak, killed = time.perf_counter(), 0, None
    with (folder / "stdout.log").open("x", encoding="utf-8") as stdout, (folder / "stderr.log").open("x", encoding="utf-8") as stderr:
        child = subprocess.Popen(command, cwd=ROOT, env=child_environment(), stdout=stdout, stderr=stderr)
        relatives = []
        try:
            process = psutil.Process(child.pid)
            while child.poll() is None:
                try:
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
        finally:
            if killed and child.poll() is None:
                for relative in reversed(relatives):
                    try:
                        relative.kill()
                    except psutil.NoSuchProcess:
                        pass
                child.kill()
            returncode = child.wait()
    result_sha = digest(result_path) if result_path.is_file() else None
    valid, failure = returncode == 0 and killed is None and result_sha is not None, None
    if valid:
        try:
            payload = read(result_path)
            if payload["task"] != task:
                raise ValueError("Worker task identity changed")
            verify_result(task, payload["result"], protocol)
        except (OSError, KeyError, ValueError, TypeError) as error:
            valid, failure = False, str(error)
    save(folder / "record.json", dict(task=task, command=command, status="completed" if valid else "failed",
        returncode=returncode, watchdog=killed, verification_error=failure,
        process_wall_s=time.perf_counter() - started, peak_rss_bytes=peak,
        result_sha256=result_sha, frozen_evidence=frozen_evidence(out, task)))
    if not valid:
        raise RuntimeError(f"Failed task retained at {folder}; stopped without retry")
    print(f"Completed {task_id(task)}", flush=True)


def run(config_path, out, stage):
    protocol, tasks = verify_protocol(config_path, out)
    if stage == "F30":
        require_d0_gate(out, protocol, tasks)
    with exclusive_run(out):
        for task in tasks[stage]:
            launch_task(config_path, out, task, protocol)
    analyze(config_path, out, stage)


def decision(config, rows, *, complete):
    expected = {(identity, method, repetition) for identity in SELECTED
                for method in config["methods"] for repetition in range(3)}
    seen, groups = [], defaultdict(list)
    try:
        for row in rows:
            task, result = row["task"], row["result"]
            key = (task["instance"], task["method"], task["repetition"])
            seen.append(key)
            if (task["stage"] != "F30" or task["seconds"] != 30 or task["connectivity"] != 8
                    or task["footprint"] != PRIMARY
                    or task["base_scene"] != ("lake_ontario" if task["instance"].startswith("lake_") else "arctic_ocean")
                    or not all(finite_number(result[name]) for name in ("J", "pd_final"))
                    or result["J"] <= 0 or not 0 <= result["pd_final"] <= 1):
                raise ValueError("Invalid decision row")
            groups[key[:2]].append(row)
        if not complete or len(seen) != len(expected) or set(seen) != expected:
            raise ValueError("Incomplete or duplicate four-arm matrix")
    except (KeyError, TypeError, ValueError):
        return dict(status="incomplete_or_invalid", rolling_candidate_continue=False, pair_gates={})
    rules, gates = config["decision"], {}
    for comparison in config["comparisons"]:
        control, candidate = comparison["control"], comparison["candidate"]
        pairs, regions = [], Counter()
        for identity in SELECTED:
            a, b = (representative(groups[identity, method]) for method in (control, candidate))
            J0, J1 = a["result"]["J"], b["result"]["J"]
            gain = (J0 - J1) / J0
            dpd = b["result"]["pd_final"] - a["result"]["pd_final"]
            winner = gain >= rules["instance_winner_min"]
            region = a["task"]["base_scene"]
            if winner:
                regions[region] += 1
            pairs.append(dict(comparison=comparison["id"], instance=identity, base_scene=region,
                control=control, candidate=candidate, J_control=J0, J_candidate=J1, relative_J_gain=gain,
                pd_control=a["result"]["pd_final"], pd_candidate=b["result"]["pd_final"],
                delta_pd_percentage_points=100 * dpd, winner=winner,
                J_regression=gain < -rules["relative_tolerance"], pd_drop_flag=dpd < -rules["max_pd_drop"],
                control_run_id=a["run_id"], candidate_run_id=b["run_id"],
                control_J_range=[min(x["result"]["J"] for x in groups[identity, control]),
                                 max(x["result"]["J"] for x in groups[identity, control])],
                candidate_J_range=[min(x["result"]["J"] for x in groups[identity, candidate]),
                                   max(x["result"]["J"] for x in groups[identity, candidate])]))
        protected = not any(x["J_regression"] for x in pairs)
        pd_protected = not any(x["pd_drop_flag"] for x in pairs)
        winners = sum(x["winner"] for x in pairs)
        passed = (protected and pd_protected and winners >= rules["min_instance_winners"]
                  and all(regions[r] >= rules["min_winners_per_scene"] for r in ("lake_ontario", "arctic_ocean")))
        gates[comparison["id"]] = dict(screen_passed=passed, role=comparison["role"],
            quality_protected=protected, pd_protected=pd_protected, instance_winners=winners,
            winners_by_scene=dict(regions), median_relative_J_gain=median(x["relative_J_gain"] for x in pairs),
            comparisons=pairs)
    continuation = all(gates[name]["screen_passed"] for name in config["continuation"]["required_pair_gates"])
    return dict(status="rolling_merge_development_screen_passed" if continuation else "rolling_merge_development_screen_not_passed",
        rolling_candidate_continue=continuation, pair_gates=gates,
        inference_scope="four seen date/seed cases; merging gains alone do not establish rolling gains or speedup")


def derived_rows(rows):
    comparisons, survival, phases, merges, histories = [], [], [], [], []
    common = ["run_id", "stage", "instance", "base_scene", "method", "repetition"]
    for row in rows:
        task, result = row["task"], row["result"]
        base = dict(run_id=row["run_id"], **{key: task[key] for key in common if key != "run_id"})
        comparisons.append(dict(base, J=result["J"], pd_final=result["pd_final"],
            algorithm_wall_s=result["algorithm_wall_s"], algorithm_cpu_s=result["algorithm_cpu_s"],
            active_compute_s=result["raw"]["active_compute_s"], process_wall_s=row["record"]["process_wall_s"],
            peak_rss_bytes=row["record"]["peak_rss_bytes"], input_load_s=result["input_load_s"],
            independent_audit_s=result["independent_audit_s"],
            deadline_overshoot_s=result["raw"].get("deadline_overshoot_s", 0.0)))
        score = result["physical_replay"]
        for tick, (at, mass) in enumerate(zip([0.0] + score["observation_times_s"], score["survival"])):
            survival.append(dict(base, tick=tick, time_s=at, remaining_mass=mass, pd_by_time=1 - mass))
        K = len(score["observation_times_s"])
        for phase in result["raw"]["phases"]:
            phases.append(dict(base, **{key: value for key, value in phase.items()
                                       if key not in {"raw", "inner", "inner_raw"}}))
            inner = phase.get("inner")
            if inner is None:
                continue
            expanded = inner["expanded"]
            histogram = inner["diagnostics"]["histograms"]["expanded_tick"]
            tail = sum(count for tick, count in histogram.items() if int(tick) >= K - 2)
            merge = inner.get("state_merge", {"mode": "off"})
            merges.append(dict(base, stage_index=phase["stage_index"], **merge,
                expanded=expanded, terminal_candidates=inner["stats"]["terminal_candidates"],
                final_two_tick_expanded=tail, final_two_tick_fraction=tail / expanded if expanded else 0.0,
                guide_s=inner["timings"]["guide_s"], transition_s=inner["timings"]["transition_s"],
                inner_stop_reason=inner["stop_reason"], accepted=phase["accepted"]))
            for entry in inner["history"]:
                histories.append(dict(base, stage_index=phase["stage_index"], inner_elapsed_s=entry["elapsed_s"],
                    source=entry["source"], J=entry["J"], pd_final=entry["pd_final"],
                    phase_accepted=phase["accepted"],
                    scope="inner incumbent diagnostic; not operational candidate availability or time-to-target"))
    return common, dict(comparison=comparisons, survival=survival, phases=phases,
                        merge_diagnostics=merges, incumbent_history=histories)


def analyze(config_path, out, stage):
    protocol, tasks = verify_protocol(config_path, out)
    if stage == "F30":
        require_d0_gate(out, protocol, tasks)
    status, rows = collect(out, tasks, protocol, stage)
    config = protocol["config"]
    conclusion = (diagnostic_gate(config, rows, complete=status["status"] == "complete") if stage == "D0"
                  else decision(config, rows, complete=status["status"] == "complete"))
    if stage == "D0" and status["status"] == "complete":
        gate = gate_payload(out, config, status, rows)
        path = out / "D0_gate.json"
        if path.exists():
            if read(path) != gate:
                raise ValueError("Frozen D0 gate or its raw evidence changed")
        else:
            save(path, gate)
    folder = out / stage
    common, derived = derived_rows(rows)
    for name, entries in derived.items():
        extra = sorted(set().union(*(entry.keys() for entry in entries)) - set(common)) if entries else []
        csv_output(folder / f"{name}.csv", entries, common + extra)
    pairs = [pair for gate in conclusion.get("pair_gates", {}).values() for pair in gate["comparisons"]]
    fields = ["comparison", "instance", "base_scene", "control", "candidate", "J_control", "J_candidate",
        "relative_J_gain", "pd_control", "pd_candidate", "delta_pd_percentage_points", "winner", "J_regression",
        "pd_drop_flag", "control_run_id", "candidate_run_id", "control_J_range", "candidate_J_range"]
    csv_output(folder / "instance_comparison.csv", pairs, fields)
    summary = dict(stage=stage, status=status, decision=conclusion, protocol_sha256=digest(out / "protocol.json"),
        data_role=config["data_role"], formal_optimality_certificate=False, speedup_claim=False,
        total_algorithm_wall_s=sum(row["result"]["algorithm_wall_s"] for row in rows),
        raw_evidence={row["run_id"]: row["record"]["result_sha256"] for row in rows},
        derived_file_sha256={f"{name}.csv": digest(folder / f"{name}.csv")
                            for name in [*derived, "instance_comparison"]})
    if stage == "F30":
        summary["D0_gate_sha256"] = digest(out / "D0_gate.json")
    save(folder / "summary.json", summary, replace=True)
    lines = ["# 精确状态合并与滚动规划：阶段结果", "",
        f"阶段：{stage}。有效性：{status['status']}。判定：{conclusion['status']}。", "",
        "四例均为已见开发数据。此报告只汇总完整原始记录；ANALYSIS.md 不会被覆盖。", ""]
    if stage == "D0":
        lines += ["| 实例 | 可合并 child | 分母 child | 比例 | 达到门槛 |",
                  "|---|---:|---:|---:|---|"]
        for item in conclusion["instances"]:
            lines.append(f"| {item['instance']} | {item['mergeable_children']} | {item['nonterminal_children']} | {item['mergeable_fraction']:.4%} | {item['qualifies']} |")
        lines += ["", "只有完整 D0 的冻结 gate 通过，才可运行 F30。容量达到限制后的计数可能低估机会。",
                  "shadow 不丢弃状态，不是加速结果；lookup_s 已包含 key_build_s，二者不可相加。"]
    else:
        lines += ["| 对比 | 通过 | 达到 0.5% 的实例数 | J 无退化 | Pd 护栏 |",
                  "|---|---|---:|---|---|"]
        for name, gate in conclusion.get("pair_gates", {}).items():
            lines.append(f"| {name} | {gate['screen_passed']} | {gate['instance_winners']} | {gate['quality_protected']} | {gate['pd_protected']} |")
        lines += ["", "滚动候选继续条件：C1_M/C0_M 与 C1_M/C0 均通过原质量门槛。",
                  "仅通用合并对比改善不能归因为滚动净收益。内层 incumbent 时间仅作诊断，不作同质量加速证明。"]
    (folder / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(dict(stage=stage, status=status["status"], decision=conclusion["status"], valid=status["valid"]), ensure_ascii=False))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "preflight", "validate", "freeze", "run", "analyze", "_worker"))
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--stage", choices=STAGES)
    parser.add_argument("--task", type=Path)
    parser.add_argument("--result", type=Path)
    args = parser.parse_args(argv)
    config_path, out = args.config.resolve(), output_path(args.out)
    config = check_config(read(config_path))
    if args.action == "plan":
        print(json.dumps(plan(config), ensure_ascii=False, indent=2))
        return
    if args.action in ("run", "analyze") and args.stage is None:
        parser.error("run/analyze requires --stage D0 or --stage F30")
    if args.action not in ("run", "analyze") and args.stage is not None:
        parser.error("--stage applies only to run and analyze")
    out.mkdir(parents=True, exist_ok=True)
    if args.action == "_worker":
        if args.task is None or args.result is None:
            parser.error("worker requires --task and --result")
        worker(config_path, out, args.task.resolve(), args.result.resolve())
        return
    started = time.perf_counter()
    record = dict(action=args.action, stage=args.stage,
        command=[sys.executable, str(Path(__file__).resolve()), *(argv if argv is not None else sys.argv[1:])],
        started_utc=datetime.now(timezone.utc).isoformat(), status="running")
    log = out / "commands" / f"{stamp()}-{args.action}.json"
    try:
        if args.action in ("run", "analyze"):
            {"run": run, "analyze": analyze}[args.action](config_path, out, args.stage)
        else:
            {"preflight": preflight, "validate": validate, "freeze": freeze}[args.action](config_path, out)
        record["status"] = "completed"
    except BaseException as error:
        record.update(status="failed", error=str(error), traceback=traceback.format_exc())
        raise
    finally:
        record["wall_s"] = time.perf_counter() - started
        save(log, record)


if __name__ == "__main__":
    main()
