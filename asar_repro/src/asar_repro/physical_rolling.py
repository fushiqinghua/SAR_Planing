"""Two-arm fixed-prediction rolling experiment; no execution at import time.

C0 calls the unchanged eight-neighbour ``completion_J`` refinement once.
C1 uses the same arithmetic in an isolated prefix-constrained copy and plans
the entire remaining horizon after each committed prefix. The target archive,
objective, sensor and absolute observation clock never change.

This is a virtual all-nondetection execution, not a flight controller. Compute
latency advances virtual mission time during online stages while the aircraft
continues the already committed route; no wall-clock sleeps are performed.
All simulator bookkeeping is charged. An external audit may verify this
returned route but must never introduce or accept another candidate.
"""
from __future__ import annotations

import math
from time import perf_counter

from .physical_model import PhysicalProblem
from .physical_refinement import solve_physical_refinement
from .physical_rolling_solver import solve_physical_prefix
from .physical_search import OBJECTIVE_ATOL, REPLAY_ATOL


BASE_COMMIT = "be048ea2304a25211be546c24cca506e87734049"
DEFAULT_SOLVER_OPTIONS = dict(
    guide_weight=1.04, max_open=100000, completion="greedy", objective="J",
    pd_tolerance=1e-8, completion_every=128, completion_max_calls=32,
    archive=True, archive_limit=512, archive_history_limit=8192,
)


def _finite(value, name, minimum=0.0, strict=False):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    value = float(value)
    if not math.isfinite(value) or (value <= minimum if strict else value < minimum):
        raise ValueError(f"{name} is outside its permitted range")
    return value


def _options(options):
    result = dict(DEFAULT_SOLVER_OPTIONS)
    supplied = {} if options is None else dict(options)
    if supplied.get("max_expansions") is not None:
        raise ValueError("formal rolling runs cannot use an expansion-count limit")
    supplied.pop("max_expansions", None)
    unknown = set(supplied) - set(result)
    if unknown:
        raise ValueError(f"unsupported solver options: {sorted(unknown)}")
    result.update(supplied)
    if result["completion"] != "greedy" or result["objective"] != "J":
        raise ValueError("both arms must use the frozen completion_J method")
    return result


def _milestones(score, horizon_s, tolerance_s):
    """Only actually reached, nonterminal vertices can become planning roots."""
    route = score["waypoints"]
    arrivals = score["planned_arrival_times_s"]
    if len(route) != len(arrivals):
        raise AssertionError("route/arrival ledger lengths differ")
    return [(index, float(time_s)) for index, time_s in enumerate(arrivals)
            if float(time_s) < horizon_s - tolerance_s]


def _select_anchor(score, *, fraction, horizon_s, execution_time_s,
                   protected_prefix, allocated_seconds, guard_s, tolerance_s):
    """Select request and commit vertices from the currently executable route."""
    route = tuple(score["waypoints"])
    if route[:len(protected_prefix)] != tuple(protected_prefix):
        raise AssertionError("active route changed an already committed prefix")
    points = _milestones(score, horizon_s, tolerance_s)
    threshold = max(float(fraction) * horizon_s, execution_time_s)
    request = next(((index, time_s) for index, time_s in points
                    if index >= len(protected_prefix) - 1
                    and time_s + tolerance_s >= threshold), None)
    if request is None:
        return None, None, None
    index, request_time = request
    ready_envelope = request_time + allocated_seconds + guard_s
    anchor = next(((candidate_index, time_s) for candidate_index, time_s in points
                   if candidate_index > index and time_s + tolerance_s >= ready_envelope), None)
    if anchor is None:
        return request, None, None
    anchor_index, anchor_time = anchor
    return request, anchor, route[:anchor_index + 1]


def _verify_candidate(problem, raw, prefix):
    """Full original-score validation; the caller includes this cost in its slot."""
    if raw.get("error") is not None or raw.get("status") == "failed":
        raise ValueError(f"inner solver failed: {raw.get('error')}")
    route = raw.get("waypoints")
    if route is None:
        return None
    route = tuple(route)
    if route[:len(prefix)] != tuple(prefix):
        raise ValueError("candidate changed the irrevocably committed prefix")
    score = problem.replay(route, connectivity=8)
    for key in ("J", "pd_final"):
        value = raw.get(key)
        if value is None or not math.isfinite(float(value)) or abs(float(value) - score[key]) > REPLAY_ATOL:
            raise ValueError(f"inner {key} differs from original full-route replay")
    survival = raw.get("survival")
    if (survival is None or len(survival) != len(score["survival"])
            or any(not math.isfinite(float(a)) or abs(float(a) - b) > REPLAY_ATOL
                   for a, b in zip(survival, score["survival"]))):
        raise ValueError("inner survival differs from original full-route replay")
    return score


