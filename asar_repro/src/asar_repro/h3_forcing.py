"""Verify and decode the official source captures registered for P2/H3."""
from __future__ import annotations

from datetime import date, timedelta
from hashlib import file_digest, sha256
from pathlib import Path
from urllib.parse import urlencode

import numpy as np

from .forcing import HistoricalForcing, Rectilinear, SurfaceField, _current, _wind, longitude
from .h2_forcing import DataIneligible, _hudson_current, _hudson_wind, expected_clock, mission_config
from .historical_drift import axes, utc_label
from .opendrift_adapter import utc_datetime


def verify_file(root, block, relative, expected, size=None):
    root, relative = Path(root).resolve(), Path(relative)
    scope = root / "data/raw/h3" / block["id"]
    path = (root / relative).resolve()
    if (relative.is_absolute() or ".." in relative.parts or not scope.is_relative_to(root)
            or not path.is_relative_to(scope)):
        raise ValueError(f"Source path is outside the registered H3 raw directory: {relative}")
    if not path.is_file() or (size is not None and path.stat().st_size != size):
        raise ValueError(f"Missing H3 source or byte count changed: {relative}")
    with path.open("rb") as stream:
        actual = file_digest(stream, "sha256").hexdigest()
    if actual != expected:
        raise ValueError(f"H3 source SHA-256 mismatch: {relative}")
    return path


def _wind_inventory(root, block, rows):
    from h2_acquire import _verify_headers, _verify_payload, parse_wind_index
    from h3_acquire import wind_requests

    expected = wind_requests(block)
    if len(rows) != len(expected):
        raise DataIneligible("Wind archive lacks the registered complete cycle/lead sequence")
    for row, (product, url, cycle, lead) in zip(rows, expected, strict=True):
        if (row["product"] != product or row["source_url"] != url or row["index_url"] != url + ".idx"
                or row["source_kind"] != "byte_exact_selected_original_grib_messages"):
            raise ValueError("Wind bytes are not identified as the registered official original messages")
        if (utc_datetime(row["run_cycle_utc"]) != cycle or row["lead_hours"] != lead
                or utc_datetime(row["valid_utc"]) != cycle + timedelta(hours=lead)):
            raise DataIneligible("Wind receipt UTC cycle, valid time or lead differs")
        index = verify_file(root, block, row["index_path"], row["index_sha256"]).read_bytes()
        data = verify_file(root, block, row["local_path"], row["sha256"], row["bytes"]).read_bytes()
        selected = parse_wind_index(index, cycle, lead)
        offset = 0
        for spec, receipt in zip(selected, row["byte_ranges"], strict=True):
            if any(receipt[k] != value for k, value in spec.items()):
                raise ValueError("Wind receipt and official inventory offsets differ")
            start, end = spec["start"], spec["end_inclusive"]
            size = end - start + 1
            component = data[offset:offset + size]
            response = receipt["response"]
            _verify_headers(response["http_status"], response, byte_range=(start, end),
                            size=size, etag=row["source_object_etag"])
            if (response["content-range"].rsplit("/", 1)[-1] != str(row["source_object_bytes"])
                    or len(component) != size or sha256(component).hexdigest() != receipt["sha256"]):
                raise ValueError("Native GRIB component does not match its original byte range")
            _verify_payload(component, "grib")
            offset += size
        if offset != len(data):
            raise ValueError("The wind archive contains bytes outside the verified two components")


