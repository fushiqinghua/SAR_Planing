"""Fail-fast synthetic audit of resumable scheduling, sparse guides and compact DP.

This script creates a fresh output directory. It never runs real forcing or
changes historical fixtures, objectives, evaluator code or older reports.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter
import traceback

import numpy as np

from asar_repro.heuristic import Heuristic
from asar_repro.motion import ParticleMotion
from asar_repro.objective import score_path
from asar_repro.oracle import enumerate_oracle
from asar_repro.particle_dp import ParticleDP
from asar_repro.research_particle import ParticleGuide
from audit_anytime_search import independent_prefix_optima, _native, _save
from audit_optimization import verify
from audit_window_search import cases, reference_path
from run_stdc_random_audit import make_case
from stdc_validation_guards import require, freeze_case, MODES

ROOT = Path(__file__).resolve().parents[1]
ATOL = 1e-10
RANDOM_SEEDS = tuple(range(100, 180))
SOURCE_PATHS = (
    "scripts/audit_adaptive.py", "scripts/audit_anytime_search.py",
    "scripts/audit_window_search.py", "scripts/run_stdc_random_audit.py",
    "scripts/stdc_validation_guards.py", "src/asar_repro/resumable_search.py",
    "src/asar_repro/adaptive_search.py", "src/asar_repro/short_window_rollout.py",
    "src/asar_repro/sparse_particle_guide.py", "src/asar_repro/compact_particle_dp.py",
    "src/asar_repro/particle_dp.py", "src/asar_repro/research_particle.py",
    "src/asar_repro/stdc_heuristic.py", "src/asar_repro/objective.py",
    "src/asar_repro/oracle.py", "src/asar_repro/motion.py",
)


def fingerprint_sources():
    return {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
            for name in SOURCE_PATHS}


def emit(stream, row):
    stream.write(json.dumps(_native(row), ensure_ascii=False, allow_nan=False)+"\n")
    stream.flush()


def random_audit(out):
    from asar_repro.compact_particle_dp import CompactParticleDP
    from asar_repro.sparse_particle_guide import SparseParticleGuide
    inputs = out/"inputs"
    inputs.mkdir()
    count = case_count = compact_count = sparse_count = 0
    max_over = max_compact_error = max_guide_error = 0.
    roots = []
    with (out/"prefixes.jsonl").open("x", encoding="utf-8") as stream:
        for kind in ("matrix", "particles"):
            for seed in RANDOM_SEEDS:
                current = dict(stage="independent_oracle", kind=kind, seed=seed)
                _save(out/"last_checked.json", current)
                grid, start, T, p, q, motion = make_case(seed, kind)
                cfg = dict(start=start, budget=T, p=p, q=q, motion=motion)
                sha = freeze_case(inputs, f"{kind}_{seed}", grid, cfg)
                best, best_paths, complete = independent_prefix_optima(grid, cfg)
                oracle = enumerate_oracle(grid, **cfg)
                require(abs(best[(start,)]-oracle.J) <= ATOL,
                        f"independent Oracles disagree: {kind}/{seed}")
                require(complete == oracle.complete_paths, "independent full-path count differs")
                bounds = {mode: Heuristic(grid, budget=T, q=q, motion=motion, mode=mode)
                          for mode in MODES}
                dense = compact = sparse = fast = None
                if isinstance(motion, ParticleMotion):
                    current = dict(stage="compact_build", kind=kind, seed=seed,
                                   input_sha256=sha)
                    _save(out/"last_checked.json", current)
                    dense = ParticleDP(grid, budget=T, q=q, motion=motion)
                    compact = CompactParticleDP(grid, start=start, budget=T, q=q, motion=motion)
                    require(dense.ready and compact.ready, "toy DP construction interrupted")
                    fast = ParticleGuide(grid, budget=T, q=q, motion=motion)
                    sparse = SparseParticleGuide(grid, budget=T, q=q, motion=motion)
                # Nonmonotone query depths exercise arbitrary-depth search use.
                prefixes = list(best)
                np.random.default_rng(seed+3_000_000).shuffle(prefixes)
                for prefix in prefixes:
                    d = len(prefix)-1
                    current = dict(stage="prefix_bounds", kind=kind, seed=seed,
                        input_sha256=sha, prefix=prefix)
                    _save(out/"last_checked.json", current)
                    replay = score_path(grid, prefix, **dict(cfg, budget=d))
                    remaining = best[prefix]-replay.J
                    values = {name: h(prefix[-1], d, replay.final_belief)
                              for name, h in bounds.items()}
                    row = dict(current, prefix_J=replay.J, exact_remaining=remaining,
                               best_full_path=best_paths[prefix], bounds=values)
                    if compact is not None:
                        hd = dense(prefix[-1], d, replay.final_belief)
                        hc = compact(prefix[-1], d, replay.final_belief)
                        err = abs(hc-hd)
                        values.update(dense_dp=hd, compact_dp=hc,
                                      stdc_compact=max(values["stdc_lb"], hc))
                        row["compact_dense_error"] = err
                        _save(out/"last_checked.json", row)
                        require(err <= ATOL,
                                f"compact/dense mismatch: {kind}/{seed}/{prefix}: {hc} vs {hd}")
                        max_compact_error = max(max_compact_error, err)
                        compact_count += 1
                        cfast, csparse = [], []
                        hf = fast(prefix[-1], d, replay.final_belief, choices=cfast)
                        hs = sparse(prefix[-1], d, replay.final_belief, choices=csparse)
                        row["guides"] = dict(reference=hf, sparse=hs,
                                             reference_choices=cfast, sparse_choices=csparse)
                        _save(out/"last_checked.json", row)
                        require(abs(hf-hs) <= ATOL and cfast == csparse,
                                f"sparse guide changed Algorithm 2: {kind}/{seed}/{prefix}")
                        max_guide_error = max(max_guide_error, abs(hf-hs))
                        sparse_count += 1
                    _save(out/"last_checked.json", row)
                    for name, value in values.items():
                        require(np.isfinite(value) and -ATOL <= value <= remaining+ATOL,
                                f"inadmissible {name}: {kind}/{seed}/{prefix}: {value} > {remaining}")
                        max_over = max(max_over, value-remaining)
                    require(all(values["stdc_lb"]+ATOL >= values[m] for m in MODES),
                            f"historical STDC dominance failure: {kind}/{seed}/{prefix}")
                    emit(stream, row)
                    count += 1
                    if d == 0:
                        roots.append(row)
                case_count += 1
                if (seed-99) % 20 == 0:
                    print(f"{kind}: cases={case_count} prefixes={count}", flush=True)
    require(case_count == 160 and count == 18024, "incomplete random schedule")
    require(compact_count == 9012 and sparse_count == 9012, "incomplete particle prefix checks")
    return dict(status="passed", cases=case_count, prefix_evaluations=count,
        compact_dense_prefix_checks=compact_count, sparse_guide_prefix_checks=sparse_count,
        max_overestimate=max_over, max_compact_dense_error=max_compact_error,
        max_guide_error=max_guide_error, roots=roots, violations=0,
        random_seeds=RANDOM_SEEDS, query_order="per-case seed+3000000 shuffle",
        sparse_scope="particle prefixes; matrix search retains the reference guide",
        data_type="synthetic_toy", global_epsilon_certified=False)


def small_audit(out):
    from asar_repro.adaptive_search import search_adaptive
    inputs = out/"inputs"
    inputs.mkdir()
    rows = []
    count = 0
    local_calls = {}
    with (out/"searches.jsonl").open("x", encoding="utf-8") as stream:
        for kind, seed, grid, cfg, derivation in cases():
            sha = freeze_case(inputs, f"{kind}_{seed}", grid, cfg)
            current = dict(stage="small_oracle", kind=kind, seed=seed, input_sha256=sha)
            _save(out/"last_checked.json", current)
            initial = reference_path(grid, cfg, seed)
            _save(inputs/f"{kind}_{seed}_initial_path.json",
                  dict(path=initial, seed=seed, data_type="synthetic_toy"))
            optimum = enumerate_oracle(grid, **cfg).J
            methods = [
                ("direct", dict(schedule="direct")),
                ("recycle", dict(schedule="recycle")),
                ("bursts", dict(schedule="bursts", diversity_slots=4)),
            ]
            if isinstance(cfg["motion"], ParticleMotion):
                methods += [
                    ("compact_only", dict(schedule="direct", dp_kind="compact",
                                          dp_mode="only", efficient_guide=True)),
                    ("compact_max", dict(schedule="direct", dp_kind="compact",
                                         dp_mode="max", efficient_guide=True)),
                ]
            for name, kwargs in methods:
                current = dict(stage="small_search", kind=kind, seed=seed,
                               method=name, input_sha256=sha)
                _save(out/"last_checked.json", current)
                started = perf_counter()
                result, phases, prep, _ = search_adaptive(
                    grid, **cfg, initial_path=initial, global_chunk=2, burst_work=4,
                    local_fraction=.5, **kwargs)
                row = dict(current, result=asdict(result), phases=phases, preprocessing=prep,
                           wall_s=perf_counter()-started, oracle_J=optimum,
                           data_type="synthetic_toy", derivation=derivation)
                _save(out/"last_checked.json", row)
                checks = verify(grid, cfg, result, optimum)
                require(result.expanded == sum(p["expanded"] for p in phases),
                        f"phase work mismatch: {kind}/{seed}/{name}")
                require(result.expanded == result.stats["work_expanded"],
                        f"reported work mismatch: {kind}/{seed}/{name}")
                require(result.stats["state_merging"] is False, "path states merged")
                require(result.stats["guide_used_for_pruning"] is False, "guide used for pruning")
                previous_work = -1
                for event in result.incumbent_history:
                    work = event.get("work_expanded", event["expanded"])
                    require(previous_work <= work <= result.expanded,
                            f"history work accounting mismatch: {kind}/{seed}/{name}")
                    previous_work = work
                if name.startswith("compact_"):
                    require(prep["dp"]["status"] == "completed" and not prep["dp_fallback"],
                            "compact toy silently fell back")
                calls = sum(p["name"] == "short_window" for p in phases)
                local_calls[name] = local_calls.get(name, 0)+calls
                row["checks"] = checks
                emit(stream, row)
                rows.append(row)
            count += 1
            print(f"small cases={count} searches={len(rows)} seed={seed}", flush=True)
    require(count == 45 and len(rows) == 145, "incomplete small search schedule")
    require(local_calls.get("bursts", 0) > 0, "burst schedule never exercised local work")
    return dict(status="passed", cases=count, searches=len(rows),
        max_J_error=max(r["checks"]["oracle_error"] for r in rows),
        max_replay_error=max(r["checks"]["replay_error"] for r in rows),
        local_phase_calls=local_calls, historical_seeds=list(range(15000, 15035)),
        derived_seeds=list(range(15000, 15005)), data_type="synthetic_toy",
        limits=None, global_epsilon_certified=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("random", "small", "all"))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    started = perf_counter()
    before = {}
    command = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]]
    try:
        before = fingerprint_sources()
        protocol = dict(command=command, tolerance=ATOL, data_type="synthetic_toy",
            expected_random_cases=160, expected_random_prefixes=18024,
            expected_compact_prefixes=9012, expected_small_cases=45, expected_small_searches=145,
            random_seeds=RANDOM_SEEDS, historical_seeds=list(range(15000, 15035)),
            derived_seeds=list(range(15000, 15005)), source_sha256=before,
            scope="finite numerical validation, not a general epsilon guarantee",
            no_state_merging=True, no_real_forcing=True)
        _save(out/"protocol.json", protocol)
        results = {}
        for stage in ("random", "small") if args.stage == "all" else (args.stage,):
            folder = out/stage if args.stage == "all" else out
            if folder != out:
                folder.mkdir()
            result = (random_audit if stage == "random" else small_audit)(folder)
            _save(folder/"stage_summary.json", result)
            results[stage] = result
        after = fingerprint_sources()
        require(before == after, "audit sources changed while executing")
        summary = dict(status="passed", stages=results, command=command,
            source_sha256_before=before, source_sha256_after=after,
            sources_unchanged=True, wall_s=perf_counter()-started,
            global_epsilon_certified=False)
    except Exception as exc:
        summary = dict(status="blocked", error=str(exc), traceback=traceback.format_exc(),
            command=command, source_sha256_before=before, wall_s=perf_counter()-started,
            global_epsilon_certified=False)
        _save(out/"summary.json", summary)
        raise
    _save(out/"summary.json", summary)
    print(json.dumps({"status":"passed", "stages":list(results),
                      "wall_s":summary["wall_s"]}), flush=True)


if __name__ == "__main__":
    main()

