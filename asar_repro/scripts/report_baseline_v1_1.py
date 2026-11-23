"""B7 handoff documents derived from gates and frozen evidence, never algorithm changes."""

from importlib.metadata import distributions
import json
from pathlib import Path
import sys

from benchmark_b5 import ROOT, read_json, save_json
from asar_repro.scenarios import digest, config_digest
from asar_repro.search_reporting import environment_versions


def prepare_handoff(output,gates):
    real=ROOT/"outputs/baseline_v1.1/lake_ontario_real"
    metadata=read_json(real/"metadata.json")
    cfg=metadata["provenance"]["config"]
    b6=read_json(ROOT/"configs/b6_comparison.json")
    warm=read_json(real/"b6_workers/warm_start.json")
    methods=[dict(name="ParallelTrack",implementation="local dynamic envelope-based PT",certification="none"),
             dict(name="ASAR_paper",heuristic="paper_greedy",epsilon=b6["epsilon"],certification="none; dynamic counterexample retained"),
             dict(name="ASAR_mass_lb",heuristic="mass_lb",epsilon=b6["epsilon"],certification="conditional discrete bound only if search completes; no B6 run completed"),
             dict(name="zero",scope="toy/Oracle reference",certification="conditional on model and completed search"),
             dict(name="ACO_inspired",scope="old synthetic only; not run in B6; not ACO_original")]
    environment=dict(interpreter=sys.executable,versions=environment_versions(),
                     installed_distributions=sorted([dict(name=d.metadata.get("Name",""),version=d.version) for d in distributions()],key=lambda d:d["name"].lower()))
    save_json(output/"methods_and_environment.json",dict(methods=methods,environment=environment))
    protocol=dict(protocol="ASAR_baseline_v1.1_frozen_main_experiment",version=1,
                  changes_require="new protocol version and separate results table; never overwrite this protocol",
                  canonical_scenario="lake_ontario",forcing_kind="historical_real",
                  experiment_label="historical_real_forcing_allwater",mission=cfg,
                  particle_archive=dict(path=b6["archive"],sha256=b6["archive_sha256"]),
                  particle_metadata_sha256=b6["metadata_sha256"],
                  source_manifest_sha256=metadata["provenance"]["input_fingerprints"]["manifest_sha256"],
                  original_forcing=metadata["provenance"]["input_fingerprints"]["sources"],
                  start_vertex=144,time_zero="CST frame, no sensing",time_index="propagate to t then sense arrival cell for t=1..49",
                  sensor="one-cell glimpse; q=0.78; no false detections; no renormalization",
                  objective="J = sum(post_detection_M[t], t=1..T); minimize",
                  secondary_metric="Pd_T=1-M_T; maximize separately",
                  mass_policy="retain land/outside/inactive/unknown weights",
                  trajectory_columns="preserve stable trajectory_id and initial_weights; no per-node Leeway calls",
                  baseline_methods=methods[:3],search_limits=b6["limits"],
                  epsilon=b6["epsilon"],initial_path=warm["path"],initial_path_sha256=config_digest(warm["path"]),
                  initial_J=warm["J"],input_seed=41,
                  stochastic_planners=dict(seeds=list(range(10)),trials=10,scope="future predeclared stochastic experiments only; not evidence these trials ran"),
                  deterministic_timing_repeats=3,
                  fairness="same frozen input, q,T,UTC,start,initial PT and per-run budgets; paired seeds for stochastic methods",
                  threads=1,timing="fresh child process, separate warm start/search/preprocessing; diagnostics separate",
                  memory="isolated process peak working set; report scope and any allocation tracer overhead",
                  audit_atol=dict(J=1e-10,Pd=1e-10,mass=1e-12),
                  outcome_rules="report every run, including timeout/open/expansion/watchdog stops; null when no complete path; incumbent origin explicit",
                  certificate="paper_greedy never certified; mass_lb/zero only with valid model and completed search; not maritime safety assurance",
                  extensions="perturbed forcing, rolling replanning, aircraft constraints, other scenarios require separate labeled extension tables",
                  score_code_sha256={n:digest(ROOT/"src/asar_repro"/(n+".py")) for n in ("objective","motion","belief","grid")})
    save_json(output/"frozen_experiment_protocol.json",protocol)
    save_json(output/"protocol_sha256.json",dict(path="frozen_experiment_protocol.json",sha256=digest(output/"frozen_experiment_protocol.json")))
    content="""# Baseline v1.1 离线复跑与恢复

本地已有 maritime-sar 环境时，在 asar_repro 下执行一条命令：

    & 'C:\\Users\\35448\\.conda\\envs\\maritime-sar\\python.exe' scripts/replay_baseline_v1_1.py

可将命令中的解释器替换为已有兼容环境，使用 --output-dir 指定新的 outputs/baseline_v1.1 子目录。入口为 Python，不执行 PowerShell 脚本或更改系统执行策略。脚本不安装或升级依赖，禁用 Python 出站 socket 连接及 PROJ 网络；每次输出到新目录，完整执行验收、重新积分、重放、报告和新归档。正常退出为 0；任一门槛失败退出 2，汇总标记 blocked。耗时与内存是新的测量，不要求与旧值完全相同。

离线包包含代码、配置、测试、已缓存原始风流、粒子和 B0–B6 结果、B7 复验证据、Git bundle 与 payload_sha256.json。它不包含 Conda 二进制环境；须事先备妥 methods_and_environment.json 所列兼容环境，不得靠隐式升级解决复跑失败。

恢复到另一位置：先展开 ZIP 到 staging，找到其中的 baseline_history.bundle；使用 git clone --config core.autocrlf=false -b baseline-v1.1 <bundle绝对路径> <新的仓库目录>，再将 staging/asar_repro 的文件覆盖到新仓库的 asar_repro 子目录（恢复自己的新目录，不覆盖当前工程）。关闭该新仓库的自动换行转换，以保留冻结字节。Git bundle 保存 B6 起始 HEAD 及 v1.0 标签；ZIP 附带本次新增 B7 文件，其字节由 payload_sha256.json 保护。随后在新目录运行上述单条命令。若旧 v1.0 工作树不在恢复位置，Git 对象的 180 份字节校验仍会执行，报告明确区分对象恢复证据与原工作树现场证据。

ZIP 的 SHA-256 存于 archive_checksum.json，包内每个条目在创建后都重新读取计算 SHA-256。最终验证报告和 validation_summary.json 是 ZIP 校验后的交付侧文件，位于 ZIP 旁，避免自引用指纹。首次归档不包含自身，也不重复打包过往 ZIP/bundle。

仅重做有限检查时，可以分别运行（目标目录必须新建，不能指向旧输出）：

    python -m pytest -q
    python scripts/validate_forcing.py --output outputs/baseline_v1.1/NEW/forcing_audit.json
    python scripts/generate_historical_drift.py --verify-replay
    python scripts/compare_b6.py --output-dir outputs/baseline_v1.1/NEW/b6

本次协议只冻结实验，不实施创新算法。真实环境与合成环境不能混入同一算法主排名；条件性模型界与实验数值分开报告。
"""
    (output/"offline_replay.md").write_text(content,encoding="utf-8")


