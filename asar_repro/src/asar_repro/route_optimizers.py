"""Full-horizon route experiments, independent of the A* / STDC ordering.

No routine in this module runs at import time.  All objective values are obtained
from the unchanged ``score_path``.  The constructor's forecast score is only a
proposal rule: it is never an objective value, pruning bound, or certificate.

This research implementation is supplied for local validation; see the protocol
for the required correctness gate before timed experiments.
"""

from dataclasses import dataclass
from hashlib import sha256
from math import ceil, exp, isfinite
from time import perf_counter

import numpy as np

from .belief import initial_belief, sensor_probabilities
from .grid import GridGraph, integer
from .objective import score_path


ATOL = 1e-10
ILS_DEFAULTS = dict(
    max_evaluations=None, max_iterations=None, polish_trials=2,
    exploration_probability=0.15, temperature_fraction=0.03,
    temperature_final_ratio=0.05, stagnation_restart=12,
    early_prefix_fraction=0.25, anchor_count=3,
    forecast_offsets=[4, 12, 24], trace_limit=2000,
)
CEM_DEFAULTS = dict(
    max_evaluations=None, max_generations=None, population=48, components=2,
    elite_fraction=0.15, learning_rate=0.7, exploration_probability=0.1,
    initial_path_bias=0.65, trace_limit=2000,
)


class _Deadline(Exception):
    """Cooperative interruption; an incomplete route is never scored."""


def _check_deadline(deadline):
    if perf_counter() >= deadline:
        raise _Deadline


def _settings(defaults, supplied):
    settings = dict(defaults)
    if supplied is not None:
        unknown = set(supplied) - set(defaults)
        if unknown:
            raise ValueError(f"unknown options: {sorted(unknown)}")
        settings.update(supplied)
    for key in ("max_evaluations", "max_iterations", "max_generations"):
        if key in settings and settings[key] is not None:
            settings[key] = integer(settings[key], key, 1)
    for key in ("polish_trials", "trace_limit"):
        if key in settings:
            settings[key] = integer(settings[key], key)
    for key in ("population", "components", "stagnation_restart", "anchor_count"):
        if key in settings:
            settings[key] = integer(settings[key], key, 1)
    for key in ("exploration_probability", "temperature_fraction",
                "temperature_final_ratio", "early_prefix_fraction",
                "elite_fraction", "learning_rate", "initial_path_bias"):
        if key in settings:
            value = float(settings[key])
            if not isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{key} must be a finite number in [0, 1]")
            settings[key] = value
    for key in ("temperature_final_ratio", "elite_fraction", "learning_rate"):
        if key in settings and settings[key] == 0:
            raise ValueError(f"{key} must be positive")
    if "forecast_offsets" in settings:
        settings["forecast_offsets"] = sorted({
            integer(v, "forecast offset", 1) for v in settings["forecast_offsets"]
        })
        if not settings["forecast_offsets"]:
            raise ValueError("forecast_offsets must not be empty")
    if "components" in settings and settings["population"] < settings["components"]:
        raise ValueError("population must provide at least one sample per component")
    if "components" in settings and settings["exploration_probability"] <= 0:
        raise ValueError("CEM requires a positive exploration probability floor")
    return settings


def _limited(value, limit):
    return limit is not None and value >= limit


def _route_digest(path):
    # Explicit endian gives the same identifier across platforms.
    return sha256(np.asarray(path, dtype="<i8").tobytes()).digest()


@dataclass
class _Evaluation:
    path: tuple
    J: float
    pd_final: float
    survival: list
    elapsed_s: float
    route_hash: str
    trace: dict | None


