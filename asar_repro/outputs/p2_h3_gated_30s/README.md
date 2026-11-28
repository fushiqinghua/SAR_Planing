# H3 门控限宽续接的 30 秒对照

五个冻结实例为 3401、4401、4402、4501 和 4601。每个实例的 C0、原 Lazy 和门控限宽续接各运行三次。按配对编号用固定种子 2026112902 随机确定次序，进程串行运行。三臂沿用原目标 J、探测模型、forcing、真实历史粒子和 S30 路线。

门控组用 S30 前四分之一观测的已探质量除以 S30 终点 Pd。比值达到 0.5 时沿用原 Lazy。原 Lazy 的资格截止在三个对照组使用的同一计时口径下固定为 5.95 秒。晚覆盖实例保持 C0 全局队列。在 5 秒和 18 秒检查点，主搜索尚未生成完整路线且 OPEN 较两秒前增长时才续接。每次波次分配最多 3 秒，选择工作计入同一波次。

短名单在最大已展开观测步的前后三步内形成，每观测步最多选六个不同顶点的原队列条目。从短名单出发，每层续接留存最多 32 个状态，保留绝对时钟、后验权重与累计 J，使用原物理推进和原引导优先级。主队列条目按原规则保留。续接候选须由原评分器完整重放，再依 J 选择。Pd 作为结果验收护栏。

## 三阶段验证

1. `check_fixed_work.py validate` 保存 toy/Oracle、原求解器及回放相关的 pytest 结果。
2. `check_fixed_work.py fixed` 复核冻结 S30 与等展开量队列指纹，独立核对选择器的实时 OPEN 来源。4601 的旧路线只在短名单选完后用于对照。
3. `run_study.py freeze` 核验旧 H3 全量输入与源码，锁定试验参数。`run_study.py run` 运行串行计时。`report_study.py` 重读原始文件、核对指纹并输出比较。

实际命令、测试证据与每次运行结果分别在 `results/local_r1/commands`、`results/local_r1/preflight`、`results/local_r1/runs`。正式求解预算是 30 秒，交付预留 2 秒。预算内包含队列选择、续接、原评分器验收和交付。输入加载与事后独立标量重放另计。峰值 RSS 为独立子进程 50 ms 轮询的采样值。

在原实验环境复跑时，从 `asar_repro` 根目录使用冻结解释器，把项目的 `scripts`、`src`、旧诊断目录 `outputs/p2_h3_frontier_diagnostic` 及本目录放入 `PYTHONPATH`，并设置 `ASAR_OFFLINE=1`。原始文件须先通过 H3 指纹检查。独立重跑使用新的结果目录，以保留已归档的候选、回退和预算证据。



## 正式结果与归档

45 次试验均通过交付、独立路线重放和计时核验，最长外层耗时 28.132 秒。

- **4601** 的结果为 门控组三次交付同一路线，J = **55.196889792**，Pd = **23.0175504%**。三次均满足 J ≤ 55.828347528 与 Pd ≥ 19.68046%。路线 SHA-256 为 `b65c8944edcfa333d0b2e8f12605dcafd10aff50724439b7c2ffc0f5edb87e5a`。
- **4501** 的结果为 J = **55.655905440**，Pd = **19.1407008%**，三臂持平。门控组峰值 RSS 中位数 **105.24 MiB**，C0 为 105.00 MiB，原 Lazy 为 374.94 MiB。门控组相对原 Lazy 的峰值 RSS 和 OPEN 中位数分别下降 71.9% 和 95.9%。
- **3401** 的结果为 门控组保住原 Lazy 的 J = **11.343163824** 和 Pd = **96.0127638417792%**。相对 C0，J 改善约 0.452%，Pd 降低 0.44315 个百分点，三次均满足 0.5 个百分点护栏。

[完整报告](results/local_r1/analysis/REPORT.md) · [对照图](results/local_r1/analysis/guard_cases.png) · [逐次 CSV](results/local_r1/analysis/runs.csv) · [配对 CSV](results/local_r1/analysis/paired.csv) · [45 次原始记录](results/local_r1/runs)

[冻结协议](results/local_r1/protocol.json) · [152 项 pytest 日志](results/local_r1/preflight/toy/stdout.log) · [等展开量前缀核验](results/local_r1/preflight/fixed_cases.json) · [独立交付核验](results/local_r1/commands/delivery_check.json) · [最终冻结复核](results/local_r1/commands/final_frozen_recheck.stdout.log)

从本目录运行 `python report_study.py` 可离线重建报告，需 Python 3.11 或以上。历史绝对路径保留为实验记录。`verify_delivery.py` 和正式复跑需要匹配冻结的本地 H3 原始输入及环境。
