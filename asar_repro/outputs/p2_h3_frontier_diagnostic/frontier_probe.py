"""Matched-work instrumentation around the frozen Lazy solver."""
from hashlib import sha256
import heapq
from struct import pack
from sys import getsizeof
from time import perf_counter_ns
from unittest.mock import patch

import psutil

from asar_repro import physical_lazy_prefix as core


MODES = ("single_global", "three_global", "three_quota")
POLICY_SECONDS = 29.75


def frontier_hash(heap):
    """Hash native heap order and full search states at the hand-off."""
    digest = sha256()
    for key, serial, state, path in heap:
        digest.update(pack("<dqdidid?", key, serial, state.time_s, state.vertex,
                           state.J, state.tick, state.distance_m, state.last_edge_partial))
        digest.update(pack(f"<I{len(path)}q", len(path), *path))
        digest.update(pack(f"<I{len(state.survival)}d", len(state.survival), *state.survival))
        digest.update(state.weights.tobytes())
        digest.update(state.actual_xy.tobytes())
    return digest.hexdigest()


def solve_probe(problem, *, mode, checkpoint, **options):
    """All modes run a deterministic native prefix before the representation contrast."""
    if mode not in MODES or checkpoint < 0:
        raise ValueError("Invalid diagnostic implementation or checkpoint")
    monitor = psutil.Process()
    probe = dict(mode=mode, checkpoint_target=checkpoint, handoff=None, split=None)
    prefix_trace, full_trace = sha256(), sha256()
    controller_type, frontier_type = core._LazyProgressController, core._LazyFrontier
    controller = None
    reserved_ancestors = {}
    reached = False

    def checkpoint_data(native):
        nonlocal reached
        if reached or controller.expanded != checkpoint:
            raise AssertionError("The native heap did not reach the registered checkpoint exactly")
        reached = True
        start = perf_counter_ns()
        signature = frontier_hash(native)
        probe["handoff"] = dict(
            monotonic_ns=start, open_count=len(native), open_sha256=signature,
            expanded=controller.expanded, prior_pops_sha256=prefix_trace.hexdigest(),
            audit_ns=perf_counter_ns()-start, rss_bytes=monitor.memory_info().rss,
        )

    def record_pop(item):
        serialized = pack("<q", item[1])
        full_trace.update(serialized)
        if not reached:
            prefix_trace.update(serialized)

    class Controller:
        # The host loop calls our wrapper on every pop. Qualification and
        # reservations still come from the original controller.
        eligible = True

        def __init__(self, ticks, _seconds):
            nonlocal controller
            controller = self
            self.expanded = 0
            self.engine = controller_type(ticks, POLICY_SECONDS)
            self.allow = False
            self.at = 0.0
            self.handoff_credit = 0.0

        def observe_expansion(self, tick):
            self.expanded += 1
            self.engine.observe_expansion(tick)

        def register_search_improvement(self, elapsed):
            self.engine.register_search_improvement(elapsed - self.handoff_credit)

        def should_reserve(self, elapsed, best_elapsed):
            self.at = elapsed
            # The common checkpoint digest is extra audit work. Budget wall
            # includes it, while the production progress clock excludes it.
            self.allow = self.engine.should_reserve(
                elapsed - self.handoff_credit, self.best_clock(best_elapsed),
            )
            if not reached and self.expanded == checkpoint:
                return mode != "single_global"  # force structural partition only
            return mode == "three_quota" and reached and self.allow

        def best_clock(self, best_elapsed):
            if best_elapsed is None:
                return None
            at = probe.get("handoff_solver_s")
            return best_elapsed if at is None or best_elapsed <= at else best_elapsed - self.handoff_credit

        def statistics(self):
            return self.engine.statistics()

    class NativeHeap:
        heappush = staticmethod(heapq.heappush)
        heapify = staticmethod(heapq.heapify)

        @staticmethod
        def heappop(heap):
            if not reached and controller.expanded == checkpoint:
                checkpoint_data(heap)
                probe["handoff_solver_s"] = controller.at
                controller.handoff_credit = probe["handoff"]["audit_ns"] / 1e9
            item = heapq.heappop(heap)
            record_pop(item)
            return item

    class ThreeHeaps(frontier_type):
        @classmethod
        def from_single_heap(cls, ticks, heap, budget):
            checkpoint_data(heap)
            probe["handoff_solver_s"] = controller.at
            controller.handoff_credit = probe["handoff"]["audit_ns"] / 1e9
            started = perf_counter_ns()
            rss_before = monitor.memory_info().rss
            result = super().from_single_heap(ticks, heap, budget)
            probe["split"] = dict(start_ns=started, constructed_ns=perf_counter_ns(),
                                  rss_before=rss_before, rss_both_heaps=monitor.memory_info().rss,
                                  rss_after_swap=None)
            return result

        def pop(self, expanded, allow_reserved=False):
            if probe["split"]["rss_after_swap"] is None:
                probe["split"]["rss_after_swap"] = monitor.memory_info().rss
                probe["split"]["swapped_ns"] = perf_counter_ns()
            before = sum(self.reserved_pops)
            # The requested hand-off never turns a global pop into a reserved pop.
            item = super().pop(expanded, mode == "three_quota" and controller.allow and allow_reserved)
            if sum(self.reserved_pops) > before:
                reserved_ancestors.setdefault(item[3], (controller.at, expanded, item[2].tick))
            record_pop(item)
            return item

    with (patch.object(core, "_LazyProgressController", Controller),
          patch.object(core, "_LazyFrontier", ThreeHeaps), patch.object(core, "heapq", NativeHeap)):
        result = core.solve_physical_lazy_prefix(problem, **options)
    probe["pop_sha256"] = full_trace.hexdigest()
    probe["reserved_distinct_paths"] = len(reserved_ancestors)
    probe["lineage_bookkeeping_bytes"] = getsizeof(reserved_ancestors) + sum(
        getsizeof(path) + getsizeof(marker) for path, marker in reserved_ancestors.items()
    )
    lineage = []
    for entry in result["history"][1:]:
        route = tuple(entry["waypoints"])
        ancestor = [
            (length, *reserved_ancestors[route[:length]])
            for length in range(1, len(route))
            if route[:length] in reserved_ancestors
            and reserved_ancestors[route[:length]][0] <= entry["elapsed_s"]
        ]
        lineage.append(dict(elapsed_s=entry["elapsed_s"], J=entry["J"], Pd=entry["pd_final"],
                            source=entry["source"], reserved_ancestors=ancestor))
    probe["incumbent_lineage"] = lineage
    return result, probe


def extended_lazy(problem, **options):
    """Extend search time while preserving the original 30 s qualification cutoff."""
    original = core._LazyProgressController
    with patch.object(core, "_LazyProgressController", lambda k, _: original(k, POLICY_SECONDS)):
        return core.solve_physical_lazy_prefix(problem, **options)
