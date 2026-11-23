"""B7 release gates: verify, replay, report and archive; never change a planner."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from time import perf_counter
import zipfile

import numpy as np

from benchmark_b5 import ROOT, read_json, save_json, load_input
from asar_repro.scenarios import digest

V1 = "abd1b472798fbf3d318e83d09caf9b69cc459122"
MANDATORY = ("frozen_integrity", "full_pytest", "dynamic_counterexample", "real_forcing",
             "constant_regression", "real_particle_reintegration", "all_path_replay",
             "performance_evidence", "b6_offline_rerun", "old_outputs_unchanged", "offline_archive")


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def release_status(gates):
    return "passed" if all(gates.get(name, {}).get("status") == "passed" for name in MANDATORY) else "blocked"


def compare_npz(first, second):
    with np.load(first, allow_pickle=False) as a, np.load(second, allow_pickle=False) as b:
        require(set(a.files) == set(b.files), "NPZ variables differ")
        for k in a.files:
            np.testing.assert_equal(a[k], b[k], err_msg=k)
        return dict(arrays=len(a.files), exact_equal=True)


def run_command(output, name, args, timeout=300):
    started = perf_counter()
    command = [sys.executable, *args]
    try:
        p = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
        code, stdout, stderr = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as error:
        code, stdout, stderr = 124, "", "Explicit verification timeout: " + str(error)
    log = dict(command=command, exit_code=code, wall_s=perf_counter()-started,
               stdout=stdout, stderr=stderr)
    save_json(output/(name+"_command.json"), log)
    (output/(name+".txt")).write_text(stdout+stderr, encoding="utf-8")
    require(code == 0, f"{name} exited {code}; see {name}.txt")
    return log


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def integrity(output):
    """Compare frozen bytes with Git objects AND the untouched v1 worktree if present."""
    frozen = read_json(ROOT/"outputs/baseline_v1.1/b0/v1.0_sha256.json")
    require(git("rev-parse", "asar-repro-v1.0").decode().strip() == V1, "v1.0 tag changed")
    old_worktree = ROOT.parent.parent/"SAR_Planing-upload"
    old_exists = old_worktree.exists()
    if old_exists:
        head = subprocess.check_output(["git", "-C", str(old_worktree), "rev-parse", "HEAD"], text=True).strip()
        require(head == V1, "original worktree HEAD differs")
    changes = []
    for name, expected in frozen.items():
        actual = hashlib.sha256(git("show", f"{V1}:{name}")).hexdigest()
        require(actual == expected, f"v1 Git blob changed: {name}")
        if old_exists:
            require(digest(old_worktree/name) == expected, f"original v1 worktree changed: {name}")
        if digest(ROOT.parent/name) != expected:
            changes.append(name)
    require(changes == ["asar_repro/src/asar_repro/planner_adapter.py"], "unexpected v1-to-v1.1 changes")
    # Check every current tracked file against the committed B6/B7 evidence, not just supplied manifests.
    tracked = git("ls-files", "-z").decode().split("\0")
    files = [ROOT/p for p in tracked if p]
    for p in files:
        rel = "asar_repro/"+p.relative_to(ROOT).as_posix()
        expected = hashlib.sha256(git("show", "HEAD:"+rel)).hexdigest()
        require(digest(p) == expected, "tracked baseline file differs from HEAD: "+rel)
    meta = read_json(ROOT/"outputs/baseline_v1.1/lake_ontario_real/metadata.json")
    raw = []
    for role, entries in meta["provenance"]["input_fingerprints"]["sources"].items():
        for entry in entries:
            p = ROOT/entry["local_path"]
            require(digest(p) == entry["sha256"], "raw forcing fingerprint mismatch")
            raw.append(dict(role=role, path=entry["local_path"], sha256=entry["sha256"],
                            bytes=p.stat().st_size, valid_utc=entry["valid_utc"], source_url=entry["source_url"]))
            files.append(p)
    # All cached raw files are included, including B1 decode/reference evidence required offline.
    files.extend(p for p in (ROOT/"data/raw").rglob("*") if p.is_file())
    inventory = {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(set(files))}
    save_json(output/"frozen_inventory.json", inventory)
    save_json(output/"real_forcing_files.json", raw)
    result = dict(v1_commit=V1, v1_files=len(frozen), git_blobs_verified=True,
                  original_worktree_present=old_exists, original_worktree_verified=old_exists,
                  intentional_v1_1_changes=changes, frozen_file_count=len(inventory), real_files=len(raw))
    save_json(output/"v1_preservation.json", result)
    return result


def dynamic_witness():
    from asar_repro.grid import GridGraph
    from asar_repro.motion import MatrixMotion
    from asar_repro.oracle import enumerate_oracle
    from asar_repro.heuristic import Heuristic
    from asar_repro.search import search_asar
    with np.load(ROOT/"data/fixtures/heuristic_dynamic_counterexample.npz", allow_pickle=False) as a:
        args=dict(start=4,budget=4,p=a["p"],q=.78,motion=MatrixMotion.time_varying(a["P"]))
    graph=GridGraph(3,3)
    exact=enumerate_oracle(graph,**args)
    h=Heuristic(graph,budget=4,q=.78,motion=args["motion"],mode="paper_greedy")(4,0,args["p"])
    result=search_asar(graph,**args,heuristic="paper_greedy",epsilon=1.)
    np.testing.assert_allclose([h,exact.J],[2.6170801771,2.5417333379],atol=1e-10,rtol=0)
    require(h>exact.J and not result.theory_certified,"counterexample or uncertified label lost")
    return dict(h=h,oracle_J=exact.J,overestimate=h-exact.J,paper_certified=result.theory_certified)


def all_path_replay():
    from stage8_metrics import collect
    from asar_repro.objective import score_path
    from asar_repro.motion import MatrixMotion
    from asar_repro.grid import GridGraph
    from asar_repro.search import SearchResult
    from asar_repro.search_reporting import classify_result
    old_rows, missions, _ = collect(ROOT)  # old Stage 1-7 evidence and all 72 marine paths
    spec=read_json(ROOT/"configs/b6_comparison.json")
    graph,args,_=load_input(spec)
    errors=[]
    counts={}
    paths=["b5/scan_runs.json", "b5/pilot_runs.json", "lake_ontario_real/runs.json"]
    # The first failed B6 orchestration attempt has an actual successful worker result; audit it too.
    failed=ROOT/"outputs/baseline_v1.1/b6_failed_attempt_01/b6_workers"
    datasets=[(p,read_json(ROOT/"outputs/baseline_v1.1"/p)) for p in paths]
    datasets += [(str(p.relative_to(ROOT)),[read_json(p)]) for p in failed.glob("paper*.json")]
    for name, rows in datasets:
        counts[name]=len(rows)
        for row in rows:
            require(row["particle_archive_sha256"]==spec["archive_sha256"],"result archive identity differs")
            require(row["T"]==args["budget"] and row["q"]==args["q"],"result T/q differs")
            score=score_path(graph,row["path"],**args)
            err=max(abs(score.J-row["J"]),abs(score.pd_final-row["Pd_T"]),abs(score.survival[-1]-row["M_T"]))
            require(err<=1e-10,"J/Pd/M replay error")
            if row["algorithm"] != "ParallelTrack":
                result=SearchResult(tuple(row["path"]),row["J"],row["expanded"],row["generated"],row["pruned"],
                                    row["peak_open"],row["heuristic"],row["epsilon"],False,row["search_status"],row["stop_reason"],row["incumbent_source"])
                flags=classify_result(result)
                for k in ("discrete_model_certified","theoretical_bound_applicable","search_completed"):
                    require(flags[k]==row[k],"state/certificate mismatch")
            errors.append(err)
    toy=read_json(ROOT/"outputs/baseline_v1.1/b4/toy_runs.json")
    from audit_search_results import toy_case
    for row in toy:
        if row["path"] is None:
            require(row["J"] is None and row["Pd_T"] is None and not row["discrete_model_certified"],"invalid no-path result")
            continue
        g,p,mat,start,_=toy_case(row["scenario_id"])
        s=score_path(g,row["path"],start=start,budget=4,p=p,q=.78,motion=MatrixMotion.time_varying(mat))
        require(abs(s.J-row["J"])<=1e-10 and abs(s.pd_final-row["Pd_T"])<=1e-10,"toy replay differs")
    return dict(old_normalized_records=len(old_rows), old_marine_paths=sum(len(m["runs"]) for m in missions.values()),
                old_marine_max_error=max(m["replay_error"] for m in missions.values()),
                additional_record_groups=counts,toy_rows=len(toy),max_real_replay_error=max(errors))


def performance():
    summary=read_json(ROOT/"outputs/baseline_v1.1/b5/summary.json")
    runs=read_json(ROOT/"outputs/baseline_v1.1/b5/scan_runs.json")
    require(summary["status"]=="passed" and len(runs)==38,"B5 performance evidence missing")
    require(all(r.get("peak_process_MiB") is not None for r in runs),"memory missing")
    require(len({(r["heuristic"],r["epsilon"],r["max_expansions"],r["max_seconds"]) for r in runs if r["max_open"]==20000})==36,"budget matrix missing")
    return {k:summary[k] for k in ("main_scan_runs","stop_distribution","probe_stops","peak_process_MiB_range","certified_runs")}


def unchanged(output):
    inventory=read_json(output/"frozen_inventory.json")
    for path,sha in inventory.items():
        require(digest(ROOT/path)==sha,"old evidence changed: "+path)
    return dict(files=len(inventory),all_unchanged=True)


def make_archive(output):
    """Zip the runnable payload and its base Git history; stream-verify every member."""
    bundle=output/"baseline_history.bundle"
    subprocess.run(["git","bundle","create",str(bundle),"--all"],cwd=ROOT,check=True,capture_output=True)
    subprocess.run(["git","bundle","verify",str(bundle)],cwd=ROOT,check=True,capture_output=True)
    archive=output/"baseline_v1_1_offline.zip"
    files=set()
    for name in ("src","scripts","tests","configs","docs","data","outputs"):
        for p in (ROOT/name).rglob("*"):
            if p.is_file() and p.suffix not in (".zip", ".bundle") and not p.is_relative_to(output) and not any(x in p.parts for x in ("__pycache__",".pytest_cache",".python-user")):
                files.add(p)
    for name in ("pyproject.toml","README.md",".gitignore"):
        if (ROOT/name).is_file():files.add(ROOT/name)
    # B7 logs and reruns are part of the handoff, but not this ZIP or its future checksum.
    files.update(p for p in output.rglob("*") if p.is_file() and p.name not in (archive.name,"validation_summary.json","archive_checksum.json"))
    inventory={"asar_repro/"+p.relative_to(ROOT).as_posix():digest(p) for p in sorted(files)}
    with zipfile.ZipFile(archive,"x",compression=zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as z:
        for p in sorted(files): z.write(p,"asar_repro/"+p.relative_to(ROOT).as_posix())
        z.writestr("payload_sha256.json",json.dumps(inventory,indent=2))
    with zipfile.ZipFile(archive) as z:
        require(set(z.namelist())==set(inventory)|{"payload_sha256.json"},"ZIP membership mismatch")
        for name,sha in inventory.items():
            with z.open(name) as f: actual=hashlib.file_digest(f,"sha256").hexdigest()
            require(actual==sha,"ZIP member mismatch: "+name)
    record=dict(path=str(archive.relative_to(ROOT)),sha256=digest(archive),bytes=archive.stat().st_size,
                verified_entries=len(inventory),git_bundle_sha256=digest(bundle),raw_forcing_included=True,
                reports="final report and validation_summary are sidecars generated after ZIP verification")
    save_json(output/"archive_checksum.json",record)
    return record


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir",type=Path,required=True)
    parser.add_argument("--publish-docs",action="store_true")
    opts=parser.parse_args()
    output=opts.output_dir.resolve()
    require(output.is_relative_to((ROOT/"outputs/baseline_v1.1").resolve()),"B7 output must be a new baseline_v1.1 subdirectory")
    require(not output.exists(),"B7 output exists; select a fresh directory")
    output.mkdir(parents=True)
    gates={}
    def gate(name,fn):
        started=perf_counter()
        try:
            evidence=fn()
            gates[name]=dict(status="passed",wall_s=perf_counter()-started,evidence=evidence)
        except Exception as error:
            gates[name]=dict(status="blocked",wall_s=perf_counter()-started,error=str(error))
        save_json(output/"validation_summary.json",dict(status="blocked",gates=gates,remaining=[n for n in MANDATORY if n not in gates]))
        print(name,gates[name]["status"],flush=True)
    gate("frozen_integrity",lambda:integrity(output))
    # Keep executing independent gates to expose all blockers, never paper over failures.
    def pytest_gate():
        log=run_command(output,"full_pytest",["-m","pytest","-q"],300)
        match=re.search(r"(\d+) passed(?:.*?) in ([\d.]+)s",log["stdout"])
        require(match is not None,"pytest did not record passing test count")
        return dict(passed=int(match[1]),pytest_s=float(match[2]),command=log["command"],exit_code=0)
    gate("full_pytest",pytest_gate)
    gate("dynamic_counterexample",dynamic_witness)
    def forcing_gate():
        run_command(output,"forcing_recheck",["scripts/validate_forcing.py","--output",str(output/"forcing_audit.json")])
        new=read_json(output/"forcing_audit.json"); old=read_json(ROOT/"outputs/baseline_v1.1/b2/forcing_audit.json")
        for key in ("fields","samples","controls","cycle_policy","requested_window_utc"):
            require(new[key]==old[key],"forcing audit changed: "+key)
        return dict(status=new["status"],files=10,exact_fields_samples_controls=True)
    gate("real_forcing",forcing_gate)
    def constant_gate():
        run_command(output,"constant_replay",["scripts/generate_drift.py","--output-dir",str(output/"constant_rerun")])
        return compare_npz(ROOT/"outputs/particles/stage5_leeway.npz",output/"constant_rerun/particles/stage5_leeway.npz")
    gate("constant_regression",constant_gate)
    def real_gate():
        log=run_command(output,"historical_replay",["scripts/generate_historical_drift.py","--verify-replay"])
        result=json.loads(log["stdout"])
        require(result["exact_replay"] is True and result["compared_npz_arrays"]==21,"real integration replay not exact")
        return result
    gate("real_particle_reintegration",real_gate)
    gate("all_path_replay",all_path_replay)
    gate("performance_evidence",performance)
    def b6_gate():
        run_command(output,"b6_rerun",["scripts/compare_b6.py","--output-dir",str(output/"b6_rerun")])
        old=read_json(ROOT/"outputs/baseline_v1.1/lake_ontario_real/runs.json"); new=read_json(output/"b6_rerun/runs.json")
        require(len(old)==len(new)==7,"B6 record count changed")
        for a,b in zip(old,new,strict=True):
            for key in ("path","J","Pd_T","M_T","expanded","generated","pruned","peak_open","search_status","stop_reason","incumbent_source","discrete_model_certified"):
                require(a[key]==b[key],"B6 deterministic replay differs: "+key)
        return dict(runs=7,exact_paths_scores_counters_status=True,timing_remeasured_separately=True)
    gate("b6_offline_rerun",b6_gate)
    gate("old_outputs_unchanged",lambda:unchanged(output))
    from report_baseline_v1_1 import prepare_handoff, final_report
    # Freeze method/version/protocol files before packaging them.
    try:
        prepare_handoff(output,gates)
    except Exception as error:
        gates["handoff"]=dict(status="blocked",error=str(error))
    if all(gates.get(n,{}).get("status")=="passed" for n in MANDATORY[:-1]) and "handoff" not in gates:
        gate("offline_archive",lambda:make_archive(output))
    else:
        gates["offline_archive"]=dict(status="blocked",error="prior mandatory gate failed; no release archive")
    status=release_status(gates)
    if any(g["status"]!="passed" for g in gates.values()):status="blocked"
    summary=dict(stage="B7",status=status,gates=gates,source_commit=git("rev-parse","HEAD").decode().strip())
    save_json(output/"validation_summary.json",summary)
    report=final_report(output,summary)
    (output/"final_validation_report.md").write_text(report,encoding="utf-8")
    if opts.publish_docs:
        target=ROOT/"docs/baseline_v1.1/final_validation_report.md"
        require(not target.exists(),"final report already exists; do not overwrite")
        shutil.copyfile(output/"final_validation_report.md",target)
    print(json.dumps(dict(status=status,output=str(output)),ensure_ascii=False),flush=True)
    return 0 if status=="passed" else 2


if __name__ == "__main__":
    sys.exit(main())
