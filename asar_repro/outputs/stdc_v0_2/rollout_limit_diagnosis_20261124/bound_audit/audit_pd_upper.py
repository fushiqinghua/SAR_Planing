"""Independent reachability-opportunity Pd upper bound; no path search."""
import json
from pathlib import Path
from collections import Counter
import numpy as np
from run_adaptive_experiments import load_case
from stdc_validation_guards import ROOT

OUT=Path(__file__).resolve().parent
rows=json.loads((ROOT/'outputs/stdc_v0_2/adaptive_20261124/benchmark/results.json').read_text(encoding='utf-8'))['rows']
output={'model':'fixed archived particles; four-connected rectangular grid, no wait; absolute t=1..T sensing; q=.78','new_searches':0,'scenes':{},'interpretation':'Optimistic simultaneous detection of every CSP-reachable particle/time event. Ignores both one-common-route coupling and compatibility of successive reachable detections. An upper bound on final Pd only, not an achievable improvement, not a J bound or epsilon guarantee.'}
for name in ('lake_ontario','arctic_ocean','bay_of_fundy'):
    grid,cfg,rec=load_case(name)
    cells=cfg['motion'].cell_ids[1:cfg['budget']+1]
    p=np.asarray(cfg['p'],dtype=float)
    assert np.all(np.asarray(cfg['q'])==.78)
    assert abs(p.sum()-1)<1e-10
    row,col=grid.coordinates(cfg['start'])
    special=cells>=grid.size
    distance=np.abs(cells//grid.cols-row)+np.abs(cells%grid.cols-col)
    times=np.arange(1,cfg['budget']+1)[:,None]
    reachable=(~special)&(distance<=times)&((times-distance)%2==0)
    counts=reachable.sum(axis=0)
    upper=float(p@(1-.22**counts))
    direct=[r for r in rows if r['scenario']==name and r['variant']=='prior_stdc']
    current=min(direct,key=lambda r:r['J'])
    # Independent replay opportunity count dominates actual hits for every saved route.
    max_violation=0.
    for r in [r for r in rows if r['scenario']==name]:
        actual=(cells==np.asarray(r['path'][1:])[:,None]).sum(axis=0)
        assert np.all(actual<=counts)
        actual_pd=float(p@(1-.22**actual))
        assert abs(actual_pd-r['Pd_T'])<1e-10
        max_violation=max(max_violation,actual_pd-upper)
    output['scenes'][name]={'particle_sha256':rec['particle_sha256'],'physical_direction_unverified':rec['physical_direction_unverified'],'T':cfg['budget'],'N':len(p),'current_STDC_J':current['J'],'current_STDC_Pd':current['Pd_T'],'Pd_optimistic_upper':upper,'upper_minus_current_percentage_points':100*(upper-current['Pd_T']),'never_reachable_mass':float(p[counts==0].sum()),'never_reachable_particles':int((counts==0).sum()),'always_special_mass':float(p[np.all(special,axis=0)].sum()),'never_reachable_with_at_least_one_searchable_frame_mass':float(p[(counts==0)&~np.all(special,axis=0)].sum()),'opportunity_count_histogram':dict(Counter(map(int,counts))),'per_particle_opportunity_counts':counts.tolist(),'actual_path_Pd_checks':60,'max_upper_violation':max_violation}
    print(name, 'Pd_upper=',upper,'current=',current['Pd_T'],'delta_pp=',100*(upper-current['Pd_T']),'unreachable_mass=',p[counts==0].sum(),flush=True)
(OUT/'pd_upper.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
