"""Independent full-path Oracle audit over frozen-seed random small problems.

Run in an installed / PYTHONPATH-enabled asar_repro checkout.
Produces one JSON with exact sampled inputs, prefix counts and bound statistics.
No external historical forcing required.
"""
import argparse
import json
from pathlib import Path
from time import perf_counter

import numpy as np

from asar_repro.grid import GridGraph
from asar_repro.heuristic import Heuristic
from asar_repro.motion import MatrixMotion, ParticleMotion
from asar_repro.objective import score_path
from asar_repro.oracle import enumerate_oracle


def paths_prefixes(grid, v, T):
    todo = [(v,)]
    while todo:
        path = todo.pop()
        yield path
        if len(path) <= T:
            todo.extend(path+(next_v,) for next_v in grid.neighbors(path[-1]))


def make_case(seed, motion_kind):
    rng = np.random.default_rng(seed)
    rows, cols = [(2,2),(2,3),(3,3)][seed%3]
    T = 3 + seed%3
    grid = GridGraph(rows, cols)
    start = (seed//3) % grid.size
    q = rng.uniform(.05, .99, grid.size)
    if seed%13 == 0: q[:]=1.
    elif seed%19 == 0: q[:]=0.
    if motion_kind == 'matrix':
        p = rng.dirichlet(np.ones(grid.size))
        mats = []
        for t in range(T):
            P=np.zeros((grid.size,grid.size))
            for i in range(grid.size):
                targets=(i,*grid.neighbors(i))
                P[i,list(targets)] = rng.dirichlet(np.full(len(targets), .8))
            mats.append(P)
        motion=MatrixMotion.time_varying(mats)
        if seed%7 == 0:
            motion=MatrixMotion.identity(grid.size)
    else:
        N=8+seed%13
        cells = np.zeros((T+1,N),dtype=np.int64)
        cells[0]=rng.integers(0,grid.size+4,size=N)
        for t in range(1,T+1):
            for j,prev in enumerate(cells[t-1]):
                options=(prev,*grid.neighbors(int(prev))) if prev<grid.size else (prev,)
                cells[t,j]=rng.choice(options)
        cells[:,0]=grid.size+3  # always-special, never searchable
        motion=ParticleMotion(cells,grid.size,np.arange(N)+seed*100)
        p=rng.dirichlet(np.ones(N))
    return grid,start,T,p,q,motion


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--cases-per-kind',type=int,default=45)
    parser.add_argument('--seed-start',type=int,default=100)
    parser.add_argument('--output',type=Path,default=Path('outputs/stdc_v0_2/random_audit.json'))
    args=parser.parse_args()
    modes=('mass_lb','reach_lb','capacity_lb','stepwise_lb','stdc_lb','stdc_radius_lb')
    counts={'matrix':0,'particles':0}
    failures=[]
    gaps={mode:[] for mode in modes}
    timings={mode:0.0 for mode in modes}
    roots=[]
    records=0
    max_overrun=-float('inf')
    max_mass_dominance_violation=0.
    started=perf_counter()
    for kind in ('matrix','particles'):
        for index in range(args.cases_per_kind):
            seed=args.seed_start+index
            grid,start,T,p,q,motion=make_case(seed,kind)
            opt=enumerate_oracle(grid,start=start,budget=T,p=p,q=q,motion=motion).J
            estimators={mode:Heuristic(grid,budget=T,q=q,motion=motion,mode=mode) for mode in modes}
            for path in paths_prefixes(grid,start,T):
                d=len(path)-1
                prefix=score_path(grid,path,start=start,budget=d,p=p,q=q,motion=motion)
                best=enumerate_oracle(grid,start=start,budget=T,p=p,q=q,motion=motion,prefix=path)
                oracle=best.J-prefix.J
                h={}
                for mode,estimate in estimators.items():
                    tic=perf_counter()
                    h[mode]=estimate(path[-1],d,prefix.final_belief)
                    timings[mode]+=perf_counter()-tic
                    if h[mode]-oracle>1e-10 or h[mode]<-1e-10:
                        failures.append(dict(kind=kind,seed=seed,path=list(path),mode=mode,
                                             h=h[mode],oracle=oracle))
                    max_overrun=max(max_overrun,h[mode]-oracle)
                    if d==0 and oracle>1e-10:
                        gaps[mode].append(h[mode]/oracle)
                max_mass_dominance_violation=max(max_mass_dominance_violation,
                             h['mass_lb']-h['stdc_lb'])
                if h['stdc_lb']+1e-10<h['stdc_radius_lb'] or \
                   h['stdc_lb']+1e-10<h['stepwise_lb']:
                    failures.append(dict(kind=kind,seed=seed,path=list(path),mode='dominance',values=h))
                records+=1
            roots.append(dict(kind=kind,seed=seed,T=T,grid=[grid.rows,grid.cols],
                              oracle=opt,values={m:estimators[m](start,0,p) for m in modes}))
            counts[kind]+=1
    result=dict(scenario_counts=counts,prefix_evaluations=records,
                positive_overestimation=max(0.,max_overrun),
                mass_dominance_violation=max_mass_dominance_violation,
                violations=len(failures),failures=failures[:10],
                root_h_over_opt_mean={m:float(np.mean(v)) for m,v in gaps.items()},
                root_h_over_opt_median={m:float(np.median(v)) for m,v in gaps.items()},
                heuristic_time_s=timings, total_wall_s=perf_counter()-started,
                roots=roots)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('roots','failures')},indent=2))
    if failures:
        raise AssertionError('STDC lower bound/monotonicity counterexample; see output')

if __name__=='__main__':
    main()
