"""SHA-gated same-budget comparisons on the two newly frozen real archives."""
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
from asar_repro.additional_forcing import checked_sources,SCENARIOS,MANIFEST_SHA
from asar_repro.grid import GridGraph
from asar_repro.motion import ParticleMotion
from asar_repro.objective import score_path
from asar_repro.opendrift_adapter import planning_times
from asar_repro.scenario_baselines import parallel_track
from asar_repro.scenarios import config_digest
from run_additional_real import preservation,mission
from run_trajectory_experiments import invoke,VARIANTS,CAPS
from run_anytime_experiments import csv_save,manifest
from run_optimization_validation import sources,snapshot,environment,child_environment
from stdc_validation_guards import ROOT,read,save,digest,require,check_score

ATOL=1e-10


def load_input(run,name):
    folder=run/'b3'/name;meta=read(folder/'metadata.json');archive=folder/'particles.npz'
    require(meta['status']=='passed' and meta['scenario']==name and meta['forcing_kind']=='historical_real','B3 real input not passed')
    require(meta['opendrift_runs']==1 and meta['max_mass_error']<1e-12,'B3 mass/integration gate failed')
    require(digest(archive)==meta['particle_sha256'],'particle SHA mismatch')
    require(meta['config']==mission(name),'mission changed')
    require(all(sources().get(k)==v for k,v in meta['source_sha256'].items()),'B3 source changed')
    case=checked_sources(ROOT,name)
    require(meta['provenance']['input_fingerprints']['sources']=={r:case[r]['local_files'] for r in ('wind','current')},'forcing identity changed')
    with np.load(archive,allow_pickle=False) as z:
        cells=z['cell_ids'].copy();ids=z['trajectory_id'].copy();p=z['initial_weights'].copy();times=z['time_utc'].copy()
        require(z['config_hash'].item()==meta['config_hash']==config_digest(meta['provenance']),'particle provenance mismatch')
    cfg=meta['config'];graph=GridGraph(*cfg['grid_rows_cols'])
    require(cells.shape==(cfg['budget']+1,500) and len(np.unique(ids))==500,'trajectory ID count changed')
    np.testing.assert_array_equal(times,planning_times(cfg['cst_utc'],cfg['budget'],cfg['step_s']))
    np.testing.assert_allclose(p,np.full(500,.002),rtol=0,atol=1e-15)
    args=dict(start=graph.vertex(graph.rows//2,graph.cols//2),budget=cfg['budget'],p=p,q=cfg['audit_q'],motion=ParticleMotion(cells,graph.size,ids))
    return graph,args,meta


def prepare(run):
    out=run/'frozen_comparison';out.mkdir(exist_ok=False)
    require(all(read(run/'b3'/n/'summary.json')['status']=='passed' for n in SCENARIOS),'both B3 gates required')
    records={}
    for name in SCENARIOS:
        grid,cfg,meta=load_input(run,name);started=perf_counter();pt=parallel_track(grid,**cfg);score=score_path(grid,pt,**cfg)
        records[name]=dict(mission=meta['config'],particle_sha256=meta['particle_sha256'],metadata_sha256=digest(run/'b3'/name/'metadata.json'),
            initial_path=list(pt),initial_path_sha256=config_digest(list(pt)),PT_J=score.J,PT_Pd=score.pd_final,
            PT_construction_s=perf_counter()-started,prior_special_mass_by_step=meta['prior_special_mass_by_step'])
    config=dict(status='passed',scenarios=records,variants=VARIANTS,caps=CAPS,seed=41,repeats=3,
        dp_memory_cap_bytes=128*2**20,beam_width=24,seed_fraction=.4,guide_weight=1.04,
        source_sha256=sources(),manifest_sha256=MANIFEST_SHA,environment=environment(),
        model='same fixed exogenous real particle archive for every method; unchanged min J and t0 convention',
        coastline='all-water collision approximation with native forcing mask/missing classification',
        limits_scope='method preprocessing + search; common frozen PT construction reported separately',
        guarantee='uncertified; no author-identical forcing/cycles or hand PT claims',
        archive_files_immutable=True)
    save(out/'protocol.json',config);snapshot(out,run);manifest(out)
    print({n:{k:records[n][k] for k in ('PT_J','PT_Pd','particle_sha256')} for n in SCENARIOS},flush=True)


def frozen(run,name):
    path=run/'frozen_comparison/protocol.json';protocol=read(path)
    require(protocol['status']=='passed' and protocol['source_sha256']==sources(),'comparison source changed after freeze')
    for item in read(run/'frozen_comparison/artifact_manifest.json')['files']:
        require(digest(run/'frozen_comparison'/item['path'])==item['sha256'],'comparison protocol changed')
    grid,cfg,meta=load_input(run,name);record=protocol['scenarios'][name]
    require(meta['particle_sha256']==record['particle_sha256'] and digest(run/'b3'/name/'metadata.json')==record['metadata_sha256'],'frozen archive changed')
    require(config_digest(record['initial_path'])==record['initial_path_sha256'],'PT changed')
    pt=score_path(grid,record['initial_path'],**cfg)
    require(abs(pt.J-record['PT_J'])<=ATOL and abs(pt.pd_final-record['PT_Pd'])<=ATOL,'PT replay changed')
    return grid,cfg,meta,record,protocol


def worker(run,out,name,variant,cap,repeat,smoke):
    mark=perf_counter();grid,cfg,meta,record,protocol=frozen(run,name);input_s=perf_counter()-mark
    limits=dict(CAPS[cap])
    if smoke:limits.update(max_expansions=100,max_seconds=3.)
    result,phases,prep,elapsed=invoke(grid,cfg,tuple(record['initial_path']),variant,limits)
    save(out/'raw_result.json',dict(result=asdict(result),phases=phases,preprocessing=prep))
    require(result.path is not None and not result.theory_certified,'missing or certified result')
    score=score_path(grid,result.path,**cfg);check_score(score)
    require(abs(score.J-result.J)<=ATOL,'original J replay mismatch')
    if hasattr(result,'Pd'):require(abs(score.pd_final-result.Pd)<=ATOL,'original Pd replay mismatch')
    require(score.J<=record['PT_J']+ATOL,'lost common PT incumbent')
    count=getattr(result,'stats',{}).get('work_expanded',result.expanded)
    require(limits['max_expansions'] is None or count<=limits['max_expansions'],'work cap exceeded')
    require(result.peak_open<=limits['max_open'],'OPEN cap exceeded')
    require(result.status in ('completed','budget_exceeded') and bool(result.stop_reason)==(result.status=='budget_exceeded'),'invalid stop status')
    replays=[];previous=float('inf')
    for event in getattr(result,'incumbent_history',[]):
        s=score_path(grid,event['path'],**cfg)
        require(abs(s.J-event['J'])<=ATOL and abs(s.pd_final-event['Pd'])<=ATOL and s.J<previous-ATOL,'history replay failed')
        require(0<=event['elapsed_s']<=elapsed+.01,'history clock')
        replays.append(dict(J=s.J,Pd=s.pd_final,legal=True));previous=s.J
    for event in getattr(result,'candidate_archive',[]):
        s=score_path(grid,event['path'],**cfg)
        require(abs(s.J-event['J'])<=ATOL and abs(s.pd_final-event['Pd'])<=ATOL,'candidate replay failed')
    mem=psutil.Process().memory_info()
    row=dict(asdict(result),scenario=name,variant=variant,protocol=cap,repeat=repeat,smoke=smoke,
        J=score.J,Pd_T=score.pd_final,work_expanded=count,search_wall_s=elapsed,
        process_peak_memory_mib=getattr(mem,'peak_wset',mem.rss)/2**20,input_verification_s=input_s,
        cooperative_overshoot_s=max(0,elapsed-limits['max_seconds']),limits=limits,
        PT_J=record['PT_J'],PT_Pd=record['PT_Pd'],delta_J_PT=score.J-record['PT_J'],
        replay_error=abs(score.J-result.J),legal=True,history_replays=replays,
        survival=score.survival.tolist(),cumulative_J=score.g.tolist(),preprocessing=prep,
        particle_sha256=record['particle_sha256'],config=record['mission'],source_sha256=sources(),
        forcing_kind='historical_real',experiment_label=meta['experiment_label'],particle_seed=41,
        guarantee='uncertified',incumbent_origin='common_frozen_ParallelTrack' if result.incumbent_source=='initial_path' else result.incumbent_source,
        memory_scope='isolated process peak includes imports, input verification, preprocessing, planning, replay')
    save(out/'result.json',row)


def reports(folder,rows):
    aggregate=[];pairs=[]
    for name in SCENARIOS:
        for cap in CAPS:
            for method in VARIANTS:
                group=[r for r in rows if (r['scenario'],r['protocol'],r['variant'])==(name,cap,method)]
                if not group:continue
                a=dict(scenario=name,protocol=cap,variant=method,runs=len(group),stops=dict(Counter(r['stop_reason'] or 'completed' for r in group)))
                for k in ('J','Pd_T','search_wall_s','work_expanded','process_peak_memory_mib','PT_J','PT_Pd'):
                    a[k+'_median']=median(r[k] for r in group);a[k+'_min']=min(r[k] for r in group);a[k+'_max']=max(r[k] for r in group)
                aggregate.append(a)
    for r in rows:
        for ref in ('paper_baseline','prior_stdc','compressed_stdc'):
            b=next((b for b in rows if (b['scenario'],b['protocol'],b['repeat'],b['variant'])==(r['scenario'],r['protocol'],r['repeat'],ref)),None)
            if b and ref!=r['variant']:pairs.append(dict(scenario=r['scenario'],protocol=r['protocol'],repeat=r['repeat'],variant=r['variant'],reference=ref,
                delta_J=r['J']-b['J'],delta_Pd=r['Pd_T']-b['Pd_T'],J_reduction_percent=100*(b['J']-r['J'])/b['J'] if b['J'] else None,
                time_ratio=r['search_wall_s']/b['search_wall_s']))
    save(folder/'aggregate.json',dict(rows=aggregate));csv_save(folder/'aggregate.csv',aggregate);csv_save(folder/'paired_comparisons.csv',pairs)
    excluded={'path','survival','cumulative_J','history_replays','candidate_archive','incumbent_history','preprocessing','config','source_sha256','stats'}
    csv_save(folder/'metrics.csv',[{k:v for k,v in r.items() if k not in excluded} for r in rows])
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    for name in SCENARIOS:
        for cap in sorted({r['protocol'] for r in rows}):
            chosen=[r for r in rows if (r['scenario'],r['protocol'],r['repeat'])==(name,cap,0)]
            if not chosen:continue
            fig,axesplot=plt.subplots(2,4,figsize=(15,9),constrained_layout=True)
            for ax,r in zip(axesplot.flat,chosen):
                nr,nc=r['config']['grid_rows_cols'];route=np.asarray(r['path'])
                ax.plot(route%nc,route//nc,'.-',ms=2);ax.scatter(route[0]%nc,route[0]//nc,marker='*',s=70)
                ax.set(title=f"{r['variant']}\nJ={r['J']:.6f}, Pd={r['Pd_T']:.6f}",xlim=(-.5,nc-.5),ylim=(nr-.5,-.5),aspect='equal');ax.grid(alpha=.2)
            fig.suptitle(name+' / '+cap+' / frozen real particles / all-water approximation / uncertified')
            fig.savefig(folder/f'{name}_{cap}_paths.png',dpi=150);plt.close(fig)
            fig,ax=plt.subplots(1,2,figsize=(14,6),constrained_layout=True)
            for r in chosen:
                h=r.get('incumbent_history',[])
                if h:ax[0].step([e['elapsed_s'] for e in h]+[r['search_wall_s']],[e['J'] for e in h]+[r['J']],where='post',label=r['variant'])
                else:ax[0].scatter([r['search_wall_s']],[r['J']],label=r['variant'])
                ax[1].plot(r['survival'],label=r['variant'])
            ax[0].set(xlabel='Paid method time (s)',ylabel='Incumbent J');ax[1].set(xlabel='t=0 at CST; no t0 sensing',ylabel='Undetected mass')
            for a in ax:a.legend(fontsize=7);a.grid(alpha=.2)
            fig.suptitle(name+' / '+cap+' / original scorer; no certification')
            fig.savefig(folder/f'{name}_{cap}_survival_quality.png',dpi=150);plt.close(fig)
            group=[a for a in aggregate if (a['scenario'],a['protocol'])==(name,cap)]
            fig,ax=plt.subplots(1,3,figsize=(16,6),constrained_layout=True)
            for a,k in zip(ax,('J','search_wall_s','process_peak_memory_mib')):
                a.barh([x['variant'] for x in group],[x[k+'_median'] for x in group]);a.invert_yaxis();a.set_title(k+' median');a.tick_params(axis='y',labelsize=8)
            fig.suptitle(name+' / '+cap+' / same archive and budget caps')
            fig.savefig(folder/f'{name}_{cap}_efficiency.png',dpi=150);plt.close(fig)


def controller(run,stage):
    folder=run/stage;folder.mkdir(exist_ok=False);rows=[];summary=dict(status='running',runs=0);started=perf_counter()
    try:
        preservation(run)
        if stage=='benchmark':
            require(read(run/'smoke/summary.json')['status']=='passed','smoke did not pass')
            for item in read(run/'smoke/artifact_manifest.json')['files']:require(digest(run/'smoke'/item['path'])==item['sha256'],'smoke file changed')
        for name in SCENARIOS:frozen(run,name)
        source=sources();snapshot(folder,run)
        schedule=[(n,v,'work',0) for n in SCENARIOS for v in VARIANTS] if stage=='smoke' else [
            (n,v,p,r) for p in CAPS for r in range(3) for n in SCENARIOS for v in VARIANTS[r:]+VARIANTS[:r]]
        save(folder/'schedule.json',dict(command=[sys.executable,*sys.argv],schedule=schedule,source_sha256=source,seed=41,caps=CAPS))
        for name,variant,cap,repeat in schedule:
            out=folder/f'{name}_{variant}_{cap}_r{repeat}';out.mkdir()
            cmd=[sys.executable,str(Path(__file__).resolve()),'worker','--run-dir',str(run),'--output-dir',str(out),
                '--scenario',name,'--variant',variant,'--protocol',cap,'--repeat',str(repeat)]
            if stage=='smoke':cmd.append('--smoke')
            env=child_environment();save(out/'command.json',dict(command=cmd,cwd=str(ROOT),seed=41,watchdog_s=180,environment={k:env.get(k) for k in ('PYTHONPATH','PYTHONUTF8','ASAR_OFFLINE','PROJ_NETWORK','OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','GIT_CONFIG_COUNT')}))
            with (out/'stdout.txt').open('w',encoding='utf-8') as stdout,(out/'stderr.txt').open('w',encoding='utf-8') as stderr:
                try:process=subprocess.run(cmd,cwd=ROOT,env=env,stdout=stdout,stderr=stderr,timeout=180)
                except subprocess.TimeoutExpired:
                    save(out/'watchdog.json',dict(status='budget_exceeded',stop_reason='watchdog',J=None,certified=False));raise
            require(process.returncode==0,'worker failed: '+out.name)
            row=read(out/'result.json');require(row['source_sha256']==source,'worker source mismatch')
            rows.append(row);save(folder/'results.json',dict(status='running',rows=rows))
            print(f"{len(rows)}/{len(schedule)} {name} {variant} {cap} J={row['J']:.9f} Pd={row['Pd_T']:.9f} {row['stop_reason']} {row['search_wall_s']:.3f}s",flush=True)
        reports(folder,rows);summary.update(status='passed',runs=len(rows),completed=sum(r['status']=='completed' for r in rows),
            budget_exceeded=sum(r['status']=='budget_exceeded' for r in rows),certified=0,max_replay_error=max(r['replay_error'] for r in rows),preservation=preservation(run))
        save(folder/'results.json',dict(status='passed',rows=rows))
    except BaseException as exc:
        summary.update(status='blocked',runs=len(rows),error=str(exc),traceback=traceback.format_exc());raise
    finally:summary['wall_s']=perf_counter()-started;save(folder/'summary.json',summary);manifest(folder)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=('prepare','smoke','benchmark','worker'));p.add_argument('--run-dir',required=True,type=Path)
    p.add_argument('--output-dir',type=Path);p.add_argument('--scenario',choices=SCENARIOS);p.add_argument('--variant',choices=VARIANTS)
    p.add_argument('--protocol',choices=CAPS,default='work');p.add_argument('--repeat',type=int,default=0);p.add_argument('--smoke',action='store_true');a=p.parse_args();run=a.run_dir.resolve()
    if a.stage=='prepare':prepare(run)
    elif a.stage=='worker':
        try:worker(run,a.output_dir.resolve(),a.scenario,a.variant,a.protocol,a.repeat,a.smoke)
        except BaseException as exc:save(a.output_dir/'failure.json',dict(status='blocked',error=str(exc),traceback=traceback.format_exc()));raise
    else:controller(run,a.stage)
