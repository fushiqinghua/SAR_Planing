"""Research-only, fixed-time endpoint-preserving route improvement.

The objective/evaluator and global A^SAR remain unchanged. Local completion
certifies neither a globally optimal route nor a global epsilon bound.
"""
from dataclasses import asdict, dataclass, field
from heapq import heappop, heappush
from itertools import count
from math import inf, isfinite
from time import perf_counter

from .belief import sensor_probabilities
from .grid import integer
from .objective import score_path
from .search import search_asar
from .window_bounds import WINDOW_MODES, WindowHeuristic, suffix_coefficients

ATOL = 1e-10


@dataclass
class WindowResult:
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
    theory_certified: bool = False
    seed: dict = field(default_factory=dict)
    windows: list = field(default_factory=list)
    improvements: list = field(default_factory=list)
    wall_s: float = 0.0
    completion_reason: str | None = None
    heuristic_evaluations: int = 0
    complete_candidates: int = 0
    accepted_replays: int = 0
    deadline_overshoot_s: float = 0.0


class _Budget:
    def __init__(self, max_expansions, max_seconds, max_open):
        self.started = perf_counter()
        for name, value in (("max_expansions", max_expansions), ("max_open", max_open)):
            if value is not None:
                integer(value, name)
        if max_seconds is not None and (not isfinite(max_seconds) or max_seconds < 0):
            raise ValueError("max_seconds must be finite and nonnegative")
        self.deadline = inf if max_seconds is None else self.started + max_seconds
        self.cap = max_expansions
        self.open_cap = max_open
        self.expanded = self.generated = self.pruned = self.peak_open = 0
        self.heuristic_evaluations = self.complete_candidates = self.accepted_replays = 0

    def time_stop(self):
        return "max_seconds" if perf_counter() >= self.deadline else None

    def expansion_stop(self):
        return self.time_stop() or ("max_expansions" if self.cap is not None
                                    and self.expanded >= self.cap else None)


def _settings(mode, lengths=None):
    if mode not in WINDOW_MODES:
        raise ValueError(f"unknown window mode: {mode}")
    if lengths is not None:
        lengths = tuple(integer(x, "window_length", minimum=1) for x in lengths)
        if not lengths or len(set(lengths)) != len(lengths):
            raise ValueError("window_lengths must be nonempty and unique")
        return lengths


def _finish(grid, cfg, path, expected, ledger, reason, source, seed, windows,
            improvements, completion_reason):
    # Mandatory full replay is included in wall time, even at a cooperative stop.
    replay = score_path(grid, path, **cfg)
    if abs(replay.J - expected.J) > ATOL or abs(replay.pd_final - expected.pd_final) > ATOL:
        raise AssertionError("final independent replay mismatch")
    reason = reason or ledger.time_stop()
    wall = perf_counter() - ledger.started
    return WindowResult(tuple(path), replay.J, replay.pd_final, ledger.expanded,
        ledger.generated, ledger.pruned, ledger.peak_open,
        "budget_exceeded" if reason else "completed", reason, source,
        seed=seed, windows=windows, improvements=improvements, wall_s=wall,
        completion_reason=None if reason else completion_reason,
        heuristic_evaluations=ledger.heuristic_evaluations,
        complete_candidates=ledger.complete_candidates,
        accepted_replays=ledger.accepted_replays,
        deadline_overshoot_s=max(0.0, ledger.started + wall - ledger.deadline))


