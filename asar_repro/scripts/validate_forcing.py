"""Audit B2 Lake Ontario forcing and the OpenDrift environment without integrating drift."""

import argparse
from collections import Counter
from datetime import datetime, timezone
from importlib.metadata import version
import json
from pathlib import Path
import sys

import numpy as np
from opendrift.models.leeway import Leeway
from pyproj import Proj
import yaml

from asar_repro.forcing import VARIABLES, load_historical_forcing, utc_datetime
from asar_repro.historical_reader import attach_historical_readers
from asar_repro.hrrr import require
from asar_repro.scenarios import digest, drift_config
from verify_lake_b1 import ROOT, CONFIG, REPORT as B1_REPORT, sample_points, save


def counts(labels):
    return dict(sorted(Counter(labels.tolist()).items()))


def bounds(points):
    lo, hi = points.min(axis=0), points.max(axis=0)
    return [float(lo[0]), float(hi[0]), float(lo[1]), float(hi[1])]


def statistics(field):
    rows = []
    for time, frame in zip(field.times, field.values):
        components = {}
        for j, name in enumerate(field.metadata["native_variables"]):
            data = frame[..., j]
            valid = np.isfinite(data)
            observed = data[valid]
            components[name] = dict(
                min=float(observed.min()),
                max=float(observed.max()),
                mean=float(observed.mean()),
                std=float(observed.std()),
                count=int(data.size),
                missing_fraction=float(1 - valid.mean()),
            )
        rows.append(dict(valid_utc=time.isoformat(), components_m_s=components))
    return rows


def compare_native_references(bundle, reference, sites):
    """Use B1 native ecCodes node values and containing-face values as independent controls."""
    w, c = bundle.wind, bundle.current
    crs = w.grid.projection.crs
    param = {p.name: p.value for p in crs.coordinate_operation.params}
    central = (param["Longitude of false origin"] + 180) % 360 - 180
    parallel = param["Latitude of 1st standard parallel"]
    require(
        parallel == param["Latitude of 2nd standard parallel"], "expected spherical tangent cone"
    )
    # For this tangent cone n=sin(phi_1). Compute convergence independently of PROJ factors.
    wind_error, current_error, norm_error = 0.0, 0.0, 0.0
    for f in reference["files"]["wind"]:
        time = f["valid_utc"]
        for name in ("LKP", "CSP"):
            index = f["components"]["UGRD"]["points"][name]["flat_index"]
            j, i = divmod(index, len(w.grid.x))
            lon, lat = w.grid.projection(w.grid.x[i], w.grid.y[j], inverse=True)
            u, v = [
                f["components"][key]["points"][name]["grid_relative_m_s"]
                for key in ("UGRD", "VGRD")
            ]
            gamma = np.deg2rad(lon - central) * np.sin(np.deg2rad(parallel))
            expected = np.array(
                [u * np.cos(gamma) + v * np.sin(gamma), -u * np.sin(gamma) + v * np.cos(gamma)]
            )
            actual = w.sample(time, lon, lat)[0]
            wind_error = max(wind_error, float(np.max(np.abs(actual - expected))))
            norm_error = max(norm_error, abs(float(np.linalg.norm(actual) - np.hypot(u, v))))
    for f in reference["files"]["current"]:
        expected = np.array(
            [[f["points"][n][k] for k in ("u_m_s", "v_m_s")] for n in ("LKP", "CSP")]
        )
        actual = c.sample(f["valid_utc"], *sites.T)
        current_error = max(current_error, float(np.max(np.abs(actual - expected))))
    require(
        wind_error < 1e-8 and current_error < 1e-12 and norm_error < 1e-8,
        "native control comparison failed",
    )
    return dict(
        wind_node_max_error_m_s=wind_error,
        wind_speed_max_error_m_s=norm_error,
        current_face_max_error_m_s=current_error,
        wind_check="B1 ecCodes node vectors rotated using analytical spherical tangent cone convergence",
        current_check="B1 original face speeds at LKP and CSP for each hour",
    )


