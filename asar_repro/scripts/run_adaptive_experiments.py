"""Frozen three-archive paired comparison of opt-in adaptive search."""
import argparse
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from statistics import median
import subprocess
import sys
from time import perf_counter
import traceback
import numpy as np
import psutil
from asar_repro.adaptive_search import search_adaptive
from asar_repro.objective import score_path
from run_trajectory_experiments import invoke as old_invoke,CAPS
from stdc_validation_guards import ROOT,load_real,read,save,digest,require,check_score
from run_optimization_validation import sources,snapshot,environment,child_environment
from run_adaptive_validation import preservation
from run_anytime_experiments import csv_save,manifest
SCENES=("lake_ontario","arctic_ocean","bay_of_fundy")
VARIANTS=("paper_baseline","prior_stdc","recycle_stdc","short_eager","short_lazy",
          "short_diverse","fast_stdc","dense_fallback","compact_dp","adaptive_combo")
OLD_DIRS={"arctic_ocean":"additional_real_20261124","bay_of_fundy":"fundy_repair_20261124"}
ATOL=1e-10
def load_case(name):
    if name=="lake_ontario":
        protocol,grid,cfg,pt,times,raw=load_real()
        rec=dict(initial_path=protocol["initial_path"],PT_J=pt.J,PT_Pd=pt.pd_final,
            mission=protocol["mission"],particle_sha256=protocol["particle_archive"]["sha256"],
            metadata_sha256=protocol["particle_metadata_sha256"],forcing=raw)
    else:
        from compare_additional_real import load_input
        old=ROOT/"outputs/stdc_v0_2"/OLD_DIRS[name]
        if name=="bay_of_fundy":
            from run_fundy_native import parent_gate,POLICY
            parent_gate(old)
        grid,cfg,meta=load_input(old,name)
        rec=read(old/"frozen_comparison/protocol.json")["scenarios"][name]
        require(meta["particle_sha256"]==rec["particle_sha256"],"archive SHA changed")
        require(digest(old/"b3"/name/"metadata.json")==rec["metadata_sha256"],"metadata changed")
        if name=="bay_of_fundy":
            require(meta["direction_policy"]["physical_direction_unverified"],"Fundy qualification lost")
        pt=score_path(grid,rec["initial_path"],**cfg)
        require(abs(pt.J-rec["PT_J"])<=ATOL and abs(pt.pd_final-rec["PT_Pd"])<=ATOL,"PT changed")
    rec=dict(rec,physical_direction_unverified=name=="bay_of_fundy")
    return grid,cfg,rec
def execute(grid,cfg,path,variant,limits):
    if variant in ("paper_baseline","prior_stdc"):
        return old_invoke(grid,cfg,path,variant,limits)
    opts={
        "recycle_stdc":dict(schedule="recycle"),
        "short_eager":dict(schedule="bursts",lazy_rollout=False),
        "short_lazy":dict(schedule="bursts",lazy_rollout=True),
        "short_diverse":dict(schedule="bursts",lazy_rollout=True,diversity_slots=4),
        "fast_stdc":dict(efficient_guide=True),
        "dense_fallback":dict(dp_kind="dense"),
        "compact_dp":dict(dp_kind="compact",dp_mode="only",efficient_guide=True),
        "adaptive_combo":dict(schedule="bursts",lazy_rollout=True,diversity_slots=4,
                              efficient_guide=True,dp_kind="compact"),
    }[variant]
    return search_adaptive(grid,**cfg,initial_path=path,**opts,**limits)
def prepare(run):
    require(read(run/"validation_summary.json")["status"]=="passed","tests/Oracle gate not passed")
    require(sources()==read(run/"freeze.json")["source_sha256"],"source changed")
    out=run/"experiment";out.mkdir(exist_ok=False)
    records={}
    for name in SCENES:
        _,_,rec=load_case(name);records[name]=rec
    save(out/"protocol.json",dict(status="passed",scenarios=records,variants=VARIANTS,
        caps=CAPS,repeats=3,seed=41,guide_weight=1.04,source_sha256=sources(),
        environment=environment(),validation_sha256=digest(run/"validation_summary.json"),
        preservation=preservation(run),model="unchanged min-J/scorer/forcing/t0; no state merging",
        global_chunk=512,burst_work=128,local_fraction_max=.1,local_time_slice_s=.1,
        local_cooldown='after completed unproductive windows, wait 2 then 4 global chunks; reset after a local J improvement',
        beam_quality_width=24,extra_diversity_slots=4,window_lengths=[4,6,8],
        dp_managed_limit_bytes=128*2**20,preprocessing_charged=True,
        time_scope="preprocessing + all search phases + internal replay; frozen input verification and common PT excluded",
        memory_scope="isolated process peak includes imports, verification, preprocessing, search and replay",
        repetition_scope="same seed41 archive; timing repeats are not independent target realizations",
        global_epsilon_certified=False,real_input=True,coastline="all-water collision approximation; native missing/land/outside mass retained"))
    snapshot(out,run);manifest(out)
    print("prepare passed: all three original archive/forcing hashes verified",flush=True)
