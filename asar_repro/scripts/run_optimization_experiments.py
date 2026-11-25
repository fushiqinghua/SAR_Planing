"""Frozen, SHA-gated ablations: equal work caps and separate equal time caps."""
import argparse
from collections import Counter
from dataclasses import asdict
import json
import os
from pathlib import Path
from statistics import median
import subprocess
import sys
from time import perf_counter
import traceback

import psutil
import numpy as np

from asar_repro.anytime_search import search_anytime
from asar_repro.objective import score_path
from asar_repro.research_search import search_research
from asar_repro.research_particle import FutureEquivalentMotion
from asar_repro.tail_repair import repair_tail
from asar_repro.search import search_asar
from run_anytime_experiments import csv_save, reference, validation_gate, manifest
from run_optimization_validation import sources, snapshot, preserve, environment, child_environment
from stdc_validation_guards import ROOT, PARTICLE_SHA, PROTOCOL_SHA, load_real, check_score, save, read, digest, require

VARIANTS=("paper_baseline","anytime_reference","fast_zero","fast_mass","fast_stdc",
          "cascade_stdc","lookahead_stdc","tail_zero","tail_stdc","compressed_stdc","portfolio_stdc")
CAPS={"work":dict(max_expansions=5000,max_open=20000,max_seconds=30.),
      "wall":dict(max_expansions=None,max_open=20000,max_seconds=5.)}
WEIGHT=1.04
ATOL=1e-10


def invoke(grid,cfg,initial,variant,limits):
    started=perf_counter();phases=[];compression=None
    if variant=="paper_baseline":
        result=search_asar(grid,**cfg,initial_path=initial,heuristic="paper_greedy",epsilon=WEIGHT,**limits)
    elif variant=="anytime_reference":
        result=search_anytime(grid,**cfg,initial_path=initial,guide_weight=WEIGHT,bound_mode="stdc_lb",**limits)
    elif variant.startswith("tail_"):
        mode="zero" if variant=="tail_zero" else "stdc_lb"
        seed_limits=dict(limits,max_seconds=limits["max_seconds"]*.4)
        if limits["max_expansions"] is not None:seed_limits["max_expansions"]=int(limits["max_expansions"]*.4)
        seed=search_research(grid,**cfg,initial_path=initial,guide_weight=WEIGHT,bound_mode=mode,**seed_limits)
        offset=perf_counter()-started
        remaining=dict(limits,max_seconds=max(0.,limits["max_seconds"]-offset))
        if limits["max_expansions"] is not None:
            remaining["max_expansions"]=max(0,limits["max_expansions"]-seed.stats["work_expanded"])
        result=repair_tail(grid,**cfg,initial_path=seed.path,bound_mode=mode,lengths=(6,10,14),**remaining)
        phases=[dict(name="global_seed",limits=seed_limits,result=asdict(seed)),
                dict(name="free_endpoint_tail",limits=remaining,result=asdict(result))]
        result.incumbent_history=list(seed.incumbent_history)+[
            dict(e,elapsed_s=e["elapsed_s"]+offset,expanded=e["expanded"]+seed.expanded,
                 source="tail_repair") for e in result.incumbent_history[1:]]
        result.expanded+=seed.expanded
        result.generated+=seed.generated
        result.pruned+=seed.pruned
        result.peak_open=max(result.peak_open,seed.peak_open)
        result.stats["work_expanded"]=result.expanded
        result.stats["global_seed_status"]=seed.status
        result.stats["global_seed_stop_reason"]=seed.stop_reason
        result.stats["seed_search_run"]=True
        result.stats["budget_scope"]="global seed plus all tail phases share total work/time/OPEN caps"
        result.stats["detail_scope"]="other counters describe tail phases; full seed stats saved separately"
        result.stats["seed_stats"]=dict(seed.stats)
        result.stats["completion_scope"]="scheduled tail neighborhoods only; global seed may be truncated"
        if result.status=="completed" and seed.status=="budget_exceeded":
            result.status="budget_exceeded";result.stop_reason="global_seed_"+seed.stop_reason
        result.incumbent_source="tail_repair" if len(result.incumbent_history)>len(seed.incumbent_history) else seed.incumbent_source
        result.wall_s=perf_counter()-started
    else:
        kwargs=dict(bound_mode={"fast_zero":"zero","fast_mass":"mass_lb","lookahead_stdc":"lookahead"}.get(variant,"stdc_lb"),
                    portfolio=variant=="portfolio_stdc",cascade=variant=="cascade_stdc")
        search_cfg=cfg
        if variant=="compressed_stdc":
            tic=perf_counter()
            motion=FutureEquivalentMotion(cfg["motion"],cfg["p"])
            compression=dict(motion.compression_stats,preprocessing_s=perf_counter()-tic,
                             groups=[list(map(int,g)) for g in motion.groups],
                             groups_kind="original_column_indices",
                             original_trajectory_ids=cfg["motion"].trajectory_ids.tolist())
            search_cfg=dict(cfg,motion=motion,p=motion.initial_weights)
            kwargs["replay_cfg"]=cfg
        offset=perf_counter()-started
        remaining=dict(limits,max_seconds=max(0.,limits["max_seconds"]-offset))
        result=search_research(grid,**search_cfg,initial_path=initial,guide_weight=WEIGHT,**kwargs,**remaining)
        for event in result.incumbent_history+result.candidate_archive:
            event["elapsed_s"]+=offset
        result.wall_s=perf_counter()-started
    return result,phases,compression,perf_counter()-started


