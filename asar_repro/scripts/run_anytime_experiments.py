"""New SHA-gated global-anytime protocol; frozen experiments remain read-only."""
import argparse
from collections import Counter
import csv
from dataclasses import asdict
import importlib.metadata
import json
import os
from pathlib import Path
from statistics import median
import subprocess
import sys
from time import perf_counter
import traceback

import numpy as np
import psutil

from asar_repro.objective import score_path
from asar_repro.search import search_asar
from stdc_validation_guards import (ROOT, PARTICLE_SHA, PROTOCOL_SHA, ATOL,
                                    load_real, check_score, save, read, digest, require)

VARIANTS = {'paper_baseline': None, 'anytime_zero': 'zero',
            'anytime_mass': 'mass_lb', 'anytime_stdc': 'stdc_lb'}
WEIGHTS = (1.04, 1.1, 1.0)  # Primary 1.04 first; no post-result tuning.
LIMITS = dict(max_expansions=5000, max_open=20000, max_seconds=30)
OLD = ROOT/'outputs/stdc_v0_2/windows_20261123/benchmark'
BEST_J = 17.29389415456
SOURCE_PATHS = ('src/asar_repro/anytime_search.py', 'src/asar_repro/search.py',
    'src/asar_repro/heuristic.py', 'src/asar_repro/stdc_heuristic.py',
    'src/asar_repro/objective.py', 'src/asar_repro/motion.py', 'src/asar_repro/belief.py',
    'src/asar_repro/grid.py', 'scripts/run_anytime_experiments.py',
    'scripts/stdc_validation_guards.py')
COLORS = dict(zip(VARIANTS, ('#0072B2', '#999999', '#E69F00', '#009E73')))


def source_hashes():
    return {name: digest(ROOT/name) for name in SOURCE_PATHS}


def csv_save(path, rows):
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                             for k, v in row.items()})


def validation_gate(path):
    require(path is not None, 'validated source evidence required')
    gate = read(path)
    require(gate['status']=='passed' and not gate['not_run'], 'prior mandatory gate not passed')
    current = {p.relative_to(ROOT).as_posix(): digest(p) for top in ('src','tests','scripts')
               for p in (ROOT/top).rglob('*.py')}
    require(current==gate['source_sha256'], 'source set/content changed after validation')
    require(all(current.get(k)==v for k,v in source_hashes().items()), 'unvalidated experiment source')
    return dict(path=str(path.resolve()), sha256=digest(path), evidence=gate)


def reference():
    old = read(OLD/'results.json')
    require(old['status']=='passed', 'frozen comparison was not passed')
    rows = [r for r in old['rows'] if r['variant']=='paper_baseline']
    require(abs(min(r['J'] for r in rows)-BEST_J)<=ATOL, 'best baseline reference changed')
    return dict(best_J=BEST_J, best_J_Pd=next(r['Pd_T'] for r in rows if r['epsilon']==1.04),
                best_Pd=max(r['Pd_T'] for r in rows),
                source=str(OLD/'results.json'), sha256=digest(OLD/'results.json'), rows=rows)


