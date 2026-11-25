"""Independent diagnostic Oracle audit; later planning has its own module."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
from time import perf_counter
import traceback

import numpy as np
from asar_repro.grid import GridGraph
from asar_repro.motion import ParticleMotion
from asar_repro.objective import score_path
from asar_repro.oracle import enumerate_oracle
from asar_repro.particle_diagnostic import solve_diagnostic
from audit_anytime_search import independent_prefix_optima, _save
from audit_window_search import reference_path
from stdc_validation_guards import require, freeze_case


def diagnostic(out):
    inputs=out/'inputs';inputs.mkdir();rows=[];prefixes=0;over=0.;error=0.
    with (out/'prefixes.jsonl').open('w',encoding='utf-8') as stream:
        for seed in range(63000,63012):
            rng=np.random.default_rng(seed)
            grid=GridGraph(2,2+seed%2);T=3+seed%2;N=5
            cells=rng.integers(0,grid.size+4,size=(T+1,N));cells[:,-1]=grid.size+3
            p=rng.dirichlet(np.ones(N));q=rng.uniform(.1,.95,grid.size)
            if seed%5==0:q[:]=1
            if seed%7==0:q[:]=0
            cfg=dict(start=seed%grid.size,budget=T,p=p,q=q,motion=ParticleMotion(cells,grid.size,np.arange(N)+100*seed))
            sha=freeze_case(inputs,str(seed),grid,cfg)
            oracle=enumerate_oracle(grid,**cfg);best,_,count=independent_prefix_optima(grid,cfg)
            require(abs(oracle.J-best[(cfg['start'],)])<=1e-10,'independent Oracles disagree')
            initial=reference_path(grid,cfg,seed)
            mip=solve_diagnostic(grid,**cfg,method='milp',initial_path=initial,max_seconds=20)
            _save(out/'last_checked.json',dict(seed=seed,stage='milp',result=asdict(mip)))
            require(mip.path is not None and mip.status=='completed','toy MILP did not finish')
            replay=score_path(grid,mip.path,**cfg)
            error=max(error,abs(replay.J-oracle.J))
            require(abs(replay.J-oracle.J)<=1e-8,'MILP differs from DFS Oracle')
            require(abs(replay.J-mip.J)<=1e-10 and abs(replay.pd_final-mip.Pd)<=1e-10,'MILP replay mismatch')
            require(not mip.theory_certified,'unexpected epsilon certificate')
            for prefix,optimum in best.items():
                lp=solve_diagnostic(grid,**cfg,method='lp',prefix_path=prefix,max_seconds=10)
                row=dict(seed=seed,prefix=prefix,oracle_full_J=optimum,input_sha256=sha,result=asdict(lp))
                _save(out/'last_checked.json',row);stream.write(json.dumps(row,allow_nan=False)+'\n')
                require(lp.lower_bound is not None,'missing conservative LP bound')
                require(lp.lower_bound<=optimum+1e-10,'inadmissible LP lower bound')
                over=max(over,lp.lower_bound-optimum);prefixes+=1
            rows.append(dict(seed=seed,oracle_J=oracle.J,oracle_paths=count,milp_J=replay.J))
            print(f'diagnostic cases={len(rows)} LP-prefixes={prefixes}',flush=True)
    _save(out/'cases.json',rows)
    return dict(status='passed',cases=len(rows),milp_searches=len(rows),prefix_evaluations=prefixes,
                max_bound_overestimate=over,max_J_error=error,violations=0,epsilon_certified=False,
                seeds=list(range(63000,63012)),data_type='synthetic_toy')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('phase',choices=('diagnostic','planning'))
    p.add_argument('--output-dir',type=Path,required=True);args=p.parse_args()
    out=args.output_dir.resolve();out.mkdir(parents=True,exist_ok=False);started=perf_counter()
    try:
        if args.phase=='diagnostic':result=diagnostic(out)
        else:
            from audit_trajectory_planning import audit
            result=audit(out)
    except Exception as exc:
        _save(out/'summary.json',dict(status='blocked',error=str(exc),traceback=traceback.format_exc()))
        raise
    result.update(wall_s=perf_counter()-started,command=[sys.executable,*sys.argv])
    _save(out/'summary.json',result);print(json.dumps(result,ensure_ascii=False),flush=True)
