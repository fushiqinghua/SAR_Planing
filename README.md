# 四／八邻接物理一致性实验（待本地执行）

分支：**eight-neighbor-physical-study-20261127**  
基点：上一批结果提交 **3399015cdf2e20dabe5895e30e3ae812bb68b049**  
交付状态：**源码、协议、配置和测试已准备；仅静态检查，测试与实验均 `not_run`。**

本批推进一个明确的问题：**同一条历史强路线起步，在相同地速、飞行时长、观测时钟与覆盖假设下，开放对角运动能否改善 SAR 搜索质量？** 请先按本地说明验证，再执行预定矩阵；不会自动启动长预算或生成新漂移档案。

## 本批入口

| 内容 | 文件 |
|---|---|
| 逐条本地命令、预检、测试、冻结与回传 | [LOCAL_RUNBOOK.md](asar_repro/docs/eight_neighbor_physical/LOCAL_RUNBOOK.md) |
| 有限实验矩阵与成本范围 | [PLAN.md](asar_repro/docs/eight_neighbor_physical/PLAN.md) |
| 恒速运动、共同观测时钟与概率评分 | [MODEL.md](asar_repro/docs/eight_neighbor_physical/MODEL.md) |
| 同预算判断门槛、负结果与停止规则 | [DECISIONS.md](asar_repro/docs/eight_neighbor_physical/DECISIONS.md) |
| 结果填写与证据清单 | [RESULTS_TEMPLATE.md](asar_repro/docs/eight_neighbor_physical/RESULTS_TEMPLATE.md) |
| 原论文、any-angle 与状态格的适用边界 | [LITERATURE.md](asar_repro/docs/eight_neighbor_physical/LITERATURE.md) |
| 固定配置 / 执行器 | [配置](asar_repro/configs/eight_neighbor_physical.json) · [执行器](asar_repro/scripts/run_eight_neighbor_physical.py) |
| 物理评分 / 搜索与独立 toy 枚举 | [physical_model.py](asar_repro/src/asar_repro/physical_model.py) · [physical_search.py](asar_repro/src/asar_repro/physical_search.py) |
| 交付状态与静态核验清单 | [delivery_manifest.json](asar_repro/docs/eight_neighbor_physical/delivery_manifest.json) |

## 本批固定矩阵

| 阶段 | 内容 | 任务数 | 算法预算 |
|---|---|---:|---:|
| P0 | 原始代码与输入保护、评分桥接、实际本地测试、冻结 | 不计性能任务 | 另计 |
| A | 六个 toy × 两种覆盖 × 四／八邻接 × 研究搜索／独立枚举 | 48 | 288 秒 |
| B5 | Lake / Hudson × 两种覆盖 × 四／八邻接 × 三次重复，各 5 秒 | 24 | 120 秒 |
| B30 | 同矩阵重新起步，各 30 秒 | 24 | 720 秒 |
| 合计 | 不包含 P0 与进程/I/O/审计开销 | **96** | **1128 秒（18 分 48 秒）** |

正交边长为 d，对角边长为 sqrt(2)d，两组保持 20 m/s 和原观测时刻。航段与探测时刻分开，允许在边内观测；末边在 H 截断仍要评满 H。固定飞行时长意味着两组实际航程均为 vH。保留原粒子身份、特殊箱质量、无等待、自由终点和原 J/Pd 公式。

主要覆盖 `heading_square` 随飞行方向转动；同预算 `axis_square` 保持世界轴方向，用于敏感性分析和旧四邻评分桥接。两者均是**未校准几何代理**。平方边长采用一个原网格宽度，不把 sweep width 当作已知实机视场。

四／八邻接共用新增的 paper-guided anytime 研究适配器，仅动作图不同。它不是原论文求解器逐位复现，没有继承旧 STDC 或 epsilon 证书。初始化使用相同的历史强四邻接路线并按新模型重放；原路线离线生成成本统一不计，复制、评分、内部预处理和候选重放均计时。

**正式比较是在新模型内部的四／八邻接之间进行。** 旧模型 J 的绝对值只做桥接核验；保持指标公式，不等于跨模型直接归因。B5 质量门槛与覆盖敏感性均通过，才标记待独立验证的筛选信号；B30 独立判断，不能改写 B5。Fundy、300 秒、any-angle、状态格与独立档案均未启用。

以下保留上一批的结果、研究入口和复现说明。

---

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

