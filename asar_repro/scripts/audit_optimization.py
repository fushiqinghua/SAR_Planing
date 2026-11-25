"""Sequential fail-fast synthetic audits; every full route uses frozen scoring."""
import argparse
from dataclasses import asdict
from pathlib import Path
from time import perf_counter
import json
import sys
import traceback

from asar_repro.heuristic import Heuristic
from asar_repro.lookahead_bound import LookaheadBound
from asar_repro.motion import ParticleMotion
from asar_repro.objective import score_path
from asar_repro.oracle import enumerate_oracle
from asar_repro.research_particle import FutureEquivalentMotion, ParticleGuide
from asar_repro.research_search import search_research
from asar_repro.tail_repair import repair_tail
from audit_anytime_search import independent_prefix_optima, _save
from audit_window_search import cases, reference_path
from run_stdc_random_audit import make_case
from stdc_validation_guards import require, freeze_case, MODES, check_score

ATOL = 1e-10


def verify(grid, cfg, result, optimum):
    replay = score_path(grid, result.path, **cfg)
    check_score(replay)
    require(result.status == "completed", "unlimited toy search aborted")
    require(not result.theory_certified, "unexpected certificate")
    require(abs(replay.J-optimum)<=ATOL, "Oracle J disagreement")
    require(abs(result.J-replay.J)<=ATOL and abs(result.Pd-replay.pd_final)<=ATOL, "final replay disagreement")
    previous = float("inf")
    for entry in result.incumbent_history:
        r = score_path(grid, entry["path"], **cfg)
        require(abs(r.J-entry["J"])<=ATOL and abs(r.pd_final-entry["Pd"])<=ATOL, "history replay disagreement")
        require(r.J<previous, "history did not improve")
        previous = r.J
    for entry in getattr(result, "candidate_archive", []):
        r = score_path(grid, entry["path"], **cfg)
        require(abs(r.J-entry["J"])<=ATOL and abs(r.pd_final-entry["Pd"])<=ATOL, "archive replay disagreement")
    return dict(oracle_error=abs(replay.J-optimum), replay_error=abs(replay.J-result.J),
                legal=True, J=replay.J, Pd=replay.pd_final)


def random_audit(out):
    inputs=out/"inputs"; inputs.mkdir()
    count=case_count=gains=0; over=0.; roots=[]
    with (out/"prefixes.jsonl").open("w",encoding="utf-8") as stream:
        for kind in ("matrix","particles"):
            for seed in range(100,180):
                grid,start,T,p,q,motion=make_case(seed,kind)
                cfg=dict(start=start,budget=T,p=p,q=q,motion=motion)
                sha=freeze_case(inputs,f"{kind}_{seed}",grid,cfg)
                best,_,complete=independent_prefix_optima(grid,cfg)
                require(abs(best[(start,)]-enumerate_oracle(grid,**cfg).J)<=ATOL,"independent Oracles disagree")
                bounds={m:Heuristic(grid,budget=T,q=q,motion=motion,mode=m) for m in MODES}
                lifted=LookaheadBound(grid,budget=T,q=q,motion=motion,steps=2)
                fast=ParticleGuide(grid,budget=T,q=q,motion=motion)
                paper=Heuristic(grid,budget=T,q=q,motion=motion,mode="paper_greedy")
                for prefix,optimum in best.items():
                    d=len(prefix)-1
                    s=score_path(grid,prefix,**dict(cfg,budget=d))
                    b=s.final_belief
                    values={m:h(prefix[-1],d,b) for m,h in bounds.items()}
                    ev=lifted.evaluate(prefix[-1],d,b)
                    values["lookahead"]=ev.value
                    row=dict(kind=kind,seed=seed,input_sha256=sha,prefix=prefix,remaining=optimum-s.J,bounds=values)
                    _save(out/"last_checked.json",row)
                    for key,h in values.items():
                        require(-ATOL<=h<=optimum-s.J+ATOL,f"inadmissible {key}: {kind}/{seed}/{prefix}")
                        over=max(over,h-(optimum-s.J))
                    require(ev.value+ATOL>=values["stdc_lb"],"lifted bound weaker than base")
                    require(all(values["stdc_lb"]+ATOL>=values[m] for m in MODES),"historical STDC dominance failure")
                    c1=[];c2=[]
                    hf=fast(prefix[-1],d,b,choices=c1)
                    hp=paper(prefix[-1],d,b,choices=c2)
                    require(abs(hf-hp)<=ATOL and c1==c2,"fast guide changed Algorithm 2")
                    gains+=int(ev.value>values["stdc_lb"]+ATOL)
                    stream.write(json.dumps(row)+"\n")
                    count+=1
                    if d==0: roots.append(row)
                case_count+=1
                if (seed-99)%20==0:
                    print(f"{kind}: cases={case_count} prefixes={count}",flush=True)
    require(case_count==160 and count==18024,"incomplete random cases/prefixes")
    return dict(status="passed",cases=case_count,prefix_evaluations=count,violations=0,
                max_overestimate=over,strictly_improved_prefixes=gains,roots=roots,
                seeds=list(range(100,180)),data_type="synthetic_toy",certified=False)