class _Problem:
    def __init__(self, grid, start, budget, p, q, motion):
        if not isinstance(grid, GridGraph):
            raise ValueError("route optimizers require the rectangular GridGraph")
        self.grid = grid
        self.start = integer(start, "start")
        self.budget = integer(budget, "budget")
        grid.coordinates(self.start)
        if motion.size != grid.size:
            raise ValueError("motion and grid size differ")
        self.p = initial_belief(p, motion.state_size)
        self.sensor = sensor_probabilities(q, grid.size)
        self.motion = motion
        if hasattr(motion, "check_horizon"):
            motion.check_horizon(self.budget)
        if self.budget and not grid.neighbors(self.start):
            raise ValueError("no legal move exists for a positive horizon")
        self.cfg = dict(start=self.start, budget=self.budget, p=self.p,
                        q=self.sensor, motion=motion)
        ids = np.arange(grid.size)
        self.rows = ids // grid.cols
        self.cols = ids % grid.cols

    def distance(self, vertex, target):
        r, c = divmod(vertex, self.grid.cols)
        tr, tc = divmod(target, self.grid.cols)
        return abs(r - tr) + abs(c - tc)

    def prefix_belief(self, prefix, deadline):
        belief = self.p.copy()
        for step, vertex in enumerate(prefix[1:], 1):
            _check_deadline(deadline)
            prior = self.motion.propagate(belief, step=step)
            belief = self.motion.sense(prior, vertex, self.sensor, step)
        return belief


class _Recorder:
    def __init__(self, problem, initial_path, started, deadline, settings, method):
        self.problem = problem
        self.initial_path = tuple(initial_path)
        problem.grid.validate_path(self.initial_path, start=problem.start,
                                   budget=problem.budget)
        self.started, self.deadline = started, deadline
        self.settings, self.method = settings, method
        self.best = None
        self.history = []
        self.candidate_trace = []
        self.late_candidates = []
        self.seen = set()
        self.lineages = []
        self.stats = dict(
            objective_calls=0, scored_in_budget=0, completed_after_deadline=0,
            unique_routes=0, duplicate_routes=0, strict_improvements=0,
            trace_dropped=0, deadline_interruptions_outside_scoring=0, first_divergence_counts={},
            source_counts={},
            objective_wall_s=0.0, construction_wall_s=0.0,
            unique_definition="SHA256 of complete little-endian int64 route",
            guide_used_for_pruning=False, global_optimality_certified=False,
        )

    def at_evaluation_limit(self):
        return _limited(self.stats["objective_calls"], self.settings["max_evaluations"])

    def mark_lineage(self, lineage):
        while lineage is not None:
            entry = self.lineages[lineage]
            entry["led_to_best"] = True
            lineage = entry["parent"]

    def register_lineage(self, evaluation, parent, before_j, iteration, forced):
        entry = dict(
            id=len(self.lineages), parent=parent, iteration=iteration,
            elapsed_s=evaluation.elapsed_s, J=evaluation.J, previous_current_J=before_j,
            route_hash=evaluation.route_hash, forced_restart=bool(forced),
            led_to_best=False,
        )
        self.lineages.append(entry)
        return entry["id"]

    def evaluate(self, path, source, lineage=None):
        if self.at_evaluation_limit():
            return None
        _check_deadline(self.deadline)
        tic = perf_counter()
        replay = score_path(self.problem.grid, path, **self.problem.cfg)
        finished = perf_counter()
        self.stats["objective_calls"] += 1
        self.stats["objective_wall_s"] += finished - tic
        elapsed = finished - self.started
        if finished > self.deadline:
            self.stats["completed_after_deadline"] += 1
            self.late_candidates.append(dict(
                path=list(path), J=replay.J, pd_final=replay.pd_final,
                elapsed_s=elapsed, source=source, excluded_from_best=True,
            ))
            raise _Deadline
        if not isfinite(replay.J) or not isfinite(replay.pd_final):
            raise AssertionError("the original scorer returned a nonfinite score")
        route = tuple(int(v) for v in path)
        digest = _route_digest(route)
        unique = digest not in self.seen
        self.seen.add(digest)
        self.stats["scored_in_budget"] += 1
        self.stats["unique_routes"] += int(unique)
        self.stats["duplicate_routes"] += int(not unique)
        divergence = next((t for t, (a, b) in enumerate(zip(route, self.initial_path))
                           if a != b), None)
        key = "same_as_initial" if divergence is None else str(divergence)
        histogram = self.stats["first_divergence_counts"]
        histogram[key] = histogram.get(key, 0) + 1
        previous_best_hash = None if self.best is None else self.best.route_hash
        same_as_best = previous_best_hash == digest.hex()
        counts = self.stats["source_counts"].setdefault(
            source, dict(scored=0, globally_new_routes=0, same_as_best_before=0))
        counts["scored"] += 1
        counts["globally_new_routes"] += int(unique)
        counts["same_as_best_before"] += int(same_as_best)
        trace = dict(
            evaluation=self.stats["objective_calls"], elapsed_s=elapsed,
            J=replay.J, pd_final=replay.pd_final, source=source,
            route_hash=digest.hex(), unique=unique, first_divergence=divergence,
            worse_lineage=lineage, best_hash_before=previous_best_hash,
            same_as_best_before=bool(same_as_best),
        )
        if len(self.candidate_trace) < self.settings["trace_limit"]:
            self.candidate_trace.append(trace)
        else:
            self.stats["trace_dropped"] += 1
            trace = None
        evaluation = _Evaluation(route, replay.J, replay.pd_final,
                                 replay.survival.tolist(), elapsed, digest.hex(), trace)
        if self.best is None or evaluation.J < self.best.J - ATOL:
            if self.best is not None:
                self.stats["strict_improvements"] += 1
            self.best = evaluation
            self.mark_lineage(lineage)
            # Best history is never subject to trace_limit.
            self.history.append(dict(
                path=list(route), J=evaluation.J, Pd=evaluation.pd_final,
                pd_final=evaluation.pd_final, elapsed_s=elapsed, source=source,
                worse_lineage=lineage, route_hash=evaluation.route_hash,
            ))
        return evaluation

    def finish(self, stop_reason, **extra):
        elapsed = perf_counter() - self.started
        best = self.best
        return dict(
            method=self.method,
            status="budget_exceeded" if stop_reason == "max_seconds" else "completed",
            stop_reason=stop_reason, elapsed_s=elapsed,
            path=None if best is None else list(best.path),
            J=None if best is None else best.J,
            pd_final=None if best is None else best.pd_final,
            survival=None if best is None else best.survival,
            history=self.history, candidate_trace=self.candidate_trace,
            late_candidates=self.late_candidates, settings=self.settings,
            stats=dict(self.stats, **extra), worse_acceptance_lineages=self.lineages,
            global_optimality_certified=False,
        )