def worker(folder, variant, weight, repeat):
    require(folder.is_dir() and not (folder/'result.json').exists(), 'worker output must be new')
    require(variant in VARIANTS and weight in WEIGHTS, 'unplanned method or guide weight')
    tic = perf_counter()
    protocol, grid, cfg, pt, times, raw = load_real()
    require(protocol['search_limits']==LIMITS, 'reference caps changed')
    refs = reference()
    sources = source_hashes()
    preprocess_s = perf_counter()-tic
    started = perf_counter()
    if variant=='paper_baseline':
        result = search_asar(grid, **cfg, initial_path=tuple(protocol['initial_path']),
                            heuristic='paper_greedy', epsilon=weight, **LIMITS)
    else:
        from asar_repro.anytime_search import search_anytime
        result = search_anytime(grid, **cfg, initial_path=tuple(protocol['initial_path']),
                               guide_weight=weight, bound_mode=VARIANTS[variant], **LIMITS)
    elapsed = perf_counter()-started
    record = asdict(result)
    save(folder/'raw_result.json', record)
    require(result.path is not None and not result.theory_certified, 'missing or certified incumbent')
    require(result.status in ('completed','budget_exceeded'), 'invalid completion status')
    require(result.expanded<=5000 and result.peak_open<=20000, 'global cap exceeded')
    require((result.stop_reason is not None)==(result.status=='budget_exceeded'), 'missing budget reason')
    tic = perf_counter()
    score = score_path(grid, result.path, **cfg)
    check_score(score)
    require(abs(score.J-result.J)<=ATOL, 'full path J replay mismatch')
    require(score.J<=pt.J+ATOL, 'lost initial feasible incumbent')
    history_replays = []
    if variant!='paper_baseline':
        require(abs(score.pd_final-result.Pd)<=ATOL, 'full Pd replay mismatch')
        require(bool(result.incumbent_history), 'missing anytime incumbent history')
        require(tuple(result.incumbent_history[0]['path'])==tuple(protocol['initial_path']), 'initial PT history mismatch')
        require(tuple(result.incumbent_history[-1]['path'])==tuple(result.path), 'final history path mismatch')
        previous = float('inf')
        previous_time = 0.
        for event in result.incumbent_history:
            replay = score_path(grid, event['path'], **cfg)
            check_score(replay)
            require(abs(replay.J-event['J'])<=ATOL and abs(replay.pd_final-event['Pd'])<=ATOL,
                    'incumbent history replay mismatch')
            require(replay.J<previous-ATOL, 'non-improving accepted incumbent history')
            require(previous_time<=event['elapsed_s']<=elapsed, 'invalid incumbent event clock')
            previous_time = event['elapsed_s']
            previous = replay.J
            history_replays.append(dict(J=replay.J, Pd=replay.pd_final, legal=True))
        require(abs(previous-score.J)<=ATOL, 'final history score mismatch')
    else:
        old = next(r for r in refs['rows'] if r['epsilon']==weight and r['repeat']==0)
        for key in ('path','J','status','stop_reason','expanded','generated','pruned','peak_open'):
            value = list(result.path) if key=='path' else getattr(result,key)
            require(value==old[key], 'unchanged baseline mismatch: '+key)
    replay_s = perf_counter()-tic
    require(sources==source_hashes(), 'source changed while worker ran')
    mem = psutil.Process().memory_info()
    row = dict(record, variant=variant, guide_weight=weight, repeat=repeat,
        Pd_T=score.pd_final, replay_J=score.J, replay_error=abs(score.J-result.J), legal=True,
        history_replays=history_replays, survival=score.survival.tolist(), cumulative_J=score.g.tolist(),
        forcing_kind='historical_real', experiment_label=protocol['experiment_label'], particle_seed=41,
        particle_sha256=PARTICLE_SHA, protocol_sha256=PROTOCOL_SHA, verified_forcing=raw,
        time_utc=[str(t)+'Z' for t in times], initial_PT_J=pt.J, initial_PT_Pd=pt.pd_final,
        best_baseline_J=refs['best_J'], best_baseline_J_Pd=refs['best_J_Pd'],
        best_baseline_Pd=refs['best_Pd'], delta_J_vs_best_baseline=score.J-refs['best_J'],
        delta_Pd_vs_best_J_baseline=score.pd_final-refs['best_J_Pd'],
        delta_Pd_vs_max_baseline_Pd=score.pd_final-refs['best_Pd'],
        beats_best_J=score.J<refs['best_J']-ATOL,
        search_wall_s=elapsed, preprocessing_s=preprocess_s, independent_replay_s=replay_s,
        cooperative_overshoot_s=max(0.,elapsed-LIMITS['max_seconds']),
        process_peak_memory_mib=getattr(mem,'peak_wset',mem.rss)/2**20,
        memory_scope='isolated worker peak; imports, SHA gates, search and replay included',
        source_sha256=sources, guarantee='uncertified', limits=LIMITS)
    save(folder/'result.json', row)
    print(json.dumps({k:row[k] for k in ('variant','guide_weight','status','stop_reason','J','Pd_T',
                                        'expanded','search_wall_s','beats_best_J')}),flush=True)


