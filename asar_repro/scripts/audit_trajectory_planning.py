"""Fail-fast prefix bounds and complete small searches; no real inputs."""
from dataclasses import asdict
import json
from time import perf_counter

from asar_repro.heuristic import Heuristic
from asar_repro.motion import ParticleMotion
from asar_repro.objective import score_path
from asar_repro.oracle import enumerate_oracle
from asar_repro.particle_dp import ParticleDP
from asar_repro.research_particle import FutureEquivalentMotion
from asar_repro.trajectory_search import search_trajectory
from asar_repro.midpoint_rollout import search_midpoint
from audit_anytime_search import independent_prefix_optima, _save
from audit_optimization import verify
from audit_window_search import cases, reference_path
from run_stdc_random_audit import make_case
from stdc_validation_guards import require, freeze_case

ATOL=1e-10


def audit(out):
    inputs=out/'inputs';inputs.mkdir();prefix_count=case_count=dp_count=gains=0;over=0.;roots=[]
    with (out/'prefixes.jsonl').open('w',encoding='utf-8') as stream:
        for kind in ('matrix','particles'):
            for seed in range(100,180):
                grid,start,T,p,q,motion=make_case(seed,kind)
                cfg=dict(start=start,budget=T,p=p,q=q,motion=motion)
                sha=freeze_case(inputs,f'{kind}_{seed}',grid,cfg)
                best,_,_=independent_prefix_optima(grid,cfg)
                require(abs(best[(start,)]-enumerate_oracle(grid,**cfg).J)<=ATOL,'independent Oracles disagree')
                stdc=Heuristic(grid,budget=T,q=q,motion=motion,mode='stdc_lb')
                dp=ParticleDP(grid,budget=T,q=q,motion=motion) if kind=='particles' else None
                if dp is not None:require(dp.ready,'toy DP construction interrupted')
                for prefix,optimum in best.items():
                    d=len(prefix)-1;s=score_path(grid,prefix,**dict(cfg,budget=d))
                    h=stdc(prefix[-1],d,s.final_belief);values=dict(stdc_lb=h)
                    if dp is not None:
                        independent=dp(prefix[-1],d,s.final_belief)
                        values.update(dp_only=independent,stdc_dp=max(h,independent))
                        gains+=int(independent>h+ATOL);dp_count+=1
                    row=dict(kind=kind,seed=seed,input_sha256=sha,prefix=prefix,
                             remaining=optimum-s.J,bounds=values)
                    _save(out/'last_checked.json',row)
                    for mode,v in values.items():
                        require(-ATOL<=v<=optimum-s.J+ATOL,f'inadmissible {mode}: {kind}/{seed}/{prefix}')
                        over=max(over,v-(optimum-s.J))
                    stream.write(json.dumps(row,allow_nan=False)+'\n');prefix_count+=1
                    if d==0:roots.append(row)
                case_count+=1
                if (seed-99)%20==0:print(f'{kind}: cases={case_count}, prefixes={prefix_count}',flush=True)
    require(case_count==160 and prefix_count==18024,'incomplete prefix schedule')
    random=dict(status='passed',cases=case_count,prefix_evaluations=prefix_count,
                dp_prefix_evaluations=dp_count,strictly_stronger_than_stdc=gains,
                max_overestimate=over,violations=0,roots=roots)
    _save(out/'random_summary.json',random)
    rows=[];case_count=0
    with (out/'searches.jsonl').open('w',encoding='utf-8') as stream:
        for kind,seed,grid,cfg,derivation in cases():
            sha=freeze_case(inputs,f'small_{kind}_{seed}',grid,cfg)
            initial=reference_path(grid,cfg,seed);opt=enumerate_oracle(grid,**cfg).J
            methods=['stdc_lb','mid_plain','mid_diverse']
            if isinstance(cfg['motion'],ParticleMotion):methods+=['dp_only','stdc_dp','compressed_dp']
            for method in methods:
                mark=perf_counter();current=dict(kind=kind,seed=seed,method=method,input_sha256=sha)
                _save(out/'last_checked.json',current)
                if method.startswith('mid_'):
                    # anchor=0 and a beam wider than the full toy tree provide an exact control.
                    result=search_midpoint(grid,**cfg,initial_path=initial,anchor_depths=(0,),
                                           beam_width=100000,diversity=method=='mid_diverse')
                elif method=='compressed_dp':
                    compressed=FutureEquivalentMotion(cfg['motion'],cfg['p'])
                    result=search_trajectory(grid,**dict(cfg,p=compressed.initial_weights,motion=compressed),
                                             initial_path=initial,bound_mode='stdc_dp',replay_cfg=cfg)
                else:result=search_trajectory(grid,**cfg,initial_path=initial,bound_mode=method)
                checks=verify(grid,cfg,result,opt)
                row=dict(current,checks=checks,result=asdict(result),wall_s=perf_counter()-mark,
                         data_type='synthetic_toy',derivation=derivation)
                stream.write(json.dumps(row,allow_nan=False)+'\n');stream.flush();rows.append(row)
            case_count+=1
            print(f'small cases={case_count}, searches={len(rows)}',flush=True)
    require(case_count==45 and len(rows)==150,'incomplete search schedule')
    return dict(status='passed',data_type='synthetic_toy',random=random,small_cases=case_count,
                small_searches=len(rows),max_J_error=max(r['checks']['oracle_error'] for r in rows),
                max_replay_error=max(r['checks']['replay_error'] for r in rows),epsilon_certified=False)
