"""Long repeated sensing regression; no production/source edits."""
import json
from dataclasses import asdict
from pathlib import Path
import numpy as np
from asar_repro.grid import GridGraph
from asar_repro.motion import ParticleMotion
from asar_repro.exact_repair import solve_exact_repair

rows=[]
for T in (49,60):
    grid=GridGraph(1,2)
    motion=ParticleMotion(np.ones((T+1,1),dtype=int),2,np.array([9]))
    result=solve_exact_repair(grid,start=0,budget=T,p=np.array([1.]),q=.78,
        motion=motion,initial_path=tuple(t%2 for t in range(T+1)))
    rows.append(asdict(result))
    assert result.status=='completed',asdict(result)
    assert result.stats['model_replay_error']<=1e-10
Path(__file__).with_name('long_toy_passed.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
print('2 long q=.78 cases passed, no tolerance relaxation')
