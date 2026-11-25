"""Fresh cold versus warm+cutoff diagnostics from the same SHA-gated STDC route."""
import argparse
from pathlib import Path
import traceback
import numpy as np
from asar_repro.objective import score_path
from run_exact_repair_experiments import prepare,run_scene,SCENES,load_case,ATOL
from run_optimization_validation import ROOT,read,save,sources,require
from run_exact_repair_validation import preserved
from run_anytime_experiments import manifest,csv_save

VARIANTS={'cold_reference':dict(warm_start=False,objective_cutoff=False),
          'warm_cutoff':dict(warm_start=True,objective_cutoff=True)}


def prepare_warm(run):
    prepare(run)
    p=read(run/'experiment/protocol.json')
    p.update(variants=VARIANTS,repetitions=1,seed=41,
        comparison='fresh cold and warm+cutoff, 300s EACH from same previously computed STDC; not a from-scratch STDC benchmark',
        execution_order='scenes sequential; cold/warm for scene0, warm/cold for scene1, cold/warm for scene2',
        warm_start_backend='SciPy bundled HiGHS private binding; complete primal vector validated and roundtrip checked',
        cutoff='original feasible J upper bound; offset accounted for; outward rounded; no strict improvement constraint',
        objective_unchanged=True,scorer_unchanged=True,forcing_unchanged=True)
    save(run/'experiment/protocol.json',p);manifest(run/'experiment')


def execute(run,smoke):
    require(read(run/'validation_summary.json')['status']=='passed','validation blocked')
    require(sources()==read(run/'freeze.json')['source_sha256'],'source changed')
    if not smoke:require(read(run/'real_smoke/summary.json')['status']=='passed','smoke blocked')
    out=run/('real_smoke' if smoke else 'diagnostic');out.mkdir(exist_ok=False)
    for v in VARIANTS:(out/v).mkdir()
    records=[];status='passed';error=None
    try:
        for i,scene in enumerate(SCENES):
            order=list(VARIANTS) if i%2==0 else list(reversed(VARIANTS))
            for v in order:
                rec=run_scene(run,out/v,scene,smoke,v);records.append(rec)
                save(out/'results.json',dict(scenes=records))
                print(scene,v,rec['status'],'J',rec['J'],'Pd',rec['Pd'],flush=True)
        require(sources()==read(run/'freeze.json')['source_sha256'],'source changed')
    except BaseException:
        status='blocked';error=traceback.format_exc()
    save(out/'summary.json',dict(status=status,scene_variant_runs=len(records),error=error,
        budget_aborted=sum(r['status']=='budget_aborted' for r in records),global_epsilon_certified=False))
    require(status=='passed',str(error))


