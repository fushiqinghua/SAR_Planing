"""SHA-gated independent real-input diagnostic, before planning implementation."""
import argparse
from dataclasses import asdict
from pathlib import Path
import sys
from time import perf_counter
import traceback

from asar_repro.objective import score_path
from asar_repro.heuristic import Heuristic
from asar_repro.particle_diagnostic import solve_diagnostic
from asar_repro.research_particle import FutureEquivalentMotion
from run_anytime_experiments import validation_gate
from run_optimization_validation import snapshot, preserve
from stdc_validation_guards import ROOT, PARTICLE_SHA, PROTOCOL_SHA, load_real, read, save, digest, require


def run(folder, validation):
    folder.mkdir(parents=True,exist_ok=False)
    result=dict(status='running',command=[sys.executable,*sys.argv],particle_seed=41,
                theory_certified=False,data_type='historical_real',target_J=17.264874448)
    try:
        result['validation']=validation_gate(validation)
        result['preservation_before']=preserve(validation.parent)
        snapshot(folder,validation.parent)
        started=perf_counter()
        protocol,grid,cfg,pt,times,raw=load_real()
        best_path=ROOT/'outputs/stdc_v0_2/optimization_20261124_resume/benchmark/anytime_reference_work_r0/result.json'
        archived=read(best_path);best=score_path(grid,archived['path'],**cfg)
        require(abs(best.J-17.264874448)<=1e-10,'archived best changed')
        grouped=FutureEquivalentMotion(cfg['motion'],cfg['p'])
        packed=dict(cfg,p=grouped.initial_weights,motion=grouped)
        prep=perf_counter()-started
        diagnostic=solve_diagnostic(grid,**packed,method='lp',max_seconds=30,
                                     initial_path=archived['path'])
        require(diagnostic.status in ('completed','budget_exhausted'),'real diagnostic solver error')
        require(diagnostic.lower_bound<=best.J+1e-10,'real lower bound exceeds incumbent')
        stdc=Heuristic(grid,budget=cfg['budget'],q=cfg['q'],motion=cfg['motion'],mode='stdc_lb')
        stdc_lb=stdc(cfg['start'],0,cfg['p'])
        require(stdc_lb<=best.J+1e-10,'STDC root bound exceeds incumbent')
        result.update(status='passed',diagnostic=asdict(diagnostic),root_stdc_lb=stdc_lb,
            independent_lp_lb=diagnostic.lower_bound,usable_combined_lb=max(stdc_lb,diagnostic.lower_bound),
            upper_bound_J=best.J,upper_bound_Pd=best.pd_final,
            upper_bound_source=dict(path=str(best_path),sha256=digest(best_path),
                use='diagnostic upper bound only; forbidden free warm start in benchmark'),
            remaining_gap=best.J-max(stdc_lb,diagnostic.lower_bound),
            interpretation='A nonzero relaxation gap is uncertainty, not proof of a better feasible route.',
            preprocessing_s=prep,particle_sha256=PARTICLE_SHA,protocol_sha256=PROTOCOL_SHA,
            verified_raw_sources=raw,absolute_utc=[str(t)+'Z' for t in times],
            compression=grouped.compression_stats,preservation_after=preserve(validation.parent))
    except Exception as exc:
        result.update(status='blocked',error=str(exc),traceback=traceback.format_exc())
    save(folder/'result.json',result)
    print({k:result.get(k) for k in ('status','independent_lp_lb','root_stdc_lb','upper_bound_J','remaining_gap','error')},flush=True)
    return 0 if result['status']=='passed' else 2


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir',required=True,type=Path)
    p.add_argument('--validation',required=True,type=Path)
    args=p.parse_args()
    sys.exit(run(args.output_dir.resolve(),args.validation.resolve()))
