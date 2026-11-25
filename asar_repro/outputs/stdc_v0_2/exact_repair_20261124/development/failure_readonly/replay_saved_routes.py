"""Read-only failure check. No solver import, no DFS, no optimization calls."""
from pathlib import Path
import hashlib
import json
import sys
import numpy as np
from asar_repro.grid import GridGraph
from asar_repro.motion import ParticleMotion
from asar_repro.objective import score_path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[4]
CASE=ROOT/'outputs/stdc_v0_2/exact_repair_20261124/oracle/audit'
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    inputs=read(CASE/'input_1059.json');failure=read(CASE/'last_checked.json')
    watched=[CASE/'input_1059.json',CASE/'last_checked.json',CASE/'summary.json',
             ROOT/'scripts/audit_exact_repair.py',ROOT/'src/asar_repro/exact_repair.py']
    before={str(p.relative_to(ROOT)):sha(p) for p in watched}
    grid=GridGraph(inputs['rows'],inputs['cols'])
    motion=ParticleMotion(inputs['cell_ids'],grid.size,inputs['trajectory_ids'])
    cfg=dict(start=inputs['start'],budget=inputs['budget'],p=inputs['p'],q=inputs['q'],motion=motion)
    a=failure['prefix_depth'];radius=failure['corridor_radius'];initial=inputs['initial_path']
    centers=[divmod(v,grid.cols) for v in initial[a:]]
    allowed={v for v in range(grid.size) if any(abs(v//grid.cols-r)+abs(v%grid.cols-c)<=radius for r,c in centers)}
    pr,pc=divmod(initial[a],grid.cols)
    layers={t:sorted(v for v in allowed if abs(v//grid.cols-pr)+abs(v%grid.cols-pc)<=t-a
                         and ((t-a)-(abs(v//grid.cols-pr)+abs(v%grid.cols-pc)))%2==0)
            for t in range(a+1,cfg['budget']+1)}
    paths={'oracle_saved':failure['oracle']['path'],
           'returned_milp':failure['result']['path'],
           'raw_solver_candidate':failure['result']['stats']['candidate_path']}
    results={}
    for name,path in paths.items():
        grid.validate_path(path,start=cfg['start'],budget=cfg['budget'])
        assert path[:a+1]==initial[:a+1]
        assert all(path[t] in layers[t] for t in range(a+1,cfg['budget']+1))
        replay=score_path(grid,path,**cfg,record_beliefs=True)
        # Direct ID-weighted arithmetic supplies a second route score, but no
        # alternative route is generated or explored by this script.
        w=np.asarray(inputs['p'],dtype=float).copy();q=np.asarray(inputs['q']);cost=0.;table=[]
        for t in range(1,cfg['budget']+1):
            w[np.asarray(inputs['cell_ids'][t])==path[t]]*=1-q[path[t]]
            cost+=w.sum();table.append(dict(t=t,vertex=path[t],mass=float(w.sum()),weights=w.tolist()))
        assert abs(cost-replay.J)<=1e-10
        assert abs((1-w.sum())-replay.pd_final)<=1e-10
        results[name]=dict(path=path,J=replay.J,Pd=replay.pd_final,legal=True,prefix_preserved=True,
            corridor_and_exact_time_reachability=True,survival=replay.survival.tolist(),step_table=table,
            original_score_vs_direct_weight_error=abs(cost-replay.J))
    expected=failure['oracle']['J'];returned=failure['result']['J']
    assert abs(results['oracle_saved']['J']-expected)<=1e-10
    assert abs(results['returned_milp']['J']-returned)<=1e-10
    assert all(sha(p)==before[str(p.relative_to(ROOT))] for p in watched)
    output=dict(status='confirmed_failure',seed=inputs['seed'],grid=[grid.rows,grid.cols],budget=cfg['budget'],
        prefix_depth=a,corridor_radius=radius,q=inputs['q'],spatial_allowed=sorted(allowed),time_layers=layers,
        source_sha256=before,scope='Read-only replay of three already-saved paths; no solver or search run',
        results=results,objective_difference=returned-expected,
        claimed_lower_bound=failure['result']['restricted_lower_bound'],
        lower_bound_exceeds_known_feasible_oracle_route=failure['result']['restricted_lower_bound']-expected,
        conclusion='Saved Oracle route satisfies identical fixed prefix and radius-zero spatial corridor, and has strictly smaller original J. This is not a domain or evaluator mismatch. Restricted optimality and returned numerical lower bound are contradicted by an already stored feasible route.',
        formal_stage_remains='blocked',modified_formal_inputs=False)
    (HERE/'saved_route_replay.json').write_text(json.dumps(output,indent=2),encoding='utf-8')
    (HERE/'command.json').write_text(json.dumps(dict(command=[sys.executable,*sys.argv],cwd=str(ROOT),
        no_solver_calls=True,no_search_calls=True),indent=2),encoding='utf-8')
    print(json.dumps({k:(r['J'],r['Pd']) for k,r in results.items()}),flush=True)
    print('difference',returned-expected,'formal status blocked',flush=True)

if __name__=='__main__':main()
