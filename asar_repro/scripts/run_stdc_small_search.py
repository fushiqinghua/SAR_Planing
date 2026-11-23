"""Compare Weighted A* with different admissible heuristics on finite small cases.

This measures end-to-end expansion counts and wall time on identical small
instances while independently checking all paths against the DFS oracle.
Use statistical interpretation: timings depend on hardware and load.
"""
import argparse
import json
from pathlib import Path
from time import perf_counter
from collections import defaultdict
import numpy as np
from asar_repro.grid import GridGraph
from asar_repro.motion import MatrixMotion
from asar_repro.search import search_asar
from asar_repro.oracle import enumerate_oracle


def case(seed):
    rng=np.random.default_rng(seed)
    grid=GridGraph(2,3) if seed%2 else GridGraph(3,3)
    T=5
    p=rng.dirichlet(np.ones(grid.size))
    q=rng.uniform(.25,.95,size=grid.size)
    mats=[]
    for _ in range(T):
        P=np.zeros((grid.size,grid.size))
        for i in range(grid.size):
            nodes=(i,*grid.neighbors(i))
            P[i,list(nodes)]=rng.dirichlet(np.ones(len(nodes)))
        mats.append(P)
    return grid,dict(start=grid.size//2,budget=T,p=p,q=q,motion=MatrixMotion.time_varying(mats))


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--cases',type=int,default=35)
    ap.add_argument('--seed-start',type=int,default=15000)
    ap.add_argument('--output',type=Path,default=Path('outputs/stdc_v0_2/small_search.json'))
    args=ap.parse_args()
    modes=('zero','mass_lb','reach_lb','capacity_lb','stepwise_lb','stdc_radius_lb','stdc_lb')
    rows=[]
    for seed in range(args.seed_start,args.seed_start+args.cases):
        grid,cfg=case(seed)
        exact=enumerate_oracle(grid,**cfg).J
        for epsilon in (1.,1.1):
            for mode in modes:
                t0=perf_counter()
                res=search_asar(grid,**cfg,epsilon=epsilon,heuristic=mode)
                elapsed=perf_counter()-t0
                assert res.status=='completed' and res.theory_certified
                assert res.J <= epsilon*exact+1e-10,(seed,mode,epsilon,res.J,exact)
                rows.append(dict(seed=seed,epsilon=epsilon,mode=mode,
                                 J=res.J,oracle=exact,expanded=res.expanded,
                                 time_s=elapsed))
    aggregates=[]
    for eps in (1.,1.1):
        for mode in modes:
            dat=[r for r in rows if r['mode']==mode and r['epsilon']==eps]
            aggregates.append(dict(mode=mode,epsilon=eps,cases=len(dat),
                 expanded_mean=float(np.mean([r['expanded'] for r in dat])),
                 expanded_median=float(np.median([r['expanded'] for r in dat])),
                 time_ms_mean=1000*float(np.mean([r['time_s'] for r in dat])),
                 relative_cost_mean=float(np.mean([r['J']/r['oracle'] for r in dat]))))
    result=dict(cases=args.cases,seed_start=args.seed_start,rows=rows,aggregate=aggregates)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2),encoding='utf8')
    for item in aggregates:
        print(f"eps={item['epsilon']:3.1f} {item['mode']:<17} "
              f"expanded_mean={item['expanded_mean']:7.2f} "
              f"mean_ms={item['time_ms_mean']:7.2f} J/Oracle={item['relative_cost_mean']:.4f}")

if __name__=='__main__':main()
