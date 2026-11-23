"""Fetch a small Lake Ontario sample from archive indexes; preserve the original encodings."""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import os
import sys
from uuid import uuid4
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

import yaml
from inventory_historical import ROOT, NOS, utc_datetime, windows, utc_text
from asar_repro.scenarios import digest


def archive_file(tmp, target, sha):
    """Publish complete bytes once; a retry must match an existing archive."""
    try:
        os.link(tmp, target)
    except FileExistsError:
        if digest(target) != sha:
            raise ValueError(f"different bytes already exist at {target}")


def selected_ranges(index):
    """Keep complete GRIB messages, using the next record offset for each endpoint."""
    lines = [line.split(":") for line in index.splitlines() if line.strip()]
    selected = {}
    for i, fields in enumerate(lines):
        if len(fields) < 6 or fields[3:5] not in (
            ["UGRD", "10 m above ground"],
            ["VGRD", "10 m above ground"],
        ):
            continue
        name = fields[3]
        if name in selected or i + 1 == len(lines):
            raise ValueError("ambiguous or unbounded 10 m wind message")
        start, end = int(fields[1]), int(lines[i + 1][1]) - 1
        if start < 0 or end < start:
            raise ValueError("invalid GRIB inventory offsets")
        selected[name] = (start, end)
    if set(selected) != {"UGRD", "VGRD"}:
        raise ValueError("both 10 m wind components required")
    return selected


def fetch_wind(base, dest):
    with urlopen(base + ".idx", timeout=20) as response:
        idx = response.read(1024 * 1024).decode("ascii")
    ranges = selected_ranges(idx)
    messages = []
    for start, end in sorted(ranges.values()):
        if end - start + 1 > 32 * 1024 * 1024:
            raise ValueError("wind message exceeds B1 sample size")
        request = Request(base, headers={"Range": f"bytes={start}-{end}"})
        with urlopen(request, timeout=40) as response:
            if response.status != 206 or not response.headers.get("Content-Range", "").startswith(
                f"bytes {start}-{end}/"
            ):
                raise ValueError("provider did not honor requested byte range")
            msg = response.read(end - start + 2)
        if (
            len(msg) != end - start + 1
            or msg[:4] != b"GRIB"
            or msg[7:8] != b"\x02"
            or int.from_bytes(msg[8:16], "big") != len(msg)
            or msg[-4:] != b"7777"
        ):
            raise ValueError("incomplete GRIB2 message")
        messages.append(msg)
    payload = b"".join(messages)
    path = dest / (base.rsplit("/", 1)[1] + ".wind10m.grib2")
    path.parent.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(payload).hexdigest()
    tmp = path.with_name(f".{uuid4().hex}.part")
    try:
        tmp.write_bytes(payload)
        archive_file(tmp, path, sha)
    finally:
        tmp.unlink(missing_ok=True)
    return dict(
        url=base,
        index_url=base + ".idx",
        index_sha256=hashlib.sha256(idx.encode("ascii")).hexdigest(),
        byte_ranges=ranges,
        subset_sha256=sha,
        full_object_sha256=None,
        local_path=path.name,
        size_bytes=len(payload),
        acquired_utc=utc_text(datetime.now(timezone.utc)),
    )


def current_keys(date):
    # Some monthly layouts place the forecast hour before the date in each name.
    # Page through the listing and retain only names belonging to the required day.
    keys = {}
    for model in ("loofs", "laofs"):
        prefixes = [
            f"{model}/netcdf/{date:%Y/%m/%d}/",
            f"{model}/netcdf/{date:%Y%m}/",
        ]
        for prefix in prefixes:
            params = {"list-type": 2, "prefix": prefix, "max-keys": 1000}
            while True:
                with urlopen(NOS + "?" + urlencode(params), timeout=20) as response:
                    tree = ET.parse(response)
                for obj in tree.findall(".//{*}Contents"):
                    key = obj.findtext("{*}Key")
                    if f"{date:%Y%m%d}" in key or f"/{date:%Y/%m/%d}/" in key:
                        keys[key] = int(obj.findtext("{*}Size"))
                token = tree.findtext("{*}NextContinuationToken")
                if not token:
                    break
                params["continuation-token"] = token
    return keys


