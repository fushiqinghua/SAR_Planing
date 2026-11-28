#!/usr/bin/env python3
"""Qualify H3 dates and freeze one independently verified archive per registered seed."""
from __future__ import annotations

import argparse
from pathlib import Path
import traceback

from h3_acquire import attempt_files
from h3_protocol import (
    DEFAULT_OUT, ROOT, batch_directory, choose_dates, digest, instances_for,
    method_lock, read, save, stamp, verify_method,
)
from asar_repro.h3_forcing import DataIneligible, load_h3_forcing, verify_file
from asar_repro.h2_inputs import FILES, load_h2_input, prepare_h2_input


def _capture(out, block, provider):
    attempts = attempt_files(out, block, provider)
    if not attempts:
        return None, {}
    inventory = {}
    for path in attempts:
        result = read(path)
        expected = dict(block_id=block["id"], scene=block["scene"], date=block["date"],
                        provider=provider, attempt=path.stem, method_lock_sha256=digest(method_lock(out)))
        if any(result[key] != value for key, value in expected.items()):
            raise ValueError(f"Wrong H3 capture identity: {path}")
        claim = path.parent / "claims" / path.name
        if any(result[key] != value for key, value in read(claim).items()):
            raise ValueError(f"H3 capture and claim differ: {path}")
        for name, sha in result["receipt_sha256"].items():
            verify_file(ROOT, block, name, sha)
        inventory.update({file.relative_to(out).as_posix(): digest(file) for file in (claim, path)})
    return result, inventory


def _audit_block(out, block, snapshot):
    result = dict(block_id=block["id"], scene=block["scene"], date=block["date"],
                  primary=block["primary"], seeds=block["seeds"], captures={})
    try:
        acquired = {}
        for provider in ("noaa", "hycom") if block["scene"] == "arctic_ocean" else ("noaa",):
            capture, inventory = _capture(out, block, provider)
            result["captures"].update(inventory)
            if capture is not None:
                acquired[provider] = capture
        result["providers"] = {name: record["status"] for name, record in acquired.items()}
        confirmed = [record for record in acquired.values() if record["status"] == "ineligible"]
        if confirmed:
            return dict(result, status="ineligible", reason=confirmed[0]["reason"],
                        details=confirmed[0]["error"])
        pending = 2 if block["scene"] == "arctic_ocean" else 1
        blocked = [record for record in acquired.values() if record["status"] == "blocked"]
        if blocked:
            return dict(result, status="blocked", reason=blocked[0]["reason"], details=blocked[0]["error"])
        if len(acquired) != pending:
            return dict(result, status="pending", reason="acquisition_not_complete")
        if any(record["status"] != "retrieved" for record in acquired.values()):
            raise ValueError("H3 source capture has an unknown status")
        noaa = acquired["noaa"]
        if "hycom" in acquired and (noaa["current"] or acquired["hycom"]["wind"]):
            raise ValueError("Hudson must use GFS wind and HYCOM currents")
        manifest = dict(
            block_id=block["id"], scene=block["scene"], date=block["date"], wind=noaa["wind"],
            current=acquired["hycom"]["current"] if "hycom" in acquired else noaa["current"],
        )
        path = out / "source_manifests" / snapshot / (block["id"] + ".json")
        save(path, manifest)
        result.update(manifest=path.relative_to(out).as_posix(), manifest_sha256=digest(path))
        _, checks = load_h3_forcing(ROOT, block, manifest)
        return dict(result, status="eligible", checks=checks)
    except DataIneligible as exc:
        return dict(result, status="ineligible", reason=str(exc), details=getattr(exc, "evidence", None))
    except Exception as exc:
        return dict(result, status="blocked", reason=str(exc), traceback=traceback.format_exc())


