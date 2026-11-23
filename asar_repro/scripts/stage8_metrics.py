"""Normalize the archived experiments, retaining their original measurement scopes."""

import csv
import json
from pathlib import Path

import numpy as np
import yaml

from asar_repro.objective import score_path
from asar_repro.scenarios import config_digest, digest, drift_config
from report_stage7 import audit_runs
from validate_stage3 import toy_cases
from asar_repro.grid import GridGraph


FIELDS = """stage scenario_id scenario_source forcing_kind data_availability seed input_seed
algorithm_seed n_particles object_type map_rows map_cols cell_width_m dt_seconds T start_vertex q
algorithm heuristic_mode epsilon J Pd_T reference_kind J_reference relative_J elapsed_s
timing_scope warm_start_s total_wall_s generated expanded pruned max_open peak_process_MiB
status stop_reason timed_out incumbent_source theory_certified config_hash archive_sha256
git_commit source_file""".split()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def counters(row):
    return dict(
        expanded=row["expanded"],
        generated=row["generated"],
        pruned=row["pruned"],
        max_open=row["peak_open"],
    )


def collect(root):
    metrics = root / "outputs/metrics"
    rows = []

    def add(
        stage,
        name,
        source,
        artifact,
        config_hash,
        shape,
        T,
        start,
        q,
        method,
        J,
        pd,
        *,
        seed=None,
        input_seed=None,
        algo_seed=None,
        ref=None,
        **fields,
    ):
        row = dict(
            stage=stage,
            scenario_id=name,
            scenario_source=source,
            source_file=artifact.relative_to(root).as_posix(),
            config_hash=config_hash,
            seed=seed,
            input_seed=input_seed,
            algorithm_seed=algo_seed,
            map_rows=shape[0],
            map_cols=shape[1],
            T=T,
            start_vertex=start,
            q=json.dumps(q) if isinstance(q, list) else q,
            algorithm=method,
            J=float(J),
            Pd_T=float(pd),
            status="completed",
        )
        if ref is not None:
            row.update(
                reference_kind=ref[0],
                J_reference=ref[1],
                relative_J=float(J) / ref[1] if ref[1] else None,
            )
        row.update(fields)
        rows.append(row)

    path = metrics / "stage1_toy.json"
    for c in read_json(path)["cases"]:
        inputs = {k: v for k, v in c.items() if k not in ("J", "pd_final", "final_belief")}
        add(
            1,
            c["case"],
            "hand_calculation",
            path,
            config_digest(inputs),
            c["shape"],
            c["T"],
            c["start"],
            c["q"],
            "score_path",
            c["J"],
            c["pd_final"],
        )

    path = metrics / "stage2_comparison.json"
    stage2 = read_json(path)
    cases = {c["case"]: c for c in stage2["inputs"]}
    exact = {r["case"]: r["J"] for r in stage2["results"] if r["solver"] == "dfs"}
    for r in stage2["results"]:
        c = cases[r["case"]]
        if (
            abs(r["J"] - exact[c["case"]]) > stage2["abs_tolerance"]
            or r["replay_error"] > stage2["abs_tolerance"]
        ):
            raise ValueError(f"{c['case']}: stage 2 Oracle regression")
        add(
            2,
            c["case"],
            "oracle_toy",
            path,
            config_digest(c),
            [c["size"]] * 2,
            c["T"],
            c["start"],
            c["q"],
            r["solver"],
            r["J"],
            r["pd_final"],
            seed=c["seed"],
            input_seed=c["seed"],
            ref=("DFS", exact[c["case"]]),
            elapsed_s=r["runtime_s"],
            timing_scope="solver",
            heuristic_mode=None if r["solver"] == "dfs" else "zero",
            **counters(r),
        )

    path = metrics / "heuristic_validity_report.json"
    validity = read_json(path)
    if digest(root / validity["fixture"]["path"]) != validity["fixture"]["sha256"]:
        raise ValueError("archived counterexample fingerprint mismatch")
    seeds = {"dynamic_seed17": 17, "dynamic_seed213": 213, "appendix_b": validity["fixture"]["seed"]}
    for name, grid, args in toy_cases(root / validity["fixture"]["path"]):
        c = validity["cases"][name]
        if any(c["lower_bound_audit"][mode]["violations"] for mode in ("zero", "mass_lb")):
            raise ValueError(f"{name}: lower bound audit failed")
        # Hash the actual transition arrays independently of timings and search outcomes.
        kernels = [
            [args["motion"].propagate(b, step=t).tolist() for b in np.eye(grid.size)]
            for t in range(1, args["budget"] + 1)
        ]
        cfg = {k: c[k] for k in ("shape", "budget", "start", "p", "q")} | {"P": kernels}
        for r in c["search_runs"]:
            if r["mode"] == "paper_greedy" and r["theory_certified"]:
                raise ValueError("unexpected certification of the paper heuristic")
            score = score_path(grid, r["path"], **args)
            np.testing.assert_allclose(score.J, r["J"], rtol=0, atol=validity["abs_tolerance"])
            add(
                3,
                name,
                "oracle_prefix_audit",
                path,
                config_digest(cfg),
                c["shape"],
                c["budget"],
                c["start"],
                c["q"],
                "ASAR_" + r["mode"],
                r["J"],
                score.pd_final,
                seed=seeds.get(name),
                input_seed=seeds.get(name),
                heuristic_mode=r["mode"],
                epsilon=r["epsilon"],
                ref=("DFS", r["oracle_J"]),
                theory_certified=r["theory_certified"],
                elapsed_s=r["seconds_with_trace"],
                timing_scope="solver_with_trace",
                **counters(r),
            )

    toy = read_json(metrics / "stage4_toy.json")
    for file in ("stage4_comparison.csv", "stage4_order.csv"):
        path = metrics / file
        for r in read_csv(path):
            if "t" in r and r["t"] != r["T"]:
                continue
            name = r["scenario"]
            c = toy["cases"][name]
            if digest(root / f"configs/{name}.yaml") != r["config_sha256"]:
                raise ValueError(f"{name} config hash mismatch")
            add(
                4,
                name,
                r["source"],
                path,
                r["config_sha256"],
                c["config"]["grid"],
                int(r["T"]),
                int(r["start"]),
                float(r["q"]),
                r["method"],
                r.get("J", r.get("J_t")),
                r.get("Pd_T", r.get("Pd_t")),
                seed=r["seed"],
                input_seed=r["seed"],
                heuristic_mode=r["heuristic"],
                epsilon=r["epsilon"],
                theory_certified=False,
                **(counters(c) if r["method"] == "asar" else {}),
            )

    drift = read_json(metrics / "stage5_drift.json")
    lake = drift["config"]
    if digest(root / "configs/lake_ontario_constant.yaml") != drift["config_hash"]:
        raise ValueError("Lake drift config hash mismatch")

    def particle_fields(cfg, archive):
        return dict(
            forcing_kind=cfg["forcing_kind"],
            n_particles=cfg["particles"],
            object_type=cfg["object_key"],
            cell_width_m=cfg["cell_width_m"],
            dt_seconds=cfg["step_s"],
            input_seed=cfg["seed"],
            archive_sha256=archive,
        )

    s6 = read_json(metrics / "stage6_particles.json")
    if s6["config"] != yaml.safe_load((root / "configs/stage6_particle_search.yaml").read_bytes()):
        raise ValueError("stage 6 benchmark configuration mismatch")
    if digest(root / s6["config"]["archive"]) != s6["archive_sha256"]:
        raise ValueError("stage 6 archive fingerprint mismatch")
    path = metrics / "stage5_mass.csv"
    ledger = read_csv(path)
    audit_J = sum(float(r["M"]) for r in ledger if int(r["t"]) > 0)
    shape = lake["grid_rows_cols"]
    start = (shape[0] // 2) * shape[1] + shape[1] // 2
    lake_args = (shape, lake["budget"], start, lake["audit_q"])
    fields = particle_fields(lake, s6["archive_sha256"])
    add(
        5,
        "lake_ontario",
        "constant_Leeway_audit",
        path,
        drift["config_hash"],
        *lake_args,
        "audit_transect",
        audit_J,
        ledger[-1]["Pd"],
        seed=lake["seed"],
        **fields,
    )
    path = metrics / "stage6_particles.json"
    for profile, runs in [(False, s6["runs"]), (True, [s6["profile_run"]])]:
        fingerprint = config_digest(
            dict(
                search=s6["config"],
                archive=s6["archive_sha256"],
                drift=drift["config_hash"],
                profile=profile,
            )
        )
        for r in runs:
            add(
                6,
                "lake_ontario",
                "frozen_stage5_particles",
                path,
                fingerprint,
                *lake_args,
                "ASAR_paper",
                r["J"],
                r["Pd"],
                seed=r["seed"],
                heuristic_mode=r["heuristic_mode"],
                epsilon=r["epsilon"],
                ref=("stage5_audit_transect", audit_J),
                elapsed_s=r["elapsed_s"],
                timing_scope="cProfile_solver" if profile else "solver",
                **fields,
                **counters(r),
                **{
                    k: r[k]
                    for k in (
                        "theory_certified",
                        "status",
                        "stop_reason",
                        "timed_out",
                        "peak_process_MiB",
                        "incumbent_source",
                    )
                },
            )

    spec = yaml.safe_load((root / "configs/stage7_scenarios.yaml").read_bytes())
    missions = {}
    for name, case in spec["scenarios"].items():
        path = root / f"outputs/stage7/{name}/results.json"
        report = read_json(path)
        m, runs = report["metadata"], report["runs"]
        cfg = drift_config(spec, case)
        if m["drift_config"] != cfg or any(m[k] != v for k, v in case.items()):
            raise ValueError(f"{name}: Table I or drift configuration mismatch")
        archive = root / Path(m["archive"].replace("\\", "/"))
        if digest(archive) != m["archive_sha256"]:
            raise ValueError(f"{name}: particle archive fingerprint mismatch")
        with np.load(archive, allow_pickle=False) as data:
            error = audit_runs(m, runs, spec, GridGraph(*case["grid_rows_cols"]), data)
        pt = next(r for r in runs if r["method"] == "ParallelTrack")
        missions[name] = dict(metadata=m, runs=runs, replay_error=error, archive=archive)
        for r in runs:
            if r["certified"] or r["forcing_kind"] != spec["forcing_kind"]:
                raise ValueError(f"{name}: unexpected guarantee or forcing label")
            algo_seed = r["algorithm_seed"]
            add(
                7,
                name,
                m["paper_source"],
                path,
                r["config_hash"],
                case["grid_rows_cols"],
                r["T"],
                r["start"],
                r["q"],
                r["method"],
                r["J"],
                r["Pd_T"],
                seed=r["drift_seed"] if algo_seed is None else algo_seed,
                algo_seed=algo_seed,
                heuristic_mode="paper_greedy" if r["method"] == "ASAR_paper" else None,
                epsilon=r["epsilon"],
                ref=("ParallelTrack", pt["J"]),
                elapsed_s=r["planner_wall_s"],
                timing_scope="planner",
                warm_start_s=r["warm_start_s"],
                total_wall_s=r["total_wall_s"],
                theory_certified=r["certified"],
                **particle_fields(cfg, m["archive_sha256"]),
                **counters(r),
                **{
                    k: r[k]
                    for k in (
                        "status",
                        "stop_reason",
                        "timed_out",
                        "incumbent_source",
                        "data_availability",
                    )
                },
            )
    keys = {(r["config_hash"], r["seed"], r["algorithm"], r.get("epsilon")) for r in rows}
    if len(keys) != len(rows):
        raise ValueError("duplicate experiment key")
    return rows, missions, validity