def _window(grid, cfg, path, a, b, mode, ledger, improvements):
    """No state merging: every heap entry retains its full conditional belief."""
    tic = perf_counter()
    before = (ledger.expanded, ledger.generated, ledger.pruned)
    original = tuple(path)
    initial = score_path(grid, original, **cfg, record_beliefs=True)
    current = initial
    coeff = suffix_coefficients(grid, original, q=cfg['q'], motion=cfg['motion'])
    estimate = WindowHeuristic(grid, end_vertex=original[b], end_depth=b,
        q=cfg['q'], motion=cfg['motion'], tail_cost=coeff.cost[b], mode=mode)
    sensor = sensor_probabilities(cfg['q'], grid.size)
    prefix_g = float(initial.g[a])
    seq = count()
    queue = []
    local_peak_open = 0
    accepted_start = len(improvements)
    reason = ledger.time_stop()

    def enqueue(vertex, depth, belief, g, route):
        nonlocal local_peak_open
        # Match legacy A^SAR: generated materialized child states exclude roots.
        ledger.generated += int(depth > a)
        if depth == b:
            if vertex != original[b]:
                raise AssertionError("infeasible endpoint reached")
            ledger.complete_candidates += 1
            predicted_j = prefix_g + g + float(coeff.cost[b] @ belief)
            predicted_pd = 1.0 - float(coeff.survival[b] @ belief)
            if not isfinite(predicted_j) or not isfinite(predicted_pd):
                raise AssertionError("non-finite exact suffix score")
            # Replay possible improvements before a cooperative deadline stop;
            # preserve every fully generated, validated improving incumbent.
            nonlocal path, current
            if predicted_j < current.J + ATOL:
                candidate = original[:a] + route + original[b+1:]
                replay = score_path(grid, candidate, **cfg)
                err_j, err_pd = abs(replay.J-predicted_j), abs(replay.pd_final-predicted_pd)
                if err_j > ATOL or err_pd > ATOL:
                    raise AssertionError("exact suffix prediction disagrees with full replay")
                if replay.J < current.J - ATOL:
                    improvements.append(dict(a=a, b=b, old_J=current.J, J=replay.J,
                        old_Pd=current.pd_final, Pd=replay.pd_final,
                        prediction_error_J=err_j, prediction_error_Pd=err_pd,
                        expanded_total=ledger.expanded, elapsed_s=perf_counter()-ledger.started,
                        path=list(candidate), source=f"window[{a}:{b}]"))
                    path, current = candidate, replay
                    ledger.accepted_replays += 1
            return ledger.time_stop()
        if ledger.time_stop():
            return "max_seconds"
        ledger.heuristic_evaluations += 1
        h = estimate(vertex, depth, belief)
        if not isfinite(h) or h < -ATOL:
            raise AssertionError("invalid bound on a feasible window prefix")
        lower = prefix_g + g + h
        if ledger.time_stop():
            return "max_seconds"
        # Conservative rounding guard: never prune using incumbent minus tol.
        if lower >= current.J + ATOL:
            ledger.pruned += 1
            return None
        if ledger.open_cap is not None and len(queue) >= ledger.open_cap:
            return "max_open"
        heappush(queue, (lower, next(seq), vertex, depth, belief, g, route))
        ledger.peak_open = max(ledger.peak_open, len(queue))
        local_peak_open = max(local_peak_open, len(queue))
        return None

    if reason is None:
        reason = enqueue(original[a], a, initial.beliefs[a].copy(), 0.0, (original[a],))
    while queue and reason is None:
        lower, _, vertex, depth, belief, g, route = heappop(queue)
        if lower >= current.J + ATOL:
            ledger.pruned += 1
            continue
        reason = ledger.expansion_stop()
        if reason:
            break
        ledger.expanded += 1
        t = depth + 1
        moved = cfg['motion'].propagate(belief, step=t)
        for nxt in grid.neighbors(vertex):
            # Common exact endpoint feasibility is independent of heuristic.
            if not estimate._feasible(nxt, b-t):
                ledger.pruned += 1
                continue
            detected = cfg['motion'].sense(moved, nxt, sensor, step=t)
            reason = enqueue(nxt, t, detected, g+float(detected.sum()), route+(nxt,))
            if reason:
                break
    reason = reason or ledger.time_stop()
    record = dict(a=a, b=b, mode=mode, initial_J=initial.J, final_J=current.J,
        status="budget_exceeded" if reason else "completed", stop_reason=reason,
        expanded=ledger.expanded-before[0], generated=ledger.generated-before[1],
        pruned=ledger.pruned-before[2], improvements=len(improvements)-accepted_start,
        peak_open=local_peak_open, wall_s=perf_counter()-tic, neighborhood_only=True)
    return tuple(path), current, reason, record


