"""Additional real scenarios: ordered B2/B3 gates and immutable outputs."""
import argparse
from collections import Counter
from dataclasses import asdict
from datetime import timedelta
import json
from pathlib import Path
import sys
from time import perf_counter
import traceback
import xml.etree.ElementTree as ET

import numpy as np
from netCDF4 import Dataset
from pyproj import Geod
import yaml

from asar_repro.additional_forcing import load_additional_forcing,checked_sources,MANIFEST_SHA,SCENARIOS
from asar_repro.historical_drift import axes,identity,run_historical,build_archive,utc_label,compare_replay
from asar_repro.historical_reader import build_opendrift_readers
from asar_repro.forcing import longitude,numeric
from asar_repro.opendrift_adapter import utc_datetime,Frames
from asar_repro.scenarios import drift_config,config_digest
from asar_repro.grid import GridGraph
from asar_repro.motion import ParticleMotion
from asar_repro.objective import score_path
from asar_repro.scenario_baselines import parallel_track
from stdc_validation_guards import ROOT,read,save,digest,require
from run_optimization_validation import REPO,git,sources,snapshot,environment
from run_anytime_experiments import csv_save,manifest


def mission(name):
    spec=yaml.safe_load((ROOT/'configs/stage7_scenarios.yaml').read_text(encoding='utf-8'))
    cfg=drift_config(spec,spec['scenarios'][name]);cfg.pop('forcing')
    cfg.update(forcing_kind='historical_real',audit_q=spec['q'])
    return cfg


def preservation(run):
    before=read(run/'before.json')
    require(git('branch','--show-current').decode().strip()==before['branch'],'branch changed')
    require(git('rev-parse','HEAD').decode().strip()==before['head'],'HEAD changed')
    for name,sha in before['protected'].items():require(digest(REPO/name)==sha,'preexisting file changed: '+name)
    # The frozen baseline independently uses the existing historical inventory.
    from run_optimization_validation import OLD
    frozen=read(OLD);base=Path(frozen['baseline_root'])
    require(git('rev-parse','HEAD',cwd=base).decode().strip()==frozen['base_commit'],'baseline HEAD changed')
    for name,sha in frozen['baseline_all_preserved'].items():require(digest(base/name)==sha,'baseline changed: '+name)
    return dict(status='passed',preexisting_files=len(before['protected']),baseline_files=len(frozen['baseline_all_preserved']))


def tests_gate(run):
    counts={}
    for name in ('b2_new_tests_r3','b2_full_tests_r3'):
        suites=ET.parse(run/(name+'.xml')).getroot()
        counts[name]={k:sum(int(s.get(k,0)) for s in suites.iter('testsuite')) for k in ('tests','errors','failures','skipped')}
        require(counts[name]['tests']>0 and counts[name]['errors']==counts[name]['failures']==counts[name]['skipped']==0,'test gate failed')
    require(counts['b2_full_tests_r3']['tests']==903+counts['b2_new_tests_r3']['tests'],'historical test count mismatch')
    return counts


def native_controls(bundle,case):
    errors=[];records=[];wind=bundle.wind
    for row in case['wind']['local_files']:
        for name in ('LKP','CSP'):
            index=row['components']['10u']['points'][name]['flat_index']
            expected=np.array([row['components'][k]['points'][name]['native_component_m_s'] for k in ('10u','10v')])
            if case['scenario']=='arctic_ocean':
                j,i=divmod(index,1440);lon=float(longitude(i*.25));lat=90-j*.25
            else:
                j,i=divmod(index,1799);i0,_,j0,_=wind.metadata['in_memory_crop_indices']
                lon,lat=wind.grid.projection(wind.grid.x[i-i0],wind.grid.y[j-j0],inverse=True)
                params={p.name:p.value for p in wind.grid.projection.crs.coordinate_operation.params}
                lon0=longitude(params['Longitude of false origin']);n=np.sin(np.deg2rad(params['Latitude of 1st standard parallel']))
                gamma=n*np.deg2rad(longitude(lon-lon0));c,s=np.cos(gamma),np.sin(gamma)
                expected=np.array([c*expected[0]+s*expected[1],-s*expected[0]+c*expected[1]])
            actual=wind.sample(row['valid_utc'],[lon],[lat])[0]
            error=float(np.max(abs(actual-expected)));require(error<1e-6,'independent native wind/rotation control failed')
            records.append(dict(role='wind',point=name,time=row['valid_utc'],error_m_s=error));errors.append(error)
    current=bundle.current
    angle_errors=[]
    for row in case['current']['local_files']:
        if case['scenario']=='arctic_ocean':
            for name in ('LKP','CSP'):
                point=row['points'][name];lon,lat=point['nearest_lon_lat']
                for k,t in enumerate(row['valid_times_utc']):
                    expected=np.array([point['east_m_s'][k],point['north_m_s'][k]])
                    error=float(np.max(abs(current.sample(t,[lon],[lat])[0]-expected)))
                    require(error<1e-7,'HYCOM independent native value check failed');errors.append(error)
                    records.append(dict(role='current',point=name,time=t,error_m_s=error))
        else:
            with Dataset('gomofs_control.nc',memory=(ROOT/row['local_path']).read_bytes()) as ds:
                for name in ('LKP','CSP'):
                    j,i=row['points'][name]['rho']['index'];lon=float(ds['lon_rho'][j,i]);lat=float(ds['lat_rho'][j,i]);a=float(ds['angle'][j,i])
                    # Independent geography verifies the xi/east angle convention.
                    az,_,_=Geod(ellps='WGS84').inv(float(ds['lon_rho'][j,i-1]),float(ds['lat_rho'][j,i-1]),float(ds['lon_rho'][j,i+1]),float(ds['lat_rho'][j,i+1]))
                    angle_error=abs(float(longitude(np.rad2deg(a)-(90-az))));require(angle_error<2.,'ROMS angle does not follow physical xi direction')
                    angle_errors.append(angle_error)
                    for k,t in enumerate(row['valid_times_utc']):
                        u=.5*(float(ds['u_sur'][k,j,i-1])+float(ds['u_sur'][k,j,i]));v=.5*(float(ds['v_sur'][k,j-1,i])+float(ds['v_sur'][k,j,i]))
                        expected=np.array([np.cos(a)*u-np.sin(a)*v,np.sin(a)*u+np.cos(a)*v])
                        error=float(np.max(abs(current.sample(t,[lon],[lat])[0]-expected)))
                        require(error<1e-6,'independent ROMS collocation/rotation control failed');errors.append(error)
                        records.append(dict(role='current',point=name,time=t,error_m_s=error))
    return dict(records=records,max_error_m_s=max(errors),roms_xi_angle_error_degrees=angle_errors)


