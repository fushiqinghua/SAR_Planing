# 八邻接后续实验：加速与同 forcing 预留实例（待本地执行）

分支：**eight-neighbor-physical-study-20261127**  
本批基点：上一批结果提交 **97dd989a488da8604b97fd287162e1b625310501**  
本批交付状态：**prepared_not_run；实现、配置、测试和协议已准备，仅静态检查。**

本批回答两个问题：**保持评分和搜索语义一致的缓存实现，能否把已有好路线更稳定地推进到 5 秒预算内；固定实现之后，八邻接的收益能否迁移到同一 forcing 范围内的新任务时段和新粒子 seed？**

## 当前入口

| 内容 | 文件 |
|---|---|
| 本地逐条命令、输入恢复、冻结、失败处理和回传 | [LOCAL_RUNBOOK.md](asar_repro/docs/eight_neighbor_followup/LOCAL_RUNBOOK.md) |
| 上一批结果及本批设计理由 | [REVIEW_R1.md](asar_repro/docs/eight_neighbor_followup/REVIEW_R1.md) |
| 固定矩阵与计算成本 | [PLAN.md](asar_repro/docs/eight_neighbor_followup/PLAN.md) |
| 后端采用、预留实例与停止门槛 | [DECISIONS.md](asar_repro/docs/eight_neighbor_followup/DECISIONS.md) |
| 结果分析模板 | [RESULTS_TEMPLATE.md](asar_repro/docs/eight_neighbor_followup/RESULTS_TEMPLATE.md) |
| 预注册配置与分阶段执行器 | [配置](asar_repro/configs/eight_neighbor_followup.json) · [执行器](asar_repro/scripts/run_eight_neighbor_followup.py) |
| 唯一缓存候选与新实例准备器 | [physical_accel.py](asar_repro/src/asar_repro/physical_accel.py) · [physical_followup_data.py](asar_repro/src/asar_repro/physical_followup_data.py) |
| 交付身份与静态核验 | [delivery_manifest.json](asar_repro/docs/eight_neighbor_followup/delivery_manifest.json) |

## 本批固定规模与执行顺序

| 阶段 | 内容 | 任务数 | 算法预算合计 |
|---|---|---:|---:|
| P0 | 8 个测试文件；8 项共同前缀严格数值审计 | 不计正式性能任务 | 另计 |
| D5 | 2 旧档案 × 2 覆盖 × 2 邻接 × 2 后端 × 3 次，各 5 秒 | 48 | 240 秒 |
| 锁定后端／准备 H1 | 先按 D5 选择，再生成四份固定时窗和 seed 的档案 | 漂移准备另计 | 另计 |
| S30 | 每份新档案生成一条共同初始路线，各 30 秒 | 4 | 120 秒 |
| 冻结 H1／H30 | 4 新实例 × 2 覆盖 × 2 邻接 × 3 次，各 30 秒，只用一个后端 | 48 | 1440 秒 |
| 正式合计 | 不含 P0、漂移、启动、输入与外部审计 | **100** | **1800 秒，30 分钟** |

沿用原 J、Pd、20 m/s 地速和共同观测时钟。两种方形覆盖仍是未标定的几何代理。四／八邻接和原／缓存后端严格同预算；完整路线重放及缓存建造计入算法时间。S30 生成成本另列，H30 计入同一初始路线的复制与重新评分。

D5 未达到加速采用条件而正确性通过时，H1 回退原后端继续。H1 固定为 Lake 的 ±1 小时时窗及 seed 1041/1042，Hudson 的 ±2 小时时窗及 seed 2041/2042；数据层级为 **same_forcing_shifted_window_new_seed**。这只能检验同 forcing 条件下的新实例迁移，不能写成独立天气或跨海区泛化。原始 forcing 不在 Git 中，必须恢复既有本地 B1 包；执行器不下载或替换数据。

主覆盖至少 2/4 新实例改善 ≥0.5%，四例均不退化，并通过预定 axis 敏感性门槛，才保留有限迁移信号。赢家只来自一个场景时单独标记。H2 新天气、300 秒、Fundy、任意角度与新 STDC 机制没有自动启用。

## 上一批已经执行的结果

上一批已上传：120 项测试通过，A48、B5 24、B30 24 项完整。Lake 在主覆盖下 J 改善约 2.97%；30 秒 axis 改善约 3.17%。Hudson 的主覆盖 30 秒改善约 0.335%，axis 没有改善。正式 B5 状态仍为 `sensor_sensitive`，B30 为 `longer_budget_signal_pending_followup`。新批次尚未运行，不能沿用这些通过数。

[上一批原始分析](asar_repro/outputs/eight_neighbor_physical_20261127/local_r1/ANALYSIS.md) · [结构化汇总](asar_repro/outputs/eight_neighbor_physical_20261127/local_r1/summary.json) · [本批对旧证据的解释](asar_repro/docs/eight_neighbor_followup/REVIEW_R1.md)

以下保留旧批次交付说明原文，其中“待执行”和 `not_run` 是各自最初交付状态；当前已上传结果以上述入口为准。

---

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

