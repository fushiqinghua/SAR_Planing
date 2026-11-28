#!/usr/bin/env python3
"""H2 method lock, official forcing acquisition/qualification, and particle preparation."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import traceback

from h2_protocol import (
    ROOT, DEFAULT_CONFIG, DEFAULT_OUT, registered_blocks, instances_for, choose_blocks,
    freeze_method, verify_method, verify_dates, verify_inputs, read, save, digest,
)
from h2_acquire import AcquisitionError, acquire_noaa
from h2_hycom import acquire_hycom, requests_for
from asar_repro.h2_forcing import DataIneligible, expected_clock, load_h2_forcing
from asar_repro.h2_inputs import FILES, load_h2_input, prepare_h2_input

RAW = ROOT / "data/raw/h2"


def _stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _source_directory(out, block):
    return out / "sources" / block["id"]


def _failure(error):
    return dict(status="ineligible" if isinstance(error, AcquisitionError) and error.reason == "source_missing"
                else "blocked", reason=str(error), error_type=type(error).__name__,
                receipt_reason=getattr(error, "reason", None), traceback=traceback.format_exc())


def acquire_block(out, config, block, source):
    directory = _source_directory(out, block)
    if source in ("noaa", "both") and not any(
        (directory / name).exists() for name in ("noaa.json", "noaa_failure.json")
    ):
        try:
            response = acquire_noaa(ROOT, RAW, block, config["total_attempts_per_request"])
            save(directory / "noaa.json", response)
        except Exception as exc:
            save(directory / "noaa_failure.json", _failure(exc))
            print(f"{block['id']} NOAA acquisition unavailable: {exc}", flush=True)
    if (source in ("hycom", "both") and block["scene"] == "arctic_ocean"
            and not any((directory / name).exists() for name in ("hycom.json", "hycom_failure.json"))):
        try:
            response = acquire_hycom(ROOT, RAW / block["id"], block, config["total_attempts_per_request"])
            save(directory / "hycom.json", dict(current=response))
        except Exception as exc:
            save(directory / "hycom_failure.json", _failure(exc))
            print(f"{block['id']} HYCOM acquisition unavailable: {exc}", flush=True)


def _request_plan(block):
    valid_wind, valid_current, cycles, leads = expected_clock(block)
    plan = dict(
        wind=[dict(valid_utc=v.isoformat(), cycle_utc=c.isoformat(), lead_hours=h)
              for v, c, h in zip(valid_wind, cycles, leads, strict=True)],
        current_valid_times_utc=[stamp.isoformat() for stamp in valid_current],
    )
    if block["scene"] == "arctic_ocean":
        plan["hycom_requests"] = requests_for(block)
    return plan


def _receipt_inventory(block):
    raw = RAW / block["id"]
    if not raw.exists():
        return {}
    return {path.relative_to(ROOT).as_posix(): digest(path) for path in sorted(raw.rglob("*"))
            if path.is_file() and path.suffix in (".json", ".jsonl", ".xml", ".idx")}


def audit_block(out, block):
    directory = _source_directory(out, block)
    scope = dict(block_id=block["id"], scene=block["scene"], date=block["date"],
                 primary=block["primary"], registered_seeds=block["seeds"],
                 request_plan=_request_plan(block), raw_receipts_sha256=_receipt_inventory(block))
    required = ["noaa"] + (["hycom"] if block["scene"] == "arctic_ocean" else [])
    failed = [directory / f"{name}_failure.json" for name in required
              if (directory / f"{name}_failure.json").exists()]
    if failed:
        failures = [read(path) for path in failed]
        return dict(scope, status="ineligible" if any(f.get("status") == "ineligible" or f.get("reason") == "source_missing"
                         or f.get("receipt_reason") == "source_missing" for f in failures) else "blocked",
                    failures=failures, acquisition_failure_files=[path.relative_to(out).as_posix() for path in failed])
    paths = [directory / f"{name}.json" for name in required]
    if not all(path.exists() for path in paths):
        return dict(scope, status="not_run",
                    pending=[path.name for path in paths if not path.exists()])
    manifest = read(paths[0])
    if len(paths) == 2:
        if manifest["current"]:
            raise ValueError("Hudson currents must come from the registered HYCOM endpoint")
        manifest["current"] = read(paths[1])["current"]
    acquired = {path.relative_to(out).as_posix(): digest(path) for path in paths}
    qualified = directory / "qualification" / _stamp()
    manifest_path = qualified / "source_manifest.json"
    save(manifest_path, manifest)
    identity = dict(scope, source_manifest=manifest_path.relative_to(out).as_posix(),
                    source_manifest_sha256=digest(manifest_path), acquisition_files=acquired)
    try:
        _, check = load_h2_forcing(ROOT, block, manifest)
        result = dict(identity, status="eligible", checks=check)
    except DataIneligible as exc:
        result = dict(identity, status="ineligible", reason=str(exc), details=getattr(exc, "evidence", None))
    except Exception as exc:
        result = dict(identity, status="blocked", reason=str(exc), traceback=traceback.format_exc())
    save(qualified / "result.json", result)
    print(f"{block['id']}: {result['status']}" +
          (f" ({result['reason']})" if "reason" in result else ""), flush=True)
    return result


def audit_dates(config_path, out):
    if (out / "date_lock.json").exists():
        return verify_dates(config_path, out)
    method = verify_method(config_path, out)
    config = method["config"]
    records = [audit_block(out, block) for block in method["date_blocks"]
               if block["primary"] or _source_directory(out, block).exists()]
    blocks, replacements, waiting = choose_blocks(config, records)
    for entry in records:
        entry.update(selected=any(b["id"] == entry["block_id"] for b in blocks),
                     replaces=replacements.get(entry["block_id"]))
    readiness = "six_dates_qualified" if len(blocks) == 6 and not waiting else "data_incomplete"
    path = out / "availability_audit.json"
    result = dict(status=readiness, dates=records, waiting=waiting, selected_blocks=blocks,
                  replacements=replacements, data_depends_only_on_forcing=True,
                  observed_planning_scores=0, method_lock_sha256=digest(out / "method_lock.json"))
    save(out / "availability_snapshots" / f"{_stamp()}.json", result)
    save(path, result, replace=True)
    print(f"{readiness}: {len(blocks)}/6 eligible blocks; next prerequisites: {waiting}", flush=True)
    if readiness == "six_dates_qualified":
        save(out / "date_lock.json", dict(status=readiness, blocks=blocks, replacements=replacements,
             method_lock_sha256=result["method_lock_sha256"], audit_sha256=digest(path)))
    return result


def prepare_archives(config_path, out):
    if (out / "inputs_lock.json").exists():
        return verify_inputs(config_path, out)
    dates = verify_dates(config_path, out)
    audit = read(out / "availability_audit.json")
    by_id = {row["block_id"]: row for row in audit["dates"]}
    for block in dates["blocks"]:
        entry = by_id[block["id"]]
        path = out / entry["source_manifest"]
        if digest(path) != entry["source_manifest_sha256"]:
            raise ValueError(f"Qualified source manifest changed for {block['id']}")
        bundle, validation = load_h2_forcing(ROOT, block, read(path))
        if validation != entry["checks"]:
            raise ValueError(f"Native forcing qualification changed for {block['id']}")
        evidence = dict(block_id=block["id"], source_manifest_sha256=digest(path),
                        method_lock_sha256=digest(out / "method_lock.json"),
                        date_lock_sha256=digest(out / "date_lock.json"))
        for case in instances_for([block]):
            destination = out / "inputs" / case["id"]
            prepare_h2_input(case, destination, bundle, validation, evidence)
            load_h2_input(ROOT, case, destination, "heading_square")
            load_h2_input(ROOT, case, destination, "axis_square")
            print(f"{case['id']}: stable IDs, UTC axes and particle mass verified", flush=True)
    cases = instances_for(dates["blocks"])
    archive_files = {f"inputs/{case['id']}/{name}": digest(out / "inputs" / case["id"] / name)
                     for case in cases for name in (*FILES, "manifest.json")}
    result = dict(status="twelve_archives_verified", instances=cases, archive_files=archive_files,
                  date_lock_sha256=digest(out / "date_lock.json"), opendrift_runs=12)
    save(out / "inputs_lock.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "lock-method", "acquire", "audit", "prepare"))
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--block", action="append", help="Registered primary or currently due backup ID")
    parser.add_argument("--source", choices=("noaa", "hycom", "both"), default="both")
    args = parser.parse_args()
    out, config_path = args.out.resolve(), args.config.resolve()
    if args.command == "lock-method":
        lock = freeze_method(config_path, out)
        print(f"{lock['status']}: {digest(out / 'method_lock.json')}", flush=True)
    elif args.command == "plan":
        import json
        print(json.dumps(registered_blocks(read(config_path)), ensure_ascii=False, indent=2))
    elif args.command == "audit":
        audit_dates(config_path, out)
    elif args.command == "prepare":
        prepare_archives(config_path, out)
    else:
        lock = verify_method(config_path, out)
        if (out / "date_lock.json").exists():
            raise ValueError("Dates are frozen. Acquisition cannot change bound source evidence.")
        registered = {block["id"]: block for block in lock["date_blocks"]}
        requested = args.block or [block["id"] for block in lock["date_blocks"] if block["primary"]]
        audit_path = out / "availability_audit.json"
        waiting = read(audit_path)["waiting"] if audit_path.exists() else []
        for identity in requested:
            if identity not in registered:
                raise ValueError(f"Unknown registered source block: {identity}")
            block = registered[identity]
            if not block["primary"] and identity not in waiting:
                raise ValueError("A backup is allowed only when the registered eligibility sequence requests it")
            acquire_block(out, lock["config"], block, args.source)


if __name__ == "__main__":
    main()
