# STDC 固定时刻窗口改进：最终验证报告

完成日期：2026-11-24（Asia/Shanghai）。实验开始于 11 月 23 日，沿用目录名 `windows_20261123`。研究分支：`stdc-research-v0.2`。

**本轮验证通过，在 ε=1 的受限预算对照中获得了 J/Pd 改善；尚未证明新方法优于本次已测试的最佳 baseline。** endpoint STDC 在 ε=1 时把 J 从 20.477608336 降至 18.331441506，下降 **10.4806%**；Pd 从 0.881063040 升至 0.890512659，提高 **0.944962 个百分点**。ε=1.1、1.04 时 J/Pd 均未改善，且增加了计算时间。baseline 在 ε=1.04 已得到更低的 J=17.29389415456，仍是本轮所有方法/参数中的最佳 J。

本报告汇总已保存证据，不改写 [benchmark 原始报告](benchmark/report.md)、旧 Stage 7、B7 或早期 STDC 结果。

## 本轮实现与数学边界

目标保持 `J = Σ M_t, t=1..T`，终点检测概率为 `Pd = 1-M_T`；t=0 不检测。只以完整路径 J 改善超过 `1e-10` 接受候选，不附加 Pd 约束。J 改善不必然使 Pd 上升。

在窗口 `[a,b]` 内重写路径，保持绝对时刻、起点/终点及窗口外路径固定。完整后缀采用精确线性系数评分：`J_full = g_a + J_window + c_bᵀ b'_b`、`Pd_full = 1-s_bᵀ b'_b`。接受和返回的完整路径均由原统一评分器独立重放；相同 `(depth, vertex)` 不合并信念状态。

四个局部模式为 `zero / mass_lb / stdc_lb / stdc_endpoint_lb`。endpoint 模式将每步可达集与“剩余步数恰能到达固定终点”的集合相交，再构造多点同时检测的松弛下界。局部假设包括固定、非负、质量守恒的运动输入，合法固定探测概率以及当前离散四连通图。

**所有完整路线均 `theory_certified=false`。** 动态 `paper_greedy` 仍不可无条件认证；窗口穷尽或整轮无改善只说明所检验局部邻域内的状态，不能推出全路线最优或 ε 界。Oracle 结果是有限 toy 的数值证据，不能替代一般数学证明。

## 顺序验证结果

|门槛|实际结果|证据|
|---|---|---|
|新增单测|75 passed，0 failure/error/skip|[new_tests/stage.json](new_tests/stage.json)|
|全量回归|431 passed，含历史 356 项；0 failure/error/skip|[full_tests/stage.json](full_tests/stage.json)|
|随机逐前缀 Oracle|160 个合成 matrix/particle 案例；6760 个前缀，其中 3618 可行、3142 不可行|[random_audit/audit/summary.json](random_audit/audit/summary.json)|
|小图完整搜索 Oracle|35 个历史动态案例 + 5 个静态矩阵 + 5 个合成粒子派生案例；45 案例、360 次搜索|[small_search/audit/summary.json](small_search/audit/summary.json)|
|真实归档 smoke|6/6 运行通过；4 次正常完成、2 次预算中止；0 条认证路线|[smoke/summary.json](smoke/summary.json)|
|真实归档正式对照|45/45 运行通过；18 次正常完成、27 次 `max_expansions` 中止；0 条认证路线|[benchmark/summary.json](benchmark/summary.json)|
|最终文件保全|654 个 baseline 文件、1864 个研究保护文件、104 个 Python 源文件 SHA 一致|[final_preservation/stage.json](final_preservation/stage.json)|

随机 Oracle 的最大下界数值超越为 `8.88e-16`，最大后缀 J 误差为 `1.78e-15`，均小于 `1e-10` 容差；endpoint 下界未弱于对应 plain STDC。小图 360 次搜索的最大 `|J-J_oracle|`、J 重放误差、Pd 重放误差均为 **0**。随机 seeds 为 100–179，历史小图 seeds 为 15000–15034，派生案例为 15000–15004。

