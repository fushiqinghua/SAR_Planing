"""Observe the frozen planner without changing its objective, ordering or limits.

Diagnostic timing includes tracing overhead and is not a performance benchmark.
State hashes are counted only: they are never used for merging or pruning.
"""
import argparse
from collections import Counter, defaultdict, deque
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from time import perf_counter
import traceback
from unittest.mock import patch

import numpy as np
from asar_repro.heuristic import Heuristic
from asar_repro.objective import score_path
import asar_repro.search as search_module
from stdc_validation_guards import ROOT, load_real, replay_result, read, save, require, digest


def decomposition(graph,cfg):
    motion=cfg['motion']; p=cfg['p']; q=cfg['q']; T=cfg['budget']
    h=Heuristic(graph,budget=T,q=q,motion=motion,mode='stdc_lb')
    relaxed=p.copy(); cap=coupled=float(p.sum()); rows=[]
    for k in range(1,T+1):
        reach=h._stdc.reachable(cfg['start'],k)
        factors=np.ones(motion.bin_count); factors[reach]=1-q
        relaxed*=factors[motion.cell_ids[k]]
        a=float(relaxed.sum())
        mass=motion.cell_mass(p,k); chosen=int(reach[np.argmax(mass[reach])])
        u=q*float(mass[chosen]); prev=cap
        cap=max((1-q)*cap,cap-u)
        mult=(1-q)*coupled; subtract=coupled-u
        coupled=max(a,mult,subtract)
        rows.append(dict(k=k,reachable_cells=len(reach),a=a,U=u,U_best_cell=chosen,
            capacity=cap,stepwise=max(a,cap),ell=coupled,coupled_reach_term=a,
            coupled_q_term=mult,coupled_U_term=subtract,capacity_before=prev))
    totals={m:Heuristic(graph,budget=T,q=q,motion=motion,mode=m)(cfg['start'],0,p)
            for m in ('zero','mass_lb','reach_lb','capacity_lb','stepwise_lb','stdc_radius_lb','stdc_lb','paper_greedy')}
    require(abs(sum(r['ell'] for r in rows)-totals['stdc_lb'])<1e-12,'root decomposition mismatch')
    return dict(rows=rows,root_h=totals,tail_after_20=sum(r['ell'] for r in rows if r['k']>20),
                total_initial_mass=float(p.sum()),special_mass_initial=float(p[motion.cell_ids[0]>=graph.size].sum()))


def trace_search(folder,mode,graph,cfg,protocol):
    events=[]; unique_states=Counter(); popped_states=Counter(); dv=defaultdict(set)
    open_signatures=defaultdict(deque); last={}; samples={}; base=search_module.Heuristic
    def factory(*args,**kwargs):
        estimator=base(*args,**kwargs)
        def observed(v,d,b,**kw):
            value=estimator(v,d,b,**kw)
            key=hashlib.sha256(np.ascontiguousarray(b,dtype='<f8').tobytes()).hexdigest()
            unique_states[(d,v,key)]+=1; dv[(d,v)].add(key)
            last.update(d=d,v=v,belief_sha=key,mass=float(b.sum()))
            return value
        return observed
    def trace(row):
        row=dict(row)
        sig=tuple(row[k] for k in ('vertex','depth','g','h','f_weighted'))
        if row['event'] in ('push','prune'):
            row.update(belief_sha=last['belief_sha'],mass=last['mass'])
            if row['event']=='push':open_signatures[sig].append((last['belief_sha'],last['mass']))
        elif row['event']=='pop':
            key,mass=open_signatures[sig].popleft()
            row.update(belief_sha=key,mass=mass)
            popped_states[(row['depth'],row['vertex'],key)]+=1
        events.append(row)
    tic=perf_counter()
    with patch.object(search_module,'Heuristic',factory):
        result=search_module.search_asar(graph,**cfg,heuristic=mode,epsilon=1.1,
            initial_path=protocol['initial_path'],trace=trace,**protocol['search_limits'])
    wall=perf_counter()-tic
    score=replay_result(graph,cfg,result)
    ref=read(ROOT/f'outputs/stdc_v0_2/local_validation_20261123_r5/paired_comparison/{mode}_eps_1p1_rep_0/{mode}.json')
    for key in ('expanded','generated','pruned','peak_open','status','stop_reason','incumbent_source','path','J'):
        actual=getattr(result,key)
        if key=='path': actual=list(actual)
        require(actual==ref[key],f'instrumentation changed {mode}/{key}')
    with (folder/f'{mode}.trace.jsonl').open('w',encoding='utf-8',newline='\n') as stream:
        for row in events:stream.write(json.dumps(row,allow_nan=False)+'\n')
    pops=[r for r in events if r['event']=='pop']
    depths=[]
    for depth in sorted({r['depth'] for r in pops}):
        group=[r for r in pops if r['depth']==depth]
        depths.append(dict(depth=depth,pops=len(group),f_min=min(r['f_weighted'] for r in group),
          f_median=float(np.median([r['f_weighted'] for r in group])),f_max=max(r['f_weighted'] for r in group),
          mass_mean=float(np.mean([r['mass'] for r in group]))))
    result_row=dict(mode=mode,result=asdict(result),diagnostic_wall_s=wall,
        matches_uninstrumented_reference=True,popped=len(pops),
        max_pop_depth=max(r['depth'] for r in pops),max_generated_depth=max(r['depth'] for r in events),
        terminal_events=sum(r['depth']==cfg['budget'] for r in events),
        final_pop=pops[-1],depths=depths,
        unique_evaluated_states=len(unique_states),duplicate_evaluations=sum(unique_states.values())-len(unique_states),
        unique_popped_states=len(popped_states),duplicate_pops=sum(popped_states.values())-len(popped_states),
        distinct_depth_vertex=len(dv),depth_vertex_with_multiple_beliefs=sum(len(s)>1 for s in dv.values()),
        distinct_pop_f_exact=len({r['f_weighted'] for r in pops}),
        f_quantiles=np.quantile([r['f_weighted'] for r in pops],[0,.25,.5,.75,1]).tolist(),
        exact_state_duplicates_are_diagnostic_only=True)
    save(folder/f'{mode}.json',result_row)
    print(json.dumps({k:result_row[k] for k in ('mode','max_pop_depth','max_generated_depth','terminal_events',
         'unique_evaluated_states','duplicate_evaluations','duplicate_pops','distinct_pop_f_exact','f_quantiles')},allow_nan=False),flush=True)
    return result_row