def _sample_future_goal(problem, belief, depth, vertex, rng, offsets, deadline):
    """Sample a reachable forecast cell; this is guidance, not a bound."""
    remaining = problem.budget - depth
    steps = sorted({min(remaining, h) for h in offsets} | {remaining})
    row, col = divmod(vertex, problem.grid.cols)
    distances = abs(problem.rows - row) + abs(problem.cols - col)
    targets, times, weights = [], [], []
    predicted, previous_time = belief, depth
    for h in steps:
        _check_deadline(deadline)
        future = depth + h
        for absolute in range(previous_time + 1, future + 1):
            predicted = problem.motion.propagate(predicted, step=absolute)
        previous_time = future
        mass = problem.motion.cell_mass(predicted, future)[:problem.grid.size]
        values = mass * problem.sensor
        reachable = (distances <= h) & ((h - distances) % 2 == 0) & (values > 0)
        cells = np.flatnonzero(reachable)
        if len(cells):
            weight = values[cells] * (problem.budget - future + 1) / (1 + distances[cells])
            targets.extend(cells.tolist())
            times.extend([future] * len(cells))
            weights.extend(weight.tolist())
    total = sum(weights)
    if not weights or total <= 0:
        return None, problem.budget
    index = int(rng.choice(len(targets), p=np.asarray(weights) / total))
    return targets[index], times[index]