[validation_summary.json](validation_summary.json) 状态为 `passed`、`not_run=[]`。预算中止是已记录的算法状态，不等同于测试门槛失败；每条运行均保留合法完整 incumbent、来源和 stop_reason。测试、下界、重放或保全门槛一旦失败，执行器会标为 `blocked` 并停止后续阶段。

## 真实输入与公平预算

使用冻结 B3 Lake Ontario 历史粒子归档，标签 `historical_real_forcing_allwater`：17×17 网格、N=500、T=49、q=0.78、粒子 seed=41、对象 `PIW-2`。事故 UTC 为 `2025-08-26T14:45:00Z`，CST UTC 为 `2025-08-26T15:45:00Z`。仍保留冻结的 all-water 离散近似；没有将 synthetic toy 冒充真实输入。

- 粒子 SHA-256：`8b30a87e543f1b33c39e70e1d0054e1750ec046ba2e0b627dd311d9945749456`。
- 冻结协议 SHA-256：`bc18ddcb922231168aef34d8805bd3f7388a2b3ed9c27e9522368141fa469ff7`。
- 每个 worker 在运行前复核真实 forcing、粒子、元数据、UTC 和评价器指纹，见 [input_gate.json](benchmark/input_gate.json)。真实实验直接消费归档，未重跑 OpenDrift 生成粒子，也未重装或升级 OpenDrift。

所有方法总上限相同：**5000 次展开、20000 物理 OPEN、30 秒**。直接 baseline 使用全部预算；四个窗口方法预先统一分配最多 1500 次展开给 paper seed，再用剩余共享预算扫描长度 4、6 的窗口，起始位置递增，直到完整一轮无改善或总预算中止。seed 子配额耗尽可以继续局部阶段；全局时间/OPEN 上限触发则停止。计数逐阶段核对，OPEN 取串行阶段的物理队列峰值。

冻结 PT 是各方法共同的已有输入，本实验不重建或计时其历史构造。预算包含本次 paper seed 搜索、内部评分、后缀系数构造和窗口搜索；外部独立重放、SHA 预检及进程启动单列。时间限制采用合作式检查，实际耗时和 overshoot 均保留。

因此，这是一份**总预算相同、内部预算分配不同的新研究协议**，没有把它伪装成旧 B7 协议的原样复跑。相对 baseline 的改进包含“完整候选初始化 + 局部窗口优化 + 子预算分配”的共同作用；四个窗口控制组之间的差异更直接反映局部下界设计的贡献。

## 核心指标与收益归因

以下为每组 3 次重复的中位数。三次重复复用同一归档、粒子和场景，只衡量运行时间变化，**不是三个独立场景或独立统计样本**。同一方法/ε 的 J、Pd 和路径在三次重复间相同。

|ε|方法|J ↓|Pd ↑|展开数|时间 s|进程峰值 MiB|正常/预算中止|
|---:|---|---:|---:|---:|---:|---:|---:|
|1.0|paper baseline|20.477608336|0.881063040|5000|4.8110|156.00|0/3|
|1.0|window zero|18.839498274|0.880293502|5000|1.7523|94.24|0/3|
|1.0|window mass_lb|18.839498274|0.880293502|5000|1.7195|94.15|0/3|
|1.0|window plain STDC|18.742343122|0.880847086|5000|1.9056|94.22|0/3|
|1.0|window endpoint STDC|18.331441506|0.890512659|4952|2.5176|94.16|3/0|
|1.04|paper baseline|17.293894155|0.897370419|1222|0.9488|89.50|3/0|
|1.04|window endpoint STDC|17.293894155|0.897370419|2136|1.2265|89.84|3/0|
|1.1|paper baseline|17.359684022|0.897769043|107|0.1384|70.39|3/0|
|1.1|window endpoint STDC|17.359684022|0.897769043|920|0.3944|70.66|3/0|

进程峰值包含导入、预检、算法与重放，不是只计搜索状态的内存。全部 15 组及范围见 [aggregate.csv](benchmark/aggregate.csv)，45 条逐运行结果见 [metrics.csv](benchmark/metrics.csv) 和 [results.json](benchmark/results.json)。