def path_bounds(graph,cfg,protocol):
    old=ROOT/'outputs/stdc_v0_2/local_validation_20261123_r5/paired_comparison'
    paths={'PT':protocol['initial_path'],
           'paper_1p1':read(old/'paper_greedy_eps_1p1_rep_0/paper_greedy.json')['path']}
    rows=[]
    for name,path in paths.items():
        score=score_path(graph,path,**cfg,record_beliefs=True)
        for d in range(50):
            values={m:Heuristic(graph,budget=49,q=cfg['q'],motion=cfg['motion'],mode=m)
                      (path[d],d,score.beliefs[d])
                    for m in ('mass_lb','reach_lb','capacity_lb','stepwise_lb','stdc_lb','paper_greedy')}
            require(values['stdc_lb']<=score.J-float(score.g[d])+1e-10,'STDC exceeds feasible suffix')
            rows.append(dict(path=name,depth=d,vertex=path[d],g=float(score.g[d]),
                  feasible_suffix_cost=score.J-float(score.g[d]),h=values,
                  stdc_f=float(score.g[d])+1.1*values['stdc_lb']))
    return rows


def main(folder):
    require(folder.is_relative_to(ROOT/'outputs/stdc_v0_2'),'research outputs only')
    folder.mkdir(exist_ok=False)
    files=list((ROOT/'src').rglob('*.py'))
    before={p.relative_to(ROOT).as_posix():digest(p) for p in files}
    save(folder/'source_before.json',before)
    summary=dict(status='running',source_commit='4a01dee2275ce3b732f619e0192fd1a417a5766e',
                 purpose='causal diagnosis; not a new benchmark or optimizer',modes=['mass_lb','stdc_lb','paper_greedy'],
                 epsilon=1.1,seed=41,limits=dict(max_expansions=5000,max_open=20000,max_seconds=30))
    try:
        protocol,graph,cfg,pt,_,raw=load_real()
        save(folder/'input_gate.json',dict(status='passed',particle_sha256=protocol['particle_archive']['sha256'],
             verified_raw_sources=raw,PT_J=pt.J,limits=protocol['search_limits']))
        save(folder/'root_decomposition.json',decomposition(graph,cfg))
        save(folder/'path_bounds.json',path_bounds(graph,cfg,protocol))
        summary['traces']=[trace_search(folder,m,graph,cfg,protocol) for m in summary['modes']]
        require(before=={p.relative_to(ROOT).as_posix():digest(p) for p in files},'production source changed')
        summary['status']='passed'
    except Exception as exc:
        summary.update(status='blocked',error=str(exc),traceback=traceback.format_exc())
        raise
    finally:save(folder/'diagnosis.json',summary)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    main(parser.parse_args().output_dir.resolve())
