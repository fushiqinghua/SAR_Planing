import json
from dataclasses import asdict
from pathlib import Path
import numpy as np
from asar_repro.grid import GridGraph
from asar_repro.motion import ParticleMotion
from asar_repro.exact_repair import solve_exact_repair

rng=np.random.default_rng(728)
grid=GridGraph(3,3); T=10; N=20
motion=ParticleMotion(rng.integers(0,9,(T+1,N)),9,np.arange(N))
path=[4]
for _ in range(T):path.append(int(rng.choice(grid.neighbors(path[-1]))))
rows=[]
for cap in (1,2):
    result=solve_exact_repair(grid,start=4,budget=T,p=np.ones(N)/N,q=.78,
        motion=motion,initial_path=path,node_limit=cap)
    rows.append(asdict(result))
    print(cap,result.status,result.stop_reason,result.solver_status,result.solver_message,flush=True)
Path(__file__).with_name('positive_node_caps.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
