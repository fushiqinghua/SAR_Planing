"""Controlled reproduction of the already-known blocked model; no real inputs."""
import argparse,json,hashlib,subprocess,sys,shutil,warnings
from pathlib import Path
from time import perf_counter
import numpy as np
from scipy.optimize import milp,Bounds,LinearConstraint
from scipy.sparse import csc_array
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
OLD=ROOT/'outputs/stdc_v0_2/exact_repair_20261124'
MODEL=OLD/'failure_readonly/solver_vector_check.json'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
BASE=dict(time_limit=30.,mip_rel_gap=0.,presolve=True,disp=True,threads=1,random_seed=0)
STRICT=dict(BASE,mip_abs_gap=0.,mip_feasibility_tolerance=1e-10,primal_feasibility_tolerance=1e-10,
    dual_feasibility_tolerance=1e-10,small_matrix_value=1e-12)
CASES={'strict_on':STRICT,'strict_off':dict(STRICT,presolve=False),
    'default_on':BASE,'default_off':dict(BASE,presolve=False),
    'strict_without_small_value':{k:v for k,v in STRICT.items() if k!='small_matrix_value'},
    'strict_default_feasibility':{k:v for k,v in STRICT.items() if k not in ('mip_feasibility_tolerance','primal_feasibility_tolerance','dual_feasibility_tolerance')}}
def worker(name):
    d=read(MODEL);c=np.array(d['c']);A=csc_array(d['matrix']);offset=d['constant']
    known=next(x for x in d['records'] if x['label']=='oracle_saved')
    t=perf_counter()
    with warnings.catch_warnings(record=True) as logs:
        warnings.simplefilter('always')
        r=milp(c,integrality=np.array(d['integrality']),bounds=Bounds(d['variable_lower'],d['variable_upper']),
            constraints=LinearConstraint(A,d['row_lower'],d['row_upper']),options=CASES[name])
    result=dict(name=name,options=CASES[name],model_sha256=sha(MODEL),wall_s=perf_counter()-t,
        solver_status=int(r.status),message=str(r.message),
        J=None if r.fun is None else float(r.fun)+offset,
        dual=None if getattr(r,'mip_dual_bound',None) is None else float(r.mip_dual_bound)+offset,
        solution=None if r.x is None else r.x.tolist(),mip_nodes=getattr(r,'mip_node_count',None),
        known_feasible_J=known['replayed_J'],warnings=[str(x.message) for x in logs])
    result['matches_known_optimum']=result['J'] is not None and abs(result['J']-known['replayed_J'])<=1e-10
    result['dual_exceeds_known_feasible']=result['dual'] is not None and result['dual']>known['replayed_J']+1e-10
    save(HERE/(name+'.json'),result)
    print(json.dumps(result),flush=True)
def main():
    before=HERE.parent/'source_before';before.mkdir(exist_ok=False)
    files=['src/asar_repro/exact_repair.py','tests/test_exact_repair.py','scripts/audit_exact_repair.py',
        'scripts/run_exact_repair_validation.py','scripts/run_exact_repair_experiments.py','docs/stdc_exact_repair.md']
    records={}
    for n in files:
        target=before/n;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/n,target);records[n]=sha(ROOT/n)
    save(before/'manifest.json',records)
    rows=[]
    for name in CASES:
        cmd=[sys.executable,str(Path(__file__).resolve()),'--case',name]
        save(HERE/(name+'_command.json'),dict(command=cmd,cwd=str(ROOT),seed=1059,solver_seed=0))
        with (HERE/(name+'.stdout.txt')).open('w',encoding='utf-8') as out,(HERE/(name+'.stderr.txt')).open('w',encoding='utf-8') as err:
            r=subprocess.run(cmd,cwd=ROOT,stdout=out,stderr=err,timeout=45)
        assert r.returncode==0,(name,r.returncode)
        row=read(HERE/(name+'.json'));rows.append(row)
        print(name,row['J'],row['dual'],row['matches_known_optimum'],flush=True)
    assert all(sha(ROOT/n)==h for n,h in records.items())
    save(HERE/'summary.json',dict(scope='expected reproduction and controlled diagnosis of known failing toy, no new admissibility gate',
        rows=rows,source_unchanged=True,real_runs=0))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--case',choices=CASES);a=p.parse_args()
    worker(a.case) if a.case else main()