def snapshot(folder):
    git = ['git','-c',f'safe.directory={ROOT.parent.as_posix()}']
    for filename,args in (('git.diff',['diff','HEAD','--binary']),('git.status',['status','--short']),
                          ('git.head',['rev-parse','HEAD'])):
        proc = subprocess.run(git+args,cwd=ROOT,capture_output=True)
        (folder/filename).write_bytes(proc.stdout)
        (folder/(filename+'.stderr')).write_bytes(proc.stderr)
        require(proc.returncode==0, 'git evidence collection failed')
    for name in SOURCE_PATHS:
        target=folder/'source_snapshot'/name; target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes((ROOT/name).read_bytes())
    save(folder/'source_sha256.json',source_hashes())


def aggregates(rows):
    summaries=[]
    for weight in WEIGHTS:
        for mode in VARIANTS:
            group=[r for r in rows if r['variant']==mode and r['guide_weight']==weight]
            if not group: continue
            entry=dict(variant=mode,guide_weight=weight,runs=len(group),
                completed=sum(r['status']=='completed' for r in group),
                budget_exceeded=sum(r['status']=='budget_exceeded' for r in group),
                stop_reasons=dict(Counter(r['stop_reason'] or 'none' for r in group)),
                distinct_paths=len({tuple(r['path']) for r in group}),
                beats_best_J_runs=sum(r['beats_best_J'] for r in group))
            for field in ('J','Pd_T','expanded','generated','pruned','peak_open','search_wall_s',
                          'process_peak_memory_mib','delta_J_vs_best_baseline',
                          'delta_Pd_vs_best_J_baseline','delta_Pd_vs_max_baseline_Pd'):
                values=[r[field] for r in group]
                entry.update({field+'_median':median(values),field+'_min':min(values),field+'_max':max(values)})
            summaries.append(entry)
    return summaries


