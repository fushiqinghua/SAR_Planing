# A^SAR 论文复现

阶段 0–8 已完成。查看[最终复现报告](docs/final_reproduction_report.md)、[论文 Table I/II、Fig. 2–4 与保证范围对照](docs/paper_comparison.md)、[逐次实验汇总](outputs/metrics/summary.csv)和[各阶段测试记录](docs/reproduction_log.md)。

## 用指定解释器复跑

从工作区的 `baseline` 目录打开 PowerShell。以下命令使用已有的 maritime-sar 环境和本地源码。

```powershell
Set-Location .\asar_repro
$PY = 'C:\Users\35448\.conda\envs\maritime-sar\python.exe'
$env:PYTHONUSERBASE = Join-Path (Get-Location) '.python-user'
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
$env:PATH = (Join-Path (Split-Path $PY) 'Library\bin') + [IO.Path]::PathSeparator + $env:PATH
$env:PYTHONIOENCODING = 'utf-8'
& $PY -m pytest -q tests/test_heuristic_counterexample.py
& $PY -m asar_repro.cli plan --scenario lake_ontario --epsilon 1.10
& $PY -m asar_repro.cli report --results outputs/metrics
& $PY -m pytest -q
```

新 PowerShell 会话需重新设置上述变量。单场景计划从固化粒子读入，向标准输出写 JSON。批量重做原阶段 7 benchmark 可执行 `& $PY scripts/run_stage7.py`，再用 `& $PY scripts/report_stage7.py` 刷新四场景指标与图，最后执行上述 report 命令。指定 `--output-dir` 可将阶段 7 新实验保存在独立目录。阶段 8 报告入口直接读取已保存的标准工作区产物，重复执行保留原实验计时。[环境快照](outputs/logs/environment.json)

## 独立规划 adapter

在已将本项目 `src` 加入 Python 搜索路径的调用进程中，可直接导入以下函数。整个 `data/processed` 目录可复制到其他工作目录，以 manifest 的实际路径调用。

```python
from asar_repro.planner_adapter import plan_from_bundle

result = plan_from_bundle("data/processed/manifest.json", "lake_ontario", epsilon=1.10)
if result["path"] is not None:
    route = result["path"]              # CSP 起始的 T+1 个原始格号
    waypoints = result["waypoints"]    # 对应格心 lon、lat、UTC、row、col
    print(result["status"], result["incumbent_source"], result["J"], result["Pd_T"])
```

已有仿真也可用 `plan_particle_path(grid=..., start=..., cell_ids=..., trajectory_ids=..., initial_weights=..., time_utc=..., q=...)` 直接传数组。`grid` 为 `ParticleGrid(GridGraph(rows, cols), (lon, lat), cell_width_m)`，按行优先、北边第一行。时间是显式按 UTC 解释的严格递增 NumPy datetime64 数组，CST 占第 0 行；`cell_ids` 的形状为 (T+1, N)，列与唯一粒子 ID 和初始权重一一对应。特殊格依次为陆地、域外、失活、未知，紧随最后一个水域格。输入未探测总质量为 1。

两种入口都接受 `heuristic`、`epsilon`、`warm_start` 和三种搜索上限。默认开启动态 PT 初始上界。中止时保留 `stop_reason`；已有完整解时返回该路径，缺少完整解时 `path`、`waypoints`、J、Pd_T 和生存曲线均为 None。每条有效路径经统一评分器重放。返回的 `discrete_model_certified` 只涉及当前离散模型，`uav_constraints="unevaluated"` 表示宿主仍需检查动力学与返航。接口不导入宿主程序，离线规划无需启动 OpenDrift。[接口源码](src/asar_repro/planner_adapter.py) · [四场景离线回放记录](outputs/logs/stage8_adapter_replay.json)

`configs/schema.json` 定义阶段 0 的配置标识 `{"stage": 0}`。场景参数及其校验规则随对应阶段加入。

## 阶段 1 单独验收

在上述项目目录和解释器设置下运行下列命令，仅加载离散模型和测试用例。

```powershell
& $PY -m pytest -q tests/test_grid.py tests/test_belief.py tests/test_objective.py
```

手算例以中心格 4 为起点，东格 5、北格 1 的先验质量分别为 0.7、0.3。

