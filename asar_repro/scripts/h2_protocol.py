"""Frozen research identity, H2 date policy, and input evidence chain."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import json
from pathlib import Path
import subprocess

import run_eight_neighbor_confirmation as confirmation

ROOT = confirmation.ROOT
DEFAULT_CONFIG = ROOT / "configs/eight_neighbor_h2.json"
DEFAULT_OUT = ROOT / "outputs/eight_neighbor_h2_20261127/local_r1"
BASE = "972082c62868a00f4e6f43e42ceb46df42ab49ed"
read, save, digest = confirmation.read, confirmation.save, confirmation.digest
object_digest = confirmation.object_digest


def utc_label(value):
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def registered_blocks(config):
    result = []
    for scene, dataset in config["datasets"].items():
        for kind in ("primary", "alternates"):
            for identity, calendar_date, *seeds in dataset[kind]:
                day = datetime.combine(date.fromisoformat(calendar_date), time(), timezone.utc)
                if scene == "lake_ontario":
                    lkp = day + timedelta(hours=14, minutes=45)
                    cst = day + timedelta(hours=15, minutes=45)
                    end = cst + timedelta(seconds=453.74)
                elif scene == "arctic_ocean":
                    lkp, cst = day, day + timedelta(days=1)
                    end = cst + timedelta(seconds=2778)
                else:
                    raise ValueError(f"Unknown registered scene {scene}")
                result.append(dict(id=identity, scene=scene, date=calendar_date, seeds=seeds,
                                   primary=kind == "primary", lkp_utc=utc_label(lkp),
                                   cst_utc=utc_label(cst), end_utc=utc_label(end)))
    return result


def instances_for(blocks):
    return [dict(id=f"{block['id']}_s{seed}", block_id=block["id"],
                 base_scene=block["scene"], lkp_utc=block["lkp_utc"],
                 cst_utc=block["cst_utc"], end_utc=block["end_utc"], seed=seed)
            for block in blocks for seed in block["seeds"]]


def _base_evidence(relative):
    current = ROOT / relative
    recorded = subprocess.check_output(
        ["git", "show", f"{BASE}:asar_repro/{relative}"], cwd=ROOT.parent)
    if current.read_bytes() != recorded:
        raise ValueError(f"Base evidence bytes changed: {relative}")
    return digest(current)


def _method_identity(config_path):
    config = read(config_path)
    confirmation.common.set_threads(config)
    if config["base_commit"] != BASE or config["method"] != "completion_J":
        raise ValueError("The registered H2 uses the fixed completion_J confirmation method")
    evidence = {
        path: _base_evidence(path)
        for path in (config["preregistration"], config["confirmation_summary"],
                     "outputs/eight_neighbor_confirmation_20261127/local_r1/protocol.json",
                     "configs/eight_neighbor_confirmation.json", "configs/stage7_scenarios.yaml")
    }
    summary = read(ROOT / config["confirmation_summary"])
    decision = summary["method_decision"]
    if (summary["status"] != "complete" or not summary["H2_method_freeze_ready"]
            or decision["status"] != "completion_development_screen_passed"
            or decision["selected_method_for_H2"] != config["method"]):
        raise ValueError("Existing confirmation evidence does not select completion_J")
    previous = read(confirmation.DEFAULT_CONFIG)
    expected_options = dict(previous["search"], **previous["refinement"],
                            **previous["methods"]["completion_J"])
    if config["solver"] != expected_options:
        raise ValueError("H2 solver differs from the validated completion_J options")
    if (config["watchdog"] != previous["watchdog"]
            or config["thread_environment"] != previous["thread_environment"]):
        raise ValueError("H2 execution constraints differ from confirmation")
    env = confirmation.environment()
    return dict(config=config, config_sha256=digest(config_path), base_commit=BASE,
                confirmation_decision=decision["status"], evidence_sha256=evidence,
                protected_sources=confirmation.previous.protect_base(config),
                environment=env, date_blocks=registered_blocks(config),
                optimality_certificate=False)


def freeze_method(config_path, out):
    out.mkdir(parents=True, exist_ok=True)
    destination = out / "method_lock.json"
    if destination.exists():
        return verify_method(config_path, out)
    if any((out / name).exists() for name in ("availability_audit.json", "inputs", "runs")):
        raise ValueError("The method must be frozen before H2 qualification, drift or scoring")
    identity = _method_identity(config_path)
    dependencies = confirmation.followup.generation_dependencies(identity["environment"], check_imports=True)
    if dependencies["status"] != "ready":
        raise ValueError(f"Existing maritime-sar environment did not pass imports: {dependencies}")
    lock = dict(status="method_locked_before_date_qualification",
                locked_at=utc_label(datetime.now(timezone.utc)), dependencies=dependencies, **identity)
    save(destination, lock)
    return lock


def verify_method(config_path, out):
    lock = read(out / "method_lock.json")
    expected = _method_identity(config_path)
    if (lock["status"] != "method_locked_before_date_qualification"
            or any(lock.get(key) != value for key, value in expected.items())):
        raise ValueError("Frozen method, scorer, source or environment changed")
    return lock


def choose_blocks(config, audits):
    """Select strictly in registration order and only from qualified source data."""
    blocks = registered_blocks(config)
    by_id = {row["block_id"]: row for row in audits}
    if len(by_id) != len(audits):
        raise ValueError("Duplicate date audits")
    if set(by_id) - {block["id"] for block in blocks}:
        raise ValueError("Unregistered date audits")
    chosen, replacements, waiting = [], {}, []
    for scene in config["datasets"]:
        primary = [row for row in blocks if row["scene"] == scene and row["primary"]]
        alternate = [row for row in blocks if row["scene"] == scene and not row["primary"]]
        vacant = []
        for block in primary:
            state = by_id.get(block["id"], {}).get("status", "not_run")
            if state == "eligible":
                chosen.append(block)
            elif state == "ineligible":
                vacant.append(block["id"])
            elif state in ("blocked", "not_run"):
                waiting.append(block["id"])
            else:
                raise ValueError(f"Invalid qualification status for {block['id']}: {state}")
        if any(block["id"] in waiting for block in primary):
            continue
        for block in alternate:
            if not vacant:
                break
            state = by_id.get(block["id"], {}).get("status", "not_run")
            if state == "eligible":
                chosen.append(block)
                replacements[block["id"]] = vacant.pop(0)
            elif state in ("blocked", "not_run"):
                waiting.append(block["id"])
                break
            elif state != "ineligible":
                raise ValueError(f"Invalid qualification status for {block['id']}: {state}")
    return chosen, replacements, waiting


def verify_dates(config_path, out):
    lock = verify_method(config_path, out)
    path = out / "date_lock.json"
    result = read(path)
    audit = out / "availability_audit.json"
    if (result["status"] != "six_dates_qualified"
            or result["method_lock_sha256"] != digest(out / "method_lock.json")
            or result["audit_sha256"] != digest(audit)):
        raise ValueError("Method or data qualification evidence changed")
    value = read(audit)
    blocks, replacements, waiting = choose_blocks(lock["config"], value["dates"])
    if len(blocks) != 6 or waiting or blocks != result["blocks"] or replacements != result["replacements"]:
        raise ValueError("Frozen six-date selection no longer matches registered eligibility")
    chosen = {block["id"] for block in blocks}
    for entry in value["dates"]:
        if entry["block_id"] not in chosen:
            continue
        prefixed = Path(entry["source_manifest"])
        if (prefixed.is_absolute() or ".." in prefixed.parts
                or digest(out / prefixed) != entry["source_manifest_sha256"]):
            raise ValueError(f"Qualified native source manifest changed for {entry['block_id']}")
    return result


def verify_inputs(config_path, out):
    dates = verify_dates(config_path, out)
    path = out / "inputs_lock.json"
    result = read(path)
    if (result["status"] != "twelve_archives_verified"
            or result["date_lock_sha256"] != digest(out / "date_lock.json")
            or result["instances"] != instances_for(dates["blocks"])):
        raise ValueError("Frozen H2 archive identity changed")
    from asar_repro.h2_inputs import FILES

    expected_files = {f"inputs/{case['id']}/{name}" for case in result["instances"]
                      for name in (*FILES, "manifest.json")}
    if set(result["archive_files"]) != expected_files or result["opendrift_runs"] != 12:
        raise ValueError("The frozen H2 archive inventory is incomplete")
    for name, expected in result["archive_files"].items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or digest(out / relative) != expected:
            raise ValueError(f"Frozen H2 archive evidence changed: {name}")
    return result
