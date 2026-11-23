"""Independent packing examples and fail-closed B1 import/data contracts."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import struct
import sys
import zipfile

from netCDF4 import Dataset
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from b1_gfs import complex_values, decode, regular_grid
from b1_extra_currents import packed_cf, native_times, hycom
from import_additional_b1 import checked_package, coverage, extend_manifest, member_path


def section(count, groups, refbits, wref, wbits, lref, lbits, last, order):
    s=bytearray(49)
    struct.pack_into('>IBIHfHHBB',s,0,49,5,count,3,0.,0,0,refbits,0)
    s[21]=1
    struct.pack_into('>I',s,31,groups)
    s[35:37]=bytes([wref,wbits])
    struct.pack_into('>I',s,37,lref)
    s[41]=1
    struct.pack_into('>I',s,42,last)
    s[46:]=bytes([lbits,order,1])
    return s


def test_order1_three_groups_cross_bit_boundaries_and_negative_minimum():
    # Original integers 10,12,9,9,14,13,13. Differences 2,-3,0,5,-1,0.
    # min=-3, dummy=0 -> packed 0,5 | 0,3,8 | 2,3.
    # refs=0,0,2 (2 bits), widths=3,4,1 (ref1 plus 2,3,0), lengths=2,3,2.
    s=section(7,3,2,1,2,2,1,2,1)
    payload=bytes([10,0x83,0x08,0xB0,0x40,0x14,0x0E,0x10])
    np.testing.assert_array_equal(complex_values(s,payload,7),[10,12,9,9,14,13,13])
    struct.pack_into('>fHH',s,11,-2.,0x8001,0x8001)
    np.testing.assert_array_equal(complex_values(s,payload,7),[30,40,25,25,50,45,45])
    for bad in (payload[:-1],payload+b'\x00'):
        with pytest.raises(ValueError):complex_values(s,bad,7)


def test_order2_and_zero_width_constant_group():
    # 5,7,10,12,13 -> second differences 1,-1,-1; min -1.
    # Dummy first two values: 0,0,2,0,0 at 2 bits -> 00001000 00000000.
    s=section(5,1,0,2,0,5,0,5,2)
    np.testing.assert_array_equal(complex_values(s,bytes([5,7,0x81,0x08,0x00]),5),[5,7,10,12,13])
    s=section(4,1,0,0,0,4,0,4,1)
    np.testing.assert_array_equal(complex_values(s,bytes([10,1]),4),[10,11,12,13])
    s[22]=1
    with pytest.raises(ValueError,match='missing'):complex_values(s,bytes([10,1]),4)


def test_gfs_rejects_grid_relative_vectors_and_invalid_scan():
    g=bytearray(72)
    struct.pack_into('>I',g,6,6)
    struct.pack_into('>IIII',g,30,3,2,0,0xffffffff)
    struct.pack_into('>II',g,46,1000000,0)
    struct.pack_into('>IIII',g,55,0,2000000,1000000,1000000)
    lon,lat=regular_grid(g)
    np.testing.assert_array_equal(lon,[0,1,2])
    np.testing.assert_array_equal(lat,[1,0])
    g[54]=8
    with pytest.raises(ValueError,match='geographic'):regular_grid(g)
    g[54]=0;g[71]=64
    with pytest.raises(ValueError,match='scan'):regular_grid(g)


def test_cf_storage_unpacks_once_and_preserves_mask(tmp_path):
    p=tmp_path/'packed.nc'
    with Dataset(p,'w') as d:
        for n,size in [('time',2),('lat',2),('lon',2)]:d.createDimension(n,size)
        v=d.createVariable('ssu','i2',('time','lat','lon'),fill_value=-30000)
        v.standard_name='eastward_sea_water_velocity';v.units='m/s'
        v.scale_factor=np.float32(.001);v.add_offset=np.float32(0)
        v.set_auto_maskandscale(False)
        v[:]=np.array([[[123,-30000],[-456,789]]]*2,dtype=np.int16)
        v.set_auto_maskandscale(True)
        decoded,meta=packed_cf(v,'eastward_sea_water_velocity','m/s')
        assert meta['unpacking_count']==1 and np.ma.getmaskarray(decoded)[:,0,1].all()
        np.testing.assert_allclose(decoded[0,0,0],.123,atol=1e-7)
        with pytest.raises(ValueError,match='mapping'):packed_cf(v,'eastward_sea_ice_velocity','m/s')
        t=d.createVariable('time','f8',('time',));t.units='hours since 2025-08-29 00:00:00';t[:]=[0,24]
        assert native_times(d,'time')==['2025-08-29T00:00:00+00:00','2025-08-30T00:00:00+00:00']
        r=d.createVariable('source_reference_time','f8',('time',));r.units=t.units;r[:]=[-6,18]
        assert native_times(d,'source_reference_time','time')[0]=='2025-08-28T18:00:00+00:00'


def test_cross_day_coverage_cannot_hide_gap_or_duplicate():
    times=['2025-08-29T21:00:00+00:00','2025-08-30T00:00:00+00:00','2025-08-30T03:00:00+00:00']
    window=['2025-08-29T22:00:00+00:00','2025-08-30T00:46:18+00:00']
    assert coverage(times,window,10800)['time_count']==3
    for wrong in (times[::2],times+[times[-1]],times[:-1]):
        with pytest.raises(ValueError):coverage(wrong,window,10800)


@pytest.mark.parametrize('name',['../bad','/abs','C:/bad','a/../b','a\\b'])
def test_archive_paths_cannot_escape_destination(name):
    with pytest.raises(ValueError,match='unsafe'):member_path(name)


def test_import_detects_member_corruption_and_refuses_overwrite(tmp_path):
    sha=lambda b:hashlib.sha256(b).hexdigest()
    sums=(sha(b'123')+'  raw/data.bin\n').encode()
    zpath=tmp_path/'package.zip'
    with zipfile.ZipFile(zpath,'w') as z:
        z.writestr('package/SHA256SUMS.txt',sums)
        z.writestr('package/raw/data.bin',b'123')
    folder,report=checked_package(zpath,sha(zpath.read_bytes()),sha(sums),tmp_path/'raw')
    assert report['verified_members']==1
    (folder/'raw/data.bin').write_bytes(b'xxx')
    with pytest.raises(ValueError,match='refusing overwrite'):
        checked_package(zpath,sha(zpath.read_bytes()),sha(sums),tmp_path/'raw')
    with zipfile.ZipFile(zpath,'w') as z:
        z.writestr('package/SHA256SUMS.txt',sums)
        z.writestr('package/raw/data.bin',b'124')
    with pytest.raises(ValueError,match='member SHA'):
        checked_package(zpath,sha(zpath.read_bytes()),sha(sums),tmp_path/'new')


def test_extension_manifest_preserves_lake_and_stage_labels():
    base=json.loads((ROOT/'data/manifests/historical_sources.json').read_bytes())
    original=deepcopy(base)
    record=dict(scenario='arctic_ocean',pair_status='verified',verification_scope='B1_delivered_files_local',
                B2_completed=False,B3_completed=False)
    merged=extend_manifest(base,[record],base['config_sha256'])
    assert base==original
    assert next(c for c in merged['scenarios'] if c['scenario']=='lake_ontario')==next(
        c for c in base['scenarios'] if c['scenario']=='lake_ontario')
    assert next(c for c in merged['scenarios'] if c['scenario']=='arctic_ocean')['B3_completed'] is False
    with pytest.raises(ValueError,match='unverified'):
        extend_manifest(base,[record|{'pair_status':'blocked'}],base['config_sha256'])


def test_delivered_gfs_compares_to_independent_reference_if_available():
    root=ROOT/'data/raw/historical/ASAR_B1_HudsonsBay_20250829'
    if not root.exists():pytest.skip('local Hudsons Bay package absent')
    reference=json.loads((root/'validation_download_environment.json').read_bytes())['wind_files'][0]
    result=decode((root/reference['file']).read_bytes())
    for i in range(2):
        a=result['uv'][...,i]
        r=reference['messages'][i]['statistics']
        np.testing.assert_allclose([a.min(),a.max(),a.mean(),a.std()],
                                   [r[k] for k in ('min','max','mean','std')],rtol=0,atol=1e-10)


def test_delivered_hycom_360_longitudes_and_valid_time_not_global_origin():
    root=ROOT/'data/raw/historical/ASAR_B1_HudsonsBay_20250829'
    if not root.exists():pytest.skip('local Hudsons Bay package absent')
    ref=json.loads((root/'validation_download_environment.json').read_bytes())['current']['files'][0]
    result=hycom((root/ref['file']).read_bytes(),
                 dict(lkp_lon_lat=[-90.6,62.85],csp_lon_lat=[-90.447,62.786]),ref)
    assert result['lon_lat_bounds'][0]==-92
    assert result['valid_times_utc'][0]=='2025-08-28T21:00:00+00:00'
    assert result['ignored_global_time_origin'].startswith('2025-12-31')
    assert result['statistics']['ssu']['missing_or_nonfinite']>0
    assert result['encoding']['ssu']['unpacking_count']==1
    assert result['points']['LKP']['bilinear_2x2_stencil_valid_all_times']
