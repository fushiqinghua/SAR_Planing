"""Produce a traceable rolling-pilot report using frozen results only."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import csv
import math
import os
from pathlib import Path
from statistics import median
import subprocess
import sys

ARMS = ("C0", "C1")
ERRORS = (OSError, ValueError, KeyError, TypeError, IndexError)
TICK = chr(96)


def fmt(value, digits=4, scale=1., signed=False):
    if value is None:
        return "—"
    return format(scale * value, f"{'+' if signed else ''}.{digits}f")


def spread(values, scale=1.):
    values = list(values)
    return (f"{fmt(median(values), scale=scale)}［{fmt(min(values), scale=scale)}, "
            f"{fmt(max(values), scale=scale)}］") if values else "—"


def counts(values):
    return "、".join(f"{key} ×{n}" for key, n in sorted(Counter(values).items())) or "无"


def table(lines, header, rows):
    lines.extend(["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"])
    for row in rows:
        cells = [str(x).replace("\r", " ").replace("\n", " ").replace("|", r"\|") for x in row]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")


def link(out, path, label=None):
    path = out / path
    if not path.exists():
        return "—"
    relative = Path(os.path.relpath(path, out)).as_posix()
    if " " in relative:
        relative = "<" + relative + ">"
    return f"[{label or path.name}]({relative})"


def git_identity(repo):
    def git(*args):
        proc = subprocess.run(["git", "-c", f"safe.directory={repo.as_posix()}", "-C", str(repo), *args],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
        return proc.stdout.strip()
    try:
        return f"{TICK}{git('branch', '--show-current')}{TICK} / {TICK}{git('rev-parse', 'HEAD')}{TICK}"
    except (OSError, subprocess.CalledProcessError):
        return "未读取"


def evidence(runner, config_path, out):
    config = runner.check_config(runner.read(config_path))
    errors = []
    identity = {}
    rows = []
    status = dict(status="incomplete_or_invalid", valid=0, missing=None, errors=[])
    if (out / "preflight.json").exists():
        try:
            identity = runner.verify_preflight(config_path, out)
        except ERRORS as error:
            errors.append(f"预检证据校验失败 {error}")
    if (out / "protocol.json").exists():
        try:
            identity, tasks = runner.verify_protocol(config_path, out)
            status, rows = runner.collect(out, tasks, identity)
        except ERRORS as error:
            errors.append(f"协议证据校验失败 {error}")
    else:
        errors.append("尚无冻结协议")
    decision = runner.decision(config, rows, complete=status["status"] == "complete" and not errors)
    if (out / "summary.json").exists() and "tasks_sha256" in identity:
        try:
            summary = runner.read(out / "summary.json")
            if (summary["status"] != status or summary["decision"] != decision
                    or summary["protocol_sha256"] != runner.digest(out / "protocol.json")
                    or summary["raw_evidence"] != {row["run_id"]: row["record"]["result_sha256"] for row in rows}):
                raise ValueError("原始任务与自动汇总不一致")
            files = summary["derived_file_sha256"]
            if set(files) != {"comparison.csv", "survival.csv", "phases.csv", "instance_comparison.csv"}:
                raise ValueError("自动汇总缺少登记的派生表")
            for name, sha in files.items():
                if runner.digest(out / name) != sha:
                    raise ValueError(f"派生表的 SHA-256 不符 {name}")
            with (out / "comparison.csv").open(encoding="utf-8-sig", newline="") as fh:
                values = list(csv.DictReader(fh))
            by_id = {entry["run_id"]: entry for entry in values}
            if len(values) != len(rows) or len(by_id) != len(rows):
                raise ValueError("逐次对照表数量或唯一性不符")
            for row in rows:
                entry = by_id[row["run_id"]]
                for field in ("J", "pd_final"):
                    if float(entry[field]) != row["result"][field]:
                        raise ValueError(f"逐次对照表与原始分数不符 {row['run_id']} {field}")
        except ERRORS as error:
            errors.append(f"自动汇总校验失败 {error}")
    elif status["status"] == "complete":
        errors.append("缺少自动汇总的校验证据")
    if errors:
        decision = runner.decision(config, rows, complete=False)
    return config, identity, status, rows, decision, errors


def run_link(out, row, name="result.json"):
    run_id = row["run_id"]
    return link(out, Path("runs") / run_id / name, run_id)


def write_identity(L, runner, config_path, out, config, identity, status, errors):
    L.extend(["## 1. 运行身份与完整性", ""])
    env = identity.get("environment", {})
    ref = identity.get("references", {})
    append = [
        ("运行分支与提交", git_identity(runner.REPO)),
        ("继承基点", runner.BASE_COMMIT),
        ("输出目录", out.relative_to(runner.ROOT).as_posix()),
        ("任务计划 / 有效 / 缺失 / 异常", f"24 / {status['valid']} / {len(status['missing']) if status['missing'] is not None else '未冻结'} / {len(status['errors'])}"),
        ("完整性", "通过" if status["status"] == "complete" and not errors else "未通过或尚未完成"),
        ("Python 与操作系统", f"{env.get('python', '未记录')} / {env.get('platform', '未记录')}"),
        ("CPU 与线程", f"{env.get('logical_cpus', '未记录')} 逻辑核 / {', '.join(f'{k}={v}' for k,v in env.get('effective_child_threads', {}).items()) or '未记录'}"),
        ("依赖", "、".join(f"{k} {v}" for k,v in env.get("packages", {}).items()) or "未记录"),
        ("冻结与来源", " · ".join(
            (link(out, config_path, "配置"), link(out, "protocol.json", "协议"),
             link(out, "preflight.json", "预检"), link(out, "tasks/R30.json", "任务清单"),
             link(out, runner.ROOT / config["reference_manifest"], "来源指纹")))),
    ]
    table(L, ["项目", "证据"], append)
    if (out / "protocol.json").exists():
        L.extend([f"- 协议 SHA-256 {runner.digest(out / 'protocol.json')}。配置 SHA-256 {runner.digest(config_path)}。", ""])
    if ref:
        L.extend([f"- 来源清单 SHA-256 {ref['manifest_sha256']}。绑定 {len(ref['files'])} 份直接指纹与 {len(ref['git_blobs'])} 份继承 Git blob。", ""])
    attempts = []
    for path in sorted((out / "validation").glob("*/result.json")):
        try:
            entry = runner.read(path)
        except ERRORS as error:
            L.extend([f"- 测试记录不能读取 {error}。 " + link(out, path), ""])
            continue
        attempts.append((path.parent.name, entry["status"], entry["testcase_count"], entry["bad_or_skipped_count"],
                         link(out, path, "命令和结果"), link(out, path.with_name("pytest.xml"), "JUnit"),
                         link(out, path.with_name("stdout.log"), "stdout"), link(out, path.with_name("stderr.log"), "stderr")))
    if attempts:
        table(L, ["测试标识", "状态", "检查项", "失败、错误或跳过", "记录", "报告", "标准输出", "错误输出"], attempts)
    L.extend(["- 全过程命令与证据。 " + link(out, "commands", "命令日志"), ""])
    for name in ("resume_provenance.json", "recovery_provenance.json", "recovery.json"):
        if (out / name).exists():
            L.extend(["- 已保存恢复核对。 " + link(out, name), ""])
    if (out / "RUNNING.lock").exists():
        L.extend(["- 读取时仍存在运行锁，需核对批次是否仍在运行。 " + link(out, "RUNNING.lock"), ""])
    for err in errors:
        L.append(f"- {err}")
    for issue in status["errors"]:
        L.append(f"- {issue['run_id']} {issue['error']}。 " + link(out, Path("runs") / issue["run_id"], "保留现场"))
    for path in sorted((out / "commands").glob("*.json")):
        try:
            call = runner.read(path)
        except ERRORS:
            continue
        if call.get("status") == "failed":
            L.append(f"- 命令 {call.get('action', '未记录')} 失败。{call.get('error', '')} " + link(out, path, "记录"))
    if status["missing"]:
        L.append("- 缺失任务 " + "、".join(status["missing"]) + "。")
    L.append("")
    if not ref:
        return
    base = runner.ROOT / config["source_root"]
    L.extend(["## 2. 固定场景与共同路线", ""])
    cases = []
    for key in runner.SELECTED:
        case, route = ref["instances"][key], ref["references"][key]
        audit = ref["archive_hashes"][key]["physical_audit"]
        ledger = base / "inputs" / key / "mass_audit.json"
        outside = runner.read(ledger)[0].get("prior_outside") if ledger.is_file() else None
        cases.append((key, f"{case['lkp_utc']} / {case['cst_utc']}", case["seed"], f"{fmt(audit['horizon_s'],2)} / {audit['tick_count']}",
                      f"{fmt(route['J'],8)} / {fmt(route['pd_final'],4,100)}%", f"{fmt(outside,1,100)}%",
                      link(out, base / "runs" / route["run_id"] / "result.json", route["run_id"]), link(out, ledger, "质量账本")))
    table(L, ["实例", "事故与 CST UTC", "seed", "H 秒 / K", "共同路线 J / Pd", "CST 域外质量", "历史 S30", "质量来源"], cases)
    L.extend(["四例为已见 H2 开发档案。每例两组共用原粒子档案、联合质量和共同 S30 路线。"
              "历史 S30 建造成本共同外置，本轮的复制、原评分及候选接纳计入求解。", ""])


def write_quality(L, out, rows, decision):
    L.extend(["## 3. 配对结果与逐次证据", ""])
    by_run = {row["run_id"]: row for row in rows}
    if decision["comparisons"]:
        pairs = []
        for p in decision["comparisons"]:
            marks = "、".join(flag for ok, flag in ((p["winner"], "达改善门槛"),
                                                   (p["J_regression"], "J 退化"),
                                                   (p["pd_drop_flag"], "Pd 超限")) if ok) or "低于改善门槛"
            pairs.append((p["instance"], fmt(p["J_C0"], 9), fmt(p["J_C1"], 9),
                          fmt(p["relative_J_gain"], 4, 100, True) + "%",
                          fmt(p["pd_C0"], 6, 100) + "%", fmt(p["pd_C1"], 6, 100) + "%",
                          fmt(p["delta_pd_percentage_points"], 4, signed=True), marks,
                          " / ".join(run_link(out, by_run[p[f"{arm}_run_id"]]) for arm in ARMS)))
        table(L, ["实例", "C0 J 中位", "C1 J 中位", "J 改善", "C0 Pd", "C1 Pd", "ΔPd 百分点", "实例门槛", "代表运行"], pairs)
        L.extend(["Pd 取同一个按 J 排序选出的中位代表运行。J 并列按固定重复序号排序。", ""])
    else:
        L.extend(["完整性门槛未通过。仅列已经核验的逐次运行，尚无本轮方法判定。", ""])
    groups = defaultdict(list)
    for row in rows:
        task = row["task"]
        groups[task["instance"], task["method"]].append(row)
    if groups:
        details = []
        for (key, arm), group in sorted(groups.items()):
            values = []
            for r in sorted(group, key=lambda row: row["task"]["repetition"]):
                result = r["result"]
                values.append(f"r{r['task']['repetition']} {fmt(result['J'],9)} / {fmt(result['pd_final'],6,100)}% {run_link(out,r)}")
            js = [r["result"]["J"] for r in group]
            pds = [r["result"]["pd_final"] for r in group]
            details.append((key, arm, " · ".join(values), f"{fmt(min(js),9)}–{fmt(max(js),9)}",
                            f"{fmt(min(pds),6,100)}%–{fmt(max(pds),6,100)}%"))
        table(L, ["实例", "方法", "全部重复 J / Pd 与证据", "J 范围", "Pd 范围"], details)


def write_phases(L, out, rows):
    L.extend(["## 4. 阶段因果性、接纳和预算", ""])
    buckets, detail, budgets = defaultdict(list), [], []
    for row in rows:
        result, task = row["result"], row["task"]
        raw = result["raw"]
        initial = raw["initial_score"]
        old = (initial["J"], initial["pd_final"])
        for p in raw["phases"]:
            buckets[task["method"],p["stage_index"]].append(p)
            if task["method"] == "C1":
                new = (p["active_J_after"], p["active_pd_final_after"])
                detail.append((f"{task['instance']} r{task['repetition']}", p["stage_index"],
                               *(fmt(p[field]) for field in ("request_time_s", "anchor_time_s", "ready_time_s",
                                  "execution_ready_time_s", "virtual_execution_time_after_s")),
                               f"{fmt(p['actual_compute_s'])} / {fmt(p['cumulative_compute_s'])}",
                               p["reason"], f"{fmt(old[0],8)} → {fmt(new[0],8)}",
                               f"{fmt(old[1],5,100)}% → {fmt(new[1],5,100)}%", run_link(out, row)))
                old = new
        rec = row["record"]
        budgets.append((f"{task['instance']} {task['method']} r{task['repetition']}",
                        fmt(result["algorithm_wall_s"]), fmt(result["algorithm_cpu_s"]), fmt(rec["process_wall_s"]),
                        fmt(rec["peak_rss_bytes"], 2, 1 / 2**20), fmt(result["independent_audit_s"], 5),
                        fmt(raw["deadline_overshoot_s"], 6), run_link(out, row, "record.json")))
    if not buckets:
        L.extend(["尚无已经核验的阶段账本。", ""])
        return budgets
    aggregate = []
    for (arm, k), phases in sorted(buckets.items()):
        unused = math.fsum(max(0, p["allocated_seconds"]-p["actual_compute_s"]) for p in phases)
        late = sum(p["reason"] in {"returned_after_deadline", "validation_after_deadline", "missed_anchor"} for p in phases)
        stops = [str(inner["stop_reason"]) for p in phases
                 if (inner := p.get("inner")) is not None and inner.get("stop_reason") is not None]
        aggregate.append((f"{arm}/{k}", len(phases), sum(bool(p["accepted"]) for p in phases), late,
                          spread(p["actual_compute_s"] for p in phases), fmt(unused), counts(p["reason"] for p in phases), counts(stops)))
    table(L, ["方法 / 阶段", "阶段数", "接纳数", "迟到数", "实耗秒中位［范围］", "本槽余量合计秒", "阶段理由", "内层停止理由"], aggregate)
    table(L, ["C1 实例 / 重复", "阶段", "请求秒", "锚点秒", "候选就绪秒", "阶段结束就绪秒", "推进至任务秒", "槽实耗 / 累计秒",
              "结论", "生效 J 前后", "生效 Pd 前后", "原记录"], detail)
    L.extend(["候选就绪用于接纳检查。阶段结束就绪计入额外已测开销，用于继续推进虚拟任务时钟。"
              "每槽余量互不转拨，越界返回的实际费用计入总支出。", ""])
    return budgets


def write_curves(L, out, rows, decision):
    L.extend(["## 5. 首次路线分歧与早晚观测贡献", ""])
    by_id = {row["run_id"]: row for row in rows}
    details = []
    for p in decision["comparisons"]:
        a,b = (by_id[p[f"{arm}_run_id"]]["result"]["physical_replay"] for arm in ARMS)
        aw,bw = a["waypoints"],b["waypoints"]
        shared = next((k for k,(u,v) in enumerate(zip(aw,bw)) if u != v), min(len(aw),len(bw)))
        if aw == bw:
            change = "路线一致"
        else:
            ai = aw[shared] if shared < len(aw) else "终止"
            bi = bw[shared] if shared < len(bw) else "终止"
            change = f"{fmt(a['planned_arrival_times_s'][shared-1])} s，节点 {aw[shared-1]} 后分别走向 {ai} / {bi}"
        values = [(t, x-y) for t,x,y in zip(a["observation_times_s"],a["survival"][1:],b["survival"][1:],strict=True)]
        early = math.fsum(d for t,d in values if t <= a["horizon_s"]/2)
        late = math.fsum(d for t,d in values if t > a["horizon_s"]/2)
        first = next((t for t,d in values if abs(d)>1e-10), None)
        if not math.isclose(early+late, a["J"]-b["J"], rel_tol=0, abs_tol=1e-8):
            raise ValueError(f"存活曲线与 J 差值不符 {p['instance']}")
        details.append((p["instance"], shared, change, fmt(first), fmt(early,9,signed=True), fmt(late,9,signed=True),
                        fmt(early+late,9,signed=True),fmt(p["delta_pd_percentage_points"],4,signed=True)))
    if details:
        table(L, ["实例", "共同航点数", "首次路线分歧", "首次质量差异秒", "前半时域 ΔJ", "后半时域 ΔJ", "总 ΔJ", "终点 ΔPd 百分点"], details)
        L.extend(["前后段按原任务物理时钟 H/2 划分。正 ΔJ 表示存档的 C1 曲线累计未发现质量较低。"
                  "差值来自已有的共同观测轴。 " + link(out,"survival.csv","全观测曲线"), ""])
    else:
        L.extend(["尚无经过完整性检查的代表路线配对。", ""])


def write_resources(L, out, rows, budgets, status, decision):
    L.extend(["## 6. 资源与正式判定", ""])
    if rows:
        resources = []
        for arm in ARMS:
            group = [row for row in rows if row["task"]["method"] == arm]
            result = [row["result"] for row in group]
            resources.append((arm,len(group),
                              spread(r["raw"]["active_compute_s"] for r in result),
                              spread(r["algorithm_wall_s"] for r in result),
                              spread(r["algorithm_cpu_s"] for r in result),
                              spread(r["record"]["process_wall_s"] for r in group),
                              spread((r["record"]["peak_rss_bytes"] for r in group),1/2**20),
                              spread(r["input_load_s"] for r in result),
                              spread(r["independent_audit_s"] for r in result),
                              fmt(math.fsum(max(0,r["raw"]["total_seconds"]-r["raw"]["active_compute_s"]) for r in result)),
                              fmt(max((r["raw"]["deadline_overshoot_s"] for r in result),default=0),6)))
        table(L, ["方法","任务数","主动计费秒","算法墙钟秒","CPU 秒","进程墙钟秒","峰值 RSS MiB","读取输入秒","独立审计秒",
                  "总预算空余合计秒","最大实际返回越界秒"], resources)
        L.extend(["资源列为中位数和范围。既有初始路线历史生成成本共同外置。外部独立审计仅核验证据。"
                  "两组整次可接纳预算均为 30 秒，实耗差异仅作描述。", ""])
        table(L, ["实例 / 方法 / 重复","算法墙钟秒","CPU 秒","进程墙钟秒","峰值 RSS MiB","独立审计秒","返回越界秒","进程记录"], budgets)
    L.extend([f"**预声明判定 {TICK}{decision['status']}{TICK}。**", ""])
    if decision["comparisons"]:
        regions = decision["winners_by_scene"]
        L.append(f"- 有效 {status['valid']}/24。达到 0.5% J 改善的实例 {decision['instance_winners']}/4，"
                 f"其中 Lake {regions.get('lake_ontario',0)}/2，Hudson {regions.get('arctic_ocean',0)}/2。")
        flags = ("是" if decision["quality_protected"] else "否", "是" if decision["pd_protected"] else "否")
        L.append(f"- J 全部在退化容差内 {flags[0]}。Pd 损失均在 0.5 个百分点内 {flags[1]}。")
        if decision["screen_passed"]:
            L.append("- 可以按本批协议进入独立日期验证设计。")
        elif (decision["instance_winners"] >= 3 and all(regions.get(k,0) >= 1 for k in ("lake_ontario","arctic_ocean"))
              and decision["quality_protected"] and not decision["pd_protected"]):
            L.append("- J 质量门槛达到，终点 Pd 未通过推广检查，本固定配置结束。")
        else:
            L.append("- 本固定配置未通过工程筛选，逐例正负结果保留，本轮结束。")
    else:
        L.append("- 完整性门槛待处理，当前证据不能作正式性能判断。")
    L.extend(["", "本轮仅支持四个已见 H2 实例上固定预测、主覆盖与有限预算的比较。"
              "结果范围是持续未发现分支的虚拟执行，尚无独立泛化、实机收益、实时预报更新或全局及 ε 最优性认证。", "",
              "证据入口", ""])
    for name, label in (("comparison.csv","逐次对照"),("instance_comparison.csv","中位代表路线"),("phases.csv","阶段账本"),
                        ("survival.csv","完整剩余质量曲线"),("summary.json","结构化判定"),("REPORT.md","自动报告"),("runs","原始运行"),("figures","诊断图")):
        if (out / name).exists():
            L.append("- " + link(out,name,label))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project", type=Path, default=Path.cwd())
    p.add_argument("--config", type=Path)
    p.add_argument("--out", type=Path)
    p.add_argument("--check", action="store_true")
    p.add_argument("--replace", action="store_true")
    args = p.parse_args()
    project = args.project.resolve()
    if not (project/"scripts/run_eight_neighbor_rolling.py").is_file():
        project = project/"asar_repro"
    sys.path.insert(0,str(project/"scripts"))
    import run_eight_neighbor_rolling as runner
    config_path = (project/(args.config or runner.DEFAULT_CONFIG)).resolve()
    out = runner.output_path(project/(args.out or runner.DEFAULT_OUT))
    if not out.is_dir():
        p.error(f"Output evidence directory does not exist: {out}")
    cfg, identity, status, rows, decision, errors = evidence(runner,config_path,out)
    lines = ["# 滚动规划最小验证结果",""]
    write_identity(lines,runner,config_path,out,cfg,identity,status,errors)
    write_quality(lines,out,rows,decision)
    budgets = write_phases(lines,out,rows)
    write_curves(lines,out,rows,decision)
    write_resources(lines,out,rows,budgets,status,decision)
    report = out/"ANALYSIS.md"
    if not args.check:
        with report.open("w" if args.replace else "x",encoding="utf-8",newline="\n") as handle:
            handle.write("\n".join(lines)+"\n")
    print(f"{decision['status']} | verified {status['valid']}/24 | {len(errors)} evidence issues | "
          f"{'checked' if args.check else 'wrote'} {report}")


if __name__ == "__main__":
    main()
