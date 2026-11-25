"""SHA-gated restricted MILP diagnostics, explicitly separate from fair benchmarks."""
import argparse
from dataclasses import asdict
from pathlib import Path
import subprocess
import sys
from time import perf_counter,sleep
import traceback
import numpy as np
import psutil
from asar_repro.exact_repair import solve_exact_repair
from asar_repro.objective import score_path
from run_adaptive_experiments import load_case,SCENES
from run_optimization_validation import ROOT,read,save,digest,sources,snapshot,environment,child_environment,require
from run_exact_repair_validation import preserved
from run_anytime_experiments import csv_save,manifest

OLD=ROOT/'outputs/stdc_v0_2/adaptive_20261124'
ATOL=1e-10

def prepare(run):
    require(read(run/'validation_summary.json')['status']=='passed','validation gate not passed')
    require(sources()==read(run/'freeze.json')['source_sha256'],'source changed after validation')
    out=run/'experiment';out.mkdir(exist_ok=False);records={}
    for scene in SCENES:
        grid,cfg,rec=load_case(scene)
        base=OLD/'benchmark'/f'{scene}_prior_stdc_work_r0/raw_result.json'
        baseline=read(base)['result'];path=baseline['path'];score=score_path(grid,path,**cfg)
        require(abs(score.J-baseline['J'])<=ATOL and abs(score.pd_final-baseline['Pd'])<=ATOL,'baseline replay mismatch')
        T=cfg['budget']
        records[scene]=dict(input=rec,baseline_path=path,baseline_J=score.J,baseline_Pd=score.pd_final,
            baseline_result_path=str(base.relative_to(ROOT)),baseline_result_sha256=digest(base),
            stages=[dict(name='late_suffix',prefix_depth=max(0,T-16),corridor_radius=1,seconds=60.),
                    dict(name='long_suffix',prefix_depth=max(0,T-28),corridor_radius=2,seconds=90.),
                    dict(name='early_divergence',prefix_depth=T//3,corridor_radius=3,seconds=150.)])
    save(out/'protocol.json',dict(status='passed',scenarios=records,source_sha256=sources(),
        validation_sha256=digest(run/'validation_summary.json'),environment=environment(),seed=41,
        purpose='independent restricted repair witness search, NOT same-budget performance comparison',
        total_diagnostic_seconds_per_scene=300.,managed_model_limit_bytes=512*2**20,
        native_process_watchdog_bytes=2*2**30,watchdog_time_grace_s=2.,
        stage_unused_budget_reallocated=True,corridor='Manhattan radius around union of supplied incumbent suffix vertices, intersect exact time reachability',
        end_vertex_fixed=False,model='unchanged min J, original scorer, fixed historical forcing and particle archives',
        initial_incumbent_source='frozen prior_stdc_work_r0 formal run; its previous computation is not charged to this diagnostic',
        solver_native_configuration=dict(threads=1,random_seed=0,mip_abs_gap=0.,presolve=False,
            mip_feasibility_tolerance=1e-10,primal_feasibility_tolerance=1e-10,
            dual_feasibility_tolerance=1e-10,small_matrix_value=1e-12),
        fair_runtime_claim=False,global_epsilon_certified=False,preservation=preserved()))
    snapshot(out,run);manifest(out);print('prepare passed',flush=True)

def verify(run,scene):
    protocol=read(run/'experiment/protocol.json');require(sources()==protocol['source_sha256'],'source changed')
    require(digest(run/'validation_summary.json')==protocol['validation_sha256'],'validation changed')
    tic=perf_counter();grid,cfg,rec=load_case(scene);input_s=perf_counter()-tic
    record=protocol['scenarios'][scene];require(rec==record['input'],'input/mission changed')
    require(digest(ROOT/record['baseline_result_path'])==record['baseline_result_sha256'],'baseline result changed')
    return protocol,record,grid,cfg,input_s

def worker(run,out,scene,smoke):
    protocol,record,grid,cfg,input_s=verify(run,scene)
    path=tuple(record['baseline_path']);baseline=score_path(grid,path,**cfg)
    total=8. if smoke else protocol['total_diagnostic_seconds_per_scene']
    plan=[dict(name='tiny_smoke',prefix_depth=cfg['budget']-4,corridor_radius=0,seconds=8.)] if smoke else record['stages']
    rows=[];start=perf_counter()
    save(out/'ready.json',dict(scene=scene,diagnostic_seconds=total,input_verification_s=input_s,baseline_path=path,
        baseline_J=baseline.J,baseline_Pd=baseline.pd_final,physical_direction_unverified=scene=='bay_of_fundy'))
    for i,stage in enumerate(plan):
        remaining=total-(perf_counter()-start)
        if remaining<=0:break
        quota=remaining if i==len(plan)-1 else min(remaining,stage['seconds'])
        folder=out/f'{i:02d}_{stage["name"]}';folder.mkdir()
        save(folder/'before.json',dict(stage=stage,initial_path=path,allocated_seconds=quota,elapsed_s=perf_counter()-start))
        result=solve_exact_repair(grid,**cfg,initial_path=path,prefix_depth=stage['prefix_depth'],
            corridor_radius=stage['corridor_radius'],max_seconds=quota,
            max_memory_bytes=protocol['managed_model_limit_bytes'],mip_rel_gap=0.)
        raw=asdict(result);save(folder/'result.json',raw)
        require(not result.theory_certified,'unexpected global certificate')
        require(result.status not in ('blocked','error','failed'),'solver returned blocked/error: '+str(result.stop_reason))
        score=score_path(grid,result.path,**cfg)
        require(abs(score.J-result.J)<=ATOL and abs(score.pd_final-result.Pd)<=ATOL,'independent replay mismatch')
        current=score_path(grid,path,**cfg);require(score.J<=current.J+ATOL,'incumbent worsened')
        require(tuple(result.path[:stage['prefix_depth']+1])==path[:stage['prefix_depth']+1],'fixed prefix changed')
        mem=psutil.Process().memory_info()
        row=dict(scene=scene,stage=stage['name'],prefix_depth=stage['prefix_depth'],corridor_radius=stage['corridor_radius'],
            J=score.J,Pd=score.pd_final,delta_J=score.J-baseline.J,delta_Pd=score.pd_final-baseline.pd_final,
            improves_J=score.J<baseline.J-ATOL,joint_improvement=score.J<baseline.J-ATOL and score.pd_final>baseline.pd_final+ATOL,
            path=list(result.path),status=result.status,stop_reason=result.stop_reason,incumbent_source=result.incumbent_source,
            restricted_lower_bound=result.restricted_lower_bound,restricted_gap=result.restricted_gap,
            wall_s=result.wall_s,model_build_s=result.model_build_s,solve_s=result.solve_s,
            diagnostic_elapsed_s=perf_counter()-start,process_peak_memory_mib=getattr(mem,'peak_wset',mem.rss)/2**20,
            solver_status=result.solver_status,solver_message=result.solver_message,stats=result.stats,
            physical_direction_unverified=scene=='bay_of_fundy',global_epsilon_certified=False)
        rows.append(row);path=tuple(result.path)
        save(out/'checkpoint.json',dict(status='running',rows=rows,path=path,elapsed_s=perf_counter()-start))
        print(scene,stage['name'],result.status,'J',score.J,'Pd',score.pd_final,flush=True)
    score=score_path(grid,path,**cfg)
    mem=psutil.Process().memory_info()
    save(out/'worker_result.json',dict(status='passed',scene=scene,rows=rows,path=path,J=score.J,Pd=score.pd_final,
        diagnostic_elapsed_s=perf_counter()-start,input_verification_s=input_s,
        process_peak_memory_mib=getattr(mem,'peak_wset',mem.rss)/2**20,
        physical_direction_unverified=scene=='bay_of_fundy',global_epsilon_certified=False))

def run_scene(run,root,scene,smoke):
    folder=root/scene;folder.mkdir();protocol=read(run/'experiment/protocol.json')
    cmd=[sys.executable,str(Path(__file__).resolve()),'worker','--run-dir',str(run),'--output-dir',str(folder),'--scene',scene]
    if smoke:cmd.append('--smoke')
    env=child_environment();save(folder/'command.json',dict(command=cmd,cwd=str(ROOT),seed=41,
        environment={k:env.get(k) for k in ('PYTHONPATH','ASAR_OFFLINE','PROJ_NETWORK','PYTHONDONTWRITEBYTECODE','OMP_NUM_THREADS','OPENBLAS_NUM_THREADS')}))
    peak=0.;reason=None;ready_at=None;start=perf_counter()
    with (folder/'stdout.txt').open('w',encoding='utf-8') as stdout,(folder/'stderr.txt').open('w',encoding='utf-8') as stderr:
        proc=subprocess.Popen(cmd,cwd=ROOT,env=env,stdout=stdout,stderr=stderr)
        monitor=psutil.Process(proc.pid)
        while proc.poll() is None:
            try:
                mem=monitor.memory_info();peak=max(peak,getattr(mem,'peak_wset',mem.rss)/2**20)
                if mem.rss>protocol['native_process_watchdog_bytes']:reason='native_process_memory_watchdog'
            except psutil.NoSuchProcess:pass
            if ready_at is None and (folder/'ready.json').exists():ready_at=perf_counter()
            if ready_at is not None and perf_counter()-ready_at>(8. if smoke else 300.)+protocol['watchdog_time_grace_s']:
                reason=reason or 'external_time_watchdog'
            if ready_at is None and perf_counter()-start>180.:reason=reason or 'input_verification_watchdog'
            if reason:
                proc.kill();proc.wait();break
            sleep(.1)
    meta=dict(exit_code=proc.returncode,external_stop=reason,process_wall_s=perf_counter()-start,
        monitored_peak_mib=peak,ready_observed=ready_at is not None)
    save(folder/'execution.json',meta)
    if reason:
        require(reason!='input_verification_watchdog','input gate not completed')
        cp=read(folder/'checkpoint.json') if (folder/'checkpoint.json').exists() else dict(rows=[],path=protocol['scenarios'][scene]['baseline_path'])
        _,_,grid,cfg,_=verify(run,scene);score=score_path(grid,cp['path'],**cfg)
        result=dict(status='budget_aborted',stop_reason=reason,scene=scene,rows=cp['rows'],path=cp['path'],
            J=score.J,Pd=score.pd_final,incumbent_source='last_completed_stage' if cp['rows'] else 'frozen_direct_STDC',
            process_peak_memory_mib=peak,diagnostic_elapsed_s=meta['process_wall_s'],
            elapsed_scope='external process wall including imports/input gate; interrupted solver has no certified result',
            physical_direction_unverified=scene=='bay_of_fundy',global_epsilon_certified=False)
        save(folder/'result.json',result);return result
    require(proc.returncode==0,'worker failed: '+scene)
    result=read(folder/'worker_result.json');result['external_execution']=meta
    save(folder/'result.json',result);return result

def plots(out,records,protocol):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    for rec in records:
        scene=rec['scene'];grid,cfg,_=load_case(scene);base=protocol['scenarios'][scene]
        p0=base['baseline_path'];p1=rec['path'];s0=score_path(grid,p0,**cfg);s1=score_path(grid,p1,**cfg)
        fig,axs=plt.subplots(1,3,figsize=(15,4.7),constrained_layout=True)
        heat=np.zeros(grid.size)
        for t in range(1,cfg['budget']+1):heat+=cfg['motion'].cell_mass(cfg['p'],t)[:grid.size]
        axs[0].imshow(heat.reshape(grid.rows,grid.cols),cmap='Blues',origin='upper')
        for path,label,color in ((p0,'Direct STDC','#2156a5'),(p1,'Restricted repair','#d5671c')):
            xy=np.array([grid.coordinates(v) for v in path]);axs[0].plot(xy[:,1],xy[:,0],lw=1.1,label=label,color=color)
        axs[0].set_title('Paths / accumulated prior mass');axs[0].legend(fontsize=8)
        axs[1].plot(s0.survival,label=f'Direct J={s0.J:.9f}');axs[1].plot(s1.survival,'--',label=f'Repair J={s1.J:.9f}')
        axs[1].set(xlabel='Absolute search step',ylabel='Undetected mass');axs[1].legend(fontsize=8)
        rows=rec['rows'];xs=[0]+[r['diagnostic_elapsed_s'] for r in rows];ys=[base['baseline_J']]+[r['J'] for r in rows]
        axs[2].step(xs,ys,where='post');axs[2].set(xlabel='Paid diagnostic seconds',ylabel='Best feasible J',title='Previous STDC supplied: NOT equal-budget')
        label=' / PHYSICAL DIRECTION UNVERIFIED' if scene=='bay_of_fundy' else ''
        fig.suptitle(scene+label);fig.savefig(out/(scene+'_diagnostic.png'),dpi=160);plt.close(fig)

def report(run):
    out=run/'diagnostic';protocol=read(run/'experiment/protocol.json');records=read(out/'results.json')['scenes']
    rows=[r for scene in records for r in scene['rows']];csv_save(out/'metrics.csv',rows)
    plots(out,records,protocol)
    lines=['# 独立受限精确修复：诊断报告','',
        '日期：2026-11-24。目标、评价器、forcing和粒子归档保持不变。使用原直接STDC路径作为已知可行上界，属于额外300秒/场景的改善存在性诊断，不是同预算性能胜出。',
        '固定前缀，终点自由；空间走廊逐阶段扩大。所有dual/gap仅属于当前受限子问题，求解器数值最优不等于全局epsilon认证。',
        '每次构建、求解和内部重放计入诊断时间；输入SHA验收另列。模型缓冲上限512MiB不是进程内存上限，原生求解器另用2GiB RSS监控。',
        '','|场景|原J|修复J|原Pd|修复Pd|过程状态|峰值MiB|','|---|---:|---:|---:|---:|---|---:|']
    for rec in records:
        b=protocol['scenarios'][rec['scene']]
        states=', '.join(str(r['status'])+(':'+str(r['stop_reason']) if r['stop_reason'] else '') for r in rec['rows'])
        if rec['status']=='budget_aborted':states+='; '+rec['stop_reason']
        lines.append(f"|{rec['scene']}|{b['baseline_J']:.12f}|{rec['J']:.12f}|{b['baseline_Pd']:.9f}|{rec['Pd']:.9f}|{states}|{rec['process_peak_memory_mib']:.2f}|")
    wins=sum(r['J']<protocol['scenarios'][r['scene']]['baseline_J']-ATOL for r in records)
    joint=sum(r['J']<protocol['scenarios'][r['scene']]['baseline_J']-ATOL and r['Pd']>protocol['scenarios'][r['scene']]['baseline_Pd']+ATOL for r in records)
    lines+=['',f'严格J改善场景 {wins}/3；J/Pd同时改善 {joint}/3。若无改善，不能据超时或有限走廊推断全局最优；若存在改善，必须与5秒基线性能分开讨论。',
        '','## 变化见证','']
    witnesses=[]
    for rec in records:
        base=protocol['scenarios'][rec['scene']];changed=[t for t,(a,b) in enumerate(zip(base['baseline_path'],rec['path'])) if a!=b]
        witness=dict(scene=rec['scene'],changed_steps=changed,first_divergence=min(changed) if changed else None,
            last_difference=max(changed) if changed else None,terminal_changed=rec['path'][-1]!=base['baseline_path'][-1],
            J_improvement=base['baseline_J']-rec['J'],Pd_change=rec['Pd']-base['baseline_Pd'])
        witnesses.append(witness);lines.append('- '+str(witness))
    save(out/'witnesses.json',dict(witnesses=witnesses,global_epsilon_certified=False))
    valid=read(run/'validation_summary.json')
    lines+=['','## 验证与文件','',
        '新测试：'+str(valid['stages']['new_tests']['test_counts'])+'；全量测试：'+str(valid['stages']['full_tests']['test_counts'])+'。',
        '独立Oracle报告：oracle/audit/summary.json；每例保存候选、受限最优值和下界误差。',
        '每阶段JSON包含solver状态、停止原因、受限dual/gap、模型大小、耗时和来源；每场景单独保存命令、stdout/stderr及watchdog记录。',
        'Fundy始终physical_direction_unverified=true；沿用既有all-water碰撞近似，未更换forcing或生成合成替代粒子。',
        '本轮只完成独立修复求解器与诊断，未把新方法接入A^SAR默认搜索，也未开展事件导向大邻域或新的正式同预算比赛。']
    (run/'final_report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    save(out/'conclusions.json',dict(strict_J_improved_scenes=wins,joint_improved_scenes=joint,
        same_budget_benchmark=False,global_epsilon_certified=False,scenes=records))
    manifest(run);print('report written',flush=True)

def controller(run,smoke):
    require(read(run/'validation_summary.json')['status']=='passed','validation not passed')
    if not smoke:require(read(run/'real_smoke/summary.json')['status']=='passed','real smoke not passed')
    out=run/('real_smoke' if smoke else 'diagnostic');out.mkdir(exist_ok=False);rows=[];status='passed';error=None
    try:
        for scene in SCENES:
            rec=run_scene(run,out,scene,smoke);rows.append(rec)
            save(out/'results.json',dict(scenes=rows));print(scene,rec['status'],'J',rec['J'],'Pd',rec['Pd'],flush=True)
        require(sources()==read(run/'freeze.json')['source_sha256'],'source changed')
    except BaseException:
        status='blocked';error=traceback.format_exc()
    save(out/'summary.json',dict(status=status,scenes=len(rows),error=error,
        budget_aborted_scenes=sum(r['status']=='budget_aborted' for r in rows),global_epsilon_certified=False))
    require(status=='passed',str(error));return 0

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=('prepare','smoke','diagnostic','worker','report'))
    p.add_argument('--run-dir',required=True,type=Path);p.add_argument('--output-dir',type=Path);p.add_argument('--scene',choices=SCENES);p.add_argument('--smoke',action='store_true')
    a=p.parse_args();run=a.run_dir.resolve();require(run.is_relative_to(ROOT/'outputs/stdc_v0_2'),'research outputs only')
    if a.action=='prepare':prepare(run)
    elif a.action=='worker':worker(run,a.output_dir.resolve(),a.scene,a.smoke)
    elif a.action=='report':report(run)
    else:controller(run,a.action=='smoke')
