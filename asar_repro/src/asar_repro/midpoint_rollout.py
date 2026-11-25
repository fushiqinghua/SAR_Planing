"""Uncertified, diverse beam suffix proposals from detection-event anchors.

Every anchor fixes an incumbent prefix at its original absolute time, then
regrows the entire remaining suffix with a free endpoint. Anchors advance one
layer per round in deterministic round-robin order. A separate admissible
bound may prune, while the paper guide and diversity keys only select beam
proposals. Beam losses are reported separately from safe pruning.

All accepted/final paths use the unchanged full-route scorer and min-J goal.
Compression requires an exactly matching original replay model. Neither
completion nor a wide beam creates a global epsilon certificate.
"""

from collections import deque
from dataclasses import dataclass, field
from itertools import count
from math import inf, isfinite
from time import perf_counter

import numpy as np

from .belief import sensor_probabilities
from .grid import integer
from .heuristic import Heuristic
from .motion import MatrixMotion, ParticleMotion
from .objective import score_path
from .research_particle import FutureEquivalentMotion, ParticleGuide


ATOL = 1e-10


@dataclass
class MidpointResult:
    path: tuple
    J: float
    Pd: float
    expanded: int
    generated: int
    pruned: int
    peak_open: int
    status: str
    stop_reason: str | None
    incumbent_source: str
    bound_mode: str
    guide_weight: float
    theory_certified: bool = False
    incumbent_history: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    anchors: list = field(default_factory=list)
    candidate_archive: list = field(default_factory=list)
    wall_s: float = 0.0
    completion_reason: str | None = None

    @property
    def history(self):
        return self.incumbent_history


@dataclass
class _Node:
    path: tuple
    belief: np.ndarray
    g: float
    lower: float
    priority: float
    sequence: int
    last_hit_vertex: int
    last_hit_depth: int
    direction: int

    @property
    def depth(self):
        return len(self.path)-1


class _FutureDetectable:
    """Geometry/motion eligibility for a diversity representative only.

    A particle is eligible iff at some future absolute frame it occupies a
    positive-q searchable cell exactly reachable from the current vertex.
    Permanent special-bin columns are excluded from the KEY, never from belief
    or scoring. Matrix states use positive transition support backwards from
    the same future searchable sets. No key merges or prunes a search state.
    """

    def __init__(self, grid, *, budget, q, motion):
        self.grid, self.budget, self.motion = grid, budget, motion
        self.q = sensor_probabilities(q, grid.size).copy()
        self.cache, self.distances = {}, {}

    def eligible(self, vertex, depth):
        key = (vertex, depth)
        if key in self.cache:
            return self.cache[key]
        if vertex not in self.distances:
            self.distances[vertex] = self.grid.distances_from(vertex)
        distances = self.distances[vertex]
        if depth == self.budget or self.grid.size == 1:
            mask = np.zeros(self.motion.state_size, dtype=bool)
        elif isinstance(self.motion, ParticleMotion):
            cells = self.motion.cell_ids[depth+1:self.budget+1]
            searchable = cells < self.grid.size
            safe_cells = np.minimum(cells, self.grid.size-1)
            distance = distances[safe_cells]
            steps = np.arange(1, len(cells)+1)[:, None]
            mask = np.any(searchable & (self.q[safe_cells] > 0)
                          & (distance <= steps) & ((steps-distance) % 2 == 0), axis=0)
        elif isinstance(self.motion, MatrixMotion):
            mask = np.zeros(self.grid.size, dtype=bool)
            for t in range(self.budget, depth, -1):
                k = t-depth
                future_cell = (self.q > 0) & (distances <= k) & ((k-distances) % 2 == 0)
                kernel = self.motion._matrices[0 if self.motion._repeat else t-1]
                mask = np.asarray(kernel @ (future_cell | mask).astype(float)).ravel() > 0
        else:
            raise ValueError("diversity requires MatrixMotion or ParticleMotion")
        mask.setflags(write=False)
        self.cache[key] = mask
        return mask

    def representative(self, vertex, depth, belief):
        eligible = self.eligible(vertex, depth) & (belief > 0)
        if not np.any(eligible):
            return -1
        return int(np.argmax(np.where(eligible, belief, -1.0)))

    def signatures(self, node):
        representative = self.representative(node.path[-1], node.depth, node.belief)
        primary = (representative, node.last_hit_vertex)
        secondary = primary + (node.direction, min(4, node.depth-node.last_hit_depth))
        return primary, secondary


