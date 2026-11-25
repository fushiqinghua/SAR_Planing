"""Three warm-start/cutoff ablations against the unchanged independent DFS."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
from time import perf_counter
import traceback
from audit_exact_repair import (SEEDS,ATOL,ROOT,native,save,toy_case,
                               independent_dfs,check_completed)
from asar_repro.exact_repair import solve_exact_repair


def main(out):
    out.mkdir(parents=True,exist_ok=False)
    save(out/'command.json',dict(command=[sys.executable,*sys.argv],cwd=str(ROOT),
        seeds=SEEDS,data_type='synthetic_toy',atol=ATOL,global_epsilon_certified=False))
    begun=perf_counter();rows=[];enumerated=0
    try:
        for seed in SEEDS:
            grid,cfg,path=toy_case(seed)
            settings=((0,None),(cfg['budget']//2,None),(cfg['budget']//2,0),(cfg['budget'],1))
            for prefix,radius in settings:
                exact=independent_dfs(grid,cfg,path,prefix,radius);enumerated+=exact['complete_paths']
                for warm,cut in ((False,True),(True,False),(True,True)):
                    current=dict(seed=seed,prefix_depth=prefix,corridor_radius=radius,warm_start=warm,objective_cutoff=cut)
                    save(out/'last_checked.json',current)
                    r=solve_exact_repair(grid,**cfg,initial_path=path,prefix_depth=prefix,
                        corridor_radius=radius,warm_start=warm,objective_cutoff=cut,max_seconds=30.)
                    row=dict(current,oracle=exact,result=asdict(r))
                    save(out/'last_checked.json',row)
                    row.update(check_completed(r,grid,cfg,path,prefix,radius,exact))
                    if warm and prefix<cfg['budget']:
                        assert r.stats['mip_start_roundtrip_verified'],'native start missing'
                    if cut and prefix<cfg['budget']:
                        assert r.stats['candidate_J']<=r.stats['initial_J']+ATOL,'cutoff excluded or exceeded'
                    rows.append(row)
                    with (out/'cases.jsonl').open('a',encoding='utf-8') as f:
                        f.write(json.dumps(native(row),ensure_ascii=False,allow_nan=False)+'\n')
            if (seed-SEEDS[0]+1)%8==0:print('seeds',seed-SEEDS[0]+1,'checks',len(rows),flush=True)
        save(out/'summary.json',dict(status='passed',repair_checks=len(rows),synthetic_cases=len(SEEDS),
            complete_path_evaluations=enumerated,max_objective_error=max(r['objective_error'] for r in rows),
            max_replay_error=max(r['replay_error'] for r in rows),
            max_bound_overestimate=max(r['bound_overestimate'] for r in rows),violations=0,
            wall_s=perf_counter()-begun,global_epsilon_certified=False))
        print('warm Oracle passed',len(rows),flush=True)
    except BaseException:
        save(out/'summary.json',dict(status='blocked',completed_repairs=len(rows),error=traceback.format_exc()))
        raise


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output-dir',type=Path,required=True)
    main(p.parse_args().output_dir.resolve())