```python
from asar_repro.grid import GridGraph
from asar_repro.motion import MatrixMotion
from asar_repro.objective import score_path

result = score_path(
    GridGraph(3, 3), [4, 5, 4, 1], start=4, budget=3,
    p=[0, 0.3, 0, 0, 0, 0.7, 0, 0, 0], q=1, motion=MatrixMotion.identity(9),
)
print(result.survival, result.J, result.pd_final)  # [1.  0.3 0.3 0. ], 0.6, 1.0
```

## 阶段 2 逐例对照

在项目根目录使用前述解释器和 `PYTHONUSERBASE` 设置。若直接指定 Conda 的 python.exe，下面的 PATH 设置使 Windows 绘图库优先使用该环境的原生 DLL，仅作用于当前 PowerShell 会话。

```powershell
$env:PATH = (Join-Path (Split-Path $PY) 'Library\bin') + [IO.Path]::PathSeparator + $env:PATH
& $PY -m pytest -q tests/test_oracle.py tests/test_search.py
& $PY -m pytest -q
& $PY scripts/validate_stage2.py
```

Python 入口为 `asar_repro.oracle.enumerate_oracle` 和 `asar_repro.search.search_zero`。两者接受相同的 `grid, start, budget, p, q, motion`。`search_zero(..., prune=False)` 为 reference，`prune=True` 启用上界剪枝。Oracle 支持至多 16 格和 8 步，返回数值最小的路径及容差内全部并列路径。验收脚本保存 [逐例指标](outputs/metrics/stage2_comparison.csv)、[实际输入与路径](outputs/metrics/stage2_comparison.json) 和 [队列峰值图](outputs/figures/stage2_peak_open.png)。

## 阶段 3 启发式核验

在项目根目录沿用上面的 `$PY`、`PYTHONUSERBASE` 和 `Library\bin` 设置，执行下列 PowerShell 命令。

```powershell
& $PY -m pytest -q tests/test_heuristic.py tests/test_heuristic_counterexample.py
& $PY -m pytest -q --ignore=tests/test_smoke.py
& $PY scripts/validate_stage3.py
```

`from asar_repro.search import search_asar` 后可调用 `search_asar(grid, start=..., budget=..., p=..., q=..., motion=..., heuristic="mass_lb", epsilon=1.02)`。默认启用上界剪枝。结果中的 `theory_certified` 指模型前提下的 ε 质量界；报告另列与本例 Oracle 的实际比较。仅作诊断时可传 `heuristic="paper_literal_abs_time"` 检查论文伪代码的绝对时间半径。

日常回归直接读取 [附录 B 固定数组](data/fixtures/heuristic_dynamic_counterexample.npz)；需要从生成过程重建该文件时运行 `& $PY scripts/generate_stage3_fixture.py`。逐例指标见 [CSV](outputs/metrics/stage3_search.csv)，根节点的数值对比见 [反例图](outputs/figures/stage3_counterexample.png)。

## 阶段 4 生成概率图与路径对比

两套 7×7 输入均为**按论文思想重建**。论文未公开 Fig. 2 的具体概率矩阵。使用项目根目录和前述 Windows 解释器设置运行：

```powershell
& $PY scripts/run_toy.py
& $PY -m pytest -q tests/test_toy.py
& $PY -m pytest -q --ignore=tests/test_smoke.py
```

脚本读取 [静态 YAML](configs/toy_static.yaml) 和 [动态 YAML](configs/toy_dynamic.yaml)。可用 `--output-dir <目录>` 指定新的复跑位置。

| 产物 | 阅读方式 |
| --- | --- |
| [静态热力图](outputs/figures/stage4_toy_static.png)、[动态热力图](outputs/figures/stage4_toy_dynamic.png) | 行为三种搜索方法，列为 0、1、5、15、30 步。M 为该帧剩余总质量，各帧与方法共享一个绝对色标。 |
| [路线比较](outputs/metrics/stage4_comparison.csv)、[逐步数据](outputs/metrics/stage4_steps.csv) | J 为第 1 至 30 步的 M 总和，Pd_T 为累计发现概率。逐步表含 t=0、顶点、行列、M_t、发现概率增量、Pd_t 和累计 J_t。 |
| [顺序实验图](outputs/figures/stage4_order.png)、[顺序实验逐步数据](outputs/metrics/stage4_order.csv) | 在相同起点和预算下交换两段闭合路径，只改变访问顺序。 |
| [配置、先验、路径和绘图矩阵](outputs/metrics/stage4_toy.json) | 包含 SHA-256 配置指纹、全部路径、三种方法各 5 帧的原始 7×7 未探测质量矩阵，以及 A^SAR 搜索计数。 |

