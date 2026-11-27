# 本地执行说明：四／八邻接物理模型研究

## 交付状态与问题范围

分支：`eight-neighbor-physical-study-20261127`  
基点：`3399015cdf2e20dabe5895e30e3ae812bb68b049`（已上传上一批本地结果）  
本次交付：**实现、协议与测试已编写；仅静态检查。依赖安装、pytest、输入重放、枚举和实验均未执行。**

本批的问题是：**给定同一条历史强路线，在相同地速、任务时长、观测时钟与传感器假设下，开放对角运动能否带来可复现的 J 改善？** 这不是同一四邻接问题上替换算法的实验，也不是实机相机或转弯动力学的验证。

先读 [PLAN.md](PLAN.md)、[MODEL.md](MODEL.md) 和 [DECISIONS.md](DECISIONS.md)。无等待、自由终点、无新增返航约束；相机覆盖是未校准的方形代理。旧 STDC 和上一批 ILS/CEM 结果仍是各自原模型中的证据。

## 1. 切到新分支，检查环境

以下 Git 命令在现有仓库根目录运行。先正常保存或提交你自己的未提交修改，避免切分支时覆盖本地工作。

```bash
git fetch origin
git switch --track origin/eight-neighbor-physical-study-20261127
cd asar_repro
```

如果本地已创建这个分支，改用 `git switch eight-neighbor-physical-study-20261127`。本批需要正常 Git checkout，不能只下载 ZIP；P0 会使用 Git 对照基点原始源码。

建议沿用上一批的 `maritime-sar` 环境与 Python 3.11+（与仓库 pyproject 要求一致），使机器及软件版本尽量一致。所需依赖见 [requirements-physical-study.txt](../../requirements-physical-study.txt)。已满足依赖的环境无需重装；缺少时在本地执行：

```bash
python -m pip install -r requirements-physical-study.txt
```

程序会记录 Python、NumPy、SciPy、pyproj、pytest、psutil、机器及线程配置。五种常见数值线程变量固定为 1。冻结后不要更换环境、编辑代码或文档、修改配置。确需修改时保留已有目录，在新版本和新结果目录重新验证及冻结，不要混合记录。

## 2. P0：预检、实际测试、冻结

以下命令在 `asar_repro` 目录运行，Windows PowerShell、Linux/macOS 均可逐条使用，不需要 Bash 变量或反斜杠续行。默认结果目录为本批的新子目录：

`outputs/eight_neighbor_physical_20261127/local_r1`

```bash
python scripts/run_eight_neighbor_physical.py plan
python scripts/run_eight_neighbor_physical.py preflight --out outputs/eight_neighbor_physical_20261127/local_r1
python scripts/run_eight_neighbor_physical.py validate --out outputs/eight_neighbor_physical_20261127/local_r1
python scripts/run_eight_neighbor_physical.py freeze --out outputs/eight_neighbor_physical_20261127/local_r1
```

- `plan` 只列任务与预算，不导入物理求解模块，不做搜索。
- `preflight` 才会在你的本地读取现有归档、检查原输入哈希、重投影粒子、复算历史路线。它不重新生成漂移轨迹，也不下载 forcing。
- `validate` 会实际运行配置列出的五个测试文件，保存 stdout、stderr、JUnit 和验证记录。仅没有失败、错误、跳过、且测试数非零时通过；交付时的静态 AST 解析不满足这个门槛。
- `freeze` 要求同一源码和环境已有真实通过的本地测试，然后保存协议、源文件哈希、归档哈希、完整 toy 定义和三阶段任务顺序。它会复算输入桥接，不启动正式实验。

P0 的关键桥接：两条历史四邻接路线（PT 和 reference）在 `axis_square` 下应复现旧 J 与 Pd，绝对误差不得超过 `1e-8`。每个 searchable 粒子重投影后的格号也必须与原归档相同。主模型 `heading_square` 会独立记录同一路线的分数；旋转半开边界规则可能产生差别，不强行改分数让它与旧结果相等。

**P0 失败就停止。** 不删除粒子、不归一化特殊箱质量、不放宽容差、不更改时钟来“通过”。将验证目录及错误记录推回，我们先定位原因。

## 3. A：六个小图的独立核验

```bash
python scripts/run_eight_neighbor_physical.py run --stage A --out outputs/eight_neighbor_physical_20261127/local_r1
```

六个固定 toy × 两种覆盖 × 两种邻接 × 两种方法，共 48 项：研究搜索每项 2 秒，独立标量 DFS 枚举每项 10 秒。算法预算合计 288 秒。

本阶段检查：独立枚举必须完整闭合，并在预算内完成主评分器交叉重放；搜索不得优于枚举最优值，也不得丢失共同初始解；同一个模型应满足八邻接最优值不高于四邻接；`diagonal_intercept` 至少一种覆盖须出现严格对角收益见证。

2 秒研究搜索不必找到 toy 的最优解。toy 闭合是有限实例上的浮点数值证据，不构成真实场景全局最优证书。读取 `summary.json` 中的 `diagnostic_gate.passed`。**A 未通过时，B5/B30 会被执行器阻止。**

## 4. B5：同预算主筛选

```bash
python scripts/run_eight_neighbor_physical.py run --stage B5 --out outputs/eight_neighbor_physical_20261127/local_r1
```

Lake / Hudson × 两种覆盖 × 两种邻接 × 三次重复 = 24 项，每项 5 秒，算法预算 120 秒。

