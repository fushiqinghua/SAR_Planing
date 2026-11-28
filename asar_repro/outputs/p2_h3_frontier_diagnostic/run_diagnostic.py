"""Offline H3 frontier controls and separate extended-budget witness search."""
import argparse
from collections import defaultdict
from contextlib import nullcontext
import csv
import os
from pathlib import Path
import random
from statistics import median
import subprocess
import sys
from time import perf_counter, perf_counter_ns, sleep
import traceback
from unittest.mock import patch
import xml.etree.ElementTree as ET

import psutil
import run_eight_neighbor_h3 as h3
import run_eight_neighbor_rolling as legacy
from h3_protocol import digest, read, save
from prepare_eight_neighbor_h3 import load_h3_input
from asar_repro import physical_rolling as rolling

from frontier_probe import MODES, POLICY_SECONDS, extended_lazy, solve_probe


HERE = Path(__file__).resolve().parent
SOURCE = h3.DEFAULT_OUT
OUT = HERE / "results/local_r1"
CAPS = {3401: 32768, 4401: 32768, 4402: 32768, 4501: 32768, 4601: 6144}
CHECKPOINT = 1024
REPS = 3
SEED = 2026112901
WATCHDOG_RSS = 2**31


def source_locks():
    return {name: digest(SOURCE/name) for name in
            ("protocol.json", "s30_lock.json", "method_lock.json", "date_lock.json", "inputs_lock.json", "tasks.json")}


def implementation():
    return {name: digest(HERE/name) for name in ("frontier_probe.py", "run_diagnostic.py", "test_frontier_probe.py")}


def test_gate():
    directory = OUT/"validation"
    if (directory/"toy.exit.txt").read_text(encoding="utf-8-sig").strip() != "0":
        raise ValueError("The toy/Oracle gate failed")
    tree = ET.parse(directory/"toy.xml")
    cases = tree.findall(".//testcase")
    if not cases or any(case.find(tag) is not None for case in cases for tag in ("failure","error","skipped")):
        raise ValueError("The toy/Oracle test evidence is incomplete")
    return dict(count=len(cases), files={p.name:digest(p) for p in directory.glob("toy.*")})


def freeze():
    gate = test_gate()
    original, tasks = h3.verify_protocol(SOURCE, full=True)
    s30 = h3.freeze_s30(SOURCE, original, tasks["S30"])["references"]
    summary = read(SOURCE/"reports/20261128T152733015237Z/summary.json")
    references = {}
    for seed in CAPS:
        case, = (v for v in original["cases"].values() if v["case"]["seed"] == seed)
        reference = s30[case["case"]["id"]]
        historic, = (row for row in summary["seed_comparisons"] if row["seed"] == seed)
        c0 = [h3.saved_task(SOURCE,t,original)["result"]["J"] for t in tasks["E30"]
              if t["seed"]==seed and t["method"]=="C0"]
        assert len(c0)==3 and median(c0)==historic["C0"]["J"]
        references[str(seed)] = dict(case=case, S30=reference, E30=historic, best_C0_J=min(c0))
    rng = random.Random(SEED)
    fixed = []
    for rep in range(REPS):
        seeds = list(CAPS)
        rng.shuffle(seeds)
        for seed in seeds:
            modes=list(MODES)
            rng.shuffle(modes)
            fixed.extend(dict(stage="fixed", seed=seed, rep=rep, mode=mode, seconds=120,
                              limit=CAPS[seed], checkpoint=CHECKPOINT) for mode in modes)
    extended = []
    for seed in [4401,4402,4501,4601]:
        arms=["C0_extend","Lazy_extend"]
        rng.shuffle(arms)
        extended.extend(dict(stage="extended", seed=seed, rep=0, mode=mode, seconds=120) for mode in arms)
    doc=dict(status="frozen_before_diagnostics", source_sha256=source_locks(), implementation_sha256=implementation(),
             tests=gate, order_seed=SEED, reference=references, fixed=fixed, extended=extended,
             solver=original["config"]["solver"], search=original["config"]["search"],
             policy_seconds=POLICY_SECONDS, environment=original["environment"], watchdog_rss=WATCHDOG_RSS,
             experimental_scope="same native OPEN after 1024 expansions; forced structural split, original quota gate")
    if (OUT/"protocol.json").exists():
        if read(OUT/"protocol.json") != doc:
            raise ValueError("Diagnostic configuration differs from the frozen plan")
    else:
        save(OUT/"protocol.json",doc)
    print(f"Frozen {len(fixed)} matched-work trials and {len(extended)} extended trials",flush=True)