## 阶段 5 从事故时刻预漂移至 CST

在 `asar_repro` 下沿用上述 PowerShell 环境设置。使用现有 maritime-sar 解释器直接执行：

```powershell
& $PY -m pytest -q tests/test_opendrift_adapter.py::test_guide_smoke_corrected_local_api
& $PY scripts/generate_drift.py --config configs/lake_ontario_constant.yaml
& $PY -m pytest -q
```

生成器支持 `--output-dir <目录>` 独立复跑。一次运行完成整个窗口的漂移。下游只需读取 [粒子 NPZ](outputs/particles/stage5_leeway.npz) 与 [配套元数据 JSON](outputs/metrics/stage5_drift.json)。另有 [逐步质量 CSV](outputs/metrics/stage5_mass.csv) 和 [粒子图](outputs/figures/stage5_particles.png)。

| NPZ 字段 | 含义 |
| --- | --- |
| trajectory_id | 每个粒子列对应的原始 ID。原生和重采样数据共享此列序。 |
| raw_time_utc、raw_lon、raw_lat、raw_status、raw_land_binary_mask、raw_cell_ids | 事故起的完整原始时间轴、原始观测及分格，数组为时间 × 粒子。原始状态和坐标保留缺测。 |
| time_utc、lon、lat、status、land_binary_mask、cell_ids | CST 起的 50 帧。两个时间数组均为语义明确为 UTC 的 datetime64[ns]；状态字典与特殊格 ID 见 JSON。 |
| initial_weights | CST 时每个 ID 的未探测质量。后续规划从该向量独立复制。 |
| audit_visited、audit_weights、audit_cell_mass | 固定审计路线的访问格、逐 ID 剩余质量、含特殊格的总质量。第 0 帧无探测，访问格以 −1 表示。 |
| config_hash | 所用 YAML 原始字节的 SHA-256，与配套 JSON 一致。 |

## 阶段 6 在固化轨迹上搜索

在项目根目录沿用前述解释器、PYTHONUSERBASE 和 Windows Library/bin 设置。先做小 N 交叉验证，再扫描阶段 5 归档。

```powershell
& $PY -m pytest -q tests/test_particle_search.py
& $PY scripts/benchmark_particles.py --config configs/stage6_particle_search.yaml
```

`ParticleMotion(cell_ids, grid.size, trajectory_ids)` 接受从 CST 开始的整数格编号，列为原始 ID，计算 T 步需要至少 T+1 帧。粒子模式下传给 `search_asar` 和 `score_path` 的 `p` 为归档的 `initial_weights`。搜索节点和评分器的信念数组按粒子列排列；用 `motion.cell_mass(weights, step)` 转成含特殊格的概率图。

| 输出 | 内容 |
| --- | --- |
| [逐 ε 对比 CSV](outputs/metrics/stage6_epsilon.csv) | 实测 J、Pd、节点计数、独立进程峰值工作集、超时标记、停止原因和可行解来源 |
| [路径与生存曲线 JSON](outputs/metrics/stage6_particles.json) | 配置、归档哈希、各 ε 的完整路径、M₀…M_T 和额外的 profile 运行 |
| [路径、粒子分布与生存曲线图](outputs/figures/stage6_particle_search.png) | 背景为 CST 单格粒子质量；实线表示搜索完成，虚线为预算中止时的可行路径 |
| [性能 profile](outputs/logs/stage6_profile.txt) | ε=1.10 的独立 cProfile 调用计数与累计时间 |

预算中止的记录须同时查看 `status`、`stop_reason` 和 `incumbent_source`。若已有完整可行解则返回其路径，否则路径和 J 均为空。本次扫描统一提供阶段 5 的审计路径作起始上界，8 个 ε 各自独立搜索。

## 阶段 7 四场景同数据对照

运行 `scripts/run_stage7.py` 按指南顺序预处理并比较四个场景，随后运行 `scripts/report_stage7.py` 核验归档指纹并独立重放每条路径。所有本地结果使用常量风流。完整参数、历史归档查阅记录、基线定义、计时口径和 PowerShell 命令见[阶段 7 说明](docs/stage7_scenarios.md)。

[统一指标](outputs/stage7/metrics.csv) · [逐步质量与路径](outputs/stage7/step_metrics.csv) · [复现偏差表](outputs/stage7/deviations.csv) · [相对成本图](outputs/stage7/relative_cost.png)