def audit(manifest, reference_path):
    bundle = load_historical_forcing(manifest, ROOT)
    cfg = drift_config(SPEC, SPEC["scenarios"]["lake_ontario"])
    start, end = map(utc_datetime, bundle.window)
    cst = utc_datetime(cfg["cst_utc"])
    mid = start + (cst - start) / 2
    queries = {"incident": start, "predrift_midpoint": mid, "cst": cst, "search_end": end}
    reference = json.loads(reference_path.read_bytes())
    centres = sample_points(cfg)
    sites = centres[:2]
    controls = compare_native_references(bundle, reference, sites)
    model = Leeway(loglevel=50)
    readers = attach_historical_readers(model, bundle)
    model.env.finalize()
    priority = {
        name: model.env.priority_list[name] for names in VARIABLES.values() for name in names
    }
    for reader in readers:
        require(
            all(priority[v] == [reader.name] for v in reader.variables),
            "unexpected reader precedence",
        )
    names = [name for role in VARIABLES for name in VARIABLES[role]]
    # Probe the entire search footprint plus a 3 km buffer on all four sides.
    lon0, lat0 = cfg["csp_lon_lat"]
    aeqd = Proj(proj="aeqd", datum="WGS84", lon_0=lon0, lat_0=lat0)
    rows, cols = cfg["grid_rows_cols"]
    buffer_m = 3000
    x_extent, y_extent = np.array([cols, rows]) * cfg["cell_width_m"] / 2 + buffer_m
    xx, yy = np.meshgrid(np.linspace(-x_extent, x_extent, 25), np.linspace(-y_extent, y_extent, 25))
    region = np.column_stack(aeqd(xx.ravel(), yy.ravel(), inverse=True))
    fields = {"wind": bundle.wind, "current": bundle.current}
    report = {}
    for role, field in fields.items():
        grid = field.grid
        grid_extent = (
            dict(
                projected_xy_m=[
                    float(grid.x[0]),
                    float(grid.x[-1]),
                    float(grid.y[0]),
                    float(grid.y[-1]),
                ],
                projection=grid.projection.srs,
            )
            if role == "wind"
            else dict(node_lon_lat=field.metadata["lon_lat_bounds"])
        )
        surface = statistics(field)
        require(
            all(any(v["std"] > 0 for v in row["components_m_s"].values()) for row in surface),
            f"{role} has no within-frame spatial variation",
        )
        native_sites = np.stack([field.sample(t, *sites.T) for t in field.times])
        delta = np.max(np.abs(np.diff(native_sites, axis=0)))
        require(delta > 0, "native mission point sample is time-invariant")
        report[role] = dict(
            **field.metadata,
            units="m/s",
            opendrift_variables=list(VARIABLES[role]),
            archive_extent=grid_extent,
            source_files=field.sources,
            gap_seconds=np.diff(field.seconds).tolist(),
            native_surface_statistics=surface,
            max_hourly_change_at_sites_m_s=float(delta),
            coverage=[],
        )
        for t in [*field.times, start, mid, cst, end]:
            _, search = field.probe(t, *centres[2:].T)
            _, buffer = field.probe(t, *region.T)
            report[role]["coverage"].append(
                dict(
                    utc=t.isoformat(),
                    search_centres=counts(search),
                    buffered_lattice=counts(buffer),
                )
            )

    # Use a real mesh-exterior search centre as an OpenDrift negative control.
    _, status = bundle.current.probe(start, *centres[2:].T)
    outside = centres[2:][np.flatnonzero(status == "outside_mesh")[0]]
    checks = np.vstack((sites, outside))
    sample_rows = []
    reader_error = 0.0
    for label, t in queries.items():
        actual, _, missing = model.env.get_environment(
            names, t.replace(tzinfo=None), *checks.T, np.zeros(3)
        )
        require(
            missing.tolist() == [False, False, True],
            "wet or outside point not classified correctly",
        )
        values = {}
        for role, field in fields.items():
            uv, state = field.probe(t, *checks.T)
            result = np.column_stack([actual[n] for n in VARIABLES[role]])
            np.testing.assert_allclose(result, uv, rtol=2e-7, atol=1e-7, equal_nan=True)
            reader_error = max(reader_error, float(np.nanmax(np.abs(result - uv))))
            values[role] = [
                dict(status=s, east_north_m_s=row.tolist() if s == "ok" else None)
                for s, row in zip(state, result)
            ]
        # Independently interpolate hourly B1 face values at both task points.
        for j, name in enumerate(("LKP", "CSP")):
            frames = reference["files"]["current"]
            ts = [utc_datetime(f["valid_utc"]).timestamp() for f in frames]
            expected = [
                np.interp(t.timestamp(), ts, [f["points"][name][k] for f in frames])
                for k in ("u_m_s", "v_m_s")
            ]
            np.testing.assert_allclose(
                values["current"][j]["east_north_m_s"], expected, rtol=2e-7, atol=1e-7
            )
        sample_rows.append(dict(event=label, utc=t.isoformat(), **values))
    controls["opendrift_float32_max_error_m_s"] = reader_error
    return dict(
        status="passed",
        stage="B2",
        scenario="lake_ontario",
        forcing_kind=bundle.forcing_kind,
        experiment_label="historical_real_forcing_allwater",
        shoreline_policy=bundle.shoreline_policy,
        note="FVCOM wet/dry flags and mesh domain still gate valid currents. No coastline collision model.",
        interpretation="retrospective_environment_reconstruction",
        verified_at_utc=datetime.now(timezone.utc).isoformat(),
        interpreter=sys.executable,
        versions={n: version(n) for n in ("opendrift", "netCDF4", "numpy", "pyproj", "shapely")},
        input_identity=dict(
            b1_report_sha256=digest(reference_path),
            manifest_sha256=digest(manifest),
            stage7_config_sha256=digest(CONFIG),
        ),
        requested_window_utc=[start.isoformat(), end.isoformat()],
        interpolation_time="linear, max gap 3600 s",
        longitude_convention="[-180,180)",
        invalid_sample="explicit status; NaN in readers; no velocity fallback",
        cycle_policy=dict(
            wind="each distinct valid UTC from its own HRRR f00 analysis",
            current="one 18 UTC LOOFS nowcast cycle using file-native valid UTC",
        ),
        roi=dict(
            search_centres_bbox_lon_lat=bounds(centres[2:]),
            buffer_m=buffer_m,
            buffer_local_projection=aeqd.srs,
            buffer_lattice_shape=[25, 25],
            buffered_bbox_lon_lat=bounds(region),
            meaning="coverage sampling, not a particle trajectory envelope",
        ),
        reader_priority=priority,
        controls=controls,
        sample_sites=dict(zip(["LKP", "CSP", "outside_LOOFS"], checks.tolist())),
        samples=sample_rows,
        fields=report,
    )


SPEC = yaml.safe_load(CONFIG.read_bytes())

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, default=ROOT / "data/manifests/historical_sources.json")
    p.add_argument("--b1-report", type=Path, default=B1_REPORT)
    p.add_argument(
        "--output", type=Path, default=ROOT / "outputs/baseline_v1.1/b2/forcing_audit.json"
    )
    args = p.parse_args()
    report = audit(args.manifest, args.b1_report)
    save(args.output, report)
    print(
        json.dumps(
            dict(
                status=report["status"],
                scenario=report["scenario"],
                checks=report["controls"],
                samples=len(report["samples"]),
            ),
            indent=2,
        )
    )
