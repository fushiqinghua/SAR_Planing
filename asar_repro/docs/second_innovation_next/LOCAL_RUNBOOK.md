# 本地执行说明

当前状态：**P1 可执行脚本已交付、未运行；P2/H3 仅设计与日期预注册，尚无新原始 forcing 或专用执行器。** 不改旧结果和旧算法。

在仓库根目录：

    git fetch origin
    git switch eight-neighbor-rolling-pilot-20261128
    git pull --ff-only origin eight-neighbor-rolling-pilot-20261128
    conda activate maritime-sar
    cd asar_repro

P1 前必须保留 H2 原输入目录 outputs/eight_neighbor_h2_20261127/local_r2/inputs，以及 Lazy 上批原协议 outputs/eight_neighbor_lazy_prefix_20261128/local_r1/protocol.json。预检会核对原文件 SHA 和源代码。查看计划：

    python scripts/run_lazy_robustness_p1.py plan

新目录冻结（不能覆盖旧 local_rN）：

    python scripts/run_lazy_robustness_p1.py prepare

真实 toy/专项和全量测试：

    python scripts/run_lazy_robustness_p1.py validate

Windows pytest 临时目录遇到硬链接错误时，请创建全新测试父目录并在 validate 前设置环境变量 ASAR_ROBUST_PYTEST_BASE。例如 PowerShell：

    $env:ASAR_ROBUST_PYTEST_BASE = Join-Path $env:USERPROFILE 'asar_p1_pytest_parent_20261128'
    New-Item -ItemType Directory -Force -Path $env:ASAR_ROBUST_PYTEST_BASE | Out-Null
    python scripts/run_lazy_robustness_p1.py validate

如果已经尝试失败的 validation，保留失败证据；使用新的 local_rN 和新代码提交，不在同一批结果上覆盖重试。测试通过后：

    python scripts/run_lazy_robustness_p1.py run
    python scripts/run_lazy_robustness_p1.py analyze

脚本会在结果目录保存 task、result、record、原始运行日志和 J/Pd/CPU/RSS 统计。中断后只跳过经过重新核验的已完成任务；失败目录阻止继续，不会覆盖。主结果见 outputs/second_innovation_p1_20261128/local_r1/REPORT.md，回传时将完整目录及人工 ANALYSIS.md 推送到同一分支。

**不要现在运行 P2/H3**：需要先用 registry 里的主日期与候补规则完成新风流 forcing 资格审计、独立 H3 reader 适配、粒子生成、共用初始化 S30、专用 E30 runner 和审计。不能直接修改旧 H2 源代码中写死的日期锁，也不能复制原 H2 粒子冒充新日期。