def report(run):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    require(read(run/'diagnostic/summary.json')['status']=='passed','diagnostic blocked')
    require(sources()==read(run/'freeze.json')['source_sha256'],'source changed')
    p=read(run/'experiment/protocol.json');recs=read(run/'diagnostic/results.json')['scenes']
    rows=[r for rec in recs for r in rec['rows']];csv_save(run/'diagnostic/metrics.csv',rows)
    comparison=[];detail=[]
    for rec in recs:
        b=p['scenarios'][rec['scene']]
        changed=[t for t,(a,c) in enumerate(zip(b['baseline_path'],rec['path'])) if a!=c]
        comparison.append(dict(scene=rec['scene'],variant=rec['variant'],J=rec['J'],Pd=rec['Pd'],
            direct_STDC_J=b['baseline_J'],direct_STDC_Pd=b['baseline_Pd'],
            delta_J=rec['J']-b['baseline_J'],delta_Pd=rec['Pd']-b['baseline_Pd'],
            elapsed_s=rec['diagnostic_elapsed_s'],peak_mib=rec['process_peak_memory_mib'],
            process_status=rec['status'],completed=sum(r['status']=='completed' for r in rec['rows']),
            budget_stops=sum(r['status']=='budget_exceeded' for r in rec['rows']),
            physical_direction_unverified=rec['scene']=='bay_of_fundy',changed_steps=changed,
            global_epsilon_certified=False))
        for row in rec['rows']:
            s=row['stats']
            detail.append(dict(scene=rec['scene'],variant=rec['variant'],stage=row['stage'],
                status=row['status'],stop_reason=row['stop_reason'],incumbent_source=row['incumbent_source'],
                J=row['J'],Pd=row['Pd'],candidate_J=s.get('candidate_J'),candidate_Pd=s.get('candidate_Pd'),
                start_submitted=s['mip_start_submitted'],start_roundtrip=s['mip_start_roundtrip_verified'],
                start_replay_error=s.get('mip_start_replay_error'),cutoff=s.get('objective_cutoff_total_J'),
                replay_error=s.get('model_replay_error'),restricted_lower_bound=row['restricted_lower_bound'],
                restricted_gap=row['restricted_gap'],nodes=s.get('solver_mip_node_count'),
                wall_s=row['wall_s'],model_s=row['model_build_s'],solve_s=row['solve_s'],
                variables=s.get('model_variables'),rows=s.get('model_rows'),peak_mib=row['process_peak_memory_mib'],
                physical_direction_unverified=row['physical_direction_unverified']))
    csv_save(run/'diagnostic/comparison.csv',comparison);csv_save(run/'diagnostic/model_efficiency.csv',detail)
    save(run/'diagnostic/comparison.json',dict(rows=comparison))
    for scene in SCENES:
        grid,cfg,_=load_case(scene);base=p['scenarios'][scene]
        subset=[r for r in recs if r['scene']==scene]
        fig,axs=plt.subplots(1,3,figsize=(16,4.8),constrained_layout=True)
        heat=np.zeros(grid.size)
        for t in range(1,cfg['budget']+1):heat+=cfg['motion'].cell_mass(cfg['p'],t)[:grid.size]
        axs[0].imshow(heat.reshape(grid.rows,grid.cols),cmap='Greys',origin='upper')
        paths=[('Direct STDC',base['baseline_path'])]+[(r['variant'],r['path']) for r in subset]
        for label,path in paths:
            score=score_path(grid,path,**cfg);xy=np.array([grid.coordinates(v) for v in path])
            axs[0].plot(xy[:,1],xy[:,0],label=label,lw=1.3)
            axs[1].plot(score.survival,label=f'{label}: J={score.J:.9f}')
        axs[0].set_title('Same archived particles / routes');axs[0].legend(fontsize=8)
        axs[1].set(xlabel='Absolute search step',ylabel='Undetected mass');axs[1].legend(fontsize=8)
        axs[2].axhline(base['baseline_J'],ls=':',color='black',label='Supplied STDC')
        for r in subset:
            axs[2].step([0]+[a['diagnostic_elapsed_s'] for a in r['rows']],
                        [base['baseline_J']]+[a['J'] for a in r['rows']],where='post',label=r['variant'])
        axs[2].set(xlabel='Extra diagnostic seconds',ylabel='Best feasible J',title='300s each; previous STDC supplied');axs[2].legend(fontsize=8)
        fig.suptitle(scene+(' / PHYSICAL DIRECTION UNVERIFIED' if scene=='bay_of_fundy' else ''))
        fig.savefig(run/'diagnostic'/(scene+'_comparison.png'),dpi=160);plt.close(fig)
    valid=read(run/'validation_summary.json');keep=preserved();save(run/'final_preservation.json',keep)
    lines=['# STDC 可行解热启动与目标上界：第三轮验证','',
        '日期：2026-11-24。原目标、评价器、forcing和粒子归档不变；真实输入SHA门控通过。',
        '完整位置/残余质量/乘积辅助变量经原评分与所有线性约束检查后传入本地HiGHS setSolution，并从原生对象读回逐项核对。',
        '增加 c·x ≤ J_incumbent−offset 的向外舍入上界，始终保留已知可行解；presolve=false及严格容差保持。',
        '接口依据[HiGHS官方示例](https://ergo-code.github.io/HiGHS/stable/interfaces/python/example-py/)；本地使用SciPy内置私有绑定，未安装或升级依赖。',
        '冷启动与热启动+上界各300秒/场景，均从同一先前STDC路径出发；三场景交错顺序，单次确定性seed41。不能作为与从头运行STDC同预算的胜出或统计显著性结论。','',
        '|场景|方法|J|Pd|额外秒|峰值MiB|完成/预算停止|',
        '|---|---|---:|---:|---:|---:|---|']
    for r in comparison:
        lines.append(f"|{r['scene']}|{r['variant']}|{r['J']:.12f}|{r['Pd']:.9f}|{r['elapsed_s']:.3f}|{r['peak_mib']:.2f}|{r['completed']}/{r['budget_stops']}|")
    lines+=['','## 验证','']
    for stage,s in valid['stages'].items():lines.append('- '+stage+': '+str(s.get('test_counts',s.get('audit',{}))))
    lines+=['','## 假设与局限','',
        '固定历史粒子、4连通无等待、t0不探测、保留特殊格质量；固定前缀及空间走廊，终点自由。原目标仅最小化J，Pd独立评价，不改变为多目标。',
        'Fundy physical_direction_unverified=true；沿用既有all-water近似。所有dual/gap仅是受限子问题数值估计；completed不等于全局epsilon认证，超时不证明无改善。',
        'SciPy私有绑定存在版本兼容风险：接口/选项/热启动拒绝均blocked，不静默冷回退。模型缓冲512MiB与原生进程2GiB限制分别记录。',
        '完整命令、seed、stdout/stderr、阶段JSON及git diff在每个阶段目录。旧baseline、旧结果与R2产物保全见final_preservation.json。','',
        '## 下一阶段尚未实施','',
        '未接入A^SAR默认搜索，未改变前缀/走廊策略，未开展多次重复或从头运行的同预算算法比赛，未添加最优性声明。']
    (run/'final_report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    save(run/'round_summary.json',dict(status='passed',comparison=comparison,
        strict_J_improved_scenes=sum(r['delta_J']<-ATOL for r in comparison if r['variant']=='warm_cutoff'),
        joint_improved_scenes=sum(r['delta_J']<-ATOL and r['delta_Pd']>ATOL for r in comparison if r['variant']=='warm_cutoff'),
        completed_repairs=sum(r['status']=='completed' for r in rows),
        budget_stops=sum(r['status']=='budget_exceeded' for r in rows),
        external_aborts=sum(r['status']=='budget_aborted' for r in recs),global_epsilon_certified=False))
    manifest(run);print('report saved',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=('prepare','smoke','diagnostic','report'))
    p.add_argument('--run-dir',type=Path,required=True);a=p.parse_args();run=a.run_dir.resolve()
    require(run.is_relative_to(ROOT/'outputs/stdc_v0_2'),'research outputs only')
    if a.action=='prepare':prepare_warm(run)
    elif a.action=='report':report(run)
    else:execute(run,a.action=='smoke')
