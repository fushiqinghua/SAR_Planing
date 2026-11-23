"""Separate archived source identity from the explicitly approved research delta.

The B4/B6 recorded hashes remain unchanged. Never resolve a moving branch name
as the archived source, and never accept an arbitrary current heuristic file.
"""
import hashlib
from pathlib import Path, PurePosixPath
import subprocess

ROOT = Path(__file__).resolve().parents[1]
FROZEN_COMMIT = "81b9be9b51625ed9012a69f9cb90e296bf2ec5c2"
APPROVED_RESEARCH = {
    "src/asar_repro/heuristic.py":
        "43f94d7ec3ae69dc67ee4416892ea65aa445498a002905f77d4b1f533b168c0b",
    # User-authorized STDC repair: opt-in exact-state dominance / bounded h cache.
    # Historical B4/B6 source identity is still checked against FROZEN_COMMIT.
    "src/asar_repro/search.py":
        "868b09203c3a782765f9b4440751d56512e5a24c1a0a44d5706e6a6aa5b34bbc",
}


def frozen_bytes(source):
    name = PurePosixPath(str(source).replace("\\", "/"))
    if name.is_absolute() or ".." in name.parts or ":" in str(name):
        raise ValueError("source must be a relative repository path")
    return subprocess.check_output(
        ["git", "-c", f"safe.directory={ROOT.parent.as_posix()}", "show",
         f"{FROZEN_COMMIT}:asar_repro/{name}"], cwd=ROOT)


def assert_archived_source(source, expected, *, current_root=ROOT):
    name = str(source).replace("\\", "/")
    historical = hashlib.sha256(frozen_bytes(name)).hexdigest()
    assert historical == expected, f"frozen source fingerprint mismatch: {name}"
    current = hashlib.sha256((current_root / name).read_bytes()).hexdigest()
    approved = APPROVED_RESEARCH.get(name, expected)
    assert current == approved, f"unapproved research source change: {name}"
    return {"source": name, "historical_sha256": historical,
            "current_sha256": current, "approved_delta": name in APPROVED_RESEARCH}
