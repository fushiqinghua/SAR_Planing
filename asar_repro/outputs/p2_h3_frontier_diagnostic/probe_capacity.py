"""Isolate the 4601 OPEN limit after both frozen extended runs fill it."""
from pathlib import Path
import sys
from unittest.mock import patch

import run_diagnostic as run
from h3_protocol import digest, read, save


BASE = run.OUT
SUPPLEMENT = BASE/"capacity_4601"
TASK = dict(stage="extended",seed=4601,rep=0,mode="C0_capacity",seconds=120)


def checked_plan():
    protocol=run.lock()
    baseline={}
    for task in protocol["extended"]:
        if task["seed"]!=4601:
            continue
        folder=BASE/"runs"/run.ident(task)
        record=read(folder/"record.json")
        path=folder/"result.json"
        if record["status"]!="valid" or record["result_sha256"]!=digest(path):
            raise ValueError("Original 4601 extended evidence does not match")
        inner=read(path)["inner"]
        if (inner["stop_reason"]!="max_open" or inner["stats"]["terminal_candidates"]!=0
                or inner["max_open"]!=100000):
            raise ValueError("The registered 4601 capacity condition was not met")
        baseline[task["mode"]]=record["result_sha256"]
    if set(baseline)!={"C0_extend","Lazy_extend"}:
        raise ValueError("Both original 4601 extended arms are required")
    doc=dict(task=TASK, settings=dict(protocol["solver"],max_open=200000), baseline_sha256=baseline,
             original_protocol_sha256=digest(BASE/"protocol.json"),
             implementation_sha256=digest(Path(__file__)), watchdog_rss=protocol["watchdog_rss"])
    path=SUPPLEMENT/"plan.json"
    if path.exists():
        if read(path)!=doc:
            raise ValueError("Capacity diagnostic identity changed")
    else:
        save(path,doc)
    return protocol, doc


def main():
    p,plan=checked_plan()
    if len(sys.argv)==3 and sys.argv[1]=="_worker" and sys.argv[2]==run.ident(TASK):
        # Use the same offline archive validation, Original C0 execution and
        # both original replay entry points as the main experiment.
        capacity=dict(p,extended=[TASK],solver=plan["settings"])
        with patch.object(run,"OUT",SUPPLEMENT), patch.object(run,"lock",lambda:capacity):
            run.worker(run.ident(TASK))
    elif len(sys.argv)==1:
        # Reuse the parent's execution watchdog and raw evidence writer.
        with patch.object(run,"OUT",SUPPLEMENT), patch.object(run,"__file__",__file__):
            run.launch(TASK)
        print(SUPPLEMENT/"runs"/run.ident(TASK)/"result.json")
    else:
        raise ValueError("Unknown capacity diagnostic invocation")


if __name__=="__main__":
    main()
