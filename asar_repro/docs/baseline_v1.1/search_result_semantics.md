# B4 搜索结果字段与适用边界

B4 核验通过。搜索、评分、状态展开和四种启发式数学行为保持不变。新增 `search_reporting.py` 将实际搜索结果分类，并用 `score_path` 独立重放完整路线。`planner_adapter.py` 复用该接口，保留旧 `status`、路线、航点和逐步质量字段。

## 字段约定

| 字段 | 定义 |
|---|---|
| `algorithm` / `heuristic` | `ASAR_paper/paper_greedy`、`ASAR_mass_lb/mass_lb`、`ASAR_zero/zero`；字面绝对时间模式仍单独标记 |
| `search_status` / `stop_reason` | 搜索实际退出状态；展开、OPEN、时间限额分别为 `max_expansions/max_open/max_seconds` |
| `incumbent_source` | `ParallelTrack` 表示保留初始 PT；`search` 表示搜索生成的更优完整路线；无路线时为 null |
| `found_feasible_path` | 是否返回长度 T、起点及邻接合法且评分重放一致的完整路线 |
| `theoretical_bound_applicable` | 已验证内置模型契约且启发式为 zero/mass_lb；即使预算中止，也可为 true，但不表示已获证书 |
| `completed_for_certificate` | 同时满足上述适用条件、正常完成搜索、存在完整路线。paper_greedy 恒为 false |
| `discrete_model_certified` | 本接口采用与 completed_for_certificate 相同的保守判断；仅指模型内条件性 ε 界 |
| `search_completed` | 正常完成且有完整路线；与启发式是否有理论下界分别记录 |
| `result_class` | completed_search、aborted_feasible_incumbent、aborted_without_path |
| `J/Pd_T/M_T/path` | 无完整路线时均为 null；CSV 明确写 `null`。J 单位为离散步，t=0 不探测 |
| `planner_wall_s` | 仅 search_asar 调用，包含其内部初始路线评分 |
| `warm_start_s` | 构造动态 ParallelTrack 的时间；不使用初始路线时为 0 |
| `total_wall_s` | 上述二者之和，不含输入校验、运动对象构造、指纹、独立重放、Oracle 或作图 |
| `config_hash` | adapter 对实际输入数组、ID、时钟、几何、传感参数、方法及预算生成的稳定 SHA-256 |

所有规定字段列在模块 `REQUIRED_FIELDS`。单次运行还记录场景、forcing、来源清单/粒子指纹、seed、环境与 Git 信息。直接调用 adapter 而未提供 provenance 时，缺失的来源、seed、Git 为 null，forcing 为 unspecified；不能据此声称是历史真实环境。`plan_from_bundle` 从校验过的便携清单补齐场景、输入指纹和 forcing。调用方可通过 `plan_particle_path(provenance=...)` 提供已核验的来源，Git 提交必须由调用方如实记录。

B4 benchmark 的 `git_commit` 是运行时 HEAD；由于当时尚有待提交的新代码，`audit.json` 明确记录 `git_commit_scope`，并保存实际执行源码的 SHA-256。历史运行缺少逐次 Git/完整环境记录时保留未知；不以本轮环境补造旧记录。

## 理论、数值和环境的区分

mass_lb 使用原有公式 `M_d * sum((1-q_max)^k, k=1..T-d)`。适用前提是非负未探测质量守恒、每步只探测一个格、q 在 [0,1]、无虚假检测、不合并不同路径的 belief。适用模型为已验证的 MatrixMotion 和 ParticleMotion。特殊格的未探测质量继续保留。

理论推导针对该离散模型；实现使用 float64。测试以 `1e-10` 绝对容差核对 Oracle/重放，并不提供对所有浮点输入的形式化认证，也不是实海行动保证。paper_greedy 即使在某些样例取得最优值，仍只属于论文算法复现，不因此取得一般性的可采纳证明。

- 冻结的 3×3、T=4、q=.78 反例：根启发值约 2.6170801771，大于 Oracle 的 2.5417333379。
- 另一个动态例子在 ε=1 时，paper_greedy 返回 J=2.197771238744739，Oracle 为 2.185746589095029，差 0.01202464964970984。
- B4 已完成的 zero/mass_lb 在 ε=1 的 toy 上与 Oracle 的 J 差为 0；ε=1.1 的条件界也逐例通过。

这些是当前离散约定下的可重复事实，不能外推为“原论文在所有海洋场景都无效”。

## 退出分支核验

新增测试覆盖根入队、启发式前后时间检查、循环时间检查、展开限制、OPEN 限制、初始路线保留、搜索生成完整解后中止、终点弹出、根被剪枝后 OPEN 耗尽、T=0，以及不可达路径的异常。时间边界使用注入时钟，避免依赖机器快慢。不可达正预算仍按原 API 抛出 `ValueError`，不伪造已完成运行。

特别注意：`max_expansions=0` 或 `max_open=0` 不一定触发中止。根在入队之前若已被上界剪枝，OPEN 会正常耗尽；结果可以是 completed 且来源为 ParallelTrack。paper_greedy 即使正常耗尽也不认证。新增资源边界测试用无剪枝模式确保实际到达待测限额分支，另有独立测试保留根剪枝的真实行为。

## 旧报告及下一阶段

原 v1.0 报告和输入保持原样。B4 另存 32 条归一化历史记录，逐路线重放 J、Pd、M；J 误差为 0。其中 15 次正常完成、17 次 max_expansions 中止；后者均返回原 PT，不能计入完成数量或宣称 A^SAR 获得改进。统计按 forcing 类型与算法分组，图中把完成与中止分栏。

本地 `J_over_PT` 的分母是本地动态 PT，不是论文的最优参考值。原论文 C++ / M1 Pro 的时间与本机 Python / Windows 时间分列，不计算跨机器加速比。B4 没有新增真实环境规划成绩；B3 的历史轨迹仍冻结。后续真实环境结果应称“使用论文任务参数的真实历史环境重建”，作者原始模式循环、地图、粒子及人工 PT 仍未逐点复现。

完整数值与图片见 [B4 自动报告](../../outputs/baseline_v1.1/b4/report.md) 和 [审计 JSON](../../outputs/baseline_v1.1/b4/audit.json)。下一阶段 B5 才执行冻结输入的预算扫描与 profile。
