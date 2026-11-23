"""Run both stage 4 configs and export comparable maps, scores and step records."""

import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
import yaml

from asar_repro.objective import score_path
from asar_repro.search import search_asar
from asar_repro.toy import baseline_path, order_control, toy_problem
from asar_repro.visualize import plot_frames, plot_order


ROOT = Path(__file__).resolve().parents[1]


def write_csv(filename, rows):
    with filename.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def evaluate(config):
    grid, args = toy_problem(config)
    search = search_asar(grid, **args, **config["asar"])
    paths = {"asar": search.path}
    for method in ("greedy", "serpentine"):
        paths[method] = baseline_path(grid, **args, method=method)
    scores = {method: score_path(grid, path, **args, record_beliefs=True)
              for method, path in paths.items()}
    np.testing.assert_allclose(search.J, scores["asar"].J, atol=1e-10, rtol=0)
    for score in scores.values():
        np.testing.assert_allclose(score.beliefs.sum(axis=1), score.survival, atol=1e-12, rtol=0)
        if np.any(np.diff(score.survival) > 1e-12):
            raise AssertionError("undetected mass increased during replay")
    return grid, args, paths, scores, search


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs")
    options = parser.parse_args()
    metrics = options.output_dir / "metrics"
    figures = options.output_dir / "figures"
    metrics.mkdir(parents=True, exist_ok=True)
    figures.mkdir(parents=True, exist_ok=True)
    cases = []
    for name in ("toy_static", "toy_dynamic"):
        raw = (ROOT / "configs" / f"{name}.yaml").read_bytes()
        config = yaml.safe_load(raw.decode("utf-8"))
        cases.append((config, hashlib.sha256(raw).hexdigest(), *evaluate(config)))
    vmax = max(float(score.beliefs.max()) for _, _, _, _, _, scores, _ in cases
               for method, score in scores.items() if method in ("asar", "greedy", "serpentine"))
    summary, steps, order_steps = [], [], []
    report = {"stage": 4, "source": "按论文思想重建", "color_scale": [0, vmax], "cases": {}}
    for config, digest, grid, args, paths, scores, search in cases:
        case = config["id"]
        plot_frames(grid, config, paths, scores, vmax, figures / f"stage4_{case}.png")
        reunion = None
        if config["motion"]["kind"] == "static":
            controls, reunion = order_control(grid, paths["serpentine"])
            for method, path in controls.items():
                paths[method] = path
                scores[method] = score_path(grid, path, **args, record_beliefs=True)
        report["cases"][case] = dict(config=config, config_sha256=digest, p=args["p"].tolist(),
                                     paths=paths, expanded=search.expanded, generated=search.generated,
                                     pruned=search.pruned, peak_open=search.peak_open,
                                     theory_certified=search.theory_certified,
                                     belief_frames={
                                         method: {t: scores[method].beliefs[t].reshape(grid.rows, grid.cols).tolist()
                                                  for t in config["frames"]}
                                         for method in ("asar", "greedy", "serpentine")
                                     })
        for method, score in scores.items():
            is_control = method in ("east_first", "north_first")
            metadata = dict(scenario=case, method=method, source=config["source"], seed=config["seed"],
                            T=args["budget"], q=args["q"], start=args["start"],
                            heuristic=search.heuristic_mode if method == "asar" else "",
                            epsilon=search.epsilon if method == "asar" else "", config_sha256=digest)
            if not is_control:
                summary.append(dict(**metadata, J=score.J, Pd_T=score.pd_final,
                                    theory_certified=search.theory_certified if method == "asar" else ""))
            for t, vertex in enumerate(paths[method]):
                r, c = grid.coordinates(vertex)
                row = dict(**metadata, t=t, vertex=vertex, row=r, col=c, M_t=score.survival[t],
                           delta_Pd=score.delta_pd[t-1] if t else "", Pd_t=1-score.survival[t],
                           J_t=score.g[t])
                (order_steps if is_control else steps).append(row)
        if reunion is not None:
            np.testing.assert_array_equal(sorted(paths["east_first"]), sorted(paths["north_first"]))
            np.testing.assert_allclose(scores["east_first"].beliefs[reunion:],
                                       scores["north_first"].beliefs[reunion:], atol=1e-12, rtol=0)
            plot_order(config, scores, reunion, figures / "stage4_order.png")
            report["order_control"] = dict(reunion_step=reunion, east_first_J=scores["east_first"].J,
                                           north_first_J=scores["north_first"].J,
                                           common_Pd_T=scores["east_first"].pd_final)
    write_csv(metrics / "stage4_comparison.csv", summary)
    write_csv(metrics / "stage4_steps.csv", steps)
    write_csv(metrics / "stage4_order.csv", order_steps)
    (metrics / "stage4_toy.json").write_text(json.dumps(report, ensure_ascii=False, indent=2,
                                                        allow_nan=False) + "\n", encoding="utf-8")
    for row in summary:
        print(f"{row['scenario']} {row['method']}: J={row['J']:.6f}, Pd={row['Pd_T']:.6f}")
    print(report["order_control"])


if __name__ == "__main__":
    main()
