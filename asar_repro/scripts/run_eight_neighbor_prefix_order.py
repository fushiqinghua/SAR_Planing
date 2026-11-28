#!/usr/bin/env python3
"""Run the frozen single-factor early/middle OPEN ordering screen."""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import os
from pathlib import Path
import random
import subprocess
import sys
import time
from unittest.mock import patch
import xml.etree.ElementTree as ET

import run_eight_neighbor_rolling_merge as inherited

ROOT = inherited.ROOT
BASE = "d605b97280b80dc8bed66ab1bab5c061ecbfc517"
OUT = ROOT / "outputs/eight_neighbor_prefix_order_20261128/local_r3"
CONFIG = inherited.DEFAULT_CONFIG
read, save = inherited.read, inherited.save
digest, object_digest = inherited.digest, inherited.object_digest
legacy = inherited._legacy

DESIGN = {
    "name": "eight-neighbor-prefix-order",
    "instances": list(inherited.SELECTED),
    "methods": ["C0", "C0_PREFIX"],
    "seconds": 30.0,
    "repetitions": 3,
    "task_order_seed": 2026112803,
    "pair_schedule": "shuffle instance/repetition blocks and arm order within each block",
    "objective": "original completion_J with independent original-route replay",
    "merge_mode": "off for both formal arms",
    "frontier": {
        "reserved_every": 4, "band_order": ["early", "middle"],
        "early": "4*tick < K", "middle": "K <= 4*tick < 3*K", "tail": "3*K <= 4*tick",
        "key": "original guide priority, original insertion serial",
        "empty_band": "global next", "state_drop": False,
    },
    "diagnostic": {"methods": ["off", "shadow", "exact"], "expansions": 4096, "runs": 12},
    "decision": {
        "minimum_relative_J_improvement": 0.001,
        "minimum_winning_instances": 3,
        "minimum_wins_per_region": 1,
        "relative_J_nonregression_tolerance": 1e-8,
        "max_terminal_Pd_drop": 0.005,
    },
    "historical_hudson_J": {
        "hudson_h2_d1_s4101": 28.448979882240007,
        "hudson_h2_d2_s4201": 58.677655392,
    },
}


def check_protected_checkout():
    subprocess.run(["git", "diff", "--exit-code", BASE, "--", "."], cwd=ROOT.parent, check=True)


def make_tasks(refs):
    rng = random.Random(DESIGN["task_order_seed"])
    pairs = [(name, repeat) for name in DESIGN["instances"]
             for repeat in range(DESIGN["repetitions"])]
    rng.shuffle(pairs)
    result = []
    for name, repeat in pairs:
        methods = DESIGN["methods"].copy()
        rng.shuffle(methods)
        for method in methods:
            result.append(dict(
                instance=name, method=method, repetition=repeat, seconds=DESIGN["seconds"],
                stage="P30", manifest_sha256=refs["archive_hashes"][name]["manifest_sha256"],
                reference_sha256=object_digest(refs["references"][name]),
            ))
    return result


def task_id(task):
    return "P30_" + object_digest(task)[:20]


def prepare(out):
    if (out / "protocol.json").exists():
        raise ValueError("The protocol has already been frozen")
    check_protected_checkout()
    from asar_repro.physical_prefix_order import FRONTIER_POLICY

    if FRONTIER_POLICY != DESIGN["frontier"]:
        raise ValueError("The scheduler differs from the registered design")
    config = inherited.check_config(read(CONFIG))
    refs = inherited.reference_evidence(config, load_archives=True)
    tasks = make_tasks(refs)
    out.mkdir(parents=True, exist_ok=True)
    save(out / "tasks.json", tasks)
    save(out / "protocol.json", dict(
        status="frozen_before_tests", frozen_utc=inherited.stamp(), base_commit=BASE,
        design=DESIGN, config=config, references=refs,
        environment=inherited.environment(), source_sha256=inherited.source_inventory(CONFIG),
        tasks_sha256=digest(out / "tasks.json"),
    ))
    print(f"Frozen {len(tasks)} timed tasks, {len(refs['files'])} file digests, "
          f"{len(refs['git_blobs'])} inherited blobs and four original particle archives.", flush=True)


