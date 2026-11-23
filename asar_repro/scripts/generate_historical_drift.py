"""Generate, freeze and independently replay the B3 Lake Ontario particle archive."""

import argparse
import csv
import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

import numpy as np
import yaml

import asar_repro
from asar_repro.forcing import load_historical_forcing
from asar_repro.gridding import particle_step
from asar_repro.historical_drift import (
    axes,
    build_archive,
    compare_replay,
    identity,
    run_historical,
    utc_label,
)
from asar_repro.scenarios import config_digest, digest, drift_config

from plot_historical_drift import plot_drift, plot_time_coverage

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "outputs/baseline_v1.1/lake_ontario_real"
MANIFEST = ROOT / "data/manifests/historical_sources.json"
CONFIG = ROOT / "configs/stage7_scenarios.yaml"
B2_AUDIT = ROOT / "outputs/baseline_v1.1/b2/forcing_audit.json"
ARTIFACTS = (
    "particles.npz",
    "mass_audit.csv",
    "particles.png",
    "forcing_snapshot.png",
    "time_coverage.png",
    "forcing_audit.json",
)


class Blocked(ValueError):
    """The historical inputs do not support generation."""


def checked_inputs():
    manifest = json.loads(MANIFEST.read_bytes())
    audit = json.loads(B2_AUDIT.read_bytes())
    if (audit["status"], audit["scenario"], audit["forcing_kind"]) != (
        "passed",
        "lake_ontario",
        "historical_real",
    ):
        raise Blocked("Lake Ontario requires a passing B2 forcing audit")
    if audit["input_identity"]["manifest_sha256"] != digest(MANIFEST):
        raise Blocked("historical manifest differs from the B2 audit")
    if audit["input_identity"]["stage7_config_sha256"] != digest(CONFIG):
        raise Blocked("mission configuration differs from the B2 audit")
    lake = next(c for c in manifest["scenarios"] if c["scenario"] == "lake_ontario")
    files = {role: lake[role]["local_files"] for role in ("wind", "current")}
    for role, sources in files.items():
        if sources != audit["fields"][role]["source_files"]:
            raise Blocked(f"{role} sources differ from the B2 audit")
        for row in sources:
            if digest(ROOT / row["local_path"]) != row["sha256"]:
                raise Blocked(f"historical source SHA-256 mismatch: {row['local_path']}")
    package = Path(asar_repro.__file__).parent
    modules = (
        "historical_drift",
        "opendrift_adapter",
        "historical_reader",
        "forcing",
        "hrrr",
        "grid",
        "gridding",
        "objective",
        "motion",
        "belief",
        "scenarios",
    )
    return dict(
        manifest_sha256=digest(MANIFEST),
        b2_audit_sha256=digest(B2_AUDIT),
        stage7_config_sha256=digest(CONFIG),
        sources=files,
        implementation_sha256={
            **{n: digest(package / f"{n}.py") for n in modules},
            "generator": digest(Path(__file__)),
            "figures": digest(Path(__file__).with_name("plot_historical_drift.py")),
        },
    )


def read_cache(folder, cfg, fingerprint):
    meta = json.loads((folder / "metadata.json").read_bytes())
    expected = config_digest(fingerprint)
    if meta["config_hash"] != expected:
        raise ValueError("stale historical particle cache; select a new output directory")
    if meta["status"] != "passed" or set(meta["artifacts_sha256"]) != set(ARTIFACTS):
        raise ValueError("incomplete historical particle archive")
    for name, sha in meta["artifacts_sha256"].items():
        if digest(folder / name) != sha:
            raise ValueError(f"cache artifact SHA-256 mismatch: {name}")
    with np.load(folder / "particles.npz", allow_pickle=False) as archive:
        data = {name: archive[name] for name in archive.files}
    if data["config_hash"].item() != expected:
        raise ValueError("NPZ cache fingerprint mismatch")
    native, target = axes(cfg)
    np.testing.assert_array_equal(data["raw_time_utc"], native)
    np.testing.assert_array_equal(data["time_utc"], target)
    return meta, data


