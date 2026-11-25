"""Run the independently passed Hudson archive while Fundy remains blocked.

The two-scene driver still requires both archives. This explicit partial
protocol retains every per-scene B2/B3/SHA gate and the unchanged method caps.
It cannot select the failed Fundy scene or generate substitute particles.
"""
import argparse
from pathlib import Path

import compare_additional_real as comparison
from stdc_validation_guards import read, save, require


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('stage', choices=('prepare', 'smoke', 'benchmark'))
    p.add_argument('--run-dir', type=Path, required=True)
    a = p.parse_args()
    run = a.run_dir.resolve()
    diagnosis = read(run / 'fundy_orientation_diagnosis.json')
    require(diagnosis['status'] == 'blocked', 'partial protocol requires explicit Fundy block')
    comparison.SCENARIOS = ('arctic_ocean',)
    if a.stage == 'prepare':
        save(run / 'comparison_scope.json', dict(
            requested=['arctic_ocean', 'bay_of_fundy'], included=['arctic_ocean'],
            excluded={'bay_of_fundy': diagnosis}, overall_status='blocked',
            partial_results_are_not_two_scene_completion=True))
        comparison.prepare(run)
    else:
        comparison.controller(run, a.stage)
