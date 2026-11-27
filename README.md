# 同一模型下的完整路线求解实验

分支：**solver-paradigm-study-20261127**  
基点：STDC 最终评估提交 **12b16441fbc5cae8539dcd247d46f7c27d5b8f12**  
本地执行状态：**P0、A、B5、B30 已完成，C300 未触发。** 冻结源码为 `a349daf`。A 阶段 9 个 tiny 实例的 count 与独立 DFS 一致。Lake 与 Hudson 的 5 秒筛选中，ILS 和 CEM 均未通过质量或时间门槛。

[结果分析与逐次证据](asar_repro/outputs/solver_paradigm_study_20261127/local_r1/ANALYSIS.md) · [逐次指标 CSV](asar_repro/outputs/solver_paradigm_study_20261127/local_r1/comparison.csv) · [C300 筛选记录](asar_repro/outputs/solver_paradigm_study_20261127/local_r1/C300_selection.json)

本批回答两个问题：保持原来的粒子、探测、运动与 J 指标，改换完整路线求解机制能否找到更好的路线；在可控制的小中规模实例上，已有解到底离最优还有多远。

## 从这里开始

1. 阅读[本地运行说明](asar_repro/docs/solver_paradigm_study/LOCAL_RUNBOOK.md)，在已有 maritime-sar 环境执行 P0。
2. 按[实验协议](asar_repro/docs/solver_paradigm_study/plan.md)依次执行 A、B5、B30。
3. 仅在自动筛选触发时运行 C300；按[判断与停止规则](asar_repro/docs/solver_paradigm_study/decisions.md)解释结果。
4. 汇总原始记录，填写[结果分析模板](asar_repro/docs/solver_paradigm_study/results_template.md)，将结果推回本分支。

**不要把本次静态检查、上一批测试成绩或历史最好值写成新算法已验证的结果。** 本地 validate 和 A 阶段会检查原评分一致性、完整路线合法性和 count 模型数值结果；失败时后续正式阶段被阻断。

## 已准备的内容

| 内容 | 入口 |
|---|---|
| 有限实验协议、预算和顺序 | [plan.md](asar_repro/docs/solver_paradigm_study/plan.md) |
| Windows / Linux 本地命令、失败处理与回传 | [LOCAL_RUNBOOK.md](asar_repro/docs/solver_paradigm_study/LOCAL_RUNBOOK.md) |
| ILS 与完整时域 CEM 的实际机制、参数 | [route_methods.md](asar_repro/docs/solver_paradigm_study/route_methods.md) |
| 完整单位流、命中次数与整数割线数学模型 | [count_model.md](asar_repro/docs/solver_paradigm_study/count_model.md) |
| 质量、时间、延长诊断与停止门槛 | [decisions.md](asar_repro/docs/solver_paradigm_study/decisions.md) |
| 原始论文与适用边界 | [literature.md](asar_repro/docs/solver_paradigm_study/literature.md) |
| 冻结配置与输入指纹 | [solver_paradigm_study.json](asar_repro/configs/solver_paradigm_study.json) |
| 独立本地执行器 | [run_solver_paradigm_study.py](asar_repro/scripts/run_solver_paradigm_study.py) |
| ILS / CEM 源码 | [route_optimizers.py](asar_repro/src/asar_repro/route_optimizers.py) |
| 小中规模数值标尺 | [count_oracle.py](asar_repro/src/asar_repro/count_oracle.py) |

## 固定的实验规模

| 阶段 | 内容 | 任务数 | 算法预算合计 |
|---|---|---:|---:|
| P0 | 本地依赖、输入、测试与冻结 | 不作为性能实验 | 取决于本地验证 |
| A | 18 个诊断实例；五种路径方法、count；tiny 加独立 DFS | 117 | 1125 秒 |
| B5 | Lake / Hudson，5 秒，确定性各 3 次、随机各 5 seeds | 38 | 190 秒 |
| B30 | 同矩阵独立运行 30 秒 | 38 | 1140 秒 |
| C300 | B30 信号触发的有限延长诊断 | 最多 8 | 最多 2400 秒 |
| H | 独立档案验证 | 未设计、未启用 | 不自动执行 |

A+B5+B30 的算法上限合计 **2455 秒（40 分 55 秒）**。这不是总运行时间承诺：进程启动、输入与哈希检查、测试、结果审计、I/O、报告及 watchdog 余量另计。某些方法会提前完成；失败会停止阶段。

## 方法与共同契约

主要对照为 paper_baseline、anytime_zero、anytime_mass；新候选为 ILS 和完整 T 步 CEM。count 模型仅在诊断实例运行，没有自动对 500 粒子真实场景启动完整 MILP。

所有方法保持四邻移动、无等待、固定起点、自由终点、t=0 不探测、原粒子身份与特殊 bins、未发现质量不归一化；最小化原 J，Pd 使用同一路线单列。正式比较均由冻结共同 PT 起步，计时包含路径复制和原评分复算；共同 PT 的原离线生成成本统一不计。历史参考只用于重放核验与目标阈值，不交给新方法热启动。

Fundy 的物理方向未验证标签继续保留，本批不进入主要矩阵。Frank–Wolfe、ALNS 自适应权重、学习方法、新场景和独立档案属于后续候选，未自动启用。

## 继承的研究结论

上一批结论仍是：暂停以 STDC 性能微调为中心的投入，保留其数学下界和审计价值。两个主场景同 5 秒预算的 zero/mass/STDC 最终质量相同，STDC 达到同质量更慢；该结论没有证明全局近最优，也未检验完不同路线求解范式。

- [上一批完整报告与原始记录](asar_repro/outputs/stdc_final_assessment_20261125_r1/FINAL_REPORT.md)
- [历史研究交接](asar_repro/RESEARCH_HANDOFF_20261125.md)
- [原论文阶段 0–8 复现入口](asar_repro/README.md)

本地验证证据和原始运行记录见上方结果入口。初次交付时的 `not_run` 状态保留在设计文档中。

