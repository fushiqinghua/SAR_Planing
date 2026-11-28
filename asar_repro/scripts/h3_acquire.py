#!/usr/bin/env python3
"""Acquire only the P2/H3 dates and products selected by the forcing audit."""
from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
import traceback

from h2_acquire import (
    AcquisitionError, GFS_ROOT, HRRR_ROOT, _loofs_sources, _wind_source,
)
from h2_hycom import HycomDataError, acquire_hycom
from h3_protocol import (
    DEFAULT_OUT, PROVIDER_ATTEMPTS, RAW, ROOT, batch_directory, choose_dates,
    digest, freeze_method, method_lock, read, save, stamp, verify_method,
)


def wind_requests(block):
    day = date.fromisoformat(block["date"])
    if block["scene"] == "lake_ontario":
        return [
            ("HRRR", f"{HRRR_ROOT}/hrrr.{day:%Y%m%d}/conus/hrrr.t{hour:02}z.wrfsfcf00.grib2",
             datetime.combine(day, time(hour), timezone.utc), 0)
            for hour in range(13, 18)
        ]
    if block["scene"] == "arctic_ocean":
        cycle = datetime.combine(day - timedelta(days=1), time(18), timezone.utc)
        return [
            ("GFS", f"{GFS_ROOT}/gfs.{cycle:%Y%m%d}/18/atmos/gfs.t18z.pgrb2.0p25.f{lead:03}",
             cycle, lead)
            for lead in range(3, 34, 3)
        ]
    raise ValueError(f"Unknown H3 scene: {block['scene']}")


def acquire_noaa_h3(raw, block):
    raw.mkdir(parents=True, exist_ok=False)
    receipts = raw / "noaa_request_receipts.jsonl"
    wind = [_wind_source(ROOT, raw / "wind", receipts, *source, PROVIDER_ATTEMPTS)
            for source in wind_requests(block)]
    current = []
    if block["scene"] == "lake_ontario":
        current = _loofs_sources(ROOT, raw / "loofs", receipts, date.fromisoformat(block["date"]),
                                 PROVIDER_ATTEMPTS)
    return dict(wind=wind, current=current)


def attempt_files(out, block, provider):
    return sorted((out / "sources" / block["id"] / provider).glob("a*.json"))


def acquire_block(out, block, provider, retry_transport, hycom_access, blocked_captures):
    existing = attempt_files(out, block, provider)
    if existing:
        previous = existing[-1]
        blocked = (read(previous)["status"] == "blocked"
                   or blocked_captures.get(previous.relative_to(out).as_posix()) == digest(previous))
        if not retry_transport or not blocked:
            print(f"{block['id']} {provider}: retaining {previous.name}", flush=True)
            return
    destination = out / "sources" / block["id"] / provider
    attempt = f"a{len(existing) + 1:03d}"
    # This exclusive claim also leaves evidence if a download process is interrupted.
    started = dict(block_id=block["id"], scene=block["scene"], date=block["date"],
                   provider=provider, attempt=attempt, started=stamp(),
                   method_lock_sha256=digest(method_lock(out)))
    save(destination / "claims" / f"{attempt}.json", started)
    raw = RAW / block["id"] / out.name / provider / attempt
    if not raw.resolve().is_relative_to((RAW / block["id"]).resolve()) or raw.exists():
        raise ValueError(f"Unexpected existing or escaped raw attempt: {raw}")
    try:
        if provider == "noaa":
            native = acquire_noaa_h3(raw, block)
        elif hycom_access == "ncss":
            native = dict(wind=[], current=acquire_hycom(ROOT, raw, block, PROVIDER_ATTEMPTS))
        else:
            from h3_hycom_dap import acquire_hycom_dap

            native = dict(wind=[], current=acquire_hycom_dap(ROOT, raw, block, PROVIDER_ATTEMPTS))
        result = dict(status="retrieved", **native)
    except Exception as exc:
        # A 404 on an aggregate OPeNDAP route need not mean that a specific date is missing.
        verified_missing = (provider == "noaa" and isinstance(exc, AcquisitionError)
                            and exc.reason == "source_missing")
        result = dict(status="ineligible" if verified_missing else "blocked",
                      reason="source_missing" if verified_missing else "unverified_acquisition",
                      error=str(exc), error_type=type(exc).__name__,
                      acquisition_reason=getattr(exc, "reason", None),
                      details=exc.audit if isinstance(exc, HycomDataError) else None,
                      traceback=traceback.format_exc())
    receipts = {
        path.relative_to(ROOT).as_posix(): digest(path)
        for path in sorted(raw.rglob("*"))
        if path.is_file() and path.suffix in {".json", ".jsonl", ".idx", ".xml", ".das", ".txt"}
    }
    save(destination / f"{attempt}.json",
         dict(started, **result, completed=stamp(), receipt_sha256=receipts))
    print(f"{block['id']} {provider}: {result['status']} {result.get('error', '')}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("lock-method", "acquire"))
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--provider", choices=("noaa", "hycom", "both"), default="both")
    parser.add_argument("--hycom-access", choices=("ncss", "dap"), default="ncss")
    parser.add_argument("--block", action="append")
    parser.add_argument("--retry-transport", action="store_true")
    args = parser.parse_args()
    out = batch_directory(args.out)
    if args.command == "lock-method":
        registry = freeze_method(out)
        print(f"Frozen {len(registry['blocks'])} registered dates and C0/Lazy method identities", flush=True)
        return
    registry = verify_method(out)
    if (out / "date_lock.json").exists():
        raise ValueError("Date selection is already frozen")
    blocks = {row["id"]: row for row in registry["blocks"]}
    identities = args.block or [identity for identity, row in blocks.items() if row["primary"]]
    snapshots = sorted((out / "qualification").glob("*.json"))
    waiting = []
    blocked_captures = {}
    if snapshots:
        latest = read(snapshots[-1])
        if latest["method_lock_sha256"] != digest(method_lock(out)):
            raise ValueError("Date audit does not match the frozen registration")
        _, _, waiting, _ = choose_dates(registry["blocks"], latest["dates"])
        blocked_captures = {name: sha for row in latest["dates"] if row["status"] == "blocked"
                            for name, sha in row["captures"].items()}
    for identity in identities:
        if identity not in blocks or (not blocks[identity]["primary"] and identity not in waiting):
            raise ValueError(f"Date is unregistered or its fallback has not opened: {identity}")
    for identity in identities:
        block = blocks[identity]
        if args.provider in ("noaa", "both"):
            acquire_block(out, block, "noaa", args.retry_transport, args.hycom_access, blocked_captures)
        if args.provider in ("hycom", "both") and block["scene"] == "arctic_ocean":
            acquire_block(out, block, "hycom", args.retry_transport, args.hycom_access, blocked_captures)


if __name__ == "__main__":
    main()
