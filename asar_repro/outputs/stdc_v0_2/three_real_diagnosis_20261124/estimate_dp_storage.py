"""Read-only archive geometry estimates and tiny DP/STDC/Oracle diagnostics.

No production algorithm, forcing, particle archive, or old report is changed.
This does NOT construct a compressed DP implementation or run a real search.
Run from the repository root with the frozen maritime-sar interpreter.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import platform
import sys
from time import perf_counter

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from asar_repro.grid import GridGraph
from asar_repro.motion import ParticleMotion
from asar_repro.objective import score_path
from asar_repro.oracle import enumerate_oracle
from asar_repro.particle_dp import ParticleDP
from asar_repro.stdc_heuristic import STDCHeuristic


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def save(name, data):
    path = OUT / name
    # Reruns must select new output names rather than overwrite evidence.
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")


def storage_estimates():
    protocol = read(ROOT / "outputs/baseline_v1.1/b7_final/frozen_experiment_protocol.json")
    specs = [dict(name="lake_ontario", archive=protocol["particle_archive"]["path"],
                  expected_sha256=protocol["particle_archive"]["sha256"],
                  rows=17, cols=17, T=49, start=protocol["start_vertex"],
                  physical_direction_unverified=False)]
    for name, prefix in (("arctic_ocean", "additional_real_20261124"),
                         ("bay_of_fundy", "fundy_repair_20261124")):
        folder = ROOT / "outputs/stdc_v0_2" / prefix / "b3" / name
        meta = read(folder / "metadata.json")
        rows, cols = meta["config"]["grid_rows_cols"]
        specs.append(dict(name=name, archive=str((folder / "particles.npz").relative_to(ROOT)),
                          expected_sha256=meta["particle_sha256"], rows=rows, cols=cols,
                          T=meta["config"]["budget"], start=(rows // 2) * cols + cols // 2,
                          physical_direction_unverified=meta.get("direction_policy", {}).get(
                              "physical_direction_unverified", False)))
    result = []
    for spec in specs:
        archive = ROOT / spec["archive"]
        actual = sha(archive)
        assert actual == spec["expected_sha256"], "particle SHA-256 mismatch"
        rows, cols, T = spec["rows"], spec["cols"], spec["T"]
        V = rows * cols
        with np.load(archive, allow_pickle=False) as data:
            cells = data["cell_ids"].copy()
            assert cells.shape == (T + 1, 500)
        rr, cc = np.indices((rows, cols))
        sr, sc = divmod(spec["start"], cols)
        distance = (abs(rr - sr) + abs(cc - sc)).ravel()
        reachable = np.array([np.sum((distance <= t) & ((t - distance) % 2 == 0))
                              for t in range(T)], dtype=np.int64)
        suffix_groups = np.array([np.unique(cells[t + 1:].T, axis=0).shape[0]
                                  for t in range(T)], dtype=np.int64)
        full_groups = np.unique(cells.T, axis=0).shape[0]
        estimates = dict(
            current_dense_value_bytes=8 * (T + 1) * V * full_groups,
            start_depth_cone_fixed_groups_value_bytes=int(8 * full_groups * reachable.sum()),
            full_grid_suffix_groups_value_bytes=int(8 * V * suffix_groups.sum()),
            cone_suffix_groups_value_bytes=int(8 * np.dot(reachable, suffix_groups)),
            one_possible_dense_int32_vertex_index_bytes=4 * T * V,
            one_possible_int32_original_to_suffix_group_bytes=4 * T * cells.shape[1],
        )
        result.append(dict(**spec, actual_sha256=actual, sha256_verified=True,
                           full_trajectory_groups=int(full_groups),
                           exact_depth_reachable_cell_sum=int(reachable.sum()),
                           estimates=estimates,
                           value_table_MiB={k: v / 2**20 for k, v in estimates.items()
                                            if k.endswith("value_bytes")},
                           per_depth=[dict(depth=t, reachable_vertices=int(reachable[t]),
                                           exact_future_suffix_groups=int(suffix_groups[t]),
                                           fp64_cone_suffix_values_bytes=int(8 * reachable[t] * suffix_groups[t]))
                                      for t in range(T)]))
    return dict(status="passed_geometry_and_archive_checks", scenarios=result,
                premise="full rectangular 4-neighbour grid, no wait, frozen start; cells at depth t+1...T determine remaining individual-particle cost",
                formula="R_t={v: Manhattan(start,v)<=t and (t-distance)%2=0}; bytes=8*sum_t |R_t|*G_t; terminal values are implicit zero",
                limitations=["Value-table estimates only, not allocated compressed tables or measured RSS.",
                             "Mapping, indexing, feasibility, temporary arrays, Python/NumPy overhead, search OPEN, and imported libraries are additional.",
                             "Fundy 123.51 MiB of values is close to the 128 MiB managed-DP cap; fitting and runtime benefit are NOT established.",
                             "No new real-scene search or OpenDrift execution.",
                             "Fundy retains physical_direction_unverified=true."])


def incomparability_toys():
    cases = [dict(name="DP_stronger_due_to_temporal_continuity", cols=4,
                  cells=[[1], [0], [3]], belief=[1.], T=2,
                  expected_dp=1., expected_stdc=.75, expected_oracle=1.),
             dict(name="STDC_stronger_due_to_shared_detection_capacity", cols=3,
                  cells=[[0, 2], [0, 2]], belief=[.5, .5], T=1,
                  expected_dp=.5, expected_stdc=.75, expected_oracle=.75)]
    records = []
    assertions = 0
    for case in cases:
        graph = GridGraph(1, case["cols"])
        motion = ParticleMotion(np.array(case["cells"]), graph.size,
                                np.arange(len(case["belief"])))
        cfg = dict(start=1, budget=case["T"], p=np.array(case["belief"]), q=.5, motion=motion)
        dp = ParticleDP(graph, budget=case["T"], q=.5, motion=motion)
        stdc = STDCHeuristic(graph, budget=case["T"], q=.5, motion=motion)
        oracle = enumerate_oracle(graph, **cfg)
        d, s = dp(1, 0, cfg["p"]), stdc(1, 0, cfg["p"])
        for actual, expected in ((d, case["expected_dp"]), (s, case["expected_stdc"]),
                                 (oracle.J, case["expected_oracle"])):
            assert abs(actual - expected) <= 1e-12
            assertions += 1
        prefixes = []
        pending = [(1,)]
        while pending:
            prefix = pending.pop()
            depth = len(prefix) - 1
            scored = score_path(graph, prefix, **dict(cfg, budget=depth))
            best = enumerate_oracle(graph, **cfg, prefix=prefix)
            remaining = best.J - scored.J
            # Reconstruct ID weights using the same t=0/no-detection convention.
            b = cfg["p"].copy()
            sensor = np.full(graph.size, .5)
            for t, vertex in enumerate(prefix[1:], 1):
                b = motion.sense(motion.propagate(b, step=t), vertex, sensor, t)
            dv, sv = dp(prefix[-1], depth, b), stdc(prefix[-1], depth, b)
            assert dv <= remaining + 1e-12 and sv <= remaining + 1e-12
            assertions += 2
            prefixes.append(dict(path=list(prefix), remaining_oracle_J=remaining, dp=dv, stdc=sv))
            if depth < case["T"]:
                pending.extend(prefix + (v,) for v in graph.neighbors(prefix[-1]))
        records.append(dict(**case, dp=d, stdc=s, oracle=asdict(oracle), prefix_checks=prefixes))
    return dict(status="passed", cases=records, case_count=len(records),
                prefix_count=sum(len(r["prefix_checks"]) for r in records),
                numerical_assertion_count=assertions,
                finding="Neither lower bound universally dominates the other. This is not a claim of real-scenario quality improvement.",
                seed=None, seed_reason="Deterministic hand-constructed cases; no RNG used.")


if __name__ == "__main__":
    started = perf_counter()
    sources = [ROOT / "src/asar_repro" / name for name in
               ("particle_dp.py", "stdc_heuristic.py", "research_particle.py", "oracle.py", "objective.py")]
    before = {str(p.relative_to(ROOT)): sha(p) for p in sources}
    estimates = storage_estimates()
    toys = incomparability_toys()
    after = {str(p.relative_to(ROOT)): sha(p) for p in sources}
    assert before == after
    save("dp_sparse_estimate.json", estimates)
    save("dp_stdc_incomparability_oracle.json", toys)
    save("dp_diagnostic_execution.json", dict(status="passed", command=[sys.executable, *sys.argv],
         python=sys.version, numpy=np.__version__, platform=platform.platform(),
         source_sha256_before=before, source_sha256_after=after, production_sources_unchanged=True,
         source=str(Path(__file__).relative_to(ROOT)), seed=None,
         seed_reason="Deterministic geometry and hand-constructed toys; archived particle seed remains 41.",
         real_searches=0, opendrift_runs=0, wall_seconds=perf_counter()-started,
         toy_case_count=toys["case_count"], toy_prefix_count=toys["prefix_count"],
         numerical_assertion_count=toys["numerical_assertion_count"]))
    print(json.dumps(dict(status="passed", toy_cases=toys["case_count"],
          toy_prefixes=toys["prefix_count"], numerical_assertions=toys["numerical_assertion_count"],
          cone_suffix_value_MiB={r["name"]: r["value_table_MiB"]["cone_suffix_groups_value_bytes"]
                                for r in estimates["scenarios"]}), ensure_ascii=False))
