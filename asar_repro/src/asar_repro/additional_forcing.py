"""Audited additional historical surface forcing. Frozen readers stay unchanged.

ROMS: arithmetic two-face collocation on interior rho nodes, rotate xi/eta
to east/north at those nodes, then interpolate on native-topology triangles.
No extrapolation, coastal fill, hidden velocity fallback, or ice drift.
"""
from datetime import datetime, timezone
import json
from pathlib import Path

from netCDF4 import Dataset, num2date
import numpy as np
from pyproj import Proj
from shapely import STRtree, points, polygons

from .forcing import SurfaceField, Rectilinear, HistoricalForcing, numeric, longitude
from .hrrr import f00_wind, require
from .opendrift_adapter import utc_datetime
from .scenarios import digest

MANIFEST_SHA='2d306909585ffd95992634ddc1e939d64d9af15c50f94547aadc55ca01f3d8fa'
SCENARIOS=('arctic_ocean','bay_of_fundy')


def checked_sources(root, name):
    root=Path(root);path=root/'data/manifests/historical_sources_additional_b1.json'
    require(digest(path)==MANIFEST_SHA,'additional B1 manifest fingerprint changed')
    doc=json.loads(path.read_text(encoding='utf-8'))
    require(digest(root/'configs/stage7_scenarios.yaml')==doc['config_sha256'],'mission fingerprint changed')
    require(name in SCENARIOS,'unsupported additional scenario')
    case=next(c for c in doc['scenarios'] if c['scenario']==name)
    require(case['pair_status']=='verified' and case['verification_scope']=='B1_delivered_files_local'
            and case['forcing_kind']=='historical_real','B1 pair not verified')
    for role in ('wind','current'):
        for row in case[role]['local_files']:
            require(digest(root/row['local_path'])==row['sha256'],'forcing SHA mismatch: '+row['local_path'])
    return case


def cf_times(var, expected):
    require(getattr(var,'calendar','standard') in ('standard','gregorian','proleptic_gregorian'),'calendar')
    values=numeric(var[:]);require(np.isfinite(values).all(),'missing times')
    # CF time units without an explicit zone default to UTC; verify against B1 UTC records.
    converted=num2date(values,var.units,calendar=getattr(var,'calendar','standard'))
    result=tuple(datetime(t.year,t.month,t.day,t.hour,t.minute,t.second,t.microsecond,tzinfo=timezone.utc) for t in converted)
    require(result==tuple(map(utc_datetime,expected)),'decoded UTC differs from B1 valid times')
    return result


def mission_roi(case, buffer_m=150000):
    xy=np.asarray([case['mission'][k] for k in ('lkp_lon_lat','csp_lon_lat')])
    dy=buffer_m/110000;dx=buffer_m/(110000*np.cos(np.deg2rad(xy[:,1].mean())))
    return [float(xy[:,0].min()-dx),float(xy[:,0].max()+dx),float(xy[:,1].min()-dy),float(xy[:,1].max()+dy)]