def qualify(out):
    if (out / "date_lock.json").exists():
        return verify_dates(out, full=True)[1]
    registry = verify_method(out)
    blocks = registry["blocks"]
    snapshot = stamp()
    records = []
    for block in blocks:
        if not block["primary"] and not (out / "sources" / block["id"]).exists():
            continue
        row = _audit_block(out, block, snapshot)
        records.append(row)
        print(f"{row['block_id']} {row['date']}: {row['status']} {row.get('reason', '')}", flush=True)
    chosen, replacements, waiting, exhausted = choose_dates(blocks, records)
    if len(chosen) == 6 and not waiting and not exhausted:
        status = "six_dates_qualified"
    elif exhausted:
        status = "data_incomplete"
    else:
        status = "pending_qualification"
    audit = dict(status=status, dates=records, selected=chosen, replacements=replacements,
                 waiting=waiting, exhausted=exhausted, selection_inputs="official source qualification only",
                 method_lock_sha256=digest(method_lock(out)), route_scores_used=0)
    overlap = out / "commands/07_hycom_transport_equivalence.json"
    if overlap.is_file():
        _verify_overlap(read(overlap))
        audit["same_hour_hycom_cross_access"] = dict(
            path=overlap.relative_to(out).as_posix(), sha256=digest(overlap),
        )
    path = out / "qualification" / (snapshot + ".json")
    save(path, audit)
    if status == "six_dates_qualified":
        save(out / "date_lock.json", dict(
            status=status, selected=chosen, replacements=replacements,
            audit=path.relative_to(out).as_posix(), audit_sha256=digest(path),
            method_lock_sha256=digest(method_lock(out)),
        ))
    print(f"{status}: {len(chosen)}/6; waiting={waiting}; exhausted={exhausted}", flush=True)
    return audit


def checked_file(out, name, sha):
    relative = Path(name)
    path = (out / relative).resolve()
    if (relative.is_absolute() or ".." in relative.parts or not path.is_relative_to(out.resolve())
            or digest(path) != sha):
        raise ValueError(f"Missing, escaped or modified H3 evidence: {name}")
    return path


def _verify_overlap(record):
    if (record["status"] != "equivalent" or record["compared_spatial_samples"] != 2835
            or record["axes"] != dict(lon=True, lat=True, time=True)
            or set(record["variables"]) != {"ssu", "ssv", "sic"}
            or any(row != dict(raw_packed_identical=True, cf_unpacked_identical=True)
                   for row in record["variables"].values())):
        raise ValueError("Official HYCOM cross-access evidence does not reproduce the same native values")
    for name, sha in record["files"].items():
        checked_file(ROOT, name, sha)


def verify_dates(out, *, full=False):
    registry = verify_method(out)
    lock = read(out / "date_lock.json")
    audit_path = checked_file(out, lock["audit"], lock["audit_sha256"])
    audit = read(audit_path)
    method_sha = digest(method_lock(out))
    chosen, replacements, waiting, exhausted = choose_dates(registry["blocks"], audit["dates"])
    if (lock["status"] != "six_dates_qualified" or audit["status"] != lock["status"]
            or lock["method_lock_sha256"] != method_sha or audit["method_lock_sha256"] != method_sha
            or waiting or exhausted or len(chosen) != 6 or audit["route_scores_used"] != 0
            or lock["selected"] != chosen or audit["selected"] != chosen
            or lock["replacements"] != replacements or audit["replacements"] != replacements):
        raise ValueError("H3 frozen selection differs from the registered data-only qualification")
    if full:
        cross_access = audit.get("same_hour_hycom_cross_access")
        if cross_access:
            _verify_overlap(read(checked_file(out, cross_access["path"], cross_access["sha256"])))
        dates = {row["id"]: row for row in registry["blocks"]}
        for row in audit["dates"]:
            captures = {}
            block = dates[row["block_id"]]
            for provider in row["providers"]:
                _, inventory = _capture(out, block, provider)
                captures.update(inventory)
            if row["captures"] != captures:
                raise ValueError(f"Frozen acquisition receipts changed for {block['id']}")
            if "manifest" in row:
                manifest = read(checked_file(out, row["manifest"], row["manifest_sha256"]))
                if row["status"] == "eligible":
                    _, checks = load_h3_forcing(ROOT, block, manifest)
                    if checks != row["checks"]:
                        raise ValueError(f"Native H3 qualification changed for {block['id']}")
                else:
                    for source in manifest["wind"] + manifest["current"]:
                        verify_file(ROOT, block, source["local_path"], source["sha256"], source["bytes"])
    return lock, audit


