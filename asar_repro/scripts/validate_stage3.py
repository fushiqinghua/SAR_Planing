"""Audit lower bounds at every reachable toy prefix and replay weighted searches."""

import csv
import hashlib
import json
from pathlib import Path
from random import Random
from time import perf_counter

import numpy as np

from asar_repro.grid import GridGraph
from asar_repro.heuristic import BOUND_MODES, MODES, Heuristic
from asar_repro.motion import MatrixMotion
from asar_repro.objective import score_path
from asar_repro.oracle import enumerate_oracle
from asar_repro.search import search_asar


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "data/fixtures/heuristic_dynamic_counterexample.npz"
ATOL = 1e-10
EPSILONS = (1.0, 1.02, 1.1)
SEARCH_MODES = ("zero", "mass_lb", "paper_greedy")


def toy_cases(fixture=FIXTURE):
    grid = GridGraph(3, 3)
    p = np.arange(1, 10, dtype=float) / 45
    for name, q in [("static_perfect", 1.0), ("static_partial", np.linspace(0.1, 0.9, 9))]:
        yield name, grid, dict(start=4, budget=4, p=p, q=q, motion=MatrixMotion.identity(9))
    rng = np.random.default_rng(17)
    small = GridGraph(2, 2)
    P = rng.dirichlet(np.ones(4), size=(4, 4))
    yield "dynamic_seed17", small, dict(start=0, budget=4, p=rng.dirichlet(np.ones(4)),
                                        q=[0.2, 0.8, 0.6, 0.4], motion=MatrixMotion.time_varying(P))
    # Additional synthetic case: the overestimate can also change the chosen path.
    rng = np.random.default_rng(213)
    p = rng.dirichlet(np.full(4, 0.5))
    P = rng.dirichlet(np.full(4, 0.4), size=(4, 4))
    yield "dynamic_seed213", small, dict(start=0, budget=4, p=p, q=.78,
                                         motion=MatrixMotion.time_varying(P))
    with np.load(fixture, allow_pickle=False) as data:
        yield "appendix_b", grid, dict(start=int(data["start"]), budget=int(data["T"]),
                                       p=data["p"], q=float(data["q"]),
                                       motion=MatrixMotion.time_varying(data["P"]))


def audit_prefixes(grid, args):
    T, start, motion = args["budget"], args["start"], args["motion"]
    estimators = {mode: Heuristic(grid, budget=T, q=args["q"], motion=motion, mode=mode)
                  for mode in MODES}
    records = []
    stack = [(start,)]
    while stack:
        path = stack.pop()
        depth = len(path) - 1
        prefix = score_path(grid, path, **{**args, "budget": depth})
        oracle = enumerate_oracle(grid, **args, prefix=path)
        # Replay the minimum-cost completion and sum only future steps. No
        # renormalization and no resetting the dynamic transition clock.
        complete = score_path(grid, oracle.path, **args)
        exact = float(complete.survival[depth + 1:].sum())
        choices = []
        estimates = {mode: estimate(path[-1], depth, prefix.final_belief,
                                    choices=choices if mode == "paper_greedy" else None)
                     for mode, estimate in estimators.items()}
        records.append(dict(prefix=path, exact_remaining=exact, h=estimates,
                            greedy_choices=choices, oracle_path=oracle.path, oracle_full_J=oracle.J,
                            feasible_completions=oracle.complete_paths))
        if depth < T:
            stack.extend(path + (v,) for v in reversed(grid.neighbors(path[-1])))
    return records


def summarize(records, mode):
    excess = [r["h"][mode] - r["exact_remaining"] for r in records]
    worst = int(np.argmax(excess))
    return dict(checked=len(excess), violations=sum(d > ATOL for d in excess),
                max_h_minus_exact=excess[worst], worst_prefix=records[worst]["prefix"])


def audit_search(grid, args, optimum, name, rng):
    rows, samples = [], []
    for mode in SEARCH_MODES:
        for eps in EPSILONS:
            trace = []
            since = perf_counter()
            result = search_asar(grid, **args, heuristic=mode, epsilon=eps, trace=trace.append)
            seconds = perf_counter() - since
            replay = score_path(grid, result.path, **args)
            within = result.J <= eps * optimum + ATOL
            if abs(replay.J - result.J) > ATOL or (result.theory_certified and not within):
                raise AssertionError(f"Search regression: {name}, {mode}, epsilon={eps}")
            rows.append(dict(case=name, mode=mode, epsilon=eps, J=result.J, oracle_J=optimum,
                             J_minus_oracle=result.J - optimum, observed_within_epsilon=within,
                             oracle_optimal_within_atol=abs(result.J - optimum) <= ATOL,
                             theory_certified=result.theory_certified, expanded=result.expanded,
                             generated=result.generated, pruned=result.pruned, peak_open=result.peak_open,
                             seconds_with_trace=seconds, path=result.path, replay_J=replay.J))
            for i in sorted(rng.sample(range(len(trace)), min(5, len(trace)))):
                samples.append(dict(mode=mode, epsilon=eps, event_index=i, **trace[i]))
    return rows, samples


