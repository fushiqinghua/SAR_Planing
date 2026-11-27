#!/usr/bin/env python3
"""Local-only, preregistered physical-search diagnostics. Delivered not_run.

The previously observed H1 archives are development data here. No downloader,
drift generation, H2 search, parameter sweep or automatic retry is enabled.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import csv
import json
import math
from pathlib import Path
import random
import statistics
import subprocess
import sys
import time
import traceback
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
import run_eight_neighbor_followup as followup
import run_eight_neighbor_physical as previous
import run_solver_paradigm_study as common

read, save, digest = common.read, common.save, common.digest
object_digest = common.object_digest
DEFAULT_CONFIG = ROOT / "configs/eight_neighbor_confirmation.json"
OUTPUT_ROOT = ROOT / "outputs/eight_neighbor_confirmation_20261127"
REGISTERED_CONFIG_HASH = "07e99d7ecedb454d6274f820bf57c2efc6ea8391f82bcad0a8a7daa615fa8660"
STAGES = ("D5", "D30", "G30", "R120")


def stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def check_config(config):
    if object_digest(config) != REGISTERED_CONFIG_HASH:
        raise ValueError("Registered configuration changed; prepare a separately labelled study")
    if sys.version_info < (3, 11):
        raise ValueError("Python 3.11+ is required")
    if object_digest(read(ROOT / config["reference_manifest"])) != config["reference_manifest_canonical_sha256"]:
        raise ValueError("Historical reference manifest changed")
    missing = [p for p in config["validation_tests"] if not (ROOT / p).is_file()]
    if missing:
        raise ValueError(f"Missing validation files: {missing}")


def environment():
    return followup.environment()


def source_inventory(config_path):
    result = followup.source_inventory(config_path)
    for path in sorted((ROOT / "docs/eight_neighbor_confirmation").rglob("*")):
        if path.is_file() and path.suffix in (".md", ".json"):
            result[path.relative_to(ROOT).as_posix()] = digest(path)
    result["../README.md"] = digest(REPO / "README.md")
    return dict(sorted(result.items()))


def reference_manifest(config):
    path = ROOT / config["reference_manifest"]
    if object_digest(read(path)) != config["reference_manifest_canonical_sha256"]:
        raise ValueError("Historical reference identity changed")
    return read(path)


def reference_for(config, case, footprint):
    refs = [r for r in reference_manifest(config)["references"]
            if (r["case"], r["footprint"]) == (case, footprint)]
    if len(refs) != 1:
        raise ValueError("Expected exactly one fixed four-neighbor reference")
    return refs[0]


def inspect_references(config, *, load_archives=False):
    manifest = reference_manifest(config)
    old = ROOT / manifest["historical_output_root"]
    pin = manifest["prepared_inputs"]
    if digest(old / pin["path"]) != pin["sha256"]:
        raise ValueError("Historical prepared_inputs.json changed")
    prepared = read(old / pin["path"])
    if prepared["files"] != pin["files"]:
        raise ValueError("Historical input inventory changed")
    for path, expected in pin["files"].items():
        if digest(old / path) != expected:
            raise ValueError(f"Historical input bytes changed or missing: {path}")
    groups = {(g["case"], g["footprint"]) for g in config["d30_groups"]}
    if groups != {(r["case"], r["footprint"]) for r in manifest["references"]}:
        raise ValueError("Reference groups differ from the registered matrix")
    checked = []
    for ref in manifest["references"]:
        result_path, record_path = old / ref["result_path"], old / ref["record_path"]
        if digest(result_path) != ref["result_sha256"] or digest(record_path) != ref["record_sha256"]:
            raise ValueError(f"Fixed reference evidence changed: {ref['run_id']}")
        payload, record = read(result_path), read(record_path)
        task, result = payload["task"], payload["result"]
        if (record["status"] != "completed" or record["returncode"] != 0
                or record["watchdog"] is not None or record["task"] != task
                or record["result_sha256"] != ref["result_sha256"]
                or result["status"] != "valid" or result["backend"] != "cached"
                or task["stage"] != "H30" or task["connectivity"] != 4
                or task["repetition"] != 0 or task["case"] != ref["case"]
                or task["footprint"] != ref["footprint"]):
            raise ValueError("Invalid fixed four-neighbor reference")
        if (result["J"] != ref["J"] or result["pd_final"] != ref["pd_final"]
                or result["physical_replay"]["waypoints"] != ref["waypoints"]
                or object_digest(ref["waypoints"]) != ref["waypoints_sha256"]):
            raise ValueError("Fixed route/score identity changed")
        for key in ("particle_sha256", "metadata_sha256", "manifest_sha256"):
            if result["inputs"][key] != prepared["cases"][ref["case"]][key]:
                raise ValueError("Reference was scored on another input archive")
        item = dict(case=ref["case"], footprint=ref["footprint"], run_id=ref["run_id"],
                    reference_J=ref["J"], reference_pd=ref["pd_final"],
                    waypoints_sha256=ref["waypoints_sha256"])
        if load_archives:
            from asar_repro.physical_followup_data import load_prepared_case
            case = next(c for c in config["cases"] if c["id"] == ref["case"])
            _, _, _, info = load_prepared_case(ROOT, case, old / "inputs" / case["id"], ref["footprint"])
            for key in ("particle_sha256", "metadata_sha256", "manifest_sha256"):
                if info[key] != prepared["cases"][case["id"]][key]:
                    raise ValueError("Loaded input identity mismatch")
            item["input_info"] = info
        checked.append(item)
    return dict(reference_commit=manifest["reference_commit"],
                manifest_sha256=config["reference_manifest_canonical_sha256"],
                prepared_inputs_sha256=pin["sha256"], input_files=len(pin["files"]),
                references=checked, new_drift_generated=False, raw_forcing_required=False,
                data_role=config["dataset_role"])


def task_id(task):
    return task["stage"] + "_" + object_digest(task)[:20]


def tasks_for(config, stage):
    if stage not in STAGES:
        raise ValueError(f"Unregistered stage: {stage}")
    if stage == "D30":
        groups = config["d30_groups"]
    elif stage == "D5":
        groups = [dict(case=c, footprint="heading_square") for c in config["diagnostic_cases"]]
    else:
        case = "lake_window_late" if stage == "G30" else "hudson_window_early"
        groups = [dict(case=case, footprint=f) for f in ("heading_square", "axis_square")]
    methods = (["completion_pd_guard"] if stage == "G30" else ["diagnostic_cached"]
               if stage == "R120" else ["diagnostic_cached", "completion_J"])
    spec = config["stages"][stage]
    tasks = [dict(stage=stage, **group, connectivity=graph, method=method,
                  repetition=rep, seconds=spec["seconds"])
             for group in groups for graph in config["connectivities"] for method in methods
             for rep in range(spec["repetitions"])]
    random.Random(config["task_order_seed"] + sum(map(ord, stage))).shuffle(tasks)
    return tasks


def plan(config):
    stages = {s: dict(tasks=len(tasks_for(config, s)),
                     algorithm_budget_s=sum(t["seconds"] for t in tasks_for(config, s))) for s in STAGES}
    return dict(status="plan_not_results", stages=stages,
                formal_tasks=sum(v["tasks"] for v in stages.values()),
                formal_algorithm_budget_s=sum(v["algorithm_budget_s"] for v in stages.values()),
                data_role=config["dataset_role"], H2=config["H2"],
                initialization=config["initialization"],
                R120="separate restarts, one repetition, quality diagnostics, not an equal-30s comparison",
                excluded_costs="local pytest, input loading, process startup, independent audits and IO")


def preflight(config, config_path, out):
    check_config(config)
    result = dict(status="ready", environment=environment(), source_sha256=source_inventory(config_path),
                  protected_base_sources=previous.protect_base(config),
                  inputs=inspect_references(config, load_archives=True), plan=plan(config))
    folder = out / "preflight" / stamp()
    save(folder / "preflight.json", result)
    save(out / "preflight/latest.json", dict(path=(folder / "preflight.json").relative_to(out).as_posix(),
         sha256=digest(folder / "preflight.json")), replace=True)
    print(f"Preflight ready: {folder}; no search or drift generation", flush=True)


def validate(config, config_path, out):
    check_config(config)
    previous.protect_base(config)
    before, env = source_inventory(config_path), environment()
    folder = out / "validation" / stamp()
    folder.mkdir(parents=True, exist_ok=False)
    xml = folder / "pytest.xml"
    command = [sys.executable, "-m", "pytest", "-q", *config["validation_tests"], f"--junitxml={xml}"]
    with (folder / "stdout.log").open("w", encoding="utf-8") as stdout, \
         (folder / "stderr.log").open("w", encoding="utf-8") as stderr:
        completed = subprocess.run(command, cwd=ROOT, env=common.child_environment(),
                                   stdout=stdout, stderr=stderr, check=False)
    cases = ET.parse(xml).getroot().findall(".//testcase") if xml.exists() else []
    bad = [x for x in cases if any(x.find(k) is not None for k in ("failure", "error", "skipped"))]
    unchanged = before == source_inventory(config_path) and env == environment()
    passed = completed.returncode == 0 and bool(cases) and not bad and unchanged
    evidence = dict(status="passed" if passed else "failed", command=command,
                    returncode=completed.returncode, testcase_count=len(cases), bad_or_skipped_count=len(bad),
                    unchanged=unchanged, source_sha256=before, environment=env,
                    xml_sha256=digest(xml) if xml.exists() else None,
                    evidence_directory=folder.relative_to(out).as_posix())
    save(folder / "result.json", evidence)
    save(out / "validation/latest.json", dict(evidence_directory=evidence["evidence_directory"],
         result_sha256=digest(folder / "result.json")), replace=True)
    print(f"Validation {evidence['status']}: {folder}", flush=True)
    if not passed:
        raise ValueError("Actual local validation must pass; preserve evidence and diagnose the failure")


def freeze(config, config_path, out):
    if (out / "protocol.json").exists():
        verify(config, config_path, out)
        print("Existing protocol verified; no overwrite", flush=True)
        return
    check_config(config)
    inventory, env = source_inventory(config_path), environment()
    protected = previous.protect_base(config)
    inputs = inspect_references(config)
    pre_ref = read(out / "preflight/latest.json")
    pre_path = out / pre_ref["path"]
    pre = read(pre_path)
    validation_ref = read(out / "validation/latest.json")
    validation_path = out / validation_ref["evidence_directory"] / "result.json"
    validation = read(validation_path)
    if (digest(pre_path) != pre_ref["sha256"] or pre["status"] != "ready"
            or pre["source_sha256"] != inventory or pre["environment"] != env
            or digest(validation_path) != validation_ref["result_sha256"]
            or validation["status"] != "passed" or not validation["unchanged"]
            or validation["testcase_count"] <= 0 or validation["bad_or_skipped_count"]
            or validation["source_sha256"] != inventory or validation["environment"] != env
            or digest(validation_path.parent / "pytest.xml") != validation["xml_sha256"]):
        raise ValueError("Ready preflight and actual passing validation for this code/environment are required")
    tasks = {s: tasks_for(config, s) for s in STAGES}
    protocol = dict(status="frozen_before_new_runs", created_utc=datetime.now(timezone.utc).isoformat(),
                    config=config, git_head=subprocess.check_output(
                        ["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
                    source_sha256=inventory, environment=env, inputs=inputs,
                    protected_base_sources=protected, preflight=pre_ref, validation=validation_ref,
                    validation_xml_sha256=validation["xml_sha256"],
                    tasks_sha256={s: object_digest(t) for s, t in tasks.items()}, plan=plan(config))
    save(out / "protocol.json", protocol)
    for stage, values in tasks.items():
        save(out / "tasks" / f"{stage}.json", values)
    print("Frozen 112 tasks; every search stage remains an explicit local command", flush=True)


def verify(config, config_path, out):
    protocol = read(out / "protocol.json")
    if (protocol["config"] != config or protocol["source_sha256"] != source_inventory(config_path)
            or protocol["environment"] != environment() or protocol["inputs"] != inspect_references(config)):
        raise ValueError("Frozen code, input, reference or environment changed; retain this output directory")
    pref = protocol["preflight"]
    val = protocol["validation"]
    vpath = out / val["evidence_directory"] / "result.json"
    if (digest(out / pref["path"]) != pref["sha256"]
            or digest(vpath) != val["result_sha256"]
            or digest(vpath.parent / "pytest.xml") != protocol["validation_xml_sha256"]):
        raise ValueError("Frozen preflight or validation evidence changed")
    for s in STAGES:
        tasks = read(out / "tasks" / f"{s}.json")
        if tasks != tasks_for(config, s) or object_digest(tasks) != protocol["tasks_sha256"][s]:
            raise ValueError("Frozen task matrix changed")
    return protocol


def frozen_evidence(out):
    return dict(protocol_sha256=digest(out / "protocol.json"))


def options_for(config, task, ref):
    options = dict(config["search"], **config["refinement"], **config["methods"][task["method"]])
    options["pd_floor"] = (ref["pd_final"] - config["decision"]["pd_guard_delta"]
                           if task["method"] == "completion_pd_guard" else None)
    return options


def timely_pareto(raw, seconds, offset):
    """Rebuild a front from insertion history after applying the outer clock.

    Filtering only the final front loses an earlier valid point if a later,
    externally late point dominated it. Histories are therefore mandatory for
    archived methods. The original scorer audits only the reconstructed front;
    it need not replay thousands of already dominated insertion events again.
    """
    if raw.get("archive_enabled") and "pareto_archive_history" not in raw:
        raise ValueError("Archived method omitted its insertion history")
    front, accepted, last_time = [], 0, -math.inf
    for row in raw.get("pareto_archive_history", []):
        elapsed = row.get("elapsed_s")
        if (isinstance(elapsed, bool) or not isinstance(elapsed, (int, float))
                or not math.isfinite(elapsed) or elapsed < 0 or elapsed < last_time):
            raise ValueError("Invalid archive validation time")
        last_time = elapsed
        if any(isinstance(row.get(k), bool) or not isinstance(row.get(k), (int, float))
               or not math.isfinite(row[k]) for k in ("J", "pd_final")):
            raise ValueError("Invalid archive metric")
        if elapsed + offset > seconds:
            continue
        accepted += 1
        item = dict(row, elapsed_s=elapsed + offset)
        if any(p["J"] <= item["J"] and p["pd_final"] >= item["pd_final"] for p in front):
            continue
        front = [p for p in front if not (item["J"] <= p["J"] and item["pd_final"] >= p["pd_final"])]
        front.append(item)
    return front, accepted


def audit_result(config, problem, ref, task, raw, wall, cpu_s):
    """Original scorer checks are external audit time, never additional search time."""
    options = options_for(config, task, ref)
    expected = dict(options, connectivity=task["connectivity"], footprint=task["footprint"],
                    max_seconds=task["seconds"], max_expansions=None)
    expected["archive_enabled"] = expected.pop("archive")
    if any(key not in raw or raw[key] != value for key, value in expected.items()):
        raise ValueError("Backend options differ from the frozen task")
    result = followup.audit_search_result(problem, ref["waypoints"], task, raw, wall, cpu_s,
                                          config["tolerance"]["score_absolute"])
    tol = config["tolerance"]["score_absolute"]
    if (abs(result["initial_J"] - ref["J"]) > tol
            or abs(result["history"][0]["pd_final"] - ref["pd_final"]) > tol):
        raise ValueError("Shared historical route does not reproduce its pinned physical score")
    offset = result["conservative_clock_offset_s"]
    started = time.perf_counter()
    archive, insertion_count = timely_pareto(raw, task["seconds"], offset)
    for row in archive:
        score = problem.replay(row["waypoints"], task["connectivity"])
        if any(not isinstance(row.get(k), (int, float)) or not math.isfinite(row[k])
               or abs(score[k] - row[k]) > tol for k in ("J", "pd_final")):
            raise ValueError("Encountered-candidate archive replay failed")
    if options["pd_floor"] is not None:
        if any(row["pd_final"] + options["pd_tolerance"] < options["pd_floor"] for row in result["history"]):
            raise ValueError("A reported guarded incumbent violates its fixed probability floor")
    result.update(method=task["method"], method_options=options,
                  reference_J=ref["J"], reference_pd=ref["pd_final"],
                  reference_run_id=ref["run_id"], reference_waypoints_sha256=ref["waypoints_sha256"],
                  pareto_archive=archive,
                  archive_insertions_inside_budget=insertion_count,
                  archive_scope="encountered and replayed candidates only; J pruning prevents a complete Pareto frontier",
                  guard_feasible=(None if options["pd_floor"] is None else
                                  result["pd_final"] + options["pd_tolerance"] >= options["pd_floor"]),
                  archive_audit_wall_s=time.perf_counter() - started,
                  input_role=config["dataset_role"])
    times = {}
    for name in ("first_terminal_generated_s", "first_search_terminal_generated_s",
                 "first_completion_terminal_generated_s", "first_new_complete_replay_s"):
        value = raw.get("diagnostics", {}).get(name)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                  or not math.isfinite(value) or value < 0):
            raise ValueError("Invalid diagnostic clock")
        times[name] = value + offset if value is not None and value + offset <= task["seconds"] else None
    result["diagnostic_times"] = times
    return result


def worker(config, config_path, out, task_path, result_path):
    protocol = verify(config, config_path, out)
    task = read(task_path)
    if task not in tasks_for(config, task["stage"]):
        raise ValueError("Unregistered worker task")
    evidence = frozen_evidence(out)
    from asar_repro.physical_followup_data import load_prepared_case
    from asar_repro.physical_refinement import solve_physical_refinement
    manifest = reference_manifest(config)
    old = ROOT / manifest["historical_output_root"]
    case = next(c for c in config["cases"] if c["id"] == task["case"])
    ref = reference_for(config, task["case"], task["footprint"])
    problem, _, _, info = load_prepared_case(ROOT, case, old / "inputs" / case["id"], task["footprint"])
    options = options_for(config, task, ref)
    started, cpu = time.perf_counter(), time.process_time()
    raw = solve_physical_refinement(problem, connectivity=task["connectivity"],
                                   initial_waypoints=ref["waypoints"], max_seconds=task["seconds"], **options)
    wall, cpu_s = time.perf_counter() - started, time.process_time() - cpu
    result = audit_result(config, problem, ref, task, raw, wall, cpu_s)
    result["inputs"] = info
    result["environment"] = environment()
    verify(config, config_path, out)
    if evidence != frozen_evidence(out) or result["environment"] != protocol["environment"]:
        raise ValueError("Frozen identity changed during worker execution")
    save(result_path, dict(task=task, result=result))


def load_record(config, out, task):
    folder = out / "runs" / task_id(task)
    if not folder.exists():
        return None
    record_path, result_path = folder / "record.json", folder / "result.json"
    if not record_path.exists():
        raise ValueError(f"Incomplete run directory preserved: {folder}")
    record = read(record_path)
    if (record["task"] != task or read(folder / "task.json") != task
            or record["frozen_evidence"] != frozen_evidence(out)
            or record["status"] != "completed" or record["returncode"] != 0 or record["watchdog"] is not None
            or digest(result_path) != record["result_sha256"]):
        raise ValueError(f"Invalid or failed run preserved: {folder}")
    payload = read(result_path)
    result = payload["result"]
    ref = reference_for(config, task["case"], task["footprint"])
    if (payload["task"] != task or result["status"] != "valid" or result["method"] != task["method"]
            or result["method_options"] != options_for(config, task, ref)
            or result["reference_run_id"] != ref["run_id"]
            or result["reference_J"] != ref["J"] or result["reference_pd"] != ref["pd_final"]
            or result["reference_waypoints_sha256"] != ref["waypoints_sha256"]
            or result["environment"] != read(out / "protocol.json")["environment"]):
        raise ValueError("Record/result/frozen reference identity mismatch")
    manifest = reference_manifest(config)
    prepared = read(ROOT / manifest["historical_output_root"] / manifest["prepared_inputs"]["path"])
    expected_input = prepared["cases"][task["case"]]
    if (any(result["inputs"].get(k) != expected_input[k]
            for k in ("particle_sha256", "metadata_sha256", "manifest_sha256", "case_spec"))
            or result["inputs"].get("footprint") != task["footprint"]
            or not result["history"] or result["history"][0].get("waypoints") != ref["waypoints"]
            or abs(result["initial_J"] - ref["J"]) > config["tolerance"]["score_absolute"]):
        raise ValueError("Recorded input archive or initial route differs from the frozen reference")
    return dict(task=task, result=result, record=record, run_id=task_id(task))


def collect(config, out, stage):
    rows, missing, errors = [], [], []
    for task in tasks_for(config, stage):
        try:
            row = load_record(config, out, task)
            if row is None:
                missing.append(task_id(task))
            else:
                rows.append(row)
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            errors.append(dict(run_id=task_id(task), error=str(exc)))
    return dict(stage=stage, planned=len(tasks_for(config, stage)), completed=len(rows),
                status="complete" if not missing and not errors else "incomplete_or_invalid",
                missing=missing, errors=errors), rows


def require_complete(config, out, stage):
    status, rows = collect(config, out, stage)
    if status["status"] != "complete":
        raise ValueError(f"{stage} is incomplete or invalid; later stages are blocked")
    return rows


def launch_task(config, config_path, out, task):
    import psutil
    existing = load_record(config, out, task)
    if existing is not None:
        print(f"Verified existing {task_id(task)}", flush=True)
        return existing
    folder = out / "runs" / task_id(task)
    folder.mkdir(parents=True, exist_ok=False)
    save(folder / "task.json", task)
    evidence = frozen_evidence(out)
    command = [sys.executable, str(Path(__file__).resolve()), "_worker", "--config", str(config_path),
               "--out", str(out), "--task", str(folder / "task.json"), "--result", str(folder / "result.json")]
    started, peak, killed = time.perf_counter(), 0, None
    with (folder / "stdout.log").open("w", encoding="utf-8") as stdout, \
         (folder / "stderr.log").open("w", encoding="utf-8") as stderr:
        child = subprocess.Popen(command, cwd=ROOT, env=common.child_environment(), stdout=stdout, stderr=stderr)
        process = None
        while child.poll() is None:
            descendants = []
            try:
                if process is None:
                    process = psutil.Process(child.pid)
                descendants = process.children(recursive=True)
                peak = max(peak, process.memory_info().rss + sum(p.memory_info().rss for p in descendants))
                if peak > config["watchdog"]["rss_limit_bytes"]:
                    killed = "rss_limit"
            except psutil.Error:
                pass
            if time.perf_counter() - started > task["seconds"] + config["watchdog"]["grace_seconds"]:
                killed = killed or "process_watchdog"
            if killed:
                for p in reversed(descendants):
                    try:
                        p.kill()
                    except psutil.Error:
                        pass
                child.kill()
                break
            time.sleep(config["watchdog"]["poll_seconds"])
        returncode = child.wait()
    result_path = folder / "result.json"
    valid = False
    if result_path.exists():
        payload = read(result_path)
        valid = payload.get("task") == task and payload.get("result", {}).get("status") == "valid"
    record = dict(task=task, command=command, frozen_evidence=evidence,
                  status="completed" if returncode == 0 and not killed and valid else "failed",
                  returncode=returncode, watchdog=killed, process_wall_s=time.perf_counter() - started,
                  peak_rss_bytes=peak, result_sha256=digest(result_path) if result_path.exists() else None)
    save(folder / "record.json", record)
    if record["status"] != "completed":
        raise RuntimeError(f"Failed run preserved; stage stopped: {folder}")
    print(f"Completed {task_id(task)}", flush=True)
    return load_record(config, out, task)


def run_stage(config, config_path, out, stage):
    verify(config, config_path, out)
    for prior in STAGES[:STAGES.index(stage)]:
        require_complete(config, out, prior)
    for task in tasks_for(config, stage):
        launch_task(config, config_path, out, task)
    analyze(config, config_path, out)


def exact_rows(config, rows, stage):
    expected = {task_id(t): t for t in tasks_for(config, stage)}
    found = [task_id(r["task"]) for r in rows]
    if len(found) != len(expected) or len(set(found)) != len(found) or set(found) != set(expected):
        return False
    return all(r["task"] == expected[task_id(r["task"])] and all(
        not isinstance(r["result"].get(k), bool) and isinstance(r["result"].get(k), (int, float))
        and math.isfinite(r["result"][k]) for k in ("J", "pd_final")) for r in rows)


def groups_for(rows):
    groups = defaultdict(list)
    for row in rows:
        t = row["task"]
        groups[(t["case"], t["footprint"], t["connectivity"], t["method"])].append(row)
    return groups


def median(rows, key):
    return statistics.median(r["result"][key] for r in rows)


def gain(reference, candidate):
    return (reference - candidate) / max(abs(reference), 1e-15)


def target_report(config, rows):
    output = []
    for target in config["development_targets"]:
        arms = {}
        for method in ("diagnostic_cached", "completion_J"):
            subset = sorted([r for r in rows if r["task"]["method"] == method
                and all(r["task"][k] == target[k] for k in ("case", "footprint", "connectivity"))],
                key=lambda r: r["task"]["repetition"])
            times = [followup.time_to_target(r["result"], target["J"], config["tolerance"]["target_absolute"])
                     for r in subset]
            full = len(times) == config["stages"]["D5"]["repetitions"] and all(t is not None for t in times)
            arms[method] = dict(times_s=times, hit_count=sum(t is not None for t in times),
                                median_if_all_hit_s=statistics.median(times) if full else None,
                                non_hit="right_censored_at_5s_not_a_measured_target_time")
        a, b = [arms[m]["median_if_all_hit_s"] for m in ("diagnostic_cached", "completion_J")]
        output.append(dict(target=target, methods=arms,
                           relative_time_reduction=None if a is None or b is None or a <= 0 else gain(a, b)))
    return output


def method_decision(config, d5_rows, d30_rows, complete):
    if not complete or not exact_rows(config, d5_rows, "D5") or not exact_rows(config, d30_rows, "D30"):
        return dict(status="incomplete_or_invalid", selected_method_for_H2=None)
    groups, comparisons = groups_for(d30_rows), []
    for group in config["d30_groups"]:
        for graph in config["connectivities"]:
            key = (group["case"], group["footprint"], graph)
            a, b = [median(groups[key + (m,)], "J") for m in ("diagnostic_cached", "completion_J")]
            comparisons.append(dict(**group, connectivity=graph, control_J=a, candidate_J=b, relative_gain=gain(a, b)))
    targets = target_report(config, d5_rows)
    quality = all(c["relative_gain"] >= -config["decision"]["quality_relative"] for c in comparisons)
    improved = sum(c["footprint"] == config["primary_footprint"] and
                   c["relative_gain"] >= config["decision"]["min_primary_method_gain"] for c in comparisons)
    hits = all(t["methods"]["completion_J"]["hit_count"] >= t["methods"]["diagnostic_cached"]["hit_count"]
               for t in targets)
    passed = quality and improved >= config["decision"]["min_improved_primary_groups"] and hits
    return dict(status="completion_development_screen_passed" if passed else "completion_development_screen_not_passed",
                selected_method_for_H2="completion_J" if passed else "cached_reference_v2",
                quality_protected=quality, improved_primary_groups=improved,
                target_hit_counts_protected=hits, comparisons=comparisons, targets=targets,
                independence_claim=False)


def graph_comparisons(config, rows):
    if not exact_rows(config, rows, "D30"):
        return []
    groups, output = groups_for(rows), []
    for method in ("diagnostic_cached", "completion_J"):
        for group in config["d30_groups"]:
            key = (group["case"], group["footprint"])
            a, b = [groups[key + (graph, method)] for graph in (4, 8)]
            j4, j8, p4, p8 = median(a, "J"), median(b, "J"), median(a, "pd_final"), median(b, "pd_final")
            output.append(dict(method=method, **group, J4=j4, J8=j8, relative_J_gain=gain(j4, j8),
                               Pd4=p4, Pd8=p8, delta_Pd_pp=100 * (p8 - p4),
                               winner=gain(j4, j8) >= config["decision"]["graph_winner_relative"],
                               role="observed_development_data_not_independent_transfer"))
    return output


def guard_decision(config, rows, d30_rows, complete):
    if not complete or not exact_rows(config, rows, "G30") or not exact_rows(config, d30_rows, "D30"):
        return dict(status="incomplete_or_invalid")
    groups, controls, comparisons = groups_for(rows), groups_for(d30_rows), []
    for footprint in ("heading_square", "axis_square"):
        ref = reference_for(config, "lake_window_late", footprint)
        floor = ref["pd_final"] - config["decision"]["pd_guard_delta"]
        arms = {}
        for graph in (4, 8):
            rs = groups[("lake_window_late", footprint, graph, "completion_pd_guard")]
            other = controls[("lake_window_late", footprint, graph, "completion_J")]
            j, pd = median(rs, "J"), median(rs, "pd_final")
            feasible = all(r["result"]["pd_final"] + config["refinement"]["pd_tolerance"] >= floor for r in rs)
            arms[str(graph)] = dict(J=j, pd_final=pd, all_repetitions_feasible=feasible,
                relative_gain_over_reference=gain(ref["J"], j),
                joint_gain_over_reference=feasible and gain(ref["J"], j) >= config["decision"]["guard_joint_gain_over_reference"],
                J_only_J=median(other, "J"), J_only_pd=median(other, "pd_final"),
                J_cost_of_guard=j - median(other, "J"))
        comparisons.append(dict(footprint=footprint, pd_floor=floor, reference_J=ref["J"],
                                methods_by_connectivity=arms, relative_J_gain_8_over_4=gain(arms["4"]["J"], arms["8"]["J"])))
    feasible = all(a["all_repetitions_feasible"] for c in comparisons for a in c["methods_by_connectivity"].values())
    primary, axis = comparisons
    joint = feasible and primary["methods_by_connectivity"]["8"]["joint_gain_over_reference"]
    graph = (primary["relative_J_gain_8_over_4"] > config["decision"]["guard_graph_positive_relative"]
             and axis["relative_J_gain_8_over_4"] >= -config["decision"]["guard_axis_max_regression_relative"])
    return dict(status=("invalid_guard_violation" if not feasible else "guarded_joint_gain_development_signal"
                        if joint and graph else "feasible_without_required_joint_graph_gain"),
                all_repetitions_feasible=feasible, primary_joint_gain=joint,
                guarded_graph_signal=graph, comparisons=comparisons,
                scope="new constrained objective; does not relabel the previous J-only study")


def reference_diagnostics(config, all_rows, complete):
    if not complete:
        return dict(status="incomplete_or_invalid")
    if not all(exact_rows(config, [r for r in all_rows if r["task"]["stage"] == stage], stage)
               for stage in STAGES):
        return dict(status="incomplete_or_invalid")
    rows = [r for r in all_rows if r["task"]["case"] == "hudson_window_early"]
    output, r120_pairs = [], []
    for footprint in ("heading_square", "axis_square"):
        ref = reference_for(config, "hudson_window_early", footprint)
        four = [r for r in rows if r["task"]["footprint"] == footprint and r["task"]["connectivity"] == 4]
        winner = min(four, key=lambda r: r["result"]["J"])
        j = min(ref["J"], winner["result"]["J"])
        arms = []
        for method in ("diagnostic_cached", "completion_J"):
            eight = [r for r in rows if r["task"]["stage"] == "D30" and r["task"]["footprint"] == footprint
                     and r["task"]["connectivity"] == 8 and r["task"]["method"] == method]
            arms.append(dict(method=method, median_8_neighbor_30s_J=median(eight, "J"),
                             relative_gain_vs_best_known_four=gain(j, median(eight, "J"))))
        output.append(dict(footprint=footprint, best_known_four_J=j,
                           source_run=winner["run_id"] if winner["result"]["J"] <= ref["J"] else ref["run_id"],
                           comparisons=arms))
        long_pair = [next(r for r in rows if r["task"]["stage"] == "R120" and
                          r["task"]["footprint"] == footprint and r["task"]["connectivity"] == graph)
                     for graph in (4, 8)]
        a, b = [r["result"] for r in long_pair]
        r120_pairs.append(dict(footprint=footprint, J4=a["J"], J8=b["J"],
                               relative_J_gain=gain(a["J"], b["J"]),
                               delta_Pd_pp=100 * (b["pd_final"] - a["pd_final"]),
                               stop_reasons=[r["stop_reason"] for r in (a, b)],
                               repetitions=1, significance_claim=False))
    return dict(status="diagnostic_only", comparisons=output, r120_paired_comparisons=r120_pairs,
                meaning="best observed feasible four-neighbor route is an upper bound on its minimum J, not a lower bound or optimum",
                budget_warning="mixed 5/30/120s reference pool; cannot claim equal-budget speed or topology optimality gap")


def analyze(config, config_path, out):
    verify(config, config_path, out)
    statuses, stages, all_rows = {}, {}, []
    for stage in STAGES:
        statuses[stage], stages[stage] = collect(config, out, stage)
        all_rows.extend(stages[stage])
    complete = all(v["status"] == "complete" for v in statuses.values())
    development_complete = all(statuses[s]["status"] == "complete" for s in ("D5", "D30"))
    summary = dict(status="complete" if complete else "incomplete_or_invalid", plan=plan(config), stages=statuses,
                   reference_commit=config["base_commit"], data_role=config["dataset_role"],
                   method_decision=method_decision(config, stages["D5"], stages["D30"], development_complete),
                   graph_comparisons=graph_comparisons(config, stages["D30"]),
                   guard_decision=guard_decision(config, stages["G30"], stages["D30"],
                       statuses["G30"]["status"] == statuses["D30"]["status"] == "complete"),
                   strong_four_reference=reference_diagnostics(config, all_rows, complete),
                   H2=config["H2"], no_global_or_epsilon_certificate=True,
                   H2_method_freeze_ready=complete,
                   algorithm_budget_is_not_end_to_end_runtime=True)
    save(out / "summary.json", summary, replace=True)
    fields = ("run_id", "stage", "case", "footprint", "connectivity", "method", "repetition", "seconds", "J", "pd_final",
              "reference_J", "reference_pd", "best_found_elapsed_s", "algorithm_wall_s", "stop_reason", "peak_rss_bytes",
              "first_terminal_generated_s", "first_new_complete_replay_s", "expanded", "terminal_candidates", "completion_calls")
    with (out / "comparison.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in all_rows:
            result, raw = row["result"], row["result"]["raw_solver"]
            value = {"run_id": row["run_id"], **row["task"],
                     **{k: result.get(k) for k in fields if k in result},
                     "peak_rss_bytes": row["record"]["peak_rss_bytes"]}
            value.update({k: result.get("diagnostic_times", {}).get(k) for k in
                          ("first_terminal_generated_s", "first_new_complete_replay_s")})
            value.update({k: raw.get("stats", {}).get(k) for k in ("expanded", "terminal_candidates", "completion_calls")})
            writer.writerow({k: value.get(k) for k in fields})
    lines = ["# 物理搜索证据补强：本地自动汇总", "", f"状态：`{summary['status']}`。输入是已经看过的开发/诊断实例。", "",
             f"完整路线候选：`{summary['method_decision']['status']}`。", "",
             f"发现概率护栏：`{summary['guard_decision']['status']}`。", "",
             "## 同预算四／八邻接对照", "", "| 方法 | 实例 | 覆盖 | J4 | J8 | J改善 | ΔPd（百分点） |",
             "|---|---|---|---:|---:|---:|---:|"]
    for x in summary["graph_comparisons"]:
        lines.append(f"| {x['method']} | {x['case']} | {x['footprint']} | {x['J4']:.8f} | {x['J8']:.8f} | "
                     f"{100*x['relative_J_gain']:.4f}% | {x['delta_Pd_pp']:+.4f} |")
    lines += ["", "## 使用边界", "", "D5/D30/G30/R120 各自从固定共同参考重启；R120 只作质量诊断。",
              "三次运行是计时重复，不能当作独立天气样本。H2 尚未启用。", "",
              "完整判定、到达目标时刻、护栏代价和较强四邻接参考见 summary.json；逐次记录见 comparison.csv 与 runs/。",
              "按 RESULTS_TEMPLATE.md 补充首个完整路线、深度/tick 分布和负结果的解释；不得将未到达目标填成5秒后计算加速比。", ""]
    (out / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Analysis {summary['status']}: {out / 'summary.json'}", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "preflight", "validate", "freeze", "run", "analyze", "_worker"))
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stage", choices=STAGES)
    parser.add_argument("--task", type=Path)
    parser.add_argument("--result", type=Path)
    args = parser.parse_args(argv)
    config_path = args.config.resolve()
    config = read(config_path)
    common.set_threads(config)
    check_config(config)
    if args.command == "plan":
        print(json.dumps(plan(config), ensure_ascii=False, indent=2))
        return
    if args.out is None:
        parser.error("--out is required")
    out = args.out.resolve()
    if out == OUTPUT_ROOT.resolve() or not out.is_relative_to(OUTPUT_ROOT.resolve()):
        raise ValueError("Use a new child directory under the registered output root")
    if args.command == "_worker":
        if args.task is None or args.result is None:
            parser.error("_worker requires --task and --result")
        try:
            worker(config, config_path, out, args.task, args.result)
        except Exception:
            if not args.result.exists():
                save(args.result, dict(task=read(args.task), result=dict(status="failed", traceback=traceback.format_exc())))
            raise
        return
    command_file = out / "commands" / f"{stamp()}_{args.command}.json"
    record = dict(command=[sys.executable, str(Path(__file__).resolve()), *(sys.argv[1:] if argv is None else argv)],
                  started_utc=datetime.now(timezone.utc).isoformat(), status="running")
    save(command_file, record)
    try:
        if args.command == "preflight":
            preflight(config, config_path, out)
        elif args.command == "validate":
            validate(config, config_path, out)
        elif args.command == "freeze":
            freeze(config, config_path, out)
        elif args.command == "run":
            if args.stage is None:
                raise ValueError("run requires --stage")
            run_stage(config, config_path, out, args.stage)
        else:
            analyze(config, config_path, out)
        record.update(status="completed", returncode=0)
    except Exception:
        record.update(status="failed", returncode=1, traceback=traceback.format_exc())
        raise
    finally:
        record["finished_utc"] = datetime.now(timezone.utc).isoformat()
        save(command_file, record, replace=True)


if __name__ == "__main__":
    main()