def ident(task):
    return f"{task['stage']}_{task['seed']}_r{task['rep']}_{task['mode']}"


def lock():
    protocol=read(OUT/"protocol.json")
    if (protocol["source_sha256"] != source_locks() or protocol["implementation_sha256"] != implementation()
            or protocol["environment"] != legacy.environment() or protocol["tests"] != test_gate()):
        raise ValueError("Frozen inputs, implementation, tests or runtime changed")
    return protocol


def worker(task_id):
    p=lock()
    task,=(t for t in p["fixed"]+p["extended"] if ident(t)==task_id)
    folder=OUT/"runs"/task_id
    ref=p["reference"][str(task["seed"])]
    info=ref["case"]
    problem,_,_,inputs=load_h3_input(SOURCE,info["case"],info["h3_evidence"],"heading_square")
    if inputs["particle_sha256"] != ref["S30"]["particle_sha256"] or problem.q != .78 or problem.speed_m_s != 20:
        raise ValueError("Archive or frozen problem differs")
    original=ref["S30"]
    kwargs=dict(initial_waypoints=original["waypoints"])
    started=perf_counter()
    start_ns=perf_counter_ns()
    if task["stage"]=="fixed":
        inner,probe=solve_probe(problem,mode=task["mode"],checkpoint=task["checkpoint"],connectivity=8,
                                max_expansions=task["limit"],max_seconds=task["seconds"],
                                **kwargs,**p["solver"])
        outer=None
    else:
        solver=patch.object(rolling,"solve_physical_refinement",extended_lazy) if task["mode"]=="Lazy_extend" else nullcontext()
        with solver:
            outer=rolling.run_physical_rolling(problem,method="C0",total_seconds=task["seconds"],
                                              solver_options=p["solver"],**kwargs,**p["search"])
        probe=None
        inner=outer["phases"][0]["inner"]
    end_ns=perf_counter_ns()
    wall=perf_counter()-started
    if not inner or inner["error"] or (outer is not None and outer["error"]):
        save(folder/"failed_solver.json",legacy.failure_safe(dict(outer=outer,inner=inner,probe=probe)))
        raise ValueError("Solver failed. Raw evidence was retained")
    initial=inner["initial_score"]
    if initial["waypoints"] != original["waypoints"] or abs(initial["J"]-original["J"])>1e-8:
        raise ValueError("Changed initial route or original score")
    selected=inner if outer is None else outer
    replay,scalar=h3.dual_replay(problem,selected["waypoints"],8)
    if abs(replay["J"]-selected["J"])>1e-8 or abs(replay["pd_final"]-selected["pd_final"])>1e-8:
        raise ValueError("Diagnostic route disagrees with the original scorer")
    run=dict(task=task, inner=inner, outer=outer, probe=probe, inputs=inputs, replay=replay,
             independent_replay=scalar, algorithm_wall_s=wall,start_ns=start_ns,end_ns=end_ns,
             exact_work=task["stage"]=="fixed" and inner["expanded"]==task["limit"] and inner["stop_reason"]=="max_expansions",
             execution_audit=None if outer is None else legacy.audit_execution(problem,outer,original,1e-8))
    save(folder/"result.json",legacy.failure_safe(run))


