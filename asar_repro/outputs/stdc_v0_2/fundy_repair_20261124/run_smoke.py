"""Selected-scene integration smoke; original algorithms/evaluator unchanged."""
from pathlib import Path
import compare_additional_real as comparison
from stdc_validation_guards import read,save,require
run=Path(__file__).resolve().parent
meta=read(run/'b3/bay_of_fundy/metadata.json')
require(meta['direction_policy']['physical_direction_unverified'],'missing qualification')
comparison.SCENARIOS=('bay_of_fundy',)
save(run/'comparison_scope.json',dict(included=['bay_of_fundy'],purpose='integration smoke only',
 direction_policy=meta['direction_policy'],formal_benchmark_not_run=True))
comparison.prepare(run)
comparison.controller(run,'smoke')
