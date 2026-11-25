"""Synthetic reader invariants before additional real-data use."""
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
import numpy as np
import pytest
from netCDF4 import Dataset
from pyproj import Proj
from asar_repro.additional_forcing import collocate_rotate,TopologyTriangles,cf_times,checked_sources,hycom_field
from asar_repro.forcing import SurfaceField,Rectilinear
from asar_repro.historical_reader import SurfaceReader


@pytest.mark.parametrize('angle',[0,np.pi/2,-np.pi/2,.37])
def test_staggered_affine_faces_collocate_and_rotate_exactly(angle):
    # u at (i+.5,j), v at (i,j+.5); expected rho (i,j).
    j,i=np.mgrid[:5,:5];ju,iu=np.mgrid[:5,:4];jv,iv=np.mgrid[:4,:5]
    u=2*(iu+.5)+3*ju;v=-iv+4*(jv+.5)
    result=collocate_rotate(u,v,np.full((5,5),angle),np.ones((5,5),bool),np.ones((5,4),bool),np.ones((4,5),bool))
    ur=(2*i+3*j)[1:-1,1:-1];vr=(-i+4*j)[1:-1,1:-1]
    np.testing.assert_allclose(result[...,0],np.cos(angle)*ur-np.sin(angle)*vr,atol=1e-13)
    np.testing.assert_allclose(result[...,1],np.sin(angle)*ur+np.cos(angle)*vr,atol=1e-13)
    assert np.all(result[...,2]==1)


@pytest.mark.parametrize('which',['rho','u','v','missing'])
def test_dynamic_and_face_masks_never_become_zero_velocity(which):
    u=np.ones((2,5,4));v=np.full((2,4,5),2.)
    r=np.ones((2,5,5),bool);um=np.ones_like(u,bool);vm=np.ones_like(v,bool)
    if which=='rho':r[1,2,2]=False
    elif which=='u':um[1,2,1]=False
    elif which=='v':vm[1,1,2]=False
    else:u[1,2,1]=np.nan
    out=collocate_rotate(u,v,np.zeros((5,5)),r,um,vm)
    np.testing.assert_array_equal(out[0,1,1],[1,2,1])
    assert np.isnan(out[1,1,1,:2]).all()
    assert out[1,1,1,2]==(0 if which=='rho' else 2)


def mesh():
    j,i=np.mgrid[:4,:4];projection=Proj(proj='aeqd',lon_0=-65,lat_0=45,datum='WGS84')
    x=(1000*i+100*j).astype(float);y=(900*j+50*i).astype(float)
    lon,lat=projection(x,y,inverse=True)
    return TopologyTriangles(lon,lat,projection),projection,x,y


@pytest.mark.parametrize('fraction',[0.,.4,1.])
def test_topology_affine_interpolation_and_UTC_time(fraction):
    m,proj,x,y=mesh();t=datetime(2025,1,1,tzinfo=timezone.utc)
    values=np.stack((.001*x+.002*y,.003*x-.001*y,np.ones_like(x)),axis=-1)
    second=values.copy();second[...,:2]+=4
    f=SurfaceField('current',(t,t+timedelta(hours=1)),m,np.stack((values,second)),[],{},3600)
    xx,yy=1220.,1270.;lon,lat=proj(xx,yy,inverse=True)
    expected=np.array([.001*xx+.002*yy,.003*xx-.001*yy])+4*fraction
    uv,status=f.probe(t+timedelta(hours=fraction),[lon],[lat])
    assert status.tolist()==['ok'];np.testing.assert_allclose(uv[0],expected,atol=1e-8)
    od=SurfaceReader(f);out=od.get_variables(od.variables,(t+timedelta(hours=fraction)).replace(tzinfo=None),np.array([lon]),np.array([lat]),np.array([0.]))
    np.testing.assert_allclose([out[k][0] for k in od.variables],expected,atol=1e-8)


@pytest.mark.parametrize('kind',['dry','mixed','outside','missing'])
def test_mesh_unavailability_categories(kind):
    m,proj,x,y=mesh();values=np.stack((x*0+1,x*0+2,x*0+1),axis=-1)
    if kind=='dry':values[...,2]=0;values[...,:2]=np.nan
    elif kind=='mixed':values[1,1,2]=0;values[1,1,:2]=np.nan
    elif kind=='missing':values[...,2]=2;values[...,:2]=np.nan
    lon,lat=proj(-1000,-1000,inverse=True) if kind=='outside' else proj(1210,1110,inverse=True)
    uv,status=m.sample(values,m.locate(np.array([lon]),np.array([lat])))
    assert status[0]=={'dry':'dry','mixed':'masked_stencil','missing':'masked_stencil','outside':'outside_mesh'}[kind]
    assert np.isnan(uv).all()