def plot_witness(records, filename):
    from matplotlib.figure import Figure

    figure = Figure(figsize=(7.4, 3.4), layout="constrained")
    ax = figure.subplots()
    labels = ["zero", "mass_lb", "Oracle", "paper_greedy"]
    h = records["h"]
    bars = ax.barh(labels, [h["zero"], h["mass_lb"], records["exact_remaining"], h["paper_greedy"]],
                   color=["#657687", "#36768a", "#187458", "#af542d"])
    ax.invert_yaxis()
    ax.axvline(records["exact_remaining"], color="#187458", linestyle="--", linewidth=1)
    ax.bar_label(bars, fmt="%.4f", padding=4)
    ax.set_xlim(0, 3.1)
    ax.set_xlabel("Remaining truncated cost at the root (steps)")
    ax.set_title("Appendix B: time-varying target, 3 × 3 grid")
    filename.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(filename, dpi=150)


def main():
    rng = Random(31)
    report = dict(
        stage=3, abs_tolerance=ATOL, epsilons=EPSILONS, trace_sample_seed=31,
        paper_claim="Theorem 1 asserts admissibility of Algorithm 2 and an epsilon cost bound.",
        assumptions=["nonnegative joint undetected mass", "row-stochastic mass-preserving motion",
                     "one sensed cell per move, 0 <= q(v) <= 1", "fixed finite T, completed search"],
        numerical_scope="float64, tolerances per discrete model; finite oracle checks are instance evidence",
        theory_certified_definition="conditional mathematical epsilon bound under the stated assumptions",
        guarantee_by_mode={
            "zero": "admissible: future costs are nonnegative; queue order gives exact optimum for any epsilon",
            "mass_lb": "admissible: M_next >= (1-q_max)*M; sum this inequality over remaining steps",
            "paper_greedy": "paper reproduction; inadmissible on general dynamic inputs; no general certificate",
            "paper_literal_abs_time": "diagnostic absolute-time radius only; no certificate",
        },
        fixture=dict(path=FIXTURE.relative_to(ROOT).as_posix(), sha256=hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
                     seed=5, trial_zero_based=35, source="local guide Appendix B, not a paper experiment"),
        cases={},
    )
    all_rows = []
    for name, grid, args in toy_cases():
        prefixes = audit_prefixes(grid, args)
        root = prefixes[0]
        summary = {mode: summarize(prefixes, mode) for mode in MODES}
        if any(summary[mode]["violations"] for mode in BOUND_MODES):
            raise AssertionError(f"Certified bound overestimate: {name}")
        if name == "static_perfect" and summary["paper_greedy"]["violations"]:
            raise AssertionError("Static perfect-sensor toy lower-bound regression")
        rows, samples = audit_search(grid, args, root["oracle_full_J"], name, rng)
        if name == "dynamic_seed213":
            paper = next(r for r in rows if r["mode"] == "paper_greedy" and r["epsilon"] == 1)
            if paper["observed_within_epsilon"] or paper["theory_certified"]:
                raise AssertionError("Expected the known suboptimal paper-greedy route")
        all_rows.extend(rows)
        report["cases"][name] = dict(shape=[grid.rows, grid.cols], budget=args["budget"],
                                     start=args["start"], p=np.asarray(args["p"]).tolist(),
                                     q=np.asarray(args["q"]).tolist(), lower_bound_audit=summary,
                                     prefixes=prefixes, search_runs=rows, trace_samples=samples)
    root = report["cases"]["appendix_b"]["prefixes"][0]
    gap = root["h"]["paper_greedy"] - root["exact_remaining"]
    np.testing.assert_allclose([root["h"]["paper_greedy"], root["exact_remaining"], gap],
                               [2.6170801771, 2.5417333379, 0.0753468392], atol=1e-9, rtol=0)
    report["counterexample"] = dict(**root, h_minus_exact=gap, admissible_on_this_case=False)
    metrics = ROOT / "outputs/metrics"
    metrics.mkdir(parents=True, exist_ok=True)
    (metrics / "heuristic_validity_report.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    with (metrics / "stage3_search.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(all_rows[0]))
        writer.writeheader()
        writer.writerows(all_rows)
    plot_witness(root, ROOT / "outputs/figures/stage3_counterexample.png")
    print(f"{len(report['cases'])} cases, {len(all_rows)} weighted searches, witness gap {gap:.12f}")


if __name__ == "__main__":
    main()
