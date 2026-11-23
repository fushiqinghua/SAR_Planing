"""Offline, additive B1 import. Preserve the B3/B7 manifest and all frozen results."""

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
from importlib.metadata import version
import json
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
from time import perf_counter
import zipfile

import numpy as np
import yaml

from asar_repro.hrrr import require, f00_wind
from asar_repro.scenarios import digest
from b1_gfs import decode as gfs_decode
from b1_extra_currents import check_stats, hycom, gomofs
from fetch_lake_b1 import selected_ranges
from verify_lake_b1 import verify as verify_lake

ROOT = Path(__file__).resolve().parents[1]


def save(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as f:
        json.dump(doc, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write('\n')


def member_path(name):
    require('\\' not in name and ':' not in name and not name.startswith('/'), 'unsafe ZIP path')
    p = PurePosixPath(name)
    require(name and all(x not in ('','..','.') for x in name.split('/')) and not p.is_absolute(), 'unsafe ZIP path')
    return p


def checked_package(archive, expected_sha, expected_sums, raw_root):
    require(digest(archive) == expected_sha, 'ZIP SHA-256 differs from pinned delivery')
    with zipfile.ZipFile(archive) as z:
        records = [i for i in z.infolist() if not i.is_dir()]
        names = [i.filename for i in records]
        require(len(names) == len(set(names)), 'duplicate ZIP members')
        for item in records:
            member_path(item.filename)
            require(not stat.S_ISLNK(item.external_attr >> 16), 'ZIP symlink not accepted')
        roots = {member_path(n).parts[0] for n in names}
        require(len(roots) == 1, 'expected one package root')
        prefix = roots.pop() + '/'
        sums_data = z.read(prefix+'SHA256SUMS.txt')
        require(hashlib.sha256(sums_data).hexdigest() == expected_sums, 'checksum manifest SHA differs')
        hashes = {}
        for line in sums_data.decode('utf-8').splitlines():
            sha, name = line.split('  ',1)
            member_path(name)
            require(re.fullmatch('[0-9a-f]{64}',sha) and name not in hashes, 'invalid/duplicate checksum row')
            hashes[name] = sha
        require(set(names) == {prefix+n for n in hashes}|{prefix+'SHA256SUMS.txt'}, 'unlisted or missing ZIP content')
        # Verify every byte before extracting. Existing imports must match; never overwrite them.
        for name, expected in hashes.items():
            with z.open(prefix+name) as f:
                require(hashlib.file_digest(f,'sha256').hexdigest() == expected, 'package member SHA mismatch: '+name)
        folder = (raw_root/prefix).resolve()
        require(folder.is_relative_to(raw_root.resolve()), 'package escapes raw root')
        for name in names:
            dest = (raw_root/name).resolve()
            require(dest.is_relative_to(folder), 'extraction escapes package')
            data = z.read(name)
            if dest.exists():
                require(dest.is_file() and dest.read_bytes() == data, 'existing package differs; refusing overwrite')
            else:
                dest.parent.mkdir(parents=True,exist_ok=True)
                with dest.open('xb') as f:
                    f.write(data)
    return folder, dict(zip_sha256=expected_sha,sums_sha256=expected_sums,
                        verified_members=len(hashes),files=hashes)


def coverage(times, window, step):
    values = [datetime.fromisoformat(t) for t in times]
    start,end = map(datetime.fromisoformat,window)
    require(values and all(t.utcoffset() == timedelta(0) for t in values+[start,end]), 'expected absolute UTC')
    require(values == sorted(set(values)), 'duplicate/unordered valid times')
    require(values[0] <= start <= end <= values[-1], 'required task window not covered')
    require(len(values)>1 and all((b-a).total_seconds() == step for a,b in zip(values,values[1:])),
            'missing or unexpected timestep')
    return dict(first_utc=values[0].isoformat(),last_utc=values[-1].isoformat(),time_count=len(values),
                interval_seconds=step,required_window_covered=True)


def wind_checks(folder, delivery, reference, case, window):
    files = []
    refs = {r['file']:r for r in reference['wind_files']}
    for source in delivery['wind']['source_records']:
        path = folder/source['local_path']
        require(digest(path) == source['sha256'] and path.stat().st_size == source['bytes'], 'wind identity differs')
        data = path.read_bytes()
        index = folder/'evidence'/(path.name.replace('.10m_uv.grib2','.idx'))
        ranges = selected_ranges(index.read_text(encoding='ascii'))
        offset = 0
        for item in source['byte_ranges']:
            require(ranges[item['variable']] == (item['start'],item['end_inclusive']), 'wind idx byte range differs')
            size = item['end_inclusive']-item['start']+1
            require(hashlib.sha256(data[offset:offset+size]).hexdigest() == item['sha256'], 'wind message SHA differs')
            offset += size
        require(offset == len(data), 'wind has trailing/unaccounted bytes')
        ref = refs[source['local_path']]
        if source['product'] == 'GFS':
            d = gfs_decode(data)
            cycle,valid,uv = d['cycle'],d['valid'],d['uv']
            require(d['lead_hours'] == source['lead_hours'], 'GFS forecast lead differs')
            lon,lat = np.meshgrid((d['lon']+180)%360-180,d['lat'])
            basis = 'geographic_east_north'
            grid = dict(kind='regular_ll',Nx=len(d['lon']),Ny=len(d['lat']),uvRelativeToGrid=0)
        else:
            valid,_,proj,x,y,uv = f00_wind(data)
            cycle = valid
            xx,yy = np.meshgrid(x,y)
            lon,lat = proj(xx,yy,inverse=True)
            basis = 'grid_relative_requires_rotation'
            grid = dict(kind='lambert',Nx=len(x),Ny=len(y),uvRelativeToGrid=1)
        require(valid == datetime.fromisoformat(source['expected_valid_time_utc']) and
                cycle == datetime.fromisoformat(source['run_cycle_utc']), 'wind valid/cycle mismatch')
        components = {}
        for component,short in enumerate(('10u','10v')):
            r = next(v for v in ref['messages'] if v['metadata']['shortName'] == short)
            values = uv[...,component]
            summary = check_stats(values,r['statistics'])
            require(summary['missing_or_nonfinite'] == 0 and summary['std'] > 0, 'invalid wind field')
            points = {}
            for name,(px,py) in {'LKP':case['lkp_lon_lat'],'CSP':case['csp_lon_lat']}.items():
                dist = np.hypot((lon-px)*np.cos(np.deg2rad(py)),lat-py)*111195
                ix = int(np.argmin(dist))
                sample = r['point_samples'][name]
                require(ix == sample['flat_index'] and values.flat[ix] == sample['native_component_m_s'],
                        'independent wind point/sample differs')
                require(dist.flat[ix] < (30000 if source['product']=='GFS' else 4500), 'task outside wind grid')
                points[name] = dict(flat_index=ix,native_component_m_s=float(values.flat[ix]),
                                    distance_m_approx=float(dist.flat[ix]))
            components[short] = dict(statistics=summary,points=points)
        files.append(dict(**{k:v for k,v in source.items() if k!='local_path'},
                          local_path=path.relative_to(ROOT).as_posix(),valid_utc=valid.isoformat(),
                          grid=grid,vector_basis=basis,units='m/s',components=components,
                          full_parent_sha256=None,reference_comparison='independent ecCodes download record'))
    times = [r['valid_utc'] for r in files]
    return dict(product=delivery['wind']['product'],status='verified',local_files=files,
                coverage=coverage(times,window,10800 if delivery['scenario']=='arctic_ocean' else 3600),
                native_variable_names=['UGRD','VGRD'],units='m/s',surface_definition='10 m above ground',
                vector_basis=basis,run_cycle_utc=sorted({r['run_cycle_utc'] for r in files}),
                delivery_kind='byte_exact_original_message_subsets',full_parent_files_available=False)


def inspect_scenario(folder, spec, integrity):
    delivery = json.loads((folder/'historical_sources.json').read_bytes())
    reference = json.loads((folder/'validation_download_environment.json').read_bytes())
    name = delivery['scenario']
    case = spec['scenarios'][name]
    require(digest(folder/'evidence/stage7_scenarios.yaml') == digest(ROOT/'configs/stage7_scenarios.yaml'),
            'package mission config differs from baseline')
    start = datetime.fromisoformat(case['incident_utc'])
    end = datetime.fromisoformat(case['cst_utc'])+timedelta(seconds=case['budget']*case['sweep_width_nm']*1852/spec['speed_m_s'])
    window = [start.isoformat(),end.isoformat()]
    require(window == delivery['requested_window_utc'], 'task window differs from package')
    wind = wind_checks(folder,delivery,reference,case,window)
    current_files, times = [], []
    if name == 'arctic_ocean':
        refs = {r['file']:r for r in reference['current']['files']}
        for source in delivery['current']['files']:
            path = folder/source['file']
            require(digest(path) == source['sha256'] and path.stat().st_size == source['bytes'], 'HYCOM SHA/size')
            result = hycom(path.read_bytes(),case,refs[source['file']])
            times.extend(result['valid_times_utc'])
            current_files.append(dict(**{k:v for k,v in source.items() if k!='file'},
                local_path=path.relative_to(ROOT).as_posix(),**result,global_parent_sha256=None))
        current = dict(product='ESPC-D-V02',status='verified',local_files=current_files,
                       native_variable_names=['ssu','ssv'],auxiliary=['sic'],units='m/s',
                       vector_basis='geographic_east_north',run_cycle_utc=None,
                       run_cycle_status='annual_archive_per_frame_lineage_not_fully_verified',
                       delivery_kind='official_NCSS_native_grid_subset')
    else:
        extraction = json.loads((folder/'gomofs_extraction_audit.json').read_bytes())
        source = delivery['current']['delivered_file']
        path = folder/source['local_path']
        require(digest(path) == source['sha256'] and path.stat().st_size == source['bytes'], 'GoMOFS SHA/size')
        result = gomofs(path.read_bytes(),case,reference['current'],extraction)
        times = result['valid_times_utc']
        current_files.append(dict(**{k:v for k,v in source.items() if k!='local_path'},
                                  local_path=path.relative_to(ROOT).as_posix(),**result))
        current = dict(product='GoMOFS',status='verified',local_files=current_files,
                       native_variable_names=['u_sur','v_sur'],units='m/s',
                       vector_basis=result['vector_basis'],run_cycle_utc=sorted(set(result['source_cycles_utc'])),
                       parent_sources=extraction['source_files'],original_parent_files_reverified_locally=False,
                       delivery_kind=delivery['current']['delivery_kind'])
    current['coverage'] = coverage(times,window,3600)
    return dict(scenario=name,alias=case.get('alias'),mission=case,requested_window_utc=window,
                sweep_width_nm=case['sweep_width_nm'],T=case['budget'],speed_m_s=spec['speed_m_s'],q=spec['q'],
                source_config_sha256=digest(ROOT/'configs/stage7_scenarios.yaml'),
                wind=wind,current=current,package=integrity,pair_status='verified',
                verification_scope='B1_delivered_files_local',forcing_kind='historical_real',
                B2_completed=False,B3_completed=False,paper_cycles_verified=False,
                real_time_information_constraint='not_certified',purpose='retrospective_environment_reconstruction')


def extend_manifest(base, verified, config_hash):
    require(base['config_sha256'] == config_hash, 'base manifest config differs')
    merged = deepcopy(base)
    merged.update(stage='B1_additional_local_packages',base_manifest='data/manifests/historical_sources.json',
                  base_manifest_sha256=digest(ROOT/'data/manifests/historical_sources.json'))
    for result in verified:
        require(result['pair_status']=='verified' and result['verification_scope']=='B1_delivered_files_local',
                'cannot merge unverified scenario')
        index = next(i for i,r in enumerate(merged['scenarios']) if r['scenario'] == result['scenario'])
        merged['scenarios'][index] = deepcopy(result)
    return merged


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=ROOT/'configs/b1_additional_packages.json')
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--include-fundy',action='store_true')
    opts = parser.parse_args()
    output = opts.output_dir.resolve()
    require(output.is_relative_to(ROOT/'outputs/baseline_v1.1') and not output.exists(), 'choose a new extension output directory')
    output.mkdir(parents=True)
    started = perf_counter()
    summary = dict(stage='B1_additional_data',status='blocked',source_commit=subprocess.check_output(
        ['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip())
    try:
        pins = json.loads(opts.config.read_bytes())
        spec = yaml.safe_load((ROOT/'configs/stage7_scenarios.yaml').read_bytes())
        tracked = subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
        before = {p:digest(ROOT/p) for p in tracked if p}
        save(output/'frozen_before.json',before)
        lake_pin = pins['lake_ontario']
        lake_folder,lake_package = checked_package(ROOT.parent/lake_pin['zip'],lake_pin['zip_sha256'],
            lake_pin['sums_sha256'],ROOT/'data/raw/historical')
        lake_audit = verify_lake(lake_folder,spec)
        save(output/'lake_ontario_recheck.json',dict(package=lake_package,**lake_audit))
        results = []
        for name in ['arctic_ocean'] + (['bay_of_fundy'] if opts.include_fundy else []):
            pin = pins[name]
            folder,integrity = checked_package(ROOT.parent/pin['zip'],pin['zip_sha256'],pin['sums_sha256'],ROOT/'data/raw/historical')
            result = inspect_scenario(folder,spec,integrity)
            save(output/(name+'_validation.json'),result)
            results.append(result)
            print(name,'verified B1 local',flush=True)
        manifest = extend_manifest(json.loads((ROOT/'data/manifests/historical_sources.json').read_bytes()),
                                   results,digest(ROOT/'configs/stage7_scenarios.yaml'))
        save(output/'historical_sources_extension.json',manifest)
        require(all(digest(ROOT/p)==sha for p,sha in before.items()),'frozen tracked evidence changed')
        # Validate B7's frozen inventory, including original forcing, without modifying it.
        old = json.loads((ROOT/'outputs/baseline_v1.1/b7_final/frozen_inventory.json').read_bytes())
        require(all(digest(ROOT/p)==sha for p,sha in old.items()),'B7 frozen fingerprint differs')
        summary.update(status='passed',scenarios=[r['scenario'] for r in results],
            existing_lake='reverified identical delivered files; existing B3/B7 unchanged',
            B2_completed=False,B3_completed=False,frozen_tracked_files=len(before),old_b7_files=len(old),
            frozen_unchanged=True,interpreter=sys.executable,
            versions={k:version(k) for k in ['numpy','netCDF4','pyproj','opendrift']},
            decoder='NumPy GRIB2 5.0/5.3, cross-checked against delivered ecCodes records; no installs',
            elapsed_s=perf_counter()-started)
    except Exception as exc:
        summary.update(error=str(exc),elapsed_s=perf_counter()-started)
    save(output/'summary.json',summary)
    print(json.dumps(summary,ensure_ascii=False),flush=True)
    return 0 if summary['status']=='passed' else 2


if __name__ == '__main__':
    sys.exit(main())
