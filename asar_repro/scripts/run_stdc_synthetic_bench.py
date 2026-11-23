"""Reproducible *synthetic* large-grid performance probe (NOT Lake Ontario).

Contrasts root-bound evaluation cost and fixed-expansion search work on
17x17, 500 IDs, 49 steps, without requiring historical forcing archives.
"""
import argparse
import json
from pathlib import Path
from time import perf_counter

import numpy as np

from asar_repro.grid import GridGraph
from asar_repro.motion import ParticleMotion
from asar_repro.heuristic import Heuristic
from asar_repro.search import search_asar


def synthetic_case(seed=20261123):
    rng=np.random.default_rng(seed)
    grid=GridGraph(17,17)
    T=49
    N=500
    rc=np.empty((T+1,N,2),dtype=np.int32)
    rc[0,:,0]=np.clip(np.round(rng.normal(8,2.2,N)).astype(int),0,16)
    rc[0,:,1]=np.clip(np.round(rng.normal(8,2.2,N)).astype(int),0,16)
    for t in range(1,T+1):
        # smooth but uncertain drift, with a slow eastward tendency
        step=rng.choice(5,size=N,p=[.45,.1,.13,.20,.12])
        rc[t]=rc[t-1]
        rc[t,:,0]=np.clip(rc[t,:,0] + (step==1)-(step==2),0,16)
        rc[t,:,1]=np.clip(rc[t,:,1] + (step==3)-(step==4),0,16)
    cells=(rc[:,:,0]*17+rc[:,:,1]).astype(np.int64)
    # 5% persistently not searchable; do not discard probability mass
    cells[:, :25]=grid.size + np.arange(25)%4
    w=rng.dirichlet(np.ones(N))
    return grid,T,ParticleMotion(cells,grid.size,np.arange(N)),w


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--expansions',type=int,default=200)
    ap.add_argument('--output',type=Path,default=Path('outputs/stdc_v0_2/synthetic_bench.json'))
    args=ap.parse_args()
    grid,T,motion,p=synthetic_case()
    start=144
    q=.78
    # Guaranteed legal but intentionally poor warm start, same for all.
    initial=(start,)+tuple(start+1 if i%2==0 else start for i in range(T))
    from asar_repro.objective import score_path
    pt=score_path(grid,initial,start=start,budget=T,p=p,q=q,motion=motion).J
    rows=[]
    for mode in ('mass_lb','reach_lb','capacity_lb','stepwise_lb','stdc_radius_lb','stdc_lb'):
        est=Heuristic(grid,budget=T,q=q,motion=motion,mode=mode)
        tic=perf_counter()
        root_h=est(start,0,p)
        root_s=perf_counter()-tic
        tic=perf_counter()
        run=search_asar(grid,start=start,budget=T,p=p,q=q,motion=motion,heuristic=mode,
                        epsilon=1.10,initial_path=initial,max_expansions=args.expansions,
                        max_open=5000,max_seconds=20)
        elapsed=perf_counter()-tic
        rows.append(dict(mode=mode,root_h=root_h,root_eval_ms=root_s*1000,
                         J=run.J,source=run.incumbent_source,status=run.status,
                         reason=run.stop_reason,expanded=run.expanded,generated=run.generated,
                         time_s=elapsed,certified=run.theory_certified))
        print(f'{mode:<17} root_h={root_h:8.4f} h_ms={root_s*1e3:7.2f} '
              f'expanded={run.expanded:4d} wall_s={elapsed:6.3f} '
              f'J={run.J:.4f} status={run.status}',flush=True)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(dict(synthetic_only=True,seed=20261123,grid=[17,17],
               particle_count=500,budget=49,initial_J=pt,expansion_cap=args.expansions,
               results=rows),indent=2),encoding='utf8')

if __name__=='__main__':
    main()