def _direction(grid, previous, vertex):
    r0, c0 = grid.coordinates(previous)
    r1, c1 = grid.coordinates(vertex)
    return {(-1, 0): 0, (0, 1): 1, (1, 0): 2, (0, -1): 3}[(r1-r0, c1-c0)]


def _choose_anchors(initial, horizon, anchor_depths):
    if anchor_depths is not None:
        depths = tuple(integer(a, "anchor depth") for a in anchor_depths)
        if not depths or len(set(depths)) != len(depths) or any(a > horizon for a in depths):
            raise ValueError("anchor_depths must be nonempty, unique, and within [0,T]")
        return depths, [dict(a=a, policy="explicit") for a in depths]
    # The final detected mass is observed under the initial route, not inferred
    # from a particular real scenario. Record every selected event/threshold.
    detected = np.maximum(0.0, initial.survival[0]-initial.survival)
    final_detected = float(detected[-1])
    if horizon == 0 or final_detected <= ATOL:
        return (0,), [dict(a=0, policy="zero_detection_or_zero_horizon_fallback")]
    records, depths = [], []
    for fraction in (0.25, 0.5, 0.75):
        event = int(np.searchsorted(detected, fraction*final_detected, side="left"))
        event = min(horizon, max(1, event))
        a = event-1
        records.append(dict(a=a, policy="initial_detected_mass_quantile", fraction=fraction,
                            event_depth=event, threshold=fraction*final_detected,
                            final_detected_mass=final_detected, duplicate=a in depths))
        if a not in depths:
            depths.append(a)
    return tuple(depths), records


