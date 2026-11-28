"""Retrieve frozen H2 Hudson surface currents from the official native NCSS grid."""
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
from http.client import HTTPException
import json
from pathlib import Path
from time import sleep
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from netCDF4 import Dataset, num2date
import numpy as np
import yaml

from b1_extra_currents import packed_cf


NCSS = "https://ncss.hycom.org/thredds/ncss/grid/ESPC-D-V02/ice/2025"
CATALOG = "https://ncss.hycom.org/thredds/catalogs/ESPC-D-V02_ice.html?dataset=ESPC-D-V02-ice-2025"
VARIABLES = (
    ("ssu", "eastward_sea_water_velocity", "m/s"),
    ("ssv", "northward_sea_water_velocity", "m/s"),
    ("sic", "sea_ice_area_fraction", "1"),
)
BOX = {"north": "64.0", "south": "61.5", "west": "268", "east": "271.5"}
NETCDF4_SIGNATURE = b"\x89HDF\r\n\x1a\n"
MAX_BODY_BYTES = 2 * 1024 * 1024
TIMEOUT_SECONDS = 110
RETRYABLE_HTTP = {408, 425, 429, 500, 502, 503, 504}


class HycomRequestError(RuntimeError):
    """No verified retrieval. Transport errors alone do not prove date ineligibility."""


class HycomDataError(ValueError):
    """The downloaded native subset failed a preregistered eligibility requirement."""

    def __init__(self, reason, audit=None):
        super().__init__(reason)
        self.audit = audit


def _utc(value):
    return value.isoformat().replace("+00:00", "Z")


def requests_for(block):
    """Use the B1 three-chunk partition of the exact native hourly window."""
    if block["scene"] != "arctic_ocean":
        raise ValueError("HYCOM H2 requests apply only to the registered Hudson scenario")
    day = datetime.combine(date.fromisoformat(block["date"]), time(), timezone.utc)
    if day.year != 2025:
        raise ValueError("The preregistered HYCOM archive year is 2025")
    specs = []
    for start, count in ((day - timedelta(hours=3), 3), (day, 24), (day + timedelta(days=1), 4)):
        times = [start + timedelta(hours=i) for i in range(count)]
        query = [("var", name) for name, _, _ in VARIABLES]
        query.extend(BOX.items())
        query.extend([
            ("horizStride", 1), ("time_start", _utc(times[0])), ("time_end", _utc(times[-1])),
            ("timeStride", 1), ("addLatLon", "true"), ("accept", "netcdf4"),
        ])
        specs.append({
            "filename": f"ESPC-D-V02_surface_{start:%Y%m%d}.nc",
            "source_url": f"{NCSS}?{urlencode(query)}",
            "valid_times_utc": [stamp.isoformat() for stamp in times],
        })
    return specs


def _require(condition, reason):
    if not condition:
        raise HycomDataError(reason)


def _axis(var, name, unit, lower, upper, step):
    arr = np.ma.asarray(var[:], dtype=np.float64).filled(np.nan)
    _require(var.dimensions == (name,) and getattr(var, "units", "") == unit,
             f"HYCOM {name} axis mapping changed")
    _require(arr.ndim == 1 and arr.size > 1 and np.isfinite(arr).all()
             and np.allclose(np.diff(arr), step, rtol=0, atol=1e-4),
             f"HYCOM {name} is not the increasing unstrided native {step} degree axis")
    _require(abs(arr[0] - lower) <= step + 1e-4 and abs(arr[-1] - upper) <= step + 1e-4,
             f"HYCOM {name} extent does not match the requested box")
    return arr


def _actual_times(var):
    calendar = getattr(var, "calendar", "standard")
    values = np.ma.asarray(var[:], dtype=np.float64).filled(np.nan)
    _require(var.dimensions == ("time",) and calendar in ("standard", "gregorian", "proleptic_gregorian")
             and np.isfinite(values).all(), "Invalid HYCOM time-axis encoding")
    converted = num2date(values, var.units, calendar=calendar)
    return [
        datetime(v.year, v.month, v.day, v.hour, v.minute, v.second, v.microsecond,
                 tzinfo=timezone.utc).isoformat()
        for v in converted
    ]


def _point_stencils(lon, lat, wet, mission_points):
    checks = {}
    for name, (x, y) in (mission_points or {}).items():
        geom_lon = (x + 360) % 360
        j, i = np.searchsorted(lon, geom_lon, side="right") - 1, np.searchsorted(lat, y, side="right") - 1
        valid = (0 <= j < len(lon) - 1 and 0 <= i < len(lat) - 1 and wet[:, i:i+2, j:j+2].all())
        _require(valid, f"Invalid HYCOM native water stencil for {name}")
        checks[name] = {"bilinear_2x2_stencil_valid_all_times": True, "indices_yx": [int(i), int(j)]}
    return checks


