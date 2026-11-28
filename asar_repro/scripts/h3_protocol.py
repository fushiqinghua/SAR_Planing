"""Immutable registration and date-selection policy for P2/H3."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import file_digest
import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / "outputs/second_innovation_h3_20261128"
DEFAULT_OUT = BATCH / "local_r1"
RAW = ROOT / "data/raw/h3"
PREREG_COMMIT = "be09ec35919a009aa0535136d76c31ddd7a67c9e"
P1_COMMIT = "26276433832c43f83dad158e7f7bcf38ce0851d0"
REGISTRY = "docs/second_innovation_next/h3_date_registry.json"
PREREGISTRATION = "docs/second_innovation_next/P2_H3_PREREGISTRATION.md"
DECISIONS = "docs/second_innovation_next/P1_DECISIONS.md"
H2_CONFIG = "configs/eight_neighbor_h2.json"
H2_DATES = "outputs/eight_neighbor_h2_20261127/local_r2/date_lock.json"
P1_SUMMARY = "outputs/second_innovation_p1_20261128/local_r1/summary.json"
PROVIDER_ATTEMPTS = 3


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, value):
    data = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(data + "\n")


def digest(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def batch_directory(path):
    path = path.resolve()
    if path.parent != BATCH.resolve() or re.fullmatch(r"local_r[1-9]\d*", path.name) is None:
        raise ValueError(f"Use a P2/H3 results directory under {BATCH}")
    return path


def verify_commit_file(relative, commit):
    """Compare actual working bytes, including line endings, to the Git object."""
    path = ROOT / relative
    frozen = subprocess.check_output(
        ["git", "show", f"{commit}:asar_repro/{relative}"], cwd=ROOT.parent
    )
    if path.read_bytes() != frozen:
        raise ValueError(f"Frozen file changed: {relative}")
    return digest(path)


def registered_method():
    registry = read(ROOT / REGISTRY)
    registered = {path: verify_commit_file(path, PREREG_COMMIT)
                  for path in (REGISTRY, PREREGISTRATION, DECISIONS, H2_CONFIG, H2_DATES)}
    registered[P1_SUMMARY] = verify_commit_file(P1_SUMMARY, P1_COMMIT)
    prior = read(ROOT / P1_SUMMARY)
    h2 = read(ROOT / H2_DATES)
    if (prior["status"] != "timing_screen_passed" or prior["valid_runs"] != 48
            or [row["date"] for row in h2["blocks"]] != registry["history"]["h2_selected"]
            or h2["replacements"] != {}):
        raise ValueError("The frozen P1 screen and six original H2 dates are required")
    protected = {}
    for relative, expected in registry["protected_github_blobs"].items():
        actual = subprocess.check_output(
            ["git", "hash-object", "--no-filters", "--", relative], cwd=ROOT
        ).decode("ascii").strip()
        if actual != expected:
            raise ValueError(f"Protected C0/Lazy or physical-model blob changed: {relative}")
        protected[relative] = digest(ROOT / relative)
    return dict(registry=registry, registered_sha256=registered, method_sha256=protected)


def method_lock(out):
    return out / "method_lock.json"


def verify_method(out):
    lock = read(method_lock(out))
    if (lock["status"] != "frozen_before_qualification"
            or lock["identity"] != registered_method()):
        raise ValueError("H3 registration or method lock changed")
    return lock["identity"]["registry"]


def freeze_method(out):
    if method_lock(out).exists():
        return verify_method(out)
    if any((out / name).exists() for name in ("sources", "qualification", "inputs", "runs")):
        raise ValueError("Freeze the registration before H3 qualification or experiments")
    identity = registered_method()
    save(method_lock(out), dict(status="frozen_before_qualification", identity=identity,
                               frozen_utc=datetime.now(timezone.utc).isoformat()))
    return identity["registry"]


def choose_dates(blocks, audits):
    """Only a documented qualification failure can open the next regional fallback."""
    by_id = {row["block_id"]: row["status"] for row in audits}
    registered = {row["id"] for row in blocks}
    if (len(by_id) != len(audits) or by_id.keys() - registered
            or set(by_id.values()) - {"pending", "blocked", "eligible", "ineligible"}):
        raise ValueError("Unexpected H3 qualification identity or status")
    replacements, selected, waiting, exhausted = {}, {}, [], []
    for region in dict.fromkeys(row["scene"] for row in blocks):
        primary = [row for row in blocks if row["scene"] == region and row["primary"]]
        fallback = [row for row in blocks if row["scene"] == region and not row["primary"]]
        vacancies, unresolved = [], []
        for row in primary:
            identity = row["id"]
            state = by_id.get(identity, "pending")
            if state == "eligible":
                selected[identity] = row
            elif state == "ineligible":
                vacancies.append(identity)
            else:
                unresolved.append(identity)
        if unresolved:
            waiting.extend(unresolved)
            continue
        for row in fallback:
            if not vacancies:
                break
            identity = row["id"]
            state = by_id.get(identity, "pending")
            if state == "eligible":
                vacancy = vacancies.pop(0)
                selected[vacancy] = row
                replacements[identity] = vacancy
            elif state != "ineligible":
                waiting.append(identity)
                break
        else:
            exhausted.extend(vacancies)
    ordered = [selected[row["id"]] for row in blocks if row["id"] in selected]
    return ordered, replacements, waiting, exhausted


def instances_for(blocks):
    return [
        dict(id=f"{block['id']}_s{seed}", block_id=block["id"], base_scene=block["scene"],
             lkp_utc=block["lkp_utc"], cst_utc=block["cst_utc"],
             end_utc=block["end_utc"], seed=seed)
        for block in blocks for seed in block["seeds"]
    ]
