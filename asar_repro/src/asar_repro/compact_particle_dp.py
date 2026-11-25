"""Exact Float64 storage reduction for the independent-particle J lower bound.

Only root-time reachable vertices are stored. At depth t, columns with exactly
the same absolute future cells t+1..T share a coefficient, irrespective of their
past observations. This groups coefficients, never path-dependent search states.
"""
from __future__ import annotations

from math import inf, isfinite, isnan
from time import perf_counter

import numpy as np

from .belief import sensor_probabilities, undetected_mass
from .grid import GridGraph, integer
from .motion import ParticleMotion
from .particle_dp import ParticleDP, _BuildInterrupted


class CompactParticleDP(ParticleDP):
    """Root-specific compact implementation of the unchanged particle DP.

    The budget covers all owned NumPy buffers and a conservative reserve for
    NumPy validation/gather temporaries. Caller-owned motion and q, Python
    objects, and library memory are outside this managed-buffer cap; record RSS
    separately. Construction and every query are synchronous, not thread-safe.
    No incomplete table is queryable. This implementation supplies only J.
    """

    def __init__(self, grid: GridGraph, *, start: int, budget: int, q,
                 motion: ParticleMotion, with_pd_bound=False, max_seconds=None,
                 deadline=inf, max_memory_bytes=None):
        started = perf_counter()
        if not isinstance(grid, GridGraph):
            raise ValueError("CompactParticleDP requires the fixed four-neighbour GridGraph")
        if not isinstance(motion, ParticleMotion):
            raise ValueError("CompactParticleDP requires ParticleMotion")
        if not isinstance(with_pd_bound, bool) or with_pd_bound:
            raise ValueError("CompactParticleDP supports only J; with_pd_bound must be False")
        grid.coordinates(start)
        self.start, self.budget = int(start), integer(budget, "budget")
        if grid.size != motion.size:
            raise ValueError("motion grid size must match the search grid")
        motion.check_horizon(self.budget)
        deadline = float(deadline)
        if isnan(deadline):
            raise ValueError("deadline must not be NaN")
        if max_seconds is not None:
            if not isfinite(max_seconds) or max_seconds < 0:
                raise ValueError("max_seconds must be finite and nonnegative")
            deadline = min(deadline, started + max_seconds)
        if max_memory_bytes is not None:
            max_memory_bytes = integer(max_memory_bytes, "max_memory_bytes")
        T, V, N = self.budget, grid.size, motion.state_size
        if max(T, V, N, motion.bin_count) > np.iinfo(np.int32).max:
            raise ValueError("compact int32 indexing capacity exceeded")
        self.grid, self.motion, self.state_size = grid, motion, N
        self.trajectory_ids, self._cells = motion.trajectory_ids, motion.cell_ids
        self.with_pd_bound = False
        self.ready, self.status, self.stop_reason = False, "building", None
        self.q = self._cost = self._survival = self._feasible = None
        self._group_map = self._next_group = self._group_cell = None
        self._group_counts = self._row_map = self._row_counts = self._offsets = None
        self._query_work = None
        # Conservative overlapping validation/gather buffers, also covering a
        # float64 conversion of list-valued q/belief and np.take index casts.
        reserve = 36 * max(V, N, 1)
        metadata_bytes = (8 * V + 4 * (T+1) * N + 8 * T * N
                          + 4 * (T+1) * V + 16 * (T+1))
        scratch_bytes = N * (8 + 1 + 8)  # DP work, hit mask, query output.
        info = dict(status="building", stop_reason=None, wall_s=0.,
            start=self.start, budget=T, vertices=V, particle_columns=N,
            with_pd_bound=False, representation="root cone and exact future suffix groups",
            cost_table_bytes=None, survival_table_bytes=0, feasible_table_bytes=0,
            metadata_bytes=metadata_bytes, scratch_bytes=scratch_bytes,
            numpy_transient_reserve_bytes=reserve, required_peak_managed_bytes=None,
            allocated_peak_managed_bytes=0, allocated_peak_owned_numpy_bytes=0,
            published_table_bytes=0, published_owned_numpy_bytes=0,
            max_memory_bytes=max_memory_bytes, max_seconds=max_seconds,
            completed_time_layers=0, completed_vertex_backups=0, edge_backups=0,
            particle_edge_backups=0, uncompressed_particle_edge_backups=0,
            deadline_overshoot_s=0., group_counts_by_depth=None,
            reachable_vertices_by_depth=None,
            memory_scope="all owned DP NumPy arrays plus reserved NumPy temporaries; excludes caller-owned arrays, Python objects, interpreter and libraries",
            work_scope="preprocessing backups, not search expansions; shared method deadline",
            query_scope="original motion ID order; arbitrary valid undetected weights; no state cache",
            global_epsilon_certified=False)
        owned = 0
        arrays = []

        def time_check():
            if perf_counter() >= deadline:
                raise _BuildInterrupted("max_seconds")

        def allocate(shape, dtype, fill=None):
            nonlocal owned
            time_check()
            count = 1
            for dim in ((shape,) if isinstance(shape, int) else shape):
                count *= int(dim)
            size = count * np.dtype(dtype).itemsize
            required = owned + size + reserve
            if max_memory_bytes is not None and required > max_memory_bytes:
                raise _BuildInterrupted("max_memory_bytes")
            array = np.empty(shape, dtype=dtype)
            if fill is not None:
                array.fill(fill)
            owned += array.nbytes
            arrays.append(array)
            info["allocated_peak_owned_numpy_bytes"] = owned
            info["allocated_peak_managed_bytes"] = owned + reserve
            return array

        sensor = groups = next_group = group_cell = counts = rows = row_counts = offsets = None
        cost = work = hit = query_work = None
        try:
            time_check()
            minimum = metadata_bytes + scratch_bytes + reserve
            info["required_peak_managed_bytes"] = minimum
            if max_memory_bytes is not None and minimum > max_memory_bytes:
                raise _BuildInterrupted("max_memory_bytes")
            sensor = allocate(V, np.float64)
            np.copyto(sensor, sensor_probabilities(q, V))
            groups = allocate((T+1, N), np.int32)
            next_group = allocate((T, N), np.int32, 0)
            group_cell = allocate((T, N), np.int32, 0)
            counts = allocate(T+1, np.int32, 0)
            rows = allocate((T+1, V), np.int32, -1)
            row_counts = allocate(T+1, np.int32, 0)
            offsets = allocate(T+1, np.int64, 0)
            groups[T].fill(0)
            counts[T] = 1
            # Exact suffix refinement. No full future-matrix sorting/copying.
            for t in range(T-1, -1, -1):
                mapping = {}
                for i in range(N):
                    time_check()
                    key = (int(self._cells[t+1, i]), int(groups[t+1, i]))
                    group = mapping.get(key)
                    if group is None:
                        group = len(mapping)
                        mapping[key] = group
                        group_cell[t, group], next_group[t, group] = key
                    groups[t, i] = group
                counts[t] = len(mapping)
            sr, sc = divmod(self.start, grid.cols)
            for t in range(T+1):
                time_check()
                count = 0
                for v in range(V):
                    r, c = divmod(v, grid.cols)
                    distance = abs(r-sr) + abs(c-sc)
                    reachable = (distance <= t and (t-distance) % 2 == 0
                                 and (V > 1 or t == 0))
                    if reachable:
                        rows[t, v] = count
                        count += 1
                row_counts[t] = count
            size = 0
            for t in range(T):
                offsets[t] = size
                size += int(row_counts[t]) * int(counts[t])
            offsets[T] = size
            required = metadata_bytes + scratch_bytes + reserve + 8 * size
            info.update(cost_table_bytes=8*size, required_peak_managed_bytes=required,
                group_counts_by_depth=counts.tolist(),
                reachable_vertices_by_depth=row_counts.tolist())
            if max_memory_bytes is not None and required > max_memory_bytes:
                raise _BuildInterrupted("max_memory_bytes")
            cost = allocate(size, np.float64, inf)
            work = allocate(N, np.float64)
            hit = allocate(N, np.bool_)
            query_work = allocate(N, np.float64)
            assert owned == metadata_bytes + scratch_bytes + cost.nbytes
            for t in range(T-1, -1, -1):
                G = int(counts[t])
                layer = cost[int(offsets[t]):int(offsets[t+1])].reshape(int(row_counts[t]), G)
                successor = None if t+1 == T else cost[int(offsets[t+1]):int(offsets[t+2])].reshape(
                    int(row_counts[t+1]), int(counts[t+1]))
                for vertex in range(V):
                    row = int(rows[t, vertex])
                    if row < 0:
                        continue
                    time_check()
                    target = layer[row]
                    for nxt in grid.neighbors(vertex):
                        time_check()
                        nxt_row = int(rows[t+1, nxt])
                        if nxt_row < 0:
                            raise AssertionError("legal successor left exact root reachability cone")
                        if successor is None:
                            work[:G].fill(1.)
                        else:
                            # Valid integer group IDs; mode=clip avoids the
                            # default raise-mode safety copy of an out buffer.
                            np.take(successor[nxt_row], next_group[t, :G], out=work[:G], mode="clip")
                            np.add(work[:G], 1., out=work[:G])
                        np.equal(group_cell[t, :G], nxt, out=hit[:G])
                        np.multiply(work[:G], 1.-sensor[nxt], out=work[:G], where=hit[:G])
                        np.minimum(target, work[:G], out=target)
                        info["edge_backups"] += 1
                        info["particle_edge_backups"] += G
                        info["uncompressed_particle_edge_backups"] += N
                    info["completed_vertex_backups"] += 1
                info["completed_time_layers"] += 1
            time_check()
            for array in arrays:
                if array is not query_work:
                    array.setflags(write=False)
            self.q, self._cost = sensor, cost
            self._group_map, self._next_group, self._group_cell = groups, next_group, group_cell
            self._group_counts, self._row_map, self._row_counts = counts, rows, row_counts
            self._offsets, self._query_work = offsets, query_work
            self.ready, self.status = True, "completed"
            info["published_table_bytes"] = cost.nbytes
            info["published_owned_numpy_bytes"] = owned - work.nbytes - hit.nbytes
        except _BuildInterrupted as interrupted:
            self.status, self.stop_reason = "budget_exceeded", interrupted.reason
        finally:
            ended = perf_counter()
            info.update(status=self.status, stop_reason=self.stop_reason,
                wall_s=ended-started, deadline_overshoot_s=max(0., ended-deadline))
            self.build_info = info

    @property
    def suffix_group_table(self):
        return self._group_map

    @property
    def vertex_row_table(self):
        return self._row_map

    def validate_compatibility(self, grid, *, budget, q, motion, start=None):
        if not self.ready:
            raise ValueError("CompactParticleDP build is not ready")
        if not isinstance(grid, GridGraph) or grid != self.grid:
            raise ValueError("CompactParticleDP grid mismatch")
        if integer(budget, "budget") != self.budget:
            raise ValueError("CompactParticleDP budget mismatch")
        if start is not None and integer(start, "start") != self.start:
            raise ValueError("CompactParticleDP root start mismatch")
        if (motion is not self.motion or motion.cell_ids is not self._cells
                or motion.trajectory_ids is not self.trajectory_ids):
            raise ValueError("CompactParticleDP motion identity or immutable archive changed")
        if not np.array_equal(sensor_probabilities(q, grid.size), self.q):
            raise ValueError("CompactParticleDP sensor mismatch")
        return True

    def __call__(self, vertex, depth, belief):
        if not self.ready:
            raise RuntimeError("CompactParticleDP build incomplete; partial tables cannot be used")
        self.grid.coordinates(vertex)
        depth = integer(depth, "depth")
        if depth > self.budget:
            raise ValueError("depth exceeds CompactParticleDP budget")
        row = int(self._row_map[depth, int(vertex)])
        if row < 0:
            raise ValueError("query outside the frozen root-time reachability cone")
        b = undetected_mass(belief, self.state_size)
        if depth == self.budget:
            return 0.
        if self.grid.size == 1:
            return inf  # No legal positive-length route, including zero belief.
        G = int(self._group_counts[depth])
        offset = int(self._offsets[depth]) + row*G
        coefficients = self._cost[offset:offset+G]
        np.take(coefficients, self._group_map[depth], out=self._query_work, mode="clip")
        return float(b @ self._query_work)

    def pd_upper_bound(self, vertex, depth, belief):
        raise RuntimeError("terminal-survival table is not supported by CompactParticleDP")
