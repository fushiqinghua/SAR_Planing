"""Constant-speed four/eight-neighbour motion on a common observation clock.

This module is an isolated modelling experiment.  It does not replace the
archived grid, particle motion, or objective implementation.  The square sensor
is a controlled geometric proxy, not a calibrated camera or sweep-width model.
An edge is a motion command; sensing occurs at fixed physical instants, including
inside an edge.  The last edge may be cut at the common mission deadline.

No simulation, search, or test is run at import time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import hypot, isfinite
from numbers import Integral

import numpy as np


def _integer(value, name, minimum=0):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise ValueError(f"{name} must be an integer >= {minimum}")
    result = int(value)
    if result < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return result


def _positive(value, name):
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name} must be positive and finite")
    result = float(value)
    if not isfinite(result) or result <= 0:
        raise ValueError(f"{name} must be positive and finite")
    return result


def _readonly(value, dtype=None):
    result = np.array(value, dtype=dtype, copy=True)
    result.setflags(write=False)
    return result


def _real_array(value, name):
    result = np.asarray(value)
    if result.dtype.kind not in "iuf":
        raise ValueError(f"{name} must contain real numeric values")
    return np.asarray(result, dtype=np.float64)


def _connectivity(value):
    value = _integer(value, "connectivity")
    if value not in (4, 8):
        raise ValueError("connectivity must be 4 or 8")
    return value


@dataclass(frozen=True, eq=False)
class PhysicalState:
    """One exact motion-command prefix, with unnormalised particle weights.

    ``vertex`` is the commanded edge endpoint.  For a terminal partial edge,
    that endpoint has not been reached: use ``actual_xy`` for the true position.
    Such a state cannot be expanded.  ``survival`` contains M_0 through M_tick.
    """

    vertex: int
    time_s: float
    tick: int
    weights: np.ndarray
    J: float
    terminal: bool
    actual_xy: np.ndarray
    last_edge_partial: bool
    survival: tuple[float, ...]
    distance_m: float
    diagonal_distance_m: float
    _owner: int = field(repr=False)


@dataclass(frozen=True, eq=False)
class PhysicalProblem:
    """Frozen particle positions and a shared square sensor on metric geometry.

    Coordinates use east-positive x and north-positive y.  Grid row zero is the
    northern row, matching ParticleGrid.  ``times_s`` is exactly the existing
    common observation cadence d/v (up to floating-point tolerance).  The
    supplied particle frame at tick k belongs to this absolute physical time,
    independently of the number of edges traversed by the aircraft.

    ``searchable=False`` preserves special-bin mass without sensing it.  A
    non-finite target coordinate is accepted only at such an unsearchable entry.
    ``axis_square`` has half-open world bounds [xmin,xmax) x [ymin,ymax), which
    matches ParticleGrid.assign.  ``heading_square`` uses the same half-open
    convention in forward/left body coordinates; its boundary tie rule rotates
    with the incoming segment.  The side length is d in both directions.
    """

    rows: int
    cols: int
    cell_width_m: float
    speed_m_s: float
    times_s: np.ndarray
    positions_xy: np.ndarray
    searchable: np.ndarray
    initial_weights: np.ndarray
    start: int
    q: float
    footprint: str = "heading_square"
    trajectory_ids: np.ndarray | None = None

    def __post_init__(self):
        rows = _integer(self.rows, "rows", 1)
        cols = _integer(self.cols, "cols", 1)
        width = _positive(self.cell_width_m, "cell_width_m")
        speed = _positive(self.speed_m_s, "speed_m_s")
        cadence = width / speed
        if (not isfinite(cadence) or cadence <= 0
                or not isfinite(rows * width) or not isfinite(cols * width)):
            raise ValueError("grid geometry and d/v must have finite positive scales")
        start = _integer(self.start, "start")
        if start >= rows * cols:
            raise ValueError("start is outside the grid")
        if rows * cols == 1:
            raise ValueError("positive-horizon no-wait motion needs a grid edge")
        if isinstance(self.q, (bool, np.bool_)):
            raise ValueError("q must be a finite probability")
        q = float(self.q)
        if not isfinite(q) or not 0 <= q <= 1:
            raise ValueError("q must be a finite probability")
        if self.footprint not in ("axis_square", "heading_square"):
            raise ValueError("unknown square footprint")

        times = _real_array(self.times_s, "times_s")
        positions = _real_array(self.positions_xy, "positions_xy")
        searchable = np.asarray(self.searchable)
        weights = _real_array(self.initial_weights, "initial_weights")
        if times.ndim != 1 or len(times) < 2 or not np.all(np.isfinite(times)):
            raise ValueError("times_s must have at least two finite entries")
        if times[0] != 0 or np.any(np.diff(times) <= 0):
            raise ValueError("times_s must begin at zero and strictly increase")
        if weights.ndim != 1 or not len(weights) or not np.all(np.isfinite(weights)):
            raise ValueError("initial_weights must be a nonempty finite vector")
        if np.any(weights < 0) or abs(float(weights.sum()) - 1.0) > 1e-12:
            raise ValueError("initial_weights must be nonnegative and sum to one")
        if positions.shape != (len(times), len(weights), 2):
            raise ValueError("positions_xy must have shape (K+1, N, 2)")
        if searchable.shape != (len(times), len(weights)) or searchable.dtype.kind != "b":
            raise ValueError("searchable must be a boolean array of shape (K+1, N)")
        if not np.all(np.isfinite(positions[searchable])):
            raise ValueError("searchable particles need finite metric positions")
        expected = np.arange(len(times), dtype=np.float64) * cadence
        if not np.all(np.isfinite(expected)) or not np.allclose(
                times, expected, rtol=64 * np.finfo(np.float64).eps, atol=0):
            raise ValueError("observation cadence must equal cell_width_m / speed_m_s")

        ids = self.trajectory_ids
        if ids is not None:
            ids = np.asarray(ids)
            if (ids.shape != weights.shape or ids.dtype.kind not in "iuUS"
                    or len(np.unique(ids)) != len(ids)):
                raise ValueError("trajectory_ids must be unique, finite-column IDs")
            if ids.dtype.kind == "S":
                ids = ids.astype(str)
            ids = _readonly(ids)
        for key, value in dict(rows=rows, cols=cols, cell_width_m=width,
                               speed_m_s=speed, start=start, q=q,
                               times_s=_readonly(times),
                               positions_xy=_readonly(positions),
                               searchable=_readonly(searchable),
                               initial_weights=_readonly(weights),
                               trajectory_ids=ids).items():
            object.__setattr__(self, key, value)

    @property
    def size(self):
        return self.rows * self.cols

    @property
    def delta_s(self):
        return self.cell_width_m / self.speed_m_s

    @property
    def horizon_s(self):
        return float(self.times_s[-1])

    @property
    def tick_count(self):
        return len(self.times_s) - 1

    @property
    def time_tolerance_s(self):
        return 64 * np.finfo(np.float64).eps * self.horizon_s

    def coordinates(self, vertex):
        vertex = _integer(vertex, "vertex")
        if vertex >= self.size:
            raise ValueError("vertex is outside the grid")
        return divmod(vertex, self.cols)

    def vertex_xy(self, vertex):
        row, col = self.coordinates(vertex)
        return np.asarray(((col + 0.5 - self.cols / 2) * self.cell_width_m,
                           (self.rows / 2 - row - 0.5) * self.cell_width_m), dtype=float)

    def neighbors(self, vertex, connectivity=4):
        connectivity = _connectivity(connectivity)
        row, col = self.coordinates(vertex)
        # Shared cardinal ordering; diagonal actions are appended deterministically.
        steps = ((-1, 0), (0, -1), (0, 1), (1, 0))
        if connectivity == 8:
            steps += ((-1, -1), (-1, 1), (1, -1), (1, 1))
        return tuple((row + dr) * self.cols + col + dc for dr, dc in steps
                     if 0 <= row + dr < self.rows and 0 <= col + dc < self.cols)

    def edge_duration_s(self, source, target, connectivity=4):
        target = _integer(target, "target")
        if target not in self.neighbors(source, connectivity):
            raise ValueError(f"illegal {connectivity}-neighbor edge {source} -> {target}")
        a, b = self.vertex_xy(source), self.vertex_xy(target)
        duration = hypot(float(b[0] - a[0]), float(b[1] - a[1])) / self.speed_m_s
        if not isfinite(duration) or duration <= 0:
            raise ValueError("edge duration must be finite and positive")
        return duration

    def initial_state(self):
        mass = float(self.initial_weights.sum())
        return PhysicalState(self.start, 0.0, 0, _readonly(self.initial_weights),
                             0.0, False, _readonly(self.vertex_xy(self.start)),
                             False, (mass,), 0.0, 0.0, id(self))

    def observation_mask(self, tick, position_xy, heading_xy):
        """Particles actually in the proxy footprint at one common clock tick."""
        tick = _integer(tick, "tick", 1)
        if tick > self.tick_count:
            raise ValueError("observation tick exceeds horizon")
        position = _real_array(position_xy, "position_xy")
        heading = _real_array(heading_xy, "heading_xy")
        if (position.shape != (2,) or heading.shape != (2,)
                or not np.all(np.isfinite(position)) or not np.all(np.isfinite(heading))):
            raise ValueError("position and heading must be finite 2-vectors")
        norm = hypot(float(heading[0]), float(heading[1]))
        if not isfinite(norm) or norm <= 0:
            raise ValueError("a flight heading must have finite nonzero norm")
        active = self.searchable[tick]
        # Do not perform arithmetic on missing/special-bin coordinates.
        delta = self.positions_xy[tick, active] - position
        if self.footprint == "axis_square":
            first, second = delta[:, 0], delta[:, 1]
        else:
            forward = heading / norm
            left = np.asarray((-forward[1], forward[0]))
            first, second = delta @ forward, delta @ left
        half = self.cell_width_m / 2
        result = np.zeros(len(self.initial_weights), dtype=bool)
        result[active] = ((first >= -half) & (first < half)
                          & (second >= -half) & (second < half))
        return result

    def advance(self, state, target, connectivity=4):
        """Execute one edge, processing all fixed-clock glimpses on that edge."""
        return self._advance(state, target, connectivity, None)

    def _advance(self, state, target, connectivity, observations):
        if not isinstance(state, PhysicalState) or state._owner != id(self):
            raise ValueError("state does not belong to this PhysicalProblem")
        if state.terminal:
            raise ValueError("cannot move after the fixed physical horizon")
        target = _integer(target, "target")
        duration = self.edge_duration_s(state.vertex, target, connectivity)
        source_xy = self.vertex_xy(state.vertex)
        target_xy = self.vertex_xy(target)
        displacement = target_xy - source_xy
        full_arrival = state.time_s + duration
        if not isfinite(full_arrival):
            raise ValueError("planned arrival time exceeds finite numeric range")
        terminal = full_arrival >= self.horizon_s - self.time_tolerance_s
        end = self.horizon_s if terminal else full_arrival
        partial = full_arrival > self.horizon_s + self.time_tolerance_s
        fraction_end = min(1.0, max(0.0, (end - state.time_s) / duration))
        actual_xy = source_xy + fraction_end * displacement
        if not partial:
            actual_xy = target_xy
        heading = displacement / (duration * self.speed_m_s)
        weights = state.weights.copy()
        survival = list(state.survival)
        tick, objective = state.tick, state.J
        while tick < self.tick_count and self.times_s[tick + 1] <= end + self.time_tolerance_s:
            tick += 1
            time_s = float(self.times_s[tick])
            if time_s < state.time_s - self.time_tolerance_s:
                raise AssertionError("observation clock moved backwards")
            fraction = min(1.0, max(0.0, (time_s - state.time_s) / duration))
            aircraft_xy = source_xy + fraction * displacement
            hits = self.observation_mask(tick, aircraft_xy, heading)
            before = float(weights.sum())
            weights[hits] *= 1.0 - self.q
            after = float(weights.sum())
            survival.append(after)
            objective += after
            if observations is not None:
                indices = np.flatnonzero(hits)
                observations.append(dict(
                    tick=tick, time_s=time_s, aircraft_xy=aircraft_xy.tolist(),
                    heading_xy=heading.tolist(), source_vertex=state.vertex,
                    target_vertex=target, fraction_of_edge=fraction,
                    sensed_particle_indices=indices.tolist(),
                    sensed_trajectory_ids=(None if self.trajectory_ids is None else
                                           self.trajectory_ids[indices].tolist()),
                    mass_before=before, mass_after=after,
                    detected_mass=before - after, cumulative_J=objective,
                ))
        if terminal and tick != self.tick_count:
            raise AssertionError("terminal route omitted a required observation")
        travelled = self.speed_m_s * (end - state.time_s)
        sr, sc = self.coordinates(state.vertex)
        tr, tc = self.coordinates(target)
        diagonal = abs(sr - tr) == 1 and abs(sc - tc) == 1
        return PhysicalState(target, float(end), tick, _readonly(weights),
                             float(objective), bool(terminal), _readonly(actual_xy),
                             bool(partial), tuple(survival),
                             state.distance_m + travelled,
                             state.diagonal_distance_m + (travelled if diagonal else 0.0),
                             id(self))

    def replay(self, waypoints, connectivity=4):
        """Replay complete motion commands up to H; do not truncate scoring early.

        The last waypoint may be an unreached commanded endpoint.  It still
        identifies the direction of the final partial edge.  Additional commands
        after H and paths ending before H are rejected, rather than silently
        changing the mission duration or number of observations.
        """
        connectivity = _connectivity(connectivity)
        route = tuple(_integer(v, "waypoint") for v in waypoints)
        if not route or route[0] != self.start:
            raise ValueError("waypoints must start at the fixed start vertex")
        state = self.initial_state()
        observations, segments = [], []
        planned_arrivals = [0.0]
        reached_arrivals = [0.0]
        diagonal_edges = 0
        for target in route[1:]:
            if state.terminal:
                raise ValueError("route contains commands after the fixed horizon")
            previous = state
            duration = self.edge_duration_s(previous.vertex, target, connectivity)
            planned_arrival = previous.time_s + duration
            state = self._advance(previous, target, connectivity, observations)
            source_xy, target_xy = self.vertex_xy(previous.vertex), self.vertex_xy(target)
            sr, sc = self.coordinates(previous.vertex)
            tr, tc = self.coordinates(target)
            diagonal = abs(sr - tr) == 1 and abs(sc - tc) == 1
            diagonal_edges += int(diagonal)
            planned_arrivals.append(float(planned_arrival))
            if not state.last_edge_partial:
                reached_arrivals.append(float(state.time_s))
            segments.append(dict(
                source_vertex=previous.vertex, target_vertex=target,
                start_time_s=previous.time_s, planned_arrival_time_s=float(planned_arrival),
                end_time_s=state.time_s, full_edge_duration_s=duration,
                start_xy=source_xy.tolist(), target_xy=target_xy.tolist(),
                actual_end_xy=state.actual_xy.tolist(), diagonal=bool(diagonal),
                partial=state.last_edge_partial,
                flown_distance_m=self.speed_m_s * (state.time_s - previous.time_s),
            ))
        if not state.terminal:
            raise ValueError("route ends before the fixed physical horizon")
        if len(observations) != self.tick_count or len(state.survival) != self.tick_count + 1:
            raise AssertionError("a complete route must contain every common observation")
        return dict(
            model="constant_speed_common_clock_square_proxy_v1",
            sensor_model_status="controlled_geometric_proxy_not_camera_calibrated",
            footprint=self.footprint, connectivity=connectivity,
            J=state.J, pd_final=1.0 - float(state.weights.sum()),
            J_time_scaled_s=state.J * self.delta_s,
            J_time_scaled_interpretation="fixed-clock post-observation sum, not exact continuous-time MTTD",
            survival=list(state.survival), final_weights=state.weights.tolist(),
            waypoints=list(route), path=list(route),
            waypoint_semantics="motion commands; a terminal partial edge may not reach its last waypoint",
            planned_arrival_times_s=planned_arrivals, arrival_times_s=reached_arrivals,
            observation_times_s=self.times_s[1:].tolist(), observations=observations,
            segments=segments, physical_duration_s=state.time_s,
            horizon_s=self.horizon_s, observation_count=self.tick_count,
            delta_s=self.delta_s, speed_m_s=self.speed_m_s,
            distance_m=state.distance_m, diagonal_distance_m=state.diagonal_distance_m,
            diagonal_distance_fraction=state.diagonal_distance_m / state.distance_m,
            diagonal_edge_count=diagonal_edges, final_xy=state.actual_xy.tolist(),
            last_edge_partial=state.last_edge_partial,
            trajectory_identity=("provided_ids" if self.trajectory_ids is not None else
                                 "column_indices_only"),
            formal_certificate=False,
        )


def replay(problem, waypoints, connectivity=4):
    """Functional alias for the isolated physical evaluator."""
    if not isinstance(problem, PhysicalProblem):
        raise TypeError("problem must be a PhysicalProblem")
    return problem.replay(waypoints, connectivity)
