"""Validate the gated solver and audit its live-prefix selection at fixed work."""
from __future__ import annotations

import argparse
import heapq
from hashlib import sha256
from pathlib import Path
from struct import pack
import subprocess
import sys
from time import perf_counter
from unittest.mock import patch
import xml.etree.ElementTree as ET

from asar_repro import physical_refinement as refinement
from frontier_probe import frontier_hash
from h3_protocol import digest, read, save
from prepare_eight_neighbor_h3 import load_h3_input
import run_diagnostic as prior
import run_eight_neighbor_h3 as h3


HERE = Path(__file__).resolve().parent
SEEDS = (3401, 4401, 4402, 4501, 4601)
WORK = {3401: 1024, 4401: 1024, 4402: 2048, 4501: 4096, 4601: 6144}
HANDOFF = 1024
TRACKED = ("gated_solver.py", "test_gated_solver.py", "check_fixed_work.py")
ORIGINAL_TESTS = (
    "tests/test_physical_search.py",
    "tests/test_physical_lazy_prefix.py",
    "tests/test_physical_refinement.py",
    "tests/test_eight_neighbor_h3_runner.py",
)


def implementation_hashes():
    return {name: digest(HERE / name) for name in TRACKED}


def evidence_files(root, paths):
    return {path.relative_to(root).as_posix(): digest(path) for path in paths}