def wind_field(root, case):
    files=sorted(case['wind']['local_files'],key=lambda r:r['valid_utc'])
    times=[];frames=[];geometry=None;roi=mission_roi(case)
    for row in files:
        data=(root/row['local_path']).read_bytes()
        if case['scenario']=='arctic_ocean':
            from b1_gfs import decode
            d=decode(data);time=d['valid'];proj=None
            ox=np.argsort(longitude(d['lon']));oy=np.argsort(d['lat'])
            x=longitude(d['lon'])[ox];y=d['lat'][oy];raw=d['uv']
            full=raw[oy][:,ox];basis='geographic_east_north'
            require(d['cycle']==utc_datetime(row['run_cycle_utc']) and d['lead_hours']==row['lead_hours'],'GFS cycle/lead')
        else:
            time,_,proj,x,y,raw=f00_wind(data);full=raw;basis='grid_relative'
        require(time==utc_datetime(row['valid_utc']),'wind valid time differs')
        # Independent B1/ecCodes native-node controls, before crop or rotation.
        for k,comp in enumerate(('10u','10v')):
            for ref in row['components'][comp]['points'].values():
                require(abs(float(raw.reshape(-1,2)[ref['flat_index'],k])-ref['native_component_m_s'])<1e-10,'native wind reference mismatch')
        lon=np.r_[np.linspace(roi[0],roi[1],25),np.linspace(roi[0],roi[1],25),np.full(25,roi[0]),np.full(25,roi[1])]
        lat=np.r_[np.full(25,roi[2]),np.full(25,roi[3]),np.linspace(roi[2],roi[3],25),np.linspace(roi[2],roi[3],25)]
        xx,yy=(lon,lat) if proj is None else proj(lon,lat)
        i0=max(0,np.searchsorted(x,min(xx))-2);i1=min(len(x),np.searchsorted(x,max(xx))+3)
        j0=max(0,np.searchsorted(y,min(yy))-2);j1=min(len(y),np.searchsorted(y,max(yy))+3)
        key=(i0,i1,j0,j1)
        if geometry is None:geometry=key;grid=Rectilinear(x[i0:i1].copy(),y[j0:j1].copy(),proj)
        require(key==geometry and np.array_equal(grid.x,x[i0:i1]) and np.array_equal(grid.y,y[j0:j1]),'wind grid changes')
        frames.append(full[j0:j1,i0:i1].copy());times.append(time)
    return SurfaceField('wind',tuple(times),grid,np.stack(frames),files,
        dict(vector_basis=basis,native_variables=['UGRD','VGRD'],height_m=10,
             spatial_method='native bilinear; HRRR rotation at query using meridian convergence',
             in_memory_crop_indices=list(map(int,geometry)),roi_lon_lat=roi,
             original_bytes_unchanged=True,native_reference_checks=2*2*len(files)),
        max_gap_s=10800 if case['scenario']=='arctic_ocean' else 3600)


def hycom_field(root, files):
    times=[];frames=[];lon=lat=None;ice=[]
    for row in files:
        with Dataset('hycom.nc',memory=(root/row['local_path']).read_bytes()) as ds:
            x=longitude(numeric(ds['lon'][:]));y=numeric(ds['lat'][:])
            if lon is None:lon,lat=x,y
            require(np.array_equal(x,lon) and np.array_equal(y,lat),'HYCOM grid changes')
            times.extend(cf_times(ds['time'],row['valid_times_utc']))
            uv=[]
            for key,standard in (('ssu','eastward_sea_water_velocity'),('ssv','northward_sea_water_velocity')):
                v=ds[key]
                require(v.dimensions==('time','lat','lon') and v.units=='m/s' and v.standard_name==standard,'HYCOM mapping')
                uv.append(numeric(v[:]))  # netCDF4 has already applied exactly one CF unpack.
            ice_values=numeric(ds['sic'][:]);wet=np.isfinite(uv[0])&np.isfinite(uv[1])
            require(ds['sic'].standard_name=='sea_ice_area_fraction' and ds['sic'].units=='1','HYCOM ice mapping')
            require(np.isfinite(ice_values[wet]).all() and np.all(ice_values[wet]==0),'nonzero or unknown ice: this Leeway experiment has no ice interaction model')
            require(np.array_equal(np.isfinite(uv[0]),np.isfinite(uv[1])),'HYCOM component masks differ')
            frames.extend(np.stack(uv,axis=-1));ice.append(float(np.max(ice_values[wet])))
    order=np.argsort([t.timestamp() for t in times]);times=tuple(times[i] for i in order)
    return SurfaceField('current',times,Rectilinear(lon,lat),np.stack(frames)[order],files,
        dict(vector_basis='geographic_east_north',native_variables=['ssu','ssv'],
             spatial_method='bilinear on native longitude/latitude; masks retained',
             ice_max=ice,ice_policy='zero verified on all native wet samples; no sea-ice velocity used',
             missing_policy='NaN velocities -> unknown; never fill zero',CF_unpack_count=1),max_gap_s=3600)