def generate(cfg, fingerprint):
    native, target = axes(cfg)
    try:
        bundle = load_historical_forcing(
            MANIFEST, ROOT, start_utc=utc_label(native[0]), end_utc=utc_label(native[-1])
        )
    except (OSError, ValueError, KeyError) as error:
        raise Blocked(str(error)) from error
    before = perf_counter()
    try:
        raw, failures, model = run_historical(cfg, bundle)
    except SystemExit as error:
        raise Blocked(f"Leeway stopped before completing the task window: {error}") from error
    seconds = perf_counter() - before
    grid, data, ledger, J = build_archive(raw, failures, bundle, cfg, fingerprint)
    native_mass = []
    for time, cells in zip(native, data["raw_cell_ids"]):
        _, mass = particle_step(grid, cells, data["initial_weights"])
        np.testing.assert_allclose(mass.sum(), 1, rtol=0, atol=1e-12)
        native_mass.append(
            dict(
                utc=utc_label(time),
                total=float(mass.sum()),
                searchable=float(mass[: grid.graph.size].sum()),
                **{k: float(mass[v]) for k, v in grid.special.items()},
            )
        )
    meta = dict(
        status="passed",
        stage="B3",
        scenario="lake_ontario",
        forcing_kind=bundle.forcing_kind,
        experiment_label="historical_real_forcing_allwater",
        shoreline_policy=bundle.shoreline_policy,
        interpretation="retrospective_environment_reconstruction",
        config_hash=data["config_hash"].item(),
        provenance=fingerprint,
        interpreter=sys.executable,
        model=model,
        weather_valid_utc={
            role: [t.isoformat() for t in field.times]
            for role, field in (("wind", bundle.wind), ("current", bundle.current))
        },
        native_output=dict(
            first_utc=utc_label(native[0]), last_utc=utc_label(native[-1]), frames=len(native)
        ),
        search_output=dict(
            first_utc=utc_label(target[0]), last_utc=utc_label(target[-1]), frames=len(target)
        ),
        archive_dims=["time", "trajectory_id"],
        status_flags=raw.flags,
        search_grid=dict(
            crs=grid.projection.target_crs.to_wkt(),
            indexing="row-major, north row first; " "west/south inclusive; east/north exclusive",
            special_bins=grid.special,
        ),
        resampling="UTC linear latitude and shortest-arc longitude with matching status and mask; "
        "ambiguous intervals unknown; carry terminal states without inventing positions",
        forcing_time_interpolation="linear between hourly native fields",
        forcing_terminal_events=failures,
        postprocessing="wet or dry and support checked at native and planning positions; future samples "
        "after a forcing-induced terminal event retain its original mass category",
        native_mass=native_mass,
        audit=dict(
            path="fixed east/west transect through CSP, first move east",
            q=cfg["audit_q"],
            J=J,
            Pd=ledger[-1]["Pd"],
            M_T=ledger[-1]["M"],
            max_error=max(row["max_error"] for row in ledger),
            max_prior_special_mass={
                k: max(row[f"prior_{k}"] for row in ledger) for k in grid.special
            },
            first=ledger[0],
            last=ledger[-1],
        ),
        integration_seconds=seconds,
    )
    return bundle, grid, data, ledger, meta


def publish(folder, generated, cfg):
    bundle, grid, data, ledger, meta = generated
    folder.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".b3-", dir=folder.parent) as temp:
        staging = Path(temp) / "archive"
        staging.mkdir()
        np.savez_compressed(staging / "particles.npz", **data)
        with (staging / "mass_audit.csv").open("w", encoding="utf-8", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=ledger[0], lineterminator="\n")
            writer.writeheader()
            writer.writerows(ledger)
        shutil.copyfile(B2_AUDIT, staging / "forcing_audit.json")
        plot_drift(staging, grid, data, bundle, cfg)
        plot_time_coverage(staging, data, bundle)
        meta["artifacts_sha256"] = {name: digest(staging / name) for name in ARTIFACTS}
        with (staging / "metadata.json").open("w", encoding="utf-8", newline="\n") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.write("\n")
        if folder.exists():
            raise FileExistsError(f"archive already exists: {folder}")
        staging.rename(folder)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument(
        "--verify-replay",
        action="store_true",
        help="reintegrate once and compare with a frozen archive",
    )
    opts = p.parse_args()
    start = perf_counter()
    try:
        inputs = checked_inputs()
    except (OSError, ValueError, KeyError, StopIteration) as error:
        print(json.dumps(dict(stage="B3", status="blocked", reason=str(error)), ensure_ascii=False))
        return 2
    spec = yaml.safe_load(CONFIG.read_bytes())
    cfg = drift_config(spec, spec["scenarios"]["lake_ontario"])
    cfg.pop("forcing")
    cfg.update(forcing_kind="historical_real", audit_q=spec["q"])
    fingerprint = identity(cfg, inputs)
    target = opts.output_dir.resolve()
    try:
        compared = 0
        if target.exists():
            meta, frozen = read_cache(target, cfg, fingerprint)
            mode = "cache_hit"
            if opts.verify_replay:
                generated = generate(cfg, fingerprint)
                compared = compare_replay(frozen, generated[2])
                np.testing.assert_equal(
                    meta["forcing_terminal_events"], generated[-1]["forcing_terminal_events"]
                )
                mode = "independent_replay"
        elif opts.verify_replay:
            raise ValueError("freeze the B3 archive before checking independent replay")
        else:
            generated = generate(cfg, fingerprint)
            publish(target, generated, cfg)
            meta, _ = read_cache(target, cfg, fingerprint)
            mode = "generated"
    except Blocked as error:
        print(json.dumps(dict(stage="B3", status="blocked", reason=str(error)), ensure_ascii=False))
        return 2
    except (ValueError, OSError, KeyError, AssertionError) as error:
        print(json.dumps(dict(stage="B3", status="failed", reason=str(error)), ensure_ascii=False))
        return 1
    print(
        json.dumps(
            dict(
                stage="B3",
                status="passed",
                mode=mode,
                config_hash=meta["config_hash"],
                archive_sha256=meta["artifacts_sha256"]["particles.npz"],
                native=meta["native_output"],
                search=meta["search_output"],
                compared_npz_arrays=compared,
                exact_replay=True if compared else None,
                forcing_terminal_events=len(meta["forcing_terminal_events"]),
                archive_integration_seconds=meta["integration_seconds"],
                runtime_seconds=perf_counter() - start,
            ),
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