def validate(out):
    out.mkdir(parents=True, exist_ok=True)
    logdir = out / "toy"
    logdir.mkdir()
    xml = logdir / "pytest.xml"
    logs = (logdir / "stdout.log", logdir / "stderr.log")
    cmd = [
        sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
        f"--basetemp={logdir / 'scratch'}", f"--junitxml={xml}",
        str(HERE / "test_gated_solver.py"), *ORIGINAL_TESTS,
    ]
    command = logdir / "command.json"
    before = implementation_hashes()
    save(command, dict(argv=cmd, cwd=str(h3.ROOT), implementation_sha256=before))
    env = dict(h3.worker_env(), PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    with logs[0].open("xb") as stdout, logs[1].open("xb") as stderr:
        result = subprocess.run(cmd, cwd=h3.ROOT, env=env, stdout=stdout, stderr=stderr)
    files = [command, *logs]
    cases, bad = [], []
    if xml.is_file():
        files.append(xml)
        cases = ET.parse(xml).findall(".//testcase")
        bad = [case for case in cases if any(
            case.find(tag) is not None for tag in ("failure", "error", "skipped")
        )]
    passed = result.returncode == 0 and bool(cases) and not bad and before == implementation_hashes()
    save(out / "validation.json", dict(
        status="passed" if passed else "failed", tests=len(cases), failed_or_skipped=len(bad),
        returncode=result.returncode, files=evidence_files(out, files),
        implementation_sha256=before,
    ))
    if not passed:
        raise RuntimeError(f"Toy/Oracle gate failed. See {logs[0]}")
    print(f"Passed {len(cases)} toy/Oracle and frozen control tests.", flush=True)


def check_gate(out):
    evidence = read(out / "validation.json")
    if (evidence["status"] != "passed"
            or evidence["implementation_sha256"] != implementation_hashes()
            or any(digest(out / name) != sha for name, sha in evidence["files"].items())):
        raise ValueError("Fixture validation is missing or changed.")


def verified_old_run(task_dir):
    record = read(task_dir / "record.json")
    if (record["status"] != "valid"
            or record["result_sha256"] != digest(task_dir / "result.json")):
        raise ValueError(f"Old evidence changed: {task_dir}")
    return read(task_dir / "result.json")


def serial_sha(entries):
    result = sha256()
    for entry in entries:
        result.update(pack("<q", entry["serial"]))
    return result.hexdigest()


def capture_prefix(problem, init, solver_options, limit):
    """Capture immutable references from C0 following complete main expansions."""
    live = cached = None
    check = None
    popped = 0
    old = refinement.heapq
    cached_type = refinement.CachedPhysicalProblem

    class Heap:
        heappush = staticmethod(old.heappush)

        @staticmethod
        def heappop(heap):
            nonlocal live, check, popped
            live = heap
            if popped == HANDOFF:
                check = frontier_hash(heap)
            popped += 1
            return old.heappop(heap)

    def capture_cache(p):
        nonlocal cached
        cached = cached_type(p)
        return cached

    start = perf_counter()
    with patch.object(refinement, "heapq", Heap), patch.object(refinement, "CachedPhysicalProblem", capture_cache):
        result = refinement.solve_physical_refinement(
            problem, connectivity=8, initial_waypoints=init,
            max_seconds=120, max_expansions=limit, **solver_options,
        )
    if result["stop_reason"] != "max_expansions" or result["expanded"] != limit or result["error"]:
        raise AssertionError("Native C0 did not reach the exact expansion checkpoint")
    if popped != limit:
        raise AssertionError("The fixed-work fixture no longer has a one-to-one pop/expansion prefix")
    if live is None or len(live) != result["open_count"]:
        raise AssertionError("C0 OPEN recorder lost the live heap")
    trace = result["diagnostics"]["pop_trace"]
    return result, live, cached, dict(
        elapsed_s=perf_counter() - start, open_sha256=frontier_hash(live),
        prior_pops_sha256=serial_sha(trace), handoff_open_sha256=check,
        handoff_pops_sha256=serial_sha(trace[:HANDOFF]),
    )


def check_handoff(seed, limit, check, result):
    old = verified_old_run(prior.OUT / "runs" / f"fixed_{seed}_r0_single_global")
    handoff = old["probe"]["handoff"]
    known = dict(
        handoff_open_sha256=handoff["open_sha256"],
        handoff_pops_sha256=handoff["prior_pops_sha256"],
    )
    if check["handoff_pops_sha256"] != known["handoff_pops_sha256"]:
        raise AssertionError(f"Frozen first {HANDOFF} C0 pops changed for seed {seed}")
    current_open = check["open_sha256"] if limit == HANDOFF else check["handoff_open_sha256"]
    if current_open != known["handoff_open_sha256"]:
        raise AssertionError(f"Frozen C0 OPEN at {HANDOFF} changed for seed {seed}")
    if limit == old["inner"]["expanded"]:
        for key in ("expanded", "generated", "open_count", "peak_open", "J", "pd_final", "waypoints"):
            if result[key] != old["inner"][key]:
                raise AssertionError(f"Frozen exact-work C0 result changed on {seed}: {key}")
        if check["prior_pops_sha256"] != old["probe"]["pop_sha256"]:
            raise AssertionError(f"Exact-work C0 pop hash changed on {seed}")
    return old["task"]


def frozen_witness_rank(live, selected):
    """Compare only after real OPEN handles have already been shortlisted."""
    path = prior.OUT / "capacity_4601_delivery/runs/extended_4601_r0_C0_capacity_reserve"
    historic = verified_old_run(path)
    witness = tuple(historic["replay"]["waypoints"])
    pending = next((entry for entry in live if witness[:len(entry[3])] == entry[3]), None)
    if pending is None:
        raise AssertionError("The frozen 4601 witness prefix is absent from its audited OPEN")
    priority, serial, state, prefix = pending
    lower = lambda entry: entry[:2] < (priority, serial)
    return dict(
        depth=len(prefix) - 1, vertex=state.vertex, tick=state.tick,
        global_rank=1 + sum(lower(entry) for entry in live),
        tick_rank=1 + sum(lower(entry) for entry in live if entry[2].tick == state.tick),
        same_tick=sum(entry[2].tick == state.tick for entry in live),
        selected=any(entry is pending for entry in selected), route_source=str(path),
        route_result_sha256=digest(path / "result.json"),
    )


def run_case(implementation, protocol, seed):
    expected = protocol["reference"][str(seed)]
    case = expected["case"]
    p, _, _, input_record = load_h3_input(
        prior.SOURCE, case["case"], case["h3_evidence"], "heading_square",
    )
    init = expected["S30"]["waypoints"]
    if (input_record["particle_sha256"] != expected["S30"]["particle_sha256"]
            or p.q != .78 or p.speed_m_s != 20):
        raise ValueError(f"Frozen physical inputs or model changed on {seed}")
    score, scalar = h3.dual_replay(p, init, 8)
    if abs(score["J"] - expected["S30"]["J"]) > 1e-8 or abs(score["J"] - scalar["J"]) > 1e-8:
        raise AssertionError(f"S30 score differs from the archived independent check on {seed}")
    limit = WORK[seed]
    result, live, cached, check = capture_prefix(p, init, protocol["solver"], limit)
    old = check_handoff(seed, limit, check, result)
    max_tick = max(int(tick) for tick in result["diagnostics"]["histograms"]["expanded_tick"])
    first_terminal = result["diagnostics"]["first_search_terminal_generated_s"]
    branch = implementation.entry_mode(score["survival"])
    previous_open = result["diagnostics"]["frontier_snapshots"][0]["open_count"]
    eligible = implementation.rescue_eligible(
        first_terminal=first_terminal, previous_open=previous_open, current_open=len(live),
    )
    selected = implementation.select_prefixes(live, max_tick=max_tick) if eligible and branch == "single_global" else []
    lookup = {id(entry) for entry in live}
    if len({id(entry) for entry in selected}) != len(selected):
        raise AssertionError("Shortlist contains repeated references to the same native state")
    if not all(id(entry) in lookup and not entry[2].terminal for entry in selected):
        raise AssertionError("Shortlist contains a fabricated or terminal state")
    if seed == 3401 and branch != "lazy":
        raise AssertionError("The early-cover 3401 fixture did not retain Lazy")
    if seed == 4501 and (branch != "single_global" or first_terminal is None or eligible or selected):
        raise AssertionError("4501 should remain global once native search has a terminal")
    if seed == 4601 and (branch != "single_global" or first_terminal is not None or not eligible or not selected):
        raise AssertionError("4601 should present live prefixes at the stalled checkpoint")
    selected_rows = [
        dict(priority=entry[0], serial=entry[1], tick=entry[2].tick, vertex=entry[2].vertex,
             time_s=entry[2].time_s, incremental_J=entry[2].J, path=list(entry[3]))
        for entry in selected
    ]
    continuation = None
    if seed == 4601:
        start = perf_counter()
        guide = refinement._CoarseCellGuide(cached, refinement._Budget(start, 4))
        candidate, details = implementation.bounded_completion(
            cached, guide, selected, connectivity=8, guide_weight=protocol["solver"]["guide_weight"],
            width=32, deadline=start + 3, incumbent_j=result["J"],
        )
        continuation = dict(
            wall_s=perf_counter() - start, info=details, incumbent_J=result["J"], better_route=None,
        )
        if candidate is not None:
            route = tuple(candidate["waypoints"])
            if not any(route[:len(entry[3])] == entry[3] for entry in selected):
                raise AssertionError("Bounded continuation did not extend a live OPEN path")
            actual, scalar = h3.dual_replay(p, route, 8)
            if (abs(actual["J"] - candidate["J"]) > 1e-8
                    or abs(actual["pd_final"] - candidate["pd_final"]) > 1e-8
                    or abs(actual["J"] - scalar["J"]) > 1e-8
                    or actual["J"] >= result["J"] - 1e-10):
                raise AssertionError("Candidate violates the original J objective or scorer")
            continuation["better_route"] = dict(J=actual["J"], Pd=actual["pd_final"], path=list(route))
    if frontier_hash(live) != check["open_sha256"]:
        raise AssertionError("Candidate selection or continuation mutated the native OPEN")
    marker = frozen_witness_rank(live, selected) if seed == 4601 else None
    return dict(
        seed=seed, fixed_expansions=limit, old_control=old,
        prefix_hashes=check, input_sha256=input_record["particle_sha256"], S30_J=score["J"],
        S30_coverage_ratio=implementation.coverage_ratio(score["survival"]), dispatch=branch,
        first_main_terminal_s=first_terminal, main_terminals=result["stats"]["terminal_candidates"],
        rescue_eligible_at_checkpoint=eligible and branch == "single_global",
        max_expanded_tick=max_tick, open_count=len(live), generated=result["generated"],
        native_result=dict(J=result["J"], Pd=result["pd_final"], path=result["waypoints"]),
        shortlist=selected_rows, witness_marker_after_selection=marker, continuation=continuation,
    )


def fixed_work(out):
    check_gate(out)
    import gated_solver

    prior_proof = prior.lock()
    rows = [run_case(gated_solver, prior_proof, seed) for seed in SEEDS]
    result_file = out / "fixed_cases.json"
    save(result_file, dict(
        cases=rows, purpose="Matched-work instrumentation and fixed-checkpoint continuation, outside the 30 s comparison",
        prior_protocol_sha256=digest(prior.OUT / "protocol.json"),
        H3_source_sha256=prior.source_locks(),
    ))
    save(out / "fixed_work.json", dict(
        status="passed", files=evidence_files(out, [result_file]),
        validation_sha256=digest(out / "validation.json"), implementation_sha256=implementation_hashes(),
    ))
    print(f"Fixed-work prefix evidence passed for {len(rows)} cases.", flush=True)


def write_cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("validate", "fixed"))
    parser.add_argument("--out", type=Path, default=HERE / "results/local_r1")
    args = parser.parse_args()
    out = args.out.resolve() / "preflight"
    if args.stage == "validate":
        validate(out)
    else:
        fixed_work(out)


if __name__ == "__main__":
    write_cli()
