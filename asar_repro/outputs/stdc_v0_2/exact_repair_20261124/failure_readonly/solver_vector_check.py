"""Read-only failure analysis: intercept builder, NEVER call an optimizer/search."""
import hashlib, inspect, json
from pathlib import Path
from unittest.mock import patch
import numpy as np
from asar_repro.grid import GridGraph
from asar_repro.motion import ParticleMotion
from asar_repro.objective import score_path
import asar_repro.exact_repair as module

ROOT=Path(__file__).resolve().parents[4]
HERE=Path(__file__).resolve().parent
AUDIT=HERE.parent/'oracle/audit'
frozen_source=ROOT/'src/asar_repro/exact_repair.py'
before=hashlib.sha256(frozen_source.read_bytes()).hexdigest()
inp=json.loads((AUDIT/'input_1059.json').read_text(encoding='utf-8'))
failed=json.loads((AUDIT/'last_checked.json').read_text(encoding='utf-8'))
grid=GridGraph(inp['rows'],inp['cols'])
cfg=dict(start=inp['start'],budget=inp['budget'],p=np.array(inp['p']),q=np.array(inp['q']),
         motion=ParticleMotion(np.array(inp['cell_ids']),grid.size,np.array(inp['trajectory_ids'])))
records=[]
def capture(c,*,integrality,bounds,constraints,options):
    frame=inspect.currentframe().f_back
    local=frame.f_locals
    A=constraints.A
    xindex=local['x_index'];groups=local['groups'];X=local['X'];offset=local['offset']
    for label,path in [('oracle_saved',failed['oracle']['path']),
                       ('solver_saved',failed['result']['stats']['candidate_path']),
                       ('initial_saved',inp['initial_path'])]:
        x=np.zeros(len(c));nextvar=X
        for t,indices in xindex.items():x[indices[path[t]]]=1.
        for weight,events in groups:
            residual=1.
            for j,(t,v,q) in enumerate(events):
                detected=residual*float(path[t]==v)
                new=residual-q*detected
                x[nextvar]=new;nextvar+=1
                if j:
                    x[nextvar]=detected;nextvar+=1
                residual=new
        activity=np.asarray(A@x)
        violations=np.maximum(constraints.lb-activity,0)+np.maximum(activity-constraints.ub,0)
        replay=score_path(grid,path,**cfg)
        records.append(dict(label=label,path=path,vector=x.tolist(),activity=activity.tolist(),
            max_row_violation=float(violations.max(initial=0)),
            max_bound_violation=max(float(np.maximum(bounds.lb-x,0).max(initial=0)),float(np.maximum(x-bounds.ub,0).max(initial=0))),
            max_integrality_error=float(np.abs(x[integrality==1]-np.rint(x[integrality==1])).max(initial=0)),
            model_objective=float(c@x+offset),replayed_J=replay.J,replayed_Pd=replay.pd_final,
            gap_from_reported_dual=float(failed['result']['restricted_lower_bound']-replay.J)))
    out=dict(status='readonly_analysis_completed',optimizer_calls=0,new_path_searches=0,
        source_sha256=before,seed=1059,variables=len(c),matrix=A.toarray().tolist(),
        c=c.tolist(),constant=offset,row_lower=constraints.lb.tolist(),row_upper=constraints.ub.tolist(),
        variable_lower=bounds.lb.tolist(),variable_upper=bounds.ub.tolist(),integrality=integrality.tolist(),
        grouped_events=[dict(prefix_mass=w,events=events) for w,events in groups],
        position_index={str(t):{str(v):i for v,i in entries.items()} for t,entries in xindex.items()},
        recorded_solver_options=options,records=records,
        confirmed='Saved Oracle path is directly evaluated in frozen model; see row/variable/integrality residuals.',
        not_established='No solver rerun, option ablation or independent solver; presolve/native backend cause not established.')
    (HERE/'solver_vector_check.json').write_text(json.dumps(out,indent=2),encoding='utf-8')
    raise RuntimeError('INTENTIONAL INTERCEPT: optimizer invocation prohibited in this read-only analysis')

with patch.object(module,'milp',capture):
    result=module.solve_exact_repair(grid,**cfg,initial_path=inp['initial_path'],prefix_depth=3,corridor_radius=0,max_seconds=30.)
assert result.status=='blocked' and 'INTENTIONAL INTERCEPT' in result.stats['exception']
assert hashlib.sha256(frozen_source.read_bytes()).hexdigest()==before
print(json.dumps(records,indent=2))