def verify(out):
    protocol = read(out / "protocol.json")
    tasks = read(out / "tasks.json")
    if (protocol["base_commit"] != BASE or protocol["design"] != DESIGN
            or protocol["config"] != inherited.check_config(read(CONFIG))
            or protocol["environment"] != inherited.environment()
            or protocol["source_sha256"] != inherited.source_inventory(CONFIG)
            or digest(out / "tasks.json") != protocol["tasks_sha256"]
            or tasks != make_tasks(protocol["references"])):
        raise ValueError("Frozen protocol, source, environment or tasks changed")
    inherited.verify_files(protocol["references"]["files"])
    inherited.verify_git_blobs(protocol["references"]["git_blobs"])
    return protocol, tasks


def validate(out):
    verify(out)
    folder = out / "validation"
    folder.mkdir(exist_ok=False)
    results = []
    for name, args in [
        ("toy", ["tests/test_physical_prefix_order.py"]),
        ("full", []),
    ]:
        xml = folder / f"{name}-pytest.xml"
        command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
        if base_temp := os.environ.get("ASAR_PREFIX_PYTEST_BASE"):
            scratch = Path(base_temp) / name
            if not scratch.parent.is_dir():
                raise FileNotFoundError(f"Create the scratch parent first: {scratch.parent}")
            if scratch.exists():
                raise FileExistsError(f"Use a new pytest scratch directory: {scratch}")
            command.append(f"--basetemp={scratch}")
        command.extend([f"--junitxml={xml}", *args])
        with (folder / f"{name}-pytest.stdout.log").open("xb") as stdout, \
                (folder / f"{name}-pytest.stderr.log").open("xb") as stderr:
            start = time.perf_counter()
            run = subprocess.run(command, cwd=ROOT, stdout=stdout, stderr=stderr,
                                 env=inherited.child_environment(), check=False)
        suites = list(ET.parse(xml).iter("testsuite")) if xml.is_file() else []
        attrs = {key: sum(int(s.attrib.get(key, "0")) for s in suites)
                 for key in ("tests", "failures", "errors", "skipped")}
        results.append(dict(name=name, command=command, returncode=run.returncode,
                            seconds=time.perf_counter()-start,
                            junit_sha256=digest(xml) if suites else None, **attrs))
        ok = run.returncode == 0 and attrs["tests"] > 0 and not (attrs["failures"] or attrs["errors"])
        save(folder / "validation.json", dict(
            status="passed" if ok and name == "full" else "toy_passed" if ok else "blocked",
            protocol_sha256=digest(out / "protocol.json"), results=results,
        ), replace=True)
        print(f"{name}: {attrs}, exit {run.returncode}", flush=True)
        if not ok:
            raise RuntimeError(f"{name} validation failed; see {folder}")
    verify(out)


def require_validation(out):
    path = out / "validation/validation.json"
    test = read(path)
    if (test["status"] != "passed" or test["protocol_sha256"] != digest(out / "protocol.json")
            or [entry["name"] for entry in test["results"]] != ["toy", "full"]):
        raise ValueError("Toy/Oracle and full tests have not passed in this freeze")
    for entry in test["results"]:
        if (entry["returncode"] != 0 or entry["tests"] <= 0 or entry["failures"] or entry["errors"]
                or digest(path.parent / f"{entry['name']}-pytest.xml") != entry["junit_sha256"]):
            raise ValueError("Frozen test evidence changed")


