"""Independent-particle dynamic-programming relaxation on absolute frames.

Each supplied motion column may choose its own legal search route. For an
undetected particle i, V_i(t,v) is the minimum remaining cumulative survival
cost. Thus sum_i b_i V_i(t,v) lower-bounds the cost of one common search route.
An optional, SEPARATE table minimizes terminal survival and supplies only a
diagnostic Pd upper bound. The two optima need not use the same route.

No partial table is published after a build budget stop. These numerical
bounds do not by themselves confer a full-search epsilon certificate.
"""
from __future__ import annotations

from math import inf, isfinite, isnan
from time import perf_counter

import numpy as np

from .belief import sensor_probabilities, undetected_mass
from .grid import GridGraph, integer
from .motion import ParticleMotion


class _BuildInterrupted(Exception):
    def __init__(self, reason):
        self.reason = reason


class ParticleDP:
    """Build V_i(t,v)=min_u a_i(t+1,u)*(1+V_i(t+1,u)) backwards.

    u must be a legal neighbour with a feasible remaining suffix. V_i(T,v)=0.
    a is 1-q[u] when cell_ids[t+1,i]==u and 1 otherwise; special bins cannot
    match a legal vertex. Columns, including compressed-column ID mappings,
    retain the order of the supplied ParticleMotion (or its subclass).

    max_memory_bytes caps the estimated peak of this builder's managed NumPy
    arrays. It is not an operating-system RSS cap: caller-owned motion arrays,
    input-conversion temporaries, interpreter and Python object overhead are
    excluded. max_seconds and deadline cover the whole cooperative build.
    A caller must include preprocessing time/memory in its experiment budget.
    """

    def __init__(self, grid: GridGraph, *, budget: int, q, motion: ParticleMotion,
                 with_pd_bound: bool = False, max_seconds=None, deadline=inf,
                 max_memory_bytes=None):
        started = perf_counter()
        if not isinstance(grid, GridGraph):
            raise ValueError("ParticleDP requires the fixed four-neighbour GridGraph")
        if not isinstance(motion, ParticleMotion):
            raise ValueError("ParticleDP requires ParticleMotion or a compatible subclass")
        if not isinstance(with_pd_bound, bool):
            raise ValueError("with_pd_bound must be a bool")
        self.grid = grid
        self.budget = integer(budget, "budget")
        if grid.size != motion.size:
            raise ValueError("motion grid size must match the search grid")
        motion.check_horizon(self.budget)
        sensor = sensor_probabilities(q, grid.size)
        deadline = float(deadline)
        if isnan(deadline):
            raise ValueError("deadline must not be NaN")
        if max_seconds is not None:
            if not isfinite(max_seconds) or max_seconds < 0:
                raise ValueError("max_seconds must be finite and nonnegative")
            deadline = min(deadline, started + max_seconds)
        if max_memory_bytes is not None:
            max_memory_bytes = integer(max_memory_bytes, "max_memory_bytes")
        self.motion = motion
        self.state_size = motion.state_size
        self.trajectory_ids = motion.trajectory_ids
        self._cells = motion.cell_ids
        self.with_pd_bound = with_pd_bound
        self.q = None
        self.ready = False
        self.status = "building"
        self.stop_reason = None
        self._cost = self._survival = self._feasible = None

        shape = (self.budget + 1, grid.size, self.state_size)
        table_bytes = int(np.prod(shape, dtype=object)) * np.dtype(np.float64).itemsize
        feasible_bytes = (self.budget + 1) * grid.size * np.dtype(np.bool_).itemsize
        sensor_bytes = grid.size * np.dtype(np.float64).itemsize
        scratch_bytes = (self.state_size * (np.dtype(np.float64).itemsize
                         + np.dtype(np.bool_).itemsize)) if self.budget else 0
        required = table_bytes * (1 + int(with_pd_bound)) + feasible_bytes + sensor_bytes + scratch_bytes
        info = dict(status="building", stop_reason=None, wall_s=0.0,
                    budget=self.budget, vertices=grid.size, particle_columns=self.state_size,
                    with_pd_bound=with_pd_bound, cost_table_bytes=table_bytes,
                    survival_table_bytes=table_bytes if with_pd_bound else 0,
                    feasible_table_bytes=feasible_bytes, sensor_bytes=sensor_bytes,
                    scratch_bytes=scratch_bytes, required_peak_managed_bytes=required,
                    allocated_peak_managed_bytes=0, published_table_bytes=0,
                    max_memory_bytes=max_memory_bytes, max_seconds=max_seconds,
                    completed_time_layers=0, completed_vertex_backups=0,
                    edge_backups=0, particle_edge_backups=0,
                    deadline_overshoot_s=0.0,
                    memory_scope="managed DP NumPy buffers; excludes caller motion, input conversion, interpreter and Python object overhead",
                    work_scope="preprocessing DP backups, not search-tree expansions; include build wall time in the shared budget",
                    column_order="supplied motion ID order; compressed motion retains its original-ID mapping",
                    pd_scope="independent terminal-survival optimum, not the min-J route",
                    global_epsilon_certified=False)
        cost = survival = feasible = work = hit = None
        allocated = 0

        def time_check():
            if perf_counter() >= deadline:
                raise _BuildInterrupted("max_seconds")

        def charge(array):
            nonlocal allocated
            allocated += array.nbytes
            info["allocated_peak_managed_bytes"] = max(info["allocated_peak_managed_bytes"], allocated)
            return array

        try:
            time_check()
            if max_memory_bytes is not None and required > max_memory_bytes:
                raise _BuildInterrupted("max_memory_bytes")
            self.q = charge(sensor.copy())
            self.q.setflags(write=False)
            cost = charge(np.full(shape, inf, dtype=np.float64))
            time_check()
            if with_pd_bound:
                survival = charge(np.full(shape, inf, dtype=np.float64))
                time_check()
            feasible = charge(np.zeros(shape[:2], dtype=np.bool_))
            feasible[self.budget] = True
            cost[self.budget] = 0.0
            if survival is not None:
                survival[self.budget] = 1.0
            if self.budget:
                work = charge(np.empty(self.state_size, dtype=np.float64))
                hit = charge(np.empty(self.state_size, dtype=np.bool_))
            for t in range(self.budget - 1, -1, -1):
                cells = self._cells[t + 1]  # Absolute frame, never relative to a query.
                for vertex in range(grid.size):
                    time_check()
                    for nxt in grid.neighbors(vertex):
                        # Feasibility is independent of the particle or its
                        # weight. Excluding infeasible suffixes FIRST avoids
                        # the invalid 0*inf case when q[nxt]==1.
                        if not feasible[t + 1, nxt]:
                            continue
                        time_check()
                        feasible[t, vertex] = True
                        np.equal(cells, nxt, out=hit)
                        np.add(cost[t + 1, nxt], 1.0, out=work)
                        np.multiply(work, 1.0 - self.q[nxt], out=work, where=hit)
                        np.minimum(cost[t, vertex], work, out=cost[t, vertex])
                        if survival is not None:
                            np.copyto(work, survival[t + 1, nxt])
                            np.multiply(work, 1.0 - self.q[nxt], out=work, where=hit)
                            np.minimum(survival[t, vertex], work, out=survival[t, vertex])
                        info["edge_backups"] += 1
                        info["particle_edge_backups"] += self.state_size
                    time_check()
                    info["completed_vertex_backups"] += 1
                info["completed_time_layers"] += 1
            time_check()
            for array in (cost, survival, feasible):
                if array is not None:
                    array.setflags(write=False)
            # Publish atomically only after the entire horizon is complete.
            self._cost, self._survival, self._feasible = cost, survival, feasible
            self.ready = True
            self.status = "completed"
            info["published_table_bytes"] = cost.nbytes + feasible.nbytes + (
                survival.nbytes if survival is not None else 0)
        except _BuildInterrupted as interrupted:
            self.status = "budget_exceeded"
            self.stop_reason = interrupted.reason
            self._cost = self._survival = self._feasible = None
            # No caller can retain a view into a partially built table.
            cost = survival = feasible = work = hit = None
        finally:
            ended = perf_counter()
            info.update(status=self.status, stop_reason=self.stop_reason,
                        wall_s=ended-started, deadline_overshoot_s=max(0.0, ended-deadline))
            self.build_info = info

    @property
    def stats(self):
        """A copy of construction diagnostics; no state-dependent query cache."""
        return dict(self.build_info)

    @property
    def cost_table(self):
        return self._cost

    @property
    def survival_table(self):
        return self._survival

    @property
    def feasible_table(self):
        return self._feasible

    def validate_compatibility(self, grid, *, budget, q, motion):
        """Reject reuse across models, including equally sized motion archives."""
        if not self.ready:
            raise ValueError("ParticleDP build is not ready")
        if not isinstance(grid, GridGraph) or grid != self.grid:
            raise ValueError("ParticleDP grid mismatch")
        if integer(budget, "budget") != self.budget:
            raise ValueError("ParticleDP budget mismatch")
        if (motion is not self.motion or motion.cell_ids is not self._cells
                or motion.trajectory_ids is not self.trajectory_ids):
            raise ValueError("ParticleDP motion identity or immutable archive changed")
        if not np.array_equal(sensor_probabilities(q, grid.size), self.q):
            raise ValueError("ParticleDP sensor mismatch")
        return True

    def _query(self, vertex, depth, belief):
        if not self.ready:
            raise RuntimeError("ParticleDP build is incomplete; partial tables cannot be used")
        self.grid.coordinates(vertex)
        vertex = int(vertex)
        depth = integer(depth, "depth")
        if depth > self.budget:
            raise ValueError("depth exceeds ParticleDP budget")
        b = undetected_mass(belief, self.state_size)
        return vertex, depth, b

    def __call__(self, vertex, depth, belief):
        vertex, depth, b = self._query(vertex, depth, belief)
        if not self._feasible[depth, vertex]:
            return inf  # A legal T-length route is required even for zero mass.
        return float(b @ self._cost[depth, vertex])

    def pd_upper_bound(self, vertex, depth, belief):
        """Optimistic TOTAL Pd, including earlier detection; None if infeasible.

        This uses a different per-particle optimization from the J table. It
        must not be reported as the Pd of a route attaining this object's J
        lower bound, or as an achieved detection probability.
        """
        vertex, depth, b = self._query(vertex, depth, belief)
        if not self.with_pd_bound:
            raise RuntimeError("terminal-survival table was not requested")
        if not self._feasible[depth, vertex]:
            return None
        return 1.0 - float(b @ self._survival[depth, vertex])
