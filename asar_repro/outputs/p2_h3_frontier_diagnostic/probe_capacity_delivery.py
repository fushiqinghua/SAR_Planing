"""Recheck the 4601 capacity witness with a larger delivery reserve."""
from pathlib import Path
import sys
from unittest.mock import patch

import run_diagnostic as run
import probe_capacity as first
from h3_protocol import digest, read, save
from prepare_eight_neighbor_h3 import load_h3_input


OUT = run.OUT/"capacity_4601_delivery"
TASK = dict(first.TASK,mode="C0_capacity_reserve")
RESERVE = 2.0


def plan():
    p, baseline=first.checked_plan()
    folder=first.SUPPLEMENT/"runs"/run.ident(first.TASK)
    record=read(folder/"record.json")
    raw_path=folder/"result.json"
    raw=read(raw_path)
    inner,phase=raw["inner"],raw["outer"]["phases"][0]
    if (record["status"]!="valid" or digest(raw_path)!=record["result_sha256"]
            or phase["reason"]!="returned_after_deadline" or phase["accepted"]
            or inner["J"]>=p["reference"]["4601"]["best_C0_J"]):
        raise ValueError("Delivery recovery requires a better inner route rejected by the original deadline")
    options=dict(p["search"],solver_reserve_s=RESERVE)
    document=dict(task=TASK, settings=baseline["settings"], search=options,
                  first_capacity_sha256=digest(raw_path), frozen_source=p["source_sha256"],
                  implementation_sha256=digest(Path(__file__)))
    path=OUT/"plan.json"
    if path.is_file():
        if read(path)!=document:
            raise ValueError("Delivery rerun settings changed")
    else:
        case=p["reference"]["4601"]["case"]
        problem,_,_,info=load_h3_input(run.SOURCE,case["case"],case["h3_evidence"],"heading_square")
        replay,scalar=run.h3.dual_replay(problem,inner["waypoints"],8)
        if abs(replay["J"]-inner["J"])>1e-8 or abs(replay["pd_final"]-inner["pd_final"])>1e-8:
            raise ValueError("The first run's inner witness disagreed with the frozen scorer")
        save(OUT/"first_inner_route_replay.json",dict(
            original_run_sha256=digest(raw_path),inputs=info,solver_best_elapsed_s=inner["best_elapsed_s"],
            return_compute_s=phase["inner_return_compute_s"],disposition=phase["reason"],replay=replay,scalar=scalar))
        save(path,document)
    return dict(p,extended=[TASK],solver=document["settings"],search=options)


def main():
    p=plan()
    if len(sys.argv)==3 and sys.argv[1]=="_worker" and sys.argv[2]==run.ident(TASK):
        with patch.object(run,"OUT",OUT), patch.object(run,"lock",lambda:p):
            run.worker(run.ident(TASK))
    elif len(sys.argv)==1:
        with patch.object(run,"OUT",OUT), patch.object(run,"__file__",__file__):
            run.launch(TASK)
        path=OUT/"runs"/run.ident(TASK)/"result.json"
        raw=read(path)
        phase=raw["outer"]["phases"][0]
        print(path)
        print(f"Algorithm wall {raw['algorithm_wall_s']:.6f} s; delivery {phase['reason']}; "
              f"J {raw['replay']['J']:.12f}; Pd {raw['replay']['pd_final']:.9f}",flush=True)
    else:
        raise ValueError("Unknown delivery diagnostic invocation")


if __name__=="__main__":
    main()
