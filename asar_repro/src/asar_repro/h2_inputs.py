"""Generate and validate one immutable particle realization per H2 seed."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from time import perf_counter
import traceback

import numpy as np

from .h2_forcing import mission_config
from .historical_drift import build_archive, identity, run_historical
from .physical_followup_data import _object_hash, _physical_inputs, _read, _sha, _write
from .scenarios import config_digest

DATA_ROLE = "new_date_historical_forcing_preregistered"
FILES = ("request.json", "particles.npz", "metadata.json", "mass_audit.json",
         "forcing_validation.json", "prepare.log")


def _validate_ledger(ledger, cfg, data):
    if len(ledger) != cfg["budget"] + 1:
        raise ValueError("Mass ledger does not cover every observation time")
    categories = ("searchable", "land", "outside", "inactive", "unknown")
    for index, row in enumerate(ledger):
        values = [row["max_error"], row["prior_total"], row["Pd"], row["M"]]
        if (row["step"] != index or row["particles"] != cfg["particles"]
                or not np.isfinite(values).all() or row["max_error"] > 1e-12
                or abs(row["prior_total"] - 1) > 1e-12
                or abs(row["Pd"] + row["M"] - 1) > 1e-12):
            raise ValueError(f"Mass conservation failed at step {index}")
        for role, expected in (("prior", 1), ("posterior", row["M"])):
            mass = [row[f"{role}_{category}"] for category in categories]
            if not np.isfinite(mass).all() or min(mass) < -1e-12 or abs(sum(mass)-expected) > 1e-12:
                raise ValueError(f"Special and searchable mass not preserved at step {index}")
    cells = data["raw_cell_ids"]
    maximum = int(np.prod(cfg["grid_rows_cols"])) + 3
    if (cells.shape != data["raw_lon"].shape or cells.dtype.kind not in "iu"
            or np.any(cells < 0) or np.any(cells > maximum)):
        raise ValueError("Raw native special and grid assignments are inconsistent")


def prepare_h2_input(case, destination, bundle, forcing_validation, evidence):
    """Called after method and six data blocks are frozen. Never retries an integration."""
    destination = Path(destination)
    cfg = mission_config(case)
    if forcing_validation["status"] != "eligible" or bundle.forcing_kind != "historical_real":
        raise ValueError("H2 particles require eligible historical inputs")
    if destination.exists():
        load_h2_input(None, case, destination, "heading_square")
        manifest = _read(destination / "manifest.json")
        if manifest["evidence"] != evidence:
            raise ValueError("Existing seed archive belongs to another forcing or method lock")
        return manifest

    destination.mkdir(parents=True, exist_ok=False)
    started = perf_counter()
    try:
        request = dict(case=case, config=cfg, data_role=DATA_ROLE, evidence=evidence)
        _write(destination / "request.json", request)
        _write(destination / "forcing_validation.json", forcing_validation)
        with (destination / "prepare.log").open("x", encoding="utf-8") as log:
            with redirect_stdout(log), redirect_stderr(log):
                print(f"{case['id']}: beginning one fixed-seed historical Leeway run", flush=True)
                provenance = identity(cfg, evidence)
                start_drift = perf_counter()
                raw, failures, model = run_historical(cfg, bundle)
                integration_wall = perf_counter() - start_drift
                _, data, ledger, _ = build_archive(raw, failures, bundle, cfg, provenance)
                _physical_inputs(data, cfg, "heading_square")
                _validate_ledger(ledger, cfg, data)
                print("Native UTC, stable IDs, observation grids and mass ledger verified", flush=True)
        with (destination / "particles.npz").open("xb") as archive:
            np.savez_compressed(archive, **data)
        _write(destination / "mass_audit.json", ledger)
        _write(destination / "metadata.json", dict(
            status="prepared", case=case, config=cfg, data_role=DATA_ROLE,
            provenance=provenance, config_hash=str(data["config_hash"].item()),
            particle_sha256=_sha(destination / "particles.npz"), model=model,
            terminal_forcing=failures, opendrift_runs=1, integration_wall_s=integration_wall,
            generation_wall_s=perf_counter()-started, fixed_path_mass_audit_only=True,
            max_mass_error=max(row["max_error"] for row in ledger),
        ))
        manifest = dict(status="prepared", case=case, data_role=DATA_ROLE,
                        config_sha256=_object_hash(cfg), evidence=evidence,
                        files={name: _sha(destination / name) for name in FILES})
        _write(destination / "manifest.json", manifest)
        return manifest
    except BaseException as error:
        _write(destination / "failure.json", dict(
            status="blocked", case=case, reason=str(error), traceback=traceback.format_exc(),
            elapsed_s=perf_counter()-started, retry_policy="preserve failure; do not repeat the seed",
        ))
        raise


def load_h2_input(root, case, destination, footprint):
    """Load one hash-verified archive for the existing physical and discrete evaluators."""
    destination = Path(destination)
    cfg = mission_config(case)
    if footprint not in ("heading_square", "axis_square"):
        raise ValueError("Unregistered H2 sensor footprint")
    if (destination / "failure.json").exists():
        raise ValueError("Seed archive generation failed. Retain its evidence.")
    manifest_path = destination / "manifest.json"
    manifest = _read(manifest_path)
    if (manifest["status"] != "prepared" or manifest["data_role"] != DATA_ROLE
            or manifest["case"] != case or manifest["config_sha256"] != _object_hash(cfg)
            or set(manifest["files"]) != set(FILES)):
        raise ValueError("H2 seed archive identity differs from the requested experiment")
    for name, expected in manifest["files"].items():
        if _sha(destination / name) != expected:
            raise ValueError(f"H2 seed archive SHA-256 mismatch: {name}")
    metadata = _read(destination / "metadata.json")
    if (metadata["case"] != case or metadata["config"] != cfg or metadata["opendrift_runs"] != 1
            or metadata["data_role"] != DATA_ROLE
            or metadata["particle_sha256"] != manifest["files"]["particles.npz"]
            or metadata["provenance"]["input_fingerprints"] != manifest["evidence"]
            or config_digest(metadata["provenance"]) != metadata["config_hash"]):
        raise ValueError("H2 seed provenance does not match its source and method")
    with np.load(destination / "particles.npz", allow_pickle=False) as archive:
        data = {key: archive[key] for key in archive.files}
    if str(data["config_hash"].item()) != metadata["config_hash"]:
        raise ValueError("H2 particle array provenance differs from its metadata")
    _validate_ledger(_read(destination / "mass_audit.json"), cfg, data)
    problem, grid, discrete, info = _physical_inputs(data, cfg, footprint)
    return problem, grid, discrete, dict(
        info, case=case, footprint=footprint, forcing_kind="historical_real",
        input_role=DATA_ROLE, manifest_sha256=_sha(manifest_path),
        particle_sha256=manifest["files"]["particles.npz"], opendrift_runs_in_search=0,
    )
