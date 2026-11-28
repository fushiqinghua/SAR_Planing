"""Independently recompute the paired acceptance checks from saved formal records."""
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

from h3_protocol import digest, read, save
from run_study import DEFAULT_OUT, ident, lock, verify_record


def main():
    out=DEFAULT_OUT
    protocol=lock(out)
    toler=protocol["acceptance"]["numerical_tolerance"]
    thresholds=protocol["acceptance"]
    groups=defaultdict(dict)
    statuses=Counter()
    all_attempts=[]
    for task in protocol["tasks"]:
        folder=out/"runs"/ident(task)
        record=verify_record(folder,task)
        statuses[record["status"]]+=1
        candidate=folder/"result.json"
        if record["status"]!="valid" or not candidate.is_file():
            continue
        result=read(candidate)
        route,scalar=result["replay"],result["independent_replay"]
        assert result["delivery"]["within_budget"] and result["algorithm_wall_s"]<=30
        assert route["waypoints"]==scalar["waypoints"]
        assert all(abs(route[key]-scalar[key])<=toler for key in ("J","pd_final"))
        assert len(route["survival"])==len(scalar["survival"])
        assert max(abs(u-v) for u,v in zip(route["survival"],scalar["survival"]))<=toler
        ref=protocol["reference"][str(task["seed"])]["S30"]
        assert result["inner"]["initial_score"]["waypoints"]==ref["waypoints"]
        assert result["inputs"]["particle_sha256"]==ref["particle_sha256"]
        assert result["inputs"]["opendrift_runs_in_search"]==0 and not result["formal_optimality_certificate"]
        groups[task["seed"],task["rep"]][task["arm"]]=(record,result)
        all_attempts.append((record,result))

    audit=dict(statuses=dict(statuses),protocol_sha256=digest(out/"protocol.json"),
               valid_trials=len(all_attempts),registered_trials=len(protocol["tasks"]),
               algorithm_wall_max_s=max((r["algorithm_wall_s"] for _,r in all_attempts),default=None),
               deadline_fallbacks=sum(
                   r["delivery"]["disposition"] in ("returned_after_deadline","validation_after_deadline")
                   for _,r in all_attempts
               ), gates={})
    for seed in (3401,4501,4601):
        checks=[]
        for rep in range(3):
            entries=groups[(seed,rep)]
            if set(entries)!={"Gated","C0","Lazy"}:
                checks.append(dict(rep=rep,status="missing_budget_valid_pair"))
                continue
            base_rec,base=entries["C0"]
            new_rec,new=entries["Gated"]
            j,pd=new["replay"]["J"],new["replay"]["pd_final"]
            rss=new_rec["process_peak_rss_bytes"]/base_rec["process_peak_rss_bytes"]
            diff=100*(pd-base["replay"]["pd_final"])
            detail=new["inner"]["diagnostics"]["gated"]
            if seed==3401:
                passed=(j<=thresholds["J_3401_max"]+toler
                        and diff>=-thresholds["Pd_loss_3401_pp_max"]-100*toler)
            elif seed==4501:
                passed=abs(j-base["replay"]["J"])<=toler and abs(diff)<=100*toler
            else:
                passed=(new["delivery"]["accepted"] and j<=thresholds["J_4601_max"]+toler
                        and pd>=thresholds["Pd_4601_min"]-toler)
            if detail["selected_source"]=="bounded_completion":
                route=new["replay"]["waypoints"]
                origins=[attempt["winning_root"] for attempt in detail["attempts"] if attempt["winning_root"]]
                logged=[p["path"] for a in detail["attempts"] for p in a["shortlist"]]
                assert any(origin in logged and route[:len(origin)]==origin for origin in origins)
            checks.append(dict(rep=rep,status="passed" if passed else "failed",J=j,Pd=pd,
                               Pd_delta_pp=diff,peak_rss_ratio=rss,mode=detail["mode"],
                               waves=len(detail["attempts"]),source=detail["selected_source"],
                               outer_accept_s=new["delivery"]["acceptance_s"]))
        ratios=[row["peak_rss_ratio"] for row in checks if "peak_rss_ratio" in row]
        rss_pass=seed!=4501 or (len(ratios)==3 and median(ratios)<=thresholds["rss_4501_factor_max"])
        audit["gates"][str(seed)]=dict(passed=rss_pass and all(c["status"]=="passed" for c in checks),
                                      paired_rss_ratio_median=median(ratios) if ratios else None,
                                      repetitions=checks)
    save(out/"commands"/"delivery_check.json",audit)
    print(audit["statuses"],{k:v["passed"] for k,v in audit["gates"].items()},flush=True)


if __name__=="__main__":
    main()