def worker(run,out,name,variant,cap,repeat,smoke):
    protocol=read(run/"experiment/protocol.json")
    require(protocol["source_sha256"]==sources(),"source changed after protocol")
    require(digest(run/"validation_summary.json")==protocol["validation_sha256"],"validation changed")
    tic=perf_counter();grid,cfg,rec=load_case(name);input_s=perf_counter()-tic
    require(rec==protocol["scenarios"][name],"frozen mission/input changed")
    limits=dict(CAPS[cap])
    if smoke:limits.update(max_expansions=100,max_seconds=3.)
    result,phases,prep,elapsed=execute(grid,cfg,tuple(rec["initial_path"]),variant,limits)
    save(out/"raw_result.json",dict(result=asdict(result),phases=phases,preprocessing=prep))
    score=score_path(grid,result.path,**cfg);check_score(score)
    require(not result.theory_certified and abs(score.J-result.J)<=ATOL,"J replay/certificate mismatch")
    if hasattr(result,"Pd"):require(abs(score.pd_final-result.Pd)<=ATOL,"Pd replay mismatch")
    require(score.J<=rec["PT_J"]+ATOL,"lost common PT")
    count=result.stats.get("work_expanded",result.expanded) if hasattr(result,"stats") else result.expanded
    require(limits["max_expansions"] is None or count<=limits["max_expansions"],"work cap exceeded")
    require(result.peak_open<=limits["max_open"],"physical OPEN exceeded")
    require(result.status in ("completed","budget_exceeded"),"invalid final status")
    require(bool(result.stop_reason)==(result.status=="budget_exceeded"),"invalid stop reason")
    replays=[];previous=float("inf")
    for event in getattr(result,"incumbent_history",[]):
        s=score_path(grid,event["path"],**cfg)
        require(abs(s.J-event["J"])<=ATOL and abs(s.pd_final-event["Pd"])<=ATOL,"history replay mismatch")
        require(s.J<previous-ATOL,"nonimproving history")
        require(0<=event["elapsed_s"]<=elapsed+.01,"history clock outside paid time")
        require(event.get("work_expanded",0)<=count,"history work outside total")
        replays.append(dict(J=s.J,Pd=s.pd_final));previous=s.J
    for phase in phases:
        for e in phase.get("incumbent_history",[]):
            s=score_path(grid,e["path"],**cfg)
            require(abs(s.J-e["J"])<=ATOL and abs(s.pd_final-e["Pd"])<=ATOL,"local replay mismatch")
    for e in getattr(result,"candidate_archive",[]):
        s=score_path(grid,e["path"],**cfg)
        require(abs(s.J-e["J"])<=ATOL and abs(s.pd_final-e["Pd"])<=ATOL,"candidate archive mismatch")
    mem=psutil.Process().memory_info()
    row=dict(asdict(result),scenario=name,variant=variant,protocol=cap,repeat=repeat,smoke=smoke,
        J=score.J,Pd_T=score.pd_final,work_expanded=count,search_wall_s=elapsed,
        process_peak_memory_mib=getattr(mem,"peak_wset",mem.rss)/2**20,input_verification_s=input_s,
        cooperative_overshoot_s=max(0,elapsed-limits["max_seconds"]),limits=limits,
        PT_J=rec["PT_J"],PT_Pd=rec["PT_Pd"],legal=True,replay_error_J=abs(score.J-result.J),
        replay_error_Pd=abs(score.pd_final-getattr(result,"Pd",score.pd_final)),
        history_replays=replays,survival=score.survival.tolist(),cumulative_J=score.g.tolist(),
        preprocessing=prep,particle_sha256=rec["particle_sha256"],config=rec["mission"],
        source_sha256=sources(),forcing_kind="historical_real",particle_seed=41,
        physical_direction_unverified=name=="bay_of_fundy",guarantee="uncertified",
        memory_scope=protocol["memory_scope"])
    save(out/"result.json",row)
