"""Explicit, offline H1 input preparation for the physical-motion follow-up.

Importing this module, inspecting checksums, and loading a prepared archive do
not integrate drift or search.  Only ``prepare_case`` invokes OpenDrift.  The
caller must freeze the development selection before calling it.  H1 changes
the task window and particle seed within the *same* historical forcing; it is
not an independent-weather/date validation.  H2 is not implemented here.

``root`` is the repository's ``asar_repro`` directory.  Raw B1 forcing files
are not tracked in Git: restore the existing audited local packages first.
There is no downloader, fallback source, seed replacement, or overwrite mode.
"""

from __future__ import annotations

from contextlib import contextmanager, redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter
import traceback


INDEPENDENCE_LEVEL = "same_forcing_shifted_window_new_seed"
SCHEMA_VERSION = 1

_CASES = (
    dict(id="lake_window_early", base_scene="lake_ontario",
         lkp_utc="2025-08-26T13:45:00Z", cst_utc="2025-08-26T14:45:00Z",
         end_utc="2025-08-26T14:52:33.740Z", seed=1041),
    dict(id="lake_window_late", base_scene="lake_ontario",
         lkp_utc="2025-08-26T15:45:00Z", cst_utc="2025-08-26T16:45:00Z",
         end_utc="2025-08-26T16:52:33.740Z", seed=1042),
    dict(id="hudson_window_early", base_scene="arctic_ocean",
         lkp_utc="2025-08-28T22:00:00Z", cst_utc="2025-08-29T22:00:00Z",
         end_utc="2025-08-29T22:46:18Z", seed=2041),
    dict(id="hudson_window_late", base_scene="arctic_ocean",
         lkp_utc="2025-08-29T02:00:00Z", cst_utc="2025-08-30T02:00:00Z",
         end_utc="2025-08-30T02:46:18Z", seed=2042),
)

_MISSIONS = {
    "lake_ontario": dict(
        forcing_kind="historical_real", seed=41, radius_m=100, particles=500,
        incident_utc="2025-08-26T14:45:00Z", cst_utc="2025-08-26T15:45:00Z",
        lkp_lon_lat=[-76.5, 44.21], csp_lon_lat=[-76.496, 44.215],
        object_key="PIW-2", budget=49, grid_rows_cols=[17, 17],
        integration_s=30, step_s=9.26, cell_width_m=185.2, output_s=30,
        audit_q=0.78),
    "arctic_ocean": dict(
        forcing_kind="historical_real", seed=41, radius_m=100, particles=500,
        incident_utc="2025-08-29T00:00:00Z", cst_utc="2025-08-30T00:00:00Z",
        lkp_lon_lat=[-90.6, 62.85], csp_lon_lat=[-90.447, 62.786],
        object_key="LIFE-RAFT-DB-10", budget=60, grid_rows_cols=[65, 85],
        integration_s=120, step_s=46.3, cell_width_m=926.0, output_s=120,
        audit_q=0.78),
}

_STAGE7 = dict(
    path="configs/stage7_scenarios.yaml",
    sha256="40311df54d7e43dcebdb2e618ebcb81a86add4d83db7a8ac925253ff73f391d6")
_INPUTS = {
    "lake_ontario": dict(
        manifest_path="data/manifests/historical_sources.json",
        manifest_sha256="fa6f8c839bf894a3654a74c28e347f598b413e4ae0484bd7d090b718a43fc400",
        b2_path="outputs/baseline_v1.1/b2/forcing_audit.json",
        b2_sha256="b78f6beabcf396270a06b2305f29bffe2fa989d9af3914e7ffc44de86d94d5bb",
        coverage_utc=["2025-08-26T13:00:00+00:00", "2025-08-26T17:00:00+00:00"]),
    "arctic_ocean": dict(
        manifest_path="data/manifests/historical_sources_additional_b1.json",
        manifest_sha256="2d306909585ffd95992634ddc1e939d64d9af15c50f94547aadc55ca01f3d8fa",
        b2_path="outputs/stdc_v0_2/additional_real_20261124/b2_r2/arctic_ocean/forcing_audit.json",
        b2_sha256="cf2fc7398ed549df7687cec2f95b5b137b207ad003b67558096676c8f2ada0f8",
        coverage_utc=["2025-08-28T21:00:00+00:00", "2025-08-30T03:00:00+00:00"]),
}

