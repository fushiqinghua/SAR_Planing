"""Formal repetition of the frozen Fundy protocol; no simulation rerun."""
from pathlib import Path
import sys
import compare_additional_real as comparison
from stdc_validation_guards import read,save,require,digest
out=Path(__file__).resolve().parent
run=out.parent/'fundy_repair_20261124'
for f in read(run/'final_fingerprints.json')['files']:
    require(digest(run/f['path'])==f['sha256'],'Fundy archive changed: '+f['path'])
meta=read(run/'b3/bay_of_fundy/metadata.json')
require(meta['direction_policy']['physical_direction_unverified'],'lost physical qualification')
comparison.SCENARIOS=('bay_of_fundy',)
save(out/'formal_protocol.json',dict(command=[sys.executable,*sys.argv],run_dir=str(run),
    scenarios=['bay_of_fundy'],variants=comparison.VARIANTS,caps=comparison.CAPS,repeats=3,
    seed=41,direction_policy=meta['direction_policy'],particle_sha256=meta['particle_sha256'],
    previous_fundy_manifest_sha256=digest(run/'final_fingerprints.json'),
    scope='Formal repeats now authorized; earlier repair/smoke reports remain historical records.',
    opendrift_runs_this_stage=0))
comparison.controller(run,'benchmark')
