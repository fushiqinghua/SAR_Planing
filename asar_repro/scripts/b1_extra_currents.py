"""B1 inspection of delivered HYCOM/GoMOFS bytes; not an OpenDrift reader."""

from datetime import datetime, timezone

from netCDF4 import Dataset, num2date
import numpy as np

from asar_repro.hrrr import require


def stats(a):
    x = np.ma.asarray(a, dtype=float).filled(np.nan)
    valid = x[np.isfinite(x)]
    require(valid.size > 0, "no valid values")
    return dict(total=x.size, valid=valid.size, missing_or_nonfinite=x.size-valid.size,
                min=float(valid.min()), max=float(valid.max()), mean=float(valid.mean()), std=float(valid.std()))


def check_stats(a, expected):
    actual = stats(a)
    for key, value in actual.items():
        np.testing.assert_allclose(value, expected[key], rtol=1e-10, atol=1e-10,
                                   err_msg="independent reference disagreement: " + key)
    return actual


def native_times(ds, name, dimension=None):
    v = ds[name]
    require(v.dimensions == (name if dimension is None else dimension,) and getattr(v, "calendar", "standard") in
            ("standard", "gregorian", "proleptic_gregorian"), "invalid calendar/time axis")
    result = num2date(v[:], v.units, calendar=getattr(v, "calendar", "standard"))
    return [datetime(t.year, t.month, t.day, t.hour, t.minute, t.second,
                     tzinfo=timezone.utc).isoformat() for t in result]


def packed_cf(v, standard, units):
    """Prove exactly one CF unpacking, including masks, against native integers."""
    require(v.standard_name == standard and v.units == units and v.dimensions == ("time", "lat", "lon"),
            "HYCOM variable mapping/dimensions/units mismatch")
    require(v.dtype == np.dtype("int16") and v._FillValue == -30000,
            "unexpected HYCOM packed storage")
    v.set_auto_maskandscale(False)
    raw = v[:]
    v.set_auto_maskandscale(True)
    decoded = v[:]
    mask = raw == v._FillValue
    np.testing.assert_array_equal(np.ma.getmaskarray(decoded), mask)
    expected = raw * v.scale_factor + v.add_offset
    np.testing.assert_array_equal(np.asarray(decoded)[~mask], expected[~mask])
    return np.ma.asarray(decoded), dict(storage=str(v.dtype), scale_factor=float(v.scale_factor),
                                       add_offset=float(v.add_offset), fill_value=int(v._FillValue),
                                       unpacking_count=1, mask_preserved=True)


def hycom(data, case, reference):
    with Dataset("hycom.nc", memory=data) as d:
        require("ESPC-D V02" in d.generating_model and "HYCOM" in d.source, "unexpected HYCOM product")
        lon = (np.asarray(d['lon'][:]) + 180) % 360 - 180
        lat = np.asarray(d['lat'][:])
        require(d['lon'].units == 'degrees_east' and d['lat'].units == 'degrees_north', "HYCOM coordinates")
        require(np.all(np.diff(lon) > 0) and np.all(np.diff(lat) > 0), "HYCOM axis order")
        times = native_times(d, 'time')
        require(times == reference['valid_times_utc'], "HYCOM valid times differ")
        fields, encoding, summaries = {}, {}, {}
        for k, standard in [('ssu', 'eastward_sea_water_velocity'),
                            ('ssv', 'northward_sea_water_velocity'), ('sic', 'sea_ice_area_fraction')]:
            a, enc = packed_cf(d[k], standard, '1' if k == 'sic' else 'm/s')
            fields[k], encoding[k] = a, enc
            summaries[k] = check_stats(a, reference['all_water_ice_fraction_statistics'] if k == 'sic'
                                      else reference['native_variables'][k])
        mask = np.ma.getmaskarray(fields['ssu'])
        require(np.array_equal(mask, np.ma.getmaskarray(fields['ssv']))
                and np.all(mask == mask[0]), "HYCOM U/V or temporal mask disagreement")
        require(np.max(np.abs(fields['ssu'])) < 20 and np.max(np.abs(fields['ssv'])) < 20,
                "implausible decoded current speed")
        require(np.min(fields['sic']) >= 0 and np.max(fields['sic']) <= 1, "invalid ice fraction")
        points = {}
        for name, (x, y) in {'LKP':case['lkp_lon_lat'], 'CSP':case['csp_lon_lat']}.items():
            j, i = np.searchsorted(lon, x)-1, np.searchsorted(lat, y)-1
            require(0 <= j < len(lon)-1 and 0 <= i < len(lat)-1, "point outside HYCOM subset")
            require(not mask[:, i:i+2, j:j+2].any(), "HYCOM interpolation stencil contains missing data")
            jn, inn = int(np.argmin(abs(lon-x))), int(np.argmin(abs(lat-y)))
            rec = dict(bilinear_2x2_stencil_valid_all_times=True,
                       nearest_lon_lat=[float(lon[jn]), float(lat[inn])])
            for key, field in [('east_m_s','ssu'),('north_m_s','ssv'),('sea_ice_fraction','sic')]:
                rec[key] = fields[field][:,inn,jn].tolist()
                np.testing.assert_array_equal(rec[key], reference['point_checks'][name][key])
            np.testing.assert_array_equal(rec['nearest_lon_lat'],reference['point_checks'][name]['nearest_lon_lat'])
            points[name] = rec
        return dict(valid_times_utc=times, native_variables=['ssu','ssv'], auxiliary=['sic'], units='m/s',
                    encoding=encoding, statistics=summaries, points=points,
                    dimensions={k:len(v) for k,v in d.dimensions.items()},
                    lon_lat_bounds=[float(lon.min()),float(lon.max()),float(lat.min()),float(lat.max())],
                    vector_basis='geographic_east_north', mask_policy='retain; never fill missing water with zero',
                    time_units=d['time'].units, time_zone_policy='CF default zero offset; compared to UTC source records',
                    ignored_global_time_origin=d.time_origin,
                    run_cycle_status='annual_archive_per_frame_lineage_not_fully_verified')


