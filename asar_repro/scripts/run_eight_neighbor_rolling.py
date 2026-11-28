#!/usr/bin/env python3
"""Minimal two-arm rolling-planning pilot. Nothing runs at import time.

Prepared for local execution by the user. This runner never generates drift,
downloads forcing, changes archived inputs, or silently retries failed jobs.
The four H2 inputs are already observed development/diagnostic cases.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager
import csv
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import random
from statistics import median
import subprocess
import sys
import time
import traceback
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
DEFAULT_CONFIG = ROOT / "configs/eight_neighbor_rolling.json"
DEFAULT_OUT = ROOT / "outputs/eight_neighbor_rolling_20261128/local_r1"
BASE_COMMIT = "be048ea2304a25211be546c24cca506e87734049"
REGISTERED_CONFIG_HASH = "7a455c88cffc146fde6c229a9c92f0261ccf5922bd46b31790ef72ec7400099a"
STAGE = "R30"
PRIMARY = "heading_square"
SELECTED = ("lake_h2_d1_s3101", "lake_h2_d2_s3201",
            "hudson_h2_d1_s4101", "hudson_h2_d2_s4201")
TESTS = ("tests/test_physical_model.py", "tests/test_physical_search.py",
         "tests/test_physical_accel.py", "tests/test_physical_refinement.py",
         "tests/test_physical_rolling.py", "tests/test_eight_neighbor_rolling_runner.py")
PROTECTED_MODULES = ("physical_model", "physical_search", "physical_accel",
                     "physical_refinement", "physical_followup_data", "h2_inputs",
                     "h2_forcing", "historical_drift", "motion")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, value, *, replace=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    with path.open("w" if replace else "x", encoding="utf-8", newline="\n") as handle:
        handle.write(content)


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def object_digest(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def rooted(relative):
    """Configuration paths cannot escape this checkout."""
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Expected a path relative to asar_repro")
    result = (ROOT / relative).resolve()
    if not result.is_relative_to(ROOT.resolve()):
        raise ValueError("Path escapes asar_repro")
    return result


def output_path(path):
    resolved = Path(path).resolve()
    if not resolved.is_relative_to((ROOT / "outputs/eight_neighbor_rolling_20261128").resolve()):
        raise ValueError("Use a fresh directory under outputs/eight_neighbor_rolling_20261128")
    return resolved


def check_config(config):
    if object_digest(config) != REGISTERED_CONFIG_HASH:
        raise ValueError("Unregistered pilot configuration; changes require a new protocol")
    if (config["base_commit"] != BASE_COMMIT or tuple(config["instances"]) != SELECTED
            or config["methods"] != ["C0", "C1"]
            or config["objective"]["connectivity"] != 8
            or config["objective"]["footprint"] != PRIMARY
            or config["search"]["seconds"] != 30.0
            or config["search"]["repetitions"] != 3):
        raise ValueError("Pilot identity differs from the registered two-arm design")
    return config


def plan(config):
    check_config(config)
    return dict(status="prepared_not_run", stage=STAGE, instances=list(SELECTED),
                methods=config["methods"], formal_tasks=24, total_algorithm_budget_s=720.0,
                C0_slots_s=[30.0], C1_slots_s=[6.0] * 5,
                triggers=config["search"]["triggers"], data_role=config["data_role"],
                budget_scope="all method computation; loading and independent result audit recorded separately",
                inference_scope="four seen date/seed instances, three timing repeats each; no independent holdout")


def child_environment():
    env = os.environ.copy()
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        env[key] = "1"
    env["PYTHONHASHSEED"] = "0"
    env["PYTHONPATH"] = str(ROOT / "src") + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env


def environment():
    packages = {}
    for name in ("numpy", "scipy", "pytest", "psutil", "pyproj", "opendrift",
                 "xarray", "PyYAML", "netCDF4", "shapely"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = "not_installed"
    return dict(python=sys.version, executable=sys.executable, platform=platform.platform(),
                machine=platform.machine(), processor=platform.processor(), logical_cpus=os.cpu_count(),
                packages=packages, effective_child_threads={key: "1" for key in
                ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS")},
                effective_child_pythonhashseed="0")


def assert_local_project_modules():
    expected = (ROOT / "src").resolve()
    for name, module in tuple(sys.modules.items()):
        if name == "asar_repro" or name.startswith("asar_repro."):
            origin = getattr(module, "__file__", None)
            if origin is None or not Path(origin).resolve().is_relative_to(expected):
                raise ValueError(f"Project module loaded from another checkout: {name}: {origin}")


def source_inventory(config_path):
    paths = set()
    for folder in ("src", "scripts", "tests"):
        paths.update((ROOT / folder).rglob("*.py"))
    paths.update((ROOT / "configs").glob("*.json"))
    paths.update(ROOT.glob("requirements*.txt"))
    for name in ("pyproject.toml", "README.md"):
        if (ROOT / name).is_file():
            paths.add(ROOT / name)
    for path in (ROOT / "docs/eight_neighbor_rolling").rglob("*"):
        if path.is_file() and path.suffix in {".md", ".json", ".py"}:
            paths.add(path)
    paths.add(Path(config_path))
    return dict(sorted((path.relative_to(ROOT).as_posix(), digest(path)) for path in paths if path.is_file()))


def verify_files(files):
    for relative, expected in files.items():
        path = rooted(relative)
        if not path.is_file() or digest(path) != expected:
            raise ValueError(f"Missing or changed frozen file: {relative}. Restore its original bytes; do not regenerate the input.")


def git_blob_digest(path):
    data = Path(path).read_bytes()
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def verify_git_blobs(files):
    for relative, expected in files.items():
        path = rooted(relative)
        if not path.is_file() or git_blob_digest(path) != expected:
            raise ValueError(f"Inherited source differs from base commit: {relative}. Restore the tracked original bytes.")


def reference_evidence(config, *, load_archives=False):
    """Verify only selected inherited archives; original H2 code lock is historical."""
    manifest_path = rooted(config["reference_manifest"])
    manifest = read(manifest_path)
    if manifest.get("schema_version") != 1 or manifest.get("base_commit") != BASE_COMMIT:
        raise ValueError("Reference manifest has the wrong source commit")
    pinned = manifest["files"]
    source_root = config["source_root"]
    required = {f"src/asar_repro/{name}.py" for name in PROTECTED_MODULES}
    required.update(f"{source_root}/{name}" for name in ("protocol.json", "s30_lock.json"))
    required.update(f"{source_root}/inputs/{identity}/manifest.json" for identity in SELECTED)
    if not required.issubset(pinned):
        raise ValueError("Reference manifest omits a protected source or selected input lock")
    verify_files(pinned)
    inherited = manifest["git_blobs"]
    if not {f"src/asar_repro/{name}.py" for name in PROTECTED_MODULES}.issubset(inherited):
        raise ValueError("Reference manifest lacks the inherited source tree inventory")
    verify_git_blobs(inherited)
    old = rooted(source_root)
    protocol, lock = read(old / "protocol.json"), read(old / "s30_lock.json")
    if lock["status"] != "shared_S30_locked" or lock["protocol_sha256"] != digest(old / "protocol.json"):
        raise ValueError("Historical S30 route lock does not bind its H2 protocol")
    files = dict(pinned)
    instances, references, input_info = {}, {}, {}
    for identity in SELECTED:
        case = protocol["instances"][identity]
        if identity != case["id"] or identity != f"{case['block_id']}_s{case['seed']}":
            raise ValueError("Selected H2 date/seed identity mismatch")
        folder = old / "inputs" / identity
        archive = read(folder / "manifest.json")
        expected = protocol["archive_hashes"][identity]
        if (digest(folder / "manifest.json") != expected["manifest_sha256"]
                or archive["case"] != case or archive["status"] != "prepared"
                or archive["files"]["particles.npz"] != expected["particle_sha256"]):
            raise ValueError("Selected H2 archive changed")
        for name, value in archive["files"].items():
            files[f"{source_root}/inputs/{identity}/{name}"] = value
        reference = lock["references"][identity][PRIMARY]
        for name in ("record.json", "result.json"):
            relative = f"runs/{reference['run_id']}/{name}"
            files[f"{source_root}/{relative}"] = lock["files"][relative]
        instances[identity], references[identity] = case, reference
        input_info[identity] = dict(expected)
    verify_files(files)
    for identity, reference in references.items():
        folder = old / "runs" / reference["run_id"]
        record, payload = read(folder / "record.json"), read(folder / "result.json")
        source_result = payload["result"]
        score = source_result["physical_replays"][PRIMARY]
        if (record["status"] != "completed" or record["returncode"] != 0 or record["watchdog"] is not None
                or record["result_sha256"] != digest(folder / "result.json")
                or payload["task"]["instance"] != identity
                or source_result["waypoints"] != reference["waypoints"]
                or score["J"] != reference["J"] or score["pd_final"] != reference["pd_final"]
                or score["observation_times_s"] != reference["observation_times_s"]):
            raise ValueError("Historical common route does not match the archived S30 result")
    if load_archives:
        from asar_repro.h2_inputs import load_h2_input
        assert_local_project_modules()
        for identity, case in instances.items():
            problem, _, _, info = load_h2_input(ROOT, case, old / "inputs" / identity, PRIMARY)
            replay = problem.replay(references[identity]["waypoints"], connectivity=8)
            validate_score(replay, config["decision"]["score_absolute"])
            if (info["manifest_sha256"] != input_info[identity]["manifest_sha256"]
                    or info["particle_sha256"] != input_info[identity]["particle_sha256"]
                    or problem.q != config["objective"]["q"]
                    or problem.speed_m_s != config["objective"]["speed_m_s"]
                    or abs(replay["J"] - references[identity]["J"]) > config["decision"]["score_absolute"]
                    or abs(replay["pd_final"] - references[identity]["pd_final"]) > config["decision"]["score_absolute"]
                    or replay["observation_times_s"] != references[identity]["observation_times_s"]):
                raise ValueError("Frozen common route does not reproduce under the unchanged physical scorer")
            input_info[identity]["physical_audit"] = dict(
                q=problem.q, horizon_s=problem.horizon_s, tick_count=problem.tick_count,
                speed_m_s=problem.speed_m_s, initial_mass=float(problem.initial_weights.sum()),
                special_mass_by_step=info["special_mass_by_step"], opendrift_runs_in_search=0)
    return dict(base_commit=BASE_COMMIT, manifest_sha256=digest(manifest_path), files=dict(sorted(files.items())),
                git_blobs=inherited,
                instances=instances, references=references, archive_hashes=input_info,
                data_role=config["data_role"], new_drift_runs=0,
                seed_generation_cost="historical S30 cost external and equal; route copy/replay charged per method")


def preflight(config_path, out):
    config = check_config(read(config_path))
    evidence = reference_evidence(config, load_archives=True)
    sources, env = source_inventory(config_path), environment()
    if any(env["packages"][key] == "not_installed" for key in ("numpy", "scipy", "pytest", "psutil", "pyproj")):
        raise ValueError("Required original runtime dependencies are missing; use the existing experiment environment")
    payload = dict(status="ready_for_local_validation", config_sha256=digest(config_path),
                   source_sha256=sources, environment=env, references=evidence, design=plan(config))
    path = out / "preflight.json"
    if path.exists():
        if read(path) != payload:
            raise ValueError("Preflight changed; retain this directory and use a new output directory")
    else:
        save(path, payload)
    print("Preflight verified four inherited inputs and their common routes. No new experiment was run.")


def verify_preflight(config_path, out):
    payload = read(out / "preflight.json")
    config = check_config(read(config_path))
    if (payload["config_sha256"] != digest(config_path)
            or payload["source_sha256"] != source_inventory(config_path)
            or payload["environment"] != environment()):
        raise ValueError("Code, configuration or environment changed after preflight")
    verify_files(payload["references"]["files"])
    verify_git_blobs(payload["references"]["git_blobs"])
    if reference_evidence(config)["references"] != payload["references"]["references"]:
        raise ValueError("Frozen common routes changed")
    return payload


def validate(config_path, out):
    if (out / "protocol.json").exists() or (out / "runs").exists():
        raise ValueError("Validation must precede freezing and formal runs")
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
        raise ValueError("Local validation failed; all test evidence was retained")
    print(f"Local validation passed: {len(cases)} tests. No formal R30 task has run.")


def check_validation(out, ref, sources, env):
    path = out / ref["path"]
    result = read(path)
    if (digest(path) != ref["sha256"] or result["status"] != "passed"
            or result["returncode"] != 0 or result["testcase_count"] <= 0
            or result["bad_or_skipped_count"] != 0 or not result["unchanged"]
            or result["paths"] != list(TESTS) or result["source_sha256"] != sources
            or result["environment"] != env or digest(path.with_name("pytest.xml")) != result["xml_sha256"]):
        raise ValueError("Local passing-test evidence does not bind current code and runtime")


def task_id(task):
    return STAGE + "_" + object_digest(task)[:20]


def make_tasks(config, evidence):
    tasks = []
    for identity in SELECTED:
        case = evidence["instances"][identity]
        for method in config["methods"]:
            for repetition in range(config["search"]["repetitions"]):
                tasks.append(dict(stage=STAGE, instance=identity, base_scene=case["base_scene"],
                    block_id=case["block_id"], seed=case["seed"], method=method, repetition=repetition,
                    seconds=config["search"]["seconds"], connectivity=8, footprint=PRIMARY,
                    manifest_sha256=evidence["archive_hashes"][identity]["manifest_sha256"],
                    reference_sha256=object_digest(evidence["references"][identity])))
    random.Random(config["task_order_seed"]).shuffle(tasks)
    return tasks


def freeze(config_path, out):
    if (out / "protocol.json").exists():
        verify_protocol(config_path, out)
        print("Existing frozen protocol verified")
        return
    if (out / "runs").exists():
        raise ValueError("Cannot freeze after a formal run has started")
    pre = verify_preflight(config_path, out)
    config = check_config(read(config_path))
    validation = read(out / "validation/latest.json")
    check_validation(out, validation, pre["source_sha256"], pre["environment"])
    tasks = make_tasks(config, pre["references"])
    save(out / "tasks/R30.json", tasks)
    save(out / "protocol.json", dict(status="frozen_before_R30", created_utc=datetime.now(timezone.utc).isoformat(),
         config=config, config_sha256=digest(config_path), source_sha256=pre["source_sha256"],
         environment=pre["environment"], references=pre["references"], validation=validation,
         preflight_sha256=digest(out / "preflight.json"), tasks_sha256=object_digest(tasks), design=plan(config)))
    print("Frozen 24 R30 tasks, 720 seconds total algorithm allocation. Ready for local execution.")


def verify_protocol(config_path, out):
    protocol = read(out / "protocol.json")
    config = check_config(read(config_path))
    if (protocol["status"] != "frozen_before_R30" or protocol["config"] != config
            or protocol["config_sha256"] != digest(config_path)
            or protocol["source_sha256"] != source_inventory(config_path)
            or protocol["environment"] != environment()
            or protocol["preflight_sha256"] != digest(out / "preflight.json")):
        raise ValueError("Frozen code, configuration, preflight or runtime changed")
    verify_files(protocol["references"]["files"])
    verify_git_blobs(protocol["references"]["git_blobs"])
    check_validation(out, protocol["validation"], protocol["source_sha256"], protocol["environment"])
    tasks = read(out / "tasks/R30.json")
    if (object_digest(tasks) != protocol["tasks_sha256"]
            or tasks != make_tasks(config, protocol["references"])):
        raise ValueError("Frozen task identities or execution order changed")
    return protocol, tasks


def finite_number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def validate_score(score, tolerance):
    survival = score["survival"]
    times = score["observation_times_s"]
    if (not survival or len(survival) != len(times) + 1
            or not all(finite_number(value) for value in survival + times + [score["J"], score["pd_final"]])
            or abs(survival[0] - 1.0) > tolerance
            or any(value < -tolerance or value > 1 + tolerance for value in survival)
            or any(b > a + tolerance for a, b in zip(survival, survival[1:]))
            or any(b <= a for a, b in zip([0.0] + times, times))
            or abs(sum(survival[1:]) - score["J"]) > tolerance
            or abs(1.0 - survival[-1] - score["pd_final"]) > tolerance):
        raise ValueError("Physical score, global survival mass or observation clock is inconsistent")


def validate_phase_ledger(raw, seconds, tolerance=1e-8):
    phases = raw["phases"]
    count = 1 if raw["method"] == "C0" else 5
    nominal = seconds / count
    if [phase["stage_index"] for phase in phases] != list(range(count)):
        raise ValueError("Missing, duplicate, reordered or unregistered planning phase")
    previous = 0.0
    for phase in phases:
        index = phase["stage_index"]
        cost, cumulative = phase["actual_compute_s"], phase["cumulative_compute_s"]
        allocation = phase["allocated_seconds"]
        if (not all(finite_number(x) and x >= 0 for x in (cost, cumulative, allocation))
                or abs(cumulative - previous - cost) > tolerance
                or abs(phase["stage_start_compute_s"] - previous) > tolerance
                or allocation > min(nominal,max(0.0,seconds-previous)) + tolerance
                or abs(phase["stage_deadline_compute_s"] - previous - allocation) > tolerance):
            raise ValueError("Planning-phase budget ledger is inconsistent")
        if phase["accepted"]:
            at = phase["acceptance_compute_s"]
            total_at = phase["cumulative_acceptance_compute_s"]
            if (not finite_number(at) or not finite_number(total_at) or at < 0 or total_at < 0
                    or at > allocation + tolerance or total_at > seconds + tolerance
                    or abs(total_at - previous - at) > tolerance or at > cost + tolerance):
                raise ValueError("A late candidate was accepted")
            if index > 0:
                if (not all(finite_number(phase[key]) for key in ("ready_time_s","request_time_s","anchor_time_s"))
                        or abs(phase["ready_time_s"] - phase["request_time_s"] - at) > tolerance
                        or phase["ready_time_s"] > phase["anchor_time_s"] + tolerance):
                    raise ValueError("An online route replacement missed its committed anchor")
        previous = cumulative
    finalization = raw["finalization_compute_s"]
    if (not finite_number(raw["active_compute_s"]) or not finite_number(finalization) or finalization < 0
            or abs(raw["phase_compute_sum_s"] - previous) > tolerance
            or abs(raw["active_compute_s"] - previous - finalization) > tolerance):
        raise ValueError("Method total omitted charged computation")


def audit_execution(problem, raw, reference, tolerance):
    """Independent audit of recorded decisions; never returns a new candidate."""
    active = problem.replay(reference["waypoints"],connectivity=8)
    protected, execution = (problem.start,), 0.0
    selected_history = [list(active["waypoints"])]
    root_audits = 0
    for phase in raw["phases"]:
        index = phase["stage_index"]
        route = tuple(active["waypoints"])
        if route[:len(protected)] != protected:
            raise ValueError("Audit found an altered executed prefix")
        expected_prefix = protected
        if index == 0:
            if phase["request_time_s"] != 0.0 or phase["anchor_time_s"] != 0.0:
                raise ValueError("Initial planning is not pre-CST")
            expected_prefix = (problem.start,)
        else:
            threshold = max(raw["triggers"][index-1]*problem.horizon_s,execution)
            # Reconstruct legal completed waypoint events from original full-route replay.
            milestones = [(j,at) for j,at in enumerate(active["planned_arrival_times_s"])
                          if at < problem.horizon_s-problem.time_tolerance_s]
            requests = [(j,at) for j,at in milestones if j >= len(protected)-1
                        and at + problem.time_tolerance_s >= threshold]
            if phase["request_time_s"] is None:
                if phase["reason"] == "shared_budget_exhausted":
                    if phase["allocated_seconds"] > tolerance and phase["actual_compute_s"] < phase["allocated_seconds"]-tolerance:
                        raise ValueError("Skipped an available planning slot without exhausting its budget")
                elif phase["reason"] != "no_remaining_request_waypoint" or requests:
                    raise ValueError("Skipped an eligible request without a registered reason")
            elif not requests:
                raise ValueError("Recorded request has no causal waypoint")
            else:
                request_index, request_time = requests[0]
                if (phase["request_waypoint_index"] != request_index
                        or abs(phase["request_time_s"]-request_time) > tolerance):
                    raise ValueError("Request is not the first eligible completed waypoint")
                anchors = [(j,at) for j,at in milestones if j > request_index
                           and at + problem.time_tolerance_s >= request_time+phase["allocated_seconds"]+raw["anchor_guard_s"]]
                if anchors:
                    anchor_index, anchor_time = anchors[0]
                    if (phase["anchor_waypoint_index"] != anchor_index or phase["anchor_time_s"] is None
                            or abs(phase["anchor_time_s"]-anchor_time) > tolerance):
                        raise ValueError("Commit anchor does not allow the registered latency buffer")
                    expected_prefix = route[:anchor_index+1]
                elif phase["anchor_time_s"] is not None:
                    raise ValueError("Nonexistent commit anchor")
        if tuple(phase["committed_prefix_waypoints"]) != expected_prefix:
            raise ValueError("Recorded committed prefix differs from the executable active route")
        inner = phase.get("inner")
        candidate = None
        if inner is not None:
            initial = inner.get("initial_score")
            if initial is not None and initial["waypoints"] != list(route):
                raise ValueError("Inner solver was not seeded from the current active full route")
            if raw["method"] == "C1":
                has_evidence = inner.get("waypoints") is not None or inner.get("root_state") is not None or phase["accepted"]
                if has_evidence and inner.get("root_prefix") != list(expected_prefix):
                    raise ValueError("Inner solver used a different root prefix")
                if not has_evidence and (inner.get("error") is not None or inner.get("status") != "budget_exceeded"):
                    raise ValueError("Missing root evidence is allowed only for an unaccepted budget stop")
                data = inner.get("root_state")
                if data is not None:
                    root = problem.initial_state()
                    for target in expected_prefix[1:]:
                        root = problem.advance(root,target,connectivity=8)
                    if (data["vertex"] != root.vertex or data["tick"] != root.tick
                            or data["terminal"] != root.terminal
                            or abs(data["time_s"]-root.time_s) > tolerance
                            or abs(data["J"]-root.J) > tolerance
                            or abs(data["remaining_mass"]-float(root.weights.sum())) > tolerance
                            or abs(data["distance_m"]-root.distance_m) > tolerance
                            or data["weights_sha256"] != hashlib.sha256(root.weights.tobytes()).hexdigest()
                            or len(data["survival"]) != len(root.survival)
                            or any(abs(a-b)>tolerance for a,b in zip(data["survival"],root.survival))):
                        raise ValueError("Re-rooted state lost absolute time, mass, history or physical position")
                    root_audits += 1
                elif phase["accepted"]:
                    raise ValueError("Accepted suffix lacks its re-rooted state evidence")
            if inner.get("waypoints") is not None:
                if tuple(inner["waypoints"][:len(expected_prefix)]) != expected_prefix:
                    raise ValueError("Inner candidate changed a committed prefix")
                candidate = problem.replay(inner["waypoints"],connectivity=8)
                validate_score(candidate,tolerance)
                if (abs(candidate["J"]-inner["J"]) > tolerance
                        or abs(candidate["pd_final"]-inner["pd_final"]) > tolerance):
                    raise ValueError("Inner candidate failed original physical replay")
        if phase["accepted"]:
            if candidate is None or candidate["J"] >= active["J"]-1e-10:
                raise ValueError("Accepted replacement did not strictly improve the full original objective")
            active = candidate
            selected_history.append(list(active["waypoints"]))
        if (abs(phase["active_J_after"]-active["J"]) > tolerance
                or abs(phase["active_pd_final_after"]-active["pd_final"]) > tolerance):
            raise ValueError("Phase active score differs from the causal selected route")
        if index and phase["request_time_s"] is not None:
            request_time = phase["request_time_s"]
            ready = request_time+phase["actual_compute_s"]
            expected_execution = min(problem.horizon_s,max(execution,ready,phase["anchor_time_s"] or 0.0))
            actual = phase["virtual_execution_time_after_s"]
            if (abs(phase["execution_ready_compute_s"]-phase["actual_compute_s"]) > tolerance
                    or abs(phase["execution_ready_time_s"]-ready) > tolerance
                    or abs(actual-expected_execution) > tolerance):
                raise ValueError("Virtual execution paused or moved ahead of its paid computation")
            execution = actual
            if phase["anchor_time_s"] is not None:
                protected = expected_prefix
    if (active["waypoints"] != raw["waypoints"]
            or [entry["waypoints"] for entry in raw["history"]] != selected_history
            or tuple(raw["protected_prefix_waypoints"]) != protected):
        raise ValueError("Final route is not the route produced by the recorded causal replacements")
    return dict(status="passed",root_state_audits=root_audits,
                selected_routes=len(selected_history),independent_original_model=True,
                candidate_selection_performed=False,q=problem.q,horizon_s=problem.horizon_s)


def verify_result(task, result, protocol):
    config = protocol["config"]
    tol = config["decision"]["score_absolute"]
    reference = protocol["references"]["references"][task["instance"]]
    score, raw = result["physical_replay"], result["raw"]
    validate_score(score, tol)
    validate_phase_ledger(raw, task["seconds"], tol)
    if (result["status"] != "valid" or result["environment"] != protocol["environment"]
            or result["method"] != task["method"] or raw["method"] != task["method"]
            or raw.get("error") is not None or raw["status"] != "completed"
            or raw["total_seconds"] != task["seconds"] or raw["solver_options"] != config["solver"]
            or raw["triggers"] != config["search"]["triggers"]
            or raw["anchor_guard_s"] != config["search"]["anchor_guard_s"]
            or raw["solver_reserve_s"] != config["search"]["solver_reserve_s"]
            or raw["slot_count"] != (1 if task["method"] == "C0" else 5)
            or raw["nominal_slot_seconds"] != (30.0 if task["method"] == "C0" else 6.0)
            or raw["source_base"] != BASE_COMMIT or raw["connectivity"] != 8 or raw["footprint"] != PRIMARY
            or raw["global_optimality_certified"] is not False or raw["epsilon_certificate"] is not None
            or result["execution_audit"]["status"] != "passed"
            or result["execution_audit"]["candidate_selection_performed"] is not False
            or result["execution_audit"]["q"] != config["objective"]["q"]
            or result["formal_optimality_certificate"] is not False
            or result["reference_sha256"] != object_digest(reference)
            or result["inputs"]["manifest_sha256"] != task["manifest_sha256"]
            or result["inputs"]["particle_sha256"] != protocol["references"]["archive_hashes"][task["instance"]]["particle_sha256"]
            or result["inputs"]["case"] != protocol["references"]["instances"][task["instance"]]
            or result["inputs"]["footprint"] != PRIMARY or result["inputs"]["opendrift_runs_in_search"] != 0
            or score["connectivity"] != 8 or score["footprint"] != PRIMARY
            or score["waypoints"] != raw["waypoints"]
            or score["observation_times_s"] != reference["observation_times_s"]
            or abs(score["J"] - raw["J"]) > tol or abs(score["pd_final"] - raw["pd_final"]) > tol
            or len(score["survival"]) != len(raw["survival"])
            or any(abs(a-b) > tol for a, b in zip(score["survival"], raw["survival"]))
            or result["J"] != score["J"] or result["pd_final"] != score["pd_final"]
            or raw["initial_score"]["waypoints"] != reference["waypoints"]
            or raw["planned_observation_times_s"] != reference["observation_times_s"]
            or score["horizon_s"] != protocol["references"]["archive_hashes"][task["instance"]]["physical_audit"]["horizon_s"]
            or score["speed_m_s"] != config["objective"]["speed_m_s"]
            or not raw["history"] or raw["history"][0]["source"] != "common_seed"
            or any(not finite_number(item["elapsed_s"]) or not 0 <= item["elapsed_s"] <= task["seconds"] for item in raw["history"])
            or not finite_number(result["algorithm_wall_s"]) or result["algorithm_wall_s"] < raw["active_compute_s"]):
        raise ValueError("Run identity, dynamic physical replay or computation evidence failed")


def failure_safe(value):
    if value is None or isinstance(value,(str,bool,int)):
        return value
    if isinstance(value,float):
        return value if math.isfinite(value) else repr(value)
    if isinstance(value,dict):
        return {str(key):failure_safe(item) for key,item in value.items()}
    if isinstance(value,(tuple,list)):
        return [failure_safe(item) for item in value]
    return repr(value)


def worker(config_path, out, task_path, result_path):
    protocol, tasks = verify_protocol(config_path, out)
    task = read(task_path)
    folder = out / "runs" / task_id(task)
    if task not in tasks or task_path != folder / "task.json" or result_path != folder / "result.json":
        raise ValueError("Worker request is not a registered R30 task")
    config = protocol["config"]
    if (any(os.environ.get(key) != value for key,value in config["thread_environment"].items())
            or os.environ.get("PYTHONHASHSEED") != "0"):
        raise ValueError("Formal worker must be launched through the one-thread registered runner")
    from asar_repro.h2_inputs import load_h2_input
    from asar_repro.physical_rolling import run_physical_rolling
    assert_local_project_modules()
    reference = protocol["references"]["references"][task["instance"]]
    case = protocol["references"]["instances"][task["instance"]]
    load_started = time.perf_counter()
    problem, _, _, info = load_h2_input(ROOT, case, rooted(config["source_root"]) / "inputs" / case["id"], PRIMARY)
    load_s = time.perf_counter() - load_started
    if (info["manifest_sha256"] != task["manifest_sha256"]
            or problem.q != config["objective"]["q"]
            or problem.speed_m_s != config["objective"]["speed_m_s"]):
        raise ValueError("Loaded archive differs from the frozen task")
    started, cpu, raw = time.perf_counter(), time.process_time(), None
    try:
        raw = run_physical_rolling(problem, method=task["method"], initial_waypoints=reference["waypoints"],
            total_seconds=task["seconds"], triggers=config["search"]["triggers"],
            anchor_guard_s=config["search"]["anchor_guard_s"], solver_reserve_s=config["search"]["solver_reserve_s"],
            solver_options=config["solver"])
        wall, cpu_s = time.perf_counter()-started, time.process_time()-cpu
        audit_started = time.perf_counter()
        if raw.get("error") is not None or raw.get("status") != "completed":
            raise ValueError(f"Method failed: {raw.get('error')}")
        # These audits cannot select, complete, or replace any candidate route.
        replay = problem.replay(raw["waypoints"], connectivity=8)
        execution_audit = audit_execution(problem,raw,reference,config["decision"]["score_absolute"])
        audit_s = time.perf_counter() - audit_started
        result = dict(status="valid", method=task["method"], J=replay["J"], pd_final=replay["pd_final"],
            physical_replay=replay, raw=raw, inputs=info, environment=environment(), execution_audit=execution_audit,
            reference_sha256=object_digest(reference), formal_optimality_certificate=False,
            algorithm_wall_s=wall, algorithm_cpu_s=cpu_s, input_load_s=load_s,
            independent_audit_s=audit_s, audit_scope="validation only; never supplies an accepted candidate")
        verify_result(task, result, protocol)
        assert_local_project_modules()
        # Inputs and frozen code are checked again after the timed operation.
        verify_protocol(config_path, out)
        save(result_path, dict(task=task, result=result))
    except BaseException as error:
        save(folder/"failure_result.json",failure_safe(dict(status="failed",task=task,raw=raw,
             error=str(error),traceback=traceback.format_exc(),elapsed_s=time.perf_counter()-started)))
        raise


def frozen_evidence(out):
    return dict(protocol_sha256=digest(out / "protocol.json"))


def load_record(out, task, protocol):
    folder = out / "runs" / task_id(task)
    if not folder.exists():
        return None
    if not (folder / "record.json").is_file() or not (folder / "result.json").is_file():
        raise ValueError(f"Incomplete run retained: {folder.name}; no automatic retry")
    record, payload = read(folder / "record.json"), read(folder / "result.json")
    if (record["status"] != "completed" or record["returncode"] != 0 or record["watchdog"] is not None
            or record["task"] != task or payload["task"] != task or read(folder / "task.json") != task
            or record["frozen_evidence"] != frozen_evidence(out)
            or record["result_sha256"] != digest(folder / "result.json")):
        raise ValueError(f"Failed or altered run retained: {folder.name}")
    verify_result(task, payload["result"], protocol)
    return dict(task=task, result=payload["result"], record=record, run_id=task_id(task))


def collect(out, tasks, protocol):
    rows, missing, errors = [], [], []
    registered = {task_id(task) for task in tasks}
    if (out / "runs").exists():
        extra = sorted(path.name for path in (out / "runs").iterdir() if path.is_dir() and path.name not in registered)
        errors.extend(dict(run_id=name, error="unregistered_run_directory") for name in extra)
    for task in tasks:
        try:
            row = load_record(out, task, protocol)
            if row is None:
                missing.append(task_id(task))
            else:
                rows.append(row)
        except (OSError, KeyError, ValueError, TypeError) as error:
            errors.append(dict(run_id=task_id(task), error=str(error)))
    return dict(status="complete" if not missing and not errors else "incomplete_or_invalid",
                planned=len(tasks), valid=len(rows), missing=missing, errors=errors), rows


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
                if time.perf_counter()-started > task["seconds"] + policy["grace_seconds"]:
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
        process_wall_s=time.perf_counter()-started, peak_rss_bytes=peak,
        result_sha256=result_sha, frozen_evidence=frozen_evidence(out)))
    if not valid:
        raise RuntimeError(f"Failed task retained at {folder}; execution stopped, no retry")
    print(f"Completed {task_id(task)}", flush=True)


@contextmanager
def exclusive_run(out):
    path = out / "RUNNING.lock"
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(pid=os.getpid(), created_utc=datetime.now(timezone.utc).isoformat())))
    try:
        yield
    finally:
        path.unlink()


def run(config_path, out):
    protocol, tasks = verify_protocol(config_path, out)
    with exclusive_run(out):
        for task in tasks:
            launch_task(config_path, out, task, protocol)
    analyze(config_path, out)


def representative(rows):
    # Three repeats: take the actual median-J run, including its own Pd.
    return sorted(rows, key=lambda row: (row["result"]["J"], row["task"]["repetition"]))[len(rows)//2]


def decision(config, rows, *, complete):
    expected = {(identity, method, repetition) for identity in SELECTED for method in ("C0", "C1") for repetition in range(3)}
    seen, groups = [], defaultdict(list)
    try:
        for row in rows:
            task, result = row["task"], row["result"]
            key = (task["instance"], task["method"], task["repetition"])
            seen.append(key)
            if (task["seconds"] != 30 or task["connectivity"] != 8 or task["footprint"] != PRIMARY
                    or task["base_scene"] != ("lake_ontario" if task["instance"].startswith("lake_") else "arctic_ocean")
                    or not all(finite_number(result[name]) for name in ("J", "pd_final"))
                    or result["J"] <= 0 or not 0 <= result["pd_final"] <= 1):
                raise ValueError("invalid decision row")
            groups[key[:2]].append(row)
        if not complete or len(seen) != len(expected) or set(seen) != expected:
            raise ValueError("incomplete or duplicate matrix")
    except (KeyError, TypeError, ValueError):
        return dict(status="incomplete_or_invalid", screen_passed=False, comparisons=[])
    rules = config["decision"]
    comparisons, region_winners = [], Counter()
    for identity in SELECTED:
        a, b = (representative(groups[identity, method]) for method in ("C0", "C1"))
        J0, J1 = a["result"]["J"], b["result"]["J"]
        gain = (J0-J1)/J0
        delta_pd = b["result"]["pd_final"] - a["result"]["pd_final"]
        region = a["task"]["base_scene"]
        winner = gain >= rules["instance_winner_min"]
        if winner:
            region_winners[region] += 1
        comparisons.append(dict(instance=identity, base_scene=region, J_C0=J0, J_C1=J1,
            relative_J_gain=gain, pd_C0=a["result"]["pd_final"], pd_C1=b["result"]["pd_final"],
            delta_pd=delta_pd, delta_pd_percentage_points=100*delta_pd,
            winner=winner, J_regression=gain < -rules["relative_tolerance"],
            pd_drop_flag=delta_pd < -rules["max_pd_drop"],
            C0_run_id=a["run_id"], C1_run_id=b["run_id"],
            C0_J_range=[min(x["result"]["J"] for x in groups[identity,"C0"]), max(x["result"]["J"] for x in groups[identity,"C0"])],
            C1_J_range=[min(x["result"]["J"] for x in groups[identity,"C1"]), max(x["result"]["J"] for x in groups[identity,"C1"])]))
    quality_protected = not any(item["J_regression"] for item in comparisons)
    pd_protected = not any(item["pd_drop_flag"] for item in comparisons)
    enough = sum(item["winner"] for item in comparisons) >= rules["min_instance_winners"]
    regions = all(region_winners[region] >= rules["min_winners_per_scene"] for region in ("lake_ontario", "arctic_ocean"))
    passed = enough and regions and quality_protected and pd_protected
    return dict(status="rolling_development_screen_passed" if passed else "rolling_development_screen_not_passed",
        screen_passed=passed, comparisons=comparisons, quality_protected=quality_protected,
        pd_protected=pd_protected, instance_winners=sum(x["winner"] for x in comparisons),
        winners_by_scene=dict(region_winners), median_relative_J_gain=median(x["relative_J_gain"] for x in comparisons),
        inference_scope="development engineering screen only; no significance, generalization or optimality proof")


def csv_output(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict,list)) else value
                             for key,value in row.items() if key in fields})


def analyze(config_path, out):
    protocol, tasks = verify_protocol(config_path, out)
    status, rows = collect(out, tasks, protocol)
    conclusion = decision(protocol["config"], rows, complete=status["status"] == "complete")
    comparisons, survival, phases = [], [], []
    for row in rows:
        task, result = row["task"], row["result"]
        base = dict(run_id=row["run_id"], **{key:task[key] for key in
                     ("instance", "base_scene", "method", "repetition")})
        comparisons.append(dict(base, J=result["J"], pd_final=result["pd_final"],
            algorithm_wall_s=result["algorithm_wall_s"], algorithm_cpu_s=result["algorithm_cpu_s"],
            active_compute_s=result["raw"]["active_compute_s"], process_wall_s=row["record"]["process_wall_s"],
            peak_rss_bytes=row["record"]["peak_rss_bytes"], input_load_s=result["input_load_s"],
            independent_audit_s=result["independent_audit_s"],
            deadline_overshoot_s=result["raw"].get("deadline_overshoot_s",0.0)))
        score = result["physical_replay"]
        for tick, (at, mass) in enumerate(zip([0.0]+score["observation_times_s"],score["survival"])):
            survival.append(dict(base,tick=tick,time_s=at,remaining_mass=mass,pd_by_time=1-mass))
        for phase in result["raw"]["phases"]:
            phases.append(dict(base,**{key:value for key,value in phase.items() if key not in {"raw","inner","inner_raw"}}))
    common_fields = ["run_id","instance","base_scene","method","repetition"]
    csv_output(out/"comparison.csv",comparisons,common_fields+["J","pd_final","algorithm_wall_s","algorithm_cpu_s",
        "active_compute_s","process_wall_s","peak_rss_bytes","input_load_s","independent_audit_s","deadline_overshoot_s"])
    csv_output(out/"survival.csv",survival,common_fields+["tick","time_s","remaining_mass","pd_by_time"])
    phase_fields = sorted(set().union(*(row.keys() for row in phases))-set(common_fields)) if phases else []
    csv_output(out/"phases.csv",phases,common_fields+phase_fields)
    pair_fields = ["instance","base_scene","J_C0","J_C1","relative_J_gain","pd_C0","pd_C1","delta_pd_percentage_points",
                   "winner","J_regression","pd_drop_flag","C0_run_id","C1_run_id","C0_J_range","C1_J_range"]
    csv_output(out/"instance_comparison.csv",conclusion["comparisons"],pair_fields)
    summary = dict(status=status, decision=conclusion, protocol_sha256=digest(out/"protocol.json"),
                   data_role=protocol["config"]["data_role"], formal_optimality_certificate=False,
                   total_algorithm_wall_s=sum(row["result"]["algorithm_wall_s"] for row in rows),
                   raw_evidence={row["run_id"]:row["record"]["result_sha256"] for row in rows},
                   derived_file_sha256={name:digest(out/name) for name in
                       ("comparison.csv","survival.csv","phases.csv","instance_comparison.csv")})
    save(out/"summary.json",summary,replace=True)
    lines = ["# 八邻域滚动规划：本地结果汇总","",f"运行状态：`{status['status']}`。判定：`{conclusion['status']}`。","",
        "四个实例来自已见 H2 档案。每组的三次运行是计时重复，不能替代独立日期或新粒子验证。","",
        "| 实例 | C0 J | C1 J | J 改善 | ΔPd 百分点 |", "|---|---:|---:|---:|---:|"]
    for pair in conclusion["comparisons"]:
        lines.append(f"| {pair['instance']} | {pair['J_C0']:.8f} | {pair['J_C1']:.8f} | {pair['relative_J_gain']*100:+.4f}% | {pair['delta_pd_percentage_points']:+.4f} |")
    lines += ["","## 判读边界","","C0/C1 均使用同一动态预测。新增机制是计算分阶段和已执行前缀后的重规划；没有新的风流或传感器信息。",
        "J、Pd 取同一个 J 中位代表运行；所有原值、存活质量曲线与阶段计费保留在 CSV 和 runs 中。",
        "未通过门槛时结束本轮，不自动增加预算或扫描滚动间隔。通过后也只进入独立验证设计，不宣称第二创新点已成立。",
        "","用户解释请写入 ANALYSIS.md；本命令不会覆盖该文件。",""]
    (out/"REPORT.md").write_text("\n".join(lines),encoding="utf-8")
    print(json.dumps(dict(status=status["status"],decision=conclusion["status"],valid=status["valid"]),ensure_ascii=False))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("plan","preflight","validate","freeze","run","analyze","_worker"))
    parser.add_argument("--config",type=Path,default=DEFAULT_CONFIG)
    parser.add_argument("--out",type=Path,default=DEFAULT_OUT)
    parser.add_argument("--task",type=Path)
    parser.add_argument("--result",type=Path)
    args = parser.parse_args(argv)
    config_path,args.out = args.config.resolve(),output_path(args.out)
    config = check_config(read(config_path))
    if args.action == "plan":
        print(json.dumps(plan(config),ensure_ascii=False,indent=2))
        return
    args.out.mkdir(parents=True,exist_ok=True)
    if args.action == "_worker":
        if args.task is None or args.result is None:
            parser.error("worker requires --task and --result")
        worker(config_path,args.out,args.task.resolve(),args.result.resolve())
        return
    action = {"preflight":preflight,"validate":validate,"freeze":freeze,"run":run,"analyze":analyze}[args.action]
    log = args.out/"commands"/f"{stamp()}-{args.action}.json"
    started = time.perf_counter()
    record = dict(action=args.action,command=[sys.executable,str(Path(__file__).resolve()),*(argv if argv is not None else sys.argv[1:])],
                  started_utc=datetime.now(timezone.utc).isoformat(),status="running")
    try:
        action(config_path,args.out)
        record["status"] = "completed"
    except BaseException as error:
        record.update(status="failed",error=str(error),traceback=traceback.format_exc())
        raise
    finally:
        record["wall_s"] = time.perf_counter()-started
        save(log,record)


if __name__ == "__main__":
    main()
