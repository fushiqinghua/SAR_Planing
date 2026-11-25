"""Fixed-protocol trajectory ablation. Historical results are read-only."""
import argparse
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
from statistics import median
import subprocess
import sys
from time import perf_counter
import traceback

import numpy as np
import psutil
from asar_repro.objective import score_path
from asar_repro.heuristic import Heuristic
from asar_repro.particle_dp import ParticleDP
from asar_repro.research_particle import FutureEquivalentMotion
from asar_repro.research_search import search_research
from asar_repro.search import search_asar
from asar_repro.trajectory_search import search_trajectory
from asar_repro.midpoint_rollout import search_midpoint
from run_anytime_experiments import csv_save, validation_gate, manifest
from run_optimization_validation import sources, snapshot, preserve, environment, child_environment
from stdc_validation_guards import ROOT, PARTICLE_SHA, PROTOCOL_SHA, load_real, check_score, save, read, digest, require

VARIANTS=('paper_baseline','prior_stdc','compressed_stdc','dp_only','stdc_dp','mid_plain','mid_diverse','mid_dp')
CAPS={'work':dict(max_expansions=5000,max_open=20000,max_seconds=30.),
      'wall':dict(max_expansions=None,max_open=20000,max_seconds=5.)}
TARGET_J=17.264874448
ATOL=1e-10