def gomofs(data, case, reference, extraction):
    """Recheck delivered native fields; absent original parent files are NOT reverified."""
    with Dataset('gomofs.nc', memory=data) as d:
        times = native_times(d, 'ocean_time')
        require(len(times) == 13, 'GoMOFS time count')
        result = dict(valid_times_utc=times, native_variables={}, points={},
                      dimensions={k:len(v) for k,v in d.dimensions.items()},
                      vector_basis='ROMS_native_staggered_xi_eta_requires_collocation_and_rotation',
                      original_parent_files_reverified_locally=False,
                      extraction_claim_scope='13 parent comparisons reported by download environment only')
        for k, grid, std in [('u_sur','u','sea_water_surface_x_velocity'),
                             ('v_sur','v','sea_water_surface_y_velocity')]:
            v = d[k]
            require(v.units == 'meter second-1' and v.standard_name == std and
                    v.dimensions == ('ocean_time','eta_'+grid,'xi_'+grid), 'GoMOFS component mapping')
            a = np.ma.asarray(v[:],dtype=float).filled(np.nan)
            static, dynamic = d['mask_'+grid][:], d['wetdry_mask_'+grid][:]
            require(np.isin(static,[0,1]).all() and np.isin(dynamic,[0,1]).all(), 'GoMOFS wet/dry mask')
            wet = (static[None,:,:] == 1) & (dynamic == 1)
            require(np.isfinite(a[wet]).all() and np.abs(a[wet]).max() < 20, 'GoMOFS wet current invalid')
            result['native_variables'][k] = dict(units=v.units, standard_name=std, dimensions=list(v.dimensions),
                wet_statistics=check_stats(a[wet],reference['native_variables'][k]['wet_statistics']),
                whole_array_statistics=check_stats(a,reference['native_variables'][k]['whole_array_statistics']))
        for name,(x,y) in {'LKP':case['lkp_lon_lat'],'CSP':case['csp_lon_lat']}.items():
            points = {}
            for grid in ('rho','u','v'):
                lon, lat = d['lon_'+grid][:], d['lat_'+grid][:]
                dist = np.hypot((lon-x)*np.cos(np.deg2rad(y)),lat-y)*111195
                i,j = np.unravel_index(np.argmin(dist),dist.shape)
                require(dist[i,j] < 1200 and d['mask_'+grid][i,j] == 1 and
                        np.all(d['wetdry_mask_'+grid][:,i,j] == 1), 'GoMOFS task point not wet/covered')
                ref = reference['point_checks'][name][grid]
                require([int(i),int(j)] == ref['index'], 'GoMOFS independent point index mismatch')
                points[grid] = dict(index=[int(i),int(j)],distance_m_approx=float(dist[i,j]),always_wet=True)
                if grid in ('u','v'):
                    values = d[grid+'_sur'][:,i,j]
                    require(not np.ma.getmaskarray(values).any(), 'GoMOFS point missing')
                    np.testing.assert_array_equal(values,ref['native_component_m_s'])
                    points[grid]['native_component_m_s'] = values.tolist()
            result['points'][name] = points
        angle = d['angle'][:]
        require(d['angle'].units in ('radian','radians') and np.isfinite(angle).all(), 'GoMOFS angle units')
        result['angle_radians_range'] = [float(angle.min()),float(angle.max())]
        np.testing.assert_allclose(result['angle_radians_range'],reference['angle_radians_range'],rtol=0,atol=1e-12)
        result['source_cycles_utc'] = native_times(d,'source_reference_time','ocean_time')
        require(result['source_cycles_utc'] == reference['source_cycles_utc'], 'GoMOFS reference cycles')
        declared = [row['valid_time_utc'] for row in extraction['source_files']]
        require([datetime.fromisoformat(t).isoformat() for t in declared] == times, 'GoMOFS source valid time')
        lon,lat = d['lon_rho'][:],d['lat_rho'][:]
        result['lon_lat_bounds'] = [float(lon.min()),float(lon.max()),float(lat.min()),float(lat.max())]
        result['time_units'] = d['ocean_time'].units
        return result