def inspect_hycom(data, expected_times, mission_points=None):
    """Audit the original compact bytes and leave missing water values unfilled."""
    _require(data.startswith(NETCDF4_SIGNATURE), "HYCOM response was not NetCDF4/HDF5")
    with Dataset("hycom.nc", memory=data) as ds:
        _require("ESPC-D V02" in getattr(ds, "generating_model", "") and "HYCOM" in getattr(ds, "source", ""),
                 "Unexpected HYCOM product fingerprints")
        lon = _axis(ds["lon"], "lon", "degrees_east", float(BOX["west"]), float(BOX["east"]), 0.08)
        lat = _axis(ds["lat"], "lat", "degrees_north", float(BOX["south"]), float(BOX["north"]), 0.04)
        times = _actual_times(ds["time"])
        expected = [datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat() for value in expected_times]
        _require(times == expected, "Decoded HYCOM valid hours differ from the preregistered request")
        decoded, encoding = {}, {}
        for name, standard, units in VARIABLES:
            field, encoding[name] = packed_cf(ds[name], standard, units)
            decoded[name] = np.ma.asarray(field, dtype=np.float64).filled(np.nan)
        wet = np.isfinite(decoded["ssu"])
        _require(np.array_equal(wet, np.isfinite(decoded["ssv"])), "HYCOM U/V masks disagree")
        _require(np.all(np.any(wet, axis=(1, 2))), "A HYCOM frame has no valid native water samples")
        _require(all(np.abs(decoded[name][wet]).max() < 20 for name in ("ssu", "ssv")),
                 "Implausible HYCOM current speed after CF decoding")
        sic = decoded["sic"][wet]
        wet_ice_finite = np.isfinite(sic)
        n_unknown = int(np.count_nonzero(~wet_ice_finite))
        n_nonzero = int(np.count_nonzero(wet_ice_finite & (sic != 0)))
        audit = {
            "valid_times_utc": times,
            "product": "ESPC-D-V02",
            "dimensions": {name: len(dim) for name, dim in ds.dimensions.items()},
            "lon_lat_bounds": [float(lon[0]), float(lon[-1]), float(lat[0]), float(lat[-1])],
            "coordinate_sha256": sha256(lon.astype("<f8").tobytes() + lat.astype("<f8").tobytes()).hexdigest(),
            "vector_basis": "geographic_east_north",
            "native_variables": ["ssu", "ssv"],
            "auxiliary_variables": ["sic"],
            "encoding": encoding,
            "known_wet_samples": int(wet.sum()),
            "nonzero_ice_wet_samples": n_nonzero,
            "unknown_ice_wet_samples": n_unknown,
            "ice_max_wet": float(sic[wet_ice_finite].max()) if wet_ice_finite.any() else None,
            "time_units": ds["time"].units,
            "run_cycle_status": "annual_archive_per_frame_lineage_not_verified",
            "point_checks": _point_stencils(lon, lat, wet, mission_points),
        }
        if n_unknown or n_nonzero:
            raise HycomDataError(
                f"nonzero or unknown sea ice on native water: {n_nonzero} nonzero, {n_unknown} unknown", audit
            )
    return audit


def _download(url):
    req = Request(url, headers={"User-Agent": "ASAR-H2-research-audit/1.0", "Accept-Encoding": "identity"})
    with urlopen(req, timeout=TIMEOUT_SECONDS) as response:
        headers = {key: response.headers.get(key) for key in
                   ("Content-Type", "Content-Length", "Content-Disposition", "Last-Modified", "Date", "ETag")}
        if response.status != 200 or response.geturl() != url:
            raise HycomRequestError("Official NCSS endpoint returned unexpected status or redirected")
        payload = response.read(MAX_BODY_BYTES + 1)
    if len(payload) > MAX_BODY_BYTES:
        raise HycomRequestError("NCSS payload exceeded the cap for a native regional chunk")
    if headers["Content-Length"] is not None and len(payload) != int(headers["Content-Length"]):
        raise OSError("HTTP Content-Length and received byte count disagree")
    return payload, headers


def _write_json(path, doc):
    with path.open("x", encoding="utf-8", newline="\n") as target:
        json.dump(doc, target, indent=2, allow_nan=False)
        target.write("\n")


def _receipt_base(block, spec, attempt):
    return {
        "block_id": block["id"], "product": "ESPC-D-V02", "attempt": attempt,
        "requested_utc": datetime.now(timezone.utc).isoformat(),
        "catalog_url": CATALOG, "source_url": spec["source_url"],
        "valid_times_utc": spec["valid_times_utc"],
    }