def invoke(grid,cfg,initial,variant,limits):
    require(variant in VARIANTS,'unplanned method')
    started=perf_counter();phases=[];prep={};dp=None;packed=cfg
    if variant=='paper_baseline':
        result=search_asar(grid,**cfg,initial_path=initial,heuristic='paper_greedy',epsilon=1.04,**limits)
        return result,phases,prep,perf_counter()-started
    if variant=='prior_stdc':
        result=search_research(grid,**cfg,initial_path=initial,guide_weight=1.04,bound_mode='stdc_lb',**limits)
        return result,phases,prep,perf_counter()-started
    mark=perf_counter();grouped=FutureEquivalentMotion(cfg['motion'],cfg['p'])
    packed=dict(cfg,p=grouped.initial_weights,motion=grouped)
    prep['compression']=dict(grouped.compression_stats,wall_s=perf_counter()-mark,
        groups=[list(map(int,g)) for g in grouped.groups],original_trajectory_ids=cfg['motion'].trajectory_ids.tolist())
    needs_dp=variant in ('dp_only','stdc_dp','mid_dp')
    midpoint=variant.startswith('mid_')
    # All preprocessing, including DP, is charged inside the seed fraction for midpoint.
    seed_end=started+limits['max_seconds']*(.4 if midpoint else 1.)
    if needs_dp:
        dp=ParticleDP(grid,budget=cfg['budget'],q=cfg['q'],motion=grouped,
                      deadline=seed_end,max_memory_bytes=128*2**20)
        prep['dp']=dp.build_info
        if not dp.ready:
            fallback_offset=perf_counter()-started
            result=search_research(grid,**packed,initial_path=initial,bound_mode='zero',
                max_expansions=0,max_seconds=0,max_open=limits['max_open'],replay_cfg=cfg)
            result.status='budget_exceeded';result.stop_reason='dp_'+str(dp.stop_reason)
            result.stats['dp_ready']=False;result.stats['work_expanded']=0
            result.wall_s=perf_counter()-started
            for e in result.incumbent_history+result.candidate_archive:e['elapsed_s']+=fallback_offset
            return result,phases,prep,result.wall_s
        prep['root_dp_lb']=dp(cfg['start'],0,grouped.initial_weights)
    mode='dp_only' if variant=='dp_only' else 'stdc_dp' if needs_dp else 'stdc_lb'
    offset=perf_counter()-started
    seed_limits=dict(limits,max_seconds=max(0.,seed_end-perf_counter()))
    if midpoint and limits['max_expansions'] is not None:
        seed_limits['max_expansions']=int(.4*limits['max_expansions'])
    if variant=='compressed_stdc':
        seed=search_research(grid,**packed,initial_path=initial,guide_weight=1.04,
                             bound_mode='stdc_lb',replay_cfg=cfg,**seed_limits)
    else:
        seed=search_trajectory(grid,**packed,initial_path=initial,guide_weight=1.04,
                               bound_mode=mode,dp=dp,replay_cfg=cfg,**seed_limits)
    for e in seed.incumbent_history+seed.candidate_archive:e['elapsed_s']+=offset
    if not midpoint:
        seed.wall_s=perf_counter()-started
        seed.stats['method_preprocessing_s']=offset
        return seed,phases,prep,seed.wall_s
    offset=perf_counter()-started
    remaining=dict(limits,max_seconds=max(0.,limits['max_seconds']-offset))
    seed_work=seed.stats['work_expanded']
    if limits['max_expansions'] is not None:remaining['max_expansions']=max(0,limits['max_expansions']-seed_work)
    stdc=Heuristic(grid,budget=cfg['budget'],q=cfg['q'],motion=grouped,mode='stdc_lb')
    bound=(lambda v,d,b:max(stdc(v,d,b),dp(v,d,b))) if needs_dp else stdc
    # Bound setup is also charged before rollout starts.
    remaining['max_seconds']=max(0.,limits['max_seconds']-(perf_counter()-started))
    offset=perf_counter()-started
    result=search_midpoint(grid,**packed,initial_path=seed.path,bound=bound,bound_mode=mode,
        beam_width=24,diversity=variant!='mid_plain',replay_cfg=cfg,**remaining)
    phases=[dict(name='paid_global_seed',limits=seed_limits,result=asdict(seed)),
            dict(name='midpoint_suffixes',limits=remaining,result=asdict(result))]
    improved=result.J<seed.J-ATOL
    result.incumbent_history=list(seed.incumbent_history)+[
        dict(e,elapsed_s=e['elapsed_s']+offset,expanded=e['expanded']+seed.expanded,
             work_expanded=e.get('work_expanded',e['expanded'])+seed_work,
             source='midpoint_rollout') for e in result.incumbent_history[1:]]
    for e in getattr(result,'candidate_archive',[]):e['elapsed_s']+=offset
    result.expanded+=seed.expanded;result.generated+=seed.generated;result.pruned+=seed.pruned
    result.peak_open=max(result.peak_open,seed.peak_open)
    result.stats.update(work_expanded=result.expanded,seed_stats=seed.stats,
        seed_search_run=True,detail_scope='other detailed counters describe rollout; seed_stats is separate',
        global_seed_status=seed.status,global_seed_stop_reason=seed.stop_reason,
        budget_scope='preprocessing + seed + all anchors share total wall/work caps',
        completion_scope='scheduled beam proposal search only; not exhaustive global planning')
    if result.status=='completed' and seed.status=='budget_exceeded':
        result.stats['rollout_completion_reason']=result.completion_reason
        result.status='budget_exceeded';result.stop_reason='global_seed_'+seed.stop_reason
        result.completion_reason=None
    result.incumbent_source='midpoint_rollout' if improved else seed.incumbent_source
    result.wall_s=perf_counter()-started
    return result,phases,prep,result.wall_s


