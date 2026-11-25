"""Bounded, root-released event proposals for the final STDC assessment.

This is a feasible-candidate generator, not a lower bound or an exact solver.
It tests an explicitly different route family from incumbent-prefix repairs:
every proposal starts from the original p at t=0, must visit one or two hard
(vertex, absolute-time) events, and has a free endpoint. Event connectors
preserve exact-step reachability, including parity, even across zero-reward
transit cells. No incumbent corridor or incumbent prefix is imposed.

The default proposal partition uses immutable particle columns / IDs. It is
used only to suggest events; all columns, including special-bin mass, remain
in the unchanged original scorer. At most 24 complete candidates are scored.
The initial route, clustering, event generation, connectors and every replay
are paid inside a cooperative wall-clock budget. A completed replay may
slightly overrun that budget; the overrun is reported, never hidden.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import permutations
from math import isfinite
from time import perf_counter

import numpy as np

from .belief import initial_belief, sensor_probabilities
from .grid import GridGraph, integer
from .motion import ParticleMotion
from .objective import score_path

ATOL = 1e-10


@dataclass
class EventCandidateResult:
    path: tuple
    J: float
    Pd: float
    status: str
    stop_reason: str | None
    wall_s: float
    incumbent_source: str
    candidate_archive: list = field(default_factory=list)
    incumbent_history: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    theory_certified: bool = False


class _Deadline(Exception):
    pass


def _distance(grid, left, right):
    r1, c1 = divmod(int(left), grid.cols)
    r2, c2 = divmod(int(right), grid.cols)
    return abs(r1-r2) + abs(c1-c2)


def _reachable(grid, left, right, steps):
    distance = _distance(grid, left, right)
    return (steps >= distance and (steps-distance) % 2 == 0
            and (steps == 0 or grid.size > 1))


def _validate_events(grid, start, budget, sequence):
    events = tuple(tuple(event) for event in sequence)
    if not 1 <= len(events) <= 2:
        raise ValueError("each event sequence must contain one or two events")
    previous, previous_t = start, 0
    checked = []
    for event in events:
        if len(event) != 2:
            raise ValueError("events must be (vertex, absolute_step) pairs")
        vertex, step = event
        grid.coordinates(vertex)
        vertex = int(vertex)
        step = integer(step, "event step", 1)
        if step > budget or step <= previous_t:
            raise ValueError("event times must increase strictly within 1..T")
        if not _reachable(grid, previous, vertex, step-previous_t):
            raise ValueError("hard events are not exactly-time reachable")
        checked.append((vertex, step))
        previous, previous_t = vertex, step
    return tuple(checked)


def _fixed_partition(grid, motion, weights, budget, count, check):
    """Weighted deterministic clustering of full-future trajectory features.

    Permanently non-searchable and zero-weight columns do not suggest events.
    Their ID-indexed mass is nevertheless retained in every original replay.
    All assigned columns belong to exactly one proposal cluster.
    """
    check()
    cells = motion.cell_ids[1:budget+1]
    visible = cells < grid.size
    observations = visible.sum(axis=0)
    eligible = np.flatnonzero((observations > 0) & (weights > 0))
    labels = np.full(motion.state_size, -1, dtype=np.intp)
    if not len(eligible):
        return labels, []
    # Mean positions plus the first/last visible positions retain trajectory
    # identity rather than independently reclustering each absolute frame.
    ce = cells[:, eligible]
    ve = visible[:, eligible]
    rr, cc = ce // grid.cols, ce % grid.cols
    obs = observations[eligible]
    first = np.argmax(ve, axis=0)
    last = budget-1-np.argmax(ve[::-1], axis=0)
    columns = np.arange(len(eligible))
    features = np.column_stack((
        np.where(ve, rr, 0).sum(axis=0)/obs,
        np.where(ve, cc, 0).sum(axis=0)/obs,
        rr[first, columns], cc[first, columns],
        rr[last, columns], cc[last, columns])).astype(float)
    spread = np.std(features, axis=0)
    features /= np.where(spread > 0, spread, 1.)
    w = weights[eligible]
    selected = [int(np.argmax(w))]
    while len(selected) < min(count, len(eligible)):
        check()
        dist = np.min(((features[:, None]-features[selected])**2).sum(axis=2), axis=1)
        candidate = int(np.argmax(dist*w))
        if dist[candidate] <= 1e-12:
            break
        selected.append(candidate)
    centers = features[selected].copy()
    assigned = np.zeros(len(eligible), dtype=np.intp)
    for _ in range(8):
        check()
        assigned = np.argmin(((features[:, None]-centers)**2).sum(axis=2), axis=1)
        changed = False
        for cluster in range(len(centers)):
            members = assigned == cluster
            if np.any(members):
                center = np.average(features[members], axis=0, weights=w[members])
                changed |= not np.array_equal(centers[cluster], center)
                centers[cluster] = center
        if not changed:
            break
    records = []
    for old_label in np.unique(assigned):
        members = eligible[assigned == old_label]
        cluster = len(records)
        labels[members] = cluster
        records.append(dict(cluster_id=cluster, particle_columns=members.tolist(),
                            trajectory_ids=motion.trajectory_ids[members].tolist(),
                            initial_mass=float(weights[members].sum())))
    return labels, records


def _events_for_clusters(grid, motion, weights, sensor, start, budget,
                         cluster_records, check):
    """At most 12 per cluster, spread over four fixed time bands.

    The ranking (T-t+1)*q*initial cluster mass is only a proposal rule. It
    neither predicts the attainable route gain nor supplies a lower bound.
    """
    all_events = {}
    r0, c0 = divmod(start, grid.cols)
    vertices = np.arange(grid.size)
    distance = abs(vertices//grid.cols-r0) + abs(vertices % grid.cols-c0)
    for record in cluster_records:
        check()
        members = np.asarray(record["particle_columns"], dtype=np.intp)
        bands = [[] for _ in range(4)]
        for t in range(1, budget+1):
            check()
            mass = np.bincount(motion.cell_ids[t, members], weights=weights[members],
                               minlength=motion.bin_count)[:grid.size]
            allowed = (distance <= t) & ((t-distance) % 2 == 0)
            quality = (budget-t+1)*sensor*mass
            viable = np.flatnonzero(allowed & (quality > 0))
            # Two cells per frame prevents a broad cloud from occupying an
            # entire time band's small event quota at just one instant.
            best = sorted(viable, key=lambda v: (-quality[v], int(v)))[:2]
            band = min(3, 4*(t-1)//max(1, budget))
            for v in best:
                bands[band].append(dict(vertex=int(v), step=t,
                    cluster_id=record["cluster_id"], proposal_score=float(quality[v]),
                    initial_cluster_cell_mass=float(mass[v])))
        kept = []
        for band in bands:
            kept.extend(sorted(band, key=lambda e: (-e["proposal_score"], e["step"], e["vertex"]))[:3])
        all_events[record["cluster_id"]] = kept
    return all_events


def _default_plans(grid, start, budget, events, maximum, check):
    """One hard-event family per ordered cluster pair, then a second time choice.

    Each selected schedule will receive two paid connector styles. Round-robin
    selection across ordered pairs prevents one pair from consuming the cap.
    When no ordered pair is feasible, single-event alternatives remain valid.
    """
    families = []
    for left, right in permutations(sorted(events), 2):
        check()
        feasible = []
        for a in events[left]:
            for b in events[right]:
                if b["step"] <= a["step"]:
                    continue
                if _reachable(grid, a["vertex"], b["vertex"], b["step"]-a["step"]):
                    feasible.append((a, b))
        feasible.sort(key=lambda ab: (-(ab[0]["proposal_score"]+ab[1]["proposal_score"]),
                                     ab[0]["step"], ab[1]["step"],
                                     ab[0]["vertex"], ab[1]["vertex"]))
        if feasible:
            families.append((f"cluster_{left}_then_{right}", feasible[:2]))
    plans = []
    for rank in range(2):
        for family, choices in families:
            if rank < len(choices):
                chosen = choices[rank]
                plans.append(dict(family=family, cluster_order=[e["cluster_id"] for e in chosen],
                    events=tuple((e["vertex"], e["step"]) for e in chosen),
                    event_records=list(chosen)))
                if len(plans) >= maximum:
                    return plans
    # Single-event choices can also change the first visited target cluster,
    # including when two hard events are unreachable within the horizon.
    singles = [(cluster, sorted(es, key=lambda e: (-e["proposal_score"], e["step"], e["vertex"])))
               for cluster, es in sorted(events.items())]
    for rank in range(12):
        for cluster, choices in singles:
            check()
            if rank < len(choices):
                event = choices[rank]
                plans.append(dict(family=f"cluster_{cluster}_single", cluster_order=[cluster],
                    events=((event["vertex"], event["step"]),), event_records=[event]))
                if len(plans) >= maximum:
                    return plans
    return plans


def _construct(grid, *, start, budget, weights, sensor, motion, events, style, check):
    """Greedy/legal connector with hard-event reachability; no reward pruning."""
    route = [start]
    belief = weights.copy()
    event_index = 0
    for t in range(1, budget+1):
        check()
        current = route[-1]
        neighbors = grid.neighbors(current)
        if event_index < len(events):
            target, target_t = events[event_index]
            neighbors = tuple(v for v in neighbors
                              if _reachable(grid, v, target, target_t-t))
        else:
            target, target_t = None, None
        if not neighbors:
            raise AssertionError("validated hard events lost all feasible connectors")
        mass = motion.cell_mass(belief, t)
        rr, cc = divmod(current, grid.cols)

        def order(vertex):
            r, c = divmod(vertex, grid.cols)
            gain = float(sensor[vertex]*mass[vertex])
            # Both styles honor events. Style 0 prioritizes paid one-step
            # gain, then row moves; style 1 prioritizes progress/column moves
            # while bridging, then gain. Neither discards zero-gain routes.
            axis = (0 if r != rr else 1) if style == 0 else (0 if c != cc else 1)
            distance = 0 if target is None else _distance(grid, vertex, target)
            if style == 0 or target is None:
                return (-gain, distance, axis, vertex if style == 0 else -vertex)
            return (distance, axis, -gain, -vertex)

        chosen = min(neighbors, key=order)
        route.append(chosen)
        belief = motion.sense(belief, chosen, sensor, t)
        if target_t == t:
            if chosen != target:
                raise AssertionError("hard event was not visited")
            event_index += 1
    return tuple(route)


def search_event_candidates(grid, *, start, budget, p, q, motion, initial_path,
                            max_seconds=5.0, max_candidates=24, max_clusters=3,
                            event_sequences=None):
    """Return min-J among the paid initial path and at most 24 event proposals.

    ``event_sequences`` optionally supplies sequences of one or two
    ``(vertex, absolute_step)`` pairs for explicit mechanism experiments.
    Each sequence is tried with two deterministic connector styles, subject
    to the shared candidate/time cap. Explicit sequences are not optimized
    or interpreted as an exhaustive search domain.
    """
    begun = perf_counter()
    budget = integer(budget, "budget")
    max_candidates = integer(max_candidates, "max_candidates")
    max_clusters = integer(max_clusters, "max_clusters", 1)
    if max_candidates > 24 or max_clusters > 3:
        raise ValueError("final assessment caps are 24 candidates and 3 clusters")
    if not isinstance(grid, GridGraph) or not isinstance(motion, ParticleMotion):
        raise ValueError("event proposals require GridGraph and ParticleMotion")
    grid.coordinates(start)
    start = int(start)
    if grid.size != motion.size:
        raise ValueError("motion/grid size mismatch")
    motion.check_horizon(budget)
    if not isfinite(max_seconds) or max_seconds < 0:
        raise ValueError("max_seconds must be finite and nonnegative")
    deadline = begun + float(max_seconds)
    weights = initial_belief(p, motion.state_size)
    sensor = sensor_probabilities(q, grid.size)
    initial_path = tuple(initial_path)
    cfg = dict(start=start, budget=budget, p=weights, q=sensor, motion=motion)
    replay_start = perf_counter()
    initial = score_path(grid, initial_path, **cfg)
    replay_s = perf_counter()-replay_start
    best_path, best_J, best_Pd = initial_path, initial.J, initial.pd_final
    source = "initial_path"
    archive, seen, unique_new = [], set(), set()
    history = [dict(path=initial_path, J=best_J, Pd=best_Pd, source=source,
                    elapsed_s=perf_counter()-begun)]
    stats = dict(initial_replays=1, candidate_replays=0, replay_wall_s=replay_s,
                 clustering_wall_s=0., event_generation_wall_s=0., connector_wall_s=0.,
                 complete_candidates=0, unique_complete_candidates=0,
                 unique_new_routes=0, duplicate_candidates=0,
                 equals_initial_candidates=0, accepted_improvements=0,
                 early_divergence_candidates=0, first_divergence_steps=[],
                 max_candidates=max_candidates, max_clusters=max_clusters,
                 cluster_records=[], generated_event_families=[], planned_schedules=0,
                 attempted_candidates=0, abandoned_partial_candidates=0,
                 hard_events_satisfied=True, reset_to_original_p0=True,
                 all_particle_columns_scored=motion.state_size,
                 protected_prefix_length=0, incumbent_corridor_used=False,
                 time_zero_sensing=False, special_mass_retained=True,
                 objective="original min-J; Pd reported independently",
                 cluster_order_scope="hard-event order; actual first detection order is replayed separately",
                 candidate_count_scope="complete proposals including duplicates; initial route excluded",
                 scope="finite root-released event candidates; no optimality certificate",
                 timing_scope="validation, initial replay, clustering, events, connectors and all replays",
                 early_divergence_threshold=max(1, budget//3))
    reason = None

    def check():
        if perf_counter() >= deadline:
            raise _Deadline()

    try:
        check()
        if budget == 0 or max_candidates == 0:
            plans = []
        elif event_sequences is not None:
            plans = []
            for index, sequence in enumerate(event_sequences):
                check()
                if len(plans) >= (max_candidates+1)//2:
                    break
                events = _validate_events(grid, start, budget, sequence)
                plans.append(dict(family=f"explicit_{index}", cluster_order=None,
                                  events=events, event_records=[]))
        else:
            tic = perf_counter()
            try:
                labels, records = _fixed_partition(grid, motion, weights, budget, max_clusters, check)
            finally:
                stats["clustering_wall_s"] = perf_counter()-tic
            stats["cluster_records"] = records
            stats["unassigned_proposal_columns"] = np.flatnonzero(labels < 0).tolist()
            tic = perf_counter()
            try:
                cluster_events = _events_for_clusters(grid, motion, weights, sensor,
                                                      start, budget, records, check)
                stats["cluster_events"] = cluster_events
                plans = _default_plans(grid, start, budget, cluster_events,
                                       (max_candidates+1)//2, check)
            finally:
                stats["event_generation_wall_s"] = perf_counter()-tic
        stats["planned_schedules"] = len(plans)
        stats["generated_event_families"] = sorted({p["family"] for p in plans})
        for plan in plans:
            for style in (0, 1):
                if len(archive) >= max_candidates:
                    break
                check()
                stats["attempted_candidates"] += 1
                tic = perf_counter()
                try:
                    route = _construct(grid, start=start, budget=budget, weights=weights,
                                       sensor=sensor, motion=motion, events=plan["events"],
                                       style=style, check=check)
                except _Deadline:
                    stats["connector_wall_s"] += perf_counter()-tic
                    stats["abandoned_partial_candidates"] += 1
                    raise
                stats["connector_wall_s"] += perf_counter()-tic
                # A just-completed route is replayed atomically, including if
                # its final connector crosses the cooperative deadline.
                tic = perf_counter()
                scored = score_path(grid, route, record_beliefs=True, **cfg)
                actual_detections = []
                for cluster in stats["cluster_records"]:
                    members = cluster["particle_columns"]
                    remaining = scored.beliefs[:, members].sum(axis=1)
                    detected = -np.diff(remaining)
                    hits = np.flatnonzero(detected > ATOL)
                    actual_detections.append(dict(cluster_id=cluster["cluster_id"],
                        first_detection_step=int(hits[0]+1) if len(hits) else None,
                        detected_mass=float(remaining[0]-remaining[-1])))
                stats["replay_wall_s"] += perf_counter()-tic
                stats["candidate_replays"] += 1
                first = next((t for t, (a, b) in enumerate(zip(route, initial_path)) if a != b), None)
                duplicate = route in seen
                same_initial = route == initial_path
                satisfied = all(route[t] == v for v, t in plan["events"])
                if not satisfied:
                    raise AssertionError("independent candidate replay violates hard events")
                record = dict(candidate_index=len(archive), family=plan["family"],
                    cluster_order=plan["cluster_order"], events=plan["events"],
                    connector_style=style, path=route, J=scored.J, Pd=scored.pd_final,
                    hard_events_satisfied=satisfied, duplicate_of_prior_candidate=duplicate,
                    equals_initial_path=same_initial, first_divergence=first,
                    actual_cluster_detections=actual_detections,
                    elapsed_s=perf_counter()-begun, accepted=False)
                seen.add(route)
                if not same_initial:
                    unique_new.add(route)
                if scored.J < best_J-ATOL:
                    best_path, best_J, best_Pd = route, scored.J, scored.pd_final
                    source = "root_event_candidate"
                    record["accepted"] = True
                    stats["accepted_improvements"] += 1
                    history.append(dict(path=route, J=best_J, Pd=best_Pd, source=source,
                                        candidate_index=len(archive), elapsed_s=perf_counter()-begun))
                archive.append(record)
                check()
    except _Deadline:
        reason = "max_seconds"
    wall = perf_counter()-begun
    stats.update(complete_candidates=len(archive), unique_complete_candidates=len(seen),
                 unique_new_routes=len(unique_new),
                 duplicate_candidates=sum(a["duplicate_of_prior_candidate"] for a in archive),
                 equals_initial_candidates=sum(a["equals_initial_path"] for a in archive),
                 early_divergence_candidates=sum(a["first_divergence"] is not None and
                     a["first_divergence"] <= stats["early_divergence_threshold"] for a in archive),
                 first_divergence_steps=[a["first_divergence"] for a in archive],
                 duplicate_fraction=(len(archive)-len(seen))/len(archive) if archive else None,
                 deadline_overshoot_s=max(0., wall-max_seconds),
                 proposal_domain_exhausted=reason is None,
                 global_search_complete=False)
    return EventCandidateResult(best_path, best_J, best_Pd,
                                "budget_exceeded" if reason else "completed", reason,
                                wall, source, archive, history, stats)
