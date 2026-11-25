# STDC 全局 anytime：最终验证报告

日期：2026-11-24（Asia/Shanghai）。分支：`stdc-research-v0.2`。本报告依据本目录已完成的测试、Oracle、真实归档实验和最终保全证据生成，不修改旧 baseline、窗口实验或本轮原始结果。

**本轮在单一冻结 Lake Ontario 归档上，实现了 J 低于最佳已测 baseline 的数值目标，但收益较小，Pd 未同步提高，计算成本明显增加。** 预设主权重 `w=1.04` 下，STDC anytime 返回 J=17.264874448，相对最佳 baseline 的 17.29389415456 降低 **0.167803%**；Pd 从 0.89737041888 变为 0.897364416，下降 `6.00288e-6`，即 **0.000600288 个百分点**。中位运行时间约为 baseline 的 **4.7395 倍**。

这证明当前固定输入和预算下存在小幅 J 改善，不证明普遍优势、双指标同时提升、同实际耗时优势或动态 ε 最优。三次重复使用同一粒子归档，不能当作三个独立场景。机器可读结论见 [final_outcome.json](final_outcome.json)。

## 本轮方法与模型假设

保留原始目标 `J = Σ M_t, t=1..T`，终点检测概率 `Pd = 1-M_T`，t=0 不检测。没有添加 Pd 阈值或改变 forcing、运动输入及统一评分器。

新增搜索使用一个 heap，按 `g + w*h_paper` 排序。动态 `paper_greedy` **只决定搜索顺序**，不用于剪枝、首解终止或认证。完整候选出现后按原评分器重放，只有 J 严格改善超过 `1e-10` 才更新 incumbent，并继续搜索。三个控制模式只在弹出状态的安全下界上不同：`zero / mass_lb / stdc_lb`；剪枝使用未加权的 `g+h_bound >= incumbent_J+1e-10`。

没有按 `(depth, vertex)` 或其他近似状态键合并状态；每个路径状态保留完整未探测信念。粒子 ID、绝对帧与特殊质量保持原模型语义。下界依赖固定、非负、质量守恒的运动，`q∈[0,1]`、当前四连通无等待图及未归一化的联合未探测质量。所有接受、最终返回及归档 incumbent 均独立重放。

找到第一条完整路径后继续搜索是本轮主要框架变化；它不是 MHA 实现。**所有返回路线 `theory_certified=false`**，包括正常完成的小图结果。本文的权重 w 不是动态 ε 认证；baseline 对照中相同数值仍对应旧实现的 epsilon 参数。有限 Oracle 一致性是本地数值事实，不替代一般数学证明。

## 顺序门槛与结果保全

|门槛|实际结果|证据|
|---|---|---|
|新增单测|63 passed，0 failure/error/skip|[new_tests/stage.json](new_tests/stage.json)|
|全量回归|494 passed = 历史 431 + 新增 63；0 failure/error/skip|[full_tests/stage.json](full_tests/stage.json)|
|历史 STDC 随机逐前缀审计|160 个合成案例、18024 个前缀、0 violation|[random_audit/audit/guard_summary.json](random_audit/audit/guard_summary.json)|
|新增全局搜索 Oracle|45 个案例、405 次搜索、12123 个前缀下界检查|[small_search/audit/summary.json](small_search/audit/summary.json)|
|真实归档 smoke|6/6 运行通过；1 正常、5 预算中止；0 认证|[smoke/summary.json](smoke/summary.json)|
|正式真实归档对照|36/36 运行通过；6 正常、30 次 `max_expansions` 中止；0 认证|[benchmark/summary.json](benchmark/summary.json)|
|最终文件保全|654 个 baseline 文件、2581 个研究保护文件、109 个 Python 源文件 SHA 一致|[final_preservation/stage.json](final_preservation/stage.json)|

新增 Oracle 包含 35 个未修改的历史动态矩阵案例、5 个静态矩阵派生案例、5 个合成粒子派生案例；每例运行 3 种下界 × 3 个排序权重。405 次搜索的最大 `|J-J_oracle|`、最终 J/Pd 重放误差、历史 incumbent 的 J/Pd 重放误差均为 **0**。新前缀审计的最大下界数值超越为 `6.66e-16`，历史审计为 `8.88e-16`，均小于 `1e-10` 容差。

随机 seeds 为 100–179；历史小图 seeds 为 15000–15034；静态/粒子派生案例使用 15000–15004。以上均明确标记 `synthetic_toy`，不与真实归档实验混淆。

