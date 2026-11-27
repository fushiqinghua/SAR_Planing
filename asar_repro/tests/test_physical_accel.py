"""Pending local validation for the cache-only physical candidate.

No tests or algorithms are executed at delivery.  Source-shape checks prevent a
cache optimization from silently changing the frozen search policy.  Numerical
checks below require exact values, not broadened tolerances.
"""
from __future__ import annotations

import ast
import copy
from pathlib import Path

import numpy as np
import pytest

from asar_repro import physical_accel as accel
from asar_repro import physical_search as original
from asar_repro.physical_model import PhysicalProblem


class _Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


@pytest.fixture
def frozen_clock(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(accel, "perf_counter", clock)
    monkeypatch.setattr(original, "perf_counter", clock)
    return clock


def _case(name="diagonal_intercept"):
    return next(c for c in original.diagnostic_cases() if c["id"] == name)


def _source_tree(module):
    return ast.parse(Path(module.__file__).read_text(encoding="utf-8"))


def _definition(tree, name):
    return next(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == name)


def _strip_docstring(body):
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        return body[1:]
    return body


def test_formal_search_loop_only_adds_charged_wrapper_and_cache_report():
    reference = copy.deepcopy(_definition(_source_tree(original), "solve_physical"))
    candidate = copy.deepcopy(_definition(_source_tree(accel), "solve_physical_accel"))
    candidate.name = reference.name

    class NormalizeCandidate(ast.NodeTransformer):
        def visit_Assign(self, node):
            if (len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "problem" and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name) and node.value.func.id == "CachedPhysicalProblem"):
                return None
            if (len(node.targets) == 1 and isinstance(node.targets[0], ast.Subscript)
                and isinstance(node.targets[0].value, ast.Name) and node.targets[0].value.id == "result"
                and isinstance(node.targets[0].slice, ast.Constant)
                and node.targets[0].slice.value in {"algorithm", "implementation_of", "cache_statistics"}):
                return None
            return self.generic_visit(node)

    candidate = NormalizeCandidate().visit(candidate)
    assert ast.dump(reference, include_attributes=False) == ast.dump(candidate, include_attributes=False)


def test_guide_arithmetic_only_replaces_the_distance_expression():
    reference_class = _definition(_source_tree(original), "_CoarseCellGuide")
    candidate_class = _definition(_source_tree(accel), "_CoarseCellGuide")
    reference = copy.deepcopy(_definition(reference_class, "remaining_cost"))
    candidate = copy.deepcopy(_definition(candidate_class, "remaining_cost"))
    normalized = []
    for node in reference.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id == "origin":
                continue
            if node.targets[0].id == "squared_distance":
                node.value = ast.parse("self._squared_distance(state.vertex)", mode="eval").body
        normalized.append(node)
    reference.body = normalized
    assert ast.dump(reference, include_attributes=False) == ast.dump(candidate, include_attributes=False)


def test_budget_check_and_elapsed_policy_match_original():
    reference = copy.deepcopy(_definition(_source_tree(original), "_Budget"))
    candidate = copy.deepcopy(_definition(_source_tree(accel), "_Budget"))
    reference.body = _strip_docstring(reference.body)
    candidate.body = _strip_docstring(candidate.body)
    assert ast.dump(reference, include_attributes=False) == ast.dump(candidate, include_attributes=False)


@pytest.mark.parametrize("name", [
    "diagonal_intercept", "late_drift", "repeat_detection",
    "special_mass", "coverage_tradeoff", "turning_footprint"])
@pytest.mark.parametrize("footprint", ["heading_square", "axis_square"])
@pytest.mark.parametrize("connectivity", [4, 8])
def test_toy_solver_and_probe_preserve_exact_histories(name, footprint, connectivity, frozen_clock):
    case = _case(name)
    problem = original.problem_from_case(case, footprint)
    options = dict(connectivity=connectivity, initial_waypoints=case["initial_waypoints"], max_seconds=30)
    reference = original.solve_physical(problem, **options)
    candidate = accel.solve_physical_accel(problem, **options)
    assert reference["status"] == candidate["status"] == "completed"
    for key in ("stop_reason", "J", "pd_final", "path", "survival", "history",
                "expanded", "generated", "peak_open", "open_count", "best"):
        assert reference[key] == candidate[key], key
    for key in ("expanded", "generated", "safe_pruned", "terminal_candidates",
                "replayed_candidates", "guide_calls", "peak_open"):
        assert reference["stats"][key] == candidate["stats"][key]
    assert candidate["cache_statistics"]["scope"].startswith("fresh")
    audit = accel.audit_equivalence(problem, **options, max_expansions=128)
    assert audit["passed"] and audit["strict_numerical_equality"]
    assert audit["stop_reason"] in ("fixed_work_complete", "frontier_exhausted")
    assert audit["expanded"] <= 128
    assert audit["stats"]["compared_states"] >= audit["generated"] + 1