def _audited_receipt(receipt, body, points):
    result = receipt.copy()
    try:
        result.update(status="accepted", audit=inspect_hycom(body, receipt["valid_times_utc"], points))
    except (OSError, KeyError, AttributeError, AssertionError, ValueError, OverflowError) as exc:
        result.update(status="rejected_data", error=str(exc), audit=getattr(exc, "audit", None))
    else:
        result.pop("error", None)
    return result


def _retrieve_chunk(root, directory, block, spec, attempts, points):
    filename = directory / spec["filename"]
    for attempt in range(1, attempts + 1):
        receipt_path = filename.with_suffix(f".attempt-{attempt}.json")
        if receipt_path.exists():
            saved = json.loads(receipt_path.read_text(encoding="utf-8"))
            if (saved["source_url"] != spec["source_url"] or saved["valid_times_utc"] != spec["valid_times_utc"]
                    or saved["block_id"] != block["id"] or saved["attempt"] != attempt):
                raise HycomRequestError(f"Saved NCSS request identity mismatch: {receipt_path}")
            if saved["status"] in ("accepted", "rejected_data"):
                body = filename.read_bytes()
                if saved["sha256"] != sha256(body).hexdigest() or saved["bytes"] != len(body):
                    raise HycomRequestError(f"Saved NCSS payload bytes changed: {filename}")
                reviewed = _audited_receipt(saved, body, points)
                if reviewed != saved:
                    # Keep the raw attempt immutable if a corrected local validator
                    # produces a new audit on the same archived response.
                    revision = filename.with_suffix(".local-audit-v2.json")
                    reviewed.update(
                        original_receipt_sha256=sha256(receipt_path.read_bytes()).hexdigest(),
                        original_receipt_path=saved["receipt_path"],
                        receipt_path=revision.relative_to(root).as_posix(),
                    )
                    if not revision.exists():
                        _write_json(revision, reviewed)
                    if json.loads(revision.read_text(encoding="utf-8")) != reviewed:
                        raise HycomRequestError(f"Saved NCSS local audit changed: {revision}")
                return reviewed
            if saved["status"] != "retryable_transport_error":
                raise HycomRequestError(saved["error"])
            continue
        if filename.exists():
            raise HycomRequestError(f"NCSS payload exists without a matching receipt: {filename}")
        receipt = _receipt_base(block, spec, attempt)
        try:
            body, headers = _download(spec["source_url"])
        except (OSError, HTTPException, HycomRequestError) as exc:
            code = exc.code if isinstance(exc, HTTPError) else None
            retryable = (isinstance(exc, (OSError, HTTPException)) and (code is None or code in RETRYABLE_HTTP))
            status = "retryable_transport_error" if retryable else "unverified_response"
            receipt.update(status=status, http_status=code, error=str(exc))
            _write_json(receipt_path, receipt)
            if retryable:
                if attempt < attempts:
                    sleep(attempt)
                continue
            raise HycomRequestError(str(exc)) from exc
        # Keep catalog-byte evidence for both eligible and rejected subsets.
        with filename.open("xb") as stream:
            stream.write(body)
        receipt.update(http_status=200, http_headers=headers, bytes=len(body), sha256=sha256(body).hexdigest(),
                       local_path=filename.relative_to(root).as_posix(),
                       receipt_path=receipt_path.relative_to(root).as_posix())
        receipt = _audited_receipt(receipt, body, points)
        _write_json(receipt_path, receipt)
        return receipt
    raise HycomRequestError(f"NCSS transport not resolved after {attempts} attempts: {spec['source_url']}")


def acquire_hycom(root, raw, block, max_attempts=3):
    """Fetch three disjoint official chunks and preserve exact per-attempt receipts."""
    if type(max_attempts) is not int or not 1 <= max_attempts <= 3:
        raise ValueError("NCSS max_attempts must be an integer in [1, 3]")
    specs = requests_for(block)
    root, raw = Path(root).resolve(), Path(raw).resolve()
    raw.relative_to(root)
    directory = raw / "hycom"
    directory.mkdir(parents=True, exist_ok=True)
    scenarios = yaml.safe_load((root / "configs/stage7_scenarios.yaml").read_text(encoding="utf-8"))["scenarios"]
    mission = scenarios["arctic_ocean"]
    points = {"LKP": mission["lkp_lon_lat"], "CSP": mission["csp_lon_lat"]}
    rows = [_retrieve_chunk(root, directory, block, spec, max_attempts, points) for spec in specs]
    if all(row["status"] == "accepted" for row in rows) and len({row["audit"]["coordinate_sha256"] for row in rows}) != 1:
        raise HycomDataError("HYCOM native grid changed between chunks")
    return rows