def search_midpoint(grid, *, start, budget, p, q, motion, initial_path,
                    bound=None, bound_mode="stdc_lb", guide_weight=1.04,
                    beam_width=24, diversity=True, anchor_depths=None,
                    max_expansions=None, max_seconds=None, max_open=None,
                    replay_cfg=None, trace=None):
    """Return the best original-J route found by scheduled beam proposals.

    `bound(v, absolute_depth, unnormalised_belief)` may supply a validated DP
    or max(STDC,DP) lower bound. Its preparation/seed work must be paid by the
    enclosing experiment; callback time is included here. It must not perform
    unreported search expansions. A missing callback selects zero/mass/STDC.

    beam_width=0 is the documented one-route greedy control (effective width
    one, diversity disabled). All controls otherwise use the same generation,
    original scoring and global budgets. OPEN includes retained anchor
    frontiers AND pending next-layer buffers, including other active anchors.
    """
    started = perf_counter()
    budget = integer(budget, "budget")
    beam_width = integer(beam_width, "beam_width")
    if not isinstance(diversity, bool):
        raise ValueError("diversity must be bool")
    if not isfinite(guide_weight) or guide_weight < 1:
        raise ValueError("guide_weight must be finite and >=1")
    for name, value in (("max_expansions", max_expansions), ("max_open", max_open)):
        if value is not None:
            integer(value, name)
    if max_seconds is not None and (not isfinite(max_seconds) or max_seconds < 0):
        raise ValueError("max_seconds must be finite and nonnegative")
    if bound is None and bound_mode not in ("zero", "mass_lb", "stdc_lb"):
        raise ValueError("without a callback, bound_mode must be zero, mass_lb or stdc_lb")
    if bound is not None and not callable(bound):
        raise ValueError("bound must be callable")
    if bound is not None and hasattr(bound, "validate_compatibility"):
        bound.validate_compatibility(grid, budget=budget, q=q, motion=motion)
    if replay_cfg is not None:
        if (not isinstance(motion, FutureEquivalentMotion)
                or replay_cfg.get("motion") is not motion.original_motion
                or replay_cfg.get("start") != start or replay_cfg.get("budget") != budget
                or not np.array_equal(replay_cfg.get("p"), motion.original_initial_weights)
                or not np.array_equal(p, motion.initial_weights)
                or not np.array_equal(sensor_probabilities(replay_cfg.get("q"), grid.size),
                                      sensor_probabilities(q, grid.size))):
            raise ValueError("alternate replay requires the exact original compressed model")
    elif isinstance(motion, FutureEquivalentMotion):
        raise ValueError("compressed midpoint search requires the exact original replay model")
    cfg = dict(start=start, budget=budget, p=p, q=q, motion=motion)
    scoring = cfg if replay_cfg is None else replay_cfg
    deadline = inf if max_seconds is None else started+max_seconds
    effective_width = max(1, beam_width)
    use_diversity = diversity and beam_width > 1
    stats = dict(initial_replays=0, model_replays=0, candidate_replays=0, final_replays=0,
                 replay_wall_s=0.0, complete_candidates=0, accepted_improvements=0,
                 candidate_replay_error_J_max=0.0, candidate_replay_error_Pd_max=0.0,
                 guide_calls=0, guide_wall_s=0.0, bound_calls=0, bound_wall_s=0.0,
                 beam_discarded=0, diversity_selections_outside_quality_beam=0,
                 diversity_wall_s=0.0, beam_width=beam_width, effective_beam_width=effective_width,
                 diversity=use_diversity, state_merging=False, guide_used_for_pruning=False,
                 guide_used_for_termination=False, bound_is_unweighted=True,
                 endpoint_free=True, seed_search_run=False, objective="sum M[1:T+1]",
                 scheduler="one full layer per active anchor in deterministic round-robin order",
                 budget_scope="shared expansions/time/physical frontier plus next-layer buffers",
                 diversity_key_scope="future-detectable representative and past detection; proposal only")
    stats["candidate_archive_scope"] = "nondominated replayed accepted incumbents only; not a global Pareto frontier"
    expanded = generated = pruned = peak_open = physical_open = 0
    sequence = count()
    history, tasks = [], []
    path = tuple(initial_path)
    original_path = path
    source = "initial_path"

    def timeout():
        return "max_seconds" if perf_counter() >= deadline else None

    def replay(route, kind, *, model=False, record_beliefs=False):
        tic = perf_counter()
        value = score_path(grid, route, **(cfg if model else scoring), record_beliefs=record_beliefs)
        stats[kind+"_replays"] += 1
        stats["replay_wall_s"] += perf_counter()-tic
        return value

    score = replay(path, "initial", record_beliefs=replay_cfg is None)
    initial_model = (score if replay_cfg is None else
                     replay(path, "model", model=True, record_beliefs=True))
    if abs(initial_model.J-score.J) > ATOL or abs(initial_model.pd_final-score.pd_final) > ATOL:
        raise AssertionError("compressed initial route disagrees with original replay")
    starts, anchor_selection = _choose_anchors(score, budget, anchor_depths)
    stats.update(anchor_selection=anchor_selection, anchor_depths=list(starts))
    sensor = sensor_probabilities(q, grid.size)
    guide = ParticleGuide(grid, budget=budget, q=q, motion=motion)
    estimate = bound if bound is not None else Heuristic(grid, budget=budget, q=q, motion=motion, mode=bound_mode)
    keys = _FutureDetectable(grid, budget=budget, q=q, motion=motion)

    def record(event, route, g, **extra):
        if trace is not None:
            trace(dict(event=event, path=tuple(route), vertex=route[-1], depth=len(route)-1,
                       g=g, incumbent_J=score.J, **extra))

    def remember(origin, anchor=None):
        history.append(dict(path=path, J=score.J, Pd=score.pd_final, source=origin,
                            anchor=anchor, expanded=expanded, generated=generated,
                            work_expanded=expanded,
                            elapsed_s=perf_counter()-started))
        record("incumbent", path, score.J, source=origin, anchor=anchor)

    remember(source)

    def materialize(task, route, belief, g, last_hit_vertex, last_hit_depth, direction,
                    *, root=False):
        nonlocal path, score, source, generated, pruned, physical_open, peak_open
        depth = len(route)-1
        if not root:
            generated += 1
            task["generated"] += 1
        if depth == budget:
            stats["complete_candidates"] += 1
            task["complete_candidates"] += 1
            record("candidate", route, g, anchor=task["a"])
            if g < score.J+ATOL:
                candidate = replay(route, "candidate")
                err_j, err_pd = abs(candidate.J-g), abs(candidate.pd_final-(1.0-float(belief.sum())))
                if err_j > ATOL or err_pd > ATOL:
                    raise AssertionError("midpoint candidate disagrees with original full replay")
                stats["candidate_replay_error_J_max"] = max(stats["candidate_replay_error_J_max"], err_j)
                stats["candidate_replay_error_Pd_max"] = max(stats["candidate_replay_error_Pd_max"], err_pd)
                if candidate.J < score.J-ATOL:
                    path, score = tuple(route), candidate
                    source = f"midpoint_anchor[{task['a']}]"
                    stats["accepted_improvements"] += 1
                    task["accepted_improvements"] += 1
                    remember(source, task["a"])
            return timeout()
        if timeout():
            return "max_seconds"
        tic = perf_counter()
        h = float(estimate(route[-1], depth, belief))
        stats["bound_calls"] += 1
        stats["bound_wall_s"] += perf_counter()-tic
        lower = g+h
        if not isfinite(lower) or h < -ATOL:
            raise ValueError("invalid remaining-cost bound")
        if timeout():
            return "max_seconds"
        if lower >= score.J+ATOL:
            pruned += 1
            task["pruned"] += 1
            record("bound_prune", route, g, anchor=task["a"], lower_bound=lower)
            return None
        tic = perf_counter()
        h_guide = float(guide(route[-1], depth, belief))
        stats["guide_calls"] += 1
        stats["guide_wall_s"] += perf_counter()-tic
        priority = g+guide_weight*h_guide
        if not isfinite(priority) or h_guide < -ATOL:
            raise ValueError("invalid paper ordering guide")
        if timeout():
            return "max_seconds"
        if max_open is not None and physical_open >= max_open:
            return "max_open"
        node = _Node(tuple(route), belief, g, lower, priority, next(sequence),
                     last_hit_vertex, last_hit_depth, direction)
        (task["frontier"] if root else task["next"]).append(node)
        physical_open += 1
        peak_open = max(peak_open, physical_open)
        record("push", route, g, anchor=task["a"], lower_bound=lower, f_guide=priority)
        return timeout()

    def select_layer(task):
        nonlocal physical_open, pruned
        candidates = []
        for node in task["next"]:
            if node.lower >= score.J+ATOL:
                physical_open -= 1
                pruned += 1
                task["pruned"] += 1
            else:
                candidates.append(node)
        task["next"] = []
        candidates.sort(key=lambda node: (node.priority, node.sequence))
        if len(candidates) <= effective_width:
            selected = candidates
        elif not use_diversity:
            selected = candidates[:effective_width]
        else:
            tic = perf_counter()
            signatures = {node.sequence: keys.signatures(node) for node in candidates}
            selected = candidates[:max(1, effective_width//2)]
            selected_ids = {node.sequence for node in selected}
            primary_seen = {signatures[node.sequence][0] for node in selected}
            secondary_seen = {signatures[node.sequence][1] for node in selected}
            # First reserve remaining slots for genuinely different eligible
            # belief/detection families; direction alone must not fill them.
            for level, seen in ((0, primary_seen), (1, secondary_seen)):
                for node in candidates:
                    if len(selected) == effective_width:
                        break
                    signature = signatures[node.sequence][level]
                    if node.sequence not in selected_ids and signature not in seen:
                        selected.append(node)
                        selected_ids.add(node.sequence)
                        primary_seen.add(signatures[node.sequence][0])
                        secondary_seen.add(signatures[node.sequence][1])
            for node in candidates:
                if len(selected) == effective_width:
                    break
                if node.sequence not in selected_ids:
                    selected.append(node)
                    selected_ids.add(node.sequence)
            top_ids = {node.sequence for node in candidates[:effective_width]}
            stats["diversity_selections_outside_quality_beam"] += len(selected_ids-top_ids)
            stats["diversity_wall_s"] += perf_counter()-tic
        discarded = len(candidates)-len(selected)
        physical_open -= discarded
        task["beam_discarded"] += discarded
        stats["beam_discarded"] += discarded
        selected.sort(key=lambda node: (node.priority, node.sequence))
        task["frontier"].extend(selected)
        task["layers"] += 1
        task["active"] = bool(task["frontier"])
        if trace is not None:
            trace(dict(event="beam_select", anchor=task["a"], candidate_count=len(candidates),
                       retained_paths=[node.path for node in selected], discarded=discarded))
        return timeout()

    reason = timeout()
    if reason is None and any(a < budget for a in starts) and max_expansions == 0:
        reason = "max_expansions"
    for index, a in enumerate(starts):
        task = dict(index=index, a=a, fixed_prefix=list(original_path[:a+1]),
                    frontier=deque(), next=[], active=False, initialized=False, finished=False,
                    expanded=0, generated=0, pruned=0, beam_discarded=0,
                    complete_candidates=0, accepted_improvements=0, layers=0)
        tasks.append(task)
        if reason:
            continue
        hit_steps = np.flatnonzero(initial_model.delta_pd[:a] > ATOL)+1
        hit_depth = int(hit_steps[-1]) if len(hit_steps) else 0
        hit_vertex = int(original_path[hit_depth]) if len(hit_steps) else -1
        prefix = original_path[:a+1]
        direction = _direction(grid, prefix[-2], prefix[-1]) if a else -1
        task["initialized"] = True
        reason = materialize(task, prefix, initial_model.beliefs[a].copy(),
                             float(initial_model.g[a]), hit_vertex, hit_depth, direction, root=True)
        task["active"] = bool(task["frontier"])
        task["finished"] = reason is None and not task["active"]
    while any(task["active"] for task in tasks) and reason is None:
        for task in tasks:
            if not task["active"]:
                continue
            count_this_layer = len(task["frontier"])
            for _ in range(count_this_layer):
                reason = timeout()
                if reason is None and max_expansions is not None and expanded >= max_expansions:
                    reason = "max_expansions"
                if reason:
                    break
                node = task["frontier"].popleft()
                physical_open -= 1
                if node.lower >= score.J+ATOL:
                    pruned += 1
                    task["pruned"] += 1
                    continue
                expanded += 1
                task["expanded"] += 1
                record("expand", node.path, node.g, anchor=task["a"], lower_bound=node.lower)
                t = node.depth+1
                prior = motion.propagate(node.belief, step=t)
                prior_mass = float(prior.sum())
                for vertex in grid.neighbors(node.path[-1]):
                    detected = motion.sense(prior, vertex, sensor, step=t)
                    remaining_mass = float(detected.sum())
                    hit = prior_mass-remaining_mass > ATOL
                    reason = materialize(task, node.path+(vertex,), detected, node.g+remaining_mass,
                                         vertex if hit else node.last_hit_vertex,
                                         t if hit else node.last_hit_depth,
                                         _direction(grid, node.path[-1], vertex))
                    if reason:
                        break
                if reason:
                    break
            if reason:
                break
            reason = select_layer(task)
            task["finished"] = reason is None and not task["active"]
            if reason:
                break
    final = replay(path, "final")
    if abs(final.J-score.J) > ATOL or abs(final.pd_final-score.pd_final) > ATOL:
        raise AssertionError("final midpoint incumbent replay mismatch")
    reason = reason or timeout()
    wall = perf_counter()-started
    anchor_records = []
    for task in tasks:
        pending = len(task["frontier"])+len(task["next"])
        row = {key: value for key, value in task.items() if key not in ("frontier", "next", "active")}
        row.update(frontier_remaining=pending,
                   status="completed" if task["finished"] else "budget_exceeded",
                   stop_reason=None if task["finished"] else reason)
        anchor_records.append(row)
    stats.update(work_expanded=expanded, physical_frontier_remaining=physical_open,
                 beam_discard=stats["beam_discarded"], proposal_discarded=stats["beam_discarded"],
                 diversity_geometry_entries=len(keys.cache),
                 deadline_overshoot_s=max(0.0, started+wall-deadline))
    archive = []
    for entry in history:
        if any(old["J"] <= entry["J"] and old["Pd"] >= entry["Pd"] for old in archive):
            continue
        archive = [old for old in archive
                   if not (entry["J"] <= old["J"] and entry["Pd"] >= old["Pd"])]
        archive.append(dict(entry))
    return MidpointResult(path, final.J, final.pd_final, expanded, generated, pruned, peak_open,
                          "budget_exceeded" if reason else "completed", reason, source,
                          bound_mode, guide_weight, incumbent_history=history, stats=stats,
                          anchors=anchor_records, candidate_archive=archive, wall_s=wall,
                          completion_reason=None if reason else "scheduled_beam_rollouts_completed")