def _construct(problem, prefix, anchors, rng, settings, deadline):
    """Reconnect geometric anchors with free arrival times and a free endpoint."""
    path = list(prefix)
    belief = problem.prefix_belief(path, deadline)
    pending = list(anchors)
    goal, expires = None, -1
    while len(path) <= problem.budget:
        _check_deadline(deadline)
        depth, vertex = len(path) - 1, path[-1]
        while pending and pending[0] == vertex:
            pending.pop(0)
        if pending:
            goal, expires = pending[0], problem.budget
        elif goal is None or goal == vertex or depth >= expires:
            goal, expires = _sample_future_goal(
                problem, belief, depth, vertex, rng, settings["forecast_offsets"], deadline)
        adjacent = problem.grid.neighbors(vertex)
        choices = adjacent
        if goal is not None and rng.random() >= settings["exploration_probability"]:
            current_distance = problem.distance(vertex, goal)
            closer = tuple(v for v in adjacent if problem.distance(v, goal) < current_distance)
            if closer:
                choices = closer
        prior = problem.motion.propagate(belief, step=depth + 1)
        mass = problem.motion.cell_mass(prior, depth + 1)
        gain = np.asarray([problem.sensor[v] * mass[v] for v in choices])
        scale = float(gain.max(initial=0.0))
        probabilities = (gain / scale + 0.1) ** 2 if scale > 0 else np.ones(len(choices))
        probabilities /= probabilities.sum()
        chosen = int(rng.choice(choices, p=probabilities))
        path.append(chosen)
        belief = problem.motion.sense(prior, chosen, problem.sensor, depth + 1)
    return tuple(path)


def _make_ils_proposal(problem, current, rng, operator, settings, deadline):
    horizon = problem.budget
    if operator == "early_rebuild" and horizon > 1:
        maximum = max(1, min(horizon - 1, int(horizon * settings["early_prefix_fraction"])))
        cut = int(rng.integers(1, maximum + 1))
        return _construct(problem, current[:cut + 1], [], rng, settings, deadline)
    if operator == "reorder_waypoints" and horizon > 1:
        count = min(settings["anchor_count"], horizon)
        indices = np.sort(rng.choice(np.arange(1, horizon + 1), size=count, replace=False))
        anchors = list(dict.fromkeys(current[int(i)] for i in indices))
        if len(anchors) > 1:
            original = list(anchors)
            rng.shuffle(anchors)
            if anchors == original:
                anchors = anchors[1:] + anchors[:1]
            if len(anchors) > 2 and rng.random() < 0.25:
                del anchors[int(rng.integers(len(anchors)))]
        return _construct(problem, [problem.start], anchors, rng, settings, deadline)
    return _construct(problem, [problem.start], [], rng, settings, deadline)


def _new_run(grid, start, budget, p, q, motion, initial_path, max_seconds,
             seed, options, defaults, method):
    started = perf_counter()
    seconds = float(max_seconds)
    if isinstance(max_seconds, bool) or not isfinite(seconds) or seconds < 0:
        raise ValueError("max_seconds must be finite and nonnegative")
    settings = _settings(defaults, options)
    seed = integer(seed, "seed")
    problem = _Problem(grid, start, budget, p, q, motion)
    recorder = _Recorder(problem, initial_path, started, started + seconds,
                         settings, method)
    return problem, recorder, np.random.default_rng(seed)