def _lake_inventory(root, block, rows, expected_times):
    from h2_acquire import LOOFS_ROOT, parse_loofs_listing

    day = date.fromisoformat(block["date"])
    prefix = f"loofs/netcdf/{day:%Y/%m/%d}/loofs.t18z.{day:%Y%m%d}.fields.n"
    keys = [prefix + f"{i:03}.nc" for i in range(1, 6)]
    listing_url = LOOFS_ROOT + "/?" + urlencode({"list-type": "2", "prefix": prefix})
    if (tuple(utc_datetime(row["valid_utc"]) for row in rows) != expected_times
            or any(utc_datetime(row["run_cycle_utc"]) != expected_times[0].replace(hour=18)
                   for row in rows)):
        raise DataIneligible("LOOFS nowcast cycle or the five required UTC frames differ")
    listing = verify_file(root, block, rows[0]["listing_path"], rows[0]["listing_sha256"])
    objects = parse_loofs_listing(listing.read_bytes(), prefix, keys)
    for key, row in zip(keys, rows, strict=True):
        original = objects[key]
        if (row["product"] != "LOOFS" or row["forecast_or_analysis"] != "nowcast"
                or row["source_kind"] != "byte_exact_original_netcdf"
                or row["source_url"] != LOOFS_ROOT + "/" + key
                or row["listing_url"] != listing_url or row["listed_object"] != original
                or row["listing_path"] != rows[0]["listing_path"]
                or row["listing_sha256"] != rows[0]["listing_sha256"]
                or row["response"]["http_status"] != 200 or row["response"]["etag"] != original["etag"]
                or row["bytes"] != original["size"]):
            raise ValueError("LOOFS capture differs from the registered NOAA nowcast object")
        verify_file(root, block, row["local_path"], row["sha256"], row["bytes"])


def _hudson_inventory(root, block, rows, cfg):
    from h2_hycom import CATALOG, HycomDataError, inspect_hycom, requests_for

    expected = requests_for(block)
    if len(rows) != len(expected):
        raise DataIneligible("HYCOM archive lacks the three complete native chunks")
    points = {name: cfg[key] for name, key in (("LKP", "lkp_lon_lat"), ("CSP", "csp_lon_lat"))}
    for spec, row in zip(expected, rows, strict=True):
        if (row["source_url"] != spec["source_url"] or row["catalog_url"] != CATALOG
                or row["product"] != "ESPC-D-V02" or row["http_status"] != 200
                or row["block_id"] != block["id"]):
            raise ValueError("HYCOM capture differs from the registered archive endpoint or subset")
        if row["valid_times_utc"] != spec["valid_times_utc"]:
            raise DataIneligible("HYCOM archive receipt omits required native hourly times")
        path = verify_file(root, block, row["local_path"], row["sha256"], row["bytes"])
        get_receipt = Path(row["receipt_path"])
        if get_receipt.parent != Path(row["local_path"]).parent:
            raise ValueError("HYCOM byte capture and its receipt are in different attempt directories")
        try:
            native_audit = inspect_hycom(path.read_bytes(), spec["valid_times_utc"], points)
        except HycomDataError as exc:
            # HTML, wrong media or an unexpected product are provenance failures.
            if str(exc) in ("HYCOM response was not NetCDF4/HDF5", "Unexpected HYCOM product fingerprints"):
                raise ValueError(f"Cannot verify original HYCOM data: {exc}") from exc
            error = DataIneligible(str(exc))
            error.evidence = exc.audit
            raise error from exc
        if row["status"] != "accepted" or row["audit"] != native_audit:
            raise ValueError("HYCOM independent native audit differs from the capture")