@pytest.mark.parametrize("connectivity", [4, 8])
def test_identical_small_open_limit_preserves_stop_and_partial_history(connectivity, frozen_clock):
    case = _case("repeat_detection")
    problem = original.problem_from_case(case)
    options = dict(connectivity=connectivity, initial_waypoints=case["initial_waypoints"],
                   max_seconds=30, max_open=3)
    reference = original.solve_physical(problem, **options)
    candidate = accel.solve_physical_accel(problem, **options)
    assert reference["stop_reason"] == candidate["stop_reason"] == "max_open"
    assert reference["history"] == candidate["history"]
    for key in ("expanded", "generated", "peak_open", "open_count", "J"):
        assert reference[key] == candidate[key]


@pytest.mark.parametrize("scale", [1e-20, 1.0, 1e12])
@pytest.mark.parametrize("footprint", ["heading_square", "axis_square"])
@pytest.mark.parametrize("route,connectivity", [([4, 5, 4, 5, 4], 4), ([4, 2, 4, 2], 8)])
def test_transition_numbers_and_partial_end_are_exact_at_multiple_scales(scale, footprint, route, connectivity):
    case = _case("repeat_detection")
    case["cell_width_m"] *= scale
    case["times_s"] = [t * scale for t in case["times_s"]]
    case["positions_xy"] = [[[v * scale for v in point] for point in frame] for frame in case["positions_xy"]]
    problem = original.problem_from_case(case, footprint)
    cached = accel.CachedPhysicalProblem(problem)
    reference_state, candidate_state = problem.initial_state(), cached.initial_state()
    for target in route[1:]:
        parent_weights = candidate_state.weights.copy()
        next_reference = problem.advance(reference_state, target, connectivity)
        next_candidate = cached.advance(candidate_state, target, connectivity)
        accel._assert_state_equal(next_reference, next_candidate)
        assert not np.shares_memory(next_candidate.weights, candidate_state.weights)
        np.testing.assert_array_equal(candidate_state.weights, parent_weights)
        reference_state, candidate_state = next_reference, next_candidate
    assert reference_state.terminal and candidate_state.terminal
    assert candidate_state.last_edge_partial == (connectivity == 8)
    assert cached.cache_statistics()["edge_hits"] > 0


def test_edge_cache_does_not_admit_diagonal_to_four_neighbor_graph():
    problem = original.problem_from_case(_case())
    cached = accel.CachedPhysicalProblem(problem)
    assert cached.edge_duration_s(4, 2, 8) == problem.edge_duration_s(4, 2, 8)
    with pytest.raises(ValueError, match="illegal"):
        cached.edge_duration_s(4, 2, 4)
    for bad in (True, 1.5, -1, 9):
        with pytest.raises(ValueError):
            cached.vertex_xy(bad)
    for connectivity in (5, True, 4.0):
        with pytest.raises(ValueError):
            cached.neighbors(4, connectivity)


def test_cached_vertices_and_geometry_cannot_be_mutated_by_a_state():
    problem = original.problem_from_case(_case("repeat_detection"))
    cached = accel.CachedPhysicalProblem(problem)
    vertex = cached.vertex_xy(5)
    with pytest.raises(ValueError):
        vertex[0] = 999
    state = cached.advance(cached.initial_state(), 5, 4)
    with pytest.raises(ValueError):
        state.actual_xy[0] = 999
    assert np.array_equal(cached.vertex_xy(5), problem.vertex_xy(5))
    assert not state.weights.flags.writeable
    untouched = accel.CachedPhysicalProblem(problem)
    assert untouched.cache_statistics()["vertex_entries"] == 0
    assert untouched.cache_statistics()["directed_edge_entries"] == 0


def test_distance_lru_has_a_fixed_payload_limit_and_exact_evicted_values(monkeypatch, frozen_clock):
    problem = original.problem_from_case(_case())
    cached = accel.CachedPhysicalProblem(problem)
    vector_bytes = problem.size * np.dtype(float).itemsize
    monkeypatch.setattr(accel, "DISTANCE_CACHE_LIMIT_BYTES", 2 * vector_bytes)
    guide = accel._CoarseCellGuide(cached, accel._Budget(0, 30))
    for vertex in (4, 1, 4, 5):
        value = guide._squared_distance(vertex)
        expected = np.square(guide.centres - problem.vertex_xy(vertex)).sum(axis=1)
        np.testing.assert_array_equal(value, expected)
        assert not value.flags.writeable
    info = cached.cache_statistics()["distance_vectors"]
    assert info["hits"] == 1 and info["misses"] == 3 and info["evictions"] == 1
    assert info["entries"] == 2 and info["peak_bytes"] == 2 * vector_bytes
    assert list(guide._distance_vectors) == [4, 5]
    np.testing.assert_array_equal(guide._squared_distance(1),
                                  np.square(guide.centres - problem.vertex_xy(1)).sum(axis=1))
    assert guide._distance_stats["current_bytes"] <= 2 * vector_bytes