[validation_summary.json](validation_summary.json) 为 `passed`、`not_run=[]`。预算中止与验证失败分别记录：前者返回合法完整 incumbent、来源与 stop_reason；后者必须标记 `blocked` 并停止后续阶段。旧 v1.1、B7、窗口实验文件及全部既有未跟踪文件均纳入本轮保护，未覆盖旧结果。

## 真实输入、预算和计时口径

使用 B3 冻结 Lake Ontario 归档：`historical_real_forcing_allwater`，N=500、17×17、T=49、q=0.78、seed=41。事故 UTC 为 `2025-08-26T14:45:00Z`，CST UTC 为 `2025-08-26T15:45:00Z`，对象为 `PIW-2`。这是**单场景真实历史 forcing 的 all-water 离散近似**，不能解释为原论文全部真实场景的完全复现。

- 粒子 SHA-256：`8b30a87e543f1b33c39e70e1d0054e1750ec046ba2e0b627dd311d9945749456`。
- 冻结协议 SHA-256：`bc18ddcb922231168aef34d8805bd3f7388a2b3ed9c27e9522368141fa469ff7`。
- 每个 worker 重新复核 forcing、粒子、元数据、UTC 与评分器 SHA，见 [input_gate.json](benchmark/input_gate.json)。本轮真实实验未运行 OpenDrift 重新生成轨迹，未改 forcing，未以合成粒子替换真实归档。

所有方法共同接收已有冻结 PT 路径；没有免费使用最佳 baseline 路径暖启动，也没有独立 seed 子预算。每次运行上限均为 **5000 次实际展开、20000 物理 OPEN、30 秒**。展开只计算实际生成后继的状态；被安全下界剪枝的弹出状态不计展开，但其计算纳入时间和下界计数。OPEN 上限触发会中止整次搜索，不静默丢弃分支后继续。

这是**相同预算上限比较，不是相同实际运行时间比较**。旧 baseline 首解后停止；anytime 继续花费剩余预算。计时覆盖本次搜索、启发式和内部重放；进程峰值内存还包括导入、输入预检等开销，不能当作纯节点内存。时间限制采用合作式检查，overshoot 单独记录。每次运行独立进程、单线程，原始命令、stdout/stderr、source SHA、incumbent 历史和重放证据均留存。

## 主权重 1.04：核心指标与贡献拆分

以下为每组 3 次重复的中位数；同一方法/权重的路径、J、Pd 在三次重复间一致。

|方法|J ↓|Pd ↑|展开数|时间 s|进程峰值 MiB|正常/预算中止|
|---|---:|---:|---:|---:|---:|---:|
|最佳 paper baseline|17.29389415456|0.89737041888|1222|0.914918|90.5234|3/0|
|anytime zero|17.26664536000|0.89667801600|5000|2.715498|129.3477|0/3|
|anytime mass|17.26664536000|0.89667801600|5000|2.734225|129.1445|0/3|
|anytime STDC|17.26487444800|0.89736441600|5000|4.336257|145.9492|0/3|

相对最佳 baseline，STDC 的 J 绝对降低 `0.02901970656`，约 **0.167803%**；Pd 有极小下降。实际展开数 1222→5000，时间 0.914918→4.336257 秒，峰值内存 90.5234→145.9492 MiB，约 **1.6123 倍**。因此“J 略好”与“计算代价更高”必须同时报告。

zero/mass 已把 J 降到 17.26664536，说明**大部分改善来自首解后继续搜索的框架**。STDC 相对 zero/mass 额外降低 J=`0.001770912`，约 **0.010256%**，同时 Pd 增加 `0.0006864`，即 **0.06864 个百分点**；其下界开销使实际运行更慢。不能把全部 `0.167803%` 收益归因于 STDC，也不能把本轮数值改善直接等同于充分的创新性或普遍优势。

## 其他权重与 J/Pd 权衡

`w=1.1` 时，STDC 返回 `(J, Pd)=(17.31900178048, 0.90006723456)`，J 仍高于最佳 baseline 的 17.29389415456；Pd 则高于所有 baseline 设置中的最大值 0.89776904256。zero/mass 在同权重下返回 `(17.33585102848, 0.9038273712)`，Pd 甚至更高，但 J 更差。这些是不同完整路径的不同取舍，不能把其中最低 J 与最高 Pd 拼接为一条不存在的结果。