def solve_ils(grid, *, start, budget, p, q, motion, initial_path,
              max_seconds, seed, options=None):
    """Iterated full-route reconstruction with an explicit worse-state chain.

    The fixed operator cycle is root_restart / early_rebuild / reorder_waypoints.
    The latter samples geometric anchors, changes their order, and reconnects
    them without preserving old timestamps or the old endpoint.  Every proposal
    gets at most polish_trials free-end suffix reconstructions before acceptance.
    A forced root restart after stagnation is a new current state, never a reset
    of the best route.  ``max_evaluations`` includes the initial replay.
    """
    problem, recorder, rng = _new_run(
        grid, start, budget, p, q, motion, initial_path, max_seconds,
        seed, options, ILS_DEFAULTS, "ils")
    settings = recorder.settings
    iteration = stagnation = 0
    lineage = None
    accepted = worse = forced_restarts = 0
    operator_counts = {name: 0 for name in ("root_restart", "early_rebuild", "reorder_waypoints")}
    polished_trials = 0
    stop_reason = "max_seconds"
    try:
        current = recorder.evaluate(initial_path, "initial_path")
        if problem.budget == 0:
            return recorder.finish("zero_horizon", iterations=0)
        while True:
            _check_deadline(recorder.deadline)
            if recorder.at_evaluation_limit():
                stop_reason = "max_evaluations"
                break
            if _limited(iteration, settings["max_iterations"]):
                stop_reason = "max_iterations"
                break
            iteration += 1
            forced = stagnation >= settings["stagnation_restart"]
            names = tuple(operator_counts)
            operator = "root_restart" if forced else names[(iteration - 1) % len(names)]
            operator_counts[operator] += 1
            candidate_lineage = None if operator == "root_restart" else lineage
            previous_best = recorder.best.J
            tic = perf_counter()
            route = _make_ils_proposal(problem, current.path, rng, operator,
                                       settings, recorder.deadline)
            recorder.stats["construction_wall_s"] += perf_counter() - tic
            candidate = recorder.evaluate(route, operator, candidate_lineage)
            if candidate is None:
                stop_reason = "max_evaluations"
                break
            if candidate.trace is not None:
                candidate.trace.update(iteration=iteration, stage="proposal",
                                       current_hash_before=current.route_hash,
                                       same_as_current=candidate.path == current.path)
            for _ in range(settings["polish_trials"]):
                if recorder.at_evaluation_limit():
                    break
                _check_deadline(recorder.deadline)
                cut = int(rng.integers(1, problem.budget)) if problem.budget > 1 else 0
                tic = perf_counter()
                route = _construct(problem, candidate.path[:cut + 1], [], rng,
                                   settings, recorder.deadline)
                recorder.stats["construction_wall_s"] += perf_counter() - tic
                polished = recorder.evaluate(route, "polish_suffix", candidate_lineage)
                polished_trials += 1
                if polished is not None and polished.trace is not None:
                    polished.trace.update(iteration=iteration, stage="polish",
                                          parent_hash=candidate.route_hash,
                                          same_as_parent=polished.path == candidate.path,
                                          current_hash_before=current.route_hash,
                                          same_as_current=polished.path == current.path)
                if polished is not None and polished.J < candidate.J - ATOL:
                    candidate = polished
            progress = min(1.0, (perf_counter() - recorder.started) / max(float(max_seconds), 1e-300))
            if settings["max_iterations"] is not None:
                progress = max(progress, iteration / settings["max_iterations"])
            temperature = (settings["temperature_fraction"] * max(1.0, recorder.history[0]["J"])
                           * settings["temperature_final_ratio"] ** progress)
            delta = candidate.J - current.J
            accept = forced or delta <= ATOL or (temperature > 0 and rng.random() < exp(-delta / temperature))
            if candidate.trace is not None:
                candidate.trace.update(current_accepted=bool(accept), forced_restart=forced,
                                       current_J_before=current.J)
            if accept:
                accepted += 1
                forced_restarts += int(forced)
                lineage = candidate_lineage
                if delta > ATOL:
                    worse += 1
                    lineage = recorder.register_lineage(candidate, lineage, current.J, iteration, forced)
                current = candidate
            if recorder.best.J < previous_best - ATOL or forced:
                stagnation = 0
            else:
                stagnation += 1
    except _Deadline:
        recorder.stats["deadline_interruptions_outside_scoring"] += int(
            not recorder.late_candidates and perf_counter() >= recorder.deadline)
    return recorder.finish(
        stop_reason, iterations=iteration, operator_counts=operator_counts,
        polish_trials=polished_trials, current_acceptances=accepted,
        accepted_worse=worse, forced_restarts=forced_restarts,
        worse_lineages_with_best=sum(int(row["led_to_best"]) for row in recorder.lineages),
        lineage_interpretation="observed proposal ancestry, not a counterfactual causal effect",
    )


_DELTAS = ((-1, 0), (0, -1), (0, 1), (1, 0))