def _hudson_dap_current(root, block, rows, cfg):
    from h2_hycom import BOX, CATALOG, HycomDataError, _point_stencils, requests_for
    from h3_hycom_dap import CF_EPOCH, DAS, TIME_AXIS, attributes, dap_url, packed_product, time_axis, unpack

    expected = requests_for(block)
    if len(rows) != len(expected):
        raise DataIneligible("HYCOM OPeNDAP lacks the three registered hourly chunks")
    metadata = rows[0]["metadata"]
    if metadata["source_url"] != DAS:
        raise ValueError("HYCOM CF metadata is outside the official OPeNDAP archive")
    path = verify_file(root, block, metadata["local_path"], metadata["sha256"], metadata["bytes"])
    packing = attributes(path.read_bytes())
    axis_capture = rows[0].get("time_axis")
    if not axis_capture or axis_capture["source_url"] != TIME_AXIS:
        raise ValueError("HYCOM OPeNDAP capture lacks a verified provider time axis")
    axis_path = verify_file(root, block, axis_capture["local_path"], axis_capture["sha256"], axis_capture["bytes"])
    official_axis = time_axis(axis_path.read_bytes())
    lon, lat = None, None
    frames, times, audits = [], [], []
    mission = {name: cfg[key] for name, key in (("LKP", "lkp_lon_lat"), ("CSP", "csp_lon_lat"))}
    for spec, row in zip(expected, rows, strict=True):
        wanted = spec["valid_times_utc"]
        if (row["source_url"] != dap_url(wanted, official_axis) or row["catalog_url"] != CATALOG
                or row["product"] != "ESPC-D-V02" or row["http_status"] != 200
                or row["block_id"] != block["id"] or row["metadata"] != metadata
                or row["time_axis"] != axis_capture):
            raise ValueError("HYCOM OPeNDAP bytes are outside the registered source")
        if row["valid_times_utc"] != wanted:
            raise DataIneligible("HYCOM OPeNDAP source receipt lost registered hours")
        path = verify_file(root, block, row["local_path"], row["sha256"], row["bytes"])
        native = packed_product(path.read_bytes(), len(wanted))
        stamps = [utc_datetime(stamp) for stamp in wanted]
        clock = [(stamp - CF_EPOCH).total_seconds() / 3600 for stamp in stamps]
        if not np.allclose(native["time"], clock, rtol=0, atol=1e-6 / 3600):
            raise DataIneligible("HYCOM OPeNDAP original CF hours differ from the requested UTCs")
        if lon is None:
            lon, lat = native["lon"], native["lat"]
            if (not np.allclose(np.diff(lon), .08, rtol=0, atol=1e-4)
                    or not np.allclose(np.diff(lat), .04, rtol=0, atol=1e-4)
                    or not np.allclose([lon[0], lon[-1], lat[0], lat[-1]],
                                       [float(BOX[k]) for k in ("west", "east", "south", "north")],
                                       rtol=0, atol=.081)):
                raise DataIneligible("HYCOM OPeNDAP is not the registered native spatial grid")
        if not np.array_equal(lon, native["lon"]) or not np.array_equal(lat, native["lat"]):
            raise DataIneligible("HYCOM OPeNDAP native grid differs between hourly chunks")
        u, v, ice = (unpack(native[key], packing[key]) for key in ("ssu", "ssv", "sic"))
        wet = np.isfinite(u)
        if not np.array_equal(wet, np.isfinite(v)) or not wet.any(axis=(1, 2)).all():
            raise DataIneligible("HYCOM OPeNDAP water mask differs between components or lacks water")
        if max(np.abs(u[wet]).max(), np.abs(v[wet]).max()) >= 20:
            raise DataIneligible("Implausible HYCOM OPeNDAP water speed after CF unpacking")
        unknown = (wet & ~np.isfinite(ice)).sum(axis=(1, 2))
        nonzero = (wet & np.isfinite(ice) & (ice != 0)).sum(axis=(1, 2))
        audit = dict(valid_times_utc=wanted, wet_counts=wet.sum(axis=(1, 2)).tolist(),
                     unknown_ice_counts=unknown.tolist(), nonzero_ice_counts=nonzero.tolist())
        if unknown.any() or nonzero.any():
            error = DataIneligible(f"HYCOM OPeNDAP water contains {unknown.sum()} unknown and {nonzero.sum()} nonzero ice samples")
            error.evidence = audit
            raise error
        try:
            audit["point_checks"] = _point_stencils(lon, lat, wet, mission)
        except HycomDataError as exc:
            raise DataIneligible(str(exc)) from exc
        times.extend(stamps)
        frames.append(np.stack((u, v), axis=-1))
        audits.append(audit)
    return SurfaceField(
        "current", tuple(times), Rectilinear(longitude(lon), lat), np.concatenate(frames), rows,
        dict(delivery="official_opendap_dap2", vector_basis="geographic_east_north",
             native_variables=["ssu", "ssv"], spatial_method="native bilinear with missing velocities masked",
             ice_policy="zero on every paired wet sample", ice_audit=audits, CF_unpack_count=1,
             native_lon_lat_bounds=[float(lon[0]), float(lon[-1]), float(lat[0]), float(lat[-1])],
             run_cycle_status="annual_archive_per_frame_lineage_not_verified"),
    )


