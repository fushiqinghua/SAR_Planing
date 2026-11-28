"""Independently verify P1 archives and derive timing/pair evidence."""
from collections import Counter, defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path
from statistics import median
import sys

ABS = 1e-8
H4101 = "hudson_h2_d1_s4101"
H4201 = "hudson_h2_d2_s4201"


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def same(a, b):
    return math.isfinite(a) and math.isfinite(b) and abs(a-b) <= ABS


def equal_score(a, b):
    return (same(a["J"], b["J"]) and same(a["pd_final"], b["pd_final"])
            and len(a["survival"]) == len(b["survival"])
            and all(same(x, y) for x, y in zip(a["survival"], b["survival"])))


def quantile(values, fraction):
    return sorted(values)[math.ceil(len(values) * fraction) - 1]


def dist(values):
    if not values:
        return None
    return dict(median=median(values), minimum=min(values), maximum=max(values), p90=quantile(values,.9))


def derived(out):
    sys.path.insert(0, str(Path("scripts").resolve()))
    import run_lazy_robustness_p1 as runner
    from asar_repro.h2_inputs import load_h2_input
    from asar_repro.physical_search import independent_replay

    root = Path.cwd()
    protocol = runner.verify(out)
    runner.check_validation(out)
    tasks = read(out/"tasks.json")
    assert len(tasks) == 48 and tasks == runner.task_matrix()
    frozen = dict(protocol_sha256=digest(out/"protocol.json"),
                  validation_sha256=digest(out/"validation/validation.json"))
    folders = {p.name for p in (out/"runs").iterdir() if p.is_dir()}
    assert folders == {runner.task_id(t) for t in tasks}
    refs = protocol["references"]
    data_root = root/protocol["config"]["source_root"]/"inputs"
    cases = {}
    targets = protocol["design"]["target"]
    seed_J = protocol["design"]["baseline_initial_j"][H4101]
    for instance in (H4101, H4201):
        case = refs["instances"][instance]
        problem, _, _, info = load_h2_input(root, case, data_root/case["id"], "heading_square")
        assert info["particle_sha256"] == refs["archive_hashes"][instance]["particle_sha256"]
        assert info["manifest_sha256"] == refs["archive_hashes"][instance]["manifest_sha256"]
        init = refs["references"][instance]
        seed_score = problem.replay(init["waypoints"], connectivity=8)
        assert same(seed_score["J"], init["J"]) and same(seed_score["pd_final"], init["pd_final"])
        assert seed_score["observation_times_s"] == init["observation_times_s"]
        cases[instance] = problem, info, init
    rows = []
    for index, task in enumerate(tasks):
        run_id = runner.task_id(task)
        folder = out/"runs"/run_id
        record, payload = read(folder/"record.json"), read(folder/"result.json")
        assert task == read(folder/"task.json") == record["task"] == payload["task"]
        assert record["status"] == "completed" and record["returncode"] == 0 and record["watchdog"] is None
        assert record["result_sha256"] == digest(folder/"result.json") and record["frozen_evidence"] == frozen
        assert record["peak_rss_bytes"] > 0 and (folder/"stdout.log").is_file() and (folder/"stderr.log").is_file()
        result = payload["result"]
        assert result["status"] == "valid" and result["formal_optimality_certificate"] is False
        instance, method = task["instance"], task["method"]
        problem, info, init = cases[instance]
        runner.check_result(task, result, protocol)
        assert result["inputs"]["manifest_sha256"] == info["manifest_sha256"]
        assert result["inputs"]["particle_sha256"] == info["particle_sha256"]
        assert result["inputs"]["opendrift_runs_in_search"] == 0
        raw = result["raw"]
        inner = raw["phases"][0]["inner"]
        assert raw["method"] == "C0" and raw["total_seconds"] == task["seconds"] == 30.0
        assert raw["initial_score"]["waypoints"] == init["waypoints"]
        assert result["reference_sha256"] == runner.old.object_digest(init)
        assert result["execution_audit"]["status"] == "passed"
        assert 0 < result["algorithm_wall_s"] <= 30.0
        assert 0 <= result["algorithm_cpu_s"] and math.isfinite(result["algorithm_cpu_s"])
        score = result["physical_replay"]
        replay = problem.replay(score["waypoints"], connectivity=8)
        independent = independent_replay(problem, score["waypoints"], connectivity=8)
        assert score["waypoints"] == raw["waypoints"] and equal_score(replay, score) and equal_score(independent, score)
        assert same(math.fsum(score["survival"][1:]), result["J"])
        assert same(1-score["survival"][-1], result["pd_final"])
        strict = [e for e in inner["history"] if e["source"] == "search"]
        diagnostics = inner["diagnostics"]
        lazy = diagnostics.get("lazy_frontier", {})
        rows.append(dict(
            **task, schedule_index=index+1, run_id=run_id, J=result["J"], Pd=result["pd_final"],
            retained_target_J=result["J"] <= targets[instance]+ABS,
            returned_seed_quality=result["J"] >= seed_J-ABS if instance == H4101 else None,
            first_search_improvement_s=strict[0]["elapsed_s"] if strict else None,
            first_terminal_s=diagnostics.get("first_search_terminal_generated_s"),
            best_inner_s=inner["best_elapsed_s"], expanded=inner["expanded"],
            generated=inner["generated"], terminal_candidates=inner["stats"]["terminal_candidates"],
            wall_s=result["algorithm_wall_s"], cpu_s=result["algorithm_cpu_s"],
            rss_mib=record["peak_rss_bytes"]/2**20,
            process_wall_s=record["process_wall_s"], input_load_s=result["input_load_s"],
            independent_audit_s=result["independent_audit_s"], stop_reason=inner["stop_reason"],
            migration_count=lazy.get("migrations", 0), migration_s=lazy.get("migration_s", 0.0),
        ))
    grouped, blocks = defaultdict(list), defaultdict(dict)
    for r in rows:
        grouped[r["instance"], r["method"]].append(r)
        blocks[r["instance"],r["repetition"]][r["method"]] = r
    def aggregate(rr):
        assert rr
        hist = Counter(f"{r['J']:.12f}" for r in rr)
        return dict(
            n=len(rr), J=dist([r["J"] for r in rr]), Pd=dist([r["Pd"] for r in rr]),
            wall_s=dist([r["wall_s"] for r in rr]), cpu_s=dist([r["cpu_s"] for r in rr]),
            rss_mib=dist([r["rss_mib"] for r in rr]), target_hits=sum(r["retained_target_J"] for r in rr),
            bad_count=sum(r["returned_seed_quality"] is True for r in rr),
            first_search_s=dist([r["first_search_improvement_s"] for r in rr if r["first_search_improvement_s"] is not None]),
            no_search_improvement=sum(r["first_search_improvement_s"] is None for r in rr),
            J_counts=dict(sorted(hist.items())), stop_reasons=dict(Counter(r["stop_reason"] for r in rr)),
        )
    scopes = {f"{i}/{m}": aggregate(v) for (i,m),v in sorted(grouped.items())}
    control = aggregate(grouped[H4101,"C0_A"] + grouped[H4101,"C0_B"])
    candidate = scopes[f"{H4101}/C0_LAZY"]
    h2 = scopes[f"{H4201}/C0_LAZY"]
    checks = dict(
        h4101_median=candidate["J"]["median"] <= control["J"]["median"] + ABS,
        h4101_p90=candidate["J"]["p90"] <= control["J"]["p90"] + ABS,
        h4101_bad_rate=candidate["bad_count"]/12 <= control["bad_count"]/24 + 1/12,
        h4201_target_hits=h2["target_hits"] >= 5,
        h4201_Pd=h2["Pd"]["median"] >= .090948-ABS,
    )
    reported = read(out/"summary.json")
    h1_pass = all(checks[k] for k in checks if k.startswith("h4101_"))
    h2_pass = all(checks[k] for k in checks if k.startswith("h4201_"))
    assert reported["decision"]["4101_noninferiority"] is h1_pass
    assert reported["decision"]["4201_retain"] is h2_pass
    assert reported["status"] == ("timing_screen_passed" if h1_pass and h2_pass else "timing_screen_not_passed")
    for (i,m), value in grouped.items():
        recorded = reported["by_instance_method"][i][m]
        v = scopes[f"{i}/{m}"]
        assert recorded["runs"] == v["n"] and recorded["hit_count"] == v["target_hits"]
        assert all(same(recorded[k], e) for k,e in [
            ("median_J",v["J"]["median"]), ("p90_J",v["J"]["p90"]), ("worst_J",v["J"]["maximum"]),
            ("median_Pd",v["Pd"]["median"]), ("median_rss_mib",v["rss_mib"]["median"]),
        ])
    def pair(i, r, a, b, methods):
        l, h = methods[a], methods[b]
        x, y = l["first_search_improvement_s"], h["first_search_improvement_s"]
        return dict(
            instance=i,repetition=r, comparison=f"{b}_vs_{a}", control_id=l["run_id"], candidate_id=h["run_id"],
            control_J=l["J"],candidate_J=h["J"], relative_J_gain=(l["J"]-h["J"])/l["J"],
            delta_J=h["J"]-l["J"], delta_Pd_pp=100*(h["Pd"]-l["Pd"]),
            control_first_search_s=x, candidate_first_search_s=y,
            first_search_delta_s=y-x if x is not None and y is not None else None,
            control_cpu_s=l["cpu_s"],candidate_cpu_s=h["cpu_s"],
            control_rss_mib=l["rss_mib"],candidate_rss_mib=h["rss_mib"],
        )
    pairs = []
    for (i,r),methods in sorted(blocks.items()):
        for a,b in ([("C0_A","C0_B"),("C0_A","C0_LAZY"),("C0_B","C0_LAZY")] if i == H4101 else [("C0","C0_LAZY")]):
            pairs.append(pair(i,r,a,b,methods))
    evidence_sufficient = not all(scopes[f"{H4101}/{m}"]["target_hits"] < 6 for m in ("C0_A","C0_B","C0_LAZY"))
    dest = out/"independent_verification.json"
    with dest.open("x",encoding="utf-8",newline="\n") as f:
        json.dump(dict(
            status="verified", run_count=len(rows), formal_decision=reported["status"], checks=checks,
            all_4101_arms_mostly_miss=not evidence_sufficient, pooled_hudson_4101_C0=control,
            frozen_evidence=frozen, score_method="dual replay from frozen H2 archives",
            method_instances=scopes, run_rows=rows, pair_rows=pairs,
        ),f,ensure_ascii=False,allow_nan=False,indent=2)
        f.write("\n")
    for name, entries in [("independent_metrics.csv",rows),("paired_metrics.csv",pairs)]:
        with (out/name).open("x",encoding="utf-8",newline="") as f:
            w=csv.DictWriter(f,fieldnames=list(entries[0]))
            w.writeheader()
            w.writerows(entries)
    for name,v in scopes.items():
        print(name,"n",v["n"],"J",v["J"],"Pd",v["Pd"]["median"],"bad",v["bad_count"],"hits",v["target_hits"],
              "CPU",v["cpu_s"]["median"],"RSS",v["rss_mib"]["median"],"first",v["first_search_s"])
    print("pooled C0",control,"checks",checks,"evidence_sufficient",evidence_sufficient)
    print("Verified all 48 frozen records, dual route replays and preregistered gates.",flush=True)


if __name__ == "__main__":
    derived(Path(sys.argv[1]).resolve())
