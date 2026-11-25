"""Bounded diagnosis beyond prior local radius; not a same-budget benchmark."""
from audit_exact_windows import *

def main():
    print('larger-window diagnostic started',flush=True)
    protocol=read(OLD/'experiment/protocol.json');before=sources();assert before==read(OLD/'freeze.json')['source_sha256']
    summary=[]
    for scene in SCENES:
        print('loading',scene,flush=True)
        grid,cfg,rec=load_case(scene);assert rec==protocol['scenarios'][scene]
        path=read(OLD/'benchmark'/f'{scene}_prior_stdc_work_r0/raw_result.json')['result']['path']
        rows=[];tic=time.perf_counter();reason=None
        for length in (10,12):
            for a in range(cfg['budget']-length+1):
                if a%10==0:print(scene,length,a,'elapsed',time.perf_counter()-tic,flush=True)
                remain=90-(time.perf_counter()-tic)
                if remain<=0:reason='diagnostic_90_second_cap';break
                try:r=enumerate_window(grid,cfg,path,a,a+length,timeout=remain)
                except TimeoutError:
                    reason='diagnostic_90_second_cap';break
                rows.append(r)
                if r['improving_paths']:
                    print(scene,'IMPROVEMENT',a,a+length,r['best_J'],r['best_Pd'],flush=True)
            if reason:break
            print(scene,'finished length',length,'windows',len(rows),flush=True)
        result=dict(scene=scene,particle_sha256=rec['particle_sha256'],physical_direction_unverified=rec['physical_direction_unverified'],
            status='budget_exceeded' if reason else 'exhausted',stop_reason=reason,diagnostic_budget_s=90,wall_s=time.perf_counter()-tic,
            baseline_J=rows[0]['baseline_J'],windows=rows,scope='single fixed-endpoint length10/12 windows on fixed direct STDC; no claim of global optimality or equal-budget performance')
        save(HERE/(scene+'_larger.json'),result)
        summary.append(dict(scene=scene,status=result['status'],stop_reason=reason,wall_s=result['wall_s'],windows=len(rows),
            enumerated_paths=sum(x['paths'] for x in rows),improving_windows=sum(x['improving_paths']>0 for x in rows),
            baseline_J=rows[0]['baseline_J'],best=min(rows,key=lambda r:r['best_J'])))
        save(HERE/'larger_summary.json',dict(scenes=summary,theory_certified=False))
        print(scene,result['status'],'best',summary[-1]['best']['best_J'],'elapsed',result['wall_s'],flush=True)
    assert sources()==before

if __name__=='__main__':main()
