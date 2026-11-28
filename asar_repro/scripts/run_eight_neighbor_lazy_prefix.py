#!/usr/bin/env python3
"""Freeze and run the lazy-prefix diagnostic and paired 30 s study."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import nullcontext
import os
from pathlib import Path
import random
from statistics import median
import subprocess
import sys
import time
from unittest.mock import patch
import xml.etree.ElementTree as ET

import run_eight_neighbor_progress as previous

ROOT = previous.ROOT
BASE = "e98908ca6bc2db771a5c43d986446cdbc59f1b86"
OUT = ROOT / "outputs/eight_neighbor_lazy_prefix_20261128/local_r1"
CONFIG = previous.CONFIG
inherited, legacy = previous.inherited, previous.legacy
read, save, digest, object_digest = previous.read, previous.save, previous.digest, previous.object_digest
HUDSON = tuple(i for i in previous.DESIGN["instances"] if i.startswith("hudson"))
DESIGN = {
    "name": "eight-neighbor-lazy-prefix",
    "instances": previous.DESIGN["instances"],
    "methods": ["C0", "C0_PROGRESS", "C0_LAZY"],
    "repetitions": 3,
    "seconds": 30.0,
    "formal_seed": 2026112805,
    "diagnostic_seed": 2026112806,
    "jitter_seed": 2026112807,
    "objective": "original completion_J; legal routes replayed by both original scorers",
    "progress_policy": previous.DESIGN["progress_policy"],
    "lazy_policy": "native single heap until first actual activation; exact 512-window; one charged migration",
    "merge_mode": "off for every arm",
    "diagnostic": {
        "instances": list(HUDSON), "heaps": [1, 3], "statistics": [False, True],
        "max_expansions": 4096, "wall_ceiling": 120.0, "repetitions": 3,
        "trace_pass_repetitions": 1, "force_reservations_off": True,
    },
    "jitter": {"instances": list(HUDSON), "methods": ["C0_A", "C0_B"], "repetitions": 3},
    "decision": dict(
        previous.DESIGN["decision"],
        protected_4201_J=58.5220872, protected_4201_Pd=0.090948,
        protected_4201_absolute_tolerance=1e-8,
    ),
}
STAGE_FILES = {"P30": "tasks.json", "jitter": "jitter_tasks.json", "ablation": "diagnostic_tasks.json"}


def check_protected_checkout():
    subprocess.run(["git", "diff", "--quiet", "--no-renames", "--diff-filter=DMRTUXB",
                    BASE, "--", "."], cwd=ROOT.parent, check=True)


def build_tasks(refs):
    def task(instance, method, repetition, stage, seconds, **extra):
        return dict(instance=instance, method=method, repetition=repetition, stage=stage, seconds=seconds,
                    manifest_sha256=refs["archive_hashes"][instance]["manifest_sha256"],
                    reference_sha256=object_digest(refs["references"][instance]), **extra)

    def make_pairs(stage, instances, methods, count, seed):
        rng = random.Random(seed)
        blocks = [(i, r) for i in instances for r in range(count)]
        rng.shuffle(blocks)
        rows = []
        for i, repeat in blocks:
            arms = list(methods)
            rng.shuffle(arms)
            rows.extend(task(i, arm, repeat, stage, 30.0) for arm in arms)
        return rows

    rng = random.Random(DESIGN["diagnostic_seed"])
    d = DESIGN["diagnostic"]
    diag = []
    for trace_pops, repetitions in [(True, d["trace_pass_repetitions"]), (False, d["repetitions"])]:
        blocks = [(i, r) for i in HUDSON for r in range(repetitions)]
        rng.shuffle(blocks)
        for i, repeat in blocks:
            arms = [(h, s) for h in d["heaps"] for s in d["statistics"]]
            rng.shuffle(arms)
            for heaps, stats in arms:
                diag.append(task(i, f"h{heaps}_stats{int(stats)}", repeat, "ablation", d["wall_ceiling"],
                                 heaps=heaps, statistics=stats, trace_pops=trace_pops,
                                 max_expansions=d["max_expansions"]))
    return {
        "P30": make_pairs("P30", DESIGN["instances"], DESIGN["methods"], DESIGN["repetitions"], DESIGN["formal_seed"]),
        "jitter": make_pairs("jitter", HUDSON, DESIGN["jitter"]["methods"],
                             DESIGN["jitter"]["repetitions"], DESIGN["jitter_seed"]),
        "ablation": diag,
    }


def task_id(task):
    return f"{task['stage']}_" + object_digest(task)[:20]


def run_directory(out, task):
    stage = task["stage"]
    return (out if stage == "P30" else out / stage) / "runs" / task_id(task)


def prepare(out):
    from asar_repro.physical_progress_prefix import PROGRESS_POLICY
    if (out / "protocol.json").exists():
        raise FileExistsError("Use a fresh local_rN for a new protocol")
    check_protected_checkout()
    if PROGRESS_POLICY != DESIGN["progress_policy"]:
        raise ValueError("Frozen progress policy differs")
    config = inherited.check_config(read(CONFIG))
    refs = inherited.reference_evidence(config, load_archives=True)
    tasks = build_tasks(refs)
    out.mkdir(parents=True, exist_ok=True)
    for stage, name in STAGE_FILES.items():
        save(out / name, tasks[stage])
    save(out / "protocol.json", dict(
        status="frozen_before_tests", frozen_utc=inherited.stamp(), base_commit=BASE,
        design=DESIGN, config=config, references=refs, environment=inherited.environment(),
        source_sha256=previous.source_inventory(),
        tasks_sha256={stage: digest(out / name) for stage, name in STAGE_FILES.items()},
    ))
    print(f"Frozen ablation={len(tasks['ablation'])}, jitter={len(tasks['jitter'])}, P30={len(tasks['P30'])}; "
          f"{len(refs['files'])} file hashes, {len(refs['git_blobs'])} inherited blobs, four H2 inputs.")


def verify(out):
    protocol = read(out / "protocol.json")
    tasks = {stage: read(out / name) for stage, name in STAGE_FILES.items()}
    if (protocol["base_commit"] != BASE or protocol["design"] != DESIGN
            or protocol["config"] != inherited.check_config(read(CONFIG))
            or protocol["environment"] != inherited.environment()
            or protocol["source_sha256"] != previous.source_inventory()
            or protocol["tasks_sha256"] != {s: digest(out / n) for s, n in STAGE_FILES.items()}
            or tasks != build_tasks(protocol["references"])):
        raise ValueError("Protocol, task, code or runtime fingerprints changed")
    inherited.verify_files(protocol["references"]["files"])
    inherited.verify_git_blobs(protocol["references"]["git_blobs"])
    return protocol, tasks


def validate(out):
    verify(out)
    folder = out / "validation"
    folder.mkdir(exist_ok=False)
    results = []
    for name, paths in [
        ("toy", ["tests/test_physical_lazy_prefix.py", "tests/test_physical_progress_prefix.py"]),
        ("full", []),
    ]:
        xml = folder / f"{name}-pytest.xml"
        cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
        if base_temp := os.environ.get("ASAR_PREFIX_PYTEST_BASE"):
            scratch = Path(base_temp) / name
            if not scratch.parent.is_dir() or scratch.exists():
                raise ValueError(f"Use a fresh pytest scratch path with an existing parent: {scratch}")
            cmd.append(f"--basetemp={scratch}")
        cmd.extend([f"--junitxml={xml}", *paths])
        with (folder / f"{name}-pytest.stdout.log").open("xb") as stdout, \
                (folder / f"{name}-pytest.stderr.log").open("xb") as stderr:
            start = time.perf_counter()
            run = subprocess.run(cmd, cwd=ROOT, stdout=stdout, stderr=stderr,
                                 env=inherited.child_environment(), check=False)
        suites = list(ET.parse(xml).iter("testsuite")) if xml.is_file() else []
        attrs = {k: sum(int(s.attrib.get(k, "0")) for s in suites)
                 for k in ("tests", "failures", "errors", "skipped")}
        results.append(dict(name=name, command=cmd, returncode=run.returncode,
                            seconds=time.perf_counter() - start,
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


def replay(problem, path):
    from asar_repro.physical_search import independent_replay

    score = problem.replay(path, connectivity=8)
    check = independent_replay(problem, path, connectivity=8)
    if (abs(check["J"] - score["J"]) > 1e-8 or abs(check["pd_final"] - score["pd_final"]) > 1e-8
            or len(check["survival"]) != len(score["survival"])
            or any(abs(a-b) > 1e-8 for a, b in zip(check["survival"], score["survival"]))):
        raise ValueError("Independent unchanged scorer disagrees")
    return score


def check_result(task, result, protocol):
    if result["method"] != task["method"] or result["status"] != "valid":
        raise ValueError("Wrong result identity")
    if not 0 < result["algorithm_wall_s"] <= task["seconds"]:
        raise ValueError(f"Algorithm wall {result['algorithm_wall_s']:.9f}s outside (0, {task['seconds']}]")
    if result["inputs"]["particle_sha256"] != protocol["references"]["archive_hashes"][task["instance"]]["particle_sha256"]:
        raise ValueError("Wrong particle input identity")
    stage = task["stage"]
    if stage == "ablation":
        inner = result["solver"]
        diag = inner["diagnostics"]
        lazy = diag["lazy_frontier"]
        order = diag["prefix_order"]
        score = result["physical_replay"]
        reference = protocol["references"]["references"][task["instance"]]
        if (inner["algorithm"] != "physical_lazy_prefix_v1" or inner["error"] is not None
                or inner["stop_reason"] != "max_expansions" or inner["expanded"] != task["max_expansions"]
                or inner["initial_score"]["waypoints"] != reference["waypoints"]
                or lazy["diagnostic_heaps"] != task["heaps"] or lazy["diagnostic_statistics"] is not task["statistics"]
                or lazy["starting_heaps"] != task["heaps"] or lazy["ending_heaps"] != task["heaps"]
                or lazy["migrations"] != 0 or order["reserved_early_pops"] or order["reserved_middle_pops"]
                or bool(diag["pop_trace"]) is not task["trace_pops"]
                or score["waypoints"] != inner["waypoints"] or abs(score["J"] - inner["J"]) > 1e-8
                or abs(score["pd_final"] - inner["pd_final"]) > 1e-8):
            raise ValueError("Fixed-work solver or replay does not match registered factorial arm")
        return
    method = "C0" if stage == "jitter" else task["method"]
    if method in ("C0", "C0_PROGRESS"):
        previous.check_result(dict(task, method=method), dict(result, method=method), protocol)
        return
    inner = result["raw"]["phases"][0]["inner"]
    diag = inner["diagnostics"]
    lazy, order, progress = (diag[k] for k in ("lazy_frontier", "prefix_order", "progress_schedule"))
    if (inner["algorithm"] != "physical_lazy_prefix_v1" or inner["max_expansions"] is not None
            or inner.get("state_merge") is not None or lazy["starting_heaps"] != 1
            or lazy["diagnostic_heaps"] is not None or lazy["diagnostic_statistics"] is not None
            or lazy["migrations"] not in (0, 1) or lazy["migration_attempts"] not in (0, 1)
            or lazy["migrations"] > lazy["migration_attempts"]
            or lazy["ending_heaps"] != 1 + 2 * lazy["migrations"]
            or order["policy"] != DESIGN["progress_policy"]
            or sum(order["final_band_sizes"]) != inner["open_count"]
            or progress["policy"] != DESIGN["progress_policy"]["activation"]):
        raise ValueError("Formal lazy solver does not match frozen scheduling policy")
    legacy.verify_result(dict(task, method="C0"), dict(result, method="C0"), protocol)


def worker(out, stage, run_id):
    protocol, tasks = verify(out)
    work = out if stage == "P30" else out / stage
    folder = work / "runs" / run_id
    task = read(folder / "task.json")
    if task not in tasks[stage] or task_id(task) != run_id:
        raise ValueError("Unregistered task")
    from asar_repro import physical_rolling as rolling
    from asar_repro.h2_inputs import load_h2_input
    from asar_repro.physical_lazy_prefix import solve_physical_lazy_prefix
    from asar_repro.physical_progress_prefix import solve_physical_progress_prefix

    legacy.assert_local_project_modules()
    config, refs = protocol["config"], protocol["references"]
    case, reference = (refs[key][task["instance"]] for key in ("instances", "references"))
    before = time.perf_counter()
    problem, _, _, info = load_h2_input(
        ROOT, case, ROOT / config["source_root"] / "inputs" / case["id"], "heading_square",
    )
    load_s = time.perf_counter() - before
    if (info["manifest_sha256"] != task["manifest_sha256"]
            or info["particle_sha256"] != refs["archive_hashes"][task["instance"]]["particle_sha256"]
            or info["opendrift_runs_in_search"] != 0):
        raise ValueError("Wrong frozen input")
    base = dict(status="valid", method=task["method"], inputs=info, environment=inherited.environment(),
                reference_sha256=object_digest(reference), formal_optimality_certificate=False, input_load_s=load_s)
    try:
        if stage == "ablation":
            start, cpu = time.perf_counter(), time.process_time()
            raw = solve_physical_lazy_prefix(
                problem, connectivity=8, initial_waypoints=reference["waypoints"], max_seconds=task["seconds"],
                max_expansions=task["max_expansions"], diagnostic_heaps=task["heaps"],
                diagnostic_statistics=task["statistics"], trace_pops=task["trace_pops"], **config["solver"],
            )
        else:
            selected = {"C0_PROGRESS": solve_physical_progress_prefix,
                        "C0_LAZY": solve_physical_lazy_prefix}.get(task["method"])
            with nullcontext() if selected is None else patch.object(rolling, "solve_physical_refinement", selected):
                start, cpu = time.perf_counter(), time.process_time()
                raw = rolling.run_physical_rolling(
                    problem, method="C0", initial_waypoints=reference["waypoints"],
                    total_seconds=task["seconds"], triggers=config["search"]["triggers"],
                    anchor_guard_s=config["search"]["anchor_guard_s"],
                    solver_reserve_s=config["search"]["solver_reserve_s"], solver_options=config["solver"],
                )
        wall, cpu_s = time.perf_counter() - start, time.process_time() - cpu
        base.update(algorithm_wall_s=wall, algorithm_cpu_s=cpu_s)
        base["solver" if stage == "ablation" else "raw"] = raw
        if raw.get("error") is not None or (stage != "ablation" and raw["status"] != "completed"):
            raise ValueError(f"Solver error: {raw.get('error')}")
        before = time.perf_counter()
        score = replay(problem, raw["waypoints"])
        base.update(J=score["J"], pd_final=score["pd_final"], physical_replay=score)
        if stage != "ablation":
            base["execution_audit"] = legacy.audit_execution(problem, raw, reference, config["decision"]["score_absolute"])
        base["independent_audit_s"] = time.perf_counter() - before
        check_result(task, base, protocol)
    except (AssertionError, KeyError, OSError, TypeError, ValueError) as error:
        save(folder / "rejected_result.json", legacy.failure_safe(dict(
            status="validation_rejected", task=task, result=base,
            error=dict(type=type(error).__name__, message=str(error)),
        )))
        raise
    save(folder / "result.json", dict(task=task, result=base))


def run_task(out, task, protocol):
    import psutil

    folder = run_directory(out, task)
    folder.mkdir(parents=True, exist_ok=False)
    save(folder / "task.json", task)
    command = [sys.executable, str(Path(__file__).resolve()), "_worker", "--out", str(out),
               task["stage"], task_id(task)]
    watch = protocol["config"]["watchdog"]
    before, peak, watchdog = time.perf_counter(), 0, None
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
                        watchdog = "rss_limit"
                        break
                    if time.perf_counter() - before > task["seconds"] + watch["grace_seconds"]:
                        watchdog = "process_watchdog"
                        break
                    time.sleep(watch["poll_seconds"])
            except BaseException:
                child.kill()
                raise
            finally:
                if watchdog and child.poll() is None:
                    child.kill()
            rc = child.wait()
    path, rejected = (folder / fn for fn in ("result.json", "rejected_result.json"))
    error = None
    if rc or watchdog or not path.is_file():
        error = read(rejected)["error"]["message"] if rejected.is_file() else "worker did not finish"
    else:
        try:
            payload = read(path)
            if payload["task"] != task or peak == 0:
                raise ValueError("Missing task identity or RSS sample")
            check_result(task, payload["result"], protocol)
        except (KeyError, OSError, TypeError, ValueError) as exc:
            error = str(exc)
    save(folder / "record.json", dict(
        task=task, command=command, status="failed" if error else "completed", returncode=rc,
        watchdog=watchdog, verification_error=error, peak_rss_bytes=peak, process_wall_s=time.perf_counter()-before,
        result_sha256=digest(path) if path.is_file() else None,
        rejected_result_sha256=digest(rejected) if rejected.is_file() else None,
        frozen_evidence=gate_evidence(out, task["stage"]),
    ))
    if error:
        raise RuntimeError(f"Stopped on {task_id(task)}. Evidence retained at {folder}: {error}")
    print(f"Completed {task_id(task)}", flush=True)


def gate_evidence(out, stage):
    evidence = dict(protocol_sha256=digest(out / "protocol.json"),
                    validation_sha256=digest(out / "validation" / "validation.json"),
                    progress_policy_sha256=object_digest(DESIGN["progress_policy"]))
    if stage != "ablation":
        evidence["ablation_sha256"] = digest(out / "ablation.json")
    if stage == "P30":
        evidence["jitter_sha256"] = digest(out / "jitter.json")
    return evidence


def collect(out, tasks, protocol):
    for task in tasks:
        folder = run_directory(out, task)
        rec = read(folder / "record.json")
        path = folder / "result.json"
        payload = read(path)
        if (rec["status"] != "completed" or rec["returncode"] or rec["watchdog"]
                or rec["result_sha256"] != digest(path) or rec["frozen_evidence"] != gate_evidence(out, task["stage"])
                or task != rec["task"] or task != payload["task"] or task != read(folder / "task.json")):
            raise ValueError(f"Raw evidence incomplete for {task_id(task)}")
        result = payload["result"]
        check_result(task, result, protocol)
        yield task, result, rec


def history_signature(inner):
    return object_digest([{k: v for k, v in row.items() if k != "elapsed_s"} for row in inner["history"]])


def ablation_report(out, data):
    rows = []
    signatures = {}
    for task, result, rec in data:
        inner = result["solver"]
        trace = inner["diagnostics"]["pop_trace"]
        comparison = dict(history=history_signature(inner), J=result["J"], Pd=result["pd_final"],
                          waypoints=inner["waypoints"], expanded=inner["expanded"], generated=inner["generated"],
                          open_count=inner["open_count"], completion_calls=inner["stats"]["completion_calls"],
                          terminal_candidates=inner["stats"]["terminal_candidates"])
        expected = signatures.setdefault(task["instance"], dict(common=comparison, trace=None))
        if expected["common"] != comparison:
            raise ValueError(f"Fixed work differs with heaps or statistics: {task}")
        trace_hash = object_digest(trace) if task["trace_pops"] else None
        if trace_hash is not None:
            if expected["trace"] is None:
                expected["trace"] = trace_hash
            elif trace_hash != expected["trace"]:
                raise ValueError(f"Full pop trace differs at equal work: {task}")
        rows.append(dict(
            **task, run_id=task_id(task), result_sha256=rec["result_sha256"], trace_sha256=trace_hash,
            trace_pops_count=len(trace), history_sha256=comparison["history"], expanded=inner["expanded"],
            generated=inner["generated"], J=result["J"], Pd=result["pd_final"],
            algorithm_wall_s=result["algorithm_wall_s"], algorithm_cpu_s=result["algorithm_cpu_s"],
            process_wall_s=rec["process_wall_s"], peak_rss_mib=rec["peak_rss_bytes"]/2**20,
        ))
    groups = []
    for instance in HUDSON:
        for heaps in (1, 3):
            for stats in (False, True):
                values = [r for r in rows if r["instance"] == instance and r["heaps"] == heaps
                          and r["statistics"] is stats and not r["trace_pops"]]
                groups.append(dict(instance=instance, heaps=heaps, statistics=stats,
                                   **{f"median_{key}": median(r[key] for r in values) for key in
                                      ("algorithm_wall_s", "algorithm_cpu_s", "peak_rss_mib")}))
    save(out / "ablation.json", dict(
        status="passed", semantic_runs=sum(r["trace_pops"] for r in rows),
        timed_runs=sum(not r["trace_pops"] for r in rows), all_trace_and_work_equal=True,
        max_expansions=DESIGN["diagnostic"]["max_expansions"], medians=groups, runs=rows,
    ))


def from_run(task, result, rec):
    inner = result["raw"]["phases"][0]["inner"]
    diag = inner["diagnostics"]
    return dict(
        **task, run_id=task_id(task), result_sha256=rec["result_sha256"],
        J=result["J"], Pd=result["pd_final"], expanded=inner["expanded"],
        first_search_terminal_s=diag.get("first_search_terminal_generated_s"),
        first_search_improvement_s=next((h["elapsed_s"] for h in inner["history"]
                                         if h["source"] == "search"), None),
        best_s=inner["best_elapsed_s"], algorithm_wall_s=result["algorithm_wall_s"],
        algorithm_cpu_s=result["algorithm_cpu_s"], peak_rss_mib=rec["peak_rss_bytes"] / 2**20,
        stop_reason=inner["stop_reason"],
    )


def jitter_report(out, data):
    rows = [from_run(*r) for r in data]
    pairs = []
    for instance in HUDSON:
        for rep in range(DESIGN["jitter"]["repetitions"]):
            a, b = sorted((r for r in rows if r["instance"] == instance and r["repetition"] == rep),
                          key=lambda r:r["method"])
            ts = [r["first_search_improvement_s"] for r in (a,b)]
            pairs.append(dict(instance=instance, repetition=rep, run_ids=[a["run_id"], b["run_id"]],
                              J_B_minus_A=b["J"] - a["J"], Pd_B_minus_A=b["Pd"] - a["Pd"],
                              first_search_improvement_B_minus_A=(None if None in ts else ts[1]-ts[0])))
    save(out / "jitter.json", dict(status="passed", run_count=len(rows), pairs=pairs, runs=rows))


def verify_gate(out, stage, tasks, protocol):
    name = {"ablation": "ablation.json", "jitter": "jitter.json"}[stage]
    gate = read(out / name)
    if gate["status"] != "passed":
        raise ValueError(f"{stage} did not pass")
    results = list(collect(out, tasks[stage], protocol))
    expected = {task_id(task): rec["result_sha256"] for task, _, rec in results}
    if len(gate["runs"]) != len(expected) or {row["run_id"]: row["result_sha256"] for row in gate["runs"]} != expected:
        raise ValueError(f"{stage} gate does not correspond to raw records")
    if stage == "ablation" and (gate["semantic_runs"] != 8 or gate["timed_runs"] != 24
                                 or gate["all_trace_and_work_equal"] is not True):
        raise ValueError("Ablation did not pass the exact fixed-work parity gate")
    if stage == "jitter" and (gate["run_count"] != 12 or len(gate["pairs"]) != 6):
        raise ValueError("Incomplete C0/C0 pairs")


def run_stage(out, stage):
    protocol, tasks = verify(out)
    check_protected_checkout()
    previous.require_validation(out)
    if stage != "ablation":
        verify_gate(out, "ablation", tasks, protocol)
    if stage == "P30":
        verify_gate(out, "jitter", tasks, protocol)
    selected = tasks[stage]
    for i, task in enumerate(selected, 1):
        print(f"{stage} {i}/{len(selected)} {task['instance']} {task['method']} repeat {task['repetition']}"
              + (" trace" if task.get("trace_pops") else ""), flush=True)
        run_task(out, task, protocol)
    if stage != "P30":
        {"ablation": ablation_report, "jitter": jitter_report}[stage](
            out, collect(out, selected, protocol),
        )
    verify(out)
    check_protected_checkout()


def analyze(out):
    from analyze_eight_neighbor_lazy_prefix import analyze as generate

    protocol, tasks = verify(out)
    previous.require_validation(out)
    for stage in ("ablation", "jitter"):
        verify_gate(out, stage, tasks, protocol)
    if sum(1 for _ in collect(out, tasks["P30"], protocol)) != 36:
        raise ValueError("Full P30 matrix is required")
    generate(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "validate", "ablation", "jitter", "P30", "analyze", "_worker"))
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("worker_args", nargs="*")
    args = parser.parse_intermixed_args()
    out = args.out.resolve()
    if out.parent != OUT.parent.resolve() or not out.name.removeprefix("local_r").isdigit():
        parser.error("Use a new local_rN under the registered output root")
    if args.action == "_worker":
        worker(out, *args.worker_args)
    elif args.action in STAGE_FILES:
        run_stage(out, args.action)
    else:
        {"prepare": prepare, "validate": validate, "analyze": analyze}[args.action](out)


if __name__ == "__main__":
    main()