def select_current(keys, cycle, hours):
    cycle_keys = {
        k: n
        for k, n in keys.items()
        if (cycle.strftime("%Y%m%d") in k or f"/{cycle:%Y/%m/%d}/" in k)
        and f"t{cycle:%H}z" in k
        and k.endswith(".nc")
        and (".fields." in k or ".2ds." in k)
    }
    hourly = []
    for h in hours:
        options = [key for key in cycle_keys if f".f{h:03}." in key]
        if options:
            hourly.append(min(options, key=cycle_keys.get))
    whole = [k for k in cycle_keys if ".forecast." in k]
    choices = [[k] for k in whole]
    if len(hourly) == len(hours):
        choices.append(hourly)
    if not choices:
        raise ValueError(
            "no listed 12Z field sequence covers the requested hours; inspect NCEI catalog"
        )
    return min(choices, key=lambda files: sum(cycle_keys[k] for k in files))


def fetch_current(dest, cycle, hours, max_bytes):
    keys = current_keys(cycle)
    chosen = select_current(keys, cycle, hours)
    if sum(keys[k] for k in chosen) > max_bytes:
        raise ValueError(f"listed fields exceed byte budget: {[(k,keys[k]) for k in chosen]}")
    dest.mkdir(parents=True, exist_ok=True)
    for k in chosen:
        url = NOS + quote(k)
        out = dest / Path(k).name
        tmp = dest / f".{uuid4().hex}.part"
        try:
            with urlopen(url, timeout=60) as response, tmp.open("wb") as fp:
                total = 0
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > keys[k]:
                        raise ValueError("object larger than listed size")
                    fp.write(chunk)
            if tmp.stat().st_size != keys[k]:
                raise ValueError("size differs from object listing")
            with tmp.open("rb") as fp:
                signature = fp.read(8)
            if (
                signature[:4] not in (b"CDF\x01", b"CDF\x02", b"CDF\x05")
                and signature != b"\x89HDF\r\n\x1a\n"
            ):
                raise ValueError("object lacks a NetCDF or HDF5 file signature")
            sha = digest(tmp)
            archive_file(tmp, out, sha)
        finally:
            tmp.unlink(missing_ok=True)
        yield dict(
            url=url,
            local_path=out.name,
            size_bytes=keys[k],
            sha256=sha,
            acquired_utc=utc_text(datetime.now(timezone.utc)),
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data/raw/historical")
    parser.add_argument("--max-current-mib", type=int, default=256)
    opts = parser.parse_args()
    spec = yaml.safe_load((ROOT / "configs/stage7_scenarios.yaml").read_bytes())
    case = spec["scenarios"]["lake_ontario"]
    low, high = map(utc_datetime, windows(spec, case)[1])
    cycle = low.replace(hour=12)
    hours = [
        int((low - cycle) / timedelta(hours=1)) + i
        for i in range(1 + int((high - low) / timedelta(hours=1)))
    ]
    dest = opts.raw_dir / "lake_ontario"
    dest.mkdir(parents=True, exist_ok=True)
    receipt = dict(
        attempted_at_utc=utc_text(datetime.now(timezone.utc)),
        cycle_requested_utc=utc_text(cycle),
        max_current_bytes=opts.max_current_mib * 1024**2,
        requested_lead_hours=hours,
        wind=[],
        current=[],
        errors={},
    )
    for role in ("wind", "current"):
        try:
            if role == "wind":
                for h in hours:
                    base = f"https://noaa-hrrr-bdp-pds.s3.amazonaws.com/hrrr.{cycle:%Y%m%d}/conus/hrrr.t{cycle:%H}z.wrfsfcf{h:02}.grib2"
                    receipt[role].append(fetch_wind(base, dest / role))
            else:
                receipt[role].extend(
                    fetch_current(dest / role, cycle, hours, opts.max_current_mib * 1024**2)
                )
        except (OSError, ValueError, ET.ParseError) as err:
            receipt["errors"][role] = str(err)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    (dest / f"acquisition_{stamp}.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 2 if receipt["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
