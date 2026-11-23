"""Verify the unpacked 2025-08-26 Lake Ontario delivery offline and update its B1 entry."""

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit
from uuid import uuid4
from xml.etree import ElementTree

import netCDF4
import numpy as np
import yaml

from asar_repro.grid import GridGraph
from asar_repro.gridding import ParticleGrid
from asar_repro.scenarios import digest, drift_config
from b1_hrrr import require, stats, wind
from fetch_lake_b1 import selected_ranges
from inventory_historical import ROOT, LAKE_PACKAGE, windows, utc_datetime

SUMS_SHA = "8ba23e4e7e3d81a0d048ab11d2efa430aa61a0042e594c5271c3203c631c7bc8"
REPORT = ROOT / "outputs/baseline_v1.1/b1/local/validation_local.json"
CONFIG = ROOT / "configs/stage7_scenarios.yaml"


def checked_hashes(folder):
    sums = folder / "SHA256SUMS.txt"
    require(digest(sums) == SUMS_SHA, "checksum table differs from the delivered edition")
    hashes = {}
    for row in sums.read_text(encoding="utf-8").splitlines():
        expected, name = row.split("  ", 1)
        require(digest(folder / name) == expected, f"SHA-256 mismatch: {name}")
        hashes[name] = expected
    require(hashes["evidence_stage7_scenarios.yaml"] == digest(CONFIG), "mission config mismatch")
    return hashes


def sample_points(cfg):
    rows, cols = cfg["grid_rows_cols"]
    grid = ParticleGrid(GridGraph(rows, cols), cfg["csp_lon_lat"], cfg["cell_width_m"])
    x, y = np.meshgrid(np.arange(cols) - (cols - 1) / 2, np.arange(rows) - (rows - 1) / 2)
    lon, lat = grid.projection.transform(
        x.ravel() * grid.width_m, y.ravel() * grid.width_m, direction="INVERSE"
    )
    return np.vstack((cfg["lkp_lon_lat"], cfg["csp_lon_lat"], np.column_stack((lon, lat))))


def containing_faces(lon, lat, tri, points):
    # Use only triangles intersecting the query envelope; preserve original FVCOM indices.
    xx, yy = lon[tri], lat[tri]
    lo, hi = points.min(axis=0), points.max(axis=0)
    ids = np.flatnonzero(
        (xx.min(axis=1) <= hi[0])
        & (xx.max(axis=1) >= lo[0])
        & (yy.min(axis=1) <= hi[1])
        & (yy.max(axis=1) >= lo[1])
    )
    a, b, c = xx[ids].T
    d, e, f = yy[ids].T
    det = (e - f) * (a - c) + (c - b) * (d - f)
    faces = []
    for x, y in points:
        with np.errstate(divide="ignore", invalid="ignore"):
            w1 = ((e - f) * (x - c) + (c - b) * (y - f)) / det
            w2 = ((f - d) * (x - c) + (a - c) * (y - f)) / det
        hit = np.flatnonzero((w1 >= -1e-10) & (w2 >= -1e-10) & (w1 + w2 <= 1 + 1e-10))
        faces.append(ids[hit[0]] if hit.size else -1)
    return np.asarray(faces)


def numbers(v):
    return np.ma.asarray(v, dtype=float).filled(np.nan)


