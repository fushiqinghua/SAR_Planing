# 本地执行手册：进展感知前缀 P30

本次仓库只交付实验代码、协议和测试，状态 prepared_not_run。用户本地执行测试与 36 次正式任务后再上传结果。实验不会更新 H2 粒子、下载 forcing 或生成新粒子。

## 一、拉取

在仓库目录执行（不要将新建文件覆盖到旧输出目录）：

    git fetch origin
    git switch eight-neighbor-rolling-pilot-20261128
    git pull --ff-only origin eight-neighbor-rolling-pilot-20261128
    cd asar_repro
    conda activate maritime-sar
    python scripts/run_eight_neighbor_progress.py prepare

新批输出默认为 outputs/eight_neighbor_progress_20261128/local_r1。需要有旧 H2 的 outputs/eight_neighbor_h2_20261127/local_r2/inputs，以及由旧冻结任务读取的 S30 初始路线。系统会核对来源 SHA 和 Git blob。

## 二、验证

    python scripts/run_eight_neighbor_progress.py validate

Windows 若默认 pytest 临时目录硬链接创建失败，先创建一个**新的**可硬链接目录，且目录父级必须存在。例如 PowerShell：

    $env:ASAR_PREFIX_PYTEST_BASE = Join-Path $env:USERPROFILE 'asar_progress_pytest_20261128_r1'
    New-Item -ItemType Directory -Force -Path $env:ASAR_PREFIX_PYTEST_BASE | Out-Null
    python scripts/run_eight_neighbor_progress.py validate

注意：不要在已经生成了失败 validation 证据的同一 local_rN 中覆盖；发生失败时保留记录，从新的 local_rN 重新 prepare。新版本需要新分支提交。

## 三、正式实验

仅验证通过后执行：

    python scripts/run_eight_neighbor_progress.py run

该程序使用 36 份冻结的任务、同机交错 C0、C0_PREFIX、C0_PROGRESS；失败运行保留原始目录，拒绝覆盖，不应以先跑完的结果替代全部矩阵。

随后：

    python scripts/run_eight_neighbor_progress.py analyze

分析产生 REPORT.md、summary.json、instance_comparison.csv、progress_diagnostics.csv、comparison.csv、survival.csv、incumbent_history.csv。应检查四个实例的 J、Pd、激活计数和相对退化，并在 ANALYSIS.md 记录人工判断。注意：候选内层 incumbent 时间不代表完整任务可执行路线的同质量加速时间。

## 四、回传

确保原始 run 结果、失败记录和协议一并保留，执行：

    git add asar_repro/outputs/eight_neighbor_progress_20261128

如果当前位于 asar_repro 子目录，可执行：

    git add outputs/eight_neighbor_progress_20261128

然后在仓库根目录 commit / push 到原分支。不要把 H2 粒子原始二进制强制上传到另一个目录，不要修改旧输出和冻结结果。若验证失败，上传 validation 证据与相关错误，不能报告正式结果已通过。

## 五、脚本保护说明

- 新增的 progress 源码与辅助脚本均包含在冻结源码清单。
- 关键旧代码与本轮基点的 Git 差异保持为零。
- 原始评分器、启发式、补全上限、时钟与 OPEN 容量保持不变。
- 结果失败或需要改代码时，使用新 local_rN，先重新冻结和测试，绝不改旧协议。
