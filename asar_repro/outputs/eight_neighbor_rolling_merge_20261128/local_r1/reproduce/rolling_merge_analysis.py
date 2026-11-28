"""Read-only verification and Markdown reporting for a completed or blocked rolling-merge batch."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from importlib import import_module
import json
import os
from pathlib import Path
from statistics import median
import subprocess
import sys
import xml.etree.ElementTree as ET

DEFAULT_OUT = "outputs/eight_neighbor_rolling_merge_20261128/local_r1"
DEFAULT_CONFIG = "configs/eight_neighbor_rolling_merge.json"


def fmt(value, places=3):
    return "—" if value is None else f"{value:.{places}f}"


def text(value):
    return str(value).replace("|", r"\|").replace("\n", " ")


def mdrow(*parts):
    return "| " + " | ".join(map(text, parts)) + " |"


def group_table(lines, columns):
    lines.extend([mdrow(*columns), mdrow(*["---"] * len(columns))])


class Report:
    def __init__(self, runner, project, config, out):
        self.r = runner
        self.project = project
        self.config_path = config
        self.out = out
        self.lines = ["# 精确状态等价合并实验分析", ""]
        self.issues = []
        self.states = {}
        self.rows = {}
        self.conclusions = {}
        self.summaries = {}
        self.protocol = None
        self.tasks = None

    def add(self, *lines):
        self.lines.extend(lines)

    def link(self, path, label=None):
        path = self.out / path
        if not path.exists():
            return "—"
        relative = Path(os.path.relpath(path, self.out)).as_posix().replace(" ", "%20")
        return f"[{label or path.name}]({relative})"

    def error(self, label, exc):
        self.issues.append(f"{label}。{type(exc).__name__}: {exc}")

    def audit(self):
        if not (self.out / "protocol.json").is_file():
            self.issues.append("冻结协议缺失。正式结果不可判定。")
            return
        try:
            self.protocol, self.tasks = self.r.verify_protocol(self.config_path, self.out)
        except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as exc:
            self.error("冻结协议校验失败", exc)
            return
        config = self.protocol["config"]
        for stage in self.r.STAGES:
            status, rows = self.r.collect(self.out, self.tasks, self.protocol, stage)
            self.states[stage], self.rows[stage] = status, rows
            complete = status["status"] == "complete"
            rule = self.r.diagnostic_gate if stage == "D0" else self.r.decision
            self.conclusions[stage] = rule(config, rows, complete=complete)
        d0_complete = self.states["D0"]["status"] == "complete"
        admitted = False
        gate_path = self.out / "D0_gate.json"
        if d0_complete:
            try:
                expected = self.r.gate_payload(self.out, config, self.states["D0"], self.rows["D0"])
                if self.r.read(gate_path) != expected:
                    raise ValueError("D0 冻结门槛与原始证据不一致")
                admitted = bool(expected["decision"]["passed"])
            except (OSError, ValueError, TypeError, KeyError) as exc:
                self.error("D0 门槛校验失败", exc)
        elif gate_path.exists():
            self.issues.append("D0 有效性不足，发现无法核验的门槛文件。")
        f30_started = any((self.out / "runs").glob("F30_*")) or (self.out / "F30").exists()
        if f30_started and not admitted:
            self.issues.append("未验证到可接纳的 D0 门槛，却发现 F30 文件。")
        for stage in ("D0", "F30"):
            if stage == "F30" and not f30_started:
                continue
            if (self.out / stage / "summary.json").is_file():
                try:
                    self.check_summary(stage)
                except (OSError, ValueError, TypeError, KeyError, StopIteration, csv.Error) as exc:
                    self.error(f"{stage} 派生证据校验失败", exc)
            elif self.states[stage]["status"] == "complete":
                self.issues.append(f"{stage} 任务已齐备，缺少自动汇总。")

    def check_summary(self, stage):
        summary = self.r.read(self.out / stage / "summary.json")
        rows = self.rows[stage]
        if (summary["stage"] != stage or summary["status"] != self.states[stage]
                or summary["decision"] != self.conclusions[stage]
                or summary["protocol_sha256"] != self.r.digest(self.out / "protocol.json")
                or summary["formal_optimality_certificate"] is not False
                or summary["speedup_claim"] is not False
                or summary["raw_evidence"] != {row["run_id"]: row["record"]["result_sha256"] for row in rows}):
            raise ValueError("自动汇总与冻结身份或原始记录不一致")
        if stage == "F30" and summary["D0_gate_sha256"] != self.r.digest(self.out / "D0_gate.json"):
            raise ValueError("F30 门槛摘要与冻结 D0 不一致")
        _, derived = self.r.derived_rows(rows)
        derived["instance_comparison"] = [
            pair for gate in summary["decision"].get("pair_gates", {}).values()
            for pair in gate["comparisons"]
        ]
        if set(summary["derived_file_sha256"]) != {name + ".csv" for name in derived}:
            raise ValueError("CSV 清单不完整")
        for name, entries in derived.items():
            path = self.out / stage / f"{name}.csv"
            if self.r.digest(path) != summary["derived_file_sha256"][path.name]:
                raise ValueError(f"{name}.csv SHA-256 不一致")
            with path.open(encoding="utf-8", newline="") as file:
                reader = csv.reader(file)
                fields = next(reader)
                actual = Counter(tuple(record) for record in reader)

            def cell(value):
                if isinstance(value, (dict, list)):
                    return json.dumps(value, ensure_ascii=False)
                return "" if value is None else str(value)

            if any(set(record) - set(fields) for record in entries):
                raise ValueError(f"{name}.csv 缺少原始运行字段")
            expected = Counter(tuple(cell(record.get(field)) for field in fields) for record in entries)
            if actual != expected:
                raise ValueError(f"{name}.csv 行值与原始证据不一致")
        self.summaries[stage] = summary

    def status(self):
        if self.issues or self.states.get("D0", {}).get("status") != "complete":
            return "incomplete_or_invalid"
        if not self.conclusions["D0"]["passed"]:
            return "D0_not_admitted"
        if not self.rows.get("F30") and not (self.out / "F30").exists():
            return "D0_admitted_F30_not_run"
        if self.states["F30"]["status"] != "complete":
            return "incomplete_or_invalid"
        return self.conclusions["F30"]["status"]

    def identity(self):
        self.add("## 1. 版本与有效性", "")
        config = self.protocol["config"] if self.protocol else self.r.read(self.config_path)
        try:
            current = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.project, text=True).strip()
            branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=self.project, text=True).strip()
        except (OSError, subprocess.SubprocessError):
            current, branch = "—", "—"
        self.add(f"- 本次分析状态 **{self.status()}**。当前检出提交 `{current}`，分支 `{branch}`。")
        self.add(f"- 父参考 `{config['study_base_commit']}`。既有 rolling pilot 资料保持原判定。")
        self.add(f"- 输出目录 `{self.out.relative_to(self.project).as_posix()}`。")
        self.add("- 四份 H2 固定粒子档案和共同初始路线属于已见开发数据。每组重复反映计时差异。")
        if self.protocol:
            p = self.protocol
            env = p["environment"]
            self.add(f"- 冻结时间 {p['created_utc']}。任务排列 seed {p['config']['task_order_seed']}。")
            self.add(f"- 协议 SHA-256 `{self.r.digest(self.out / 'protocol.json')}`。"
                     f"配置 SHA-256 `{p['config_sha256']}`。"
                     f"[冻结协议](protocol.json) · [预检](preflight.json) · "
                     f"{self.link(self.config_path, '冻结配置')} · "
                     f"{self.link(self.project / config['reference_manifest'], '参考清单')}")
            platform_details = "，".join(
                env[key] for key in ("platform", "machine", "processor") if env[key]
            )
            self.add(f"- Python {text(env['python'])}。{platform_details}，"
                     f"{env['logical_cpus']} 个逻辑核。五个数值线程设置均为 1。"
                     "RSS 监控上限 2 GiB。")
            self.add("- 软件版本 " + "、".join(f"{k} {v}" for k, v in env["packages"].items()) + "。")
            self.add(f"- 来源证据包含 {len(p['references']['files'])} 份直接文件 SHA 和 "
                     f"{len(p['references']['git_blobs'])} 份继承 Git blob。")
        if (self.out / "RUNNING.lock").exists():
            self.add("- 生成报告时存在运行锁。完整性只能按本次读取的证据判定。")
        self.add("")
        group_table(self.lines, ("阶段", "计划", "有效", "尚缺", "失败或无效", "阶段状态"))
        for stage in ("D0", "F30"):
            diff = self.states.get(stage)
            if diff is None:
                self.add(mdrow(stage, config["stages"][stage]["tasks"], "—", "—", "—", "无法核验"))
                continue
            dormant = stage == "F30" and not any((self.out / "runs").glob("F30_*"))
            self.add(mdrow(stage, diff["planned"], diff["valid"], len(diff["missing"]), len(diff["errors"]),
                           "未运行" if dormant else diff["status"]))
            for item in diff["errors"]:
                link = self.link(f"runs/{item['run_id']}", item["run_id"])
                self.add(mdrow("失败证据", link, "", "", "", item["error"]))
        self.add("")
        for issue in self.issues:
            self.add(f"- 核验异常。{text(issue)}")
        if self.issues:
            self.add("")

    def validation(self):
        self.add("### 本地软件验证", "")
        group_table(self.lines, ("尝试", "状态", "通过", "失败", "错误", "跳过", "证据"))
        for result in sorted((self.out / "validation").glob("*/result.json")):
            verdict = self.r.read(result)
            xml_path = result.with_name("pytest.xml")
            counts = Counter()
            if xml_path.is_file():
                for case in ET.parse(xml_path).getroot().findall(".//testcase"):
                    counts[next((tag for tag in ("failure", "error", "skipped") if case.find(tag) is not None),
                                "passed")] += 1
            self.add(mdrow(result.parent.name, verdict["status"],
                           *[counts[key] if xml_path.is_file() else "—"
                             for key in ("passed", "failure", "error", "skipped")],
                           " · ".join(self.link(p, name) for p, name in
                                      ((result, "命令与结果"), (xml_path, "JUnit"),
                                       (result.with_name("stdout.log"), "stdout"),
                                       (result.with_name("stderr.log"), "stderr")))))
        self.add("", f"执行命令、耗时和退出记录。 {self.link('commands', '命令日志')}", "")

    def d0(self):
        self.add("## 2. D0 严格等价机会", "")
        self.add("D0 各项使用原八邻接问题和共同路线，计入影子索引开销。"
                 "主搜索呈交索引的非终止子状态为分母。"
                 "原 J 剪除的子状态、根、终端和贪心补全的内部候选均排除。"
                 "更低 J 代表的更新也从可合并数量排除。"
                 "四项全部有效且至少一个实例同时达到 100 个和 5%，才进入 F30。", "")
        conclusion = self.conclusions.get("D0")
        if not conclusion:
            self.add("D0 结果无法核验。", "")
            return
        stats = self.r.derived_rows(self.rows["D0"])[1]["merge_diagnostics"]
        by_id = {s["run_id"]: s for s in stats}
        group_table(self.lines, ("实例", "非终止 child", "可合并", "比例", "更低 J 更新", "登记键数",
                                 "容量拒绝", "键 payload 峰值 MiB", "查找秒", "达标", "记录"))
        for item in conclusion["instances"]:
            s = by_id.get(item["run_id"], {})
            payload = s.get("payload_bytes_peak")
            self.add(mdrow(item["instance"], item["nonterminal_children"], item["mergeable_children"],
                           f"{item['mergeable_fraction']:.3%}", s.get("replaced_entries", "—"),
                           s.get("entries", "—"), item["capacity_skips"],
                           fmt(payload / 2**20 if payload is not None else None),
                           fmt(item["lookup_s"]), item["qualifies"],
                           self.link(f"runs/{item['run_id']}/result.json", item["run_id"])))
        self.add("", "查找时间包含键构造。容量拒绝只表示没有登记新键，可能限制测得的机会。"
                 "键 payload 只含保留的位置和权重数据。", "")
        group_table(self.lines, ("实例", "展开数", "末两 tick 占比", "终端生成事件",
                                 "guide / transition 秒", "键构造秒", "影子丢弃 / 陈旧跳过", "内层停止"))
        for s in stats:
            self.add(mdrow(s["instance"], s["expanded"], f"{s['final_two_tick_fraction']:.3%}",
                           s["terminal_candidates"], f"{fmt(s['guide_s'])} / {fmt(s['transition_s'])}",
                           fmt(s.get("key_build_s")), f"{s.get('discarded_children', '—')} / {s.get('stale_pops', '—')}",
                           s["inner_stop_reason"]))
        self.add("", f"- D0 判定 **{conclusion['status']}**。满足两个数值门槛的实例 "
                 f"{conclusion['qualifying_instances']}/4。 {self.link('D0_gate.json', '冻结机会门槛')} · "
                 f"{self.link('D0/merge_diagnostics.csv', '详细诊断')} · {self.link('D0/summary.json', '自动汇总')}",
                 "- 终端生成数以事件计。固定预算中的影子机会率只用于本轮准入。", "")

    def f30(self):
        self.add("## 3. F30 同预算对照", "")
        conclusion = self.conclusions.get("F30")
        if not self.rows.get("F30"):
            self.add("F30 未运行。以下四个配对的路线质量留待有效 F30 判定。", "")
            return
        gates = conclusion["pair_gates"]
        if not gates:
            self.add("F30 记录不完整或无效。本报告保留已核验原始运行，不作性能门槛判定。", "")
            return
        config = self.protocol["config"]
        group_table(self.lines, ("配对", "角色", "通过", "J 达标实例", "Lake / Hudson 达标",
                                 "J 无退化", "Pd 通过"))
        for spec in config["comparisons"]:
            gate = gates[spec["id"]]
            wins = gate["winners_by_scene"]
            self.add(mdrow(spec["id"], gate["role"], gate["screen_passed"], gate["instance_winners"],
                           f"{wins.get('lake_ontario', 0)} / {wins.get('arctic_ocean', 0)}",
                           gate["quality_protected"], gate["pd_protected"]))
        self.add("")
        for spec in config["comparisons"]:
            name = spec["id"]
            self.add(f"### {name}", "")
            group_table(self.lines, ("实例", "对照 J", "候选 J", "J 改善", "对照 Pd", "候选 Pd",
                                     "ΔPd 百分点", "J ≥ 0.5%", "J 退化", "Pd 超限", "代表运行"))
            for row in gates[name]["comparisons"]:
                link = " / ".join(self.link(f"runs/{row[key]}/result.json", row[key])
                                  for key in ("control_run_id", "candidate_run_id"))
                self.add(mdrow(row["instance"], fmt(row["J_control"], 8), fmt(row["J_candidate"], 8),
                               f"{row['relative_J_gain']:+.4%}", f"{row['pd_control']:.5%}",
                               f"{row['pd_candidate']:.5%}", f"{row['delta_pd_percentage_points']:+.5f}",
                               row["winner"], row["J_regression"], row["pd_drop_flag"], link))
            self.add("")
        self.add("J 和 Pd 来自按 J、重复序号排序选出的同一个中位代表运行。"
                 f"全部重复保留在 {self.link('F30/comparison.csv', '逐次对照')}。", "")
        self.add("每个配对需至少 3/4 实例达到 0.5% J 相对改善，两地区各至少一例，"
                 "任一实例的 J 退化不得超出相对容差 1e-8，终点 Pd 降幅不得超过 0.5 个百分点。", "")

    def mechanism(self):
        self.add("## 4. 机制证据", "")
        stage = "F30" if self.rows.get("F30") else "D0"
        if not self.rows.get(stage):
            self.add("没有可核验的机制记录。", "")
            return
        config = self.protocol["config"]
        cases = {}
        for row in self.rows[stage]:
            task = row["task"]
            cases.setdefault((task["instance"], task["method"]), []).append(row)
        group_table(self.lines, ("实例 / 方法 / 槽", "展开", "最大展开 tick", "末两 tick 展开",
                                 "终端生成事件", "OPEN 计数 / tick 范围", "下层首次 / 最终改善秒·来源",
                                 "外层可接替时刻 / 接纳决定", "原始记录"))
        for instance in config["instances"]:
            for method in config["stages"][stage]["methods"]:
                group = cases.get((instance, method))
                if not group:
                    continue
                selected = self.r.representative(group)
                replay = selected["result"]["physical_replay"]
                horizon_ticks = len(replay["observation_times_s"])
                for phase in selected["result"]["raw"]["phases"]:
                    inner = phase.get("inner")
                    details = ["—"] * 6
                    if inner is not None:
                        hist = inner["diagnostics"]["histograms"]
                        expanded = {int(tick): count for tick, count in hist["expanded_tick"].items()}
                        live = {int(tick): count for tick, count in hist["frontier_tick"].items() if count}
                        terminal = inner["stats"]["terminal_candidates"]
                        tail = sum(count for tick, count in expanded.items() if tick >= horizon_ticks - 2)
                        history = [entry for entry in inner["history"] if entry["source"] != "initial_route"]
                        times = " / ".join(f"{fmt(item['elapsed_s'])}·{item['source']}"
                                           for item in (history[0], history[-1])) if history else "—"
                        open_range = f"{sum(live.values())} / {min(live)}–{max(live)}" if live else "0 / —"
                        details = [inner["expanded"], max(expanded, default="—"), tail, terminal, open_range, times]
                    applied = phase.get("ready_time_s")
                    self.add(mdrow(f"{instance} / {method} / {phase['stage_index']}", *details,
                                   f"{fmt(applied)} / {phase['reason']}",
                                   self.link(f"runs/{selected['run_id']}/result.json", selected["run_id"])))
        self.add("", "F30 表使用各实例每方法的中位路线代表。内层记录与原模型审计后的外层接纳是两个时刻。"
                 "终端生成数按事件计，OPEN 按实际堆中元素计。"
                 f"{self.link(f'{stage}/incumbent_history.csv', '所有内层候选')} · "
                 f"{self.link(f'{stage}/phases.csv', '所有阶段和时刻')}", "")

        if stage == "D0":
            return
        gates = self.conclusions[stage]["pair_gates"]
        if not gates:
            return
        for name, gate in gates.items():
            improvements = sum(row["relative_J_gain"] > config["decision"]["relative_tolerance"]
                               for row in gate["comparisons"])
            regressions = sum(row["J_regression"] for row in gate["comparisons"])
            lake = [row for row in gate["comparisons"] if row["base_scene"] == "lake_ontario"]
            lake_gains = "、".join(f"{row['instance']} {row['relative_J_gain']:+.4%}" for row in lake)
            self.add(f"- {name} 有 {improvements} 例严格改善、{regressions} 例退化。Lake 两例的 J 相对变化为 {lake_gains}。")
        self.add("- 邻近权重、终端集中、覆盖率高、提前找到 incumbent 或少展开本身都不能推出最优。"
                 "索引开销、重新入队、按展开次数触发补全和可接替时刻会共同改变固定预算下的路线。", "")

    def resources(self):
        self.add("## 5. 阶段执行与资源", "")
        group_table(self.lines, ("阶段 / 方法", "实例×重复", "算法秒中位 / 最大", "CPU 秒中位",
                                 "进程秒中位", "RSS 最大 MiB", "独立审计秒中位",
                                 "最大返回越界秒", "在线接纳", "停止原因"))
        for stage, rows in self.rows.items():
            for method in sorted({row["task"]["method"] for row in rows}):
                arm = [row for row in rows if row["task"]["method"] == method]
                result = [row["result"] for row in arm]
                record = [row["record"] for row in arm]
                phases = [phase for r in result for phase in r["raw"]["phases"]]
                stops = Counter(phase["inner"].get("stop_reason") for phase in phases if phase.get("inner"))
                wall = [r["algorithm_wall_s"] for r in result]
                self.add(mdrow(f"{stage} / {method}", len(arm), f"{fmt(median(wall))} / {fmt(max(wall))}",
                               fmt(median(r["algorithm_cpu_s"] for r in result)),
                               fmt(median(r["process_wall_s"] for r in record)),
                               fmt(max(r["peak_rss_bytes"] for r in record) / 2**20),
                               fmt(median(r["independent_audit_s"] for r in result)),
                               fmt(max(r["raw"].get("deadline_overshoot_s", 0.0) for r in result), 6),
                               sum(p["stage_index"] > 0 and p["accepted"] for p in phases),
                               ", ".join(f"{k}×{v}" for k, v in stops.items()) or "—"))
        self.add("", "历史共同路线来自冻结 S30，复制、原模型重放和索引工作均计入本轮各方法。"
                 "进程额外记入加载和独立审计。内层 incumbent 日志用于描述搜索时刻。", "")
        self.add("### 路线来源与接纳", "")
        group_table(self.lines, ("阶段 / 方法", "完成运行", "最终已执行路径来源", "内层 incumbent 更新来源",
                                 "阶段决定 / 次数"))
        for stage, rows in self.rows.items():
            for method in sorted({row["task"]["method"] for row in rows}):
                raws = [row["result"]["raw"] for row in rows if row["task"]["method"] == method]
                sources = Counter(raw["history"][-1]["source"] for raw in raws if raw.get("history"))
                inner = Counter(item["source"] for raw in raws for phase in raw["phases"] if phase.get("inner")
                                for item in phase["inner"]["history"])
                reasons = Counter(phase["reason"] for raw in raws for phase in raw["phases"])
                values = [", ".join(f"{key}×{value}" for key, value in counts.items()) or "—"
                          for counts in (sources, inner, reasons)]
                self.add(mdrow(f"{stage} / {method}", len(raws), *values))
        self.add("", "`common_seed` 来自共同初始路线。阶段来源表示最后一次接纳。内层 incumbent 来源按事件计。", "")
        if self.rows.get("F30"):
            self.add("### F30 合并工作量", "")
            _, derived = self.r.derived_rows(self.rows["F30"])
            group_table(self.lines, ("方法", "非终止 child", "可合并", "实际丢弃", "代表更新",
                                    "陈旧跳过", "容量拒绝", "键 payload 峰值 MiB", "查找秒合计"))
            for name in ("C0_M", "C1_M"):
                stats = [s for s in derived["merge_diagnostics"] if s["method"] == name]
                if not stats:
                    continue
                fields = ("nonterminal_children", "mergeable_children", "discarded_children",
                          "replaced_entries", "stale_pops", "capacity_skips")
                self.add(mdrow(name, *[sum(row[key] for row in stats) for key in fields],
                               fmt(max(row["payload_bytes_peak"] for row in stats) / 2**20),
                               fmt(sum(row["lookup_s"] for row in stats))))
            self.add("")

    def end(self):
        self.add("## 6. 结论与适用边界", "")
        status = self.status()
        if status == "D0_not_admitted":
            self.add("四项有效性通过。按原门槛停止本固定配置，F30 未运行。"
                     "观察量限于已登记时间、精确键与固定索引容量。")
        elif status == "D0_admitted_F30_not_run":
            self.add("D0 达到机会门槛，F30 尚无运行证据。")
        elif status == "incomplete_or_invalid":
            self.add("证据完整性或有效性待解决。保留现有档案，暂停正式比较。")
        else:
            accepted = self.conclusions["F30"]["rolling_candidate_continue"]
            self.add("本配置具备设计独立验证的工程信号。" if accepted
                     else "本固定配置未达到滚动候选的双门槛，结束本轮。")
            self.add("通用状态合并、滚动内部的合并、净滚动，以及相对原 C0 的整体改善按四个配对单列。")
        self.add("局部严格支配适用于冻结模型的未来状态。实际墙钟结果取决于索引、堆顺序和重新展开。"
                 "实验依据四个已见案例，暂未建立新日期泛化、同质量加速或全局及 ε 最优证书。", "")
        self.add("证据链接", "")
        for stage in ("D0", "F30"):
            if (self.out / stage).exists():
                parts = [self.link(f"{stage}/{name}") for name in (
                    "REPORT.md", "summary.json", "comparison.csv", "instance_comparison.csv",
                    "merge_diagnostics.csv", "phases.csv", "survival.csv", "incumbent_history.csv")]
                self.add(f"- {stage}。{' · '.join(x for x in parts if x != '—')}")
        for folder, label in (("runs", "原始运行目录"), ("figures", "诊断图")):
            if (self.out / folder).exists():
                self.add(f"- {self.link(folder, label)}")
        self.add("")

    def build(self):
        self.audit()
        self.identity()
        self.validation()
        self.d0()
        self.f30()
        self.mechanism()
        self.resources()
        self.end()
        return self.status(), "\n".join(self.lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--config", type=Path, default=Path(DEFAULT_CONFIG))
    parser.add_argument("--out", type=Path, default=Path(DEFAULT_OUT))
    parser.add_argument("--check", action="store_true", help="audit and render without writing")
    parser.add_argument("--replace", action="store_true", help="explicitly overwrite ANALYSIS.md")
    args = parser.parse_args()
    project = args.project.resolve()
    out, config = (project / args.out).resolve(), (project / args.config).resolve()
    if not out.is_dir() or not config.is_file():
        parser.error("use the asar_repro working directory or supply --project, --out, and --config")
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(project / "scripts"))
    runner = import_module("run_eight_neighbor_rolling_merge")
    report = Report(runner, project, config, out)
    status, markdown = report.build()
    target = out / "ANALYSIS.md"
    if not args.check:
        with target.open("w" if args.replace else "x", encoding="utf-8", newline="\n") as file:
            file.write(markdown)
    print(f"{status} | {len(report.issues)} evidence issues | "
          f"{'checked' if args.check else 'wrote'} {target}")


if __name__ == "__main__":
    main()
