#!/usr/bin/env python3
"""Local-only, frozen comparison of physical four/eight-neighbor motion.

Delivery performs no tests or searches. Every command is explicit. The study
uses a controlled square-footprint proxy, not a calibrated flight sensor.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import csv
import hashlib
import importlib.metadata
import json
import math
import os
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
import run_solver_paradigm_study as common

DEFAULT_CONFIG = ROOT / "configs/eight_neighbor_physical.json"
OUTPUT_ROOT = ROOT / "outputs/eight_neighbor_physical_20261127"
read, save, digest = common.read, common.save, common.digest
object_digest, clean = common.object_digest, common.clean


def environment():
    result = common.environment()
    result["packages"]["pyproj"] = importlib.metadata.version("pyproj")
    return result


def source_inventory(config_path):
    paths = set()
    for folder, pattern in (("src/asar_repro", "*.py"), ("scripts", "*.py"),
                            ("tests", "*.py"), ("configs", "*.json"),
                            ("docs/eight_neighbor_physical", "*.md")):
        paths.update((ROOT / folder).rglob(pattern))
    paths.update([Path(config_path), ROOT / "requirements-physical-study.txt", ROOT / "pyproject.toml"])
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(paths)}


def protect_base(config):
    """Compare original tracked code with base blobs, allowing CRLF/LF checkout."""
    scopes = ["asar_repro/src/asar_repro", "asar_repro/scripts",
              "asar_repro/tests", "asar_repro/configs"]
    listing = subprocess.check_output(
        ["git", "ls-tree", "-rz", config["base_commit"], "--", *scopes], cwd=REPO)
    entries = []
    for entry in listing.split(b"\0"):
        if not entry:
            continue
        meta, path_bytes = entry.split(b"\t", 1)
        _, kind, sha = meta.split()
        path = path_bytes.decode("utf-8")
        if kind == b"blob" and Path(path).suffix in (".py", ".json"):
            entries.append((sha.decode("ascii"), path))
    if not entries:
        raise ValueError("No baseline sources found in git; fetch the base branch first")
    payload = "".join(sha + "\n" for sha, _ in entries).encode("ascii")
    blobs = subprocess.check_output(["git", "cat-file", "--batch"], cwd=REPO, input=payload)
    offset, protected = 0, {}
    for expected_sha, path in entries:
        end = blobs.index(b"\n", offset)
        sha, kind, size_bytes = blobs[offset:end].split()
        if sha.decode() != expected_sha or kind != b"blob":
            raise ValueError("Unexpected git cat-file response")
        size = int(size_bytes)
        data = blobs[end + 1:end + 1 + size]
        offset = end + 1 + size + 1
        canonical = data.replace(b"\r\n", b"\n")
        local = (REPO / path).read_bytes().replace(b"\r\n", b"\n")
        expected = hashlib.sha256(canonical).hexdigest()
        if hashlib.sha256(local).hexdigest() != expected:
            raise ValueError(f"Baseline source changed: {path}")
        protected[path] = expected
    return protected


def legacy_config(config):
    return read(ROOT / config["legacy_config"])


def load_real_problem(config, scene, footprint):
    """Read original frames; no drift generation, interpolation or downloads."""
    import numpy as np
    from pyproj import CRS, Transformer
    from run_stdc_final_assessment import load_scene
    from asar_repro.physical_model import PhysicalProblem

    legacy = legacy_config(config)
    grid, old_cfg, spec, info = load_scene(legacy, scene)
    mission = spec["mission"]
    d, delta = float(mission["cell_width_m"]), float(mission["step_s"])
    speed = float(config["physical_contract"]["speed_m_s"])
    if abs(d / delta - speed) > 1e-10:
        raise ValueError("Frozen frame cadence and requested ground speed disagree")
    with np.load(ROOT / spec["particle_path"], allow_pickle=False) as archive:
        required = {"lon", "lat", "cell_ids", "time_utc", "trajectory_id", "initial_weights"}
        if not required.issubset(archive.files):
            raise ValueError(f"Archive lacks physical fields: {sorted(required-set(archive.files))}")
        lon, lat = archive["lon"].copy(), archive["lat"].copy()
        cells = archive["cell_ids"].copy()
        utc = archive["time_utc"].copy()
        ids, weights = archive["trajectory_id"].copy(), archive["initial_weights"].copy()
    center_lon, center_lat = mission["csp_lon_lat"]
    crs = CRS.from_proj4(
        f"+proj=aeqd +lat_0={center_lat} +lon_0={center_lon} +datum=WGS84 +units=m")
    projection = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    x, y = projection.transform(lon, lat)
    xy = np.stack([x, y], axis=-1).astype(float)
    searchable = cells < grid.size
    if lon.shape != cells.shape or lat.shape != cells.shape:
        raise ValueError("Position/particle frame dimensions disagree")
    finite = np.isfinite(xy).all(axis=-1)
    if np.any(searchable & ~finite):
        raise ValueError("Searchable archived particle has no finite physical position")
    xy[~finite] = 0.0
    # Audit mapping against the original classification. Special bins are not
    # reconstructed: their archived labels remain authoritative.
    valid_xy = xy[searchable]
    cols = np.floor(valid_xy[:, 0] / d + grid.cols / 2).astype(int)
    south = np.floor(valid_xy[:, 1] / d + grid.rows / 2).astype(int)
    remapped = (grid.rows - 1 - south) * grid.cols + cols
    if not np.array_equal(remapped, cells[searchable]):
        raise ValueError("Metric projection does not reproduce original searchable cell IDs")
    times = (utc - utc[0]) / np.timedelta64(1, "s")
    problem = PhysicalProblem(
        rows=grid.rows, cols=grid.cols, cell_width_m=d, speed_m_s=speed,
        times_s=np.asarray(times, dtype=float), positions_xy=xy,
        searchable=searchable, initial_weights=weights,
        start=int(spec["reference_path"][0]), q=float(mission["audit_q"]),
        footprint=footprint, trajectory_ids=ids)
    info = dict(info, physical_clock_s=np.asarray(times).tolist(),
                actual_particles=len(ids), projected_searchable_cell_mapping="matched",
                masked_nonfinite_unsearchable_positions=int((~finite).sum()),
                sensor_model_status=config["sensor_model_status"], footprint=footprint,
                initialization="historical strong four-neighbor route, newly replayed",
                old_reference_J=spec["reference_J"], old_reference_Pd=spec["reference_Pd"])
    return problem, list(spec["reference_path"]), spec, info


def diagnostic_definitions():
    from asar_repro.physical_search import diagnostic_cases
    cases = diagnostic_cases()
    if len({c["id"] for c in cases}) != len(cases):
        raise ValueError("Duplicate diagnostic case IDs")
    return {c["id"]: c for c in cases}


def check_config(config):
    registered = {
        "batch": "eight-neighbor-physical-study-20261127",
        "base_commit": "3399015cdf2e20dabe5895e30e3ae812bb68b049",
        "diagnostic": {"expected_cases": 6, "search_seconds": 2, "oracle_seconds": 10,
                       "tolerance": 1e-8},
        "stages": {"B5": {"seconds": 5, "repetitions": 3},
                   "B30": {"seconds": 30, "repetitions": 3}},
        "search": {"guide_weight": 1.04, "max_open": 100000},
        "gates": {"quality_relative_improvement": 0.005,
                  "non_regression_relative_tolerance": 1e-8,
                  "sensitivity_positive_relative_tolerance": 1e-8,
                  "sensitivity_max_relative_regression": 0.005},
    }
    for key, expected in registered.items():
        if config[key] != expected:
            raise ValueError(f"Registered {key} changed; design and label a new study version")
    if config["connectivities"] != [4, 8]:
        raise ValueError("This protocol compares exactly four/eight connectivity")
    if config["footprints"] != ["heading_square", "axis_square"]:
        raise ValueError("Both prespecified sensor proxies must be retained")
    if set(config["primary_scenes"]) != {"lake_ontario", "arctic_ocean"}:
        raise ValueError("Main scenes changed; register a new study version")
    if config["primary_footprint"] != "heading_square":
        raise ValueError("Primary sensor proxy changed")
    if float(config["physical_contract"]["speed_m_s"]) != 20.0:
        raise ValueError("This frozen study uses the existing 20 m/s ground speed")
    if any(not (ROOT / p).is_file() for p in config["validation_tests"]):
        raise ValueError("Required validation test files are missing")


def inspect_inputs(config):
    cases = diagnostic_definitions()
    if len(cases) != config["diagnostic"]["expected_cases"]:
        raise ValueError("Diagnostic case count differs from registered design")
    scenes = {}
    tol = config["diagnostic"]["tolerance"]
    for scene in config["primary_scenes"]:
        sensors = {}
        for footprint in config["footprints"]:
            problem, seed, spec, info = load_real_problem(config, scene, footprint)
            scores = {}
            for name in ("initial_path", "reference_path"):
                score = problem.replay(spec[name], 4)
                scores[name] = dict(J=score["J"], pd_final=score["pd_final"])
                old_j = spec["PT_J" if name == "initial_path" else "reference_J"]
                old_pd = spec["PT_Pd" if name == "initial_path" else "reference_Pd"]
                scores[name]["delta_from_legacy_J"] = score["J"] - old_j
                scores[name]["delta_from_legacy_Pd"] = score["pd_final"] - old_pd
                if footprint == "axis_square" and (
                    abs(score["J"] - old_j) > tol or abs(score["pd_final"] - old_pd) > tol):
                    raise ValueError(f"Legacy clock/axis-square bridge failed: {scene}/{name}")
            sensors[footprint] = dict(inputs=info, legacy_bridge_replays=scores)
        scenes[scene] = sensors
    return dict(scenes=scenes, diagnostic_cases=cases,
                physical_model="proxy_sensor_no_turn_dynamics",
                old_metrics_are_not_new_model_targets=True)


def tasks_for(config, stage, cases):
    tasks = []
    if stage == "A":
        for case in sorted(cases):
            for footprint in config["footprints"]:
                for connectivity in config["connectivities"]:
                    for method, seconds in (
                        ("search", config["diagnostic"]["search_seconds"]),
                        ("oracle", config["diagnostic"]["oracle_seconds"])):
                        tasks.append(dict(stage=stage, case=case, footprint=footprint,
                                          connectivity=connectivity, method=method,
                                          seconds=seconds, repetition=0))
    elif stage in ("B5", "B30"):
        settings = config["stages"][stage]
        for scene in config["primary_scenes"]:
            for footprint in config["footprints"]:
                for connectivity in config["connectivities"]:
                    for repetition in range(settings["repetitions"]):
                        tasks.append(dict(stage=stage, scene=scene, footprint=footprint,
                                          connectivity=connectivity, method="search",
                                          seconds=settings["seconds"], repetition=repetition))
    else:
        raise ValueError(f"Unknown stage: {stage}")
    random.Random(config["task_order_seed"] + sum(map(ord, stage))).shuffle(tasks)
    return tasks


def task_id(task):
    return task["stage"] + "_" + object_digest(task)[:20]


def plan(config):
    cases = [f"case_{i}" for i in range(config["diagnostic"]["expected_cases"])]
    stages = {}
    for stage in ("A", "B5", "B30"):
        tasks = tasks_for(config, stage, cases)
        stages[stage] = dict(tasks=len(tasks), algorithm_budget_s=sum(t["seconds"] for t in tasks))
    return dict(status="plan_not_results", stages=stages,
                total_tasks=sum(s["tasks"] for s in stages.values()),
                algorithm_budget_s=sum(s["algorithm_budget_s"] for s in stages.values()),
                excludes="validation, input loading, process startup, final audit and IO",
                long_budget="not_enabled", holdout="not_designed_not_run")


def stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def preflight(config, config_path, out):
    check_config(config)
    protected = protect_base(config)
    evidence = dict(status="preflight_passed_not_benchmarked", environment=environment(),
                    source_sha256=source_inventory(config_path),
                    protected_base_sources=protected, inputs=inspect_inputs(config), plan=plan(config))
    folder = out / "preflight" / stamp()
    save(folder / "preflight.json", evidence)
    print(f"Preflight saved: {folder}", flush=True)


def validate(config, config_path, out):
    check_config(config)
    protect_base(config)
    before, env_before = source_inventory(config_path), environment()
    folder = out / "validation" / stamp()
    folder.mkdir(parents=True, exist_ok=False)
    xml = folder / "pytest.xml"
    command = [sys.executable, "-m", "pytest", "-q", *config["validation_tests"],
               f"--junitxml={xml}"]
    with (folder / "stdout.log").open("w", encoding="utf-8") as stdout, \
         (folder / "stderr.log").open("w", encoding="utf-8") as stderr:
        result = subprocess.run(command, cwd=ROOT, env=common.child_environment(),
                                stdout=stdout, stderr=stderr, check=False)
    testcases = ET.parse(xml).getroot().findall(".//testcase") if xml.exists() else []
    bad = [x for x in testcases if any(x.find(k) is not None for k in ("failure", "error", "skipped"))]
    unchanged = before == source_inventory(config_path) and env_before == environment()
    passed = result.returncode == 0 and bool(testcases) and not bad and unchanged
    evidence = dict(status="passed" if passed else "failed", command=command,
                    returncode=result.returncode, testcase_count=len(testcases),
                    bad_or_skipped_count=len(bad), source_sha256=before,
                    environment=env_before, unchanged=unchanged,
                    xml_sha256=digest(xml) if xml.exists() else None,
                    evidence_directory=folder.relative_to(out).as_posix())
    save(folder / "result.json", evidence)
    save(out / "validation/latest.json", dict(evidence_directory=evidence["evidence_directory"],
         result_sha256=digest(folder / "result.json")), replace=True)
    print(f"Validation {evidence['status']}: {folder}", flush=True)
    if not passed:
        raise RuntimeError("Local validation did not pass; freezing is blocked")


def verify(config, config_path, out):
    protocol = read(out / "protocol.json")
    if config != protocol["config"] or source_inventory(config_path) != protocol["source_sha256"]:
        raise ValueError("Frozen source/config changed; use a new output directory after revalidation")
    if environment() != protocol["environment"]:
        raise ValueError("Frozen execution environment changed")
    validation_file = out / protocol["validation"]["evidence_directory"] / "result.json"
    if digest(validation_file) != protocol["validation"]["result_sha256"]:
        raise ValueError("Frozen validation evidence changed")
    xml = validation_file.parent / "pytest.xml"
    if digest(xml) != protocol["validation_xml_sha256"]:
        raise ValueError("Frozen JUnit changed")
    legacy = legacy_config(config)
    for scene in config["primary_scenes"]:
        spec = legacy["scenes"][scene]
        for path_key, hash_key in (("particle_path", "particle_sha256"),
                                   ("metadata_path", "metadata_sha256")):
            if digest(ROOT / spec[path_key]) != spec[hash_key]:
                raise ValueError("Frozen archive/metadata changed")
    return protocol


def freeze(config, config_path, out):
    if (out / "protocol.json").exists():
        verify(config, config_path, out)
        print("Existing frozen protocol verified; no overwrite", flush=True)
        return
    check_config(config)
    protected = protect_base(config)
    latest = read(out / "validation/latest.json")
    evidence_path = out / latest["evidence_directory"] / "result.json"
    if digest(evidence_path) != latest["result_sha256"]:
        raise ValueError("Latest validation record hash mismatch")
    evidence = read(evidence_path)
    if (evidence["status"] != "passed" or evidence["source_sha256"] != source_inventory(config_path)
        or evidence["environment"] != environment() or not evidence["unchanged"]
        or evidence["testcase_count"] <= 0 or evidence["bad_or_skipped_count"]):
        raise ValueError("Passing validation for this exact code/environment is required")
    if digest(evidence_path.parent / "pytest.xml") != evidence["xml_sha256"]:
        raise ValueError("Validation JUnit hash mismatch")
    inputs = inspect_inputs(config)
    tasks = {stage: tasks_for(config, stage, inputs["diagnostic_cases"])
             for stage in ("A", "B5", "B30")}
    protocol = dict(status="frozen_before_measurements",
                    created_utc=datetime.now(timezone.utc).isoformat(),
                    git_head=subprocess.check_output(["git", "rev-parse", "HEAD"],
                                                     cwd=REPO, text=True).strip(),
                    config=config, environment=environment(), source_sha256=source_inventory(config_path),
                    protected_base_sources=protected, inputs=inputs,
                    validation=latest, validation_xml_sha256=evidence["xml_sha256"],
                    tasks_sha256={stage: object_digest(t) for stage, t in tasks.items()},
                    plan=plan(config))
    save(out / "protocol.json", protocol)
    for stage, stage_tasks in tasks.items():
        save(out / "tasks" / f"{stage}.json", stage_tasks)
    print("Frozen A, B5 and B30; no experiment was launched by freeze", flush=True)


def selected_history(raw, seconds, offset):
    candidates = []
    for row in raw.get("history", []):
        elapsed = row.get("elapsed_s")
        if not isinstance(elapsed, (float, int)) or not math.isfinite(elapsed) or elapsed < 0:
            raise ValueError("Invalid incumbent timestamp")
        j, pd = row.get("J"), row.get("pd_final", row.get("Pd"))
        if not all(isinstance(v, (float, int)) and math.isfinite(v) for v in (j, pd)):
            raise ValueError("Invalid incumbent metrics")
        if elapsed + offset <= seconds:
            item = dict(row)
            item["elapsed_s"] = elapsed + offset
            item["pd_final"] = pd
            candidates.append(item)
    candidates.sort(key=lambda x: x["elapsed_s"])
    return candidates


def worker(config, config_path, out, task_path, result_path):
    protocol = verify(config, config_path, out)
    task = read(task_path)
    tasks = read(out / "tasks" / f"{task['stage']}.json")
    if object_digest(tasks) != protocol["tasks_sha256"][task["stage"]] or task not in tasks:
        raise ValueError("Worker task not in frozen matrix")
    from asar_repro.physical_search import solve_physical, enumerate_physical, problem_from_case
    if task["stage"] == "A":
        case = protocol["inputs"]["diagnostic_cases"][task["case"]]
        problem = problem_from_case(case, footprint=task["footprint"])
        seed = case["initial_waypoints"]
        inputs = dict(case_id=case["id"], case_sha256=object_digest(case))
    else:
        problem, seed, _, inputs = load_real_problem(config, task["scene"], task["footprint"])
    tic, cpu = time.perf_counter(), time.process_time()
    if task["method"] == "oracle":
        raw = enumerate_physical(problem, connectivity=task["connectivity"], max_seconds=task["seconds"])
    else:
        raw = solve_physical(problem, connectivity=task["connectivity"],
                             initial_waypoints=seed, max_seconds=task["seconds"],
                             **config["search"])
    external_wall, cpu_s = time.perf_counter() - tic, time.process_time() - cpu
    if raw.get("status") in ("failed", "fatal", "blocked", "solver_error", "invalid"):
        save(result_path, dict(task=task, result=dict(status="failed",
             failure="solver did not complete valid work", raw_solver=raw, inputs=inputs)))
        raise RuntimeError("Algorithm error/block cannot be masked by an initial route")
    internal_wall = raw.get("wall_s", raw.get("elapsed_s"))
    if (not isinstance(internal_wall, (int, float)) or not math.isfinite(internal_wall)
        or internal_wall < 0):
        raise ValueError("Missing algorithm timer")
    offset = max(0.0, external_wall - internal_wall)
    history = selected_history(raw, task["seconds"], offset)
    if not history:
        raise ValueError("No fully scored feasible route within the algorithm budget")
    if task["method"] == "search" and (
        history[0].get("source") != "initial_route"
        or history[0].get("waypoints", history[0].get("path")) != list(seed)):
        raise ValueError("The shared initial route was not validated within budget")
    audit_start = time.perf_counter()
    tolerance = config["diagnostic"]["tolerance"]
    audited, previous = [], math.inf
    for row in history:
        path = row.get("waypoints", row.get("path"))
        score = problem.replay(path, task["connectivity"])
        if (abs(score["J"] - row["J"]) > tolerance
            or abs(score["pd_final"] - row["pd_final"]) > tolerance):
            raise ValueError("Independent physical replay disagrees with incumbent")
        if row["J"] > previous + tolerance:
            raise ValueError("Incumbent history regressed")
        previous = row["J"]
        audited.append(dict(row, waypoints=list(path)))
    best = min(audited, key=lambda x: x["J"])
    score = problem.replay(best["waypoints"], task["connectivity"])
    proof_time = raw.get("proof_elapsed_s")
    proof_complete = (raw.get("status") == "optimal_enumerated"
                      and isinstance(proof_time, (float, int)) and math.isfinite(proof_time)
                      and 0 <= proof_time + offset <= task["seconds"]
                      and abs(raw.get("lower_bound", math.inf) - score["J"]) <= tolerance)
    result = dict(status="valid", method_status=raw.get("status"),
                  stop_reason=raw.get("stop_reason"), J=score["J"], pd_final=score["pd_final"],
                  physical_replay=score, history=audited, raw_solver=raw,
                  best_found_elapsed_s=best["elapsed_s"],
                  initial_J=audited[0]["J"] if task["method"] == "search" else None,
                  improvement_from_initial_J=(audited[0]["J"] - score["J"]
                                              if task["method"] == "search" else None),
                  algorithm_wall_s=external_wall, algorithm_cpu_s=cpu_s,
                  inner_wall_s=internal_wall, conservative_clock_offset_s=offset,
                  audit_wall_s=time.perf_counter() - audit_start,
                  budget_overshoot_s=max(0.0, external_wall-task["seconds"]),
                  numerical_optimum_complete=proof_complete,
                  lower_bound=score["J"] if proof_complete else None,
                  proof_elapsed_s=proof_time + offset if isinstance(proof_time, (int, float)) else None,
                  inputs=inputs, environment=environment(),
                  sensor_model_status=config["sensor_model_status"],
                  formal_optimality_certificate=False)
    save(result_path, dict(task=task, result=result))


def load_record(config, out, task, protocol_hash):
    folder = out / "runs" / task_id(task)
    if not folder.exists():
        return None
    record_path = folder / "record.json"
    if not record_path.exists():
        raise ValueError(f"Incomplete run directory preserved: {folder}")
    record = read(record_path)
    if record["task"] != task or record["protocol_sha256"] != protocol_hash:
        raise ValueError("Task/protocol mismatch in existing evidence")
    if record["status"] != "completed":
        raise ValueError(f"Failed/blocked run is preserved: {folder}")
    path = folder / "result.json"
    if digest(path) != record["result_sha256"]:
        raise ValueError(f"Raw result changed: {folder}")
    payload = read(path)
    if payload["task"] != task or payload["result"]["status"] != "valid":
        raise ValueError("Raw/record validity mismatch")
    return dict(task=task, record=record, result=payload["result"], run_id=task_id(task))


def launch_task(config, config_path, out, task):
    import psutil
    protocol_hash = digest(out / "protocol.json")
    existing = load_record(config, out, task, protocol_hash)
    if existing is not None:
        print(f"Verified existing {task_id(task)}", flush=True)
        return existing
    folder = out / "runs" / task_id(task)
    folder.mkdir(parents=True, exist_ok=False)
    save(folder / "task.json", task)
    command = [sys.executable, str(Path(__file__).resolve()), "_worker",
               "--config", str(config_path), "--out", str(out),
               "--task", str(folder / "task.json"), "--result", str(folder / "result.json")]
    started, peak, killed = time.perf_counter(), 0, None
    with (folder / "stdout.log").open("w", encoding="utf-8") as stdout, \
         (folder / "stderr.log").open("w", encoding="utf-8") as stderr:
        child = subprocess.Popen(command, cwd=ROOT, env=common.child_environment(),
                                 stdout=stdout, stderr=stderr)
        process = psutil.Process(child.pid)
        while child.poll() is None:
            relatives = []
            try:
                relatives = process.children(recursive=True)
                rss = process.memory_info().rss + sum(p.memory_info().rss for p in relatives)
                peak = max(peak, rss)
                if rss > config["watchdog"]["rss_limit_bytes"]:
                    killed = "rss_limit"
                elif time.perf_counter()-started > task["seconds"]+config["watchdog"]["grace_seconds"]:
                    killed = "process_watchdog"
                if killed:
                    for descendant in reversed(relatives):
                        try:
                            descendant.kill()
                        except psutil.Error:
                            pass
                    child.kill()
                    break
            except psutil.Error:
                pass
            time.sleep(config["watchdog"]["poll_seconds"])
        returncode = child.wait()
    elapsed = time.perf_counter() - started
    raw_path = folder / "result.json"
    valid = False
    if raw_path.exists():
        payload = read(raw_path)
        valid = payload.get("task") == task and payload.get("result", {}).get("status") == "valid"
    record = dict(task=task, command=command,
                  status="completed" if returncode == 0 and not killed and valid else "failed",
                  returncode=returncode, watchdog=killed, process_wall_s=elapsed,
                  peak_rss_bytes=peak, protocol_sha256=protocol_hash,
                  result_sha256=digest(raw_path) if raw_path.exists() else None)
    save(folder / "record.json", record)
    if record["status"] != "completed":
        raise RuntimeError(f"Run failed; evidence preserved, stage stopped: {folder}")
    print(f"Completed {task_id(task)}", flush=True)
    return load_record(config, out, task, protocol_hash)


def collect(config, out, stage):
    protocol = read(out / "protocol.json")
    tasks = read(out / "tasks" / f"{stage}.json")
    if object_digest(tasks) != protocol["tasks_sha256"][stage]:
        raise ValueError("Frozen task list changed")
    rows, missing, errors = [], [], []
    for task in tasks:
        try:
            row = load_record(config, out, task, digest(out / "protocol.json"))
            if row is None:
                missing.append(task_id(task))
            else:
                rows.append(row)
        except (ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
            errors.append(dict(run_id=task_id(task), error=str(exc)))
    return dict(stage=stage, planned=len(tasks), completed=len(rows),
                status="complete" if len(rows) == len(tasks) and not errors else "incomplete_or_invalid",
                missing=missing, errors=errors), rows


def diagnostic_gate(config, rows, complete):
    if not complete:
        return dict(passed=False, reason="A incomplete", cases=[])
    indexed = {(r["task"]["case"], r["task"]["footprint"], r["task"]["connectivity"],
                r["task"]["method"]): r for r in rows}
    cases = {r["task"]["case"] for r in rows}
    expected = {(case, footprint, connectivity, method) for case in cases
                for footprint in config["footprints"] for connectivity in config["connectivities"]
                for method in ("search", "oracle")}
    if (len(cases) != config["diagnostic"]["expected_cases"]
        or len(indexed) != len(rows) or set(indexed) != expected):
        return dict(passed=False, reason="A matrix incomplete or duplicated", cases=[])
    tolerance, details = config["diagnostic"]["tolerance"], []
    for case in sorted(cases):
        for footprint in config["footprints"]:
            optima, errors = {}, []
            for connectivity in config["connectivities"]:
                oracle = indexed[(case, footprint, connectivity, "oracle")]["result"]
                search = indexed[(case, footprint, connectivity, "search")]["result"]
                if not oracle.get("numerical_optimum_complete"):
                    errors.append(f"oracle_{connectivity}_not_closed_in_budget")
                else:
                    optima[connectivity] = oracle["J"]
                    if search["J"] < oracle["J"] - tolerance:
                        errors.append(f"search_{connectivity}_below_enumerated_optimum")
                seed_j = search["history"][0]["J"]
                if search["J"] > seed_j + tolerance:
                    errors.append(f"search_{connectivity}_lost_initial_incumbent")
            if set(optima) == {4, 8} and optima[8] > optima[4] + tolerance:
                errors.append("eight_optimum_worse_despite_nested_feasible_sets")
            details.append(dict(case=case, footprint=footprint, optima=optima,
                                errors=errors, passed=not errors))
    witnessed = any(d["case"] == "diagonal_intercept"
                    and set(d["optima"]) == {4, 8}
                    and d["optima"][8] < d["optima"][4] - tolerance for d in details)
    return dict(passed=bool(details) and all(d["passed"] for d in details) and witnessed,
                same_speed_diagonal_witness=witnessed, cases=details,
                scope="enumerated diagnostic problems only; numerical checks, no real-scene certificate")


def paired_decision(config, rows, complete, *, stage="B5"):
    if stage not in ("B5", "B30"):
        raise ValueError("Only B5 and B30 have paired real-scene decisions")
    if not complete:
        return dict(status="incomplete_or_invalid", main_quality_pass=False, sensitivity_pass=False)
    groups = defaultdict(list)
    identities = set()
    for row in rows:
        task = row["task"]
        identity = (task["scene"], task["footprint"], task["connectivity"], task["repetition"])
        if (task["stage"] != stage or task["method"] != "search"
            or task["seconds"] != config["stages"][stage]["seconds"] or identity in identities
            or not math.isfinite(row["result"]["J"])):
            return dict(status="incomplete_or_invalid", main_quality_pass=False, sensitivity_pass=False)
        identities.add(identity)
        groups[(task["scene"], task["footprint"], task["connectivity"])].append(row["result"]["J"])
    expected = {(scene, footprint, connectivity, repetition)
                for scene in config["primary_scenes"] for footprint in config["footprints"]
                for connectivity in config["connectivities"]
                for repetition in range(config["stages"][stage]["repetitions"])}
    if identities != expected:
        return dict(status="incomplete_or_invalid", main_quality_pass=False, sensitivity_pass=False)
    comparisons = {}
    for footprint in config["footprints"]:
        comparisons[footprint] = {}
        for scene in config["primary_scenes"]:
            j4 = statistics.median(groups[(scene, footprint, 4)])
            j8 = statistics.median(groups[(scene, footprint, 8)])
            gain = (j4-j8) / max(abs(j4), 1e-15)
            comparisons[footprint][scene] = dict(J4_median=j4, J8_median=j8,
                                                relative_gain=gain)
    gates = config["gates"]
    main = comparisons["heading_square"]
    winners = [s for s, v in main.items()
               if v["relative_gain"] >= gates["quality_relative_improvement"]]
    quality = bool(winners) and all(
        v["relative_gain"] >= -gates["non_regression_relative_tolerance"] for v in main.values())
    axis = comparisons["axis_square"]
    sensitivity = (bool(winners)
                   and any(axis[s]["relative_gain"] > gates["sensitivity_positive_relative_tolerance"]
                           for s in winners)
                   and all(v["relative_gain"] >= -gates["sensitivity_max_relative_regression"]
                           for v in axis.values()))
    status = ("screen_passed_pending_holdout" if quality and sensitivity
              else "sensor_sensitive" if quality else "screen_not_passed")
    if stage == "B30":
        status = ("longer_budget_signal_pending_followup" if quality and sensitivity
                  else "longer_budget_sensor_sensitive" if quality
                  else "longer_budget_screen_not_passed")
    return dict(status=status, main_quality_pass=quality, sensitivity_pass=sensitivity,
                primary_improvement_scenes=winners, comparisons=comparisons,
                claim="motion-model screening under two uncalibrated proxies, not solver novelty")


def run_stage(config, config_path, out, stage):
    protocol = verify(config, config_path, out)
    if stage in ("B5", "B30"):
        a_status, a_rows = collect(config, out, "A")
        gate = diagnostic_gate(config, a_rows, a_status["status"] == "complete")
        if not gate["passed"]:
            raise ValueError("A correctness/clock/oracle gate has not passed")
    if stage == "B30":
        status, _ = collect(config, out, "B5")
        if status["status"] != "complete":
            raise ValueError("Complete B5 before independent B30")
    tasks = read(out / "tasks" / f"{stage}.json")
    if object_digest(tasks) != protocol["tasks_sha256"][stage]:
        raise ValueError("Frozen tasks changed")
    for task in tasks:
        launch_task(config, config_path, out, task)
    summarize(config, config_path, out)


def summarize(config, config_path, out):
    verify(config, config_path, out)
    statuses, all_rows = {}, []
    stage_rows = {}
    for stage in ("A", "B5", "B30"):
        status, rows = collect(config, out, stage)
        statuses[stage], stage_rows[stage] = status, rows
        all_rows.extend(rows)
    gate = diagnostic_gate(config, stage_rows["A"], statuses["A"]["status"] == "complete")
    decisions = {s: paired_decision(config, stage_rows[s],
                                    statuses[s]["status"] == "complete" and gate["passed"], stage=s)
                 for s in ("B5", "B30")}
    grouped = defaultdict(list)
    for row in all_rows:
        task = row["task"]
        if task["stage"] in ("B5", "B30"):
            grouped[(task["stage"], task["scene"], task["footprint"], task["connectivity"])].append(row)
    aggregates = []
    for (stage, scene, footprint, connectivity), rows in sorted(grouped.items()):
        values = [r["result"]["J"] for r in rows]
        aggregates.append(dict(
            stage=stage, scene=scene, footprint=footprint, connectivity=connectivity,
            n=len(rows), planned=config["stages"][stage]["repetitions"],
            J_median=statistics.median(values), J_min=min(values), J_max=max(values),
            Pd_median=statistics.median(r["result"]["pd_final"] for r in rows),
            initial_J_median=statistics.median(r["result"]["initial_J"] for r in rows),
            improvement_from_initial_J_median=statistics.median(
                r["result"]["improvement_from_initial_J"] for r in rows),
            algorithm_wall_median_s=statistics.median(r["result"]["algorithm_wall_s"] for r in rows),
            algorithm_cpu_median_s=statistics.median(r["result"]["algorithm_cpu_s"] for r in rows),
            best_found_elapsed_median_s=statistics.median(r["result"]["best_found_elapsed_s"] for r in rows),
            diagonal_distance_fraction_median=statistics.median(
                r["result"]["physical_replay"]["diagonal_distance_fraction"] for r in rows),
            peak_rss_median_bytes=statistics.median(r["record"]["peak_rss_bytes"] for r in rows)))
    summary = dict(batch=config["batch"], stage_status=statuses, diagnostic_gate=gate,
                   decisions=decisions, aggregates=aggregates,
                   sensor_model_status=config["sensor_model_status"],
                   holdout="not_designed_not_run", long_budget="not_enabled",
                   historical_metrics="bridge only, never the new-model improvement target",
                   B30_does_not_rewrite_B5=True)
    save(out / "summary.json", summary, replace=True)
    fields = ["stage", "scene_or_case", "footprint", "connectivity", "method", "repetition",
              "seconds", "run_id", "record_status", "error", "J", "pd_final", "initial_J",
              "improvement_from_initial_J", "best_found_elapsed_s", "stop_reason",
              "algorithm_wall_s", "algorithm_cpu_s", "process_wall_s",
              "peak_rss_bytes", "budget_overshoot_s", "numerical_optimum_complete",
              "lower_bound", "physical_duration_s", "distance_m", "diagonal_distance_fraction",
              "physical_replay_json", "raw_result"]
    with (out / "comparison.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in all_rows:
            t, r, record = row["task"], row["result"], row["record"]
            writer.writerow(dict(stage=t["stage"], scene_or_case=t.get("scene", t.get("case")),
                footprint=t["footprint"], connectivity=t["connectivity"], method=t["method"],
                repetition=t["repetition"], seconds=t["seconds"], run_id=row["run_id"],
                record_status=record["status"],
                J=r["J"], pd_final=r["pd_final"], algorithm_wall_s=r["algorithm_wall_s"],
                initial_J=r["initial_J"], improvement_from_initial_J=r["improvement_from_initial_J"],
                best_found_elapsed_s=r["best_found_elapsed_s"], stop_reason=r["stop_reason"],
                algorithm_cpu_s=r["algorithm_cpu_s"],
                process_wall_s=record["process_wall_s"], peak_rss_bytes=record["peak_rss_bytes"],
                budget_overshoot_s=r["budget_overshoot_s"],
                numerical_optimum_complete=r["numerical_optimum_complete"], lower_bound=r["lower_bound"],
                physical_duration_s=r["physical_replay"]["physical_duration_s"],
                distance_m=r["physical_replay"]["distance_m"],
                diagonal_distance_fraction=r["physical_replay"]["diagonal_distance_fraction"],
                physical_replay_json=f"runs/{row['run_id']}/result.json#/result/physical_replay",
                raw_result=f"runs/{row['run_id']}/result.json"))
        for stage, status in statuses.items():
            errors = {e["run_id"]: e["error"] for e in status["errors"]}
            missing = set(status["missing"])
            for t in read(out / "tasks" / f"{stage}.json"):
                identity = task_id(t)
                if identity not in errors and identity not in missing:
                    continue
                writer.writerow(dict(stage=stage, scene_or_case=t.get("scene", t.get("case")),
                    footprint=t["footprint"], connectivity=t["connectivity"], method=t["method"],
                    repetition=t["repetition"], seconds=t["seconds"], run_id=identity,
                    record_status="incomplete_or_invalid" if identity in errors else "missing",
                    error=errors.get(identity, "not run")))
    lines = ["# 四／八邻接物理模型比较", "",
             "本报告仅汇总本目录记录。传感器是未校准的共同几何代理；结果不构成实飞收益或最优性证书。", "",
             "## 完成情况", "", "| 阶段 | 完成/计划 | 状态 |", "|---|---:|---|"]
    for stage, status in statuses.items():
        lines.append(f"| {stage} | {status['completed']}/{status['planned']} | {status['status']} |")
    lines += ["", f"A 正确性门槛：{gate['passed']}", "", "## 逐组质量", "",
              "J/Pd 分别取中位数，可能来自不同运行；范围不是置信区间。", "",
              "| 阶段 | 场景 | 覆盖 | 邻接 | 有效/计划 | J 中位数 [范围] | Pd 中位数 |",
              "|---|---|---|---:|---:|---:|---:|"]
    for a in aggregates:
        lines.append(f"| {a['stage']} | {a['scene']} | {a['footprint']} | {a['connectivity']} | "
                     f"{a['n']}/{a['planned']} | {a['J_median']:.9f} "
                     f"[{a['J_min']:.9f}, {a['J_max']:.9f}] | {a['Pd_median']:.9f} |")
    lines += ["", "## 预声明判断", ""]
    for stage, d in decisions.items():
        lines.append(f"- {stage}: {d['status']}；主质量通过={d['main_quality_pass']}，"
                     f"同预算覆盖敏感性通过={d['sensitivity_pass']}。")
    lines += ["", "物理时长、实际位置、沿途观测、对角比例与完整路线保存在每次 result.json。",
              "失败或缺失记录不会作为零改善加入中位数；B30 不改变 B5 的通过状态。",
              "没有预注册的跨模型旧参考 time-to-target，也没有自动长预算或独立档案实验。", ""]
    (out / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Summary written to {out}", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "preflight", "validate", "freeze", "run",
                                            "summarize", "_worker"))
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stage", choices=("A", "B5", "B30"))
    parser.add_argument("--task", type=Path)
    parser.add_argument("--result", type=Path)
    args = parser.parse_args(argv)
    config_path = args.config.resolve()
    config = read(config_path)
    common.set_threads(config)
    if args.command == "plan":
        print(json.dumps(plan(config), ensure_ascii=False, indent=2))
        return
    if args.out is None:
        parser.error("--out is required")
    out = args.out.resolve()
    if out == OUTPUT_ROOT.resolve() or not out.is_relative_to(OUTPUT_ROOT.resolve()):
        raise ValueError("Use a new child directory below the registered output root")
    if args.command == "preflight":
        preflight(config, config_path, out)
    elif args.command == "validate":
        validate(config, config_path, out)
    elif args.command == "freeze":
        freeze(config, config_path, out)
    elif args.command == "run":
        if args.stage is None:
            parser.error("--stage is required")
        run_stage(config, config_path, out, args.stage)
    elif args.command == "summarize":
        summarize(config, config_path, out)
    else:
        if args.task is None or args.result is None:
            parser.error("_worker requires --task and --result")
        try:
            worker(config, config_path, out, args.task, args.result)
        except Exception:
            if not args.result.exists():
                save(args.result, dict(task=read(args.task),
                     result=dict(status="failed", error=traceback.format_exc())))
            raise


if __name__ == "__main__":
    main()