def worker(folder,variant,protocol_name,repeat,evidence,smoke):
    gate=validation_gate(evidence);source=sources();mark=perf_counter()
    protocol,grid,cfg,pt,times,raw=load_real();input_s=perf_counter()-mark
    limits=dict(CAPS[protocol_name])
    if smoke:limits.update(max_expansions=100,max_seconds=3.)
    result,phases,prep,elapsed=invoke(grid,cfg,tuple(protocol['initial_path']),variant,limits)
    save(folder/'raw_result.json',dict(result=asdict(result),phases=phases,preprocessing=prep))
    require(result.path is not None and not result.theory_certified,'missing/certified incumbent')
    score=score_path(grid,result.path,**cfg);check_score(score)
    require(abs(score.J-result.J)<=ATOL,'original J replay mismatch')
    if hasattr(result,'Pd'):require(abs(score.pd_final-result.Pd)<=ATOL,'original Pd replay mismatch')
    require(score.J<=pt.J+ATOL,'lost shared PT incumbent')
    work=getattr(result,'stats',{}).get('work_expanded',result.expanded)
    require(limits['max_expansions'] is None or work<=limits['max_expansions'],'total expansion cap exceeded')
    require(result.peak_open<=limits['max_open'],'OPEN cap exceeded')
    require(result.status in ('completed','budget_exceeded'),'unknown status')
    require(bool(result.stop_reason)==(result.status=='budget_exceeded'),'missing explicit stop reason')
    checks=[];previous=float('inf')
    for event in getattr(result,'incumbent_history',[]):
        replay=score_path(grid,event['path'],**cfg)
        require(abs(replay.J-event['J'])<=ATOL and abs(replay.pd_final-event['Pd'])<=ATOL,'history replay mismatch')
        require(replay.J<previous-ATOL,'history is not strictly improving')
        require(0<=event['elapsed_s']<=elapsed+.01,'invalid history clock')
        checks.append(dict(J=replay.J,Pd=replay.pd_final,legal=True));previous=replay.J
    for event in getattr(result,'candidate_archive',[]):
        replay=score_path(grid,event['path'],**cfg)
        require(abs(replay.J-event['J'])<=ATOL and abs(replay.pd_final-event['Pd'])<=ATOL,'candidate replay mismatch')
    require(sources()==source,'source changed during real run')
    mem=psutil.Process().memory_info()
    row=dict(asdict(result),variant=variant,protocol=protocol_name,repeat=repeat,smoke=smoke,
        Pd_T=score.pd_final,work_expanded=work,search_wall_s=elapsed,input_verification_s=input_s,
        process_peak_memory_mib=getattr(mem,'peak_wset',mem.rss)/2**20,
        memory_scope='isolated process peak including input, preprocessing, planning and replay',
        replay_error_J=abs(result.J-score.J),legal=True,history_replays=checks,
        survival=score.survival.tolist(),cumulative_J=score.g.tolist(),
        target_J=TARGET_J,delta_J=result.J-TARGET_J,particle_sha256=PARTICLE_SHA,
        protocol_sha256=PROTOCOL_SHA,particle_seed=41,verified_forcing=raw,
        time_utc=[str(t)+'Z' for t in times],forcing_kind='historical_real',
        experiment_label=protocol['experiment_label'],limits=limits,preprocessing=prep,
        cooperative_overshoot_s=max(0.,elapsed-limits['max_seconds']),
        source_sha256=source,validation_sha256=gate['sha256'],guarantee='uncertified')
    save(folder/'result.json',row)
    print(json.dumps({k:row[k] for k in ('variant','protocol','J','Pd_T','status','stop_reason','work_expanded','search_wall_s')}),flush=True)