def current(path, points, reference):
    # Opening the original bytes in memory also supports Unicode Windows paths
    # with netCDF-C builds that use a narrow-character file API.
    with netCDF4.Dataset("lake.nc", memory=path.read_bytes()) as ds:
        t = ds["time"]
        require(
            ds.title == "LOOFS"
            and ds.source.startswith("FVCOM")
            and t.time_zone == "UTC"
            and t.size == 1,
            "unexpected lake product or time axis",
        )
        date = netCDF4.num2date(t[0], t.units, only_use_cftime_datetimes=False)
        valid = datetime.fromisoformat(date.isoformat()).replace(tzinfo=timezone.utc)
        text_time = datetime.fromisoformat(ds["Times"][0].tobytes().decode("ascii")).replace(
            tzinfo=timezone.utc
        )
        require(
            valid == text_time and valid.isoformat() in reference["valid_times_utc"],
            "lake time mismatch",
        )
        lon, lat = (numbers(ds["lon"][:]) + 180) % 360 - 180, numbers(ds["lat"][:])
        tri = np.asarray(ds["nv"][:].T, dtype=int) - 1
        require(tri.min() >= 0 and tri.max() < len(lon), "invalid FVCOM connectivity")
        sigma = numbers(ds["siglay"][:])
        require(
            ds["siglay"].positive == "up"
            and np.all(np.diff(sigma, axis=0) < 0)
            and np.allclose(sigma[0], -0.025),
            "unexpected surface layer",
        )
        face = containing_faces(lon, lat, tri, points)
        flags = numbers(ds["wet_cells"][0, :])
        require(np.isin(flags, [0, 1]).all(), "invalid wet mask")
        wet_sites = (face >= 0) & (flags[np.maximum(face, 0)] == 1)
        require(wet_sites[:2].all(), "LKP or CSP outside wet FVCOM mesh")
        samples = {n: dict(face=int(j), wet=True) for n, j in zip(("LKP", "CSP"), face[:2])}
        components = {}
        for name, cf in (
            ("u", "eastward_sea_water_velocity"),
            ("v", "northward_sea_water_velocity"),
        ):
            var = ds[name]
            require(
                var.dimensions == ("time", "siglay", "nele")
                and var.standard_name.lower() == cf
                and var.units == "meters s-1"
                and var.location == "face",
                "lake velocity metadata mismatch",
            )
            values = numbers(var[0, 0, :])
            components[name] = dict(standard_name=var.standard_name, statistics=stats(values))
            for label, j in zip(samples, face[:2]):
                ref = reference["point_checks"][label]
                require(
                    ref["containing_face_zero_based"] == j and values[j] == ref[name + "_m_s"][0],
                    "reference lake face or current sample mismatch",
                )
                samples[label][name + "_m_s"] = float(values[j])
        h, eta = numbers(ds["h"][:]), numbers(ds["zeta"][0, :])
        for label, j in zip(samples, face[:2]):
            nodes = tri[j]
            samples[label]["top_center_depth_m"] = float(
                np.mean(-sigma[0, nodes] * (h[nodes] + eta[nodes]))
            )
        return dict(
            valid_utc=valid.isoformat(),
            model=ds.source,
            dimensions={k: len(v) for k, v in ds.dimensions.items()},
            projection=ds.CoordinateProjection,
            units=ds["u"].units,
            lon_lat_bounds=[lon.min(), lon.max(), lat.min(), lat.max()],
            top_sigma=float(sigma[0, 0]),
            components=components,
            points=samples,
            grid_centres=dict(
                total=len(face) - 2,
                wet=int(wet_sites[2:].sum()),
                outside_mesh=int((face[2:] < 0).sum()),
                dry=int(((face[2:] >= 0) & ~wet_sites[2:]).sum()),
            ),
        )


def hourly_coverage(times, bounds):
    start, end = map(utc_datetime, bounds)
    actual = sorted(map(utc_datetime, times))
    expected = [
        start + timedelta(hours=i) for i in range(int((end - start).total_seconds() / 3600) + 1)
    ]
    require(actual == expected, "incomplete, duplicated or displaced hourly data")
    return [dt.isoformat() for dt in actual]


def verify(folder, spec):
    hashes = checked_hashes(folder)
    case = spec["scenarios"]["lake_ontario"]
    requested, buffered = windows(spec, case)
    points = sample_points(drift_config(spec, case))
    delivery = json.loads((folder / "source_downloads.json").read_bytes())
    ref = json.loads((folder / "validation_download_environment.json").read_bytes())
    refs = {r["local_path"]: r for r in ref["files"]}
    objects = ElementTree.parse(folder / "evidence/loofs_s3_listing.xml")
    sizes = {
        n.findtext("{*}Key"): int(n.findtext("{*}Size")) for n in objects.findall(".//{*}Contents")
    }
    files = {"wind": [], "current": []}
    for item in delivery["records"]:
        name = item["local_path"]
        path = folder / name
        require(
            item["sha256"] == hashes[name] and item["bytes"] == path.stat().st_size,
            "source identity mismatch",
        )
        if item["product"] == "HRRR":
            role = "wind"
            hour = utc_datetime(item["run_cycle_utc"]).strftime("%H")
            idx = folder / f"evidence/hrrr.20250826.t{hour}z.wrfsfcf00.grib2.idx"
            audit = wind(
                path, item, selected_ranges(idx.read_text(encoding="ascii")), points, refs[name]
            )
        else:
            role = "current"
            key = urlsplit(item["source_url"]).path.lstrip("/")
            require(
                item["product"] == "LOOFS"
                and sizes[key] == item["bytes"]
                and key.endswith("/" + path.name),
                "lake object does not match archived S3 listing",
            )
            audit = current(path, points, refs[name])
        absolute = path.resolve()
        location = absolute.relative_to(ROOT) if absolute.is_relative_to(ROOT) else absolute
        files[role].append(dict(source=item, local_path=location.as_posix(), **audit))
    hours = {
        role: hourly_coverage([f["valid_utc"] for f in rows], buffered)
        for role, rows in files.items()
    }
    return dict(
        status="verified_B1_local",
        scenario="lake_ontario",
        verified_at_utc=datetime.now(timezone.utc).isoformat(),
        requested_window_utc=requested,
        valid_hours_utc=hours,
        files=files,
        checksums_verified=len(hashes),
        sums_sha256=SUMS_SHA,
        source_acquired_utc=delivery["acquired_utc"],
        mission_config_sha256=digest(CONFIG),
        interpreter=sys.executable,
        versions=dict(numpy=np.__version__, netCDF4=netCDF4.__version__),
        wind_decoder="GRIB2 simple packing 5.0 (NumPy); grid projection via pyproj",
        comparison="local wind statistics and LKP/CSP wind and current samples agree with delivered reference",
        forcing_kind="historical_real",
        purpose="retrospective_environment_reconstruction",
        paper_cycles_verified=False,
        available_at_cst=False,
    )


