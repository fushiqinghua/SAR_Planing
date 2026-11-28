"""Acquire byte-identical NOAA forcing inputs for a preregistered H2 block.

The caller selects a registered block. This module implements its fixed products
and times and records each request. It does not decide dataset eligibility:
the independent reader must still decode and qualify each downloaded input.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


LOOFS_ROOT = "https://noaa-nos-ofs-pds.s3.amazonaws.com"
HRRR_ROOT = "https://noaa-hrrr-bdp-pds.s3.amazonaws.com"
GFS_ROOT = "https://noaa-gfs-bdp-pds.s3.amazonaws.com"
INDEX_LIMIT = 1024 * 1024
GRIB_MESSAGE_LIMIT = 32 * 1024 * 1024
LOOFS_OBJECT_LIMIT = 256 * 1024 * 1024
WIND_LEVEL = "10 m above ground"
WIND_NAMES = {"UGRD", "VGRD"}
S3_XML = "{http://s3.amazonaws.com/doc/2006-03-01/}"


class AcquisitionError(ValueError):
    def __init__(self, message, *, reason="integrity", retriable=False):
        super().__init__(message)
        self.reason = reason
        self.retriable = retriable


def _utc(value):
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _sha_file(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _write_once(path, data):
    """Publish complete bytes. Existing evidence can be reused or rejected."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.stat().st_size != len(data) or _sha_file(path) != _sha_bytes(data):
            raise AcquisitionError(f"Existing artifact has conflicting bytes: {path}", reason="local_evidence")
        return
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".part", delete=False) as stream:
        pending = Path(stream.name)
        try:
            stream.write(data)
        except BaseException:
            stream.close()
            pending.unlink(missing_ok=True)
            raise
    try:
        if os.name == "nt":
            pending.rename(path)
        else:
            os.link(pending, path)
    except FileExistsError:
        if path.stat().st_size != len(data) or _sha_file(path) != _sha_bytes(data):
            raise AcquisitionError(f"Concurrent artifact conflicts: {path}", reason="local_evidence")
    finally:
        pending.unlink(missing_ok=True)


def _row_identity(root, path, data):
    return {"local_path": path.relative_to(root).as_posix(), "sha256": _sha_bytes(data), "bytes": len(data)}


def _record(path, row):
    with path.open("a", encoding="utf-8", newline="\n") as out:
        out.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")


def _verify_headers(status, headers, *, byte_range=None, size=None, etag=None):
    expected_status = 206 if byte_range else 200
    if status != expected_status:
        raise AcquisitionError(f"Expected HTTP {expected_status}, received HTTP {status}")
    if headers.get("content-encoding", "identity").strip().lower() != "identity":
        raise AcquisitionError("Unexpected non-identity content encoding")
    if headers.get("content-type", "").split(";")[0].strip().lower() in {
        "text/html", "application/xhtml+xml"
    }:
        raise AcquisitionError("Received an HTML page instead of an archive artifact")
    if etag is not None and headers.get("etag") != etag:
        raise AcquisitionError("S3 object ETag differs from the selected object")
    if byte_range:
        bounds = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", headers.get("content-range", ""))
        if not bounds:
            raise AcquisitionError("Missing or invalid Content-Range")
        start, end, total = map(int, bounds.groups())
        if (start, end) != byte_range or total <= end:
            raise AcquisitionError("Content-Range differs from requested inclusive byte range")
    length = headers.get("content-length")
    if length is not None and (not length.isdecimal() or (size is not None and int(length) != size)):
        raise AcquisitionError("Content-Length differs from the required byte count")


def _verify_payload(data, kind):
    start = data[:200].lstrip().lower()
    if not data or start.startswith((b"<html", b"<!doctype html")):
        raise AcquisitionError("Empty or HTML response body")
    if kind == "grib" and (
        len(data) < 20 or data[:4] != b"GRIB" or data[7] != 2
        or int.from_bytes(data[8:16], "big") != len(data) or data[-4:] != b"7777"
    ):
        raise AcquisitionError("Requested range is not a complete original GRIB2 message")
    if kind == "netcdf" and not data.startswith((b"CDF\x01", b"CDF\x02", b"CDF\x05", b"\x89HDF\r\n\x1a\n")):
        raise AcquisitionError("Downloaded object does not have a NetCDF signature")