ε=1 时，endpoint 相对同调度、同 seed 子配额的 window zero，J 再下降 **2.6968%**，Pd 增加 **1.021916 个百分点**，但中位运行时间为其 **1.4367 倍**。这说明本次 endpoint 下界在有限展开预算内能找到更好的完整路径，同时存在下界计算开销。zero/mass 也获得明显 J 改善，且其 Pd 略低于 baseline，因此不能把全部窗口收益归因于 STDC，也不能把 J/Pd 当作同一个优化目标。

ε=1.04 与 1.1 时，四个窗口模式均未改善 seed 的 J/Pd。ε=1.1 时，endpoint 相对 plain STDC 将总展开从 4437 降至 920（局部阶段 4330→813），但仍比直接 baseline 更慢，也没有 J/Pd 增益。endpoint 只是在较少局部展开后确认本窗口调度没有进一步改善，不能据此声称整体质量提升。尤其是最佳已测 baseline `ε=1.04, J=17.29389415456` 仍优于 endpoint 在 ε=1 下的 18.33144150592；本轮支持的是**部分受限预算设置下的改进**，不支持“已经全面超过 baseline”的结论。

图形证据：[全部 ε 核心指标](additional_figures/core_metrics_all_epsilons.png)、[ε=1 路径图](additional_figures/paths_eps1.png)、[ε=1 剩余质量曲线](additional_figures/survival_eps1.png)，以及自动报告的 [路径图](benchmark/paths.png)、[剩余质量曲线](benchmark/survival.png)、[效率图](benchmark/efficiency.png)。附加图只读取已完成的结果，由本输出目录中的 `plot_all_epsilons.py` 生成，不改动算法或冻结输入。逐 ε/重复的对照差值见 [paired_comparisons.csv](benchmark/paired_comparisons.csv)。

## 新增文件清单与环境

代码与说明共新增 9 个文件，未改动已有源码、评价器、运动输入或旧结果：

|文件|用途|
|---|---|
|[window_bounds.py](../../../src/asar_repro/window_bounds.py)|精确后缀系数、四种窗口下界、端点可达性|
|[window_search.py](../../../src/asar_repro/window_search.py)|共享预算、完整 incumbent、局部扫描与严格 J 接受|
|[test_window_bounds.py](../../../tests/test_window_bounds.py)|手算、索引、特殊质量、后缀及可采纳性测试|
|[test_window_search.py](../../../tests/test_window_search.py)|窗口 Oracle、重放、预算及 incumbent 回归|
|[audit_window_bounds.py](../../../scripts/audit_window_bounds.py)|160 案例逐前缀独立 Oracle|
|[audit_window_search.py](../../../scripts/audit_window_search.py)|45 案例、360 次完整搜索对照|
|[run_window_validation.py](../../../scripts/run_window_validation.py)|顺序门槛、环境记录和冻结文件保全|
|[run_window_experiments.py](../../../scripts/run_window_experiments.py)|真实输入 SHA 门槛、独立进程、smoke/benchmark 与图表|
|[stdc_window_improvement.md](../../../docs/stdc_window_improvement.md)|数学假设、新协议与解释边界|

实际解释器为 `C:\Users\35448\.conda\envs\maritime-sar\python.exe`；Python 3.11.18，NumPy 2.4.6，SciPy 1.17.1，pytest 9.2.0，OpenDrift 1.14.12，psutil 7.2.2，Matplotlib 3.11.2，netCDF4 1.7.5，pyproj 3.7.2。版本从包元数据读取。环境和保护清单见 [preflight.json](preflight.json)，完整新增文件 diff 见 [untracked_files.diff](untracked_files.diff)，源码指纹见 [source_sha256.json](source_sha256.json)。

## 离线复跑命令

以下 PowerShell 命令使用现有解释器、现有冻结 baseline checkout 与本地真实归档，不安装依赖。使用新输出目录；任何一步非零退出即停止。冻结后不得编辑源码或切换分支；真实输入缺失/指纹不符时应保留 `blocked`，不得替换合成输入。

