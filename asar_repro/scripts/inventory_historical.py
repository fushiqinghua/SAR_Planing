"""B1: inspect dated archive indexes and local file headers without running Leeway."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import socket
import sys
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import getproxies, urlopen
from xml.etree import ElementTree as ET

import numpy as np
import yaml

from asar_repro.opendrift_adapter import planning_times, utc_datetime
from asar_repro.scenarios import digest, drift_config

ROOT = Path(__file__).resolve().parents[1]
NOS = "https://noaa-nos-ofs-pds.s3.amazonaws.com/"
NCEI = "https://www.ncei.noaa.gov/thredds/catalog"
HYCOM = "https://tds.hycom.org/thredds/dodsC/ESPC-D-V02/ice/2025"
HYCOM_CATALOG = (
    "https://tds.hycom.org/thredds/catalogs/ESPC-D-V02_ice.html?dataset=ESPC-D-V02-ice-2025"
)
NOAA_DOC = "https://www.ncei.noaa.gov/products/weather-climate-models/co-ops-operational-forecast"
BYTE_LIMIT = 1024 * 1024


def utc_text(t):
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def windows(spec, case):
    cfg = drift_config(spec, case)
    end = planning_times(cfg["cst_utc"], cfg["budget"], cfg["step_s"])[-1]
    last = utc_datetime(np.datetime_as_string(end, unit="ms") + "Z")
    first = utc_datetime(cfg["incident_utc"])
    # One extra sample each side beyond the hourly brackets. File-native
    # cadence and any missing hours must still be checked separately.
    start = first.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    ceil = last.replace(minute=0, second=0, microsecond=0)
    if ceil < last:
        ceil += timedelta(hours=1)
    return (
        [utc_text(first), utc_text(last)],
        [utc_text(start), utc_text(ceil + timedelta(hours=1))],
    )


def endpoints(name, case):
    date = utc_datetime(case["incident_utc"])
    day, hour = date.strftime("%Y%m%d"), date.strftime("%H")
    if case["wind"] == "HRRR":
        key = f"hrrr.{day}/conus/hrrr.t{hour}z.wrfsfcf00.grib2.idx"
        wind = [
            ("idx", "https://noaa-hrrr-bdp-pds.s3.amazonaws.com/" + key),
            ("idx", "https://storage.googleapis.com/high-resolution-rapid-refresh/" + key),
        ]
    else:
        key = f"gfs.{day}/{hour}/atmos/gfs.t{hour}z.pgrb2.0p25.f000.idx"
        wind = [("idx", "https://noaa-gfs-bdp-pds.s3.amazonaws.com/" + key)]
    if name in ("lake_ontario", "bay_of_fundy"):
        products = ["loofs", "laofs"] if name == "lake_ontario" else ["gomofs"]
        current = []
        for product in products:
            for prefix in [f"{product}/netcdf/{date:%Y/%m/%d}/", f"{product}/netcdf/{date:%Y%m}/"]:
                current.append(
                    (
                        "s3",
                        NOS + "?" + urlencode({"list-type": 2, "prefix": prefix, "max-keys": 100}),
                    )
                )
        current.append(("thredds", f"{NCEI}/model-{products[0]}-files/{date:%Y/%m}/catalog.xml"))
        current.append(("thredds", f"{NCEI}/model-{products[0]}-files/{date:%Y/%m/%d}/catalog.xml"))
    elif name == "arctic_ocean":
        current = [
            ("dds", HYCOM + ".dds"),
            ("ncss", "https://ncss.hycom.org/thredds/ncss/grid/ESPC-D-V02/ice/2025/dataset.xml"),
        ]
    else:
        current = [("directory", f"https://dd.weather.gc.ca/{day}/model_ciops/salish-sea/500m/00/")]
    return {"wind": wind, "current": current}


def describe_response(kind, body):
    if kind == "idx":
        lines = body.decode("ascii").splitlines()
        matches = [
            line
            for line in lines
            if any(s in line for s in (":UGRD:10 m above ground:", ":VGRD:10 m above ground:"))
        ]
        return {"matched_wind_index_lines": matches}
    if kind in ("s3", "thredds", "ncss"):
        xml = ET.fromstring(body)
        if kind == "s3":
            if xml.tag.split("}")[-1] != "ListBucketResult":
                raise ValueError("not an S3 object listing")
            return dict(
                listed_keys=[n.text for n in xml.findall(".//{*}Contents/{*}Key")],
                truncated=xml.findtext("{*}IsTruncated") == "true",
            )
        return dict(
            root=xml.tag.split("}")[-1],
            dataset_paths=[n.attrib["urlPath"] for n in xml.iter() if "urlPath" in n.attrib][:200],
            subcatalogs=[
                n.get("{http://www.w3.org/1999/xlink}href") for n in xml.findall(".//{*}catalogRef")
            ],
        )
    if kind == "dds":
        text = body.decode("ascii")
        return {"listed_surface_components": [v for v in ("ssu", "ssv") if v in text]}
    return {"directory_preview": body.decode("utf-8", errors="replace")[:500]}


def probe(item):
    kind, url = item
    row = dict(
        kind=kind,
        url=url,
        queried_at_utc=utc_text(datetime.now(timezone.utc)),
        command=f'curl.exe --fail --location "{url}"',
    )
    host = urlsplit(url).hostname
    try:
        row["dns_addresses"] = sorted(
            {a[4][0] for a in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
        )
    except OSError as err:
        row["dns_error"] = str(err)
    try:
        with urlopen(url, timeout=8) as response:
            row.update(http_status=response.status, final_url=response.geturl())
            body = response.read(BYTE_LIMIT + 1)
        if len(body) > BYTE_LIMIT:
            raise ValueError("metadata response exceeded 1 MiB")
        row.update(
            response_bytes=len(body),
            metadata_response_sha256=hashlib.sha256(body).hexdigest(),
            evidence=describe_response(kind, body),
            status="metadata_received",
        )
    except (OSError, ValueError, ET.ParseError) as err:
        cause = err.reason if isinstance(err, URLError) else err
        row.update(status="probe_failed", error=str(err), winerror=getattr(cause, "winerror", None))
        if isinstance(err, HTTPError):
            row["http_status"] = err.code
    return row


def inspect_local(path):
    """Take inventory of original bytes. Record native coordinates without unit conversion."""
    row = dict(local_path=str(path.resolve()), size_bytes=path.stat().st_size, sha256=digest(path))
    try:
        import xarray as xr

        grib = path.suffix.lower() in {".grb", ".grib", ".grb2", ".grib2"}
        engine = {"engine": "cfgrib", "backend_kwargs": {"indexpath": ""}} if grib else {}
        with xr.open_dataset(path, **engine) as ds:
            row.update(
                status="header_opened_pending_review",
                dimensions=dict(ds.sizes),
                variables={
                    v: dict(
                        dims=list(var.dims),
                        units=var.attrs.get("units"),
                        standard_name=var.attrs.get("standard_name"),
                    )
                    for v, var in ds.variables.items()
                },
            )
            ranges = {}
            for v in (
                "valid_time",
                "time",
                "ocean_time",
                "lat",
                "lon",
                "latc",
                "lonc",
                "latitude",
                "longitude",
                "lat_rho",
                "lon_rho",
                "depth",
                "heightAboveGround",
            ):
                if v in ds:
                    values = ds[v].values
                    if values.dtype.kind == "M":
                        values = values[~np.isnat(values)]
                    elif values.dtype.kind in "iuf":
                        values = values[np.isfinite(values)]
                    else:
                        continue
                    if values.size:
                        ranges[v] = [str(values.min()), str(values.max())]
            row["native_coordinate_ranges"] = ranges
    except (OSError, ImportError, ValueError, RuntimeError) as err:
        row.update(status="header_unreadable", error=str(err))
    return row


def source(product, catalog, local_dir, attempts):
    fields = (
        "resolved_source local_path sha256 size_bytes native_variable_names units valid_time_range_utc "
        "spatial_coverage run_cycle_utc forecast_or_analysis downloaded_at_utc download_command "
        "crs dimensions missing_fraction subset_bounds subset_sha256"
    ).split()
    files = [
        inspect_local(p)
        for p in sorted(local_dir.rglob("*"))
        if p.is_file()
        and p.suffix.lower() in {".nc", ".nc4", ".cdf", ".grb", ".grib", ".grib2", ".grb2"}
    ]
    by_identity = {(Path(f["local_path"]).name, f["sha256"]): f for f in files}
    for receipt_path in sorted(local_dir.parent.glob("acquisition_*.json")):
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        for item in receipt.get(local_dir.name, []):
            identity = (item["local_path"], item.get("subset_sha256") or item.get("sha256"))
            if identity in by_identity:
                by_identity[identity]["acquisition"] = dict(item, receipt=receipt_path.name)
    status = "unverified"
    if files:
        status = (
            "local_files_pending_review"
            if any(f["status"] == "header_opened_pending_review" for f in files)
            else "local_files_unreadable"
        )
    return dict.fromkeys(fields) | dict(
        product=product,
        catalog=catalog,
        probes=attempts,
        local_files=files,
        status=status,
        citation_and_rights_source=catalog,
    )


def inventory(spec, raw):
    cases = []
    for name, case in spec["scenarios"].items():
        task, buffered = windows(spec, case)
        record = dict(
            scenario=name,
            requested_window_utc=task,
            hourly_inspection_window_utc=buffered,
            cst_utc=case["cst_utc"],
            lkp_lon_lat=case["lkp_lon_lat"],
            csp_lon_lat=case["csp_lon_lat"],
        )
        for role, items in endpoints(name, case).items():
            with ThreadPoolExecutor(max_workers=4) as pool:
                attempts = list(pool.map(probe, items))
            product = case[role]
            entry = source(product, spec["archive_catalogs"][product], raw / name / role, attempts)
            if role == "current" and name == "arctic_ocean":
                entry.update(published_dataset_service=HYCOM, service_catalog=HYCOM_CATALOG)
            if role == "current" and name in ("lake_ontario", "bay_of_fundy"):
                entry["additional_catalog"] = NOAA_DOC
            record[role] = entry
        record["pair_status"] = (
            "local_pair_pending_review"
            if all(record[k]["status"] == "local_files_pending_review" for k in ("wind", "current"))
            else "blocked_pending_file_verification"
        )
        cases.append(record)
    return cases


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data/raw/historical")
    parser.add_argument(
        "--output", type=Path, default=ROOT / "data/manifests/historical_sources.json"
    )
    opts = parser.parse_args()
    config = ROOT / "configs/stage7_scenarios.yaml"
    cases = inventory(yaml.safe_load(config.read_bytes()), opts.raw_dir)
    manifest = dict(
        stage="B1",
        audit_utc=utc_text(datetime.now(timezone.utc)),
        config_sha256=digest(config),
        interpreter=sys.executable,
        proxy_schemes=sorted(getproxies()),
        aws_cli=shutil.which("aws"),
        raw_root=str(opts.raw_dir.resolve()),
        scenarios=cases,
    )
    opts.output.parent.mkdir(parents=True, exist_ok=True)
    opts.output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for case in cases:
        print(case["scenario"], *case["requested_window_utc"], case["pair_status"])
    # Zero means two candidate headers can be reviewed for at least one case.
    # It makes no claim about coverage, components or suitability for B2.
    sys.exit(0 if any(c["pair_status"] == "local_pair_pending_review" for c in cases) else 2)
