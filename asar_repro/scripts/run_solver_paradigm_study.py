#!/usr/bin/env python3
"""Prepare, freeze and execute the finite solver-paradigm study LOCALLY.

This file is delivered without executing experiments. No algorithm runs on
import. Commands are explicit; there is intentionally no automatic "all" stage.
All paths, scores and numerical solver claims are independently replayed.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
import csv
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
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
OUTPUT_ROOT = ROOT / "outputs/solver_paradigm_study_20261127"
DEFAULT_CONFIG = ROOT / "configs/solver_paradigm_study.json"
DETERMINISTIC = ("paper_baseline", "anytime_zero", "anytime_mass")
STOCHASTIC = ("ils", "cem")
PROTECTED_INVENTORY = ROOT / "docs/solver_paradigm_study/base_source_inventory.json"


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if hasattr(value, "tolist"):
        return clean(value.tolist())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def canonical(value):
    return json.dumps(clean(value), sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def object_digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, value, *, replace=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not replace:
        raise FileExistsError(f"Refusing to overwrite evidence: {path}")
    text = json.dumps(clean(value), ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def source_inventory(config_path):
    files = set((ROOT / "src/asar_repro").glob("*.py"))
    files.update((ROOT / "tests").glob("*.py"))
    files.update((ROOT / "scripts").glob("*.py"))
    files.update((ROOT / "configs").glob("*.json"))
    files.update({Path(config_path), PROTECTED_INVENTORY})
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(files)}


def protect_originals():
    inventory = read(PROTECTED_INVENTORY)
    for relative, expected in inventory["files"].items():
        path = REPO / relative
        # At least one historical Git blob already uses CRLF, and checkout may
        # also change line endings. The LF digest was anchored to the exact
        # base Git blob when this inventory was prepared.
        data = path.read_bytes().replace(b"\r\n", b"\n")
        actual = hashlib.sha256(data).hexdigest()
        if actual != inventory["canonical_lf_sha256"][relative]:
            raise ValueError(f"Protected baseline source changed: {relative}")
    return inventory["base_commit"]


def set_threads(config):
    for key, value in config["thread_environment"].items():
        os.environ[key] = str(value)


def child_environment():
    result = os.environ.copy()
    result.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    result["PYTHONPATH"] = str(ROOT / "src") + (
        os.pathsep + result["PYTHONPATH"] if result.get("PYTHONPATH") else "")
    return result


def environment():
    import psutil
    versions = {name: importlib.metadata.version(name)
                for name in ("numpy", "scipy", "pytest", "psutil")}
    try:
        from scipy.optimize._highspy import _core
        highs_version = _core._Highs().version()
    except (ImportError, AttributeError):
        highs_version = "unavailable_from_this_scipy_build"
    cpu_model = platform.processor()
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        cpu_model = next((line.split(":", 1)[1].strip()
                          for line in cpuinfo.read_text().splitlines()
                          if line.startswith("model name")), cpu_model)
    return dict(python=sys.version, executable=os.path.normcase(str(Path(sys.executable).resolve())),
                platform=platform.platform(), machine=platform.machine(),
                processor=cpu_model, cpu_count=os.cpu_count(),
                memory_total_bytes=psutil.virtual_memory().total, packages=versions,
                scipy_embedded_highs_version=highs_version,
                thread_environment={key: os.environ.get(key) for key in
                    ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                     "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS")})


def scene_inputs(config):
    from run_stdc_final_assessment import load_scene
    return {name: load_scene(config, name)[3] for name in config["primary_scenes"]}


def diagnostic_inputs():
    from asar_repro.count_oracle import diagnostic_cases, diagnostic_case_metadata
    return {case["id"]: diagnostic_case_metadata(case)
            for tier in ("tiny", "medium") for case in diagnostic_cases(tier=tier)}


def case_ids(config):
    return [f"{tier}_{family}_{variant}" for tier in config["diagnostic"]["tiers"]
            for family in config["diagnostic"]["families"]
            for variant in config["diagnostic"]["variants"]]


def make_tasks(config, stage, selected=None):
    tasks = []
    if stage == "A":
        settings = config["diagnostic"]
        for case in case_ids(config):
            tier = case.split("_")[0]
            for method in config["methods"]:
                tasks.append(dict(stage=stage, case=case, method=method,
                                  seconds=settings["solver_seconds"],
                                  seed=settings["solver_seed"], repetition=0))
            tasks.append(dict(stage=stage, case=case, method="count_oracle",
                              seconds=settings["count_seconds"][tier], seed=0, repetition=0))
            if tier == "tiny":
                tasks.append(dict(stage=stage, case=case, method="dfs",
                                  seconds=settings["dfs_seconds"], seed=0, repetition=0))
    elif stage in ("B5", "B30"):
        for scene in config["primary_scenes"]:
            for method in config["methods"]:
                seeds = ([0] * config["deterministic_repetitions"] if method in DETERMINISTIC
                         else config["optimizer_seeds"])
                for repetition, seed in enumerate(seeds):
                    tasks.append(dict(stage=stage, scene=scene, method=method,
                                      seconds=config["stages"][stage]["seconds"],
                                      seed=seed, repetition=repetition))
    elif stage == "C300":
        for method, scene in sorted(selected or []):
            if method not in STOCHASTIC or scene not in config["primary_scenes"]:
                raise ValueError("C300 selection outside preregistered methods/scenes")
            n = config["stages"][stage]["replications"]
            for repetition, seed in enumerate(config["optimizer_seeds"][:n]):
                tasks.append(dict(stage=stage, scene=scene, method=method,
                                  seconds=config["stages"][stage]["seconds"],
                                  seed=seed, repetition=repetition))
    else:
        raise ValueError(f"Unknown stage: {stage}")
    random.Random(config["task_order_seed"] + sum(map(ord, stage))).shuffle(tasks)
    return tasks


def task_id(task):
    return task["stage"] + "_" + object_digest(task)[:20]


def plan(config):
    result = {}
    for stage in ("A", "B5", "B30"):
        tasks = make_tasks(config, stage)
        result[stage] = dict(tasks=len(tasks), algorithm_budget_s=sum(t["seconds"] for t in tasks))
    selected = [(m, s) for m in STOCHASTIC for s in config["primary_scenes"]]
    tasks = make_tasks(config, "C300", selected)
    result["C300_maximum"] = dict(tasks=len(tasks),
                                algorithm_budget_s=sum(t["seconds"] for t in tasks),
                                gated=True)
    result["scope"] = "budget sums exclude startup, tests, IO, replay audit and watchdog overhead"
    result["status"] = "plan_only_not_results"
    return result


def preflight(config, config_path, out):
    protect_originals()
    missing_tests = [p for p in config["validation_tests"] if not (ROOT / p).is_file()]
    if missing_tests:
        raise FileNotFoundError(f"Validation tests missing: {missing_tests}")
    result = dict(status="preflight_passed_not_benchmarked", environment=environment(),
                  inputs=scene_inputs(config), diagnostic_inputs=diagnostic_inputs(),
                  source_sha256=source_inventory(config_path), plan=plan(config))
    if set(result["diagnostic_inputs"]) != set(case_ids(config)):
        raise ValueError("Diagnostic generator IDs differ from the frozen design")
    folder = out / "preflight" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    save(folder / "preflight.json", result)
    print(f"Preflight saved: {folder / 'preflight.json'}")


def validate(config, config_path, out):
    protect_originals()
    snapshot = source_inventory(config_path)
    folder = out / "validation" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder.mkdir(parents=True, exist_ok=False)
    xml = folder / "pytest.xml"
    command = [sys.executable, "-m", "pytest", "-q", *config["validation_tests"],
               f"--junitxml={xml}"]
    with (folder / "stdout.log").open("w", encoding="utf-8") as stdout:
        with (folder / "stderr.log").open("w", encoding="utf-8") as stderr:
            completed = subprocess.run(command, cwd=ROOT, env=child_environment(),
                                       stdout=stdout, stderr=stderr, check=False)
    testcases = ET.parse(xml).getroot().findall(".//testcase") if xml.exists() else []
    bad = [item for item in testcases
           if any(item.find(tag) is not None for tag in ("failure", "error", "skipped"))]
    unchanged = snapshot == source_inventory(config_path)
    passed = completed.returncode == 0 and bool(testcases) and not bad and unchanged
    result = dict(status="passed" if passed else "failed", command=command,
                  returncode=completed.returncode, testcase_count=len(testcases),
                  bad_or_skipped_count=len(bad), source_sha256=snapshot,
                  environment=environment(), source_unchanged=unchanged,
                  xml_sha256=digest(xml) if xml.exists() else None,
                  evidence_directory=str(folder.relative_to(out)))
    save(folder / "result.json", result)
    save(out / "validation/latest.json",
         dict(evidence_directory=str(folder.relative_to(out)),
              result_sha256=digest(folder / "result.json")), replace=True)
    print(f"Validation {result['status']}: {folder}")
    if not passed:
        raise RuntimeError("Local validation failed; no formal stage is enabled")


def freeze(config, config_path, out):
    if (out / "protocol.json").exists():
        verify(config, config_path, out)
        print("Existing protocol verified; not overwritten")
        return
    protect_originals()
    latest = read(out / "validation/latest.json")
    result_path = out / latest["evidence_directory"] / "result.json"
    if digest(result_path) != latest["result_sha256"]:
        raise ValueError("Validation evidence changed")
    validation = read(result_path)
    current = source_inventory(config_path)
    if validation["status"] != "passed" or validation["source_sha256"] != current:
        raise ValueError("Passing tests for this exact source/config are required before freeze")
    if validation["environment"] != environment():
        raise ValueError("Validation environment changed; validate again")
    xml = result_path.parent / "pytest.xml"
    if digest(xml) != validation["xml_sha256"]:
        raise ValueError("JUnit evidence changed")
    diagnostics = diagnostic_inputs()
    if set(diagnostics) != set(case_ids(config)):
        raise ValueError("Diagnostic generator and config disagree")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO,
                          capture_output=True, text=True, check=True).stdout.strip()
    protocol = dict(status="frozen_before_experiments", created_utc=datetime.now(timezone.utc).isoformat(),
                    git_head=head, config=config, source_sha256=current, environment=environment(),
                    inputs=scene_inputs(config), diagnostic_inputs=diagnostics,
                    validation=latest, validation_xml_sha256=validation["xml_sha256"],
                    plan=plan(config))
    save(out / "protocol.json", protocol)
    for stage in ("A", "B5", "B30"):
        save(out / "tasks" / f"{stage}.json", make_tasks(config, stage))
    print(f"Frozen: {out / 'protocol.json'}")


def verify(config, config_path, out):
    protocol = read(out / "protocol.json")
    if protocol["config"] != config or protocol["source_sha256"] != source_inventory(config_path):
        raise ValueError("Frozen source/config changed; use a NEW output directory and revalidate")
    protect_originals()
    if protocol["environment"] != environment():
        raise ValueError("Frozen environment differs from current interpreter/libraries/machine")
    result_path = out / protocol["validation"]["evidence_directory"] / "result.json"
    if digest(result_path) != protocol["validation"]["result_sha256"]:
        raise ValueError("Frozen validation result changed")
    if digest(result_path.parent / "pytest.xml") != protocol["validation_xml_sha256"]:
        raise ValueError("Frozen JUnit changed")
    for scene in config["primary_scenes"]:
        entry = config["scenes"][scene]
        for p, h in (("particle_path", "particle_sha256"), ("metadata_path", "metadata_sha256")):
            if digest(ROOT / entry[p]) != entry[h]:
                raise ValueError(f"Frozen input changed: {scene}/{p}")
    return protocol


def get_case(config, task):
    if "scene" in task:
        from run_stdc_final_assessment import load_scene
        return load_scene(config, task["scene"])
    from asar_repro.count_oracle import diagnostic_cases, diagnostic_case_metadata
    tier = task["case"].split("_")[0]
    case = next(c for c in diagnostic_cases(tier=tier) if c["id"] == task["case"])
    cfg = {key: case[key] for key in ("start", "budget", "p", "q", "motion")}
    scene = dict(initial_path=case["initial_path"], physical_direction_unverified=False)
    return case["grid"], cfg, scene, diagnostic_case_metadata(case)


def select_budget_history(history, seconds):
    """Keep only actual completed, replayed incumbents; no free t=0 seed."""
    result = []
    best = math.inf
    valid = [item for item in history
             if isinstance(item.get("elapsed_s"), (int, float))
             and math.isfinite(item["elapsed_s"]) and 0 <= item["elapsed_s"] <= seconds
             and isinstance(item.get("J"), (int, float)) and math.isfinite(item["J"])]
    # Filter NaN before sorting: NaN is unordered and can otherwise prevent
    # earlier valid incumbents from appearing before later improvements.
    for item in sorted(valid, key=lambda x: x["elapsed_s"]):
        value = item["J"]
        if value < best - 1e-10:
            result.append(item)
            best = value
    return result


def quality_targets(history, targets, reference_j, observation_end):
    values = {}
    for name, factor in targets.items():
        target = factor * reference_j
        hits = [h["elapsed_s"] for h in history if h["J"] <= target + 1e-10]
        values[name] = dict(target_J=target, reached=bool(hits),
                            time_s=min(hits) if hits else None,
                            censored=not hits, censor_time_s=None if hits else observation_end)
    return values


def worker(config, task, protocol):
    # Imports/immutable input IO are outside the planner budget, and their
    # process cost is separately measured by the parent. Algorithm preparation,
    # common PT copy/replay, guides, sampling, model construction and replay are in.
    from asar_repro.objective import score_path
    from asar_repro.search import search_asar
    from asar_repro.research_search import search_research
    from asar_repro.route_optimizers import solve_ils, solve_cem
    from asar_repro.count_oracle import solve_count_oracle
    from asar_repro.oracle import enumerate_oracle
    grid, cfg, scene, info = get_case(config, task)
    if "case" in task and info != protocol["diagnostic_inputs"][task["case"]]:
        raise ValueError("Diagnostic instance changed after freeze")
    actual_environment = environment()
    if actual_environment != protocol["environment"]:
        raise ValueError("Worker environment does not match protocol")
    started, cpu_started = time.perf_counter(), time.process_time()
    seconds = float(task["seconds"])
    initial = list(scene["initial_path"])
    seed_score = score_path(grid, initial, **cfg)
    prep_s = time.perf_counter() - started
    history = [dict(path=initial, J=seed_score.J, pd_final=seed_score.pd_final,
                    elapsed_s=prep_s, source="common_PT_replay")]
    method = task["method"]
    offset = time.perf_counter() - started
    remaining = max(0.0, seconds - offset)
    raw = {}
    if remaining <= 0:
        raw = dict(status="budget_exceeded", stop_reason="initialization_exhausted_budget")
    elif method in STOCHASTIC:
        function = solve_ils if method == "ils" else solve_cem
        raw = function(grid, **cfg, initial_path=initial, max_seconds=remaining,
                       seed=task["seed"], options=config[method])
    elif method in ("anytime_zero", "anytime_mass"):
        settings = config["search"]
        raw = asdict(search_research(
            grid, **cfg, initial_path=initial, max_seconds=remaining,
            bound_mode="zero" if method == "anytime_zero" else "mass_lb",
            **{key: settings[key] for key in ("guide_weight", "fast_guide", "portfolio",
                                             "cascade", "archive_candidates", "max_open")}))
    elif method == "paper_baseline":
        result = search_asar(grid, **cfg, initial_path=initial, heuristic="paper_greedy",
                             epsilon=config["search"]["epsilon"],
                             max_open=config["search"]["max_open"], max_seconds=remaining)
        raw = asdict(result)
        # This legacy API does not expose timestamps/paths for intermediate
        # incumbents. Only the returned and fully replayed route is observable.
        if result.path is not None:
            replay = score_path(grid, result.path, **cfg)
            if abs(replay.J - result.J) > config["tolerance"]:
                raise AssertionError("Legacy paper result failed replay")
            history.append(dict(path=list(result.path), J=replay.J, pd_final=replay.pd_final,
                                elapsed_s=time.perf_counter() - started,
                                source="paper_return_and_full_replay"))
    elif method == "count_oracle":
        raw = solve_count_oracle(grid, **cfg, initial_path=initial, max_seconds=remaining,
                                 options=config["count_oracle"])
    elif method == "dfs":
        result = enumerate_oracle(grid, **cfg)
        raw = asdict(result)
        # The tiny DFS API is protected by the parent watchdog. A result that
        # finishes after its requested cap is preserved but is not a timed proof.
        path = raw.get("path")
        if path is None:
            paths = raw.get("tied_paths") or []
            path = paths[0] if paths else None
        if path is None:
            raise ValueError("DFS returned no inspectable complete path")
        replay = score_path(grid, path, **cfg)
        history.append(dict(path=list(path), J=replay.J, pd_final=replay.pd_final,
                            elapsed_s=time.perf_counter() - started, source="dfs_complete"))
        raw.update(status="optimal_enumerated", J=replay.J, path=list(path),
                   lower_bound=replay.J, lower_bound_elapsed_s=time.perf_counter() - started)
    else:
        raise ValueError(f"Unknown method: {method}")
    algorithm_wall_s = time.perf_counter() - started
    algorithm_cpu_s = time.process_time() - cpu_started
    # The legacy APIs expose elapsed durations, not their absolute start clock.
    # Charging return/dispatch overhead conservatively avoids classifying a
    # just-late incumbent as on-time because of a few uncharged call instructions.
    inner_elapsed = raw.get("elapsed_s", raw.get("wall_s"))
    history_offset = offset
    if isinstance(inner_elapsed, (int, float)) and math.isfinite(inner_elapsed):
        history_offset = max(offset, algorithm_wall_s - inner_elapsed)
    method_state = str(raw.get("status", ""))
    failure_status = None
    if method_state.startswith("blocked"):
        failure_status = "blocked"
    elif raw.get("fatal") or method_state.startswith("fatal") or method_state == "solver_error":
        failure_status = "failed"
    for item in raw.get("history", raw.get("incumbent_history", [])):
        normalized = dict(item)
        normalized["elapsed_s"] = float(item["elapsed_s"]) + history_offset
        normalized["pd_final"] = item.get("pd_final", item.get("Pd"))
        history.append(normalized)
    accepted = select_budget_history(history, seconds)
    audit_started = time.perf_counter()
    for item in accepted:
        replay = score_path(grid, item["path"], **cfg)
        if (abs(replay.J - item["J"]) > config["tolerance"]
                or item["pd_final"] is None
                or abs(replay.pd_final - item["pd_final"]) > config["tolerance"]):
            raise AssertionError("Budgeted incumbent failed independent original scorer replay")
    best = accepted[-1] if accepted else None
    final_replay = score_path(grid, best["path"], **cfg) if best else None
    lower = raw.get("lower_bound")
    lower_when = raw.get("lower_bound_elapsed_s", raw.get("bound_completed_at_s"))
    if method == "dfs":
        lower_time = lower_when
    else:
        lower_time = None if lower_when is None else float(lower_when) + history_offset
    if (lower is None or lower_time is None or not math.isfinite(lower)
            or lower_time > seconds or best is None):
        lower = None
    elif lower > best["J"] + config["diagnostic"]["agreement_atol"]:
        raise AssertionError("Numerical lower bound exceeds replayed feasible upper bound")
    observed_end = min(seconds, algorithm_wall_s)
    result = dict(status=failure_status or ("valid" if best else "no_budgeted_solution"),
                  method_status=raw.get("status"), stop_reason=raw.get("stop_reason"),
                  path=None if best is None else best["path"],
                  J=None if best is None else best["J"],
                  pd_final=None if best is None else best["pd_final"],
                  survival=None if final_replay is None else final_replay.survival,
                  history=accepted, lower_bound=lower,
                  numerical_gap=None if lower is None else max(0.0, best["J"] - lower),
                  bound_scope="full diagnostic instance only" if "case" in task else None,
                  algorithm_wall_s=algorithm_wall_s, algorithm_cpu_s=algorithm_cpu_s,
                  preparation_wall_s=prep_s, audit_wall_s=time.perf_counter() - audit_started,
                  budget_overshoot_s=max(0.0, algorithm_wall_s - seconds),
                  raw_solver=raw, worker_environment=actual_environment, inputs=info,
                  theory_certified=False)
    if "scene" in task:
        result["targets"] = quality_targets(accepted, config["quality_targets"],
                                            config["scenes"][task["scene"]]["reference_J"],
                                            observed_end)
        reference = config["scenes"][task["scene"]]["reference_path"]
        result["final_first_divergence_from_historical_reference"] = (
            None if best is None else next(
                (t for t, (a, b) in enumerate(zip(best["path"], reference)) if a != b), None))
        result["final_equals_historical_reference"] = (
            None if best is None else list(best["path"]) == list(reference))
    return clean(result)


def read_record(out, task):
    folder = out / "runs" / task_id(task)
    record_path = folder / "record.json"
    if not record_path.exists():
        return None
    record = read(record_path)
    if record["task"] != task or record["protocol_sha256"] != digest(out / "protocol.json"):
        raise ValueError("Saved task/protocol mismatch")
    raw_path = folder / "result.json"
    if record["status"] != "completed":
        return dict(task=task, status=record["status"], record=record)
    if digest(raw_path) != record["result_sha256"]:
        raise ValueError("Raw result changed")
    payload = read(raw_path)
    if payload["task"] != task:
        raise ValueError("Raw task mismatch")
    return dict(task=task, status="completed", result=payload["result"], record=record)


def run_one(config, config_path, out, task):
    import psutil
    existing = read_record(out, task)
    if existing:
        if existing["status"] != "completed":
            raise RuntimeError("Previous failed task preserved; diagnose it and use a new batch directory")
        return
    folder = out / "runs" / task_id(task)
    if folder.exists():
        raise RuntimeError(f"Incomplete previous task directory preserved: {folder}")
    folder.mkdir(parents=True, exist_ok=False)
    save(folder / "task.json", task)
    command = [sys.executable, str(Path(__file__).resolve()), "_worker",
               "--config", str(config_path), "--out", str(out), "--task", str(folder / "task.json")]
    child_env = child_environment()
    started = time.perf_counter()
    peak_rss = 0
    killed = None
    with (folder / "stdout.log").open("w", encoding="utf-8") as stdout:
        with (folder / "stderr.log").open("w", encoding="utf-8") as stderr:
            proc = subprocess.Popen(command, cwd=ROOT, env=child_env, stdout=stdout, stderr=stderr)
            while proc.poll() is None:
                try:
                    process = psutil.Process(proc.pid)
                    relatives = process.children(recursive=True)
                    rss = process.memory_info().rss + sum(p.memory_info().rss for p in relatives)
                    peak_rss = max(peak_rss, rss)
                    if rss > config["watchdog"]["rss_bytes"]:
                        killed = "rss_watchdog"
                    if time.perf_counter() - started > task["seconds"] + config["watchdog"]["extra_seconds"]:
                        killed = killed or "process_wall_watchdog"
                    if killed:
                        for child in reversed(relatives):
                            try:
                                child.kill()
                            except psutil.NoSuchProcess:
                                pass
                        proc.kill()
                        break
                except psutil.NoSuchProcess:
                    pass
                time.sleep(config["watchdog"]["poll_seconds"])
            returncode = proc.wait()
    result_path = folder / "result.json"
    payload = read(result_path) if result_path.exists() else None
    completed = (returncode == 0 and killed is None and payload is not None
                 and payload.get("result", {}).get("status") == "valid")
    record_status = "completed" if completed else (
        "blocked" if payload and payload.get("result", {}).get("status") == "blocked" else "failed")
    record = dict(task=task, status=record_status,
                  protocol_sha256=digest(out / "protocol.json"), command=command,
                  returncode=returncode, watchdog_reason=killed,
                  process_wall_s=time.perf_counter() - started, peak_rss_bytes=peak_rss,
                  result_sha256=digest(result_path) if result_path.exists() else None)
    save(folder / "record.json", record)
    print(f"{task_id(task)} {record['status']} {task.get('scene', task.get('case'))} {task['method']}",
          flush=True)
    if not completed:
        raise RuntimeError(f"Task failed; stage stopped, evidence preserved in {folder}")


def stage_records(config, out, stage, selected=None):
    return [read_record(out, task) for task in make_tasks(config, stage, selected)]


def diagnostic_gate(config, out):
    expected = make_tasks(config, "A")
    records = [read_record(out, task) for task in expected]
    if any(r is None or r["status"] != "completed" for r in records):
        return dict(passed=False, reason="A incomplete or failed")
    for record in records:
        raw = record["result"].get("raw_solver", {})
        status = str(raw.get("status", ""))
        if (raw.get("fatal") or status.startswith(("fatal", "blocked"))
                or status == "solver_error"):
            return dict(passed=False, reason="A contains invalid solver evidence",
                        task=record["task"], method_status=status)
    by_case = defaultdict(dict)
    for record in records:
        by_case[record["task"]["case"]][record["task"]["method"]] = record["result"]
    checks = []
    atol = config["diagnostic"]["agreement_atol"]
    for case, methods in by_case.items():
        oracle = methods["count_oracle"]
        entry = dict(case=case, count_J=oracle["J"], count_L=oracle["lower_bound"],
                     interval_closed=oracle["lower_bound"] is not None
                     and oracle["J"] - oracle["lower_bound"] <= atol)
        best_feasible = min(value["J"] for value in methods.values())
        consistent_bound = oracle["lower_bound"] is None or oracle["lower_bound"] <= best_feasible + atol
        entry.update(best_feasible_J=best_feasible, bound_consistent_with_all_routes=consistent_bound)
        if case.startswith("tiny_"):
            dfs = methods["dfs"]
            complete = dfs["raw_solver"].get("status") == "optimal_enumerated" and dfs["lower_bound"] is not None
            numerical = oracle["raw_solver"]
            checked_optimal = (numerical.get("solver_status") == 0
                               and numerical.get("status") == "optimal_numeric"
                               and numerical.get("numerical_optimality_checked") is True
                               and numerical.get("optimality_scope") == "full_fixed_particle_discrete_instance"
                               and not numerical.get("fatal", False))
            entry["dfs_J"] = dfs["J"]
            entry["passed"] = bool(complete and checked_optimal and consistent_bound and entry["interval_closed"]
                                    and abs(oracle["J"] - dfs["J"]) <= atol)
            for method in config["methods"]:
                if methods[method]["J"] < dfs["J"] - atol:
                    entry["passed"] = False
                    entry["reason"] = "heuristic score below independent exhaustive optimum"
        else:
            # A numerical dual inconsistent with any independently replayed
            # feasible route is a failure even if its own MILP incumbent is worse.
            entry["passed"] = bool(consistent_bound)
        checks.append(entry)
    return dict(passed=all(c["passed"] for c in checks), checks=checks,
                scope="tiny original-scorer DFS agreement; medium may remain unclosed")


def group_rows(records):
    grouped = defaultdict(list)
    for record in records:
        if (record is not None and record["status"] == "completed"
                and record.get("result", {}).get("status") == "valid"):
            task = record["task"]
            grouped[(task.get("scene", task.get("case")), task["method"])].append(record["result"])
    return grouped


def engineering_decisions(config, records):
    """Engineering screen only. Never treat missing runs or censored targets as wins."""
    grouped = group_rows(records)
    expected = {m: config["deterministic_repetitions"] if m in DETERMINISTIC
                else len(config["optimizer_seeds"]) for m in config["methods"]}
    result = {}
    settings = config["decision"]
    for method in STOCHASTIC:
        per_scene = {}
        complete = True
        for scene in config["primary_scenes"]:
            rows = grouped.get((scene, method), [])
            controls = {m: grouped.get((scene, m), []) for m in ("anytime_zero", "anytime_mass")}
            if len(rows) != expected[method] or any(len(v) != expected[m] for m, v in controls.items()):
                complete = False
                per_scene[scene] = dict(complete=False)
                continue
            new_j = statistics.median(r["J"] for r in rows)
            control_j = {m: statistics.median(r["J"] for r in values) for m, values in controls.items()}
            best_control = min(control_j.values())
            gain = (best_control - new_j) / max(abs(best_control), 1e-15)
            no_regression = new_j <= best_control + settings["non_regression_relative_tolerance"] * max(abs(best_control), 1e-15)
            key = settings["time_target"]
            all_reached = all(r["targets"][key]["reached"] for r in rows)
            all_reached = all_reached and all(
                r["targets"][key]["reached"] for values in controls.values() for r in values)
            time_ratios = {}
            if all_reached:
                new_time = statistics.median(r["targets"][key]["time_s"] for r in rows)
                time_ratios = {m: new_time / max(statistics.median(r["targets"][key]["time_s"] for r in values), 1e-15)
                               for m, values in controls.items()}
            ref = config["scenes"][scene]["reference_J"]
            witnesses = sum(r["J"] < ref - config["strict_improvement_absolute"] for r in rows)
            per_scene[scene] = dict(complete=True, median_J=new_j, cheap_median_J=control_j,
                                    relative_gain=gain, no_regression=no_regression,
                                    all_targets_reached=all_reached, time_ratios=time_ratios,
                                    reference_strict_wins=witnesses)
        quality = complete and any(v["relative_gain"] >= settings["quality_relative_improvement"]
                                   for v in per_scene.values()) and all(v["no_regression"] for v in per_scene.values())
        speed = complete and all(v["no_regression"] and v["all_targets_reached"]
                                 and all(ratio <= 1 - settings["time_relative_reduction"] for ratio in v["time_ratios"].values())
                                 for v in per_scene.values())
        result[method] = dict(complete=complete, quality_pass=bool(quality),
                             time_pass=bool(speed), scenes=per_scene,
                             external_validation="not_run")
    return result


def aggregate_stage(config, stage, records):
    output = []
    for (case, method), values in sorted(group_rows(records).items()):
        expected = (1 if stage == "A" else config["stages"]["C300"]["replications"]
                    if stage == "C300" else config["deterministic_repetitions"]
                    if method in DETERMINISTIC else len(config["optimizer_seeds"]))
        entry = dict(scene_or_case=case, method=method, valid=len(values), planned=expected,
                     complete=len(values) == expected,
                     J_median=statistics.median(v["J"] for v in values),
                     J_min=min(v["J"] for v in values), J_max=max(v["J"] for v in values),
                     Pd_median=statistics.median(v["pd_final"] for v in values))
        key = config["decision"]["time_target"]
        available = [v["targets"][key] for v in values if key in v.get("targets", {})]
        if available:
            reached = [t["time_s"] for t in available if t["reached"]]
            entry.update(target_reached=len(reached), target_planned=expected,
                         target_all_reached=len(reached) == expected,
                         time_to_target_median_s=statistics.median(reached)
                         if len(reached) == expected else None,
                         reached_only_median_s=statistics.median(reached) if reached else None,
                         range_is_not_confidence_interval=True)
        output.append(entry)
    return output


def select_long(config, out):
    records = stage_records(config, out, "B30")
    if any(r is None or r["status"] != "completed" for r in records):
        raise RuntimeError("Complete valid B30 is required before C300 selection")
    decisions = engineering_decisions(config, records)
    selected = []
    for method, decision in decisions.items():
        for scene, data in decision["scenes"].items():
            if (data["reference_strict_wins"] >= config["decision"]["strict_witness_min_seeds"]
                    or decision["quality_pass"] or decision["time_pass"]):
                selected.append((method, scene))
    return selected, decisions


def run_stage(config, config_path, out, stage):
    verify(config, config_path, out)
    selected = None
    if stage in ("B5", "B30", "C300"):
        gate = diagnostic_gate(config, out)
        if not gate["passed"]:
            raise RuntimeError(f"A diagnostic gate not passed: {canonical(gate)}")
    if stage in ("B30", "C300"):
        b5 = stage_records(config, out, "B5")
        if any(r is None or r["status"] != "completed" for r in b5):
            raise RuntimeError("Complete B5 is required before B30/C300")
    if stage == "C300":
        selected, decisions = select_long(config, out)
        selection = dict(status="triggered" if selected else "not_triggered",
                         selected=selected, decisions=decisions,
                         b30_result_hashes={task_id(t): read_record(out, t)["record"]["result_sha256"]
                                           for t in make_tasks(config, "B30")})
        target = out / "C300_selection.json"
        if target.exists() and read(target) != clean(selection):
            raise ValueError("C300 preregistered selection evidence changed")
        if not target.exists():
            save(target, selection)
        if not selected:
            print("C300 not triggered; no long experiments executed")
            return
    tasks = make_tasks(config, stage, selected)
    manifest = out / "tasks" / f"{stage}.json"
    if not manifest.exists():
        save(manifest, tasks)
    if read(manifest) != tasks:
        raise ValueError("Frozen task order changed")
    for task in tasks:
        verify(config, config_path, out)
        run_one(config, config_path, out, task)
    print(f"Stage {stage} complete: {len(tasks)} tasks")


def summarize(config, config_path, out):
    verify(config, config_path, out)
    all_records = []
    stage_status = {}
    decisions = {}
    aggregates = {}
    for stage in ("A", "B5", "B30", "C300"):
        selected = None
        if stage == "C300":
            if not (out / "C300_selection.json").exists():
                stage_status[stage] = dict(status="not_evaluated", planned=0, completed=0, failed=0)
                continue
            selection = read(out / "C300_selection.json")
            selected = selection["selected"]
            if not selected:
                stage_status[stage] = dict(status="not_triggered", planned=0, completed=0, failed=0)
                continue
        tasks = make_tasks(config, stage, selected)
        records = [read_record(out, t) for t in tasks]
        complete = sum(r is not None and r["status"] == "completed" for r in records)
        failed = sum(r is not None and r["status"] != "completed" for r in records)
        stage_status[stage] = dict(status="complete" if complete == len(tasks) else
                                   ("not_run" if complete == 0 and failed == 0 else "incomplete"),
                                   planned=len(tasks), completed=complete, failed=failed)
        all_records.extend(r for r in records if r is not None)
        aggregates[stage] = aggregate_stage(config, stage, records)
        if stage in ("B5", "B30"):
            decisions[stage] = engineering_decisions(config, records)
    report = dict(batch=config["batch"], stage_status=stage_status, decisions=decisions,
                  aggregates=aggregates,
                  diagnostic_gate=diagnostic_gate(config, out),
                  holdout="not_designed_not_run", fundy="excluded_from_primary_matrix",
                  raw_results_are_not_cross_machine_speed_comparisons=True)
    save(out / "summary.json", report, replace=True)
    fields = ["stage", "scene_or_case", "method", "seconds", "seed", "repetition", "record_status",
              "J", "pd_final", "lower_bound", "numerical_gap", "algorithm_wall_s", "process_wall_s",
              "budget_overshoot_s", "peak_rss_bytes", "target_reached", "time_to_target_s",
              "target_censored", "censor_time_s", "raw_result"]
    with (out / "comparison.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in all_records:
            task = record["task"]
            value = record.get("result", {})
            target = value.get("targets", {}).get(config["decision"]["time_target"], {})
            writer.writerow(dict(stage=task["stage"], scene_or_case=task.get("scene", task.get("case")),
                method=task["method"], seconds=task["seconds"], seed=task["seed"],
                repetition=task["repetition"], record_status=record["status"],
                **{k: value.get(k) for k in ("J", "pd_final", "lower_bound", "numerical_gap",
                                           "algorithm_wall_s", "budget_overshoot_s")},
                process_wall_s=record["record"]["process_wall_s"],
                peak_rss_bytes=record["record"]["peak_rss_bytes"],
                target_reached=target.get("reached"), time_to_target_s=target.get("time_s"),
                target_censored=target.get("censored"), censor_time_s=target.get("censor_time_s"),
                raw_result=f"runs/{task_id(task)}/result.json"))
    lines = ["# 完整路线求解实验报告", "", "**本报告只汇总本目录实际记录；缺失不视为零改善。**", "",
             "## 阶段完成情况", "", "| 阶段 | 状态 | 完成/计划 | 失败 |", "|---|---|---:|---:|"]
    for stage, item in stage_status.items():
        lines.append(f"| {stage} | {item['status']} | {item['completed']}/{item['planned']} | {item['failed']} |")
    lines += ["", "## 两个主要场景的工程筛选", "",
              "B5 和 B30 独立报告；B30 的胜出不能回写为 B5 优势。严格参考改善不等于工程筛选通过。", "",
              "| 阶段 | 方法 | 完整 | 质量门槛 | 时间门槛 |", "|---|---|---|---|---|"]
    for stage, methods in decisions.items():
        for method, item in methods.items():
            lines.append(f"| {stage} | {method} | {item['complete']} | {item['quality_pass']} | {item['time_pass']} |")
    lines += ["", "## 实际数值", "",
              "J/Pd 为有效运行的中位数；不完整分组会标明有效/计划数，不参与通过判断。时间中位数只在全部计划运行达到目标时显示。",
              "J 范围是观测最小—最大，不是置信区间。", "",
              "| 阶段 | 场景 | 方法 | 有效/计划 | J中位数 [范围] | Pd中位数 | 达到目标 | 同质量中位秒 |",
              "|---|---|---|---:|---:|---:|---:|---:|"]
    for stage, groups in aggregates.items():
        if stage == "A":
            continue
        for item in groups:
            target_time = item.get("time_to_target_median_s")
            display_time = "—" if target_time is None else f"{target_time:.6f}"
            lines.append(
                f"| {stage} | {item['scene_or_case']} | {item['method']} | {item['valid']}/{item['planned']} | "
                f"{item['J_median']:.9f} [{item['J_min']:.9f}, {item['J_max']:.9f}] | "
                f"{item['Pd_median']:.9f} | {item.get('target_reached', 0)}/{item['planned']} | {display_time} |")
    lines += ["", "## 原始数值与解释边界", "",
              "逐次 J/Pd、下界、耗时、RSS 和达到时间见 comparison.csv；详细筛选见 summary.json。",
              "历史参考是已知可行解；count 的 dual 是对应完整诊断实例的数值界，不能推广到原真实场景。",
              "真实档案只含 Lake/Hudson；Fundy 不进入主结论。独立档案验证未设计、未运行。",
              "请填写 docs/solver_paradigm_study/results_template.md，解释路线变化、失败与下一步判断。", ""]
    (out / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Summary written: {out / 'REPORT.md'}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "preflight", "validate", "freeze", "run", "summarize", "_worker"))
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stage", choices=("A", "B5", "B30", "C300"))
    parser.add_argument("--task", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    config_path = args.config.resolve()
    config = read(config_path)
    set_threads(config)
    if args.command == "plan":
        print(json.dumps(plan(config), ensure_ascii=False, indent=2))
        return
    if args.out is None:
        parser.error("--out is required; use a new batch directory")
    out = args.out.resolve()
    if not out.is_relative_to(OUTPUT_ROOT.resolve()) or out == OUTPUT_ROOT.resolve():
        raise ValueError(f"--out must be a NEW child directory of {OUTPUT_ROOT}")
    if args.command == "_worker":
        if args.task is None:
            parser.error("--task is required for internal worker")
        protocol = verify(config, config_path, out)
        task = read(args.task)
        result = worker(config, task, protocol)
        save(args.task.parent / "result.json", dict(task=task, result=result))
        return
    out.mkdir(parents=True, exist_ok=True)
    if args.command == "preflight":
        preflight(config, config_path, out)
    elif args.command == "validate":
        validate(config, config_path, out)
    elif args.command == "freeze":
        freeze(config, config_path, out)
    elif args.command == "run":
        if args.stage is None:
            parser.error("--stage is required; no implicit all-stage execution")
        run_stage(config, config_path, out, args.stage)
    elif args.command == "summarize":
        summarize(config, config_path, out)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