```powershell
$project = 'E:\毕业设计\终稿研发\new\baseline\SAR_Planing-stdc-v0.2\asar_repro'
$python = 'C:\Users\35448\.conda\envs\maritime-sar\python.exe'
Set-Location -LiteralPath $project
$run = 'outputs/stdc_v0_2/windows_replay_' + (Get-Date -Format 'yyyyMMdd_HHmmss')
if (Test-Path -LiteralPath $run) { throw '输出目录必须是新目录' }
$env:PYTHONPATH = "$project\scripts\offline_guard;$project\src;$project\scripts"
$env:PATH = (Join-Path (Split-Path $python) 'Library\bin') + [IO.Path]::PathSeparator + $env:PATH
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:ASAR_OFFLINE = '1'
$env:PROJ_NETWORK = 'OFF'
$env:PYTHONHASHSEED = '0'
$env:OMP_NUM_THREADS = '1'
$env:OPENBLAS_NUM_THREADS = '1'
$env:MKL_NUM_THREADS = '1'
$env:VECLIB_MAXIMUM_THREADS = '1'
$env:NUMEXPR_NUM_THREADS = '1'
$env:GIT_CONFIG_COUNT = '2'
$env:GIT_CONFIG_KEY_0 = 'safe.directory'
$env:GIT_CONFIG_VALUE_0 = 'E:/毕业设计/终稿研发/new/baseline/SAR_Planing-stdc-v0.2'
$env:GIT_CONFIG_KEY_1 = 'safe.directory'
$env:GIT_CONFIG_VALUE_1 = 'E:/毕业设计/终稿研发/new/baseline/SAR_Planing-v1.1'

function Invoke-CheckedPython {
    param([string[]]$Arguments)
    & $python @Arguments
    if ($LASTEXITCODE -ne 0) { throw "blocked: Python exit code $LASTEXITCODE" }
}

foreach ($stage in @('init', 'new_tests', 'full_tests', 'random_audit', 'small_search')) {
    Invoke-CheckedPython -Arguments @('scripts/run_window_validation.py', $stage, '--run-dir', $run)
}
Invoke-CheckedPython -Arguments @('scripts/run_window_experiments.py', 'smoke', '--output-dir', "$run/smoke", '--validation-evidence', "$run/validation_summary.json")
Invoke-CheckedPython -Arguments @('scripts/run_window_experiments.py', 'benchmark', '--output-dir', "$run/benchmark", '--smoke-dir', "$run/smoke")
Invoke-CheckedPython -Arguments @('scripts/run_window_validation.py', 'final_preservation', '--run-dir', $run)
```

新增单测底层命令为 `python -m pytest -x -q -p no:cacheprovider tests/test_window_bounds.py tests/test_window_search.py`；全量为 `python -m pytest -x -q -p no:cacheprovider tests`。执行器另外传入隔离 ASCII `--basetemp` 和 `--junitxml`，完整实际命令、seed、stdout/stderr、测试数和 git diff 均在对应阶段目录中。

`final_preservation` 必须最后执行。它成功时保存独立保全证据，不改写已被真实实验按 SHA 固定的 `validation_summary.json`；失败则将本次验证置为 `blocked`。

## 已知局限与尚未实现范围

目前只有一个冻结 Lake Ontario 场景和一份 500 粒子归档，不能外推其他事故、风流或粒子 seeds；小图 Oracle 为合成输入，与真实输入证据严格分开。全路线动态 paper 启发式及复合窗口方法均未认证；30 秒是合作式上限；短窗口固定终点/时刻可能困在无法跨越的局部最优。

全局 anytime / 多启发式 A*（MHA）、更长程的非局部重写、多场景独立验证尚未实施。本轮未开展创新点二，未改变目标函数、forcing、原有海上搜救程序或 baseline 分支。后续比较仍应保留最佳已测 baseline 参数作为主要参照，同时保持局部下界消融、共享预算、独立全路径重放和真实输入 SHA 门槛。