def reports(folder,rows):
    aggregates=[]
    for protocol_name in CAPS:
        for variant in VARIANTS:
            group=[r for r in rows if r['protocol']==protocol_name and r['variant']==variant]
            if not group:continue
            a=dict(protocol=protocol_name,variant=variant,runs=len(group),
                   stops=dict(Counter(r['stop_reason'] or 'completed' for r in group)))
            for key in ('J','Pd_T','search_wall_s','work_expanded','process_peak_memory_mib','delta_J'):
                a[key+'_median']=median(r[key] for r in group)
                a[key+'_min']=min(r[key] for r in group);a[key+'_max']=max(r[key] for r in group)
            aggregates.append(a)
    save(folder/'aggregate.json',dict(rows=aggregates));csv_save(folder/'aggregate.csv',aggregates)
    excluded={'path','survival','cumulative_J','history_replays','candidate_archive','incumbent_history',
              'verified_forcing','source_sha256','preprocessing','time_utc'}
    csv_save(folder/'metrics.csv',[{k:v for k,v in r.items() if k not in excluded} for r in rows])
    pairs=[]
    for r in rows:
        for name in ('paper_baseline','prior_stdc','compressed_stdc','mid_plain'):
            base=next((b for b in rows if b['variant']==name and b['protocol']==r['protocol'] and b['repeat']==r['repeat']),None)
            if base and name!=r['variant']:
                pairs.append(dict(variant=r['variant'],reference=name,protocol=r['protocol'],repeat=r['repeat'],
                    delta_J=r['J']-base['J'],delta_Pd=r['Pd_T']-base['Pd_T'],time_ratio=r['search_wall_s']/base['search_wall_s']))
    csv_save(folder/'paired_comparisons.csv',pairs)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    for protocol_name in sorted({r['protocol'] for r in rows}):
        chosen=[r for r in rows if r['protocol']==protocol_name and r['repeat']==0]
        fig,axes=plt.subplots(2,4,figsize=(15,8),constrained_layout=True)
        for ax,r in zip(axes.flat,chosen):
            route=np.asarray(r['path']);ax.plot(route%17,route//17,'.-',ms=3)
            ax.scatter(route[0]%17,route[0]//17,s=70,marker='*')
            ax.set(title=f"{r['variant']}\nJ={r['J']:.6f}; Pd={r['Pd_T']:.6f}",
                   xlim=(-.5,16.5),ylim=(16.5,-.5),aspect='equal');ax.grid(alpha=.2)
        fig.suptitle(f'Frozen real archive; all-water approximation; uncertified; {protocol_name}')
        fig.savefig(folder/f'{protocol_name}_paths.png',dpi=160);plt.close(fig)
        fig,axes=plt.subplots(1,2,figsize=(14,6),constrained_layout=True)
        for r in chosen:
            h=r.get('incumbent_history',[])
            if h:axes[0].step([e['elapsed_s'] for e in h]+[r['search_wall_s']],
                              [e['J'] for e in h]+[r['J']],where='post',label=r['variant'])
            else:axes[0].scatter([r['search_wall_s']],[r['J']],label=r['variant'])
            axes[1].plot(r['survival'],label=r['variant'])
        axes[0].axhline(TARGET_J,color='black',ls='--',label='previous best')
        axes[0].set(xlabel='Paid method time (s)',ylabel='Incumbent J')
        axes[1].set(xlabel='Absolute step; no t=0 sensing',ylabel='Undetected mass')
        for ax in axes:ax.legend(fontsize=7);ax.grid(alpha=.2)
        fig.suptitle(f'{protocol_name}: original evaluator; no certification')
        fig.savefig(folder/f'{protocol_name}_quality_survival.png',dpi=160);plt.close(fig)
        group=[a for a in aggregates if a['protocol']==protocol_name]
        fig,axes=plt.subplots(1,3,figsize=(16,6),constrained_layout=True)
        for ax,key,label in zip(axes,('J','search_wall_s','process_peak_memory_mib'),('J (lower better)','Paid time (s)','Peak process MiB')):
            ax.barh(range(len(group)),[a[key+'_median'] for a in group])
            ax.set_yticks(range(len(group)),[a['variant'] for a in group],fontsize=8);ax.invert_yaxis();ax.set_title(label)
        fig.suptitle(f'{protocol_name}: repeated timings of one real archive, not independent scenes')
        fig.savefig(folder/f'{protocol_name}_efficiency.png',dpi=160);plt.close(fig)
    return aggregates


def controller(stage,folder,evidence,smoke):
    folder.mkdir(parents=True,exist_ok=False);rows=[];tic=perf_counter();summary=dict(status='running',runs=0)
    try:
        validation_gate(evidence);preserve(evidence.parent)
        if stage=='benchmark':
            require(smoke is not None and read(smoke/'summary.json')['status']=='passed','smoke not passed')
            for item in read(smoke/'artifact_manifest.json')['files']:
                require(digest(smoke/item['path'])==item['sha256'],'smoke fingerprint mismatch')
            require(read(smoke/'source_sha256.json')==sources(),'source changed after smoke')
        snapshot(folder,folder.parent);source=sources();save(folder/'source_sha256.json',source)
        schedule=[(v,'work',0) for v in VARIANTS] if stage=='smoke' else [
            (v,p,r) for p in CAPS for r in range(3) for v in VARIANTS[r:]+VARIANTS[:r]]
        save(folder/'protocol.json',dict(variants=VARIANTS,caps=CAPS,schedule=schedule,seed=41,
            beam=24,seed_fraction=.4,anchor_detection_fractions=[.25,.5,.75],dp_memory_bytes=128*2**20,
            smoke_limits=dict(max_expansions=100,max_seconds=3,max_open=20000),environment=environment(),
            validation_sha256=digest(evidence),guarantee='uncertified',input='common frozen PT',
            target_J=TARGET_J,preprocessing_charged=True))
        for variant,protocol_name,repeat in schedule:
            target=folder/f'{variant}_{protocol_name}_r{repeat}';target.mkdir()
            command=[sys.executable,str(Path(__file__).resolve()),'worker','--output-dir',str(target),
                '--variant',variant,'--protocol',protocol_name,'--repeat',str(repeat),'--validation-evidence',str(evidence)]
            if stage=='smoke':command.append('--smoke')
            env=child_environment();save(target/'command.json',dict(command=command,cwd=str(ROOT),seed=41,
                watchdog_s=180,environment={k:env.get(k) for k in ('PYTHONPATH','ASAR_OFFLINE','PROJ_NETWORK','OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS')}))
            with (target/'stdout.txt').open('w',encoding='utf-8') as out,(target/'stderr.txt').open('w',encoding='utf-8') as err:
                try:proc=subprocess.run(command,cwd=ROOT,env=env,stdout=out,stderr=err,timeout=180)
                except subprocess.TimeoutExpired:
                    save(target/'watchdog.json',dict(status='budget_exceeded',stop_reason='watchdog',J=None,theory_certified=False));raise
            require(proc.returncode==0,'worker failed: '+str(target))
            row=read(target/'result.json');require(row['source_sha256']==source,'worker source mismatch')
            rows.append(row);save(folder/'results.json',dict(status='running',rows=rows))
            print(f"{len(rows)}/{len(schedule)} {variant} {protocol_name} J={row['J']:.9f} Pd={row['Pd_T']:.9f} {row['stop_reason']} {row['search_wall_s']:.3f}s",flush=True)
        reports(folder,rows);preserve(evidence.parent)
        save(folder/'results.json',dict(status='passed',rows=rows))
        summary.update(status='passed',runs=len(rows),completed=sum(r['status']=='completed' for r in rows),
            budget_exceeded=sum(r['status']=='budget_exceeded' for r in rows),certified=0,
            best_J=min(r['J'] for r in rows),beat_previous_best=min(r['J'] for r in rows)<TARGET_J-ATOL)
    except Exception as exc:
        summary.update(status='blocked',runs=len(rows),error=str(exc),traceback=traceback.format_exc());raise
    finally:
        summary['wall_s']=perf_counter()-tic;save(folder/'summary.json',summary);manifest(folder)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('stage',choices=('smoke','benchmark','worker'))
    p.add_argument('--output-dir',required=True,type=Path);p.add_argument('--validation-evidence',required=True,type=Path)
    p.add_argument('--smoke-dir',type=Path);p.add_argument('--variant',choices=VARIANTS)
    p.add_argument('--protocol',choices=CAPS,default='work');p.add_argument('--repeat',type=int,default=0)
    p.add_argument('--smoke',action='store_true');a=p.parse_args()
    folder=a.output_dir.resolve();evidence=a.validation_evidence.resolve()
    require(folder.is_relative_to(ROOT/'outputs/stdc_v0_2'),'research output only')
    if a.stage=='worker':
        try:worker(folder,a.variant,a.protocol,a.repeat,evidence,a.smoke)
        except Exception as exc:
            save(folder/'failure.json',dict(status='blocked',error=str(exc),traceback=traceback.format_exc()));raise
    else:controller(a.stage,folder,evidence,a.smoke_dir.resolve() if a.smoke_dir else None)