def forcing(run,name,out):
    test_counts=tests_gate(run);cfg=mission(name);native,target=axes(cfg)
    bundle,case=load_additional_forcing(ROOT,name,window=(utc_label(native[0]),utc_label(native[-1])))
    controls=native_controls(bundle,case);readers=build_opendrift_readers(bundle)
    stamps=[native[0],native[0]+(target[0]-native[0])//2,target[0],target[-1],native[-1]]
    records=[]
    for t in stamps:
        when=utc_datetime(utc_label(t))
        for label in ('lkp_lon_lat','csp_lon_lat'):
            x,y=cfg[label]
            for field,reader in zip((bundle.wind,bundle.current),readers):
                uv,status=field.probe(when,[x],[y]);require(status[0]=='ok','task point forcing unavailable')
                result=reader.get_variables(reader.variables,when.replace(tzinfo=None),np.array([x]),np.array([y]),np.array([0.]))
                np.testing.assert_allclose([result[k][0] for k in reader.variables],uv[0],rtol=0,atol=1e-12)
                records.append(dict(time_utc=when.isoformat(),point=label,role=field.role,east=float(uv[0,0]),north=float(uv[0,1]),status=str(status[0])))
    payload=dict(status='passed',scenario=name,forcing_kind='historical_real',experiment_label='historical_real_forcing_allwater_native_masks',
        test_counts=test_counts,mission=cfg,manifest_sha256=MANIFEST_SHA,original_sources={role:case[role] for role in ('wind','current')},
        source_sha256=sources(),fields={r:dict(metadata=f.metadata,valid_times_utc=[t.isoformat() for t in f.times],shape=list(f.values.shape)) for r,f in [('wind',bundle.wind),('current',bundle.current)]},
        native_controls=controls,point_probes=records,shoreline='no full coastline collision; native dry/masked cells become land/unknown mass',
        paper_cycles_verified=False,original_parent_files_reverified_locally=False if name=='bay_of_fundy' else None)
    save(out/'forcing_audit.json',payload);csv_save(out/'point_probes.csv',records)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axesplot=plt.subplots(2,1,figsize=(11,7),constrained_layout=True)
    for ax,field in zip(axesplot,(bundle.wind,bundle.current)):
        vals=np.array([field.sample(t,[cfg['lkp_lon_lat'][0]],[cfg['lkp_lon_lat'][1]])[0] for t in field.times])
        ax.plot(field.times,vals[:,0],label='east m/s');ax.plot(field.times,vals[:,1],label='north m/s');ax.legend();ax.grid(alpha=.2);ax.set_title(field.role+' at LKP; native valid UTC')
    fig.suptitle(name+' / historical real / native masks / no coast-collision model')
    fig.savefig(out/'forcing_timeseries.png',dpi=150);plt.close(fig)
    return dict(status='passed',scenario=name,native_control_error=controls['max_error_m_s'],samples=len(records))


def particles(run,name,out):
    gate=read(run/'b2_passed.json')[name]
    audit_path=run/gate['path'];require(digest(audit_path)==gate['sha256'],'B2 audit fingerprint changed');audit=read(audit_path)
    require(audit['status']=='passed' and all(sources().get(k)==v for k,v in audit['source_sha256'].items()),'B2 source changed')
    cfg=mission(name);require(cfg==audit['mission'],'mission changed');native,target=axes(cfg)
    bundle,case=load_additional_forcing(ROOT,name,window=(utc_label(native[0]),utc_label(native[-1])))
    fingerprint=identity(cfg,dict(manifest_sha256=MANIFEST_SHA,b2_sha256=digest(audit_path),sources={r:case[r]['local_files'] for r in ('wind','current')},implementation_sha256=sources()))
    started=perf_counter();raw,failures,model=run_historical(cfg,bundle);integration_s=perf_counter()-started
    grid,data,ledger,J=build_archive(raw,failures,bundle,cfg,fingerprint)
    np.savez_compressed(out/'particles.npz',**data)
    with np.load(out/'particles.npz',allow_pickle=False) as z:cached={k:z[k] for k in z.files}
    # No second OpenDrift run: regrid and replay from frozen native trajectories.
    native_frames=Frames(cached['trajectory_id'],cached['raw_time_utc'],cached['raw_lon'],cached['raw_lat'],cached['raw_status'],cached['raw_land_binary_mask'],{int(k):v for k,v in json.loads(cached['flags_json'].item()).items()})
    _,replayed,reledger,reJ=build_archive(native_frames,failures,bundle,cfg,fingerprint)
    compared=compare_replay(cached,replayed);require(abs(reJ-J)<1e-12,'cache J mismatch')
    csv_save(out/'mass_audit.csv',ledger)
    graph=grid.graph;motion=ParticleMotion(cached['cell_ids'],graph.size,cached['trajectory_id'])
    p=cached['initial_weights'];totals=[float(motion.cell_mass(p,t).sum()) for t in range(len(target))]
    require(max(abs(x-1) for x in totals)<1e-12,'lost particle mass')
    from plot_historical_drift import plot_drift
    # New plots use original IDs and all special masses, independent of search.
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(1,2,figsize=(13,6),constrained_layout=True)
    ax[0].plot(cached['raw_lon'][:,::10],cached['raw_lat'][:,::10],alpha=.4,lw=.6)
    ax[0].scatter(cached['lon'][0],cached['lat'][0],s=4,label='CST');ax[0].scatter(*cfg['csp_lon_lat'],marker='*',s=80,label='CSP');ax[0].legend()
    ax[0].set(xlabel='Longitude',ylabel='Latitude',title='Real pre-drift and search trajectories; every 10th ID')
    for key in ('searchable','land','outside','inactive','unknown'):ax[1].plot(range(len(ledger)),[a['prior_'+key] for a in ledger],label=key)
    ax[1].set(xlabel='Absolute search step, t=0 at CST',ylabel='Undetected prior mass',title='All mass retained, no detection');ax[1].legend();ax[1].grid(alpha=.2)
    fig.suptitle(name+' / historical real forcing / all-water coast approximation + native masks')
    fig.savefig(out/'particles.png',dpi=160);plt.close(fig)
    meta=dict(status='passed',scenario=name,forcing_kind='historical_real',experiment_label=audit['experiment_label'],config=cfg,
        config_hash=config_digest(fingerprint),provenance=fingerprint,source_sha256=sources(),b2_sha256=digest(audit_path),
        particle_sha256=digest(out/'particles.npz'),model=model,opendrift_runs=1,cache_replay_variables=compared,
        integration_wall_s=integration_s,terminal_forcing=failures,initial_mass=float(p.sum()),
        prior_special_mass_by_step=[{k:r['prior_'+k] for k in ('land','outside','inactive','unknown')} for r in ledger],
        max_mass_error=max(r['max_error'] for r in ledger),audit_J=J,
        native_utc=[utc_label(t) for t in native],planning_utc=[utc_label(t) for t in target],
        data_availability='B1/B2/B3 local historical validated; author-identical forcing/cycles unproven',theory_certified=False)
    save(out/'metadata.json',meta)
    return {k:meta[k] for k in ('status','scenario','particle_sha256','opendrift_runs','max_mass_error','integration_wall_s')}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=('b2','b3'));p.add_argument('--run-dir',required=True,type=Path);p.add_argument('--scenario',choices=SCENARIOS,required=True);p.add_argument('--label')
    a=p.parse_args();run=a.run_dir.resolve();out=run/(a.label or a.stage)/a.scenario;out.mkdir(parents=True,exist_ok=False)
    summary=dict(status='running',command=[sys.executable,*sys.argv],seed=41,source_sha256=sources(),environment=environment());started=perf_counter()
    try:
        summary['preservation_before']=preservation(run);snapshot(out,run)
        summary.update((forcing if a.stage=='b2' else particles)(run,a.scenario,out))
        summary['preservation_after']=preservation(run)
        if a.stage=='b2':
            gate_path=run/'b2_passed.json';gates=read(gate_path) if gate_path.exists() else {}
            gates[a.scenario]=dict(path=(out/'forcing_audit.json').relative_to(run).as_posix(),sha256=digest(out/'forcing_audit.json'))
            save(gate_path,gates)
    except BaseException as exc:
        summary.update(status='blocked',error=str(exc),traceback=traceback.format_exc());raise
    finally:
        summary['wall_s']=perf_counter()-started;save(out/'summary.json',summary);manifest(out)
    print(json.dumps({k:v for k,v in summary.items() if k not in ('source_sha256','environment','command','preservation_before','preservation_after')},ensure_ascii=False),flush=True)