def case_evidence(out, case, row):
    if case["block_id"] != row["block_id"]:
        raise ValueError("H3 seed and qualified source date are different")
    return dict(study="second_innovation_h3_new_forcing", source_manifest_sha256=row["manifest_sha256"],
                method_lock_sha256=digest(method_lock(out)), date_lock_sha256=digest(out / "date_lock.json"))


def load_h3_input(out, case, expected, footprint):
    destination = out / "inputs" / case["id"]
    manifest = read(destination / "manifest.json")
    if manifest["evidence"] != expected:
        raise ValueError("Particle archive is outside the frozen H3 source/method/seed chain")
    problem, grid, discrete, info = load_h2_input(ROOT, case, destination, footprint)
    return problem, grid, discrete, dict(info, input_role="p2_h3_preregistered_new_date",
                                         h3_evidence=expected)


def prepare_inputs(out):
    if (out / "inputs_lock.json").exists():
        return verify_inputs(out, full=True)
    dates, audit = verify_dates(out)
    by_date = {row["block_id"]: row for row in audit["dates"]}
    all_cases, files = {}, {}
    for block in dates["selected"]:
        row = by_date[block["id"]]
        manifest = read(checked_file(out, row["manifest"], row["manifest_sha256"]))
        bundle, checks = load_h3_forcing(ROOT, block, manifest)
        if checks != row["checks"]:
            raise ValueError(f"Native H3 qualification changed for {block['id']}")
        for case in instances_for([block]):
            expected = case_evidence(out, case, row)
            destination = out / "inputs" / case["id"]
            prepare_h2_input(case, destination, bundle, checks, expected)
            for footprint in ("heading_square", "axis_square"):
                _, _, _, info = load_h3_input(out, case, expected, footprint)
            all_cases[case["id"]] = dict(case=case, h3_evidence=expected,
                                         input_sha256=info["particle_sha256"],
                                         manifest_sha256=info["manifest_sha256"])
            for name in (*FILES, "manifest.json"):
                path = destination / name
                files[path.relative_to(out).as_posix()] = digest(path)
            print(f"{case['id']}: verified UTC, particle IDs, mass and input SHA-256", flush=True)
    result = dict(status="twelve_historical_archives_verified", cases=all_cases, files=files,
                  date_lock_sha256=digest(out / "date_lock.json"), opendrift_preprocessing_runs=len(all_cases))
    save(out / "inputs_lock.json", result)
    return verify_inputs(out)


def verify_inputs(out, *, full=False):
    dates, audit = verify_dates(out, full=full)
    lock = read(out / "inputs_lock.json")
    cases = {row["id"]: row for row in instances_for(dates["selected"])}
    files = {f"inputs/{identity}/{name}" for identity in cases for name in (*FILES, "manifest.json")}
    by_date = {row["block_id"]: row for row in audit["dates"]}
    if (lock["status"] != "twelve_historical_archives_verified" or len(cases) != 12
            or lock["opendrift_preprocessing_runs"] != 12 or set(lock["files"]) != files
            or set(lock["cases"]) != set(cases)
            or lock["date_lock_sha256"] != digest(out / "date_lock.json")):
        raise ValueError("The H3 archive chain does not describe the twelve frozen inputs")
    for name, sha in lock["files"].items():
        checked_file(out, name, sha)
    for identity, case in cases.items():
        record = lock["cases"][identity]
        evidence = case_evidence(out, case, by_date[case["block_id"]])
        if record != dict(case=case, h3_evidence=evidence,
                          input_sha256=lock["files"][f"inputs/{identity}/particles.npz"],
                          manifest_sha256=lock["files"][f"inputs/{identity}/manifest.json"]):
            raise ValueError(f"H3 case, input or forcing fingerprint mismatch: {identity}")
        if full:
            load_h3_input(out, case, evidence, "heading_square")
    return lock


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("qualify", "prepare", "verify-inputs"))
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    out = batch_directory(args.out)
    if args.command == "qualify":
        qualify(out)
    elif args.command == "prepare":
        prepare_inputs(out)
    else:
        lock = verify_inputs(out, full=True)
        print(f"{lock['status']}: {digest(out / 'inputs_lock.json')}", flush=True)


if __name__ == "__main__":
    main()
