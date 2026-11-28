import hashlib
import json
from pathlib import Path
from statistics import median
import sys

out=Path(sys.argv[1])
sys.path.insert(0, str(Path("scripts").resolve()))
import run_eight_neighbor_prefix_order as runner

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def read(p):
    return json.loads(p.read_bytes())

protocol,tasks=runner.verify(out.resolve())
runner.require_validation(out.resolve())
runner.require_diagnostic(out.resolve())
assert len(tasks)==24 and len({runner.task_id(t) for t in tasks})==24
g=read(out/"gate.json")
group={}
for t in tasks:
    d=out/"runs"/runner.task_id(t)
    z=read(d/"record.json")
    result_file=d/"result.json"
    value=read(result_file)
    assert z["result_sha256"]==sha(result_file)
    assert z["frozen_evidence"]["protocol_sha256"]==sha(out/"protocol.json")
    assert z["frozen_evidence"]["fixed_work_sha256"]==sha(out/"equal-work.json")
    assert z["frozen_evidence"]["validation_sha256"]==sha(out/"validation/validation.json")
    assert t==z["task"]==value["task"]==read(d/"task.json")
    assert z["status"]=="completed" and z["returncode"]==0 and z["watchdog"] is None
    assert z["peak_rss_bytes"]>0 and z["verification_error"] is None
    for log in ["stdout.log","stderr.log"]:
        assert (d/log).is_file()
    r=value["result"]
    runner.check_result(t,r,protocol)
    score=r["physical_replay"]
    assert abs(r["J"]-sum(score["survival"][1:]))<=1e-10
    assert abs(r["pd_final"]-(1-score["survival"][-1]))<=1e-10
    group.setdefault((t["instance"],t["method"]),[]).append((r["J"],t["repetition"],r["pd_final"]))
for instance in runner.DESIGN["instances"]:
    c0,order = (sorted(group[instance,method])[1] for method in runner.DESIGN["methods"])
    pair=next(x for x in g["pairs"] if x["instance"]==instance)
    assert pair["C0_J"]==c0[0] and pair["C0_PREFIX_J"]==order[0]
    assert pair["C0_pd"]==c0[-1] and pair["C0_PREFIX_pd"]==order[-1]
    print(instance,"J/Pd",c0,order,"relative_J", (c0[0]-order[0])/c0[0])
print("Verified 24 raw run fingerprints, test evidence, fixed-work evidence, replay scores, same-route medians and original files.")