def merge_lake(case, report):
    require(
        case["scenario"] == "lake_ontario"
        and case["requested_window_utc"] == report["requested_window_utc"],
        "inventory scenario or task window differs",
    )
    case.update(
        pair_status="verified",
        forcing_kind=report["forcing_kind"],
        verification_scope="B1_raw_files",
        package_checksums_sha256=report["sums_sha256"],
        verified_at_utc=report["verified_at_utc"],
        purpose=report["purpose"],
        paper_cycles_verified=False,
        available_at_cst=False,
    )
    for role, rows in report["files"].items():
        is_wind = role == "wind"
        local_files = []
        for row in rows:
            src = row["source"]
            local_files.append(
                dict(
                    **{k: v for k, v in src.items() if k != "local_path"},
                    local_path=row["local_path"],
                    valid_utc=row["valid_utc"],
                    subset_sha256=src["sha256"] if is_wind else None,
                    full_object_sha256=None if is_wind else src["sha256"],
                )
            )
        case[role].update(
            status="verified",
            local_files=local_files,
            resolved_source=[r["source_url"] for r in local_files],
            local_path=[r["local_path"] for r in rows],
            sha256=[r["sha256"] for r in local_files],
            size_bytes=sum(r["bytes"] for r in local_files),
            native_variable_names=list(rows[0]["components"]),
            units=rows[0]["units"],
            valid_time_range_utc=[report["valid_hours_utc"][role][i] for i in (0, -1)],
            run_cycle_utc=sorted({r["run_cycle_utc"] for r in local_files}),
            forecast_or_analysis=local_files[0]["forecast_or_analysis"],
            downloaded_at_utc=report["source_acquired_utc"],
            download_command="python scripts/download_lake.py --out <new-directory> (from unpacked delivery root)",
            crs=rows[0]["grid"] if is_wind else rows[0]["projection"],
            dimensions=(
                [rows[0]["grid"][k] for k in ("Ny", "Nx")] if is_wind else rows[0]["dimensions"]
            ),
            spatial_coverage=(
                dict(
                    sites_inside_grid=rows[0]["sites_inside_grid"],
                    lon_lat_bounds=rows[0]["grid"]["lon_lat_bounds"],
                )
                if is_wind
                else dict(
                    lon_lat_bounds=rows[0]["lon_lat_bounds"],
                    grid_centres_by_hour=[r["grid_centres"] for r in rows],
                )
            ),
            missing_fraction=0.0,
            missing_fraction_scope=(
                "delivered 10m components" if is_wind else "uppermost layer components"
            ),
            subset_bounds="full native horizontal grid, two 10 m messages" if is_wind else None,
            subset_sha256=[r["sha256"] for r in local_files] if is_wind else None,
            vector_basis="grid_relative" if is_wind else "geographic_east_north",
            surface_definition="10 m above ground" if is_wind else "uppermost sigma layer, index 0",
        )


def save(path, doc, newline="\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid4().hex}.part")
    try:
        with temp.open("x", encoding="utf-8", newline=newline) as f:
            json.dump(doc, f, indent=2, ensure_ascii=False, allow_nan=False)
            f.write("\n")
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=ROOT / "data/raw/historical" / LAKE_PACKAGE)
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument(
        "--manifest", type=Path, default=ROOT / "data/manifests/historical_sources.json"
    )
    args = parser.parse_args()
    result = verify(args.package, yaml.safe_load(CONFIG.read_bytes()))
    manifest = json.loads(args.manifest.read_bytes())
    require(
        manifest["config_sha256"] == result["mission_config_sha256"],
        "inventory configuration differs",
    )
    merge_lake(next(c for c in manifest["scenarios"] if c["scenario"] == "lake_ontario"), result)
    save(args.report, result)
    save(args.manifest, manifest, newline=None)
    print(
        result["status"],
        result["checksums_verified"],
        "checksums;",
        {k: len(v) for k, v in result["files"].items()},
    )