每种覆盖下，四／八邻接均从同一条历史强四邻接路线起步，按当前覆盖重新评分。该历史路线的离线生成成本统一不计；复制、物理重放、搜索内部预处理和新候选重放均计入本次算法预算。因此本批衡量“已有可行强路线后的改进”，不能用结果宣称从零开始的速度优势。

J 越低越好；Pd 使用同一次运行的同一路线单列。旧 STDC/baseline 的 J 只能用于旧模型桥接，不能直接用作新模型胜负阈值。三次重复用于观察截止时间和机器调度波动，不是三个独立海况样本。

## 5. B30：预先安排的独立诊断

B5 的 24 项都有效完成后，无论 B5 是否达到质量门槛，执行既定 B30。无需根据中间结果选参数、挑场景或筛选覆盖。

```bash
python scripts/run_eight_neighbor_physical.py run --stage B30 --out outputs/eight_neighbor_physical_20261127/local_r1
python scripts/run_eight_neighbor_physical.py summarize --out outputs/eight_neighbor_physical_20261127/local_r1
```

矩阵与 B5 相同，24 项各 30 秒，算法预算 720 秒。每项是全新进程、从同一历史路线重启，不从 B5 最好解接着跑。B30 判断使用自己的同预算两种覆盖结果，不能回写 B5 的通过状态。

总计 **96 项，1128 算法秒，即 18 分 48 秒**。这不是总耗时承诺：实际测试、输入读取/哈希、进程启动、结果审计、I/O 和 watchdog 余量另计；部分任务可能提前完成。执行器逐项串行运行，不要同时启动两个指向同一目录的进程。

## 6. 如何读结果

首先看 `REPORT.md` 的完整性与 A 门槛，再看各组 J/Pd、`summary.json` 的判断和 `comparison.csv` 的逐项证据。

B5 的预声明质量门槛：主覆盖至少一个场景 J 中位数改善达到 0.5%，另一场景不能回退（相对数值容差 `1e-8`）。同预算 axis 覆盖至少在一个主覆盖获胜场景也须正改善（超过相对 `1e-8`），且任一场景不得回退超过 0.5%。0.5% 是工程筛选阈值，不是显著性检验。

| 状态 | 解释 |
|---|---|
| `screen_passed_pending_holdout` | B5 主质量与覆盖敏感性均通过；仍需下一批独立档案和物理校准 |
| `sensor_sensitive` | 主覆盖有信号，但同预算敏感性不支持；优先核查相机覆盖假设 |
| `screen_not_passed` | B5 未达到预声明门槛；不自动启动大规模调参 |
| `longer_budget_signal_pending_followup` | B30 独立出现信号；不能宣称 B5 通过 |
| `longer_budget_sensor_sensitive` / `longer_budget_screen_not_passed` | B30 的覆盖敏感或未通过判断 |
| `incomplete_or_invalid` | 缺记录、错误、矩阵不完整或 A 未通过；不能解释为零收益或路线无效 |

共同飞行时长为 H，实际飞行距离应为 vH。几何收益若存在，体现在同样航程下更合适的到达/观测位置；不能写成多飞了距离或缩短了本批固定任务时长。搜索 wall/CPU、进程 wall、采样 RSS、展开数和 guide/transition/replay 计时在原始 JSON 中保存。RSS 为轮询峰值近似，不是操作系统精确高水位。

`comparison.csv` 同时列出有效、缺失和失败/不完整项，缺失指标留空。J/Pd 汇总中位数可能来自不同重复，不能合成为一条虚构路线；定位具体改善请使用单次 `result.json` 的 J、Pd、waypoints 与 physical_replay。

## 7. 中断、失败与复跑

每次运行保存独立的 `task.json`、`stdout.log`、`stderr.log`、`result.json` 和 `record.json`。2 GiB RSS 上限或“算法预算 + 15 秒”进程 watchdog 触发时，保留失败记录并停止当前阶段。15 秒是启动、输入和审计余量，**不会扩展有效候选的算法截止时间**。

完全成功、哈希一致的记录可由同一命令验证后跳过。若某任务留下半目录、失败或损坏证据，同一目录不能覆盖或悄悄重跑。保留它，在 `local_r2` 等新目录重新进行 P0、冻结和规定阶段，并说明重跑原因；不要删除失败来制造完整矩阵。

冻结后修改源码、测试、协议文档、配置或依赖也必须重新验证，使用新目录。预算和门槛已在 runner 中锁定；如要开展不同协议，应明确建立新批次，而不是把新规模继续称为本批 B5/B30。

## 8. 回传仓库

完整结果至少包括：预检、validation/JUnit、protocol、tasks、runs、summary、comparison、REPORT。不要只上传汇总表。按照 [RESULTS_TEMPLATE.md](RESULTS_TEMPLATE.md) 写 `ANALYSIS.md`，明确未通过、失败和未运行项。

确认你仍在本研究分支，随后在仓库根目录提交本批目录：

```bash
git status --short
git add asar_repro/outputs/eight_neighbor_physical_20261127/local_r1
git commit -m "Record local four/eight-neighbor physical study results"
git push origin eight-neighbor-physical-study-20261127
```

本批不自动运行 300 秒搜索、MILP、any-angle、状态格、Fundy 或独立新档案。是否进入这些方向，应在有限矩阵完成后，依据物理评分、覆盖敏感性和计算开销决定。