def reports(folder,rows):
    aggregate=[];pairs=[]
    for name in SCENES:
        for cap in CAPS:
            for variant in VARIANTS:
                rs=[r for r in rows if (r["scenario"],r["protocol"],r["variant"])==(name,cap,variant)]
                if not rs:continue
                a=dict(scenario=name,protocol=cap,variant=variant,n=len(rs),
                    completed=sum(r["status"]=="completed" for r in rs),
                    budget_exceeded=sum(r["status"]=="budget_exceeded" for r in rs),
                    stops=dict(Counter(r["stop_reason"] or "completed" for r in rs)),
                    physical_direction_unverified=name=="bay_of_fundy")
                for k in ("J","Pd_T","search_wall_s","process_peak_memory_mib","work_expanded"):
                    for label,fn in (("median",median),("min",min),("max",max)):a[k+"_"+label]=fn(r[k] for r in rs)
                aggregate.append(a)
    for r in rows:
        b=next((b for b in rows if (b["scenario"],b["protocol"],b["repeat"],b["variant"])==(r["scenario"],r["protocol"],r["repeat"],"prior_stdc")),None)
        if b and r["variant"]!="prior_stdc":
            pairs.append(dict(scenario=r["scenario"],protocol=r["protocol"],repeat=r["repeat"],variant=r["variant"],
                delta_J=r["J"]-b["J"],delta_Pd=r["Pd_T"]-b["Pd_T"],
                improves_J=r["J"]<b["J"]-ATOL,improves_Pd=r["Pd_T"]>b["Pd_T"]+ATOL,
                joint_improvement=r["J"]<b["J"]-ATOL and r["Pd_T"]>b["Pd_T"]+ATOL,
                time_ratio=r["search_wall_s"]/b["search_wall_s"],memory_ratio=r["process_peak_memory_mib"]/b["process_peak_memory_mib"]))
    save(folder/"aggregate.json",dict(rows=aggregate));csv_save(folder/"aggregate.csv",aggregate);csv_save(folder/"paired_comparisons.csv",pairs)
    flat=[{k:r.get(k) for k in ("scenario","protocol","repeat","variant","J","Pd_T","search_wall_s","process_peak_memory_mib","work_expanded","status","stop_reason","incumbent_source","physical_direction_unverified","particle_sha256")} for r in rows]
    csv_save(folder/"metrics.csv",flat)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    for name in SCENES:
        tag=" / PHYSICAL DIRECTION UNVERIFIED" if name=="bay_of_fundy" else ""
        for cap in CAPS:
            chosen=[r for r in rows if (r["scenario"],r["protocol"],r["repeat"])==(name,cap,0)]
            if not chosen:continue
            fig,axs=plt.subplots(2,5,figsize=(18,8),constrained_layout=True)
            for ax,r in zip(axs.flat,chosen):
                nr,nc=r["config"]["grid_rows_cols"];path=np.array(r["path"])
                ax.plot(path%nc,path//nc,".-",ms=2);ax.scatter(path[0]%nc,path[0]//nc,marker="*",s=60)
                ax.set(title=f"{r['variant']}\nJ={r['J']:.6f} Pd={r['Pd_T']:.6f}",aspect="equal",xlim=(-.5,nc-.5),ylim=(nr-.5,-.5))
            fig.suptitle(name+" / "+cap+" / real archive; all-water approximation; uncertified"+tag)
            fig.savefig(folder/f"{name}_{cap}_paths.png",dpi=150);plt.close(fig)
            fig,axs=plt.subplots(1,2,figsize=(14,5),constrained_layout=True)
            for r in chosen:
                axs[0].plot(r["survival"],label=r["variant"])
                h=r.get("incumbent_history",[])
                if h:axs[1].step([e["elapsed_s"] for e in h]+[r["search_wall_s"]],[e["J"] for e in h]+[r["J"]],where="post",label=r["variant"])
            axs[0].set(xlabel="Absolute planning step (t=0 no detection)",ylabel="Undetected mass")
            axs[1].set(xlabel="Paid method seconds",ylabel="Best complete J")
            for ax in axs:ax.legend(fontsize=6);ax.grid(alpha=.2)
            fig.suptitle(name+" / "+cap+tag);fig.savefig(folder/f"{name}_{cap}_survival_anytime.png",dpi=150);plt.close(fig)
            group=[a for a in aggregate if (a["scenario"],a["protocol"])==(name,cap)]
            fig,axs=plt.subplots(1,4,figsize=(20,6),constrained_layout=True)
            for ax,k in zip(axs,("J","Pd_T","search_wall_s","process_peak_memory_mib")):
                ax.barh([a["variant"] for a in group],[a[k+"_median"] for a in group]);ax.invert_yaxis();ax.set_title(k+" median");ax.tick_params(axis="y",labelsize=7)
            fig.suptitle(name+" / "+cap+tag);fig.savefig(folder/f"{name}_{cap}_efficiency.png",dpi=150);plt.close(fig)
            pair_group=[p for p in pairs if (p['scenario'],p['protocol'])==(name,cap)]
            if pair_group:
                fig,axs=plt.subplots(1,2,figsize=(14,6),constrained_layout=True)
                labels=[v for v in VARIANTS if v!='prior_stdc']
                for ax,key,scale,title in ((axs[0],'delta_J',1,'Paired median delta J (negative better)'),
                                          (axs[1],'delta_Pd',100,'Paired median delta Pd (percentage points)')):
                    values=[scale*median(p[key] for p in pair_group if p['variant']==v) for v in labels]
                    ax.barh(labels,values);ax.axvline(0,color='black',lw=.8);ax.invert_yaxis();ax.set_title(title)
                fig.suptitle(name+' / '+cap+' / direct STDC reference'+tag)
                fig.savefig(folder/f'{name}_{cap}_paired_deltas.png',dpi=150);plt.close(fig)
def controller(run,stage):
    out=run/stage;out.mkdir(exist_ok=False);rows=[];started=perf_counter();summary=dict(status="running")
    try:
        require(read(run/"validation_summary.json")["status"]=="passed","validation not passed")
        protocol=read(run/"experiment/protocol.json");require(protocol["source_sha256"]==sources(),"frozen source changed")
        if stage=="benchmark":require(read(run/"smoke/summary.json")["status"]=="passed","smoke failed")
        schedule=[(n,v,"work",0) for n in SCENES for v in VARIANTS] if stage=="smoke" else [
            (n,v,p,r) for p in CAPS for r in range(3) for n in SCENES for v in VARIANTS[r:]+VARIANTS[:r]]
        save(out/"schedule.json",dict(schedule=schedule,seed=41,protocol_sha256=digest(run/"experiment/protocol.json")))
        for name,variant,cap,repeat in schedule:
            sub=out/f"{name}_{variant}_{cap}_r{repeat}";sub.mkdir()
            cmd=[sys.executable,str(Path(__file__).resolve()),"worker","--run-dir",str(run),
                "--output-dir",str(sub),"--scenario",name,"--variant",variant,"--protocol",cap,"--repeat",str(repeat)]
            if stage=="smoke":cmd+=["--smoke"]
            env=child_environment();save(sub/"command.json",dict(command=cmd,cwd=str(ROOT),seed=41,watchdog_s=180,
                environment={k:env.get(k) for k in ("PYTHONPATH","ASAR_OFFLINE","PROJ_NETWORK","OMP_NUM_THREADS","OPENBLAS_NUM_THREADS","MKL_NUM_THREADS")}))
            with (sub/"stdout.txt").open("w",encoding="utf-8") as stdout,(sub/"stderr.txt").open("w",encoding="utf-8") as stderr:
                try:proc=subprocess.run(cmd,cwd=ROOT,env=env,stdout=stdout,stderr=stderr,timeout=180)
                except subprocess.TimeoutExpired:
                    save(sub/"watchdog.json",dict(status="budget_exceeded",stop_reason="watchdog",J=None,certified=False));raise
            require(proc.returncode==0,"worker failed: "+sub.name)
            row=read(sub/"result.json");rows.append(row);save(out/"results.json",dict(status="running",rows=rows))
            print(f"{len(rows)}/{len(schedule)} {name} {variant} {cap} J={row['J']:.9f} Pd={row['Pd_T']:.9f} {row['stop_reason']} {row['search_wall_s']:.3f}s",flush=True)
        reports(out,rows)
        summary.update(status="passed",runs=len(rows),completed=sum(r["status"]=="completed" for r in rows),
            budget_exceeded=sum(r["status"]=="budget_exceeded" for r in rows),certified=0,
            max_J_replay_error=max(r["replay_error_J"] for r in rows),max_Pd_replay_error=max(r["replay_error_Pd"] for r in rows))
        save(out/"results.json",dict(status="passed",rows=rows))
    except BaseException as exc:
        summary.update(status="blocked",runs=len(rows),error=str(exc),traceback=traceback.format_exc());raise
    finally:
        summary["wall_s"]=perf_counter()-started;save(out/"summary.json",summary);manifest(out)
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("stage",choices=("prepare","smoke","benchmark","worker"))
    p.add_argument("--run-dir",required=True,type=Path);p.add_argument("--output-dir",type=Path)
    p.add_argument("--scenario",choices=SCENES);p.add_argument("--variant",choices=VARIANTS)
    p.add_argument("--protocol",choices=CAPS,default="work");p.add_argument("--repeat",type=int,default=0)
    p.add_argument("--smoke",action="store_true");a=p.parse_args();run=a.run_dir.resolve()
    if a.stage=="prepare":prepare(run)
    elif a.stage=="worker":
        try:worker(run,a.output_dir.resolve(),a.scenario,a.variant,a.protocol,a.repeat,a.smoke)
        except BaseException as e:
            save(a.output_dir/"failure.json",dict(status="blocked",error=str(e),traceback=traceback.format_exc()));raise
    else:controller(run,a.stage)

