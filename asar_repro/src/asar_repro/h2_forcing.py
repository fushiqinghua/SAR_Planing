"""Native historical forcing for H2, independent of the frozen B1 manifests."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

from netCDF4 import Dataset
import numpy as np

from .additional_forcing import cf_times, mission_roi
from .forcing import (
    HistoricalForcing, Rectilinear, SurfaceField, _archived_bytes,
    _current, _wind, longitude, numeric,
)
from .historical_drift import axes, utc_label
from .opendrift_adapter import utc_datetime
from .physical_followup_data import _MISSIONS, _sha


class DataIneligible(ValueError):
    """Verified forcing falls outside a preregistered source or model requirement."""


def mission_config(case):
    """Reuse the frozen mission geometry, changing only date and seed."""
    cfg = deepcopy(_MISSIONS[case["base_scene"]])
    if type(case["seed"]) is not int:
        raise ValueError("H2 seed must be a registered integer")
    cfg.update(incident_utc=case["lkp_utc"], cst_utc=case["cst_utc"], seed=case["seed"])
    _, target = axes(cfg)
    if utc_datetime(utc_label(target[-1])) != utc_datetime(case["end_utc"]):
        raise ValueError("H2 case end differs from the frozen physical horizon")
    return cfg


def expected_clock(block):
    day = datetime.fromisoformat(block["date"]).replace(tzinfo=timezone.utc)
    if block["scene"] == "lake_ontario":
        times = tuple(day + timedelta(hours=h) for h in range(13, 18))
        return times, times, times, (0,) * 5
    if block["scene"] == "arctic_ocean":
        cycle = day - timedelta(hours=6)
        leads = tuple(range(3, 34, 3))
        return (tuple(cycle + timedelta(hours=h) for h in leads),
                tuple(cycle + timedelta(hours=h) for h in range(3, 34)),
                (cycle,) * len(leads), leads)
    raise ValueError(f"Unregistered H2 scene: {block['scene']}")


def _source_file(root, block, row, *, path_key="local_path", hash_key="sha256"):
    relative = Path(row[path_key])
    root = root.resolve()
    source_dir = (root / "data/raw/h2" / block["id"]).resolve()
    path = (root / relative).resolve()
    if (relative.is_absolute() or ".." in relative.parts or not source_dir.is_relative_to(root)
            or not path.is_relative_to(source_dir)):
        raise ValueError(f"H2 raw path escaped the registered input directory: {relative}")
    if not path.is_file() or _sha(path) != row[hash_key]:
        raise ValueError(f"H2 source SHA-256 missing or inconsistent: {relative}")
    if path_key == "local_path" and path.stat().st_size != row["bytes"]:
        raise ValueError(f"H2 source length differs from receipt: {relative}")
    return path


def _order(rows, key):
    return tuple(utc_datetime(row[key]) for row in rows)


def verify_source_rows(root, block, manifest):
    if (manifest["block_id"], manifest["scene"], manifest["date"]) != (
        block["id"], block["scene"], block["date"]
    ):
        raise ValueError("H2 source manifest is for a different date or scene")
    want_wind, want_current, cycles, leads = expected_clock(block)
    wind, current = manifest["wind"], manifest["current"]
    if (_order(wind, "valid_utc") != want_wind or _order(wind, "run_cycle_utc") != cycles
            or tuple(row["lead_hours"] for row in wind) != leads):
        raise DataIneligible("Wind source cycle, lead or valid UTC sequence differs")
    if block["scene"] == "lake_ontario":
        if _order(current, "valid_utc") != want_current:
            raise DataIneligible("LOOFS must include exactly the five 13–17Z nowcast frames")
        expected_cycle = want_current[0].replace(hour=18)
        if _order(current, "run_cycle_utc") != (expected_cycle,) * 5:
            raise DataIneligible("LOOFS frame is outside the registered 18Z nowcast cycle")
    else:
        current_times = tuple(utc_datetime(stamp) for row in current for stamp in row["valid_times_utc"])
        if current_times != want_current:
            raise DataIneligible("HYCOM must include exactly 31 consecutive registered hourly frames")
    for row in wind + current:
        if not row["source_url"].startswith("https://"):
            raise ValueError("Native source receipt must identify an HTTPS source")
        _source_file(root, block, row)
    for row in wind:
        _source_file(root, block, row, path_key="index_path", hash_key="index_sha256")


def _hudson_wind(root, rows, cfg):
    from b1_gfs import decode

    frames, times = [], []
    roi = mission_roi({"mission": cfg})
    for row in rows:
        field = decode(_archived_bytes(root, row))
        lon, lat = field["lon"], field["lat"]
        if (field["cycle"] != utc_datetime(row["run_cycle_utc"])
                or field["valid"] != utc_datetime(row["valid_utc"])
                or field["lead_hours"] != row["lead_hours"]):
            raise DataIneligible("Decoded GFS UTC cycle or lead disagrees with the receipt")
        if (not np.array_equal(lon, np.arange(1440) * 0.25)
                or not np.array_equal(lat, 90 - np.arange(721) * 0.25)):
            raise DataIneligible("GFS vector grid is not the original global 0.25-degree grid")
        x_order, y_order = np.argsort(longitude(lon)), np.argsort(lat)
        x, y = longitude(lon)[x_order], lat[y_order]
        i0, i1 = np.searchsorted(x, roi[:2]) + [-2, 3]
        j0, j1 = np.searchsorted(y, roi[2:]) + [-2, 3]
        grid = Rectilinear(x[i0:i1], y[j0:j1])
        frames.append(field["uv"][np.ix_(y_order[j0:j1], x_order[i0:i1])].copy())
        times.append(field["valid"])
    return SurfaceField("wind", tuple(times), grid, np.stack(frames), rows,
                        dict(vector_basis="geographic_east_north", native_variables=["UGRD", "VGRD"],
                             height_m=10, spatial_method="native bilinear",
                             roi_lon_lat=roi, grid_spacing_deg=0.25),
                        max_gap_s=10800)


def _hycom_axes(ds):
    lon, lat = numeric(ds["lon"][:]), numeric(ds["lat"][:])
    if (ds["lon"].dimensions != ("lon",) or ds["lat"].dimensions != ("lat",)
            or ds["lon"].units != "degrees_east" or ds["lat"].units != "degrees_north"
            or lon.ndim != 1 or lat.ndim != 1 or min(len(lon), len(lat)) < 2
            or not np.isfinite(lon).all() or not np.isfinite(lat).all()
            or not (np.diff(lon) > 0).all() or not (np.diff(lat) > 0).all()
            or np.max(np.diff(lon)) > 0.081 or np.max(np.diff(lat)) > 0.081
            or not np.allclose([lon[0], lon[-1], lat[0], lat[-1]],
                               [268, 271.5, 61.5, 64], rtol=0, atol=0.081)):
        raise DataIneligible("HYCOM returned a different native spatial subset or coordinate mapping")
    return lon, lat


def _hycom_vectors(ds):
    mappings = (
        ("ssu", "eastward_sea_water_velocity", "m/s"),
        ("ssv", "northward_sea_water_velocity", "m/s"),
        ("sic", "sea_ice_area_fraction", "1"),
    )
    unpacked = []
    ds.set_auto_maskandscale(True)
    for name, standard, unit in mappings:
        var = ds[name]
        if ((var.dimensions, getattr(var, "standard_name", None), getattr(var, "units", None))
                != (("time", "lat", "lon"), standard, unit)):
            raise DataIneligible(f"HYCOM native dimensions, direction or units differ for {name}")
        unpacked.append(numeric(var[:]))
    u, v, ice = unpacked
    wet = np.isfinite(u)
    if not np.array_equal(wet, np.isfinite(v)):
        raise DataIneligible("HYCOM current component masks disagree")
    wet_counts = np.count_nonzero(wet, axis=(1, 2))
    if np.any(wet_counts == 0):
        raise DataIneligible("HYCOM has a valid time with no finite paired water currents")
    unknown = wet & ~np.isfinite(ice)
    nonzero = wet & np.isfinite(ice) & (ice != 0)
    counts_unknown = np.count_nonzero(unknown, axis=(1, 2)).tolist()
    counts_nonzero = np.count_nonzero(nonzero, axis=(1, 2)).tolist()
    return np.stack((u, v), axis=-1), dict(
        wet_counts=wet_counts.tolist(), unknown_ice_counts=counts_unknown,
        nonzero_ice_counts=counts_nonzero,
    )


def _hudson_current(root, rows):
    lon, lat = None, None
    times, frames, ice_audit = [], [], []
    for row in rows:
        with Dataset("hydromodel.nc", memory=_archived_bytes(root, row)) as dataset:
            x, y = _hycom_axes(dataset)
            if lon is None:
                lon, lat = x, y
            if not np.array_equal(lon, x) or not np.array_equal(lat, y):
                raise DataIneligible("HYCOM native grid changes between response chunks")
            try:
                time = cf_times(dataset["time"], row["valid_times_utc"])
            except ValueError as exc:
                raise DataIneligible(f"Decoded HYCOM CF valid times differ: {exc}") from exc
            uv, ice = _hycom_vectors(dataset)
            ice["valid_times_utc"] = [stamp.isoformat() for stamp in time]
            ice_audit.append(ice)
            times.extend(time)
            frames.append(uv)
    bad = [frame for chunk in ice_audit for frame, missing, nonzero in zip(
        chunk["valid_times_utc"], chunk["unknown_ice_counts"], chunk["nonzero_ice_counts"], strict=True
    ) if missing or nonzero]
    if bad:
        error = DataIneligible(f"HYCOM has unknown or nonzero ice on wet samples at {', '.join(bad)}")
        error.evidence = ice_audit
        raise error
    return SurfaceField(
        "current", tuple(times), Rectilinear(longitude(lon), lat), np.concatenate(frames), rows,
        dict(vector_basis="geographic_east_north", native_variables=["ssu", "ssv"],
             spatial_method="native bilinear with missing velocities masked",
             ice_policy="zero on every paired wet sample", ice_audit=ice_audit,
             native_lon_lat_bounds=[float(lon[0]), float(lon[-1]), float(lat[0]), float(lat[-1])],
             CF_unpack_count=1),
    )


def load_h2_forcing(root, block, manifest):
    """Verify original bytes, reconstruct native samplers, and audit the requested window."""
    verify_source_rows(root, block, manifest)
    cfg = mission_config(dict(base_scene=block["scene"], seed=block["seeds"][0],
                              **{key: block[key] for key in ("lkp_utc", "cst_utc", "end_utc")}))
    native, _ = axes(cfg)
    window = (utc_label(native[0]), utc_label(native[-1]))
    if block["scene"] == "lake_ontario":
        wind = _wind(root, manifest["wind"])
        current = _current(root, manifest["current"])
    else:
        wind = _hudson_wind(root, manifest["wind"], cfg)
        current = _hudson_current(root, manifest["current"])
    decoded_expected = expected_clock(block)
    fields = {}
    lon, lat = np.array([cfg[point] for point in ("lkp_lon_lat", "csp_lon_lat")]).T
    for field, expected in zip((wind, current), decoded_expected[:2], strict=True):
        if field.times != expected or not field.times[0] <= utc_datetime(window[0]) <= utc_datetime(window[1]) <= field.times[-1]:
            raise DataIneligible(f"{field.role} valid UTC sequence or rounded native tail is incomplete")
        values = []
        for stamp in native:
            uv, status = field.probe(utc_label(stamp), lon, lat)
            if not np.all(status == "ok") or not np.isfinite(uv).all():
                raise DataIneligible(f"{field.role} unavailable at LKP/CSP at {utc_label(stamp)}: {status.tolist()}")
            values.append(uv)
        fields[field.role] = dict(
            valid_times_utc=[stamp.isoformat() for stamp in field.times], shape=list(field.values.shape),
            metadata=field.metadata, lkp_csp_probe_count=2 * len(native),
            lkp_csp_min_m_s=np.min(values, axis=0).tolist(), lkp_csp_max_m_s=np.max(values, axis=0).tolist(),
        )
    return HistoricalForcing(wind, current, window, "historical_real"), dict(
        forcing_kind="historical_real", status="eligible", native_window_utc=list(window), fields=fields,
    )