def worker(folder,variant,protocol_name,repeat,evidence_path):
    gate=validation_gate(evidence_path)
    preserve(evidence_path.parent)
    source=sources();pre=perf_counter()
    protocol,grid,cfg,pt,times,raw=load_real()
    refs=reference();preprocessing=perf_counter()-pre
    limits=CAPS[protocol_name]
    result,phases,compression,elapsed=invoke(grid,cfg,tuple(protocol["initial_path"]),variant,limits)
    save(folder/"raw_result.json",dict(result=asdict(result),phases=phases,compression=compression))
    require(result.path is not None and not result.theory_certified,"missing/certified route")
    score=score_path(grid,result.path,**cfg);check_score(score)
    require(abs(score.J-result.J)<=ATOL,"J original replay mismatch")
    if hasattr(result,"Pd"):require(abs(score.pd_final-result.Pd)<=ATOL,"Pd original replay mismatch")
    require(score.J<=pt.J+ATOL,"lost common feasible incumbent")
    require(result.status in ("completed","budget_exceeded"),"unknown status")
    require(bool(result.stop_reason)==(result.status=="budget_exceeded"),"missing stop reason")
    work=getattr(result,"stats",{}).get("work_expanded",result.expanded)
    require(limits["max_expansions"] is None or work<=limits["max_expansions"],"shared work budget exceeded")
    require(result.peak_open<=limits["max_open"],"physical OPEN budget exceeded")
    replays=[];previous=float("inf")
    for event in getattr(result,"incumbent_history",[]):
        r=score_path(grid,event["path"],**cfg);check_score(r)
        require(abs(r.J-event["J"])<=ATOL and abs(r.pd_final-event["Pd"])<=ATOL,"history mismatch")
        require(r.J<previous-ATOL,"nonimproving accepted history")
        require(0<=event["elapsed_s"]<=elapsed+.01,"invalid event clock")
        previous=r.J;replays.append(dict(J=r.J,Pd=r.pd_final,legal=True))
    archive=[]
    for event in getattr(result,"candidate_archive",[]):
        r=score_path(grid,event["path"],**cfg)
        require(abs(r.J-event["J"])<=ATOL and abs(r.pd_final-event["Pd"])<=ATOL,"candidate archive mismatch")
        archive.append(dict(event,legal=True))
    if protocol_name=="work" and variant in ("anytime_reference","fast_stdc"):
        old=read(ROOT/"outputs/stdc_v0_2/anytime_20261124/benchmark/anytime_stdc_w1.04_rep0/raw_result.json")
        for key in ("path","expanded","generated","pruned","peak_open"):
            value=list(result.path) if key=="path" else getattr(result,key)
            require(value==old[key],"equivalent guide/reference changed search: "+key)
        require(abs(result.J-old["J"])<=ATOL,"equivalent search J changed")
    require(sources()==source,"source changed during real worker")
    mem=psutil.Process().memory_info()
    row=dict(asdict(result),variant=variant,protocol=protocol_name,repeat=repeat,guide_weight=WEIGHT,
             Pd_T=score.pd_final,work_expanded=work,search_wall_s=elapsed,preprocessing_s=preprocessing,
             process_peak_memory_mib=getattr(mem,"peak_wset",mem.rss)/2**20,
             replay_error_J=abs(result.J-score.J),legal=True,history_replays=replays,candidate_archive=archive,
             survival=score.survival.tolist(),cumulative_J=score.g.tolist(),
             particle_sha256=PARTICLE_SHA,protocol_sha256=PROTOCOL_SHA,verified_forcing=raw,
             particle_seed=41,experiment_label=protocol["experiment_label"],forcing_kind="historical_real",
             data_scope="single frozen Lake Ontario all-water approximation",limits=limits,
             best_baseline_J=refs["best_J"],best_baseline_Pd=refs["best_J_Pd"],
             delta_J=result.J-refs["best_J"],delta_Pd=score.pd_final-refs["best_J_Pd"],
             cooperative_overshoot_s=max(0.,elapsed-limits["max_seconds"]),
             source_sha256=source,compression=compression,validation_sha256=gate["sha256"],
             guarantee="uncertified",memory_scope="isolated process peak including imports/input checks")
    save(folder/"result.json",row)
    print(json.dumps({k:row[k] for k in ("variant","protocol","J","Pd_T","status","stop_reason","work_expanded","search_wall_s")}),flush=True)