def _actions_for_path(grid, path):
    actions = []
    for source, target in zip(path, path[1:]):
        r, c = divmod(source, grid.cols)
        nr, nc = divmod(target, grid.cols)
        actions.append(_DELTAS.index((nr - r, nc - c)))
    return np.asarray(actions, dtype=np.intp)


def _sample_cem_path(problem, policy, rng, deadline):
    path, actions = [problem.start], []
    for t in range(problem.budget):
        _check_deadline(deadline)
        r, c = divmod(path[-1], problem.grid.cols)
        legal = [a for a, (dr, dc) in enumerate(_DELTAS)
                 if 0 <= r + dr < problem.grid.rows and 0 <= c + dc < problem.grid.cols]
        probabilities = policy[t, legal]
        probabilities = probabilities / probabilities.sum()
        action = int(rng.choice(legal, p=probabilities))
        dr, dc = _DELTAS[action]
        path.append((r + dr) * problem.grid.cols + c + dc)
        actions.append(action)
    return tuple(path), np.asarray(actions, dtype=np.intp)


def solve_cem(grid, *, start, budget, p, q, motion, initial_path,
              max_seconds, seed, options=None):
    """Full-T legal sequential cross-entropy sampling with separate components.

    ``population`` is the total per generation, not the per-component size.
    Samples alternate components; each component fits its own elites.  Only the
    first component starts biased toward the common initial path; others start
    uniform.  Probability flooring is retained after every update.  No partial
    horizon is concatenated and no invalid path receives a penalty objective.
    """
    problem, recorder, rng = _new_run(
        grid, start, budget, p, q, motion, initial_path, max_seconds,
        seed, options, CEM_DEFAULTS, "cem")
    settings = recorder.settings
    generations = samples = updates = 0
    stop_reason = "max_seconds"
    try:
        recorder.evaluate(initial_path, "initial_path")
        if problem.budget == 0:
            return recorder.finish("zero_horizon", generations=0)
        count = settings["components"]
        policies = np.full((count, problem.budget, 4), 0.25)
        actions = _actions_for_path(grid, initial_path)
        bias = settings["initial_path_bias"]
        policies[0] *= 1 - bias
        policies[0, np.arange(problem.budget), actions] += bias
        floor = settings["exploration_probability"]
        policies = (1 - floor) * policies + floor / 4
        while True:
            _check_deadline(recorder.deadline)
            if recorder.at_evaluation_limit():
                stop_reason = "max_evaluations"
                break
            if _limited(generations, settings["max_generations"]):
                stop_reason = "max_generations"
                break
            population = [[] for _ in range(count)]
            complete_generation = True
            for sample in range(settings["population"]):
                if recorder.at_evaluation_limit():
                    complete_generation = False
                    stop_reason = "max_evaluations"
                    break
                component = sample % count
                tic = perf_counter()
                path, sequence = _sample_cem_path(problem, policies[component], rng, recorder.deadline)
                recorder.stats["construction_wall_s"] += perf_counter() - tic
                evaluation = recorder.evaluate(path, f"cem_component_{component}")
                samples += 1
                population[component].append((evaluation.J, sequence))
            if not complete_generation:
                break
            _check_deadline(recorder.deadline)
            for component, entries in enumerate(population):
                entries.sort(key=lambda item: item[0])
                elite_count = max(1, ceil(settings["elite_fraction"] * len(entries)))
                frequencies = np.zeros((problem.budget, 4))
                for _, sequence in entries[:elite_count]:
                    frequencies[np.arange(problem.budget), sequence] += 1 / elite_count
                rate = settings["learning_rate"]
                updated = (1 - rate) * policies[component] + rate * frequencies
                policies[component] = (1 - floor) * updated + floor / 4
                updates += 1
            generations += 1
    except _Deadline:
        recorder.stats["deadline_interruptions_outside_scoring"] += int(
            not recorder.late_candidates and perf_counter() >= recorder.deadline)
    return recorder.finish(
        stop_reason, generations_completed=generations, samples_scored=samples,
        component_updates=updates, population_is_total=True,
        action_order=["north", "west", "east", "south"],
    )
