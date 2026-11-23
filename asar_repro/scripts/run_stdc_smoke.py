"""Run STDC on the frozen B7 Lake Ontario NPZ without rerunning OpenDrift.

This script MUST run in a local asar_repro checkout where the historical
particles.npz and B7 frozen_experiment_protocol.json are present.
Default: mass_lb vs stdc_lb, epsilon=1.10. Use --full for the complete ablation.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

import numpy as np

from asar_repro.grid import GridGraph
from asar_repro.heuristic import Heuristic
from asar_repro.motion import ParticleMotion
from asar_repro.objective import score_path
import asar_repro.search as search_module

ROOT = Path(__file__).resolve().parents[1]
PROTO = ROOT / 'outputs/baseline_v1.1/b7_final/frozen_experiment_protocol.json'


def hash_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--full', action='store_true', help='all 5 modes x all 3 epsilon values')
    p.add_argument('--repeat', type=int, default=1, help='repeat per run; set 3 for final timing')
    p.add_argument('--output', type=Path, default=ROOT/'outputs/stdc_v0_2/lake_results.json')
    args = p.parse_args()
    protocol = json.loads(PROTO.read_text(encoding='utf-8'))
    archive = ROOT / protocol['particle_archive']['path']
    required = protocol['particle_archive']['sha256']
    actual = hash_file(archive)
    if actual != required:
        raise RuntimeError(f'frozen particle SHA mismatch: {actual} != {required}')
    cfg = protocol['mission']
    graph = GridGraph(*cfg['grid_rows_cols'])
    T = int(cfg['budget'])
    with np.load(archive, allow_pickle=False) as z:
        cells = np.asarray(z['cell_ids'])
        ids = np.asarray(z['trajectory_id'])
        w = np.asarray(z['initial_weights'])
    motion = ParticleMotion(cells, graph.size, ids)
    search_args = dict(start=int(protocol['start_vertex']), budget=T, p=w,
                       q=cfg['audit_q'], motion=motion)
    warm_start = tuple(protocol['initial_path'])
    pt = score_path(graph, warm_start, **search_args)
    if abs(pt.J - float(protocol['initial_J'])) > 1e-10:
        raise AssertionError(f'PT J mismatch: {pt.J} vs {protocol["initial_J"]}')
    modes = ('mass_lb','reach_lb','capacity_lb','stepwise_lb','stdc_lb') if args.full else ('mass_lb','stdc_lb')
    epsilons = tuple(protocol['epsilon']) if args.full else (1.10,)
    limits = protocol['search_limits']
    rows = []
    for eps in epsilons:
        for mode in modes:
            for repeat in range(args.repeat):
                counter = {'calls':0,'s':0.0}
                base = search_module.Heuristic
                def factory(*a, **kw):
                    h = base(*a, **kw)
                    def timed(v, d, b, **extra):
                        st = perf_counter()
                        try:
                            return h(v,d,b,**extra)
                        finally:
                            counter['calls'] += 1
                            counter['s'] += perf_counter()-st
                    return timed
                with patch.object(search_module, 'Heuristic', new=factory):
                    t0 = perf_counter()
                    res = search_module.search_asar(
                        graph, **search_args, heuristic=mode, epsilon=eps,
                        initial_path=warm_start, **limits)
                    elapsed = perf_counter()-t0
                score = score_path(graph, res.path, **search_args) if res.path is not None else None
                if score is not None and abs(score.J - res.J) > 1e-10:
                    raise AssertionError('independent replay failed')
                row = dict(mode=mode, epsilon=eps, repeat=repeat,
                           J=res.J, Pd_T=score.pd_final if score else None,
                           status=res.status, reason=res.stop_reason,
                           theory_certified=res.theory_certified,
                           source=res.incumbent_source, expanded=res.expanded,
                           generated=res.generated, pruned=res.pruned, peak_open=res.peak_open,
                           heuristic_calls=counter['calls'], heuristic_wall_s=counter['s'],
                           search_wall_s=elapsed,
                           path=list(res.path) if res.path is not None else None)
                rows.append(row)
                print(f'{mode:<17} eps={eps:.2f} rep={repeat} {res.status:<17} '
                      f'J={res.J:.6f} expanded={res.expanded} wall={elapsed:.3f}s '
                      f'cert={res.theory_certified}', flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(dict(protocol_sha256=hash_file(PROTO),
                         particle_sha256=actual, rows=rows), ensure_ascii=False, indent=2),
                           encoding='utf-8')
    print('Saved:', args.output)

if __name__ == '__main__':
    main()
