"""User-authorized official-angle reproduction; physical orientation remains unverified."""
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
                    angle_error=abs(float(longitude(np.rad2deg(a)-(90-az))));require(np.isfinite(angle_error),'nonfinite ROMS orientation diagnostic')
                    angle_errors.append(angle_error)
                    for k,t in enumerate(row['valid_times_utc']):
                        u=.5*(float(ds['u_sur'][k,j,i-1])+float(ds['u_sur'][k,j,i]));v=.5*(float(ds['v_sur'][k,j-1,i])+float(ds['v_sur'][k,j,i]))
                        expected=np.array([np.cos(a)*u-np.sin(a)*v,np.sin(a)*u+np.cos(a)*v])
                        error=float(np.max(abs(current.sample(t,[lon],[lat])[0]-expected)))
                        require(error<1e-6,'independent ROMS collocation/rotation control failed');errors.append(error)
                        records.append(dict(role='current',point=name,time=t,error_m_s=error))
    return dict(records=records,max_error_m_s=max(errors),roms_xi_angle_error_degrees=angle_errors)


import run_additional_real as original
from run_additional_real import mission,preservation
POLICY=dict(mode='official_native_angle',geographic_direction_validated=False,
 physical_direction_unverified=True,original_strict_gate_passed=False,
 accepted_by_user='2026-11-24: 按官方 angle 接入，保留未验证标签',
 implementation_basis='ROMS Utility/uv_rotate.F: average native faces then rotate with supplied angle',
 original_parent_sha256='c2879d000da71de2509e5f5194130de8c063256dc9c784a443826474894a378e')
def parent_gate(run):
 require(digest(run/'verified_parent_n005.nc')==POLICY['original_parent_sha256'],'original parent SHA mismatch')
 proof=read(run/'parent_comparison.json')
 require(all(x['exact_bytes_equal'] for x in proof['checks'].values()),'parent/subset discrepancy')
def tests_gate(run):
 counts={}
 for label in ('native_tests','full_tests'):
  suites=ET.parse(run/(label+'.xml')).getroot()
  counts[label]={k:sum(int(s.get(k,0)) for s in suites.iter('testsuite')) for k in ('tests','errors','failures','skipped')}
  require(counts[label]['tests']>0 and sum(counts[label][k] for k in ('errors','failures','skipped'))==0,'test gate')
 require(counts['full_tests']['tests']==924+counts['native_tests']['tests'],'historical test inventory')
 return counts
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('stage',choices=('b2','b3'));p.add_argument('--run-dir',type=Path,required=True);a=p.parse_args()
 run=a.run_dir.resolve();out=run/a.stage/'bay_of_fundy';out.mkdir(parents=True,exist_ok=False)
 summary=dict(status='running',direction_policy=POLICY,command=[sys.executable,*sys.argv],seed=41,environment=environment())
 try:
  parent_gate(run);summary['preservation_before']=preservation(run);snapshot(out,run)
  original.native_controls=native_controls
  original.tests_gate=tests_gate
  if a.stage=='b2':
   summary.update(original.forcing(run,'bay_of_fundy',out))
   audit=read(out/'forcing_audit.json');audit.update(direction_policy=POLICY,experiment_label='historical_real_native_angle_geography_unverified')
   save(out/'forcing_audit.json',audit)
   save(run/'b2_passed.json',dict(bay_of_fundy=dict(path='b2/bay_of_fundy/forcing_audit.json',sha256=digest(out/'forcing_audit.json'))))
  else:
   summary.update(original.particles(run,'bay_of_fundy',out))
   meta=read(out/'metadata.json');meta.update(direction_policy=POLICY,physical_direction_validated=False)
   save(out/'metadata.json',meta)
  summary['preservation_after']=preservation(run)
 except BaseException as e:
  summary.update(status='blocked',error=str(e),traceback=traceback.format_exc());raise
 finally:
  save(out/'summary.json',summary);manifest(out)
 print(json.dumps(summary,ensure_ascii=False),flush=True)