`w=1.0` 时，四个方法均返回冻结 PT：J=20.477608336、Pd=0.88106304，均耗尽 5000 次展开，没有质量改善。STDC 反而花费更多时间。全部 anytime 正式运行均为预算中止，未完成全局搜索。

所有 12 个方法/权重组合、运行范围、逐运行状态见 [aggregate.csv](benchmark/aggregate.csv)、[metrics.csv](benchmark/metrics.csv)、[results.json](benchmark/results.json)。配对差值见 [paired_comparisons.csv](benchmark/paired_comparisons.csv)。图形见 [质量与剩余质量曲线](benchmark/quality_and_survival.png)、[路径图](benchmark/paths.png)、[效率图](benchmark/efficiency.png)。

## 归档候选的事后观察

主权重 STDC 的 incumbent 历史中，展开数 1510 时存在候选 `J=17.29356023968, Pd=0.89740619904`，其 J/Pd 同时优于**最佳 J baseline 那条路径**。这可从 [原始 incumbent 历史](benchmark/anytime_stdc_w1.04_rep0/raw_result.json) 核对。

该路径是**事后观察到的归档候选，不是本轮最终返回路径，也不是新选择规则**。当前算法只最小化 J，因此继续搜索并返回更低 J、Pd 略低的路线。若后续希望保留或选择双指标更优候选，应事先规定新输出/选择协议并另行验证，不能用事后挑选替换本轮正式主结果。

事后分析已实际执行并通过：201 条带运行归属的候选记录，26 条唯一归档/参考路径全部独立重放，109 个源码指纹不变。在预设 `STDC/w=1.04/repeat=0` 这一次运行中，上述同时改善最佳 J baseline 的归档候选有 1 条；若把 Pd 门槛换成 baseline 各设置中的最大 Pd，则合格候选为 **0**。zero/mass 的同权重运行也存在对应的双指标改善候选，因此这一事后观察本身并非 STDC 独有收益。

证据见 [事后分析摘要](incumbent_analysis/summary.json)、[取舍说明](incumbent_analysis/tradeoffs.md)、[候选 JSON](incumbent_analysis/candidate_tradeoffs.json)、[候选 CSV](incumbent_analysis/candidate_tradeoffs.csv) 和 [J/Pd 取舍图](incumbent_analysis/pareto_tradeoffs.png)。图中只展示已接受、已归档的候选，不是全问题的 Pareto 前沿；分析未更改方法、目标、默认返回或原始结果。

## 新增文件与环境

本轮新增 6 个代码/测试/说明文件，原搜索、统一评价器、运动输入及之前的窗口实现保持不变：

|文件|用途|
|---|---|
|[anytime_search.py](../../../src/asar_repro/anytime_search.py)|排序与安全剪枝分离、持续搜索、完整 incumbent 与预算语义|
|[test_anytime_search.py](../../../tests/test_anytime_search.py)|63 项新增回归、手算、预算与 Oracle 测试|
|[audit_anytime_search.py](../../../scripts/audit_anytime_search.py)|45 案例、405 搜索和全部前缀的独立 DFS 对照|
|[run_anytime_validation.py](../../../scripts/run_anytime_validation.py)|顺序门槛、源代码冻结及旧文件保全|
|[run_anytime_experiments.py](../../../scripts/run_anytime_experiments.py)|真实 SHA 门槛、6 次 smoke、36 次正式实验及结果图表|
|[stdc_anytime_improvement.md](../../../docs/stdc_anytime_improvement.md)|预设方法、预算、比较目标和结论边界|

解释器为 `C:\Users\35448\.conda\envs\maritime-sar\python.exe`；Python 3.11.18，NumPy 2.4.6，SciPy 1.17.1，pytest 9.2.0，OpenDrift 1.14.12，psutil 7.2.2，Matplotlib 3.11.2，netCDF4 1.7.5，pyproj 3.7.2。未重装/升级 OpenDrift。版本、指纹和 diff 见 [preflight.json](preflight.json)、[source_sha256.json](source_sha256.json)、[untracked_files.diff](untracked_files.diff)；旧数据/输出使用逐文件 SHA 保全，避免反复展开二进制 diff。

## 离线完整复跑命令

前提是现有研究分支、冻结 baseline checkout、真实 forcing/粒子归档与环境仍在本机。使用新的输出目录，不覆盖本次结果；冻结后不得编辑源代码或切换分支。以下 PowerShell 命令开启现有 socket 离线保护，配置 Conda DLL 搜索路径，并为 Git 设置当前进程有效的安全目录例外，不修改全局 Git 配置。