def _fetch(receipts, url, purpose, max_attempts, *, limit, kind, size=None, byte_range=None, etag=None):
    headers = {"Accept-Encoding": "identity"}
    if byte_range:
        headers["Range"] = f"bytes={byte_range[0]}-{byte_range[1]}"
    if etag is not None:
        headers["If-Match"] = etag
    request = Request(url, headers=headers)
    for attempt in range(1, max_attempts + 1):
        receipt = {
            "purpose": purpose,
            "url": url,
            "attempt": attempt,
            "request_headers": headers,
            "started_utc": _utc(datetime.now(timezone.utc)),
        }
        error = None
        try:
            with urlopen(request, timeout=60) as response:
                response_headers = {k.lower(): v for k, v in response.headers.items()}
                receipt.update(
                    status=response.status,
                    response_url=response.geturl(),
                    response_headers={
                        k: response_headers[k]
                        for k in ("content-type", "content-length", "content-range", "content-encoding",
                                  "etag", "last-modified", "x-amz-request-id", "x-amz-id-2")
                        if k in response_headers
                    },
                )
                if receipt["response_url"] != url:
                    raise AcquisitionError("Response URL differs from the registered archive request")
                _verify_headers(response.status, response_headers, byte_range=byte_range, size=size, etag=etag)
                expected_length = int(response_headers["content-length"]) if "content-length" in response_headers else size
                if expected_length is not None and expected_length > limit:
                    raise AcquisitionError("Artifact exceeds the expected download size limit")
                data = response.read(limit + 1)
                receipt["bytes"] = len(data)
                if len(data) > limit:
                    raise AcquisitionError("Artifact exceeds the expected download size limit")
                if (size is not None and len(data) != size) or (
                    expected_length is not None and len(data) != expected_length
                ):
                    raise AcquisitionError("Incomplete artifact response", reason="network", retriable=True)
                _verify_payload(data, kind)
                receipt.update(sha256=_sha_bytes(data), outcome="verified_transfer")
        except HTTPError as e:
            receipt["status"] = e.code
            receipt["response_url"] = e.geturl()
            e.close()
            reason = "source_missing" if e.code in {404, 410} else "provider_http"
            error = AcquisitionError(
                f"HTTP {e.code} for {purpose}: {url}", reason=reason,
                retriable=(e.code in {408, 429} or 500 <= e.code <= 599),
            )
        except AcquisitionError as e:
            error = e
        except (URLError, TimeoutError, ConnectionError, http.client.HTTPException, OSError) as e:
            error = AcquisitionError(f"{purpose} request failed: {e}", reason="network", retriable=True)
        receipt["ended_utc"] = _utc(datetime.now(timezone.utc))
        if error is None:
            _record(receipts, receipt)
            return data, receipt["response_headers"]
        receipt.update(outcome="failed", error=str(error), reason=error.reason, retriable=error.retriable)
        _record(receipts, receipt)
        if not error.retriable or attempt == max_attempts:
            raise error
    raise AssertionError("Request attempt count should have been validated")


def parse_wind_index(index, cycle, lead_hours):
    """Find each 10 m component and its complete original GRIB byte range."""
    try:
        lines = [line for line in index.decode("ascii").splitlines() if line.strip()]
        rows = [line.split(":") for line in lines]
        offsets = [int(row[1]) for row in rows]
    except (UnicodeDecodeError, ValueError, IndexError) as e:
        raise AcquisitionError("Invalid NOAA GRIB inventory bytes") from e
    if not offsets or offsets[0] != 0 or any(b < a for a, b in zip(offsets, offsets[1:])):
        raise AcquisitionError("Invalid or unsorted NOAA GRIB inventory offsets")
    expected_cycle = f"d={cycle:%Y%m%d%H}"
    expected_forecast = "anl" if lead_hours == 0 else f"{lead_hours} hour fcst"
    selected = {}
    for position, row in enumerate(rows):
        if len(row) < 6 or row[3] not in WIND_NAMES or row[4] != WIND_LEVEL:
            continue
        variable = row[3]
        if row[2] != expected_cycle or row[5] != expected_forecast:
            raise AcquisitionError(f"Wrong cycle or lead for {variable} in the requested wind inventory")
        if variable in selected or not row[0].isdecimal() or position + 1 == len(rows):
            raise AcquisitionError(f"Ambiguous or unbounded original byte range for {variable}")
        start, next_start = offsets[position:position + 2]
        if start == next_start or (position and offsets[position - 1] == start):
            raise AcquisitionError(f"Shared original GRIB message offset for {variable}")
        if next_start - start > GRIB_MESSAGE_LIMIT:
            raise AcquisitionError(f"Original GRIB message for {variable} exceeds the single-message limit")
        selected[variable] = {
            "variable": variable,
            "level": WIND_LEVEL,
            "start": start,
            "end_inclusive": next_start - 1,
            "index_line": lines[position],
        }
    if set(selected) != WIND_NAMES:
        raise AcquisitionError("Missing UGRD or VGRD at 10 m in the requested wind inventory")
    return sorted(selected.values(), key=lambda row: row["start"])