def plots(folder, rows, aggregate):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    selected=[r for r in rows if r['guide_weight']==1.04 and r['repeat']==0]
    require(len(selected)==4,'missing primary controls')
    fig,axes=plt.subplots(1,2,figsize=(12,5),constrained_layout=True)
    for row in selected:
        name=row['variant']; color=COLORS[name]
        hist=row.get('incumbent_history')
        if hist:
            x=[e['elapsed_s'] for e in hist]+[row['search_wall_s']]
            y=[e['J'] for e in hist]+[row['J']]
            axes[0].step(x,y,where='post',color=color,label=name)
        else:
            axes[0].scatter([0,row['search_wall_s']],[row['initial_PT_J'],row['J']],
                            color=color,label=name+' (endpoints only)',zorder=5)
        axes[1].plot(range(len(row['survival'])),row['survival'],color=color,label=name)
    axes[0].axhline(BEST_J,color='black',ls='--',lw=1,label='Best frozen baseline J')
    axes[0].set(xlabel='Method elapsed time (s)',ylabel='Incumbent J (lower is better)',title='Observed incumbent improvements')
    axes[1].set(xlabel='Absolute step (t=0 no sensing)',ylabel='Remaining undetected mass',title='Independent full-path replay')
    for ax in axes: ax.grid(alpha=.2);ax.legend(fontsize=8)
    fig.suptitle('Frozen real Lake Ontario; primary guide weight 1.04; all routes uncertified')
    fig.savefig(folder/'quality_and_survival.png',dpi=170);plt.close(fig)
    fig,axes=plt.subplots(2,2,figsize=(10,10),constrained_layout=True)
    for ax,row in zip(axes.flat,selected):
        route=np.asarray(row['path'])
        ax.plot(route%17,route//17,'o-',ms=2,color=COLORS[row['variant']])
        ax.scatter(route[0]%17,route[0]//17,marker='*',s=80,c='gold',edgecolors='black',zorder=5)
        ax.set(xlim=(-.5,16.5),ylim=(16.5,-.5),xlabel='Column',ylabel='Row',
               title=f"{row['variant']}\nJ={row['J']:.6f}, Pd={row['Pd_T']:.6f}\n{row['status']} / {row['stop_reason']}")
        ax.set_aspect('equal');ax.grid(alpha=.2)
    fig.suptitle('Fixed 17x17 route grid; same real input; not a geographic map')
    fig.savefig(folder/'paths.png',dpi=170);plt.close(fig)
    chosen=[r for r in aggregate if r['guide_weight']==1.04]
    fig,axes=plt.subplots(2,2,figsize=(12,8),constrained_layout=True)
    for ax,field,title in zip(axes.flat,('J','Pd_T','search_wall_s','process_peak_memory_mib'),
                              ('J (lower is better)','Pd(T)','Method wall time (s)','Process peak (MiB)')):
        y=np.arange(len(chosen));values=[r[field+'_median'] for r in chosen]
        ax.barh(y,values,color=[COLORS[r['variant']] for r in chosen])
        ax.set_yticks(y,[r['variant'] for r in chosen],fontsize=9);ax.invert_yaxis();ax.set_title(title)
        ax.grid(axis='x',alpha=.2);ax.set_axisbelow(True)
    fig.suptitle('Primary weight 1.04; medians; equal caps, actual effort/status differs')
    fig.savefig(folder/'efficiency.png',dpi=170);plt.close(fig)


def report(folder, rows, stage):
    aggregate=aggregates(rows)
    save(folder/'aggregate.json',dict(rows=aggregate))
    csv_save(folder/'aggregate.csv',aggregate)
    metrics=[{k:v for k,v in row.items() if k not in ('path','survival','cumulative_J','history_replays',
              'incumbent_history','source_sha256','time_utc','verified_forcing')} for row in rows]
    csv_save(folder/'metrics.csv',metrics)
    pairs=[]
    for row in rows:
        if row['variant']=='paper_baseline': continue
        references=('paper_baseline','anytime_zero','anytime_mass') if row['variant']=='anytime_stdc' else ('paper_baseline',)
        for ref in references:
            base=next((r for r in rows if r['variant']==ref and r['guide_weight']==row['guide_weight']
                       and r['repeat']==row['repeat']),None)
            if base is None: continue
            pairs.append(dict(variant=row['variant'],reference=ref,guide_weight=row['guide_weight'],repeat=row['repeat'],
                delta_J=row['J']-base['J'],delta_Pd=row['Pd_T']-base['Pd_T'],
                time_ratio=row['search_wall_s']/base['search_wall_s'],
                delta_expanded=row['expanded']-base['expanded'],
                delta_J_vs_best_baseline=row['delta_J_vs_best_baseline']))
    csv_save(folder/'paired_comparisons.csv',pairs)
    plots(folder,rows,aggregate)
    stdc=[r for r in rows if r['variant']=='anytime_stdc']
    wins=sum(r['beats_best_J'] for r in stdc)
    lines=['# STDC 全局 anytime：同总预算验证','',f'阶段：{stage}；实际运行 {len(rows)} 次。',
        f'预先固定最好 baseline J={BEST_J:.11f}；STDC 的 {len(stdc)} 次运行中 {wins} 次低于它。',
        '这里比较的是每次独立预算内的结果；不同权重的最好值不是免费多次搜索组成的单次方法。',
        '主要预设权重为 1.04；另报 1.1、1.0。权重只控制 paper guide 排序，不是 ε 认证。','',
        '每方法上限5000实际展开、20000物理OPEN、30秒。共同输入为已有冻结PT；本次未免费使用最好baseline路径暖启动。',
        'anytime在首解后继续搜索，paper guide只排序；zero/mass/STDC仅用未加权可采纳下界剪枝，所有完整改善用冻结评分器重放。',
        '直接baseline仍按原实现首解停止；相同cap不代表相同实际耗时。新方法额外耗时须与质量收益一起评价。',
        '同一真实Lake Ontario归档、seed41、N500、17×17、T49、q=.78，仍是historical_real_forcing_allwater离散近似。',
        '每worker重新校验forcing/粒子/元数据/UTC/评分器SHA；未运行OpenDrift、改forcing或替换synthetic粒子。',
        '全部完整路线theory_certified=false，预算中止明确记录。正常耗尽frontier也仅按当前数值容差描述，不添加ε声称。','',
        '|方法|guide权重|次数|J ↓|Pd ↑|展开|秒|正常/预算中止|',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for r in aggregate:
        lines.append(f"|{r['variant']}|{r['guide_weight']:g}|{r['runs']}|{r['J_median']:.9f}|{r['Pd_T_median']:.9f}|{r['expanded_median']:g}|{r['search_wall_s_median']:.4f}|{r['completed']}/{r['budget_exceeded']}|")
    lines+=['','## 解释边界','',
        'J是唯一原始优化目标，Pd单列；J改善不自动意味着Pd改善。metrics同时报告相对最好J baseline的Pd以及baseline各设置中的最大Pd差值。',
        'anytime_zero/mass/STDC使用相同guide与预算；共同收益属于首解后持续搜索，STDC额外贡献须从控制组差值判断。',
        '三次重复使用同一归档，仅观察时间变化，不是三个独立场景。结果不外推其他事故或forcing；未实现MHA或第二创新点。',
        '未通过的数值/历史回归/真实SHA门槛必须blocked。搜索预算中止与验证失败分开，合法完整incumbent仍完整保存。','',
        '![完整路径质量和剩余质量](quality_and_survival.png)','', '![路径](paths.png)','',
        '![效率](efficiency.png)','',
        '命令、stdout/stderr、原始result、逐incumbent独立重放、source_snapshot与源指纹均随各worker归档。']
    (folder/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return dict(stdc_runs=len(stdc),stdc_beats_best_J_runs=wins,
                best_stdc_J=min(r['J'] for r in stdc),best_reference_J=BEST_J)


def manifest(folder):
    save(folder/'artifact_manifest.json',dict(files=[dict(path=p.relative_to(folder).as_posix(),
         bytes=p.stat().st_size,sha256=digest(p)) for p in sorted(folder.rglob('*'))
         if p.is_file() and p.name!='artifact_manifest.json']))


def controller(stage, folder, evidence_path=None, smoke=None):
    require(not folder.exists(),'output must be new; previous experiments cannot be overwritten')
    folder.mkdir(parents=True)
    summary=dict(status='running',stage=stage,runs=0);rows=[];started=perf_counter()
    try:
        snapshot(folder); sources=source_hashes()
        if stage=='smoke':
            gate=validation_gate(evidence_path)
        else:
            require(smoke is not None and read(smoke/'summary.json')['status']=='passed', 'smoke gate failed')
            require(read(smoke/'summary.json')['runs']==6,'incomplete smoke')
            for item in read(smoke/'artifact_manifest.json')['files']:
                require(digest(smoke/item['path'])==item['sha256'],'smoke artifact changed')
            require(read(smoke/'source_sha256.json')==sources,'source changed after smoke')
            prior=read(smoke/'validation_evidence.json')
            require(digest(Path(prior['path']))==prior['sha256'],'validation evidence changed')
            gate=validation_gate(Path(prior['path']))
        save(folder/'validation_evidence.json',gate)
        protocol,grid,cfg,pt,times,raw=load_real()
        save(folder/'input_gate.json',dict(status='passed',particle_sha256=PARTICLE_SHA,
            protocol_sha256=PROTOCOL_SHA,mission=protocol['mission'],verified_forcing=raw,
            PT_J=pt.J,PT_Pd=pt.pd_final,reference=reference()))
        schedule=[]
        if stage=='smoke':
            schedule=[(mode,1.04,0) for mode in VARIANTS]+[('anytime_stdc',1.1,0),('anytime_stdc',1.0,0)]
        else:
            for weight in WEIGHTS:
                for repeat in range(3):
                    modes=list(VARIANTS);modes=modes[repeat:]+modes[:repeat]
                    schedule.extend((m,weight,repeat) for m in modes)
        save(folder/'plan.json',dict(stage=stage,command=[sys.executable,*sys.argv],variants=VARIANTS,
            guide_weights=WEIGHTS,primary_weight=1.04,limits=LIMITS,seed=41,expected_runs=len(schedule),
            frozen_best_J=BEST_J,initial_path='frozen common PT, not free best-baseline warm start',
            schedule=[dict(variant=m,guide_weight=w,repeat=r) for m,w,r in schedule],
            source_sha256=sources,versions={p:importlib.metadata.version(p) for p in ('numpy','scipy','pytest','opendrift')},
            guarantee='uncertified; guide is ordering only'))
        for mode,weight,repeat in schedule:
            target=folder/f'{mode}_w{weight}_rep{repeat}';target.mkdir()
            command=[sys.executable,str(Path(__file__).resolve()),'worker','--output-dir',str(target),
                     '--variant',mode,'--weight',str(weight),'--repeat',str(repeat)]
            env=os.environ.copy()
            for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
                env[key]='1'
            save(target/'command.json',dict(command=command,seed=41,threads=1,watchdog_s=180))
            tic=perf_counter()
            with (target/'stdout.txt').open('w',encoding='utf-8') as out,(target/'stderr.txt').open('w',encoding='utf-8') as err:
                try: proc=subprocess.run(command,cwd=ROOT,stdout=out,stderr=err,env=env,timeout=180)
                except subprocess.TimeoutExpired:
                    save(target/'watchdog.json',dict(status='budget_exceeded',stop_reason='watchdog',J=None,theory_certified=False));raise
            save(target/'process.json',dict(exit_code=proc.returncode,wall_s=perf_counter()-tic))
            require(proc.returncode==0,'worker failed; inspect '+str(target))
            row=read(target/'result.json');require(row['source_sha256']==sources,'worker source mismatch')
            rows.append(row);save(folder/'results.json',dict(status='running',rows=rows))
            print(f"{len(rows)}/{len(schedule)} {mode} w={weight} J={row['J']:.9f} Pd={row['Pd_T']:.9f} {row['status']} {row['stop_reason']} {row['search_wall_s']:.3f}s",flush=True)
        save(folder/'results.json',dict(status='passed',rows=rows))
        conclusion=report(folder,rows,stage)
        summary.update(status='passed',runs=len(rows),completed=sum(r['status']=='completed' for r in rows),
            budget_exceeded=sum(r['status']=='budget_exceeded' for r in rows),certified_full_routes=0,conclusion=conclusion)
    except Exception as exc:
        summary.update(status='blocked',runs=len(rows),error=str(exc),traceback=traceback.format_exc())
        (folder/'blocked.md').write_text('blocked\n\n'+str(exc),encoding='utf-8')
        raise
    finally:
        summary['wall_s']=perf_counter()-started;save(folder/'summary.json',summary);manifest(folder)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=('smoke','benchmark','worker'))
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--validation-evidence',type=Path)
    parser.add_argument('--smoke-dir',type=Path)
    parser.add_argument('--variant',choices=VARIANTS)
    parser.add_argument('--weight',type=float,default=1.04)
    parser.add_argument('--repeat',type=int,default=0)
    args=parser.parse_args();folder=args.output_dir.resolve()
    require(folder.is_relative_to(ROOT/'outputs/stdc_v0_2') and folder!=ROOT/'outputs/stdc_v0_2','research output only')
    if args.stage=='worker':
        try: worker(folder,args.variant,args.weight,args.repeat)
        except Exception as exc:
            save(folder/'failure.json',dict(status='blocked',error=str(exc),traceback=traceback.format_exc()));raise
    else: controller(args.stage,folder,args.validation_evidence,args.smoke_dir.resolve() if args.smoke_dir else None)