```powershell
$repo = 'E:\毕业设计\终稿研发\new\baseline\SAR_Planing-stdc-v0.2'
$project = Join-Path $repo 'asar_repro'
$envPrefix = 'C:\Users\35448\.conda\envs\maritime-sar'
$python = Join-Path $envPrefix 'python.exe'
Set-Location -LiteralPath $project
$run = 'outputs/stdc_v0_2/anytime_replay_' + (Get-Date -Format 'yyyyMMdd_HHmmss')
if (Test-Path -LiteralPath $run) { throw '输出目录必须是新目录' }
$env:PATH = "$envPrefix\Library\bin;$envPrefix\Scripts;$envPrefix;$env:PATH"
$env:PYTHONPATH = "$project\scripts\offline_guard;$project\src;$project\scripts"
$env:ASAR_OFFLINE = '1'
$env:PROJ_NETWORK = 'OFF'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONHASHSEED = '0'
$env:OMP_NUM_THREADS = '1'
$env:OPENBLAS_NUM_THREADS = '1'
$env:MKL_NUM_THREADS = '1'
$env:VECLIB_MAXIMUM_THREADS = '1'
$env:NUMEXPR_NUM_THREADS = '1'
$env:GIT_CONFIG_COUNT = '2'
$env:GIT_CONFIG_KEY_0 = 'safe.directory'
$env:GIT_CONFIG_VALUE_0 = $repo.Replace('\', '/')
$env:GIT_CONFIG_KEY_1 = 'safe.directory'
$env:GIT_CONFIG_VALUE_1 = 'E:/毕业设计/终稿研发/new/baseline/SAR_Planing-v1.1'

function Invoke-CheckedPython {
    param([string[]]$Arguments)
    & $python @Arguments
    if ($LASTEXITCODE -ne 0) { throw "blocked: Python exit code $LASTEXITCODE" }
}

foreach ($stage in @('init', 'new_tests', 'full_tests', 'random_audit', 'small_search')) {
    Invoke-CheckedPython -Arguments @('scripts/run_anytime_validation.py', $stage, '--run-dir', $run)
}
Invoke-CheckedPython -Arguments @('scripts/run_anytime_experiments.py', 'smoke', '--output-dir', "$run/smoke", '--validation-evidence', "$run/validation_summary.json")
Invoke-CheckedPython -Arguments @('scripts/run_anytime_experiments.py', 'benchmark', '--output-dir', "$run/benchmark", '--smoke-dir', "$run/smoke")
Copy-Item -LiteralPath 'outputs/stdc_v0_2/anytime_20261124/analyze_incumbents.py' -Destination "$run/analyze_incumbents.py"
Invoke-CheckedPython -Arguments @("$run/analyze_incumbents.py")
Invoke-CheckedPython -Arguments @('scripts/run_anytime_validation.py', 'final_preservation', '--run-dir', $run)
```

新增单测底层命令为 `python -m pytest -x -q -p no:cacheprovider tests/test_anytime_search.py`；全量为 `python -m pytest -x -q -p no:cacheprovider tests`。执行器附加隔离 ASCII `--basetemp`、JUnit 文件及单阶段 1200 秒 watchdog。每阶段保存完整实际命令、seed、stdout/stderr、JSON、测试总数、耗时、SHA 和 diff。真实输入校验或任何强制门槛失败都应保留 `blocked`，不得绕过或替换输入。

最后执行 `final_preservation`。成功时另存证据，不改写已被真实实验按 SHA 固定的验证摘要；失败则将本次状态置为 `blocked`。本报告与事后分析均为结果衍生文件，不改写冻结实验。

## 已知局限与下一步未实现范围

已达到的范围是一个固定真实归档、预设权重和给定上限下的小幅 J 改善；没有跨事故、forcing、粒子 seeds 或多个独立归档的泛化证据。三次重复主要反映时间波动，不能支持独立样本统计显著性结论。所有正式 anytime 运行均未穷尽搜索，动态 paper 启发式仍不可认证；Pd 与 J 存在实际取舍。

后续应优先做**相同实际墙钟预算**下的质量曲线比较，并在多个独立冻结归档上预设协议复验；同时明确分离 anytime 框架收益与 STDC 下界的增量收益。尚未实施新的多目标选择规则、MHA、多场景扩展或创新点二；本轮没有修改原有海上搜救程序、目标函数或 forcing。