def reports(folder,rows):
    aggregate=[]
    for protocol_name in CAPS:
        for variant in VARIANTS:
            group=[r for r in rows if r["variant"]==variant and r["protocol"]==protocol_name]
            if not group:continue
            a=dict(protocol=protocol_name,variant=variant,runs=len(group),
                   stops=dict(Counter(r["stop_reason"] or "completed" for r in group)),
                   distinct_paths=len({tuple(r["path"]) for r in group}))
            for key in ("J","Pd_T","search_wall_s","work_expanded","expanded","process_peak_memory_mib","delta_J","delta_Pd"):
                vals=[r[key] for r in group]
                a[key+"_median"]=median(vals);a[key+"_min"]=min(vals);a[key+"_max"]=max(vals)
            aggregate.append(a)
    save(folder/"aggregate.json",dict(rows=aggregate));csv_save(folder/"aggregate.csv",aggregate)
    excluded={"path","survival","cumulative_J","history_replays","candidate_archive","incumbent_history","verified_forcing","source_sha256","compression"}
    csv_save(folder/"metrics.csv",[{k:v for k,v in r.items() if k not in excluded} for r in rows])
    pairs=[]
    for row in rows:
        for ref in ("paper_baseline","anytime_reference","fast_zero","fast_stdc"):
            base=next((b for b in rows if b["variant"]==ref and b["protocol"]==row["protocol"] and b["repeat"]==row["repeat"]),None)
            if base and ref!=row["variant"]:
                pairs.append(dict(variant=row["variant"],reference=ref,protocol=row["protocol"],repeat=row["repeat"],
                                  delta_J=row["J"]-base["J"],delta_Pd=row["Pd_T"]-base["Pd_T"],
                                  time_ratio=row["search_wall_s"]/base["search_wall_s"]))
    csv_save(folder/"paired_comparisons.csv",pairs)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    for protocol_name in sorted({r["protocol"] for r in rows}):
        chosen=[r for r in rows if r["protocol"]==protocol_name and r["repeat"]==0]
        fig,ax=plt.subplots(1,2,figsize=(14,6),constrained_layout=True)
        for r in chosen:
            hist=r.get("incumbent_history",[])
            if hist:ax[0].step([e["elapsed_s"] for e in hist]+[r["search_wall_s"]],[e["J"] for e in hist]+[r["J"]],where="post",label=r["variant"])
            else:ax[0].scatter([r["search_wall_s"]],[r["J"]],label=r["variant"])
            ax[1].plot(r["survival"],label=r["variant"])
        ax[0].set(xlabel="Method wall time (s)",ylabel="Incumbent J",title="Time to solution quality")
        ax[1].set(xlabel="Absolute step; t=0 no sensing",ylabel="Undetected mass",title="Original scorer replay")
        for a in ax:a.grid(alpha=.2);a.legend(fontsize=7)
        fig.suptitle(f"Real archive / all-water approximation / uncertified / {protocol_name} caps")
        fig.savefig(folder/f"{protocol_name}_quality_survival.png",dpi=160);plt.close(fig)
        fig,axes=plt.subplots(3,4,figsize=(15,12),constrained_layout=True)
        for a,r in zip(axes.flat,chosen):
            route=np.asarray(r["path"]);a.plot(route%17,route//17,".-",ms=3)
            a.scatter(route[0]%17,route[0]//17,marker="*",s=70)
            a.set(title=f"{r['variant']}\nJ={r['J']:.6f}, Pd={r['Pd_T']:.6f}",xlim=(-.5,16.5),ylim=(16.5,-.5),aspect="equal")
            a.grid(alpha=.2)
        for a in axes.flat[len(chosen):]:a.axis("off")
        fig.suptitle(f"Same frozen real particles; grid paths; {protocol_name}; no certificates")
        fig.savefig(folder/f"{protocol_name}_paths.png",dpi=150);plt.close(fig)
        agg=[a for a in aggregate if a["protocol"]==protocol_name]
        fig,axes=plt.subplots(1,3,figsize=(16,6),constrained_layout=True)
        for a,key,label in zip(axes,("J","search_wall_s","process_peak_memory_mib"),("J lower is better","Wall seconds","Process peak MiB")):
            a.barh(range(len(agg)),[r[key+"_median"] for r in agg]);a.set_yticks(range(len(agg)),[r["variant"] for r in agg],fontsize=8);a.invert_yaxis();a.set_title(label)
        fig.suptitle(f"Medians across repeated timing runs of one archive; {protocol_name}")
        fig.savefig(folder/f"{protocol_name}_efficiency.png",dpi=160);plt.close(fig)
    lines=["# STDC optimization ablations", "", "All routes uncertified; original min-J objective and scorer unchanged.",
           "Same real historical Lake Ontario archive, all-water approximation, seed41. Repeats are not independent scenes.",
           "Work protocol: 5000 total expansions INCLUDING lookahead auxiliary expansions, 20000 physical heap entries, 30s.",
           "Wall protocol: 5s, no expansion cap, same 20000 physical heap entry cap. OPEN may stop a run before 5s.",
           "Portfolio duplicates queue entries and charges both; compression preprocessing and candidate replay are timed.",
           "Tail variants pay a 40% global seed quota then search suffix lengths 6/10/14 with the remainder. No free baseline warm start.",
           "All methods start from the common frozen PT. Baseline stops at its first solution; actual effort differs.","",
           "|Protocol|Method|J median|Pd median|Seconds|Total work|Peak MiB|Stops|", "|---|---|---:|---:|---:|---:|---:|---|"]
    for a in aggregate:lines.append(f"|{a['protocol']}|{a['variant']}|{a['J_median']:.9f}|{a['Pd_T_median']:.9f}|{a['search_wall_s_median']:.4f}|{a['work_expanded_median']:g}|{a['process_peak_memory_mib_median']:.2f}|{a['stops']}|")
    lines += ["", "J and final Pd can trade off. Candidate archives describe encountered/replayed candidates only, never a global Pareto frontier.",
              "Generic speedups, larger neighborhoods and multiple ordering queues are engineering techniques, not established STDC novelty.",
              "No epsilon guarantee is inferred from finite Oracle checks or budget-stopped real searches."]
    (folder/"report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    return aggregate


def controller(stage,folder,evidence_path,smoke):
    require(not folder.exists(),"refuse to overwrite outputs");folder.mkdir(parents=True)
    rows=[];summary=dict(status="running",runs=0);tic=perf_counter()
    try:
        validation_gate(evidence_path);preserve(evidence_path.parent)
        if stage=="benchmark":
            require(smoke is not None and read(smoke/"summary.json")["status"]=="passed","smoke not passed")
            for item in read(smoke/"artifact_manifest.json")["files"]:require(digest(smoke/item["path"])==item["sha256"],"smoke file changed")
            require(read(smoke/"source_sha256.json")==sources(),"source changed after smoke")
        snapshot(folder,folder.parent);source=sources()
        save(folder/"source_sha256.json",source)
        schedule=[(v,"work",0) for v in VARIANTS] if stage=="smoke" else [
            (v,p,r) for p in CAPS for r in range(3) for v in VARIANTS[r:]+VARIANTS[:r]]
        save(folder/"protocol.json",dict(variants=VARIANTS,caps=CAPS,schedule=schedule,seed=41,
             weight=WEIGHT,lookahead_horizon=8,lookahead_steps=2,tail_lengths=[6,10,14],
             tail_seed_fraction=.4,portfolio_every=8,environment=environment(),
             synthetic_validation=str(evidence_path),validation_sha256=digest(evidence_path),
             guarantee="uncertified",objective="sum M_t for t=1..T; default min J",input="common frozen PT"))
        for variant,protocol_name,repeat in schedule:
            target=folder/f"{variant}_{protocol_name}_r{repeat}";target.mkdir()
            command=[sys.executable,str(Path(__file__).resolve()),"worker","--output-dir",str(target),
                     "--variant",variant,"--protocol",protocol_name,"--repeat",str(repeat),
                     "--validation-evidence",str(evidence_path)]
            env=child_environment()
            save(target/"command.json",dict(command=command,cwd=str(ROOT),seed=41,timeout_s=180,
                 environment={k:env.get(k) for k in ("PYTHONPATH","PYTHONDONTWRITEBYTECODE","ASAR_OFFLINE","PROJ_NETWORK","OMP_NUM_THREADS","OPENBLAS_NUM_THREADS","MKL_NUM_THREADS","NUMEXPR_NUM_THREADS")}))
            with (target/"stdout.txt").open("w",encoding="utf-8") as out,(target/"stderr.txt").open("w",encoding="utf-8") as err:
                try:proc=subprocess.run(command,cwd=ROOT,stdout=out,stderr=err,timeout=180,env=env)
                except subprocess.TimeoutExpired:
                    save(target/"watchdog.json",dict(status="budget_exceeded",stop_reason="watchdog",J=None,certified=False));raise
            require(proc.returncode==0,"worker failed: "+str(target))
            row=read(target/"result.json");require(row["source_sha256"]==source,"worker source mismatch")
            rows.append(row);save(folder/"results.json",dict(status="running",rows=rows))
            print(f"{len(rows)}/{len(schedule)} {variant} {protocol_name} J={row['J']:.9f} Pd={row['Pd_T']:.9f} {row['stop_reason']} {row['search_wall_s']:.3f}s",flush=True)
        reports(folder,rows);preserve(evidence_path.parent)
        save(folder/"results.json",dict(status="passed",rows=rows))
        summary.update(status="passed",runs=len(rows),completed=sum(r["status"]=="completed" for r in rows),
                       budget_exceeded=sum(r["status"]=="budget_exceeded" for r in rows),certified=0)
    except Exception as exc:
        summary.update(status="blocked",runs=len(rows),error=str(exc),traceback=traceback.format_exc())
        raise
    finally:
        summary["wall_s"]=perf_counter()-tic;save(folder/"summary.json",summary);manifest(folder)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage",choices=("smoke","benchmark","worker"))
    parser.add_argument("--output-dir",type=Path,required=True)
    parser.add_argument("--validation-evidence",type=Path,required=True)
    parser.add_argument("--smoke-dir",type=Path)
    parser.add_argument("--variant",choices=VARIANTS)
    parser.add_argument("--protocol",choices=CAPS,default="work")
    parser.add_argument("--repeat",type=int,default=0)
    args=parser.parse_args();folder=args.output_dir.resolve();evidence=args.validation_evidence.resolve()
    require(folder.is_relative_to(ROOT/"outputs/stdc_v0_2"),"research output only")
    if args.stage=="worker":
        try:worker(folder,args.variant,args.protocol,args.repeat,evidence)
        except Exception as exc:
            save(folder/"failure.json",dict(status="blocked",error=str(exc),traceback=traceback.format_exc()));raise
    else:controller(args.stage,folder,evidence,args.smoke_dir.resolve() if args.smoke_dir else None)
