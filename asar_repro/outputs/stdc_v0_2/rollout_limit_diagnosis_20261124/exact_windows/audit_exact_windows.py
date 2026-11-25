"""Independent diagnostic DFS, no planner bounds/beam/dominance; old data read-only."""
import json, hashlib, time
from pathlib import Path
import numpy as np
from run_adaptive_experiments import load_case, SCENES
from run_optimization_validation import sources
from asar_repro.objective import score_path
from asar_repro.grid import GridGraph
from asar_repro.motion import ParticleMotion

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
OLD=ROOT/'outputs/stdc_v0_2/adaptive_20261124'
TOL=1e-10
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def save(p,o):p.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8')

def enumerate_window(grid,cfg,path,a,b,free_end=False,timeout=180.):
    tic=time.perf_counter();T=cfg['budget'];cells=cfg['motion'].cell_ids
    q=np.broadcast_to(cfg['q'],(grid.size,));p=np.array(cfg['p'],dtype=float)
    # Direct particle-factor recurrence, independent of window_bounds or planner.
    w=p.copy();g=0.
    for t in range(1,a+1):
        w[cells[t]==path[t]]*=1-q[path[t]];g+=w.sum()
    tail=np.zeros(len(p));surv=np.ones(len(p))
    for t in range(T,b,-1):
        fac=np.where(cells[t]==path[t],1-q[path[t]],1.)
        tail=fac*(1+tail);surv=fac*surv
    inc=score_path(grid,path,**cfg)
    neighbors=[grid.neighbors(v) for v in range(grid.size)]
    er,ec=divmod(path[b],grid.cols)
    best=[inc.J,inc.pd_final,tuple(path)];count=equal=improving=nodes=0
    maxpd_tie=inc.pd_final;minj_other=float('inf');replay_error=0.
    def dfs(route,weights,cost):
        nonlocal count,equal,improving,nodes,maxpd_tie,minj_other,replay_error
        nodes+=1
        if nodes%8192==0 and time.perf_counter()-tic>timeout:raise TimeoutError('explicit diagnostic cap')
        t=len(route)
        for v in neighbors[route[-1]]:
            if not free_end:
                r,c=divmod(v,grid.cols);d=abs(r-er)+abs(c-ec)
                if d>b-t or (b-t-d)%2:continue
            nw=weights.copy();nw[cells[t]==v]*=1-q[v]
            ng=cost+nw.sum();new=route+(v,)
            if t==b:
                count+=1;J=float(ng+tail@nw);Pd=float(1-surv@nw)
                full=new+tuple(path[b+1:])
                if full!=tuple(path):minj_other=min(minj_other,J)
                if abs(J-inc.J)<=TOL:equal+=1;maxpd_tie=max(maxpd_tie,Pd)
                if J<inc.J-TOL:improving+=1
                if J<best[0]-TOL:
                    replay=score_path(grid,full,**cfg)
                    replay_error=max(replay_error,abs(replay.J-J),abs(replay.pd_final-Pd))
                    assert replay_error<TOL
                    best[:]=[J,Pd,full]
            else:dfs(new,nw,ng)
    dfs(tuple(path[:a+1]),w,g)
    replay=score_path(grid,best[2],**cfg)
    replay_error=max(replay_error,abs(replay.J-best[0]),abs(replay.pd_final-best[1]))
    assert replay_error<TOL
    return dict(a=a,b=b,length=b-a,free_endpoint=free_end,status='exhausted',paths=count,nodes=nodes,
                same_J_paths=equal,improving_paths=improving,baseline_J=inc.J,baseline_Pd=inc.pd_final,
                best_J=best[0],best_Pd=best[1],best_path=best[2],max_Pd_at_incumbent_J=maxpd_tie,
                best_alternative_J=None if np.isinf(minj_other) else minj_other,
                independent_replay_max_error=replay_error,wall_s=time.perf_counter()-tic)

def toy_check():
    rng=np.random.default_rng(1041);rows=[]
    for rep in range(12):
        grid=GridGraph(3,3);T=6;N=7;cells=rng.integers(0,9,(T+1,N))
        cfg=dict(start=4,budget=T,p=np.ones(N)/N,q=.78,motion=ParticleMotion(cells,9,np.arange(N)))
        path=[4]
        for t in range(T):path.append(int(rng.choice(grid.neighbors(path[-1]))))
        a,b=1,5;r=enumerate_window(grid,cfg,path,a,b)
        vals=[]
        def slow(seq):
            if len(seq)==b+1:
                if seq[-1]==path[b]:vals.append(score_path(grid,seq+path[b+1:],**cfg).J)
                return
            for v in grid.neighbors(seq[-1]):slow(seq+[v])
        slow(path[:a+1])
        assert r['paths']==len(vals) and abs(r['best_J']-min(vals))<TOL
        rows.append(dict(rep=rep,paths=len(vals),max_error=abs(r['best_J']-min(vals))))
    return dict(seed=1041,cases=rows,status='passed')

def main():
    save(HERE/'toy_validation.json',toy_check())
    before=sources();assert before==read(OLD/'freeze.json')['source_sha256']
    protocol=read(OLD/'experiment/protocol.json');summary=[]
    for scene in SCENES:
        grid,cfg,rec=load_case(scene);assert rec==protocol['scenarios'][scene]
        path=read(OLD/'benchmark'/f'{scene}_prior_stdc_work_r0/raw_result.json')['result']['path']
        rows=[];tic=time.perf_counter()
        for length in (4,6,8):
            for a in range(cfg['budget']-length+1):
                row=enumerate_window(grid,cfg,path,a,a+length);rows.append(row)
            print(scene,'length',length,'windows',len(rows),'improving',sum(x['improving_paths'] for x in rows),flush=True)
        # Terminal endpoint is not constrained by the mission; inspect the last 8 moves freely.
        tail=enumerate_window(grid,cfg,path,cfg['budget']-8,cfg['budget'],free_end=True)
        result=dict(scene=scene,seed=41,particle_sha256=rec['particle_sha256'],
            physical_direction_unverified=rec['physical_direction_unverified'],status='passed',
            scope='all single fixed-endpoint windows length4/6/8 around frozen direct STDC; one free terminal8; not global proof, not same-budget benchmark',
            windows=rows,free_terminal8=tail,wall_s=time.perf_counter()-tic)
        save(HERE/(scene+'.json'),result)
        summary.append(dict(scene=scene,windows=len(rows),enumerated_paths=sum(x['paths'] for x in rows),
            improving_windows=sum(x['improving_paths']>0 for x in rows),improving_paths=sum(x['improving_paths'] for x in rows),
            equal_J_paths=sum(x['same_J_paths'] for x in rows),baseline_J=rows[0]['baseline_J'],
            best_J=min(x['best_J'] for x in rows),max_Pd_at_same_J=max(x['max_Pd_at_incumbent_J'] for x in rows),
            free_terminal8_best_J=tail['best_J'],free_terminal8_best_Pd=tail['best_Pd'],free_terminal8_paths=tail['paths'],
            wall_s=result['wall_s']))
        print(summary[-1],flush=True)
    assert sources()==before
    save(HERE/'summary.json',dict(status='passed',scenes=summary,source_preservation=True,theory_certified=False))

if __name__=='__main__':main()
