"""Compare exhaustive DFS with both zero-heuristic searches on fixed toy inputs."""

import csv
import json
from pathlib import Path
from time import perf_counter

import numpy as np

from asar_repro.grid import GridGraph
from asar_repro.motion import MatrixMotion
from asar_repro.objective import score_path
from asar_repro.oracle import enumerate_oracle
from asar_repro.search import search_zero


OUTPUT = Path(__file__).resolve().parents[1] / "outputs" / "metrics"
ATOL = 1e-10


def toy_cases():
    for size, T, seed in [(2, 6, 202), (3, 5, 203), (4, 5, 204)]:
        grid = GridGraph(size, size)
        rng = np.random.default_rng(seed)
        p = rng.dirichlet(np.ones(grid.size)).tolist()
        common = dict(size=size, start=grid.vertex(size // 2, size // 2),
                      T=T, seed=seed, p=p, q=0.78)
        yield dict(case=f"static_{size}x{size}", matrices=None, **common)
        # Independently sample a row-stochastic local kernel for each time.
        matrices = []
        for _ in range(T):
            P = np.zeros((grid.size, grid.size))
            for u in range(grid.size):
                reachable = [u, *grid.neighbors(u)]
                P[u, reachable] = rng.dirichlet(np.ones(len(reachable)))
            matrices.append(P.tolist())
        yield dict(case=f"dynamic_{size}x{size}", matrices=matrices, **common)
    p = (np.array([8, 2, 1, 1, 0, 0, 8, 8, 1]) / 29).tolist()
    yield dict(case="prefix_collision", size=3, T=5, start=0, seed=None,
               p=p, q=1, matrices=None)
    yield dict(case="all_tied", size=2, T=4, start=0, seed=None,
               p=[1, 0, 0, 0], q=0, matrices=None)


def count_walks(grid, start, T):
    """Count full paths by endpoint without inspecting search costs or beliefs."""
    counts = [0] * grid.size
    counts[start] = 1
    for _ in range(T):
        counts = [sum(counts[u] for u in grid.neighbors(v)) for v in range(grid.size)]
    return sum(counts)


def compare(case):
    grid = GridGraph(case["size"], case["size"])
    matrices = case["matrices"]
    motion = (MatrixMotion.identity(grid.size) if matrices is None
              else MatrixMotion.time_varying(matrices))
    args = dict(start=case["start"], budget=case["T"], p=case["p"], q=case["q"], motion=motion)
    rows = []
    for name, solver, options in [
        ("dfs", enumerate_oracle, {}), ("heap_reference", search_zero, {}),
        ("heap_pruned", search_zero, {"prune": True}),
    ]:
        since = perf_counter()
        result = solver(grid, **args, **options)
        runtime_s = perf_counter() - since
        if name == "dfs":
            oracle = result
            if oracle.complete_paths != count_walks(grid, case["start"], case["T"]):
                raise AssertionError(f"Incomplete enumeration in {case['case']}")
        replay = score_path(grid, result.path, **args)
        error = abs(result.J - oracle.J)
        replay_error = abs(result.J - replay.J)
        if max(error, replay_error) > ATOL or result.path not in oracle.tied_paths:
            raise AssertionError(f"Cost or route mismatch in {case['case']} / {name}")
        rows.append(dict(case=case["case"], T=case["T"], solver=name, J=result.J,
                         abs_error=error, replay_error=replay_error, expanded=result.expanded,
                         generated=result.generated, pruned=getattr(result, "pruned", 0),
                         peak_open=result.peak_open, runtime_s=runtime_s, path=list(result.path),
                         pd_final=replay.pd_final, complete_paths_oracle=oracle.complete_paths))
    return rows


def plot_peak_open(rows, filename):
    from matplotlib.figure import Figure

    reference = [r for r in rows if r["solver"] == "heap_reference"]
    bounded = [r for r in rows if r["solver"] == "heap_pruned"]
    labels = [r["case"].replace("_", " ") for r in reference]
    y = np.arange(len(labels))
    figure = Figure(figsize=(7.6, 4.8), layout="constrained")
    axes = figure.subplots()
    for group, offset, label, color in [
        (reference, -0.18, "Reference", "#64748b"),
        (bounded, 0.18, "Incumbent pruning", "#117864"),
    ]:
        bars = axes.barh(y + offset, [r["peak_open"] for r in group],
                         height=0.34, label=label, color=color)
        axes.bar_label(bars, padding=3, fontsize=8)
    axes.set_yticks(y, labels)
    axes.invert_yaxis()
    axes.margins(x=0.14)
    axes.set_xlabel("Peak number of queued paths")
    axes.set_title("Heap occupancy with the heuristic fixed to zero")
    axes.legend(loc="lower right")
    filename.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(filename, dpi=160)


def main():
    cases = list(toy_cases())
    rows = [row for case in cases for row in compare(case)]
    OUTPUT.mkdir(parents=True, exist_ok=True)
    report = {"stage": 2, "heuristic": "zero", "abs_tolerance": ATOL,
              "oracle_tie_atol": 1e-12, "inputs": cases, "results": rows}
    (OUTPUT / "stage2_comparison.json").write_text(
        json.dumps(report, allow_nan=False) + "\n", encoding="utf-8"
    )
    with (OUTPUT / "stage2_comparison.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    plot_peak_open(rows, OUTPUT.parent / "figures" / "stage2_peak_open.png")
    print(f"{len(cases)} cases, {len(rows)} runs, max absolute error "
          f"{max(row['abs_error'] for row in rows):g}")


if __name__ == "__main__":
    main()
