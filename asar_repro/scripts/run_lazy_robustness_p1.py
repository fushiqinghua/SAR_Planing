#!/usr/bin/env python3
"""P1: frozen 30-s timing-robustness experiment for C0 and lazy-prefix search.

This is a separate study: it never modifies or overwrites old experimental records.
Run plan -> prepare -> validate -> run -> analyze in the existing maritime-sar environment.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import nullcontext
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import random
import subprocess
import sys
import time
from statistics import median
from unittest.mock import patch
import xml.etree.ElementTree as ET

import run_eight_neighbor_lazy_prefix as old

ROOT = old.ROOT
BATCH = ROOT / "outputs/second_innovation_p1_20261128"
DEFAULT_OUT = BATCH / "local_r1"
REFERENCE = ROOT / "outputs/eight_neighbor_lazy_prefix_20261128/local_r1/protocol.json"
BASE_COMMIT = "440760c35e5c5e26f8ea44d5501e50088c3d2bcd"
DESIGN = {
    "study": "lazy_prefix_p1_timing_robustness",
    "reference_commit": BASE_COMMIT,
    "cases": {"hudson_h2_d1_s4101": 12, "hudson_h2_d2_s4201": 6},
    "arms": {
        "hudson_h2_d1_s4101": ["C0_A", "C0_B", "C0_LAZY"],
        "hudson_h2_d2_s4201": ["C0", "C0_LAZY"],
    },
    "seconds": 30.0,
    "task_seed": 2026112816,
    "target": {"hudson_h2_d1_s4101": 28.448979882240007,
               "hudson_h2_d2_s4201": 58.522087200},
    "baseline_initial_j": {"hudson_h2_d1_s4101": 28.72458835200001},
    "source_model": "unchanged original eight-neighbor C0, heading_square and completion_J",
    "lazy_model": "unchanged physical_lazy_prefix_v1",
    "metrics": "full route J, same-route Pd, time to first strict search improvement, RSS",
}
PROTECTED = (
    "src/asar_repro/physical_model.py", "src/asar_repro/physical_accel.py",
    "src/asar_repro/physical_search.py", "src/asar_repro/physical_refinement.py",
    "src/asar_repro/physical_rolling.py", "src/asar_repro/physical_lazy_prefix.py",
    "src/asar_repro/physical_progress_prefix.py",
    "scripts/run_eight_neighbor_lazy_prefix.py",
    "scripts/run_eight_neighbor_progress.py", "configs/eight_neighbor_rolling_merge.json",
)
SOURCES = PROTECTED + (
    "scripts/run_lazy_robustness_p1.py",
    "tests/test_lazy_robustness_p1.py",
    "docs/second_innovation_next/PLAN.md",
    "docs/second_innovation_next/P1_DECISIONS.md",
    "docs/second_innovation_next/LOCAL_RUNBOOK.md",
    "docs/second_innovation_next/P2_H3_PREREGISTRATION.md",
    "docs/second_innovation_next/h3_date_registry.json",
)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, data, overwrite=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w" if overwrite else "x", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_lock():
    return {p: sha(ROOT / p) for p in SOURCES}


def get_ref():
    source = read(REFERENCE)
    if source["design"]["name"] != "eight-neighbor-lazy-prefix":
        raise ValueError("Wrong historical lazy-prefix reference")
    if source["config"]["search"]["seconds"] != DESIGN["seconds"]:
        raise ValueError("Unmatched search budget")
    if source["design"]["progress_policy"]["activation"]["first_search_improvement_before_fraction"] != 0.2:
        raise ValueError("Historical progress policy changed")
    old.inherited.verify_files(source["references"]["files"])
    old.inherited.verify_git_blobs(source["references"]["git_blobs"])
    return source


def task_matrix():
    rng = random.Random(DESIGN["task_seed"])
    blocks = [(instance, repetition) for instance, n in DESIGN["cases"].items()
              for repetition in range(n)]
    rng.shuffle(blocks)
    tasks = []
    for instance, repetition in blocks:
        arms = list(DESIGN["arms"][instance])
        rng.shuffle(arms)
        for arm in arms:
            tasks.append(dict(instance=instance, repetition=repetition, method=arm,
                              seconds=DESIGN["seconds"], stage="P1", block=f"{instance}:{repetition}"))
    if len(tasks) != 48 or len(set(task_id(t) for t in tasks)) != 48:
        raise AssertionError("Expected 48 unique preassigned P1 runs")
    return tasks


def task_id(task):
    payload = json.dumps(task, sort_keys=True, separators=(",", ":"))
    return "P1_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def plan():
    return dict(status="prepared_not_run", branch="eight-neighbor-rolling-pilot-20261128",
                base_commit=BASE_COMMIT, config=DESIGN,
                tasks=48, max_algorithm_seconds=48*30,
                input_role="seen_development_timing_diagnostic",
                independence="not a new weather-date validation",
                experimental_claim="timing stability, not model generalization")


def prepare(out):
    if out.exists():
        raise FileExistsError(f"Choose a fresh local_rN: {out}")
    source = get_ref()
    from asar_repro.physical_lazy_prefix import solve_physical_lazy_prefix
    if not callable(solve_physical_lazy_prefix):
        raise ValueError("Original lazy solver not importable")
    tasks = task_matrix()
    out.mkdir(parents=True)
    write(out / "tasks.json", tasks)
    write(out / "protocol.json", dict(
        status="frozen_before_tests", design=DESIGN, historical_protocol_sha256=sha(REFERENCE),
        sources=source_lock(), tasks_sha256=sha(out / "tasks.json"),
        environment=old.inherited.environment(), references=source["references"],
        config=source["config"], base_commit=BASE_COMMIT))
    print("Frozen 48 paired runs. No search or drift run in prepare.", flush=True)


def verify(out):
    protocol = read(out / "protocol.json")
    if (protocol["status"] != "frozen_before_tests" or protocol["design"] != DESIGN
            or protocol["historical_protocol_sha256"] != sha(REFERENCE)
            or protocol["sources"] != source_lock()
            or protocol["environment"] != old.inherited.environment()
            or protocol["tasks_sha256"] != sha(out / "tasks.json")
            or read(out / "tasks.json") != task_matrix()):
        raise ValueError("Protocol, source, runtime or tasks changed after freezing")
    old.inherited.verify_files(protocol["references"]["files"])
    old.inherited.verify_git_blobs(protocol["references"]["git_blobs"])
    return protocol


def validate(out):
    p = verify(out)
    root = out / "validation"
    if root.exists():
        raise FileExistsError("Validation already attempted; retain all evidence and use new local_rN")
    root.mkdir()
    results=[]
    for label, tests in (("toy", ["tests/test_physical_lazy_prefix.py",
                                   "tests/test_physical_progress_prefix.py",
                                   "tests/test_lazy_robustness_p1.py"]),
                         ("full", [])):
        xml=root/f"{label}.xml"
        cmd=[sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
        if envpath := os.getenv("ASAR_ROBUST_PYTEST_BASE"):
            parent=Path(envpath)
            if not parent.is_dir():
                raise FileNotFoundError(f"Create pytest scratch parent: {parent}")
            dest=parent/label
            if dest.exists():
                raise FileExistsError(f"Use a new scratch directory: {dest}")
            cmd += [f"--basetemp={dest}"]
        cmd += [f"--junitxml={xml}", *tests]
        with (root/f"{label}.stdout.log").open("xb") as so, (root/f"{label}.stderr.log").open("xb") as se:
            completed=subprocess.run(cmd, cwd=ROOT, env=old.inherited.child_environment(),
                                     stdout=so, stderr=se, check=False)
        suite=ET.parse(xml).getroot().findall(".//testcase") if xml.exists() else []
        failures=sum(any(x.find(tag) is not None for tag in ("failure","error","skipped")) for x in suite)
        item=dict(name=label, returncode=completed.returncode, tests=len(suite),
                  failures_or_skips=failures, junit_sha256=sha(xml) if suite else None)
        results.append(item)
        write(root/"validation.json", dict(status="passed" if label=="full" and
            all(x["returncode"]==0 and x["tests"]>0 and x["failures_or_skips"]==0 for x in results)
            else "in_progress" if completed.returncode==0 and not failures else "blocked",
            protocol_sha256=sha(out/"protocol.json"), results=results), overwrite=label=="full")
        if completed.returncode or not suite or failures:
            raise RuntimeError(f"Test failure: {label}. Keep evidence and do not run P1.")
    verify(out)
    print("Tests passed and bound to frozen protocol.", flush=True)


def check_validation(out):
    result=read(out/"validation/validation.json")
    if (result["status"]!="passed" or result["protocol_sha256"]!=sha(out/"protocol.json")
            or [x["name"] for x in result["results"]] != ["toy","full"]
            or any(x["returncode"] or x["failures_or_skips"] or x["tests"]<=0
                or x["junit_sha256"] != sha(out/"validation"/f"{x['name']}.xml")
                for x in result["results"])):
        raise ValueError("No passing frozen toy+full validation")


def check_result(task, result, protocol):
    if result["method"] != task["method"] or not 0 < result["algorithm_wall_s"] <= 30:
        raise ValueError("Incorrect method or exceeded algorithm budget")
    score=result["physical_replay"]
    inner=result["raw"]["phases"][0]["inner"]
    expected="physical_lazy_prefix_v1" if task["method"]=="C0_LAZY" else "physical_refinement_diagnostic_v1"
    if inner["algorithm"]!=expected or inner["error"] or inner["stop_reason"] not in (
        "max_seconds","frontier_exhausted","max_open","max_archive","max_archive_history"
    ):
        raise ValueError("Invalid solver identity/stop")
    if abs(score["J"]-inner["J"])>1e-8 or abs(score["pd_final"]-inner["pd_final"])>1e-8:
        raise ValueError("Inner solver and physical replay disagree")
    if task["method"]=="C0_LAZY" and inner["diagnostics"].get("lazy_frontier") is None:
        raise ValueError("Missing lazy migration record")
    if task["method"]!="C0_LAZY" and inner["diagnostics"].get("lazy_frontier") is not None:
        raise ValueError("C0 control contaminated by lazy mechanism")
    from asar_repro.physical_search import independent_replay
    # Worker performs independent original-model replay. An outer result also
    # supplies the full score plus execution audit for post-run verification.
    if not result["execution_audit"]:
        raise ValueError("Missing actual route execution audit")


def worker(out, run_id):
    protocol=verify(out)
    tasks=read(out/"tasks.json")
    task=read(out/"runs"/run_id/"task.json")
    if task_id(task)!=run_id or task not in tasks:
        raise ValueError("Unregistered task or altered run id")
    from asar_repro import physical_rolling as rolling
    from asar_repro.h2_inputs import load_h2_input
    from asar_repro.physical_lazy_prefix import solve_physical_lazy_prefix
    from asar_repro.physical_search import independent_replay

    old.legacy.assert_local_project_modules()
    reference=protocol["references"]
    case, seed=(reference[k][task["instance"]] for k in ("instances","references"))
    initial=time.perf_counter()
    problem, _, _, info=load_h2_input(ROOT, case,
        ROOT/protocol["config"]["source_root"]/"inputs"/case["id"], "heading_square")
    load_s=time.perf_counter()-initial
    if (info["manifest_sha256"] != reference["archive_hashes"][task["instance"]]["manifest_sha256"]
            or info["particle_sha256"] != reference["archive_hashes"][task["instance"]]["particle_sha256"]
            or info["opendrift_runs_in_search"] != 0):
        raise ValueError("Frozen H2 particle identity mismatch")
    solver=solve_physical_lazy_prefix if task["method"]=="C0_LAZY" else None
    with (nullcontext() if solver is None else patch.object(rolling,"solve_physical_refinement",solver)):
        start, cpu=time.perf_counter(),time.process_time()
        raw=rolling.run_physical_rolling(problem,method="C0",
            initial_waypoints=seed["waypoints"],total_seconds=30.0,
            triggers=protocol["config"]["search"]["triggers"],
            anchor_guard_s=protocol["config"]["search"]["anchor_guard_s"],
            solver_reserve_s=protocol["config"]["search"]["solver_reserve_s"],
            solver_options=protocol["config"]["solver"])
        algorithm_wall_s=time.perf_counter()-start
        algorithm_cpu_s=time.process_time()-cpu
    if raw.get("error") or raw["status"]!="completed":
        write(out/"runs"/run_id/"raw_failure.json",dict(error=raw.get("error"),status=raw["status"]))
        raise ValueError("Solver failed")
    before=time.perf_counter()
    original=problem.replay(raw["waypoints"],connectivity=8)
    independent=independent_replay(problem,raw["waypoints"],connectivity=8)
    if (abs(original["J"]-independent["J"])>1e-8
            or abs(original["pd_final"]-independent["pd_final"])>1e-8
            or len(original["survival"])!=len(independent["survival"])
            or any(abs(a-b)>1e-8 for a,b in zip(original["survival"],independent["survival"]))):
        raise AssertionError("Independent physical replay mismatch")
    result=dict(status="valid",method=task["method"],J=original["J"],
        pd_final=original["pd_final"],physical_replay=original,raw=raw,
        execution_audit=old.legacy.audit_execution(problem,raw,seed,1e-8),
        inputs=info, algorithm_wall_s=algorithm_wall_s,
        algorithm_cpu_s=algorithm_cpu_s,input_load_s=load_s,
        independent_audit_s=time.perf_counter()-before,
        reference_sha256=old.object_digest(seed),formal_optimality_certificate=False)
    check_result(task,result,protocol)
    write(out/"runs"/run_id/"result.json",dict(task=task,result=result))


def verify_saved_task(out, task, folder):
    record=read(folder/"record.json")
    payload=read(folder/"result.json")
    if (record["status"]!="completed" or record["task"]!=task
            or record["returncode"]!=0 or record["watchdog"] is not None
            or payload["task"]!=task or record["result_sha256"]!=sha(folder/"result.json")):
        raise ValueError("Saved task is not valid")
    check_result(task,payload["result"],verify(out))
    return record,payload["result"]


def run(out):
    import psutil
    p=verify(out)
    check_validation(out)
    tasks=read(out/"tasks.json")
    watch=p["config"]["watchdog"]
    for index,task in enumerate(tasks,1):
        tid=task_id(task)
        folder=out/"runs"/tid
        if folder.exists():
            verify_saved_task(out,task,folder)
            print(f"{index}/{len(tasks)} reused verified: {tid}",flush=True)
            continue
        folder.mkdir(parents=True)
        write(folder/"task.json",task)
        cmd=[sys.executable,str(Path(__file__).resolve()),"_worker","--out",str(out),tid]
        start=time.perf_counter()
        peak,termination=0,None
        flags=subprocess.CREATE_NO_WINDOW if sys.platform=="win32" else 0
        with (folder/"stdout.log").open("xb") as so, (folder/"stderr.log").open("xb") as se:
            with subprocess.Popen(cmd,cwd=ROOT,stdout=so,stderr=se,
                                  env=old.inherited.child_environment(),creationflags=flags) as child:
                try:
                    proc=psutil.Process(child.pid)
                    while child.poll() is None:
                        try: peak=max(peak,proc.memory_info().rss)
                        except psutil.NoSuchProcess: break
                        if peak>watch["rss_limit_bytes"]:
                            termination="rss_limit"; break
                        if time.perf_counter()-start>30+watch["grace_seconds"]:
                            termination="process_watchdog"; break
                        time.sleep(watch["poll_seconds"])
                except BaseException:
                    child.kill()
                    raise
                finally:
                    if termination is not None and child.poll() is None:
                        child.kill()
                rc=child.wait()
        resultpath=folder/"result.json"
        error=None
        if rc or termination or not resultpath.exists():
            error="Worker did not finish"
        else:
            try:
                result=read(resultpath)
                if result["task"]!=task or peak<=0:
                    raise ValueError("Task or RSS missing")
                check_result(task,result["result"],p)
            except (ValueError,KeyError,TypeError) as exc: error=str(exc)
        write(folder/"record.json",dict(
            task=task,command=cmd,status="failed" if error else "completed",
            returncode=rc,watchdog=termination,verification_error=error,
            peak_rss_bytes=peak,process_wall_s=time.perf_counter()-start,
            result_sha256=sha(resultpath) if resultpath.exists() else None,
            frozen_evidence=dict(protocol_sha256=sha(out/"protocol.json"),
                validation_sha256=sha(out/"validation/validation.json"))))
        if error:
            raise RuntimeError(f"Failure preserved at {folder}: {error}")
        print(f"{index}/{len(tasks)} {task['instance']} {task['method']} {tid}",flush=True)
    verify(out)


def nearest_rank(values, fraction):
    values=sorted(values)
    return values[max(0,math.ceil(fraction*len(values))-1)]


def analyze(out):
    verify(out); check_validation(out)
    tasks=read(out/"tasks.json")
    rows=[]
    for task in tasks:
        tid=task_id(task)
        record,result=verify_saved_task(out,task,out/"runs"/tid)
        score=result["physical_replay"]; inner=result["raw"]["phases"][0]["inner"]
        history=[v for v in inner["history"] if v["source"]=="search"]
        rows.append(dict(
            instance=task["instance"],method=task["method"],repetition=task["repetition"],
            block=task["block"],run_id=tid,J=float(score["J"]),Pd=float(score["pd_final"]),
            wall_s=float(result["algorithm_wall_s"]),
            rss_mib=record["peak_rss_bytes"]/1048576,
            search_hit=score["J"] <= DESIGN["target"][task["instance"]]+1e-8,
            first_search_improvement_s=history[0]["elapsed_s"] if history else None,
            last_improvement_s=inner["best_elapsed_s"],
            terminal_candidates=inner["stats"]["terminal_candidates"],
            expanded=inner["expanded"],stop_reason=inner["stop_reason"],
            lazy_migrations=(inner["diagnostics"].get("lazy_frontier") or {}).get("migrations",0),
        ))
    if len(rows)!=48: raise ValueError("Incomplete 48-run study")
    by={}
    for instance in DESIGN["cases"]:
        by[instance]={}
        for arm in DESIGN["arms"][instance]:
            sample=[r for r in rows if r["instance"]==instance and r["method"]==arm]
            by[instance][arm]=dict(
                runs=len(sample),median_J=median(v["J"] for v in sample),
                p90_J=nearest_rank([v["J"] for v in sample],.9),
                worst_J=max(v["J"] for v in sample),
                hit_count=sum(v["search_hit"] for v in sample),
                hit_rate=sum(v["search_hit"] for v in sample)/len(sample),
                median_Pd=median(v["Pd"] for v in sample),
                median_rss_mib=median(v["rss_mib"] for v in sample),
                median_wall_s=median(v["wall_s"] for v in sample),
                missed_search_improvement=sum(v["first_search_improvement_s"] is None for v in sample),
                stopped=dict(Counter(v["stop_reason"] for v in sample)),
            )
    a=by["hudson_h2_d1_s4101"]
    control=[r for r in rows if r["instance"]=="hudson_h2_d1_s4101" and r["method"] in ("C0_A","C0_B")]
    lazy=[r for r in rows if r["instance"]=="hudson_h2_d1_s4101" and r["method"]=="C0_LAZY"]
    bad=lambda r:r["J"]>=DESIGN["baseline_initial_j"]["hudson_h2_d1_s4101"]-1e-8
    pooled_bad=sum(map(bad,control))/len(control)
    lazy_bad=sum(map(bad,lazy))/len(lazy)
    c=by["hudson_h2_d2_s4201"]
    safe=(a["C0_LAZY"]["median_J"]<=median(v["J"] for v in control)+1e-8
          and a["C0_LAZY"]["p90_J"]<=nearest_rank([v["J"] for v in control],.9)+1e-8
          and lazy_bad<=pooled_bad+1/12)
    retained=(c["C0_LAZY"]["hit_count"]>=5
              and c["C0_LAZY"]["median_Pd"]>=.090948-1e-8)
    decision=dict(status=("timing_screen_passed" if safe and retained else "timing_screen_not_passed"),
                  4101_noninferiority=safe,4201_retain=retained,
                  4101_control_pooled_bad_rate=pooled_bad,4101_lazy_bad_rate=lazy_bad,
                  note="engineering robustness screen, not significance or generalization proof")
    summary=dict(status=decision["status"],valid_runs=len(rows),expected_runs=48,
                 by_instance_method=by,decision=decision,
                 data_role="seen_development_timing_diagnostic",
                 input_provenance="frozen H2 particle cases",global_optimality_certified=False)
    write(out/"summary.json",summary,overwrite=True)
    with (out/"comparison.csv").open("w",encoding="utf-8",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)
    lines=["# P1：同机计时稳健性验证","",f"**{decision['status']}**，全部 {len(rows)} 次有效。",
           "本轮仅用于开发实例的时间扰动诊断，不能声称新 forcing 泛化。","",
           "| 实例 | 方法 | 次数 | J 中位 | J p90 | J 最差 | 目标命中数 | Pd 中位 | 峰值 RSS 中位 MiB |",
           "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for ins,d in by.items():
        for method,v in d.items():
            lines.append(f"| {ins} | {method} | {v['runs']} | {v['median_J']:.9f} | "
                         f"{v['p90_J']:.9f} | {v['worst_J']:.9f} | {v['hit_count']}/{v['runs']} | "
                         f"{100*v['median_Pd']:.4f}% | {v['median_rss_mib']:.1f} |")
    lines += ["","## 预注册门槛",
              "",f"4101 计时稳健性：{safe}；4201 目标保持：{retained}。",
              f"4101 同算法双对照的无改进率：{pooled_bad:.3f}；Lazy 无改进率：{lazy_bad:.3f}。",
              "不得把不同重复作为独立风流样本，不得事后删除失败运行或调阈值。",""]
    (out/"REPORT.md").write_text("\n".join(lines),encoding="utf-8",newline="\n")
    print(decision["status"],flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("plan","prepare","validate","run","analyze","_worker"))
    parser.add_argument("--out",type=Path,default=DEFAULT_OUT)
    parser.add_argument("run_id",nargs="?")
    args=parser.parse_intermixed_args()
    if args.action=="plan":
        print(json.dumps(plan(),ensure_ascii=False,indent=2));return
    out=args.out.resolve()
    if out.parent!=BATCH.resolve() or not out.name.startswith("local_r"):
        parser.error("Use a fresh local_rN under second_innovation_p1_20261128")
    if args.action=="_worker": worker(out,args.run_id)
    elif args.action=="prepare": prepare(out)
    elif args.action=="validate": validate(out)
    elif args.action=="run": run(out)
    else: analyze(out)


if __name__=="__main__":
    main()
