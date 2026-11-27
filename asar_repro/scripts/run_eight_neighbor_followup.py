#!/usr/bin/env python3
"""Local-only acceleration and same-forcing transfer study. Delivered not_run.

Explicit stages keep development decisions ahead of new particle generation.
Original source, scoring, archived results and the previous protocol are retained.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
import csv
import importlib
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
import run_eight_neighbor_physical as previous
import run_solver_paradigm_study as common

read, save, digest = common.read, common.save, common.digest
object_digest, clean = common.object_digest, common.clean
DEFAULT_CONFIG = ROOT / "configs/eight_neighbor_followup.json"
OUTPUT_ROOT = ROOT / "outputs/eight_neighbor_followup_20261127"
REGISTERED_CONFIG_HASH = "83004137823a037e44b02ffc271d2501dacbe93fad8d749f8fd06eef6b46910a"
STAGES = ("P0", "D5", "S30", "H30")


def stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def check_config(config):
    if object_digest(config) != REGISTERED_CONFIG_HASH:
        raise ValueError("Registered study configuration changed; label and register a new study version")
    if sys.version_info < (3, 11):
        raise ValueError("Use Python 3.11+ as required by the existing project")
    missing = [p for p in config["validation_tests"] if not (ROOT / p).is_file()]
    if missing:
        raise ValueError(f"Missing local validation files: {missing}")


def environment():
    result = previous.environment()
    for name in ("opendrift", "xarray", "PyYAML", "netCDF4", "shapely", "cfgrib", "eccodes", "numba"):
        try:
            version = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            version = "not_installed"
        result["packages"][name] = version
    return result


def generation_dependencies(env, *, check_imports=False):
    required = ("opendrift", "xarray", "PyYAML", "netCDF4", "shapely")
    errors = [f"Required generation package is missing: {name}" for name in required
              if env["packages"].get(name, "not_installed") == "not_installed"]
    shapely_version = env["packages"].get("shapely", "not_installed")
    if shapely_version != "not_installed" and int(shapely_version.split(".")[0]) < 2:
        errors.append("Existing forcing reader requires Shapely 2+ APIs")
    imported = []
    if check_imports and not errors:
        for module in ("opendrift.models.leeway", "asar_repro.historical_reader",
                       "asar_repro.forcing", "asar_repro.additional_forcing", "yaml"):
            try:
                importlib.import_module(module)
                imported.append(module)
            except Exception as exc:
                errors.append(f"Generation dependency import failed: {module}: {type(exc).__name__}: {exc}")
    return dict(status="ready" if not errors else "blocked", required=list(required),
                import_checks_requested=check_imports, imported=imported, errors=errors,
                drift_generation_performed=False)


def source_inventory(config_path):
    result = previous.source_inventory(config_path)
    for p in sorted((ROOT / "docs/eight_neighbor_followup").rglob("*.md")):
        result[p.relative_to(ROOT).as_posix()] = digest(p)
    path = ROOT / "requirements-physical-followup.txt"
    result[path.relative_to(ROOT).as_posix()] = digest(path)
    return dict(sorted(result.items()))


def original_config(config):
    return read(ROOT / config["previous_config"])


def task_id(task):
    return task["stage"] + "_" + object_digest(task)[:20]


def tasks_for(config, stage):
    tasks = []
    if stage in ("P0", "D5"):
        for scene in config["primary_scenes"]:
            for footprint in config["footprints"]:
                for connectivity in config["connectivities"]:
                    for backend in (["paired_audit"] if stage == "P0" else config["backends"]):
                        for repetition in range(1 if stage == "P0" else config["stages"][stage]["repetitions"]):
                            tasks.append(dict(stage=stage, scene=scene, footprint=footprint,
                                connectivity=connectivity, backend=backend, repetition=repetition,
                                seconds=config["audit"]["max_seconds"] if stage == "P0"
                                    else config["stages"][stage]["seconds"]))
    elif stage == "S30":
        tasks = [dict(stage=stage, case=case["id"], backend="original_paper",
                      repetition=0, seconds=config["stages"][stage]["seconds"])
                 for case in config["cases"]]
    elif stage == "H30":
        for case in config["cases"]:
            for footprint in config["footprints"]:
                for connectivity in config["connectivities"]:
                    for repetition in range(config["stages"][stage]["repetitions"]):
                        tasks.append(dict(stage=stage, case=case["id"], scene=case["base_scene"],
                            footprint=footprint, connectivity=connectivity, backend="selected",
                            repetition=repetition, seconds=config["stages"][stage]["seconds"]))
    else:
        raise ValueError(f"Unknown stage: {stage}")
    random.Random(config["task_order_seed"] + sum(map(ord, stage))).shuffle(tasks)
    return tasks


def plan(config):
    stages = {stage: dict(tasks=len(tasks_for(config, stage)),
               algorithm_budget_s=sum(t["seconds"] for t in tasks_for(config, stage)))
              for stage in ("D5", "S30", "H30")}
    return dict(status="plan_not_results", stages=stages,
        formal_tasks=sum(x["tasks"] for x in stages.values()),
        formal_algorithm_budget_s=sum(x["algorithm_budget_s"] for x in stages.values()),
        P0=dict(paired_audits=8, expansion_cap_each=config["audit"]["max_expansions"],
                wall_cap_each_s=config["audit"]["max_seconds"], performance_evidence=False),
        excluded_costs="pytest, P0 audits, forcing validation, drift generation, loading, startup, audit and IO",
        independence_level=config["holdout"]["independence_level"], H2="not_enabled", long_budget="not_enabled")


def preflight(config, config_path, out):
    from asar_repro.physical_followup_data import forcing_inventory
    check_config(config)
    protected = previous.protect_base(config)
    forcing = forcing_inventory(ROOT)
    env = environment()
    dependencies = generation_dependencies(env, check_imports=True)
    inputs = previous.inspect_inputs(original_config(config))
    result = dict(status="ready" if forcing["status"] == dependencies["status"] == "ready" else "blocked",
                  source_sha256=source_inventory(config_path), environment=env,
                  protected_base_sources=protected, forcing_inventory=forcing,
                  generation_dependencies=dependencies,
                  development_inputs=inputs, plan=plan(config))
    folder = out / "preflight" / stamp()
    save(folder / "preflight.json", result)
    save(out / "preflight/latest.json", dict(path=(folder / "preflight.json").relative_to(out).as_posix(),
         sha256=digest(folder / "preflight.json")), replace=True)
    print(f"Preflight {result['status']}: {folder}", flush=True)
    if result["status"] != "ready":
        raise ValueError("Read preflight.json: restore the audited B1 packages and compatible generation environment before freezing; no automatic download, substitution or installation")


def validate(config, config_path, out):
    check_config(config)
    previous.protect_base(config)
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
    cases = ET.parse(xml).getroot().findall(".//testcase") if xml.exists() else []
    bad = [x for x in cases if any(x.find(k) is not None for k in ("failure", "error", "skipped"))]
    unchanged = before == source_inventory(config_path) and env_before == environment()
    passed = result.returncode == 0 and bool(cases) and not bad and unchanged
    evidence = dict(status="passed" if passed else "failed", command=command,
        returncode=result.returncode, testcase_count=len(cases), bad_or_skipped_count=len(bad),
        unchanged=unchanged, source_sha256=before, environment=env_before,
        xml_sha256=digest(xml) if xml.exists() else None,
        evidence_directory=folder.relative_to(out).as_posix())
    save(folder / "result.json", evidence)
    save(out / "validation/latest.json", dict(evidence_directory=evidence["evidence_directory"],
         result_sha256=digest(folder / "result.json")), replace=True)
    print(f"Validation {evidence['status']}: {folder}", flush=True)
    if not passed:
        raise ValueError("Actual local validation must pass before freezing")


def freeze_dev(config, config_path, out):
    if (out / "protocol.json").exists():
        verify_dev(config, config_path, out)
        print("Existing development freeze verified; no overwrite", flush=True)
        return
    check_config(config)
    protected = previous.protect_base(config)
    preflight_ref = read(out / "preflight/latest.json")
    preflight_file = out / preflight_ref["path"]
    if digest(preflight_file) != preflight_ref["sha256"]:
        raise ValueError("Preflight evidence changed")
    pre = read(preflight_file)
    latest = read(out / "validation/latest.json")
    evidence_file = out / latest["evidence_directory"] / "result.json"
    evidence = read(evidence_file)
    if digest(evidence_file) != latest["result_sha256"]:
        raise ValueError("Validation evidence changed")
    inventory, env = source_inventory(config_path), environment()
    if (pre["status"] != "ready" or pre["source_sha256"] != inventory or pre["environment"] != env
        or evidence["status"] != "passed" or not evidence["unchanged"]
        or evidence["source_sha256"] != inventory or evidence["environment"] != env
        or evidence["testcase_count"] <= 0 or evidence["bad_or_skipped_count"]
        or digest(evidence_file.parent / "pytest.xml") != evidence["xml_sha256"]):
        raise ValueError("Ready preflight and passing tests for this exact code/environment are required")
    tasks = {s: tasks_for(config, s) for s in STAGES}
    protocol = dict(status="development_frozen_before_new_outcomes",
        created_utc=datetime.now(timezone.utc).isoformat(), config=config,
        git_head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
        source_sha256=inventory, environment=env, protected_base_sources=protected,
        preflight=preflight_ref, validation=latest, validation_xml_sha256=evidence["xml_sha256"],
        tasks_sha256={s: object_digest(t) for s, t in tasks.items()}, plan=plan(config))
    save(out / "protocol.json", protocol)
    for s, values in tasks.items():
        save(out / "tasks" / f"{s}.json", values)
    print("Development protocol and all task identities frozen; no benchmark launched", flush=True)


def verify_dev(config, config_path, out):
    protocol = read(out / "protocol.json")
    if protocol["config"] != config or protocol["source_sha256"] != source_inventory(config_path):
        raise ValueError("Frozen code/config/docs changed; retain evidence and use a new study directory")
    if protocol["environment"] != environment():
        raise ValueError("Frozen environment changed")
    for ref, path_key, sha_key in ((protocol["preflight"], "path", "sha256"),):
        if digest(out / ref[path_key]) != ref[sha_key]:
            raise ValueError("Frozen preflight changed")
    evidence = out / protocol["validation"]["evidence_directory"] / "result.json"
    if (digest(evidence) != protocol["validation"]["result_sha256"]
        or digest(evidence.parent / "pytest.xml") != protocol["validation_xml_sha256"]):
        raise ValueError("Frozen validation changed")
    legacy = read(ROOT / config["legacy_config"])
    for scene in config["primary_scenes"]:
        for path_key, hash_key in (("particle_path", "particle_sha256"), ("metadata_path", "metadata_sha256")):
            spec = legacy["scenes"][scene]
            if digest(ROOT / spec[path_key]) != spec[hash_key]:
                raise ValueError("Original development archive changed")
    for stage in STAGES:
        if object_digest(read(out / "tasks" / f"{stage}.json")) != protocol["tasks_sha256"][stage]:
            raise ValueError("Frozen task matrix changed")
    return protocol


def case_spec(config, case_id):
    return next(c for c in config["cases"] if c["id"] == case_id)


def file_inventory(folder, relative_to):
    return {p.relative_to(relative_to).as_posix(): digest(p)
            for p in sorted(folder.rglob("*")) if p.is_file()}


def verify_files(out, files):
    for path, sha in files.items():
        if digest(out / path) != sha:
            raise ValueError(f"Frozen evidence changed: {path}")


def verify_selection(out):
    selection = read(out / "selection.json")
    if selection["protocol_sha256"] != digest(out / "protocol.json"):
        raise ValueError("Backend selection uses another protocol")
    if selection["selected_backend"] not in ("original", "cached"):
        raise ValueError("Unknown selected backend")
    verify_files(out, selection["development_evidence"])
    return selection


def verify_prepared(out):
    selection = verify_selection(out)
    prepared = read(out / "prepared_inputs.json")
    if prepared["selection_sha256"] != digest(out / "selection.json"):
        raise ValueError("Particle generation must follow the locked backend selection")
    verify_files(out, prepared["files"])
    return prepared, selection


def verify_holdout(out):
    _, selection = verify_prepared(out)
    holdout = read(out / "holdout_protocol.json")
    if (holdout["protocol_sha256"] != digest(out / "protocol.json")
        or holdout["selection_sha256"] != digest(out / "selection.json")
        or holdout["prepared_inputs_sha256"] != digest(out / "prepared_inputs.json")
        or holdout["selected_backend"] != selection["selected_backend"]
        or holdout["task_matrix_sha256"] != object_digest(read(out / "tasks/H30.json"))):
        raise ValueError("Holdout freeze identity changed")
    verify_files(out, holdout["initialization_evidence"])
    return holdout


def stage_evidence(out, stage):
    result = {"protocol_sha256": digest(out / "protocol.json")}
    if stage == "H30":
        verify_holdout(out)
        result["holdout_protocol_sha256"] = digest(out / "holdout_protocol.json")
    elif stage == "S30":
        verify_prepared(out)
    if stage in ("S30", "H30"):
        result.update(selection_sha256=digest(out / "selection.json"),
                      prepared_inputs_sha256=digest(out / "prepared_inputs.json"))
    return result


def load_record(out, task, expected_evidence=None):
    folder = out / "runs" / task_id(task)
    if not folder.exists():
        return None
    record_path = folder / "record.json"
    if not record_path.exists():
        raise ValueError(f"Incomplete run directory preserved: {folder}")
    record = read(record_path)
    if expected_evidence is None:
        expected_evidence = stage_evidence(out, task["stage"])
    if record["task"] != task or record["frozen_evidence"] != expected_evidence:
        raise ValueError(f"Run identity mismatch: {folder}")
    if record["status"] != "completed":
        raise ValueError(f"Failed run preserved: {folder}")
    raw = folder / "result.json"
    if digest(raw) != record["result_sha256"]:
        raise ValueError(f"Raw result changed: {folder}")
    payload = read(raw)
    if payload["task"] != task or payload["result"]["status"] != "valid":
        raise ValueError("Record/result mismatch")
    if payload["result"].get("environment") != read(out / "protocol.json")["environment"]:
        raise ValueError("Recorded environment differs from frozen protocol")
    if task["stage"] in ("D5", "H30"):
        backend = task["backend"] if task["stage"] == "D5" else read(out / "selection.json")["selected_backend"]
        if payload["result"].get("backend") != backend:
            raise ValueError("Run backend differs from frozen selection")
    return dict(task=task, result=payload["result"], record=record, run_id=task_id(task))


def collect(out, stage):
    tasks = read(out / "tasks" / f"{stage}.json")
    protocol = read(out / "protocol.json")
    if object_digest(tasks) != protocol["tasks_sha256"][stage]:
        raise ValueError("Task matrix changed")
    rows, missing, errors, evidence = [], [], [], None
    for task in tasks:
        try:
            if evidence is None and (out / "runs" / task_id(task)).exists():
                evidence = stage_evidence(out, stage)
            row = load_record(out, task, evidence)
            if row is None:
                missing.append(task_id(task))
            else:
                rows.append(row)
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            errors.append(dict(run_id=task_id(task), error=str(exc)))
    return dict(stage=stage, planned=len(tasks), completed=len(rows),
        status="complete" if len(rows) == len(tasks) and not errors else "incomplete_or_invalid",
        missing=missing, errors=errors), rows


def require_complete(out, stage):
    status, rows = collect(out, stage)
    if status["status"] != "complete":
        raise ValueError(f"{stage} must be complete and valid")
    return rows


def evidence_for_rows(out, rows):
    result = {}
    for row in rows:
        folder = out / "runs" / row["run_id"]
        for name in ("record.json", "result.json"):
            path = folder / name
            result[path.relative_to(out).as_posix()] = digest(path)
    return result


def time_to_target(result, target, tolerance):
    times = [h["elapsed_s"] for h in result["history"] if h["J"] <= target + tolerance]
    return min(times) if times else None


def development_decision(config, rows, complete):
    if not complete:
        return dict(status="incomplete_or_invalid", selected_backend=None)
    expected = tasks_for(config, "D5")
    if (len(rows) != len(expected) or {object_digest(r["task"]) for r in rows}
        != {object_digest(t) for t in expected}):
        return dict(status="incomplete_or_invalid", selected_backend=None)
    groups = defaultdict(list)
    for row in rows:
        task = row["task"]
        if not math.isfinite(row["result"]["J"]):
            return dict(status="incomplete_or_invalid", selected_backend=None)
        groups[(task["scene"], task["footprint"], task["connectivity"], task["backend"])].append(row)
    quality = []
    for scene in config["primary_scenes"]:
        for footprint in config["footprints"]:
            for connectivity in config["connectivities"]:
                a = statistics.median(r["result"]["J"] for r in groups[(scene, footprint, connectivity, "original")])
                b = statistics.median(r["result"]["J"] for r in groups[(scene, footprint, connectivity, "cached")])
                gain = (a-b)/max(abs(a), 1e-15)
                quality.append(dict(scene=scene, footprint=footprint, connectivity=connectivity,
                    original_J=a, cached_J=b, relative_gain=gain,
                    non_regression=gain >= -config["tolerance"]["quality_relative"]))
    targets, more_hits, faster_groups = [], 0, 0
    hit_protected = True
    reps = config["stages"]["D5"]["repetitions"]
    for target in config["development_targets"]:
        values = {}
        for backend in config["backends"]:
            rr = groups[(target["scene"], target["footprint"], target["connectivity"], backend)]
            times = [time_to_target(r["result"], target["J"], config["tolerance"]["target_absolute"]) for r in rr]
            hit = [t for t in times if t is not None]
            values[backend] = dict(hit_count=len(hit), planned=reps, times_s=times,
                median_if_all_hit_s=statistics.median(hit) if len(hit) == reps else None,
                non_hit="right_censored_at_5s_not_a_measured_target_time")
        original, cached = values["original"], values["cached"]
        hit_protected &= cached["hit_count"] >= original["hit_count"]
        more_hits += int(cached["hit_count"] > original["hit_count"])
        reduction = None
        if original["hit_count"] == cached["hit_count"] == reps:
            original_time, cached_time = original["median_if_all_hit_s"], cached["median_if_all_hit_s"]
            if original_time > 0:
                reduction = 1-cached_time/original_time
                # Compare times directly so exactly 4.0 -> 3.6 seconds is
                # accepted at the registered 10% boundary despite subtraction rounding.
                faster_groups += int(cached_time <=
                    (1-config["selection"]["min_relative_time_reduction"])*original_time)
        targets.append(dict(target=target, backends=values, relative_time_reduction=reduction))
    protected = all(q["non_regression"] for q in quality) and hit_protected
    signal = (more_hits >= config["selection"]["min_improved_target_hit_groups"]
              or faster_groups >= config["selection"]["alternative_full_hit_speed_groups"])
    accepted = protected and signal
    return dict(status="acceleration_screen_passed" if accepted else "acceleration_screen_not_passed",
        selected_backend="cached" if accepted else "original",
        quality_protected=all(q["non_regression"] for q in quality),
        target_hit_counts_protected=hit_protected, improved_hit_groups=more_hits,
        full_hit_faster_groups=faster_groups, quality=quality, targets=targets,
        scope="development archives only; prospective targets derived from previous B30, no change to old B5")


def select_backend(config, config_path, out):
    verify_dev(config, config_path, out)
    audit = require_complete(out, "P0")
    rows = require_complete(out, "D5")
    if any(not r["result"]["audit"]["passed"] for r in audit):
        raise ValueError("Strict equivalence audit failed")
    decision = development_decision(config, rows, True)
    selection = dict(protocol_sha256=digest(out / "protocol.json"),
        selected_backend=decision["selected_backend"], decision=decision,
        development_evidence=evidence_for_rows(out, audit+rows))
    path = out / "selection.json"
    if path.exists():
        if read(path) != selection:
            raise ValueError("Locked backend selection cannot be replaced")
        verify_selection(out)
    else:
        if (out / "inputs").exists() or (out / "prepared_inputs.json").exists():
            raise ValueError("Backend must be locked before new particle preparation")
        save(path, selection)
    print(f"Backend locked: {selection['selected_backend']} ({decision['status']})", flush=True)


def prepare_inputs(config, config_path, out):
    from asar_repro.physical_followup_data import forcing_inventory, prepare_case, load_prepared_case
    protocol = verify_dev(config, config_path, out)
    verify_selection(out)
    if (out / "prepared_inputs.json").exists():
        verify_prepared(out)
        print("Prepared inputs verified; no regeneration", flush=True)
        return
    expected_forcing = read(out / protocol["preflight"]["path"])["forcing_inventory"]
    actual = forcing_inventory(ROOT)
    if actual["status"] != "ready" or actual != expected_forcing:
        raise ValueError("Audited forcing differs from preflight; no substitutes are allowed")
    case_records = {}
    for case in config["cases"]:
        destination = out / "inputs" / case["id"]
        if destination.exists():
            if not (destination / "manifest.json").exists() or (destination / "failure.json").exists():
                raise ValueError(f"Failed/incomplete input preparation preserved: {destination}")
            _, _, _, info = load_prepared_case(ROOT, case, destination, "axis_square")
        else:
            prepare_case(ROOT, case, destination)
            _, _, _, info = load_prepared_case(ROOT, case, destination, "axis_square")
        case_records[case["id"]] = info
        print(f"Prepared {case['id']}", flush=True)
    verify_dev(config, config_path, out)
    save(out / "prepared_inputs.json", dict(
        status="all_four_new_archives_prepared_before_holdout_search",
        selection_sha256=digest(out / "selection.json"),
        independence_level=config["holdout"]["independence_level"],
        cases=case_records, files=file_inventory(out / "inputs", out)))
    print("Four H1 archives prepared; no H30 search launched", flush=True)


def seed_for_case(out, case_id):
    tasks = read(out / "tasks/S30.json")
    task = next(t for t in tasks if t["case"] == case_id)
    row = load_record(out, task)
    if row is None:
        raise ValueError("Missing shared initialization")
    return row["result"]["waypoints"], row


def freeze_holdout(config, config_path, out):
    verify_dev(config, config_path, out)
    prepared, selection = verify_prepared(out)
    rows = require_complete(out, "S30")
    if set(prepared["cases"]) != {c["id"] for c in config["cases"]}:
        raise ValueError("All four registered archives are required")
    result = dict(status="holdout_frozen_before_H30",
        protocol_sha256=digest(out / "protocol.json"),
        selection_sha256=digest(out / "selection.json"),
        prepared_inputs_sha256=digest(out / "prepared_inputs.json"),
        selected_backend=selection["selected_backend"],
        initialization_evidence=evidence_for_rows(out, rows),
        common_paths={r["task"]["case"]:r["result"]["waypoints"] for r in rows},
        independence_level=config["holdout"]["independence_level"],
        task_matrix_sha256=object_digest(read(out / "tasks/H30.json")))
    path = out / "holdout_protocol.json"
    if path.exists():
        if read(path) != result:
            raise ValueError("Frozen holdout cannot be replaced")
        verify_holdout(out)
    else:
        save(path, result)
    print("All inputs and shared routes frozen; H30 remains an explicit command", flush=True)


def audit_search_result(problem, seed, task, raw, external_wall, cpu_s, tolerance):
    if raw.get("status") in ("failed", "blocked", "fatal", "invalid", "solver_error"):
        raise ValueError(f"Backend failed; cannot conceal error with initial route: {raw.get('error')}")
    internal = raw.get("wall_s")
    if not isinstance(internal, (int,float)) or not math.isfinite(internal) or internal < 0:
        raise ValueError("Invalid backend clock")
    offset = max(0.0, external_wall-internal)
    history = previous.selected_history(raw, task["seconds"], offset)
    if (not history or history[0].get("source") != "initial_route"
        or history[0].get("waypoints", history[0].get("path")) != list(seed)):
        raise ValueError("Shared initial route not fully evaluated inside budget")
    audit_started = time.perf_counter()
    last = math.inf
    for entry in history:
        score = problem.replay(entry.get("waypoints", entry.get("path")), task["connectivity"])
        if (abs(score["J"]-entry["J"]) > tolerance
            or abs(score["pd_final"]-entry["pd_final"]) > tolerance
            or entry["J"] > last+tolerance):
            raise ValueError("Physical replay or monotone-incumbent audit failed")
        last = entry["J"]
    best = min(history, key=lambda h:h["J"])
    score = problem.replay(best.get("waypoints", best.get("path")), task["connectivity"])
    return dict(status="valid", J=score["J"], pd_final=score["pd_final"],
        initial_J=history[0]["J"], improvement_from_initial_J=history[0]["J"]-score["J"],
        best_found_elapsed_s=best["elapsed_s"], history=history,
        physical_replay=score, raw_solver=raw, stop_reason=raw.get("stop_reason"),
        algorithm_wall_s=external_wall, algorithm_cpu_s=cpu_s,
        inner_wall_s=internal, conservative_clock_offset_s=offset,
        budget_overshoot_s=max(0.0,external_wall-task["seconds"]),
        audit_wall_s=time.perf_counter()-audit_started, formal_optimality_certificate=False)


def initialize_case(config, task, problem, grid, discrete_cfg, other_problem):
    from asar_repro.scenario_baselines import parallel_track
    from asar_repro.search import search_asar
    from asar_repro.objective import score_path
    started, cpu = time.perf_counter(), time.process_time()
    initial = parallel_track(grid, **discrete_cfg)
    physical = problem.replay(initial, 4)
    discrete = score_path(grid, initial, **discrete_cfg)
    tolerance = config["tolerance"]["score_absolute"]
    if abs(physical["J"]-discrete.J)>tolerance or abs(physical["pd_final"]-discrete.pd_final)>tolerance:
        raise ValueError("New archive axis-square PT bridge failed")
    first_elapsed = time.perf_counter()-started
    if first_elapsed > task["seconds"]:
        raise ValueError("PT initialization did not finish in budget")
    best = dict(waypoints=list(initial), J=physical["J"], pd_final=physical["pd_final"],
                elapsed_s=first_elapsed, source="parallel_track",
                bridge=dict(discrete_J=discrete.J, discrete_pd_final=discrete.pd_final,
                            physical_J=physical["J"], physical_pd_final=physical["pd_final"]))
    history = [best.copy()]
    remaining = task["seconds"]-(time.perf_counter()-started)-config["initialization"]["final_replay_reserve_seconds"]
    raw = None
    late = []
    if remaining > 0:
        result = search_asar(grid, **discrete_cfg, heuristic="paper_greedy",
            epsilon=config["initialization"]["epsilon"], max_open=config["initialization"]["max_open"],
            initial_path=initial, max_seconds=remaining)
        raw = asdict(result)
        if result.path is None or result.status not in ("completed","budget_exceeded"):
            raise ValueError("Original paper initialization failed")
        score = problem.replay(result.path, 4)
        discrete_candidate = score_path(grid, result.path, **discrete_cfg)
        elapsed = time.perf_counter()-started
        if (abs(score["J"]-result.J)>tolerance
            or abs(score["J"]-discrete_candidate.J)>tolerance
            or abs(score["pd_final"]-discrete_candidate.pd_final)>tolerance):
            raise ValueError("Original paper/physical initialization disagreement")
        candidate = dict(waypoints=list(result.path), J=score["J"], pd_final=score["pd_final"],
                         elapsed_s=elapsed, source="original_paper_greedy",
                         bridge=dict(discrete_J=discrete_candidate.J,
                                     discrete_pd_final=discrete_candidate.pd_final,
                                     physical_J=score["J"], physical_pd_final=score["pd_final"]))
        if elapsed <= task["seconds"]:
            if candidate["J"] < best["J"]:
                best = candidate
                history.append(candidate.copy())
        else:
            late.append(candidate)
    algorithm_wall = time.perf_counter()-started
    cpu_s = time.process_time()-cpu
    # Independent post-run documentation for both proxies; not additional search.
    scores = {"axis_square":problem.replay(best["waypoints"],4),
              "heading_square":other_problem.replay(best["waypoints"],4)}
    return dict(status="valid", waypoints=best["waypoints"], J=best["J"], pd_final=best["pd_final"],
        history=history, late_candidates=late, raw_solver=raw, stop_reason=None if raw is None else raw["stop_reason"],
        algorithm_wall_s=algorithm_wall, algorithm_cpu_s=cpu_s,
        budget_overshoot_s=max(0.0,algorithm_wall-task["seconds"]),
        physical_replays=scores, physical_replay=scores["axis_square"],
        bridge=best["bridge"],
        initial_J=history[0]["J"], best_found_elapsed_s=best["elapsed_s"],
        initialization_scope=config["initialization"]["generation_cost"],
        formal_optimality_certificate=False)


def worker(config, config_path, out, task_path, result_path):
    verify_dev(config, config_path, out)
    task = read(task_path)
    if task not in read(out / "tasks" / f"{task['stage']}.json"):
        raise ValueError("Task is not in frozen matrix")
    evidence_before = stage_evidence(out, task["stage"])
    from asar_repro.physical_search import solve_physical
    from asar_repro.physical_accel import solve_physical_accel, audit_equivalence
    if task["stage"] in ("P0","D5"):
        problem, seed, _, info = previous.load_real_problem(original_config(config),
                                                           task["scene"],task["footprint"])
    else:
        from asar_repro.physical_followup_data import load_prepared_case
        case = case_spec(config,task["case"])
        problem, grid, discrete_cfg, info = load_prepared_case(
            ROOT,case,out/"inputs"/case["id"],task.get("footprint","axis_square"))
        if task["stage"] == "H30":
            seed, _ = seed_for_case(out, task["case"])
    if task["stage"] == "P0":
        audit = audit_equivalence(problem, connectivity=task["connectivity"], initial_waypoints=seed,
            max_expansions=config["audit"]["max_expansions"], max_seconds=task["seconds"],
            guide_weight=config["search"]["guide_weight"])
        if not audit["passed"]:
            raise ValueError(f"Strict real-input equivalence failed: {audit}")
        result = dict(status="valid", audit=audit, inputs=info, performance_evidence=False)
    elif task["stage"] == "S30":
        other, _, _, _ = load_prepared_case(ROOT,case,out/"inputs"/case["id"],"heading_square")
        result = initialize_case(config,task,problem,grid,discrete_cfg,other)
        result["inputs"] = info
    else:
        backend = task["backend"] if task["stage"] == "D5" else verify_selection(out)["selected_backend"]
        fn = solve_physical if backend == "original" else solve_physical_accel
        started, cpu = time.perf_counter(), time.process_time()
        raw = fn(problem, connectivity=task["connectivity"], initial_waypoints=seed,
                 max_seconds=task["seconds"], **config["search"])
        wall, cpu_s = time.perf_counter()-started, time.process_time()-cpu
        result = audit_search_result(problem,seed,task,raw,wall,cpu_s,config["tolerance"]["score_absolute"])
        result.update(backend=backend,inputs=info)
    protocol = verify_dev(config, config_path, out)
    if stage_evidence(out, task["stage"]) != evidence_before:
        raise ValueError("Frozen stage evidence changed during worker execution")
    result["environment"] = environment()
    if result["environment"] != protocol["environment"]:
        raise ValueError("Worker environment changed during execution")
    save(result_path,dict(task=task,result=result))


def launch_task(config, config_path, out, task):
    import psutil
    existing = load_record(out,task)
    if existing is not None:
        print(f"Verified existing {task_id(task)}",flush=True)
        return existing
    frozen = stage_evidence(out,task["stage"])
    folder=out/"runs"/task_id(task)
    folder.mkdir(parents=True,exist_ok=False)
    save(folder/"task.json",task)
    command=[sys.executable,str(Path(__file__).resolve()),"_worker","--config",str(config_path),
             "--out",str(out),"--task",str(folder/"task.json"),"--result",str(folder/"result.json")]
    started,peak,killed=time.perf_counter(),0,None
    with (folder/"stdout.log").open("w",encoding="utf-8") as stdout, \
         (folder/"stderr.log").open("w",encoding="utf-8") as stderr:
        child=subprocess.Popen(command,cwd=ROOT,env=common.child_environment(),stdout=stdout,stderr=stderr)
        process=None
        while child.poll() is None:
            relatives=[]
            try:
                if process is None:
                    process=psutil.Process(child.pid)
                relatives=process.children(recursive=True)
                rss=process.memory_info().rss+sum(p.memory_info().rss for p in relatives)
                peak=max(peak,rss)
                if rss>config["watchdog"]["rss_limit_bytes"]:
                    killed="rss_limit"
            except psutil.Error:
                pass
            if time.perf_counter()-started>task["seconds"]+config["watchdog"]["grace_seconds"]:
                killed=killed or "process_watchdog"
            if killed:
                for descendant in reversed(relatives):
                    try:
                        descendant.kill()
                    except psutil.Error:
                        pass
                child.kill()
                break
            time.sleep(config["watchdog"]["poll_seconds"])
        returncode=child.wait()
    raw=folder/"result.json"
    valid=False
    if raw.exists():
        payload=read(raw)
        valid=payload.get("task")==task and payload.get("result",{}).get("status")=="valid"
    record=dict(task=task,command=command,frozen_evidence=frozen,
        status="completed" if returncode==0 and not killed and valid else "failed",
        returncode=returncode,watchdog=killed,process_wall_s=time.perf_counter()-started,
        peak_rss_bytes=peak,result_sha256=digest(raw) if raw.exists() else None)
    save(folder/"record.json",record)
    if record["status"]!="completed":
        raise RuntimeError(f"Failed run preserved; stage stopped: {folder}")
    print(f"Completed {task_id(task)}",flush=True)
    return load_record(out,task)


def run_stage(config, config_path, out, stage):
    verify_dev(config,config_path,out)
    if stage=="D5":
        audit=require_complete(out,"P0")
        if any(not r["result"]["audit"]["passed"] for r in audit):
            raise ValueError("Strict equivalence audit is required")
        if (out/"selection.json").exists():
            # Resuming a fully verified dev run is harmless; new measurements
            # after backend locking or holdout exposure are not permitted.
            require_complete(out,"D5")
    if stage=="S30":
        verify_prepared(out)
    if stage=="H30":
        verify_holdout(out)
    for task in read(out/"tasks"/f"{stage}.json"):
        launch_task(config,config_path,out,task)
    summarize(config,config_path,out)


def holdout_decision(config, rows, complete):
    if not complete:
        return dict(status="incomplete_or_invalid")
    expected=tasks_for(config,"H30")
    if len(rows)!=len(expected) or {object_digest(r["task"]) for r in rows}!={object_digest(t) for t in expected}:
        return dict(status="incomplete_or_invalid")
    groups=defaultdict(list)
    backends=set()
    for row in rows:
        t,r=row["task"],row["result"]
        if not math.isfinite(r["J"]):
            return dict(status="incomplete_or_invalid")
        groups[(t["case"],t["footprint"],t["connectivity"])].append(r["J"])
        backends.add(r["backend"])
    if len(backends)!=1 or not backends.issubset(set(config["backends"])):
        return dict(status="incomplete_or_invalid",reason="mixed_or_unknown_backends")
    comparisons={}
    for footprint in config["footprints"]:
        comparisons[footprint]={}
        for case in config["cases"]:
            j4=statistics.median(groups[(case["id"],footprint,4)])
            j8=statistics.median(groups[(case["id"],footprint,8)])
            comparisons[footprint][case["id"]]=dict(J4=j4,J8=j8,relative_gain=(j4-j8)/max(abs(j4),1e-15))
    rules=config["holdout"]
    main=comparisons["heading_square"]; axis=comparisons["axis_square"]
    winners=[case for case,row in main.items() if row["relative_gain"]>=rules["primary_relative_gain"]]
    quality=(len(winners)>=rules["min_primary_winners"] and
             all(r["relative_gain"]>=-rules["primary_non_regression_relative"] for r in main.values()))
    sensitivity=(bool(winners) and any(axis[c]["relative_gain"]>rules["axis_positive_relative"] for c in winners)
                 and all(r["relative_gain"]>=-rules["axis_max_regression_relative"] for r in axis.values()))
    per_scene={scene:sum(c["id"] in winners for c in config["cases"] if c["base_scene"]==scene)
               for scene in config["primary_scenes"]}
    scene_specific=bool(winners) and sum(n>0 for n in per_scene.values())==1
    status=("within_forcing_scene_specific_signal" if quality and sensitivity and scene_specific
            else "within_forcing_transfer_signal" if quality and sensitivity
            else "within_forcing_sensor_sensitive" if quality else "within_forcing_screen_not_passed")
    return dict(status=status,main_quality_pass=quality,sensitivity_pass=sensitivity,
        primary_winners=winners,winners_by_scene=per_scene,comparisons=comparisons,
        backend=next(iter(backends)),independence_level=rules["independence_level"],
        independent_weather_generalization=False)


def summarize(config, config_path, out):
    verify_dev(config,config_path,out)
    statuses,rows_by={},{}
    for stage in STAGES:
        status,rows=collect(out,stage)
        statuses[stage],rows_by[stage]=status,rows
    p0_ok=statuses["P0"]["status"]=="complete" and all(r["result"]["audit"]["passed"] for r in rows_by["P0"])
    dev=development_decision(config,rows_by["D5"],p0_ok and statuses["D5"]["status"]=="complete")
    holdout=holdout_decision(config,rows_by["H30"],p0_ok and statuses["H30"]["status"]=="complete")
    aggregates=[]
    groups=defaultdict(list)
    for stage in ("D5","H30"):
        for row in rows_by[stage]:
            t,r=row["task"],row["result"]
            groups[(stage,t.get("case",t.get("scene")),t["footprint"],t["connectivity"],r["backend"])].append(row)
    for key,rr in sorted(groups.items()):
        stage,case,footprint,connectivity,backend=key
        values=[r["result"]["J"] for r in rr]
        aggregates.append(dict(stage=stage,case_or_scene=case,footprint=footprint,
            connectivity=connectivity,backend=backend,n=len(rr),
            planned=config["stages"][stage]["repetitions"],J_median=statistics.median(values),
            J_min=min(values),J_max=max(values),
            Pd_median=statistics.median(r["result"]["pd_final"] for r in rr),
            algorithm_wall_median_s=statistics.median(r["result"]["algorithm_wall_s"] for r in rr),
            peak_rss_median_bytes=statistics.median(r["record"]["peak_rss_bytes"] for r in rr)))
    summary=dict(batch=config["batch"],stage_status=statuses,equivalence_passed=p0_ok,
        development_decision=dev,holdout_decision=holdout,aggregates=aggregates,
        selected_backend=read(out/"selection.json")["selected_backend"] if (out/"selection.json").exists() else None,
        H2="not_enabled_requires_new_forcing",long_budget="not_enabled")
    save(out/"summary.json",summary,replace=True)
    fields=["stage","case_or_scene","footprint","connectivity","backend","repetition","seconds","run_id",
            "status","error","J","pd_final","initial_J","best_found_elapsed_s","algorithm_wall_s",
            "algorithm_cpu_s","process_wall_s","peak_rss_bytes","budget_overshoot_s",
            "physical_duration_s","distance_m","diagonal_distance_fraction","stop_reason","raw_result"]
    with (out/"comparison.csv").open("w",encoding="utf-8",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        for stage in STAGES:
            by_id={r["run_id"]:r for r in rows_by[stage]}
            errors={e["run_id"]:e["error"] for e in statuses[stage]["errors"]}
            for t in read(out/"tasks"/f"{stage}.json"):
                identity=task_id(t); row=by_id.get(identity)
                base=dict(stage=stage,case_or_scene=t.get("case",t.get("scene")),
                    footprint=t.get("footprint"),connectivity=t.get("connectivity"),
                    backend=t["backend"],repetition=t["repetition"],seconds=t["seconds"],run_id=identity)
                if row is None:
                    base.update(status="incomplete_or_invalid" if identity in errors else "missing",
                                error=errors.get(identity,"not run"))
                else:
                    r,record=row["result"],row["record"]
                    base.update(status="completed",backend=r.get("backend",t["backend"]),
                                process_wall_s=record["process_wall_s"],peak_rss_bytes=record["peak_rss_bytes"],
                                raw_result=f"runs/{identity}/result.json")
                    for key in ("J","pd_final","initial_J","best_found_elapsed_s","algorithm_wall_s",
                                "algorithm_cpu_s","budget_overshoot_s","stop_reason"):
                        base[key]=r.get(key)
                    for key in ("physical_duration_s","distance_m","diagonal_distance_fraction"):
                        base[key]=r.get("physical_replay",{}).get(key)
                writer.writerow(base)
    lines=["# 八邻接后续实验：加速与同 forcing 预留实例","","这是当前输出目录的记录汇总；新实例共享历史forcing，不能解释成独立天气泛化。","",
           "| 阶段 | 有效/计划 | 状态 |","|---|---:|---|"]
    for stage,status in statuses.items():
        lines.append(f"| {stage} | {status['completed']}/{status['planned']} | {status['status']} |")
    lines+=["",f"严格等价性审计：{p0_ok}",f"D5：{dev['status']}",f"H30：{holdout['status']}","",
            "## 逐组指标","","J/Pd中位数可能来自不同重复；缺失与失败不会计为零收益。","",
            "| 阶段 | 场景/实例 | 覆盖 | 邻接 | 后端 | n | J 中位数 [范围] | Pd 中位数 |",
            "|---|---|---|---:|---|---:|---:|---:|"]
    for a in aggregates:
        lines.append(f"| {a['stage']} | {a['case_or_scene']} | {a['footprint']} | {a['connectivity']} | "
            f"{a['backend']} | {a['n']}/{a['planned']} | {a['J_median']:.9f} "
            f"[{a['J_min']:.9f}, {a['J_max']:.9f}] | {a['Pd_median']:.9f} |")
    lines+=["","D5目标命中次数、删失与目标时间见summary.json；未达到不填成5秒后计算加速比。",
            "共同初始化成本单列于S30；H30计时包括其路线复制与重新评分。",
            "原始history、缓存计数、逐次观测及路线见各result.json。H2和300秒扩展未启用。",""]
    (out/"REPORT.md").write_text("\n".join(lines),encoding="utf-8")
    print(f"Summary written to {out}",flush=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=("plan","preflight","validate","freeze-dev","audit","run",
        "select-backend","prepare-inputs","freeze-holdout","summarize","_worker"))
    parser.add_argument("--config",type=Path,default=DEFAULT_CONFIG)
    parser.add_argument("--out",type=Path)
    parser.add_argument("--stage",choices=("D5","S30","H30"))
    parser.add_argument("--task",type=Path)
    parser.add_argument("--result",type=Path)
    args=parser.parse_args(argv)
    config_path=args.config.resolve();config=read(config_path);common.set_threads(config)
    if args.command=="plan":
        print(json.dumps(plan(config),ensure_ascii=False,indent=2));return
    check_config(config)
    if args.out is None:
        parser.error("--out is required")
    out=args.out.resolve()
    if out==OUTPUT_ROOT.resolve() or not out.is_relative_to(OUTPUT_ROOT.resolve()):
        raise ValueError("Use a new child directory under the registered output root")
    if args.command=="preflight":preflight(config,config_path,out)
    elif args.command=="validate":validate(config,config_path,out)
    elif args.command=="freeze-dev":freeze_dev(config,config_path,out)
    elif args.command=="audit":run_stage(config,config_path,out,"P0")
    elif args.command=="run":
        if args.stage is None:parser.error("--stage is required")
        run_stage(config,config_path,out,args.stage)
    elif args.command=="select-backend":select_backend(config,config_path,out)
    elif args.command=="prepare-inputs":prepare_inputs(config,config_path,out)
    elif args.command=="freeze-holdout":freeze_holdout(config,config_path,out)
    elif args.command=="summarize":summarize(config,config_path,out)
    else:
        if args.task is None or args.result is None:parser.error("_worker requires --task and --result")
        try:
            worker(config,config_path,out,args.task,args.result)
        except Exception:
            if not args.result.exists():
                save(args.result,dict(task=read(args.task),result=dict(status="failed",error=traceback.format_exc())))
            raise


if __name__=="__main__":
    main()