def collocate_rotate(u,v,angle,rho_wet,u_wet,v_wet):
    """Two native faces per interior rho node; missing coastal stencils remain invalid."""
    shape=angle.shape;require(u.shape==(*rho_wet.shape[:-2],shape[0],shape[1]-1) and
        v.shape==(*rho_wet.shape[:-2],shape[0]-1,shape[1]),'ROMS staggered dimensions')
    require(u_wet.shape==u.shape and v_wet.shape==v.shape and rho_wet.shape[-2:]==shape,'ROMS mask dimensions')
    ur=.5*(u[...,1:-1,:-1]+u[...,1:-1,1:])
    vr=.5*(v[...,:-1,1:-1]+v[...,1:,1:-1])
    wet=rho_wet[...,1:-1,1:-1].astype(bool)
    faces=u_wet[...,1:-1,:-1]&u_wet[...,1:-1,1:]&v_wet[...,:-1,1:-1]&v_wet[...,1:,1:-1]
    valid=wet&faces&np.isfinite(ur)&np.isfinite(vr)
    a=angle[1:-1,1:-1];c,s=np.cos(a),np.sin(a)
    east=c*ur-s*vr;north=s*ur+c*vr
    status=np.where(~wet,0,np.where(valid,1,2))
    return np.stack((np.where(valid,east,np.nan),np.where(valid,north,np.nan),status),axis=-1)


class TopologyTriangles:
    """Piecewise affine on two fixed triangles per native quadrilateral; no Delaunay bridging."""
    def __init__(self,lon,lat,projection):
        require(lon.shape==lat.shape and lon.ndim==2 and min(lon.shape)>=2,'curvilinear geometry shape')
        self.shape=lon.shape;self.projection=projection
        x,y=projection(lon,lat);self.xy=np.column_stack((x.ravel(),y.ravel()))
        ids=np.arange(lon.size).reshape(lon.shape);a=ids[:-1,:-1].ravel();b=ids[:-1,1:].ravel();c=ids[1:,1:].ravel();d=ids[1:,:-1].ravel()
        self.tri=np.concatenate((np.column_stack((a,b,c)),np.column_stack((a,c,d))))
        coords=self.xy[self.tri];self.origin=coords[:,0];m=np.stack((coords[:,1]-coords[:,0],coords[:,2]-coords[:,0]),axis=-1)
        det=np.linalg.det(m);require(np.isfinite(m).all() and np.all(abs(det)>1e-6),'degenerate curvilinear triangles')
        require(np.all(np.sign(det)==np.sign(det[0])),'folded curvilinear topology')
        self.inverse=np.linalg.inv(m);self.tree=STRtree(polygons(coords))

    def locate(self,lon,lat):
        x,y=self.projection(lon,lat);query=np.column_stack((x,y))
        pids,tids=self.tree.query(points(x,y),predicate='intersects')
        chosen=np.full(len(query),len(self.tri),dtype=int);np.minimum.at(chosen,pids,tids)
        inside=chosen<len(self.tri);safe=np.where(inside,chosen,0)
        ab=np.einsum('nij,nj->ni',self.inverse[safe],query-self.origin[safe])
        weights=np.column_stack((1-ab.sum(axis=1),ab))
        weights=np.maximum(weights,0);weights/=weights.sum(axis=1)[:,None]
        return safe,weights,inside

    def sample(self,values,location):
        chosen,w,inside=location
        nodes=values.reshape(-1,3)[self.tri[chosen]];used=w>1e-12
        state=nodes[:,:,2]
        good=np.all(~used|(state==1),axis=1);dry=np.all(~used|(state==0),axis=1)
        result=np.sum(np.where(used[:,:,None],nodes[:,:,:2],0)*w[:,:,None],axis=1)
        status=np.where(~inside,'outside_mesh',np.where(dry,'dry',np.where(good,'ok','masked_stencil')))
        return np.where((status=='ok')[:,None],result,np.nan),status