_SOURCE_PATHS = tuple("src/asar_repro/" + name + ".py" for name in (
    "physical_followup_data", "physical_model", "historical_drift", "historical_reader", "forcing",
    "additional_forcing", "hrrr", "gridding", "grid", "opendrift_adapter",
    "scenarios", "motion", "objective", "belief")) + ("scripts/b1_gfs.py",)


class InputBlockedError(ValueError):
    """An explicit input gate failed; no replacement data may be substituted."""


def registered_cases():
    """Return a fresh JSON-compatible copy of the four prespecified H1 cases."""
    return deepcopy(list(_CASES))


def _json_default(value):
    if type(value).__module__.split(".")[0] == "numpy":
        return value.tolist() if hasattr(value, "tolist") else value.item()
    raise TypeError(f"Not JSON serializable: {type(value).__name__}")


def _object_hash(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False,
                     default=_json_default).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _sha(path):
    hasher = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(path, value):
    # Exclusive creation is deliberate, including failure and provenance files.
    with Path(path).open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2,
                  allow_nan=False, default=_json_default)
        handle.write("\n")


def _utc(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("An explicit UTC offset is required")
    return result.astimezone(timezone.utc)


def _checked_case(case_spec):
    if not isinstance(case_spec, dict):
        raise ValueError("case_spec must be one of registered_cases()")
    expected = next((c for c in _CASES if c["id"] == case_spec.get("id")), None)
    if expected is None or set(case_spec) != set(expected):
        raise ValueError("Unknown or modified H1 case fields; register a new study")
    # Boolean seeds compare equal to integers in Python; type checking is explicit.
    if type(case_spec["seed"]) is not int or case_spec != expected:
        raise ValueError("H1 case window, scene and seed are frozen")
    return deepcopy(expected)


def case_config(case_spec):
    """Frozen base mission, changing only incident/CST timestamps and seed."""
    case = _checked_case(case_spec)
    cfg = deepcopy(_MISSIONS[case["base_scene"]])
    cfg.update(incident_utc=case["lkp_utc"], cst_utc=case["cst_utc"], seed=case["seed"])
    if abs((_utc(case["end_utc"]) - _utc(case["cst_utc"])).total_seconds()
           - cfg["budget"] * cfg["step_s"]) > 1e-9:
        raise ValueError("Registered end time differs from the fixed mission horizon")
    return cfg


def _inside(root, relative):
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Input path must stay inside asar_repro")
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Input path resolves outside asar_repro")
    return path


def _file_check(root, relative, expected):
    path = _inside(root, relative)
    result = dict(path=relative, sha256=expected, actual_sha256=None, status="missing")
    if path.is_file():
        result.update(actual_sha256=_sha(path), bytes=path.stat().st_size)
        result["status"] = "verified" if result["actual_sha256"] == expected else "hash_mismatch"
    return result


def forcing_inventory(root):
    """Read-only checksum inventory; imports no numerical/drift dependencies.

    Returns ``status``, per-scene ``scenes`` and explicit ``errors``.  Missing
    bytes are reported together.  The result does not certify that an installed
    OpenDrift environment can run; native field checks occur during preparation.
    """
    root = Path(root).resolve()
    shared = _file_check(root, _STAGE7["path"], _STAGE7["sha256"])
    result = dict(schema_version=SCHEMA_VERSION, status="ready", shared_config=shared,
                  independence_level=INDEPENDENCE_LEVEL, scenes={}, errors=[],
                  network_downloads=False, raw_forcing_tracked_in_git=False)
    for name, fixed in _INPUTS.items():
        scene = dict(base_scene=name, status="ready", **deepcopy(fixed), sources=[], errors=[])
        for label, row in (
                ("stage7_config", shared),
                ("manifest", _file_check(root, fixed["manifest_path"], fixed["manifest_sha256"])),
                ("b2_audit", _file_check(root, fixed["b2_path"], fixed["b2_sha256"]))):
            scene[label] = row
            if row["status"] != "verified":
                scene["errors"].append(f"{row['status']}: {row['path']}")
        if scene["manifest"]["status"] == "verified":
            try:
                doc = _read(root / fixed["manifest_path"])
                candidates = [c for c in doc["scenarios"] if c["scenario"] == name]
                if len(candidates) != 1:
                    raise ValueError("Manifest must contain exactly one matching scene")
                source_case = candidates[0]
                if source_case["forcing_kind"] != "historical_real" or source_case["pair_status"] != "verified":
                    raise ValueError("Historical B1 wind/current pair is not verified")
                scene["source_records"] = {}
                seen = set()
                for role in ("wind", "current"):
                    files = source_case[role]["local_files"]
                    if not files:
                        raise ValueError(f"Empty {role} inventory")
                    scene["source_records"][role] = deepcopy(files)
                    for row in files:
                        relative = row["local_path"]
                        if relative in seen:
                            raise ValueError(f"Duplicate forcing input: {relative}")
                        seen.add(relative)
                        checked = _file_check(root, relative, row["sha256"])
                        scene["sources"].append(dict(role=role, **checked))
                        if checked["status"] != "verified":
                            scene["errors"].append(f"{checked['status']}: {relative}")
            except (KeyError, TypeError, ValueError, OSError) as exc:
                scene["errors"].append(f"Manifest validation failed: {exc}")
        if scene["errors"]:
            scene["status"] = "blocked"
            result["errors"].extend(f"{name}: {error}" for error in scene["errors"])
        result["scenes"][name] = scene
    if result["errors"]:
        result["status"] = "blocked"
        result["recovery"] = (
            "Raw forcing files are not tracked in Git. Restore the existing audited "
            "B1 packages at the recorded data/raw/historical paths. No download, "
            "alternative source, extrapolation, or seed replacement is attempted.")
    result["inventory_sha256"] = _object_hash(result)
    return result


def _source_fingerprints(root):
    missing = [path for path in _SOURCE_PATHS if not (root / path).is_file()]
    if missing:
        raise InputBlockedError("Required local source files missing: " + ", ".join(missing))
    return {path: _sha(root / path) for path in _SOURCE_PATHS}


@contextmanager
def _scripts_path(root):
    path = str(root / "scripts")
    inserted = path not in sys.path
    if inserted:
        sys.path.insert(0, path)
    try:
        yield
    finally:
        if inserted:
            sys.path.remove(path)


def _load_bundle(root, cfg, scene, native):
    from .historical_drift import utc_label
    window = (utc_label(native[0]), utc_label(native[-1]))
    if scene == "lake_ontario":
        from .forcing import load_historical_forcing
        return load_historical_forcing(root / _INPUTS[scene]["manifest_path"], root,
                                       start_utc=window[0], end_utc=window[1])
    from .additional_forcing import load_additional_forcing
    return load_additional_forcing(root, scene, window=window)[0]


def _generate(root, case, cfg, inventory, sources):
    """The only integration entry point, reachable only from prepare_case."""
    import numpy as np
    from .historical_drift import axes, identity, run_historical, build_archive, utc_label

    native, target = axes(cfg)
    with _scripts_path(root):
        bundle = _load_bundle(root, cfg, case["base_scene"], native)
    probes, fields = [], {}
    for field in (bundle.wind, bundle.current):
        if not field.times[0] <= _utc(utc_label(native[0])) <= _utc(utc_label(native[-1])) <= field.times[-1]:
            raise InputBlockedError(f"{field.role} does not bracket the rounded native output window")
        fields[field.role] = dict(
            valid_times_utc=[t.isoformat() for t in field.times],
            metadata=field.metadata, shape=list(field.values.shape))
        for stamp in native:
            for label in ("lkp_lon_lat", "csp_lon_lat"):
                lon, lat = cfg[label]
                uv, status = field.probe(_utc(utc_label(stamp)), [lon], [lat])
                if status[0] != "ok" or not np.isfinite(uv[0]).all():
                    raise InputBlockedError(f"{field.role} unavailable at {label}, {utc_label(stamp)}: {status[0]}")
                probes.append(dict(role=field.role, point=label, utc=utc_label(stamp),
                                   east_m_s=float(uv[0, 0]), north_m_s=float(uv[0, 1]), status="ok"))
    inputs = dict(case_spec=case, independence_level=INDEPENDENCE_LEVEL,
                  forcing_inventory=inventory, implementation_sha256=sources)
    fingerprint = identity(cfg, inputs)
    print(f"{case['id']}: source and native-window checks passed; integrating one fixed seed", flush=True)
    started = perf_counter()
    raw, failures, model = run_historical(cfg, bundle)
    integration_wall_s = perf_counter() - started
    _, data, ledger, audit_J = build_archive(raw, failures, bundle, cfg, fingerprint)
    return data, dict(provenance=fingerprint, model=model, terminal_forcing=failures,
                      opendrift_runs=1, integration_wall_s=integration_wall_s,
                      audit_J=audit_J, native_utc=[utc_label(t) for t in native],
                      planning_utc=[utc_label(t) for t in target]), ledger, dict(
                          fields=fields, point_probes=probes)


class _Tee:
    def __init__(self, stream, log, channel):
        self.stream, self.log, self.channel = stream, log, channel

    def _live_stream(self):
        # A library logging handler may retain the first redirected stderr.
        # Subsequent cases must never append to an already frozen log or fail
        # on a closed handle: forward to the current case's live capture.
        current = getattr(sys, self.channel)
        return current if isinstance(current, _Tee) and current is not self else self.stream

    def write(self, value):
        if self.log.closed:
            return self._live_stream().write(value)
        self.log.write(value)
        self.log.flush()
        return self.stream.write(value)

    def flush(self):
        if self.log.closed:
            self._live_stream().flush()
            return
        self.log.flush()
        self.stream.flush()

    def __getattr__(self, key):
        return getattr(self.stream, key)


def prepare_case(root, case_spec, destination):
    """Explicitly generate one immutable H1 archive after caller-side selection.

    ``destination`` must not exist, even as an empty or failed directory.
    Failures retain ``failure.json``, stdout/stderr log and available provenance.
    Success writes ``manifest.json`` with hashes of every deliverable file.
    The returned mapping additionally contains its *file* ``manifest_sha256``;
    that self-hash is not embedded inside manifest.json.
    """
    root, destination = Path(root).resolve(), Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite prepared or failed input directory: {destination}")
    case, cfg = _checked_case(case_spec), case_config(case_spec)
    destination.mkdir(parents=True, exist_ok=False)
    started = perf_counter()
    request = dict(schema_version=SCHEMA_VERSION, status="requested", case_spec=case,
                   config=cfg, independence_level=INDEPENDENCE_LEVEL,
                   requested_utc=datetime.now(timezone.utc).isoformat())
    _write(destination / "request.json", request)
    try:
        with (destination / "prepare.log").open("x", encoding="utf-8", newline="\n") as log:
            with redirect_stdout(_Tee(sys.stdout, log, "stdout")), redirect_stderr(_Tee(sys.stderr, log, "stderr")):
                print(f"{case['id']}: validating existing local forcing; no downloads", flush=True)
                inventory = forcing_inventory(root)
                _write(destination / "input_validation.json", inventory)
                selected = inventory["scenes"][case["base_scene"]]
                if selected["status"] != "ready":
                    raise InputBlockedError("; ".join(selected["errors"]) + ". " + inventory["recovery"])
                sources = _source_fingerprints(root)
                _write(destination / "source_fingerprints.json", sources)
                data, drift, ledger, validation = _generate(root, case, cfg, selected, sources)
                # No solver, search, trajectory selection or particle filtering here.
                import numpy as np
                with (destination / "particles.npz").open("xb") as archive:
                    np.savez_compressed(archive, **data)
                _write(destination / "mass_audit.json", ledger)
                _write(destination / "forcing_validation.json", validation)
                meta = dict(schema_version=SCHEMA_VERSION, status="prepared", case_spec=case,
                            config=cfg, config_hash=str(data["config_hash"].item()),
                            independence_level=INDEPENDENCE_LEVEL,
                            particle_sha256=_sha(destination / "particles.npz"),
                            source_sha256=sources, initial_mass=float(data["initial_weights"].sum()),
                            max_mass_error=max(row["max_error"] for row in ledger),
                            searchable_mass_by_step=[row["prior_searchable"] for row in ledger],
                            prior_special_mass_by_step=[{k: row["prior_" + k] for k in
                                ("land", "outside", "inactive", "unknown")} for row in ledger],
                            generation_wall_s=perf_counter() - started,
                            model_limitations=["same historical forcing", "all-water coast approximation",
                                               "native forcing masks retained", "square sensor proxy"],
                            **drift)
                from .scenarios import config_digest
                if config_digest(meta["provenance"]) != meta["config_hash"]:
                    raise ValueError("Generated archive provenance hash mismatch")
                # Validate arrays before publishing the readiness manifest.  This
                # constructs inputs only; it does not evaluate any candidate path.
                _physical_inputs(data, cfg, "heading_square")
                _write(destination / "metadata.json", meta)
                print(f"{case['id']}: immutable particle archive prepared; no search executed", flush=True)
        filenames = ("request.json", "input_validation.json", "source_fingerprints.json",
                     "particles.npz", "mass_audit.json", "forcing_validation.json",
                     "metadata.json", "prepare.log")
        manifest = dict(schema_version=SCHEMA_VERSION, status="prepared", case_spec=case,
                        independence_level=INDEPENDENCE_LEVEL, config_sha256=_object_hash(cfg),
                        files={name: _sha(destination / name) for name in filenames})
        _write(destination / "manifest.json", manifest)
        return dict(manifest, manifest_sha256=_sha(destination / "manifest.json"))
    except BaseException as exc:
        trace = traceback.format_exc()
        with (destination / "prepare.log").open("a", encoding="utf-8") as log:
            log.write(trace)
        _write(destination / "failure.json", dict(
            status="blocked", case_spec=case, error=str(exc), error_type=type(exc).__name__,
            traceback=trace, elapsed_s=perf_counter() - started,
            overwrite_allowed=False, retry_policy="keep this failure; do not change seed or source"))
        raise


def _physical_inputs(data, cfg, footprint):
    import numpy as np
    from .grid import GridGraph
    from .gridding import ParticleGrid
    from .historical_drift import axes
    from .motion import ParticleMotion
    from .physical_model import PhysicalProblem

    required = {"trajectory_id", "cell_ids", "time_utc", "initial_weights", "lon", "lat",
                "raw_time_utc", "raw_lon", "raw_lat", "raw_status", "raw_land_binary_mask",
                "status", "land_binary_mask", "special_bins_json", "flags_json", "config_hash"}
    if not required.issubset(data):
        raise ValueError("Prepared archive lacks fields: " + ", ".join(sorted(required - set(data))))
    graph = GridGraph(*cfg["grid_rows_cols"])
    spatial = ParticleGrid(graph, cfg["csp_lon_lat"], cfg["cell_width_m"])
    native, target = axes(cfg)
    cells, ids, weights = (np.asarray(data[k]) for k in ("cell_ids", "trajectory_id", "initial_weights"))
    if (cells.shape != (cfg["budget"] + 1, cfg["particles"])
            or ids.shape != (cfg["particles"],) or weights.shape != ids.shape
            or ids.dtype.kind not in "iu" or len(np.unique(ids)) != len(ids)):
        raise ValueError("Prepared particle dimensions or stable IDs disagree with mission")
    if (not np.isfinite(weights).all() or np.any(weights < 0)
            or abs(float(weights.sum()) - 1) > 1e-12
            or not np.allclose(weights, 1 / cfg["particles"], rtol=0, atol=1e-15)):
        raise ValueError("Prepared particle initial weights changed")
    if (not np.array_equal(data["time_utc"], target)
            or not np.array_equal(data["raw_time_utc"], native)):
        raise ValueError("Prepared native or observation UTC axis differs from frozen case")
    for key in ("lon", "lat", "status", "land_binary_mask"):
        if np.asarray(data[key]).shape != cells.shape:
            raise ValueError(f"Prepared {key} dimensions disagree with particle cells")
    for key in ("raw_lon", "raw_lat", "raw_status", "raw_land_binary_mask"):
        if np.asarray(data[key]).shape != (len(native), cfg["particles"]):
            raise ValueError(f"Prepared {key} dimensions disagree with native time axis")
    if json.loads(str(data["special_bins_json"].item())) != spatial.special:
        raise ValueError("Prepared special-bin mapping changed")
    motion = ParticleMotion(cells, graph.size, ids)
    x, y = spatial.projection.transform(data["lon"], data["lat"])
    xy = np.stack((x, y), axis=-1).astype(float)
    searchable = cells < graph.size
    finite = np.isfinite(xy).all(axis=-1)
    if np.any(searchable & ~finite):
        raise ValueError("Searchable prepared particle lacks finite metric coordinates")
    valid = xy[searchable]
    cols = np.floor(valid[:, 0] / cfg["cell_width_m"] + graph.cols / 2).astype(int)
    south = np.floor(valid[:, 1] / cfg["cell_width_m"] + graph.rows / 2).astype(int)
    remapped = (graph.rows - 1 - south) * graph.cols + cols
    if (np.any(cols < 0) or np.any(cols >= graph.cols) or np.any(south < 0)
            or np.any(south >= graph.rows) or not np.array_equal(remapped, cells[searchable])):
        raise ValueError("Metric projection does not reproduce prepared searchable cells")
    xy[~finite] = 0.0  # masked only; their archived special-bin mass is preserved.
    start = graph.vertex(graph.rows // 2, graph.cols // 2)
    times = np.asarray((target - target[0]) / np.timedelta64(1, "s"), dtype=float)
    problem = PhysicalProblem(
        rows=graph.rows, cols=graph.cols, cell_width_m=cfg["cell_width_m"], speed_m_s=20.0,
        times_s=times, positions_xy=xy, searchable=searchable, initial_weights=weights,
        start=start, q=cfg["audit_q"], footprint=footprint, trajectory_ids=ids)
    discrete = dict(start=start, budget=cfg["budget"], p=weights.copy(), q=cfg["audit_q"], motion=motion)
    info = dict(physical_clock_s=times.tolist(), actual_particles=len(ids), shape=list(cells.shape),
                stable_trajectory_ids=True, initial_mass=float(weights.sum()),
                special_mass_by_step=[float(weights[row >= graph.size].sum()) for row in cells],
                projected_searchable_cell_mapping="matched",
                masked_nonfinite_unsearchable_positions=int((~finite).sum()))
    return problem, graph, discrete, info


def load_prepared_case(root, case_spec, destination, footprint):
    """Verify and load one prepared archive without forcing access or integration.

    Returns ``(PhysicalProblem, GridGraph, discrete_cfg, input_info)``.  The
    discrete configuration has ``start,budget,p,q,motion`` and can initialize
    every compared method from the same new input.  No historical path is
    silently reused.  The caller pins input_info['manifest_sha256'] in tasks.
    """
    root, destination = Path(root).resolve(), Path(destination).resolve()
    case, cfg = _checked_case(case_spec), case_config(case_spec)
    if (destination / "failure.json").exists():
        raise InputBlockedError("Prepared input directory contains a recorded failure; refusing to load")
    manifest = _read(destination / "manifest.json")
    if (manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("status") != "prepared"
            or manifest.get("case_spec") != case or manifest.get("config_sha256") != _object_hash(cfg)
            or manifest.get("independence_level") != INDEPENDENCE_LEVEL):
        raise ValueError("Prepared manifest does not match the registered H1 task")
    required = {"request.json", "input_validation.json", "source_fingerprints.json",
                "particles.npz", "mass_audit.json", "forcing_validation.json", "metadata.json", "prepare.log"}
    if set(manifest.get("files", {})) != required:
        raise ValueError("Prepared manifest file inventory changed")
    for name, expected in manifest["files"].items():
        if _sha(destination / name) != expected:
            raise ValueError(f"Prepared input checksum mismatch: {name}")
    meta = _read(destination / "metadata.json")
    if (meta.get("status") != "prepared" or meta.get("case_spec") != case or meta.get("config") != cfg
            or meta.get("independence_level") != INDEPENDENCE_LEVEL
            or meta.get("particle_sha256") != manifest["files"]["particles.npz"]):
        raise ValueError("Prepared metadata identity mismatch")
    from .scenarios import config_digest
    if config_digest(meta["provenance"]) != meta["config_hash"]:
        raise ValueError("Prepared provenance hash mismatch")
    import numpy as np
    with np.load(destination / "particles.npz", allow_pickle=False) as archive:
        data = {name: archive[name].copy() for name in archive.files}
    if str(data["config_hash"].item()) != meta["config_hash"]:
        raise ValueError("Prepared NPZ provenance hash mismatch")
    problem, graph, discrete, info = _physical_inputs(data, cfg, footprint)
    info.update(case_spec=case, mission=cfg, independence_level=INDEPENDENCE_LEVEL,
                particle_path=str(destination / "particles.npz"), metadata_path=str(destination / "metadata.json"),
                manifest_path=str(destination / "manifest.json"), manifest_sha256=_sha(destination / "manifest.json"),
                particle_sha256=manifest["files"]["particles.npz"], metadata_sha256=manifest["files"]["metadata.json"],
                config_hash=meta["config_hash"], source_sha256=meta["source_sha256"],
                raw_forcing_reaudited=False, footprint=footprint,
                sensor_model_status="controlled_square_footprint_proxy",
                initialization="caller must build and freeze a common four-neighbor route on this archive")
    return problem, graph, discrete, info
