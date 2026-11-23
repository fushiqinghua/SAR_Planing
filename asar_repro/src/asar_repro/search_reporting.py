"""Audited reporting for the unchanged path-state search, not a new planner."""

from importlib.metadata import PackageNotFoundError, version
import platform

import numpy as np

from .heuristic import BOUND_MODES
from .motion import MatrixMotion, ParticleMotion
from .objective import score_path


REQUIRED_FIELDS = """scenario_id forcing_kind source_manifest_sha256 particle_archive_sha256
algorithm heuristic epsilon T q search_status stop_reason incumbent_source found_feasible_path
theoretical_bound_applicable completed_for_certificate discrete_model_certified
J Pd_T M_T planner_wall_s warm_start_s total_wall_s expanded generated pruned peak_open
max_expansions max_open max_seconds config_hash seed environment_versions git_commit""".split()

ASSUMPTIONS = (
    "Conserved nonnegative undetected mass; one cell sensed per step; q in [0,1]; "
    "no false detections; t=0 has no detection; finite full path tree without state merging. "
    "Conditional discrete epsilon bound, subject to float64 arithmetic; not a maritime safety guarantee."
)


def environment_versions():
    result = {"python": platform.python_version(), "platform": platform.platform()}
    for name in ("numpy", "scipy", "pyproj", "opendrift"):
        try:
            result[name] = version(name)
        except PackageNotFoundError:
            result[name] = None
    return result


def classify_result(result, *, model_assumptions_verified=True, initial_source="initial_path"):
    """Separate applicability, completed proof conditions, and returned-route origin.

    A completed paper-greedy run never receives a certificate here, even when
    its numerical value happens to agree with an Oracle on a particular input.
    """
    feasible = result.path is not None
    if feasible != (result.J is not None):
        raise ValueError("path and J must either both exist or both be null")
    if result.status not in ("completed", "budget_exceeded"):
        raise ValueError("unknown search status")
    if (result.status == "completed") != (result.stop_reason is None):
        raise ValueError("search status and stop reason disagree")
    if feasible != (result.incumbent_source is not None):
        raise ValueError("path and incumbent source disagree")
    applicable = bool(model_assumptions_verified and result.heuristic_mode in BOUND_MODES)
    completed = result.status == "completed" and feasible
    certified = applicable and completed
    source = (
        initial_source if result.incumbent_source == "initial_path" else result.incumbent_source
    )
    return dict(
        search_status=result.status,
        stop_reason=result.stop_reason,
        incumbent_source=source,
        found_feasible_path=feasible,
        theoretical_bound_applicable=applicable,
        completed_for_certificate=certified,
        discrete_model_certified=certified,
        search_completed=completed,
        result_class=(
            "completed_search"
            if completed
            else "aborted_feasible_incumbent" if feasible else "aborted_without_path"
        ),
        bound_assumptions=ASSUMPTIONS,
    )


def search_record(
    result,
    grid,
    *,
    start,
    budget,
    p,
    q,
    motion,
    planner_wall_s,
    warm_start_s=0.0,
    limits=None,
    provenance=None,
    initial_source="initial_path"
):
    """Replay a result using the common scorer before producing strict-JSON fields.

    Missing provenance stays null/unspecified; callers must supply verified
    input hashes. Timing excludes preprocessing, replay, provenance and plots.
    Only the two validated built-in motion classes enable the conditional bound.
    """
    durations = np.asarray([planner_wall_s, warm_start_s], dtype=float)
    if not np.isfinite(durations).all() or (durations < 0).any():
        raise ValueError("timings must be finite and nonnegative")
    provenance, limits = provenance or {}, limits or {}
    classification = classify_result(
        result,
        model_assumptions_verified=type(motion) in (MatrixMotion, ParticleMotion),
        initial_source=initial_source,
    )
    record = {
        key: provenance.get(key)
        for key in (
            "scenario_id",
            "source_manifest_sha256",
            "particle_archive_sha256",
            "config_hash",
            "seed",
            "git_commit",
        )
    }
    record.update(
        forcing_kind=provenance.get("forcing_kind", "unspecified"),
        environment_versions=provenance.get("environment_versions") or environment_versions(),
        algorithm={
            "paper_greedy": "ASAR_paper",
            "mass_lb": "ASAR_mass_lb",
            "zero": "ASAR_zero",
        }.get(result.heuristic_mode, "ASAR_paper_literal_abs_time"),
        heuristic=result.heuristic_mode,
        epsilon=float(result.epsilon),
        T=budget,
        q=np.asarray(q).tolist(),
        **classification,
        J=None,
        Pd_T=None,
        M_T=None,
        path=None,
        M_0_to_T=None,
        planner_wall_s=float(planner_wall_s),
        warm_start_s=float(warm_start_s),
        total_wall_s=float(planner_wall_s + warm_start_s),
        timing_scope="warm_start_plus_search; excludes preprocessing/replay/reporting",
        expanded=result.expanded,
        generated=result.generated,
        pruned=result.pruned,
        peak_open=result.peak_open,
        **{key: limits.get(key) for key in ("max_expansions", "max_open", "max_seconds")},
    )
    if result.path is not None:
        score = score_path(grid, result.path, start=start, budget=budget, p=p, q=q, motion=motion)
        if not np.isfinite(result.J) or not np.isclose(score.J, result.J, atol=1e-10, rtol=0):
            raise ValueError("search J differs from independent path replay")
        record.update(
            J=score.J,
            Pd_T=score.pd_final,
            M_T=float(score.survival[-1]),
            path=list(map(int, result.path)),
            M_0_to_T=score.survival.tolist(),
        )
    return record


def summarize_records(records):
    """Never combine distinct forcing kinds into one completion denominator."""
    groups = {}
    for row in records:
        key = (row["forcing_kind"], row["algorithm"])
        group = groups.setdefault(
            key,
            dict(
                forcing_kind=key[0],
                algorithm=key[1],
                runs=0,
                completed_search=0,
                aborted_feasible_incumbent=0,
                aborted_without_path=0,
                certified=0,
            ),
        )
        group["runs"] += 1
        group[row["result_class"]] += 1
        group["certified"] += int(row["discrete_model_certified"])
    for group in groups.values():
        group["completion_rate"] = group["completed_search"] / group["runs"]
    return list(groups.values())