def parse_loofs_listing(data, prefix, expected_keys):
    """Require actual listing entries rather than relying on constructed keys."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise AcquisitionError("NOAA public S3 listing is not valid XML") from e
    if (
        root.tag != S3_XML + "ListBucketResult"
        or root.findtext(S3_XML + "Name") != "noaa-nos-ofs-pds"
        or root.findtext(S3_XML + "Prefix") != prefix
        or root.findtext(S3_XML + "IsTruncated") != "false"
    ):
        raise AcquisitionError("NOAA public S3 listing did not confirm the complete requested prefix")
    objects = {}
    for entry in root.findall(S3_XML + "Contents"):
        key = entry.findtext(S3_XML + "Key")
        if key not in expected_keys:
            continue
        etag = entry.findtext(S3_XML + "ETag")
        size = entry.findtext(S3_XML + "Size", "")
        last_modified = entry.findtext(S3_XML + "LastModified")
        if key in objects or not (etag and last_modified and size.isdecimal()
                                    and 0 < int(size) <= LOOFS_OBJECT_LIMIT):
            raise AcquisitionError(f"Invalid or duplicate S3 listing metadata for {key}")
        objects[key] = {"object_key": key, "etag": etag, "size": int(size), "last_modified": last_modified}
    missing = set(expected_keys).difference(objects)
    if missing:
        raise AcquisitionError(f"Required LOOFS objects absent from the provider listing: {sorted(missing)}",
                               reason="source_missing")
    return objects


def _read_existing_row(root, manifest, expected, *, index=False):
    if not manifest.exists():
        return None
    try:
        row = json.loads(manifest.read_bytes())
        if any(row.get(key) != value for key, value in expected.items()):
            raise ValueError("row identity differs from the registered request")
        path = root / row["local_path"]
        if path.stat().st_size != row["bytes"] or _sha_file(path) != row["sha256"]:
            raise ValueError("archived artifact SHA-256 or size mismatch")
        if index:
            index_path = root / row["index_path"]
            if _sha_file(index_path) != row["index_sha256"]:
                raise ValueError("archived wind index SHA-256 mismatch")
        return row
    except (KeyError, OSError, ValueError) as e:
        raise AcquisitionError(f"Invalid preserved source row {manifest}: {e}", reason="local_evidence") from e


def _save_row(path, row):
    _write_once(path, (json.dumps(row, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def _wind_source(root, folder, receipts, product, url, cycle, lead, attempts):
    name = url.rsplit("/", 1)[1]
    path = folder / (name + ".wind10m.grib2")
    manifest = path.with_name(path.name + ".source.json")
    index_path = folder / (name + ".idx")
    index_url = url + ".idx"
    expected = {
        "product": product,
        "source_url": url,
        "local_path": path.relative_to(root).as_posix(),
        "index_url": index_url,
        "index_path": index_path.relative_to(root).as_posix(),
        "run_cycle_utc": _utc(cycle),
        "valid_utc": _utc(cycle + timedelta(hours=lead)),
        "lead_hours": lead,
        "forecast_or_analysis": "analysis_f00" if lead == 0 else "forecast",
        "source_kind": "byte_exact_selected_original_grib_messages",
    }
    cached = _read_existing_row(root, manifest, expected, index=True)
    if cached is not None:
        return cached
    index, index_headers = _fetch(receipts, index_url, "wind_index", attempts, limit=INDEX_LIMIT, kind="index")
    _write_once(index_path, index)
    selected = parse_wind_index(index, cycle, lead)
    components = []
    etag, total = None, None
    for component in selected:
        start, end = component["start"], component["end_inclusive"]
        data, headers = _fetch(
            receipts, url, "wind_" + component["variable"], attempts, limit=end - start + 1,
            kind="grib", size=end - start + 1, byte_range=(start, end), etag=etag,
        )
        current_total = int(headers["content-range"].rsplit("/", 1)[1])
        current_etag = headers.get("etag")
        if not current_etag or (total is not None and (current_total != total or current_etag != etag)):
            raise AcquisitionError("Wind byte ranges lack proof of the same source object")
        etag, total = current_etag, current_total
        component.update(sha256=_sha_bytes(data), response={"http_status": 206, **headers})
        components.append(data)
    data = b"".join(components)
    _write_once(path, data)
    row = expected | _row_identity(root, path, data) | {
        "index_sha256": _sha_bytes(index),
        "index_response": {"http_status": 200, **index_headers},
        "byte_ranges": selected,
        "source_object_etag": etag,
        "source_object_bytes": total,
    }
    _save_row(manifest, row)
    return row


def _loofs_sources(root, folder, receipts, day, attempts):
    cycle = datetime.combine(day, time(18), timezone.utc)
    prefix = f"loofs/netcdf/{day:%Y/%m/%d}/loofs.t18z.{day:%Y%m%d}.fields.n"
    # LOOFS numbers its nowcast fields in chronological order: n001 is
    # cycle−5 h; n005 is cycle−1 h. The reader checks the file's UTC itself.
    indices = tuple(range(1, 6))
    keys = tuple(f"{prefix}{index:03}.nc" for index in indices)
    listing_url = LOOFS_ROOT + "/?" + urlencode({"list-type": "2", "prefix": prefix})
    listing_path = folder / "loofs_18z_provider_listing.xml"
    listing_manifest = listing_path.with_name(listing_path.name + ".source.json")
    listing_expected = {"source_url": listing_url, "local_path": listing_path.relative_to(root).as_posix()}
    listing_row = _read_existing_row(root, listing_manifest, listing_expected)
    if listing_row is None:
        listing_data, listing_headers = _fetch(
            receipts, listing_url, "current_provider_listing", attempts, limit=INDEX_LIMIT, kind="listing"
        )
        _write_once(listing_path, listing_data)
        listing_row = listing_expected | _row_identity(root, listing_path, listing_data) | {
            "response": {"http_status": 200, **listing_headers},
        }
        _save_row(listing_manifest, listing_row)
    else:
        listing_data = listing_path.read_bytes()
    objects = parse_loofs_listing(listing_data, prefix, keys)
    rows = []
    for key, index in zip(keys, indices):
        lead = index - 6
        url = LOOFS_ROOT + "/" + quote(key, safe="/")
        info = objects[key]
        path = folder / key.rsplit("/", 1)[1]
        manifest = path.with_name(path.name + ".source.json")
        expected = {
            "product": "LOOFS",
            "source_url": url,
            "local_path": path.relative_to(root).as_posix(),
            "run_cycle_utc": _utc(cycle),
            "valid_utc": _utc(cycle + timedelta(hours=lead)),
            "lead_hours": lead,
            "forecast_or_analysis": "nowcast",
            "source_kind": "byte_exact_original_netcdf",
            "listing_url": listing_url,
            "listing_path": listing_row["local_path"],
            "listing_sha256": listing_row["sha256"],
            "listed_object": info,
        }
        row = _read_existing_row(root, manifest, expected)
        if row is None:
            data, headers = _fetch(receipts, url, "current_loofs_native_field", attempts,
                                   limit=info["size"], kind="netcdf", size=info["size"], etag=info["etag"])
            _write_once(path, data)
            row = expected | _row_identity(root, path, data) | {"response": {"http_status": 200, **headers}}
            _save_row(manifest, row)
        rows.append(row)
    return rows


def acquire_noaa(root: Path, raw: Path, block: dict, max_attempts: int = 3) -> dict:
    """Fetch one selected block's NOAA products and preserve original bytes and receipts."""
    root = Path(root).resolve()
    raw = (root / raw).resolve()
    if not raw.is_relative_to((root / "data/raw/h2").resolve()):
        raise ValueError("H2 raw NOAA downloads must be under data/raw/h2")
    if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or not 1 <= max_attempts <= 3:
        raise ValueError("NOAA requests allow one through three attempts")
    block_id, scene, day = block["id"], block["scene"], date.fromisoformat(block["date"])
    if scene not in {"lake_ontario", "arctic_ocean"} or not re.fullmatch(r"[a-z][a-z0-9_]*", block_id):
        raise ValueError("Invalid NOAA H2 block identity")
    folder = (raw / block_id).resolve()
    if not folder.is_relative_to(raw):
        raise ValueError("H2 block folder resolves outside its raw directory")
    folder.mkdir(parents=True, exist_ok=True)
    receipts = folder / "noaa_request_receipts.jsonl"
    wind_dir = folder / "noaa_wind"
    if scene == "lake_ontario":
        wind = [
            _wind_source(root, wind_dir, receipts, "HRRR",
                         f"{HRRR_ROOT}/hrrr.{day:%Y%m%d}/conus/hrrr.t{hour:02}z.wrfsfcf00.grib2",
                         datetime.combine(day, time(hour), timezone.utc), 0, max_attempts)
            for hour in range(13, 18)
        ]
        current = _loofs_sources(root, folder / "loofs", receipts, day, max_attempts)
    else:
        cycle = datetime.combine(day - timedelta(days=1), time(18), timezone.utc)
        wind = [
            _wind_source(root, wind_dir, receipts, "GFS",
                         f"{GFS_ROOT}/gfs.{cycle:%Y%m%d}/18/atmos/gfs.t18z.pgrb2.0p25.f{lead:03}",
                         cycle, lead, max_attempts)
            for lead in range(3, 34, 3)
        ]
        current = []
    return {
        "block_id": block_id,
        "scene": scene,
        "date": day.isoformat(),
        "wind": wind,
        "current": current,
        "receipts": [receipts.relative_to(root).as_posix()],
    }