def gomofs_field(root, files, case):
    require(len(files)==1,'expected delivered time-concatenated GoMOFS file')
    row=files[0];roi=mission_roi(case)
    with Dataset('gomofs.nc',memory=(root/row['local_path']).read_bytes()) as ds:
        times=cf_times(ds['ocean_time'],row['valid_times_utc'])
        lon,lat=numeric(ds['lon_rho'][:]),numeric(ds['lat_rho'][:])
        use=(lon>=roi[0])&(lon<=roi[1])&(lat>=roi[2])&(lat<=roi[3]);jj,ii=np.nonzero(use)
        require(len(jj)>0,'mission ROI outside GoMOFS')
        j0=max(0,int(jj.min())-3);j1=min(lon.shape[0],int(jj.max())+4)
        i0=max(0,int(ii.min())-3);i1=min(lon.shape[1],int(ii.max())+4)
        angle=numeric(ds['angle'][j0:j1,i0:i1]);require(ds['angle'].units=='radians' and np.isfinite(angle).all(),'ROMS angle')
        require(ds['u_sur'].standard_name=='sea_water_surface_x_velocity' and ds['v_sur'].standard_name=='sea_water_surface_y_velocity','ROMS vector basis')
        require(ds['u_sur'].dimensions==('ocean_time','eta_u','xi_u') and ds['v_sur'].dimensions==('ocean_time','eta_v','xi_v'),'ROMS variable dimensions')
        require(ds['u_sur'].units==ds['v_sur'].units=='meter second-1','ROMS units')
        arrays={};masks={}
        for g,ys,xs in [('rho',slice(j0,j1),slice(i0,i1)),('u',slice(j0,j1),slice(i0,i1-1)),('v',slice(j0,j1-1),slice(i0,i1))]:
            static=numeric(ds['mask_'+g][ys,xs]);dynamic=numeric(ds['wetdry_mask_'+g][:,ys,xs])
            require(np.isin(static,[0,1]).all() and np.isin(dynamic,[0,1]).all(),'ROMS mask values')
            masks[g]=(static==1)&(dynamic==1)
            if g!='rho':arrays[g]=numeric(ds[g+'_sur'][:,ys,xs])
        values=collocate_rotate(arrays['u'],arrays['v'],angle,masks['rho'],masks['u'],masks['v'])
        x,y=case['mission']['csp_lon_lat'];projection=Proj(proj='aeqd',lon_0=x,lat_0=y,datum='WGS84',units='m')
        mesh=TopologyTriangles(lon[j0+1:j1-1,i0+1:i1-1],lat[j0+1:j1-1,i0+1:i1-1],projection)
    return SurfaceField('current',times,mesh,values,files,
        dict(vector_basis='geographic_east_north',native_variables=['u_sur','v_sur'],
             spatial_method='native two-face mean at rho; angle rotation at rho; native-topology triangular interpolation',
             rotation='east=cos(angle)*u-sin(angle)*v; north=sin(angle)*u+cos(angle)*v',
             rho_crop=[j0+1,j1-1,i0+1,i1-1],wet_policy='static AND dynamic masks on rho/u/v; mixed or unsupported stencil unknown',
             original_parent_files_reverified_locally=False,roi_lon_lat=roi),max_gap_s=3600)


def load_additional_forcing(root, name, *, window=None):
    root=Path(root);case=checked_sources(root,name)
    wind=wind_field(root,case)
    current=hycom_field(root,case['current']['local_files']) if name=='arctic_ocean' else gomofs_field(root,case['current']['local_files'],case)
    return HistoricalForcing(wind,current,case['requested_window_utc'] if window is None else window,'historical_real'),case