def launch(task):
    folder=OUT/"runs"/ident(task)
    if folder.exists():
        existing=read(folder/"record.json")
        if existing["task"] == task and existing["status"]=="valid" and existing["result_sha256"]==digest(folder/"result.json"):
            return existing
        raise ValueError(f"An unverified trial already occupies {folder}")
    folder.mkdir(parents=True)
    save(folder/"task.json",task)
    cmd=[sys.executable,str(Path(__file__).resolve()),"_worker",ident(task)]
    elapsed=perf_counter()
    samples=[]
    watchdog=None
    with (folder/"stdout.log").open("xb") as stdout, (folder/"stderr.log").open("xb") as stderr:
        flags=subprocess.CREATE_NO_WINDOW if sys.platform=="win32" else 0
        with subprocess.Popen(cmd,cwd=legacy.ROOT,env=h3.worker_env(),stdout=stdout,stderr=stderr,
                              creationflags=flags) as child:
            proc=psutil.Process(child.pid)
            try:
                while child.poll() is None:
                    try:
                        samples.append((perf_counter_ns(),proc.memory_info().rss))
                    except psutil.NoSuchProcess:
                        break
                    if samples[-1][1]>WATCHDOG_RSS:
                        watchdog="rss"
                        break
                    if perf_counter()-elapsed>task["seconds"]+60:
                        watchdog="wall"
                        break
                    sleep(.05)
            finally:
                if child.poll() is None:
                    child.kill()
                rc=child.wait()
    target=folder/"result.json"
    valid=rc==0 and target.exists() and not watchdog
    with (folder/"rss.csv").open("x",encoding="utf-8",newline="") as file:
        writer=csv.writer(file)
        writer.writerow(("monotonic_ns","rss_bytes"))
        writer.writerows(samples)
    value=dict(status="valid" if valid else "failed", task=task, command=cmd, watchdog=watchdog, returncode=rc,
               process_peak_rss_bytes=max((rss for _,rss in samples),default=0),
               result_sha256=digest(target) if target.is_file() else None,
               files={file.name:digest(file) for file in folder.iterdir() if file.is_file()})
    save(folder/"record.json",value)
    if not valid:
        raise RuntimeError(f"Diagnostic worker failed; evidence retained at {folder}")
    return value


def load_results(p,stage):
    rows=[]
    for task in p[stage]:
        folder=OUT/"runs"/ident(task)
        record=read(folder/"record.json")
        if record["status"]!="valid" or any(digest(folder/n)!=sha for n,sha in record["files"].items()):
            raise ValueError(f"Failed or changed run: {folder}")
        result=read(folder/"result.json")
        if result["task"]!=task:
            raise ValueError("Task evidence mismatch")
        rows.append((record,result,folder))
    return rows


def check_fixed(rows):
    by_seed=defaultdict(list)
    for record,result,folder in rows:
        by_seed[result["task"]["seed"]].append(result)
        if not result["probe"]["handoff"]:
            raise ValueError(f"Missing common prefix: {folder}")
    for seed,group in by_seed.items():
        def checkpoint(r):
            a=r["probe"]["handoff"]
            return a["open_sha256"],a["prior_pops_sha256"],a["open_count"],a["expanded"]
        if len({checkpoint(r) for r in group})!=1:
            raise ValueError(f"The three continuations did not share a prefix for {seed}")
        controls=[r for r in group if r["task"]["mode"]!="three_quota" and r["exact_work"]]
        if len({(r["probe"]["pop_sha256"],r["replay"]["J"],r["replay"]["pd_final"],
                 r["inner"]["peak_open"],r["inner"]["generated"]) for r in controls})>1:
            raise ValueError(f"Global order changed after partition on {seed}")


def run_stage(stage):
    p=lock()
    if stage=="extended":
        check_fixed(load_results(p,"fixed"))
    for index,task in enumerate(p[stage],1):
        launch(task)
        print(f"{stage} {index}/{len(p[stage])} {ident(task)}",flush=True)
    if stage=="fixed":
        check_fixed(load_results(p,"fixed"))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("command",choices=("freeze","fixed","extended","_worker"))
    p.add_argument("task",nargs="?")
    a=p.parse_args()
    if a.command=="freeze":
        freeze()
    elif a.command=="_worker":
        try:
            worker(a.task)
        except Exception:
            print(traceback.format_exc(),file=sys.stderr)
            raise SystemExit(1)
    else:
        run_stage(a.command)


if __name__=="__main__":
    main()
