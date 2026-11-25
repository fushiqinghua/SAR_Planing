"""Read-only root-bound diagnostic; no planner run or archive mutation."""
import json
import hashlib
from pathlib import Path
from time import perf_counter
from statistics import median
from run_adaptive_experiments import load_case
from stdc_validation_guards import ROOT
from asar_repro.heuristic import Heuristic
from asar_repro.compact_particle_dp import CompactParticleDP

OUT=Path(__file__).resolve().parent
SOURCE=ROOT/'outputs/stdc_v0_2/adaptive_20261124/benchmark/results.json'
rows=json.loads(SOURCE.read_text(encoding='utf-8'))['rows']
result={'new_searches':0,'new_opendrift_runs':0,'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'scenes':{}}
for scene in ('lake_ontario','arctic_ocean','bay_of_fundy'):
    grid,cfg,rec=load_case(scene) # existing original input SHA gates
    direct=[r for r in rows if r['scenario']==scene and r['variant']=='prior_stdc']
    U=min(r['J'] for r in direct)
    h=Heuristic(grid,budget=cfg['budget'],q=cfg['q'],motion=cfg['motion'],mode='stdc_lb')
    root_stdc=float(h(cfg['start'],0,cfg['p']))
    tic=perf_counter()
    dp=CompactParticleDP(grid,start=cfg['start'],budget=cfg['budget'],q=cfg['q'],motion=cfg['motion'],max_memory_bytes=128*2**20)
    assert dp.ready
    root_dp=float(dp(cfg['start'],0,cfg['p']))
    L=max(root_stdc,root_dp)
    assert L <= U+1e-10
    profiles=[]
    for cap in ('work','wall'):
        for variant in ('prior_stdc','compact_dp','adaptive_combo'):
            rr=[r for r in rows if (r['scenario'],r['variant'],r['protocol'])==(scene,variant,cap)]
            profiles.append({'variant':variant,'cap':cap,'J_median':median(r['J'] for r in rr),'Pd_median':median(r['Pd_T'] for r in rr),'expanded_median':median(r['work_expanded'] for r in rr),'frontier_remaining':[r.get('stats',{}).get('frontier_remaining') for r in rr],'stop_reasons':[r['stop_reason'] for r in rr],'certificate_fields':[{k:v for k,v in r.items() if 'bound' in k or 'gap' in k or 'certif' in k} for r in rr]})
    result['scenes'][scene]={'particle_sha256':rec['particle_sha256'],'physical_direction_unverified':rec['physical_direction_unverified'],'U_best_direct_STDC':U,'root_stdc_lower_bound':root_stdc,'root_particle_dp_lower_bound':root_dp,'L_root_max':L,'uncertainty_U_minus_L':U-L,'uncertainty_fraction_of_U':(U-L)/U,'relative_suboptimality_upper_bound_U_over_L_minus_one':U/L-1 if L>0 else None,'root_bound_evaluation_wall_s':perf_counter()-tic,'dp_build':dp.build_info,'profiles':profiles}
    print(scene, U, root_stdc, root_dp, (U-L)/U, flush=True)
    del dp
result['interpretation']={
 'bounds':'Model-conditional floating numerical root bounds, tested in earlier toy audits. No verified outward-rounded global bound or frontier minimum is produced here.',
 'gap':'Large U-L is uncertainty, not evidence that a better feasible route exists.',
 'frontier':'Current saved result stores counts and timing, not remaining path-dependent states/min admissible f. Heap priority uses weighted paper guide and cannot substitute for min admissible f.',
 'J_Pd':'J=sum(M_t,t=1..T); Pd=1-M_T. Lower J alone need not improve terminal Pd.',
 'future_test':'Exhaustively solve tiny fixed-window bridge neighborhoods and release endpoint/suffix one restriction at a time, warm starting the same incumbent and charging diagnostic effort separately. Only full-tree bounds establish global near-optimality.'}
(OUT/'bounds.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