def require_diagnostic(out):
    gate = read(out / "equal-work.json")
    if (gate["status"] != "passed" or gate["admitted"] is not True
            or gate["run_count"] != DESIGN["diagnostic"]["runs"]
            or gate["expected_expansions"] != DESIGN["diagnostic"]["expansions"]
            or gate["protocol_sha256"] != digest(out / "diagnostics" / "protocol.json")
            or len(gate["runs"]) != DESIGN["diagnostic"]["runs"]
            or len(gate["comparisons"]) != len(DESIGN["instances"])
            or any(not pair["off_shadow_invariant_passed"] for pair in gate["comparisons"])):
        raise ValueError("Fixed-work diagnostic did not pass")
    for evidence in gate["runs"]:
        directory = (out / evidence["path"]).resolve()
        if (directory.parent != out / "diagnostics" / "runs"
                or digest(directory / "record.json") != evidence["record_sha256"]
                or digest(directory / "result.json") != evidence["result_sha256"]):
            raise ValueError("Fixed-work run evidence changed")


def check_result(task, result, protocol):
    # Outer C0 execution is identical in both arms. Preserve the old validator's
    # expected outer labels while checking our experimental arm separately.
    raw = result["raw"]
    inner = raw["phases"][0]["inner"]
    expected_algorithm = ("physical_prefix_order_v1" if task["method"] == "C0_PREFIX"
                          else "physical_refinement_diagnostic_v1")
    ordering = inner["diagnostics"].get("prefix_order")
    if (result["method"] != task["method"] or inner["algorithm"] != expected_algorithm
            or inner["max_expansions"] is not None or inner.get("state_merge") is not None
            or (task["method"] == "C0_PREFIX") != (ordering is not None)
            or (ordering and (ordering["policy"] != DESIGN["frontier"]
                             or sum(ordering["final_band_sizes"]) != inner["open_count"]))
            or not 0 < result["algorithm_wall_s"] <= task["seconds"]):
        raise ValueError("Formal arm does not match its registered scheduler, deadline or merge mode")
    legacy.verify_result(dict(task, method="C0"), dict(result, method="C0"), protocol)


def worker(out, run_id):
    protocol, tasks = verify(out)
    folder = out / "runs" / run_id
    task = read(folder / "task.json")
    if task not in tasks or task_id(task) != run_id:
        raise ValueError("Unregistered formal task")
    from asar_repro import physical_rolling as rolling
    from asar_repro.h2_inputs import load_h2_input
    from asar_repro.physical_prefix_order import solve_physical_prefix_order
    from asar_repro.physical_search import independent_replay

    legacy.assert_local_project_modules()
    config, refs = protocol["config"], protocol["references"]
    case, reference = (refs[key][task["instance"]] for key in ("instances", "references"))
    before = time.perf_counter()
    problem, _, _, info = load_h2_input(
        ROOT, case, ROOT / config["source_root"] / "inputs" / case["id"], "heading_square"
    )
    input_load = time.perf_counter() - before
    if (info["manifest_sha256"] != task["manifest_sha256"]
            or info["particle_sha256"] != refs["archive_hashes"][task["instance"]]["particle_sha256"]):
        raise ValueError("Original forcing or particle identity changed")
    if task["method"] == "C0_PREFIX":
        solver_binding = patch.object(rolling, "solve_physical_refinement", solve_physical_prefix_order)
    else:
        solver_binding = nullcontext()
    with solver_binding:
        before, cpu = time.perf_counter(), time.process_time()
        raw = rolling.run_physical_rolling(
            problem, method="C0", initial_waypoints=reference["waypoints"],
            total_seconds=task["seconds"], triggers=config["search"]["triggers"],
            anchor_guard_s=config["search"]["anchor_guard_s"],
            solver_reserve_s=config["search"]["solver_reserve_s"], solver_options=config["solver"],
        )
        wall, cpu_s = time.perf_counter()-before, time.process_time()-cpu
    if raw.get("error") is not None or raw.get("status") != "completed":
        save(folder / "raw_failure.json", legacy.failure_safe(raw))
        raise ValueError(f"Formal arm failed: {raw.get('error')}")
    before = time.perf_counter()
    score = problem.replay(raw["waypoints"], connectivity=8)
    independent = independent_replay(problem, raw["waypoints"], connectivity=8)
    if (abs(independent["J"] - score["J"]) > 1e-8
            or abs(independent["pd_final"] - score["pd_final"]) > 1e-8
            or len(independent["survival"]) != len(score["survival"])
            or any(abs(a-b) > 1e-8 for a, b in zip(independent["survival"], score["survival"]))):
        raise ValueError("Independent unchanged scorer disagrees")
    audit = legacy.audit_execution(problem, raw, reference, config["decision"]["score_absolute"])
    result = dict(
        status="valid", method=task["method"], J=score["J"], pd_final=score["pd_final"],
        physical_replay=score, raw=raw, inputs=info, environment=inherited.environment(),
        execution_audit=audit, reference_sha256=object_digest(reference),
        formal_optimality_certificate=False, algorithm_wall_s=wall, algorithm_cpu_s=cpu_s,
        input_load_s=input_load, independent_audit_s=time.perf_counter()-before,
    )
    check_result(task, result, protocol)
    save(folder / "result.json", dict(task=task, result=result))