def load_h3_forcing(root, block, manifest):
    """Reconstruct original fields and qualify coverage from LKP to rounded native tail."""
    if (manifest["block_id"], manifest["scene"], manifest["date"]) != (
            block["id"], block["scene"], block["date"]):
        raise ValueError("H3 forcing manifest is for a different date or region")
    wind_rows, current_rows = manifest["wind"], manifest["current"]
    expected_wind, expected_current, _, _ = expected_clock(block)
    cfg = mission_config(dict(
        base_scene=block["scene"], seed=block["seeds"][0],
        **{key: block[key] for key in ("lkp_utc", "cst_utc", "end_utc")},
    ))
    _wind_inventory(root, block, wind_rows)
    if block["scene"] == "lake_ontario":
        _lake_inventory(root, block, current_rows, expected_current)
        try:
            wind, current = _wind(root, wind_rows), _current(root, current_rows)
        except ValueError as exc:
            audited_failures = (
                "HRRR grid changed across valid times", "HRRR valid UTC does not match manifest",
                "invalid LOOFS face connectivity", "LOOFS projection does not match node coordinates",
                "LOOFS grid changed between times", "LOOFS top sigma layer mismatch",
                "invalid FVCOM top-layer depth", "invalid FVCOM wet/dry mask",
            )
            if str(exc) in audited_failures:
                raise DataIneligible(str(exc)) from exc
            raise
    else:
        wind = _hudson_wind(root, wind_rows, cfg)
        access = {row.get("access", "official_ncss") for row in current_rows}
        if access == {"official_opendap_dap2"}:
            current = _hudson_dap_current(root, block, current_rows, cfg)
        elif access <= {"official_ncss"}:
            _hudson_inventory(root, block, current_rows, cfg)
            current = _hudson_current(root, current_rows)
        else:
            raise ValueError("HYCOM captures must use one documented native access route")
    native, _ = axes(cfg)
    window = (utc_label(native[0]), utc_label(native[-1]))
    points = np.array([cfg[name] for name in ("lkp_lon_lat", "csp_lon_lat")])
    checks = {}
    for field, expected, sources in (
        (wind, expected_wind, wind_rows), (current, expected_current, current_rows),
    ):
        if (field.times != expected
                or not field.times[0] <= utc_datetime(window[0]) <= utc_datetime(window[1]) <= field.times[-1]):
            raise DataIneligible(f"{field.role} native UTC coverage is incomplete")
        probe = []
        for when in native:
            velocity, status = field.probe(utc_label(when), points[:, 0], points[:, 1])
            if not np.all(status == "ok") or not np.isfinite(velocity).all():
                raise DataIneligible(f"{field.role} unavailable at LKP/CSP at {utc_label(when)}: {status.tolist()}")
            probe.append(velocity)
        checks[field.role] = dict(
            native_valid_times_utc=[when.isoformat().replace("+00:00", "Z") for when in field.times],
            native_shape=list(field.values.shape), metadata=field.metadata, probe_count=2 * len(probe),
            lkp_csp_range_m_s=np.stack((np.min(probe, axis=0), np.max(probe, axis=0))).tolist(),
            source_sha256={row["local_path"]: row["sha256"] for row in sources},
        )
    return HistoricalForcing(wind, current, window, "historical_real"), dict(
        status="eligible", forcing_kind="historical_real", native_window_utc=list(window),
        lkp_csp_lon_lat=points.tolist(), fields=checks,
    )