def solve_window(grid, *, start, budget, p, q, motion, path, a, b,
                 mode="stdc_endpoint_lb", max_expansions=None, max_seconds=None,
                 max_open=None):
    """Solve one fixed window with an exact unchanged suffix; useful for Oracle checks."""
    ledger = _Budget(max_expansions, max_seconds, max_open)
    _settings(mode)
    a, b = integer(a, "a"), integer(b, "b")
    if not 0 <= a < b <= budget:
        raise ValueError("window must satisfy 0 <= a < b <= budget")
    cfg = dict(start=start, budget=budget, p=p, q=q, motion=motion)
    improvements = []
    path, score, reason, record = _window(grid, cfg, tuple(path), a, b, mode, ledger, improvements)
    source = improvements[-1]['source'] if improvements else "initial_path"
    return _finish(grid, cfg, path, score, ledger, reason, source, {}, [record],
                   improvements, "fixed_window_exhausted_at_tolerance")


def improve_with_windows(grid, *, start, budget, p, q, motion, initial_path,
                         epsilon=1.1, mode="stdc_endpoint_lb", window_lengths=(4, 6),
                         seed_max_expansions=1500, max_expansions=5000,
                         max_open=20000, max_seconds=30):
    """Pay for a paper seed, then perform deterministic local improvement sweeps.

    Seed expansion subquota is an explicit method allocation. Seed time/OPEN
    stops remain global stops. All queues share one total expansion/time cap;
    OPEN is the peak physical queue size across the sequential search phases.
    Acceptance minimizes the original full J, without adding a Pd constraint.
    """
    ledger = _Budget(max_expansions, max_seconds, max_open)
    lengths = _settings(mode, window_lengths)
    seed_max_expansions = integer(seed_max_expansions, "seed_max_expansions")
    cfg = dict(start=start, budget=budget, p=p, q=q, motion=motion)
    path = tuple(initial_path)
    score = score_path(grid, path, **cfg)
    reason = ledger.time_stop()
    source, seed, windows, improvements = "initial_path", {}, [], []
    if reason is None:
        seed_cap = seed_max_expansions if ledger.cap is None else min(seed_max_expansions, ledger.cap)
        tic = perf_counter()
        seeded = search_asar(grid, **cfg, initial_path=path, heuristic="paper_greedy",
            epsilon=epsilon, max_expansions=seed_cap, max_open=max_open,
            max_seconds=None if ledger.deadline == inf else max(0., ledger.deadline-perf_counter()))
        seed = dict(**asdict(seeded), cap_kind="method_subbudget", expansion_quota=seed_cap,
                    wall_s=perf_counter()-tic, phase_budget_exceeded=seeded.status=="budget_exceeded")
        ledger.expanded, ledger.generated, ledger.pruned = seeded.expanded, seeded.generated, seeded.pruned
        ledger.peak_open = seeded.peak_open
        path = tuple(seeded.path)
        score = score_path(grid, path, **cfg)
        if abs(score.J-seeded.J) > ATOL:
            raise AssertionError("seed replay mismatch")
        source = "seed_search" if seeded.incumbent_source == "search" else "initial_path"
        if seeded.stop_reason and seeded.stop_reason != "max_expansions":
            reason = seeded.stop_reason
        reason = reason or ledger.expansion_stop()
        seed['remaining_global_expansions'] = None if ledger.cap is None else ledger.cap-ledger.expanded
        seed['continuing_after_subquota'] = seeded.stop_reason == "max_expansions" and reason is None
    stalled = False
    sweep = 0
    while reason is None:
        changed = False
        for length in lengths:
            for a in range(max(0, budget-length+1)):
                reason = ledger.expansion_stop()
                if reason:
                    break
                before = len(improvements)
                path, score, reason, row = _window(grid, cfg, path, a, a+length,
                                                  mode, ledger, improvements)
                row['sweep'] = sweep
                windows.append(row)
                if len(improvements) > before:
                    changed = True
                    source = improvements[-1]['source']
                if reason:
                    break
            if reason:
                break
        if reason:
            break
        if not changed:
            stalled = True
            break
        sweep += 1
    return _finish(grid, cfg, path, score, ledger, reason, source, seed, windows,
                   improvements, "local_stalled_at_tolerance" if stalled else None)
