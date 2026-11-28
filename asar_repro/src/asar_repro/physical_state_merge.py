"""Bounded, exact labels for one physical-problem/committed-prefix search.

Only equality of the full future-relevant state is used.  At the same exact
state, the lowest cumulative J represents all equivalent prefixes for the
current J/terminal-Pd objectives.  No approximate clock, mass bin, componentwise
dominance scan, or digest-only equality is used.  Different historical survival
curves may have the same J; this rule does not promise to preserve those curves.

The current physical model has fixed speed, unrestricted revisits, a free end
point and no heading/energy history constraint.  A model adding such constraints
must extend this key before reusing the rule.  Each re-rooted call owns a fresh
index: a representative from a different committed prefix is never borrowed.
"""
from __future__ import annotations

import math
from numbers import Integral
from time import perf_counter


DEFAULT_MAX_ENTRIES = 16384
DEFAULT_MAX_PAYLOAD_BYTES = 64 * 1024 * 1024
MERGE_MODES = ("off", "shadow", "exact")


def validate_merge_limits(max_entries, max_payload_bytes):
    result = []
    for value, name in ((max_entries, "merge_max_entries"),
                        (max_payload_bytes, "merge_max_payload_bytes")):
        if isinstance(value, bool) or not isinstance(value, Integral) or value < 1:
            raise ValueError(f"{name} must be a positive integer")
        result.append(int(value))
    return tuple(result)


class ExactStateMerge:
    """Lowest-J label per exact nonterminal state, with bounded stored payload.

    ``shadow`` updates the same index and counts discard opportunities, while
    always letting search continue.  Its counts describe that unpruned search;
    they are not a prediction of the work an ``exact`` run would save.

    The payload cap covers retained xy/weight byte strings, not Python object
    overhead.  The entry cap also bounds that overhead, and the existing process
    RSS watchdog remains authoritative.  Reaching either cap only disables
    insertion of new keys; it never causes an unproven state to be discarded.
    """

    def __init__(self, mode="off", *, max_entries=DEFAULT_MAX_ENTRIES,
                 max_payload_bytes=DEFAULT_MAX_PAYLOAD_BYTES):
        if mode not in MERGE_MODES:
            raise ValueError(f"merge mode must be one of {MERGE_MODES}")
        self.mode = mode
        self.max_entries, self.max_payload_bytes = validate_merge_limits(
            max_entries, max_payload_bytes)
        self._best = {}
        self._payload_bytes = 0
        self._counts = dict(
            root_considered=0, nonterminal_children=0, mergeable_children=0,
            discarded_children=0, equal_J_duplicates=0, higher_J_duplicates=0,
            replaced_entries=0, pop_checks=0, stale_pop_candidates=0,
            stale_pops=0, capacity_skips=0, entries_peak=0,
            payload_bytes_peak=0, lookup_s=0.0, key_build_s=0.0,
        )

    def _key(self, state):
        before = perf_counter()
        try:
            if state.terminal or state.last_edge_partial:
                raise ValueError("only full, nonterminal vertex states may be indexed")
            time_s, objective = float(state.time_s), float(state.J)
            if not math.isfinite(time_s) or not math.isfinite(objective):
                raise ValueError("indexed time and objective must be finite")
            xy, weights = state.actual_xy, state.weights
            xy_bytes = xy.tobytes(order="C")
            weight_bytes = weights.tobytes(order="C")
            key = (
                state._owner, int(state.vertex), time_s.hex(), int(state.tick),
                xy.dtype.str, tuple(xy.shape), xy_bytes,
                weights.dtype.str, tuple(weights.shape), weight_bytes,
            )
            return key, len(xy_bytes) + len(weight_bytes)
        finally:
            self._counts["key_build_s"] += perf_counter() - before

    def should_discard(self, state, *, source="child"):
        """Register an eligible state and say whether ``exact`` may skip it.

        Call after the existing accumulated-J prune and before its guide/heap
        insertion. ``nonterminal_children`` counts these presented children,
        not all generated children and not the initial root.
        """
        if self.mode == "off":
            return False
        if source not in ("child", "root"):
            raise ValueError("state merge source must be child or root")
        before = perf_counter()
        try:
            self._counts["root_considered" if source == "root" else "nonterminal_children"] += 1
            key, payload = self._key(state)
            objective = float(state.J)
            previous = self._best.get(key)
            if previous is not None:
                if previous <= objective:
                    if source == "child":
                        self._counts["mergeable_children"] += 1
                        counter = "equal_J_duplicates" if previous == objective else "higher_J_duplicates"
                        self._counts[counter] += 1
                        if self.mode == "exact":
                            self._counts["discarded_children"] += 1
                    return self.mode == "exact"
                # A cheaper prefix can arrive after a label was expanded.
                # Keep it and reopen it; stale older heap labels are skipped.
                self._best[key] = objective
                self._counts["replaced_entries"] += 1
                return False
            if (len(self._best) >= self.max_entries
                    or self._payload_bytes + payload > self.max_payload_bytes):
                self._counts["capacity_skips"] += 1
                return False
            self._best[key] = objective
            self._payload_bytes += payload
            self._counts["entries_peak"] = max(self._counts["entries_peak"], len(self._best))
            self._counts["payload_bytes_peak"] = max(
                self._counts["payload_bytes_peak"], self._payload_bytes)
            return False
        finally:
            # This includes key construction; do not add key_build_s to it.
            self._counts["lookup_s"] += perf_counter() - before

    def is_stale(self, state):
        """Skip an older queued label only after a strictly cheaper one exists."""
        if self.mode == "off":
            return False
        before = perf_counter()
        try:
            self._counts["pop_checks"] += 1
            key, _ = self._key(state)
            previous = self._best.get(key)
            stale = previous is not None and previous < float(state.J)
            if stale:
                self._counts["stale_pop_candidates"] += 1
                if self.mode == "exact":
                    self._counts["stale_pops"] += 1
            return bool(stale and self.mode == "exact")
        finally:
            self._counts["lookup_s"] += perf_counter() - before

    def statistics(self):
        return dict(
            mode=self.mode, max_entries=self.max_entries,
            max_payload_bytes=self.max_payload_bytes,
            **self._counts, entries=len(self._best), payload_bytes=self._payload_bytes,
            key_semantics="exact_owner_vertex_time_tick_xy_weights",
            key_fields=["owner", "vertex", "float.hex(time_s)", "tick",
                        "actual_xy.dtype/shape/C-bytes", "weights.dtype/shape/C-bytes"],
            child_denominator="nonterminal children after original J pruning, before guide",
            capacity_policy="stop_storing_new_keys_keep_existing_updates",
            payload_definition="retained actual_xy and weights bytes; excludes Python overhead",
            timing_note="lookup_s includes key_build_s; all index work is in the solver budget",
            shadow_scope="opportunities in the unpruned run, not a predicted active saving",
        )