def small_audit(out):
    inputs=out/"inputs";inputs.mkdir();rows=[];case_count=0
    with (out/"searches.jsonl").open("w",encoding="utf-8") as stream:
        for kind,seed,grid,cfg,derivation in cases():
            sha=freeze_case(inputs,f"{kind}_{seed}",grid,cfg)
            initial=reference_path(grid,cfg,seed)
            optimum=enumerate_oracle(grid,**cfg).J
            schedule=[("fast_"+m,dict(bound_mode=m)) for m in ("zero","mass_lb","stdc_lb","lookahead")]
            schedule.append(("portfolio",dict(bound_mode="stdc_lb",portfolio=True)))
            schedule.extend([("tail_zero",None),("tail_stdc",None)])
            if isinstance(cfg["motion"],ParticleMotion):schedule.append(("compressed",None))
            for name,kwargs in schedule:
                current=dict(kind=kind,seed=seed,variant=name,input_sha256=sha)
                _save(out/"last_checked.json",current)
                started=perf_counter()
                if name.startswith("tail_"):
                    result=repair_tail(grid,**cfg,initial_path=initial,lengths=(cfg["budget"],),
                                       bound_mode="zero" if name=="tail_zero" else "stdc_lb")
                elif name=="compressed":
                    motion=FutureEquivalentMotion(cfg["motion"],cfg["p"])
                    result=search_research(grid,**dict(cfg,motion=motion,p=motion.initial_weights),
                                           initial_path=initial,replay_cfg=cfg)
                else:
                    result=search_research(grid,**cfg,initial_path=initial,**kwargs)
                checks=verify(grid,cfg,result,optimum)
                row=dict(current,checks=checks,result=asdict(result),wall_s=perf_counter()-started,
                         data_type="synthetic_toy",derivation=derivation)
                stream.write(json.dumps(row)+"\n");stream.flush();rows.append(row)
            case_count+=1
            print(f"cases={case_count} searches={len(rows)} seed={seed}",flush=True)
    require(case_count==45 and len(rows)==320,"incomplete small search schedule")
    return dict(status="passed",cases=case_count,searches=len(rows),
                max_J_error=max(r["checks"]["oracle_error"] for r in rows),
                max_replay_error=max(r["checks"]["replay_error"] for r in rows),certified=False)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage",choices=("random","small"))
    parser.add_argument("--output-dir",type=Path,required=True)
    args=parser.parse_args();out=args.output_dir;out.mkdir(parents=True,exist_ok=False)
    started=perf_counter()
    try:
        result=(random_audit if args.stage=="random" else small_audit)(out)
    except Exception as exc:
        result=dict(status="blocked",error=str(exc),traceback=traceback.format_exc())
        _save(out/"summary.json",result)
        raise
    result["wall_s"]=perf_counter()-started
    result["command"]=[sys.executable,*sys.argv]
    _save(out/"summary.json",result)
    print(json.dumps({k:v for k,v in result.items() if k!="roots"}),flush=True)