def run(out):
    import psutil

    protocol, tasks = verify(out)
    check_protected_checkout()
    require_validation(out)
    require_diagnostic(out)
    config = protocol["config"]
    watch = config["watchdog"]
    for ordinal, task in enumerate(tasks, 1):
        identity = task_id(task)
        folder = out / "runs" / identity
        folder.mkdir(parents=True, exist_ok=False)
        save(folder / "task.json", task)
        command = [sys.executable, str(Path(__file__).resolve()), "_worker", "--out", str(out), identity]
        print(f"{ordinal}/{len(tasks)} {task['instance']} {task['method']} repeat {task['repetition']}",
              flush=True)
        before, peak, killed = time.perf_counter(), 0, None
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        with (folder / "stdout.log").open("xb") as stdout, (folder / "stderr.log").open("xb") as stderr:
            with subprocess.Popen(command, cwd=ROOT, stdout=stdout, stderr=stderr,
                                  env=inherited.child_environment(), creationflags=flags) as child:
                try:
                    process = psutil.Process(child.pid)
                    while child.poll() is None:
                        try:
                            peak = max(peak, process.memory_info().rss)
                        except psutil.NoSuchProcess:
                            break
                        if peak > watch["rss_limit_bytes"]:
                            killed = "rss_limit"
                            break
                        if time.perf_counter()-before > task["seconds"] + watch["grace_seconds"]:
                            killed = "process_watchdog"
                            break
                        time.sleep(watch["poll_seconds"])
                except BaseException:
                    child.kill()
                    raise
                finally:
                    if killed and child.poll() is None:
                        child.kill()
                rc = child.wait()
        path = folder / "result.json"
        problem = None
        if rc != 0 or killed or not path.is_file():
            problem = "worker did not complete"
        else:
            try:
                payload = read(path)
                if payload["task"] != task:
                    raise ValueError("Saved task differs from protocol")
                check_result(task, payload["result"], protocol)
            except (KeyError, OSError, TypeError, ValueError) as error:
                problem = str(error)
        save(folder / "record.json", dict(
            task=task, command=command, status="failed" if problem else "completed",
            returncode=rc, watchdog=killed, verification_error=problem, peak_rss_bytes=peak,
            process_wall_s=time.perf_counter()-before,
            result_sha256=digest(path) if path.is_file() else None,
            frozen_evidence=dict(
                protocol_sha256=digest(out / "protocol.json"),
                validation_sha256=digest(out / "validation" / "validation.json"),
                fixed_work_sha256=digest(out / "equal-work.json"),
            ),
        ))
        if problem:
            raise RuntimeError(f"Failed task retained at {folder}: {problem}")
        print(f"Completed {identity}", flush=True)
    verify(out)
    check_protected_checkout()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "validate", "run", "_worker"))
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("run_id", nargs="?")
    args = parser.parse_intermixed_args()
    out = args.out.resolve()
    if (out.parent != OUT.parent.resolve() or not out.name.startswith("local_r")
            or not out.name.removeprefix("local_r").isdigit()):
        parser.error("Use a fresh local_rN directory under the registered batch root")
    if args.action == "_worker":
        worker(out, args.run_id)
    else:
        {"prepare": prepare, "validate": validate, "run": run}[args.action](out)


if __name__ == "__main__":
    main()