def test_exact_node_does_not_use_zero_weight_dry_corner():
    m,proj,x,y=mesh();values=np.stack((x*0+1,x*0+2,x*0+0),axis=-1)
    values[1,1,2]=1
    lon,lat=proj(x[1,1],y[1,1],inverse=True)
    uv,status=m.sample(values,m.locate(np.array([lon]),np.array([lat])))
    assert status[0]=='ok';np.testing.assert_allclose(uv,[[1,2]],atol=1e-9)


def test_rectilinear_longitude_and_time_extrapolation_rejected():
    t=datetime(2025,1,1,tzinfo=timezone.utc)
    f=SurfaceField('current',(t,t+timedelta(hours=1)),Rectilinear(np.array([-92.,-90.,-88.]),np.array([61.,62.,63.])),np.ones((2,3,3,2)),[],{},3600)
    np.testing.assert_array_equal(f.sample(t,[270],[62]),[[1,1]])
    assert f.probe(t-timedelta(seconds=1),[-90],[62])[1][0]=='outside_time'
    assert f.probe(t,[-80],[62])[1][0]=='outside_grid'


def test_cf_default_UTC_must_match_independent_expected_times(tmp_path):
    file=tmp_path/'clock.nc';t=datetime(2025,1,1,tzinfo=timezone.utc)
    with Dataset(file,'w') as d:
        d.createDimension('time',2);v=d.createVariable('time','f8',('time',));v.units='hours since 2025-01-01 00:00:00';v[:]=[0,1]
    with Dataset(file) as d:
        assert cf_times(d['time'],[t.isoformat(),(t+timedelta(hours=1)).isoformat()])==(t,t+timedelta(hours=1))
        with pytest.raises(ValueError,match='UTC'):cf_times(d['time'],[t.isoformat(),t.isoformat()])


def test_sha_guard_rejects_forged_manifest(tmp_path):
    p=tmp_path/'data/manifests';p.mkdir(parents=True);(p/'historical_sources_additional_b1.json').write_text('{}')
    with pytest.raises(ValueError,match='fingerprint'):checked_sources(tmp_path,'arctic_ocean')


def test_grid_shape_failures_are_explicit():
    with pytest.raises(ValueError,match='staggered'):collocate_rotate(np.ones((5,5)),np.ones((4,5)),np.zeros((5,5)),np.ones((5,5),bool),np.ones((5,5),bool),np.ones((4,5),bool))
    with pytest.raises(ValueError,match='degenerate'):TopologyTriangles(np.zeros((3,3)),np.zeros((3,3)),lambda x,y:(x,y))


def test_hycom_bytes_adapter_supports_nonascii_windows_paths(tmp_path):
    # netCDF C library may reject Unicode filenames; Python reads immutable bytes.
    source=tmp_path/'ascii.nc'
    with Dataset(source,'w') as d:
        for k,n in [('time',2),('lat',3),('lon',3)]:d.createDimension(k,n)
        time=d.createVariable('time','f8',('time',));time.units='hours since 2025-01-01 00:00:00';time[:]=[0,1]
        d.createVariable('lat','f8',('lat',))[:]=[61,62,63]
        d.createVariable('lon','f8',('lon',))[:]=[268,270,272]
        for key,std,value in [('ssu','eastward_sea_water_velocity',.2),('ssv','northward_sea_water_velocity',-.3),('sic','sea_ice_area_fraction',0)]:
            v=d.createVariable(key,'f8',('time','lat','lon'));v.standard_name=std;v.units='1' if key=='sic' else 'm/s';v[:]=value
    target=tmp_path/'真实流.nc';target.write_bytes(source.read_bytes())
    field=hycom_field(tmp_path,[dict(local_path=target.name,valid_times_utc=['2025-01-01T00:00:00Z','2025-01-01T01:00:00Z'])])
    np.testing.assert_allclose(field.sample('2025-01-01T00:30:00Z',[-90],[62]),[[.2,-.3]])
