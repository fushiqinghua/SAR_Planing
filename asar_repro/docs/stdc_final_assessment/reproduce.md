# 复跑本批实验

本批在已有冻结粒子档案上评估算法，不需要重新调用 OpenDrift。三份粒子文件已在仓库；原始风流大文件不属于此次重放的前置条件。本批不据此声称重新完成了原始 forcing 审计。

## 依赖和环境

本次实际使用 Python 3.12.14、NumPy 2.3.5、SciPy 1.17.0、psutil 7.2.2、pytest 9.0.2。SciPy 内置 HiGHS 为 **1.8.0**，不同于旧 Windows 实验的 HiGHS 1.12.0；因此只比较本批同环境的四个 MILP arm。关闭 presolve 和严格数值检查保持一致。绘图另用 matplotlib，版本写入输出环境。

完整机器、CPU、解释器、包版本和线程环境见正式输出 `protocol.json`。新机器必须重新冻结，不能续接本机的已测时间。

在 `asar_repro` 目录，先设置 `PYTHONPATH=src` 和数值库单线程：

```bash
export PYTHONPATH=src
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
```

以下 `python` 应是已安装上述依赖的解释器。请用新的输出目录名，避免覆盖档案。

## 验证与冻结

```bash
mkdir -p outputs/my_final_assessment/validation
python -m pytest -q -p no:cacheprovider \
  tests/test_final_event_candidates.py \
  tests/test_final_pair_bound.py \
  tests/test_final_assessment_runner.py \
  tests/test_stdc_heuristic.py tests/test_research_search.py \
  tests/test_research_particle.py tests/test_exact_repair.py \
  tests/test_grid.py tests/test_belief.py tests/test_objective.py \
  --junitxml=outputs/my_final_assessment/validation/junit.xml \
  > outputs/my_final_assessment/validation/pytest.log 2>&1
python scripts/audit_stdc_final_theory.py \
  --output outputs/my_final_assessment/validation/theory_audit.json
python scripts/run_stdc_final_assessment.py --stage freeze \
  --output outputs/my_final_assessment
```

freeze 要求测试没有失败、错误或跳过，理论审计通过，原分支已有源码仍与 `6167d344` 一致，三景哈希和历史路线重放一致。需要 Git 历史中包含这个基点；只取最新提交的浅克隆须先取得基点提交。

## 串行实验

```bash
python scripts/run_stdc_final_assessment.py --stage benchmark --output outputs/my_final_assessment
python scripts/run_stdc_final_assessment.py --stage events --output outputs/my_final_assessment
python scripts/run_stdc_final_assessment.py --stage event_followup --output outputs/my_final_assessment
python scripts/run_stdc_final_assessment.py --stage pairs --output outputs/my_final_assessment
python scripts/run_stdc_final_assessment.py --stage mip --output outputs/my_final_assessment
python scripts/run_stdc_final_assessment.py --stage summarize --output outputs/my_final_assessment
python scripts/report_stdc_final_assessment.py --output outputs/my_final_assessment
```

不要同时启动多个阶段、多个计时 worker 或其他 CPU 密集任务。相同源代码/输入/环境下可重复调用某阶段以恢复已完成记录。首个进程级阻塞会终止该阶段并保存证据；修复实现或环境后建立新目录重新验证冻结，不修改旧记录。

## 如何读输出

- `protocol.json`：配置、输入/源码/验证指纹、机器环境、主辅助场景标签。
- `runs/<task>/task.json`：场景、方法、预算、重复序号、固定前缀等具体任务。
- `runs/<task>/raw_result.json`：完整路线、原评分重放、incumbent history、到达目标时间、统计与实际 worker 环境。
- `runs/<task>/record.json`：进程退出、watchdog、峰值 RSS、启动到退出耗时与结果哈希。
- `stdout.log`、`stderr.log`：原始日志。MILP 数值/约束警告另保存在结果 stats。
- `summary.json`：固定规则计算的门槛结果、计时统计、缺失/删失、事件及 pair 诊断。

`measured_algorithm_wall_s` 与整个 worker 的时间不同；后者含导入和输入加载。正式 J 和 time-to-target 只接受预算内完成的 incumbent。`returned_*` 保留合作式截止后返回的实际路径，不把迟到改善计入限时结果。固定扩展表也不是同墙钟成绩。

首轮 `outputs/stdc_final_assessment_20261125` 的启动阻塞记录完整保留；正式重新冻结后的结果位于 `outputs/stdc_final_assessment_20261125_r1`。两者不得混合汇总。