def run_physical_rolling(
        problem, *, method, initial_waypoints, total_seconds=30.0,
        triggers=(0.2, 0.4, 0.6, 0.8), anchor_guard_s=0.25,
        solver_reserve_s=0.25, solver_options=None):
    """Return a budgeted C0/C1 route with its causal virtual execution ledger.

    C0 has one pre-CST slot. C1 has one pre-CST slot and one slot per fixed
    trigger. Every slot is at most total_seconds / slot_count; early unused
    budget is not redistributed. Actual overshoot is debited from the shared
    budget before later slots. Accepted candidates must be returned and fully
    validated inside both deadlines and, online, before their commit anchor.

    The first slot includes common initial-route copy and original replay.
    Each subsequent slot includes trigger/anchor selection, prefix replay,
    solver preprocessing, search, full candidate validation and acceptance.
    Time between slots is attributed to the next slot. Final packaging time is
    separately recorded and included in total active computation. No virtual
    flight duration is charged as processor use and no sleeping is performed.
    """
    started = perf_counter()
    if not isinstance(problem, PhysicalProblem):
        raise TypeError("problem must be a PhysicalProblem")
    if method not in ("C0", "C1"):
        raise ValueError("method must be C0 or C1")
    total_seconds = _finite(total_seconds, "total_seconds", strict=True)
    anchor_guard_s = _finite(anchor_guard_s, "anchor_guard_s")
    solver_reserve_s = _finite(solver_reserve_s, "solver_reserve_s")
    triggers = tuple(_finite(value, "trigger", strict=True) for value in triggers)
    if any(value >= 1 for value in triggers) or tuple(sorted(set(triggers))) != triggers:
        raise ValueError("triggers must be strictly increasing fractions between zero and one")
    options = _options(solver_options)
    slots = 1 if method == "C0" else len(triggers) + 1
    nominal_slot = total_seconds / slots
    global_deadline = started + total_seconds
    phases, history = [], []
    active = None
    initial = None
    error = None
    execution_time = 0.0
    protected_prefix = (problem.start,)
    phase_started = started
    last_phase_end = started

    def finish():
        completed = perf_counter()
        finalization = max(0.0, completed - last_phase_end)
        wall = float(completed - started)
        ledger_sum = sum(phase["actual_compute_s"] for phase in phases)
        result = dict(
            algorithm="fixed_prediction_rolling_validation_v1", method=method,
            status="failed" if error else "completed", error=error,
            source_base=BASE_COMMIT, connectivity=8, footprint=problem.footprint,
            total_seconds=total_seconds, slot_count=slots, nominal_slot_seconds=nominal_slot,
            triggers=list(triggers), anchor_guard_s=anchor_guard_s,
            solver_reserve_s=solver_reserve_s, solver_options=options,
            execution_model="virtual_all_nondetection; committed_motion_during_online_compute; no_wait",
            comparison_scope="same_fixed_dynamic_prediction_and_total_compute_cap; full_remaining_horizon",
            preparation_scope="historical_common_seed_generation_external; copy_and_replay_charged",
            pre_cst_compute_cap_s=nominal_slot,
            global_optimality_certified=False, epsilon_certificate=None,
            initial_score=initial, best=active, phases=phases, history=history,
            J=None if active is None else active["J"],
            pd_final=None if active is None else active["pd_final"],
            waypoints=None if active is None else active["waypoints"],
            path=None if active is None else active["waypoints"],
            survival=None if active is None else active["survival"],
            protected_prefix_waypoints=list(protected_prefix),
            final_virtual_execution_time_s=problem.horizon_s if active else execution_time,
            planned_observation_times_s=problem.times_s[1:].tolist(),
            phase_compute_sum_s=float(ledger_sum), finalization_compute_s=float(finalization),
            active_compute_s=wall, wall_s=wall,
            deadline_overshoot_s=max(0.0, wall - total_seconds),
            accepted_replans=sum(bool(row["accepted"]) for row in phases if row["stage_index"] > 0),
            late_replans=sum(row["reason"] in (
                "returned_after_deadline", "validation_after_deadline", "missed_anchor")
                for row in phases if row["stage_index"] > 0),
            notes=[
                "No new environmental or target observations enter this experiment.",
                "Earlier accepted full paths are retained as fallbacks; every update preserves its committed prefix.",
                "Final active full path equals the virtually executed path because all replaced suffixes follow irrevocable prefixes.",
                "J is the original full-horizon post-observation survival sum; no segment normalization or horizon extension.",
            ],
        )
        # Include result construction in the reported computation, without
        # accepting or evaluating anything after the last decision checkpoint.
        completed = perf_counter()
        result["finalization_compute_s"] = max(0.0, float(completed - last_phase_end))
        result["active_compute_s"] = result["wall_s"] = float(completed - started)
        result["deadline_overshoot_s"] = max(0.0, result["wall_s"] - total_seconds)
        return result

    schedule = (None,) if method == "C0" else (None,) + triggers
    for stage_index, fraction in enumerate(schedule):
        # The previous checkpoint is the start: interstage bookkeeping is not free.
        if stage_index:
            phase_started = last_phase_end
        allocated = max(0.0, min(nominal_slot, global_deadline - phase_started))
        stage_deadline = phase_started + allocated
        record = dict(
            stage_index=stage_index, trigger_fraction=fraction,
            stage_kind="pre_cst" if stage_index == 0 else "online",
            stage_start_compute_s=float(phase_started - started),
            allocated_seconds=float(allocated), nominal_slot_seconds=nominal_slot,
            stage_deadline_compute_s=float(stage_deadline - started),
            request_time_s=0.0 if stage_index == 0 else None,
            request_waypoint_index=0 if stage_index == 0 else None,
            anchor_time_s=0.0 if stage_index == 0 else None,
            anchor_waypoint_index=0 if stage_index == 0 else None,
            committed_prefix_waypoints=list(protected_prefix),
            acceptance_compute_s=None, cumulative_acceptance_compute_s=None,
            ready_time_s=None, candidate_J=None, candidate_pd_final=None,
            execution_ready_compute_s=None, execution_ready_time_s=None,
            accepted=False, reason=None, inner=None, validation=None,
        )
        try:
            if stage_index == 0:
                seed = tuple(initial_waypoints)
                active = problem.replay(seed, connectivity=8)
                initial = active
                seed_elapsed = float(perf_counter() - started)
                record["initial_copy_replay_s"] = seed_elapsed
                if perf_counter() > stage_deadline or perf_counter() > global_deadline:
                    raise ValueError("common initial route was not validated inside the first slot")
                history.append(dict(
                    source="common_seed", elapsed_s=seed_elapsed,
                    cumulative_compute_s=seed_elapsed, switch_time_s=0.0,
                    J=active["J"], pd_final=active["pd_final"],
                    waypoints=list(active["waypoints"]),
                ))
                prefix = (problem.start,)
            elif allocated <= 0 or perf_counter() >= stage_deadline:
                record["reason"] = "shared_budget_exhausted"
                prefix = None
            else:
                request, anchor, prefix = _select_anchor(
                    active, fraction=fraction, horizon_s=problem.horizon_s,
                    execution_time_s=execution_time, protected_prefix=protected_prefix,
                    allocated_seconds=allocated, guard_s=anchor_guard_s,
                    tolerance_s=problem.time_tolerance_s,
                )
                if request is None:
                    record["reason"] = "no_remaining_request_waypoint"
                else:
                    record["request_waypoint_index"], record["request_time_s"] = request
                    if anchor is None:
                        record["reason"] = "no_remaining_commit_anchor"
                    else:
                        record["anchor_waypoint_index"], record["anchor_time_s"] = anchor
                        record["committed_prefix_waypoints"] = list(prefix)

            if prefix is not None and record["reason"] is None:
                remaining = min(stage_deadline, global_deadline) - perf_counter() - solver_reserve_s
                if remaining <= 0:
                    record["reason"] = "insufficient_budget_after_preparation"
                else:
                    record["inner_budget_seconds"] = float(remaining)
                    call_started = perf_counter()
                    record["inner_start_compute_s"] = float(call_started - started)
                    kwargs = dict(
                        connectivity=8, initial_waypoints=tuple(active["waypoints"]),
                        max_seconds=float(remaining), **options,
                    )
                    if method == "C0":
                        raw = solve_physical_refinement(problem, **kwargs)
                    else:
                        raw = solve_physical_prefix(problem, root_prefix=prefix, **kwargs)
                    record["inner"] = raw
                    returned = perf_counter()
                    record["inner_return_compute_s"] = float(returned - started)
                    if raw.get("error") is not None or raw.get("status") == "failed":
                        raise ValueError(f"inner solver failed: {raw.get('error')}")
                    if returned > stage_deadline or returned > global_deadline:
                        record["reason"] = "returned_after_deadline"
                    else:
                        validation_started = perf_counter()
                        candidate = _verify_candidate(problem, raw, prefix)
                        validated = perf_counter()
                        record["validation"] = dict(
                            kind="original_full_mission_replay", completed=True,
                            wall_s=float(validated - validation_started),
                            completed_compute_s=float(validated - started),
                            prefix_preserved=True, absolute_clock_preserved=True,
                        )
                        if candidate is None:
                            record["reason"] = "no_complete_candidate"
                        else:
                            record["candidate_J"] = candidate["J"]
                            record["candidate_pd_final"] = candidate["pd_final"]
                            # No computation may change a suffix before this checkpoint.
                            accepted_at = perf_counter()
                            elapsed = float(accepted_at - phase_started)
                            ready = 0.0 if stage_index == 0 else record["request_time_s"] + elapsed
                            record["ready_time_s"] = float(ready)
                            if accepted_at > stage_deadline or accepted_at > global_deadline:
                                record["reason"] = "validation_after_deadline"
                            elif stage_index and ready > record["anchor_time_s"] + problem.time_tolerance_s:
                                record["reason"] = "missed_anchor"
                            elif candidate["J"] >= active["J"] - OBJECTIVE_ATOL:
                                record["reason"] = "no_strict_J_improvement"
                            else:
                                active = candidate
                                record["accepted"] = True
                                record["reason"] = "accepted"
                                record["acceptance_compute_s"] = elapsed
                                record["cumulative_acceptance_compute_s"] = float(accepted_at - started)
                                history.append(dict(
                                    source=f"{method}_stage_{stage_index}",
                                    elapsed_s=float(accepted_at - started),
                                    cumulative_compute_s=float(accepted_at - started),
                                    switch_time_s=float(record["anchor_time_s"]),
                                    J=active["J"], pd_final=active["pd_final"],
                                    waypoints=list(active["waypoints"]),
                                ))

            record["active_J_after"] = None if active is None else active["J"]
            record["active_pd_final_after"] = None if active is None else active["pd_final"]
        except Exception as exc:
            error = dict(type=type(exc).__name__, message=str(exc), stage_index=stage_index)
            record["reason"] = "failed"
            record["error"] = error
        last_phase_end = perf_counter()
        record["actual_compute_s"] = float(last_phase_end - phase_started)
        record["cumulative_compute_s"] = float(last_phase_end - started)
        record["slot_overshoot_s"] = max(0.0, last_phase_end - stage_deadline)
        if stage_index and record["request_time_s"] is not None:
            # One checkpoint defines latency, actual charged cost and execution
            # advance. Ledger construction after it is charged to the next slot
            # (or finalization); it cannot make another selection in this slot.
            returned_ready = record["request_time_s"] + record["actual_compute_s"]
            record["execution_ready_compute_s"] = record["actual_compute_s"]
            record["execution_ready_time_s"] = float(returned_ready)
            if record["ready_time_s"] is None:
                record["ready_time_s"] = float(returned_ready)
            if record["anchor_time_s"] is not None:
                protected_prefix = tuple(record["committed_prefix_waypoints"])
                execution_time = max(execution_time, record["anchor_time_s"], returned_ready)
            else:
                execution_time = max(execution_time, returned_ready)
        record["virtual_execution_time_after_s"] = min(problem.horizon_s, execution_time)
        phases.append(record)
        if error is not None:
            break
    return finish()