def final_report(output,summary):
    status=summary["status"]
    lines=["# Baseline v1.1 最终验证报告", "", f"**B7 状态：{status}。**", "",
           f"复跑基准 Git commit：{summary['source_commit']}；v1.0 标签：abd1b472798fbf3d318e83d09caf9b69cc459122。",
           "B7 仅新增验证、归档、报告与实验协议文件；数值核心与已验收实验不修改。新增验证脚本通过源码指纹及 ZIP 成员清单记录，Git bundle 保存复跑时 HEAD。", "",
           "| 强制门槛 | 状态 | 证据/失败原因 |", "|---|---|---|"]
    for name,g in summary["gates"].items():
        detail=g.get("error",str(g.get("evidence",{})))
        lines.append(f"| {name} | {g['status']} | {detail.replace('|','/')} |")
    if status!="passed":
        lines += ["", "存在未通过的强制门槛。此次不定版、不开放创新阶段绿灯；请查阅同目录 validation_summary.json 与命令日志。",
                  "旧实验数值不构成本轮验收通过证据。未实施创新点。"]
        return "\n".join(lines)+"\n"
    real=ROOT/"outputs/baseline_v1.1/lake_ontario_real"
    rows=read_json(real/"runs.json")
    audit=read_json(output/"forcing_audit.json")
    source_list=read_json(output/"real_forcing_files.json")
    environment=read_json(output/"methods_and_environment.json")["environment"]
    lines += ["", "本轮环境："+str(environment["versions"])+"。实际解释器："+environment["interpreter"]+"。完整已安装包版本单列保存；未安装或升级 OpenDrift。"]
    lines += ["", "## 已复现：数学实现与可验证事实", "",
              "Eq.(1)、(5)–(7)、t=0 无探测、四邻接路径、独立 DFS Oracle、路径专属未探测权重与无路径连续性约束的 Algorithm 2 保持原行为。搜索/启发式/评分器字节与 v1.0 一致；v1.1 对原版 180 文件的唯一变更为 planner_adapter.py 的报告字段与计时扩展。旧 v1.0 Git 对象可恢复，原工作树是否存在及逐文件核验结果单列。",
              "独立真实积分比较全部 21 个 NPZ 字段；恒定环境 run_constant 按原配置重新积分后与旧归档逐字段比较。正常/中止、PT/search/no-path、条件认证以及原动态反例均有回归测试。",
              "3×3、T=4、q=.78 反例：paper_greedy 根值 2.6170801771，大于 Oracle 2.5417333379。另一个动态 ε=1 的例子返回次优路径。paper_greedy 本地保持未认证；mass_lb/zero 仅在模型前提成立且搜索完成时可记条件性离散界。浮点实例验证不是所有场景的形式证明或实海安全保证。", "",
              "## 近似复现：一组完整历史风流与 Leeway", "",
              "已完成 Lake Ontario 的本地 HRRR 风 + LOOFS 流配对。事件日期 2025-08-26，缓存有效 UTC 为 13–17 时；事故 14:45，CST 15:45，搜索结束 15:52:33.740，原生轨迹到 15:53。500 粒子，seed=41，PIW-2，137 原生帧与 50 规划帧，T=49、q=.78。",
              "HRRR：5 个各自循环的 f00 分析，10 m UGRD/VGRD，m/s；获取方式为官方 S3 对原始 GRIB2 的逐字节消息范围提取，非完整全变量文件。原生 Lambert 双线性插值后旋转为东/北分量。",
              "LOOFS：5 个原始 FVCOM netCDF，18 UTC nowcast 循环提供回算有效时次；u/v，m/s，最浅 sigma≈−0.025，含点原生三角面内常值；时间线性插值，最大间隔 3600 s。",
              f"流场节点经纬度范围：{audit['fields']['current']['lon_lat_bounds']}。搜索格心范围：{audit['roi']['search_centres_bbox_lon_lat']}。风场原生投影范围与投影参数详见 forcing_audit.json 的 fields.wind.archive_extent。",
              "reader 为本地 historical_reader.py，通过 OpenDrift 四个实际环境分量查询验证非 fallback。全水域岸线策略 historical_real_forcing_allwater；FVCOM 湿干/域外仍有显式状态，保留 land/outside/inactive/unknown 质量。289 格心中流场覆盖 221、域外 68；本次实际粒子云保持有效覆盖。缺测不会替换成虚构常量。", "",
              "| 角色 | 有效 UTC | 本地文件 | SHA-256 |", "|---|---|---|---|"]
    for source in source_list:
        lines.append(f"| {source['role']} | {source['valid_utc']} | {source['path']} | {source['sha256']} |")
    lines += ["", "逐文件官方 URL、获取范围/循环与读取元数据在原始来源清单、B3 metadata 和 B7 real_forcing_files.json 中保留。", "",
              "## 相同真实输入的基线结果", "",
              "| 方法 | ε | J | Pd(T) | 状态 | 来源 | 秒（求解/构造） |", "|---|---:|---:|---:|---|---|---:|"]
    for r in rows:
        lines.append(f"| {r['algorithm']} | {r['epsilon']} | {r['J']:.10f} | {r['Pd_T']:.8f} | {r['stop_reason'] or r['search_status']} | {r['incumbent_source']} | {r['planner_wall_s']:.6f} |")
    lines += ["", "上表保持原 B6 测量；B7 在独立目录再次运行，路径、J/Pd/M、节点计数、状态和来源相同，耗时另存。PT 不计搜索完成率；6 次搜索 2 完成、4 中止且保留 PT。本轮 B6 结果全部未获离散认证。",
              "B0 冻结的旧 17/32 中止统计保持原数。B5 新真实输入 36 次扫描中 10 完成、26 因展开限制中止，另两个 OPEN=2400 探针中止；ε=1.04 从 600 上限的中止改善为 1222 次展开完成。新旧环境和预算不同，不能把两个完成率直接解释为算法改进。",
              "J 是时间累积目标，Pd(T) 是末时刻指标；ε=1.04 的 J 更小而 Pd 略低。J_over_PT 的分母是本地 PT，不是最优值。原文 C++/M1 Pro 时间未改，本地 Python/Windows 不作跨机器加速比较。", "",
              "## 未复现与已知局限", "",
              "- 原作者精确模式循环、粒子、地图与人工 PT，以及原始完整真实实验未逐点复现。真实 forcing 不意味着已获得作者原数据。",
              "- Bay of Fundy、Hudsons/Arctic 场景、Salish Sea 仍只有旧 constant_synthetic 验收结果。用户提供的其他 ZIP 尚未导入并完成变量、UTC/空间、reader 与质量审计；Salish 包还明确只有风场与核查记录。不能仅凭 ZIP 存在宣称完整真实风流可用。Lake 的旧 synthetic 证据也保留。",
              "- 未实现岸线碰撞、海冰、飞行转弯/返航约束、在线滚动重规划及其他原系统集成。",
              "- paper_greedy 的动态下界反例保留；mass_lb 与 ε=1 的大规模搜索在有限预算下未完成，不能补造证书。",
              "- ACO_inspired 只保留旧合成对照，本轮不运行；没有 ACO_original 复现声明。",
              "- Windows 单次计时与进程峰值受调度/导入影响；独立 cProfile/tracemalloc 诊断不混入原速统计。",
              "- B6 首次调度的文件名后缀问题已修复且失败尝试保留，未纳入正式结果表。", "",
              "## 移交、离线归档与冻结协议", "",
              f"本轮证据目录：{output.relative_to(ROOT).as_posix()}。validation_summary.json 为逐门槛权威状态；archive_checksum.json 给出 ZIP SHA-256 和逐条目复核数量。ZIP 包含缓存原始风流及 Git bundle，不包含 Conda 环境；最终报告和汇总为包旁侧文件。",
              "方法与安装版本清单见 methods_and_environment.json。离线复跑与从 bundle 恢复步骤见 offline_replay.md。入口为现有 Python 解释器执行 scripts/replay_baseline_v1_1.py，无需改变 PowerShell 执行策略；失败必须输出 blocked 并非零退出。",
              "下一阶段不可变主实验契约在 frozen_experiment_protocol.json，SHA 在 protocol_sha256.json。冻结真实粒子指纹、UTC/LKP/CSP/CST、T/q、ID/质量策略、统一评分器、同一初始 PT、5000/20000/30 秒限制与 ε 三档。后续随机方法预先冻结 seed 0–9、10 次；确定性计时建议三次并逐次保留。这些是未来协议，未冒充本轮已执行的创新实验。",
              "扩展风流扰动、滚动重规划、其他场景须独立标记和单列；不得改变主实验输入后在同一主表宣称优越性。七项 baseline 绿灯条件已通过；这不要求四组真实场景全完成，也不要求 ε=1 大规模搜索全部结束。",
              "本轮停止于 B7，不实施创新点。"]
    return "\n".join(lines)+"\n"
