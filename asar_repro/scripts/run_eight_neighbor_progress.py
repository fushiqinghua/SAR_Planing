#!/usr/bin/env python3
"""Run a preregistered paired progress-gated prefix-order study; no automatic experiments."""
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
BASE = "5b7ffcf9c90a8e3b219ae58a9f7fb066f069b588"
OUT = ROOT / "outputs/eight_neighbor_progress_20261128/local_r1"
CONFIG = inherited.DEFAULT_CONFIG
read, save = inherited.read, inherited.save
digest, object_digest = inherited.digest, inherited.object_digest
legacy = inherited._legacy

DESIGN = {
    "name": "eight-neighbor-progress-aware-prefix-v1",
    "instances": list(inherited.SELECTED),
    "methods": ["C0", "C0_PREFIX", "C0_PROGRESS"],
    "seconds": 30.0,
    "repetitions": 3,
    "task_order_seed": 2026112804,
    "pair_schedule": "shuffle instance/repetition blocks and all three arms",
    "objective": "original completion_J with original and independent physical replay",
    "merge_mode": "off for all three arms",
    "fixed_frontier": {
        "reserved_every": 4, "band_order": ["early", "middle"],
        "early": "4*tick < K", "middle": "K <= 4*tick < 3*K",
        "tail": "3*K <= 4*tick", "key": "original guide priority, original insertion serial",
        "empty_band": "global next", "state_drop": False,
    },
    "progress_policy": {
        "reserved_every": 4, "band_order": ["early", "middle"],
        "early": "4*tick < K", "middle": "K <= 4*tick < 3*K",
        "tail": "3*K <= 4*tick", "key": "original guide priority, original insertion serial",
        "empty_band": "global next", "state_drop": False,
        "activation": {
            "first_search_improvement_before_fraction": 0.20,
            "stagnation_seconds": 2.0,
            "window_expansions": 512,
            "tail_enter_fraction": 0.80,
            "tail_exit_fraction": 0.55,
            "recent_improvement_pause_s": 1.0,
        },
    },
    "decision": {
        "minimum_relative_J_improvement": 0.001,
        "secondary_relative_J_improvement": 0.005,
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


PROTECTED = (
    "src/asar_repro/physical_model.py", "src/asar_repro/physical_search.py",
    "src/asar_repro/physical_accel.py", "src/asar_repro/physical_refinement.py",
    "src/asar_repro/physical_prefix_order.py", "src/asar_repro/physical_rolling.py",
    "scripts/run_eight_neighbor_prefix_order.py",
    "scripts/run_eight_neighbor_rolling_merge.py",
    "tests/test_physical_prefix_order.py", "configs/eight_neighbor_rolling_merge.json",
)


def check_protected_checkout():
    subprocess.run(["git", "diff", "--exit-code", BASE, "--", *PROTECTED],
                   cwd=ROOT, check=True)


def source_inventory():
    inventory = inherited.source_inventory(CONFIG)
    for path in (ROOT / "docs/eight_neighbor_progress").glob("*"):
        if path.is_file() and path.suffix in (".md", ".json"):
            inventory[path.relative_to(ROOT).as_posix()] = digest(path)
    return dict(sorted(inventory.items()))


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
    from asar_repro.physical_progress_prefix import PROGRESS_POLICY

    if FRONTIER_POLICY != DESIGN["fixed_frontier"] or PROGRESS_POLICY != DESIGN["progress_policy"]:
        raise ValueError("The old or progress scheduler differs from the registered design")
    config = inherited.check_config(read(CONFIG))
    refs = inherited.reference_evidence(config, load_archives=True)
    tasks = make_tasks(refs)
    out.mkdir(parents=True, exist_ok=True)
    save(out / "tasks.json", tasks)
    save(out / "protocol.json", dict(
        status="frozen_before_tests", frozen_utc=inherited.stamp(), base_commit=BASE,
        design=DESIGN, config=config, references=refs,
        environment=inherited.environment(), source_sha256=source_inventory(),
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
            or protocol["source_sha256"] != source_inventory()
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
        ("toy", ["tests/test_physical_prefix_order.py", "tests/test_physical_progress_prefix.py"]),
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


def check_result(task, result, protocol):
    wall = result["algorithm_wall_s"]
    if not 0 < wall <= task["seconds"]:
        raise ValueError(f"Algorithm wall time {wall:.9f} s outside (0, {task['seconds']:.9f}] s")
    raw = result["raw"]
    inner = raw["phases"][0]["inner"]
    expected_algorithm = {
        "C0": "physical_refinement_diagnostic_v1",
        "C0_PREFIX": "physical_prefix_order_v1",
        "C0_PROGRESS": "physical_progress_prefix_v1",
    }[task["method"]]
    diagnostics = inner["diagnostics"]
    ordering = diagnostics.get("prefix_order")
    progress = diagnostics.get("progress_schedule")
    needs_frontier = task["method"] != "C0"
    if (result["method"] != task["method"] or inner["algorithm"] != expected_algorithm
            or inner["max_expansions"] is not None or inner.get("state_merge") is not None
            or needs_frontier != (ordering is not None)
            or (ordering and (ordering["policy"] != DESIGN[
                "progress_policy" if task["method"] == "C0_PROGRESS" else "fixed_frontier"]
                or sum(ordering["final_band_sizes"]) != inner["open_count"]))
            or (task["method"] == "C0_PROGRESS") != (progress is not None)
            or (progress is not None and
                (progress["policy"] != DESIGN["progress_policy"]["activation"]
                 or progress["active_decisions"] > progress["checked_pops"]
                 or progress["activations"] < progress["deactivations"]
                 or progress["first_search_improvement_s"] is not None and
                    progress["first_search_improvement_s"] > task["seconds"]))):
        raise ValueError("Formal arm does not match registered algorithm or policy")
    legacy.verify_result(dict(task, method="C0"), dict(result, method="C0"), protocol)

def save_checked_result(folder, task, result, protocol):
    try:
        check_result(task, result, protocol)
    except (KeyError, OSError, TypeError, ValueError) as error:
        save(folder / "rejected_result.json", legacy.failure_safe(dict(
            status="validation_rejected", error=dict(type=type(error).__name__, message=str(error)),
            task=task, result=result,
        )))
        raise
    save(folder / "result.json", dict(task=task, result=result))


def worker(out, run_id):
    protocol, tasks = verify(out)
    folder = out / "runs" / run_id
    task = read(folder / "task.json")
    if task not in tasks or task_id(task) != run_id:
        raise ValueError("Unregistered formal task")
    from asar_repro import physical_rolling as rolling
    from asar_repro.h2_inputs import load_h2_input
    from asar_repro.physical_prefix_order import solve_physical_prefix_order
    from asar_repro.physical_progress_prefix import solve_physical_progress_prefix
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
    solvers = {
        "C0": None,
        "C0_PREFIX": solve_physical_prefix_order,
        "C0_PROGRESS": solve_physical_progress_prefix,
    }
    selected = solvers[task["method"]]
    solver_binding = (nullcontext() if selected is None else
                      patch.object(rolling, "solve_physical_refinement", selected))
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
    save_checked_result(folder, task, result, protocol)


def run(out):
    import psutil

    protocol, tasks = verify(out)
    check_protected_checkout()
    require_validation(out)
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
        rejected = folder / "rejected_result.json"
        if rc != 0 or killed or not path.is_file():
            problem = (read(rejected)["error"]["message"] if rejected.is_file()
                       else "worker did not complete")
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
            rejected_result_sha256=digest(rejected) if rejected.is_file() else None,
            frozen_evidence=dict(
                protocol_sha256=digest(out / "protocol.json"),
                validation_sha256=digest(out / "validation" / "validation.json"),
                progress_policy_sha256=object_digest(DESIGN["progress_policy"]),
            ),
        ))
        if problem:
            raise RuntimeError(f"Failed task retained at {folder}: {problem}")
        print(f"Completed {identity}", flush=True)
    verify(out)
    check_protected_checkout()


def analyze(out):
    verify(out)
    require_validation(out)
    from analyze_eight_neighbor_progress import analyze as generate
    generate(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "validate", "run", "analyze", "_worker"))
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
        {"prepare": prepare, "validate": validate, "run": run, "analyze": analyze}[args.action](out)


if __name__ == "__main__":
    main()