def test_oversized_distance_vector_is_not_retained(monkeypatch, frozen_clock):
    problem = original.problem_from_case(_case())
    cached = accel.CachedPhysicalProblem(problem)
    monkeypatch.setattr(accel, "DISTANCE_CACHE_LIMIT_BYTES", 1)
    guide = accel._CoarseCellGuide(cached, accel._Budget(0, 30))
    guide._squared_distance(4)
    assert guide._distance_stats["oversized_vectors"] == 1
    assert guide._distance_stats["entries"] == guide._distance_stats["current_bytes"] == 0


def test_seed_and_candidate_replay_delegate_to_original_problem(monkeypatch, frozen_clock):
    problem = original.problem_from_case(_case())
    cached = accel.CachedPhysicalProblem(problem)

    def forbidden(*args, **kwargs):
        raise AssertionError("full replay used accelerated transition")

    monkeypatch.setattr(accel.CachedPhysicalProblem, "_advance", forbidden)
    assert cached.replay([4, 5, 2], 4) == problem.replay([4, 5, 2], 4)


def test_cache_setup_is_inside_budget_and_no_seed_is_free(monkeypatch, frozen_clock):
    setup = accel.CachedPhysicalProblem.__init__

    def delayed(self, problem):
        setup(self, problem)
        frozen_clock.value = 2.0

    monkeypatch.setattr(accel.CachedPhysicalProblem, "__init__", delayed)
    case = _case()
    result = accel.solve_physical_accel(original.problem_from_case(case), connectivity=8,
        initial_waypoints=case["initial_waypoints"], max_seconds=1.0)
    assert result["stop_reason"] == "max_seconds"
    assert result["best"] is None and result["history"] == []
    assert result["wall_s"] >= 2.0


def test_zero_budget_creates_no_cache_or_free_incumbent(frozen_clock):
    case = _case()
    result = accel.solve_physical_accel(original.problem_from_case(case), connectivity=8,
        initial_waypoints=case["initial_waypoints"], max_seconds=0.0)
    assert result["history"] == [] and result["best"] is None
    assert result["cache_statistics"] is None


def test_probe_rejects_even_one_ulp_guide_mismatch(monkeypatch, frozen_clock):
    method = accel._CoarseCellGuide.remaining_cost

    def perturbed(self, state):
        return np.nextafter(method(self, state), np.inf)

    monkeypatch.setattr(accel._CoarseCellGuide, "remaining_cost", perturbed)
    case = _case()
    audit = accel.audit_equivalence(original.problem_from_case(case), connectivity=8,
        initial_waypoints=case["initial_waypoints"], max_expansions=128, max_seconds=30)
    assert not audit["passed"]
    assert audit["stop_reason"] == "audit_error"
    assert "exact guide value mismatch" in audit["error"]["message"]


def test_probe_timeout_never_counts_as_equivalence_pass(monkeypatch, frozen_clock):
    method = accel.CachedPhysicalProblem._advance

    def delayed(self, *args, **kwargs):
        result = method(self, *args, **kwargs)
        frozen_clock.value = 2.0
        return result

    monkeypatch.setattr(accel.CachedPhysicalProblem, "_advance", delayed)
    case = _case()
    audit = accel.audit_equivalence(original.problem_from_case(case), connectivity=8,
        initial_waypoints=case["initial_waypoints"], max_expansions=128, max_seconds=1.0)
    assert not audit["passed"]
    assert audit["stop_reason"] == "audit_deadline"
    assert not audit["performance_claim"]


def test_probe_work_limit_is_explicit_and_not_a_search_budget(frozen_clock):
    case = _case("repeat_detection")
    audit = accel.audit_equivalence(original.problem_from_case(case), connectivity=8,
        initial_waypoints=case["initial_waypoints"], max_expansions=2, max_seconds=30)
    assert audit["passed"] and audit["stop_reason"] == "fixed_work_complete"
    assert audit["expanded"] == 2
    assert audit["generated"] <= 16
    assert len(audit["pop_trace_sha256"]) == 64

