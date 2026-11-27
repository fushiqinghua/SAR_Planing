# 本地执行说明

## 交付状态

本分支提供实验协议、冻结配置、ILS/CEM、count 模型、待运行测试与独立执行器。**交付时所有新测试、算法、枚举、MILP 和真实场景实验均为 not_run。** 当前仅经过源文件阅读、数学/协议静态审查、Python AST 与 JSON 解析检查。

顺序是 P0 → A → B5 → B30 → 条件 C300 → 汇总。脚本没有自动执行全部阶段的命令，也不会下载 forcing、重新生成真实粒子、运行 Fundy 或启动独立档案验证。

## 1. 拉取新分支

在已有 SAR_Planing 仓库目录执行。若当前有自己的未提交修改，先提交或备份再切换；不要使用 reset --hard。

~~~powershell
git status --short
git fetch origin
git switch -c solver-paradigm-study-20261127 --track origin/solver-paradigm-study-20261127
Set-Location ./asar_repro
~~~

首次建立本地分支使用上面的 switch -c。以后回到这个分支时使用：

~~~powershell
git switch solver-paradigm-study-20261127
git pull --ff-only
~~~

原分支与历史结果保留。新实验不要写到已有 STDC 输出目录中。

## 2. 本地环境

推荐继续使用已有 maritime-sar 环境，不需要重新配置 OpenDrift 或重跑漂移。本批直接读取已归档粒子。

~~~powershell
conda activate maritime-sar
$PY = (Get-Command python).Source
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$OUT = Join-Path (Get-Location) "outputs/solver_paradigm_study_20261127/local_r1"
& $PY -m pip install -r requirements-solver-study.txt
~~~

依赖安装不加 --upgrade，保留现有满足条件的包。本地正式冻结记录实际 Python、NumPy、SciPy、psutil、pytest、系统与 CPU，以及可以取得的 SciPy 内嵌 HiGHS 版本；无法读取的原生版本明确标记 unavailable，不推断为其他 highspy 包的版本。运行器在导入数值代码前设置单线程环境，count 显式向 HiGHS 请求 threads=1，并保存选项和 warning；没有假称已完成原生线程读回核验。

Python 需要 3.11 或更高版本。本批不要求绘图库、独立 highspy、GPU 或商业求解器。pytest 子进程的 PYTHONPATH 由运行器配置。

Linux / macOS 可使用相同阶段命令，仅将调用变量改为：

~~~bash
conda activate maritime-sar
cd /path/to/SAR_Planing/asar_repro
SAR_STUDY_PY="$(command -v python)"
SAR_STUDY_OUT="$PWD/outputs/solver_paradigm_study_20261127/local_r1"
"$SAR_STUDY_PY" -m pip install -r requirements-solver-study.txt
"$SAR_STUDY_PY" scripts/run_solver_paradigm_study.py plan
~~~

以下以 PowerShell 为例。Linux 将 “& $PY” 替换为 “"$SAR_STUDY_PY"”，将 $OUT 替换为 "$SAR_STUDY_OUT"。只运行需要的阶段，每条命令成功结束后再进入下一条。

## 3. P0：预检、验证和冻结

先查看任务规模；plan 只列计划，不加载真实档案或启动算法：

~~~powershell
& $PY scripts/run_solver_paradigm_study.py plan
~~~

再做预检：

~~~powershell
& $PY scripts/run_solver_paradigm_study.py preflight --out $OUT
~~~

预检检查旧源文件指纹、两个主要场景的输入与 metadata SHA-256、时间轴、轨迹身份、共同 PT 和历史参考的原评分重放，以及诊断实例定义。不做性能比较。

应存在以下输入，位置和哈希已在配置中给定：

| 场景 | 粒子 | metadata |
|---|---|---|
| Lake | outputs/baseline_v1.1/lake_ontario_real/particles.npz | 同目录 metadata.json |
| Hudson | outputs/stdc_v0_2/additional_real_20261124/b3/arctic_ocean/particles.npz | 同目录 metadata.json |

缺失时，从原工作区恢复对应原文件；若 Git LFS checkout 仅留下指针，应按仓库既有方式恢复二进制文件。**不要重新随机生成一个同名档案，也不要改哈希使错误输入过关。** 方向仍未核实的 Fundy 不作为 P0 的主要输入要求。

执行本地验证：

~~~powershell
& $PY scripts/run_solver_paradigm_study.py validate --out $OUT
~~~

这个命令才会在你的本地运行 pytest。它包含原 objective/particle_search 回归，以及新路线优化器、count、协议控制测试。它会真实调用小模型求解来交叉验证，因此不得把它标成纯语法检查。

每次验证生成独立时间戳目录，保留 stdout、stderr、JUnit 与 source/config 指纹。必须返回码为 0、有 testcase、无 failure/error/skip 且源文件不变，才能冻结。失败后查看 validation/latest.json 指向的目录；修复、再次验证，不跳过检查。

~~~powershell
& $PY scripts/run_solver_paradigm_study.py freeze --out $OUT
~~~

freeze 要求测试证据与当前代码、配置、环境完全一致，生成 protocol.json 和固定任务清单。原有算法源码由 base_source_inventory.json 保护；本批新增文件允许在本地验证前修复，但必须记录修复并重新验证冻结。

## 4. A：小中规模最优差距诊断

~~~powershell
& $PY scripts/run_solver_paradigm_study.py run --stage A --out $OUT
& $PY scripts/run_solver_paradigm_study.py summarize --out $OUT
~~~

共 18 个预定义实例：

- tiny：4×4，T=4/5/6；三类结构各三例。
- medium：7×7，T=12/14/16；同样三类结构。
- 每例五种路径方法各 2 秒、各一次。
- count：tiny 每例 15 秒，medium 每例 60 秒。
- tiny 再由已有独立 DFS 完整枚举，每例 30 秒名义保护预算。

A 共 117 任务、1125 秒算法预算。所有实例定义在冻结文件保存，不按结果筛选。

进入 B 的要求：

1. A 所有任务有效完成；blocked、数值错误和异常不会被共同初始路线掩盖。
2. 每个 tiny 的 DFS 在预算内完成。
3. tiny count 返回完整问题域的数值闭合，solver status、原路线复算和 dual 均相符，且与独立 DFS 的 J 在 1e-8 内一致。
4. 任何 count 下界不得超过同例所有求解器已复算的最小可行 J 加容差，medium 也检查。

medium 在预算内未闭合属于有效诊断，保留区间；不称为最优，也不能用来证明原真实场景最优。

DFS 旧 API 没有合作式 deadline，由父进程 watchdog 保护；若超过名义预算才结束，其最优结果只留在 raw，不作为预算内通过证据。watchdog 对所有方法保留额外 15 秒进程/清理余量，该余量不能贡献正式 J 或时间收益。

## 5. B5 / B30：同模型真实档案比较

~~~powershell
& $PY scripts/run_solver_paradigm_study.py run --stage B5 --out $OUT
& $PY scripts/run_solver_paradigm_study.py summarize --out $OUT
~~~

B5 完整后再执行：

~~~powershell
& $PY scripts/run_solver_paradigm_study.py run --stage B30 --out $OUT
& $PY scripts/run_solver_paradigm_study.py summarize --out $OUT
~~~

每阶段有 38 个任务：两个主要场景；paper_baseline、anytime_zero、anytime_mass 各 3 次；ILS/CEM 各 5 个固定种子。

B5 与 B30 是独立运行，不能用 30 秒退火日程的前 5 秒快照替代 B5。共同 PT 的复制和评分从计时开始计入；模型输入读取、库导入、哈希/环境校验与报告审计在算法预算外，由进程总耗时另报。算法内部仍发生的准备或延迟导入计入其预算。

本批比较“给定相同已知可行 PT 后的求解”，原 PT 的离线生成成本各方法统一不计。历史参考路线不作为正式热启动。论文 API 不能提供中间完整路径时间戳，因此只把其返回并完整重放的路线记为可观测改善；旧原始返回值保留，晚于预算的改善不计入主表。

## 6. C300：按 B30 证据触发的有限延长诊断

~~~powershell
& $PY scripts/run_solver_paradigm_study.py run --stage C300 --out $OUT
~~~

运行器先检查完整 B30：

- 某新方法—场景至少 2/5 seeds 严格击败该景历史参考，绝对改善 >1e-8；或
- 该方法按完整两主场景规则通过 B30 质量/时间筛选。

每个触发组合只跑预先固定的前两个种子，不能挑表现最好的两个。最多 8 任务、2400 秒。未触发时只保存 not_triggered，没有启动长实验。进入 C300 不代表 B5 已通过，也不代表可以宣称独立泛化。

## 7. 中断、失败与续跑

- 所有任务串行、各用独立子进程。每任务保存 task、record、raw result 和 stdout/stderr。
- 同一命令再次运行时，只跳过已完成且任务、协议及 raw 哈希一致的记录。
- 如果存在没有 record 的半成品目录，或 record 已标 failed/blocked，会停止，不删除或覆盖。
- 修改代码、配置、依赖或输入后，旧 protocol 不再可续跑。换 local_r2 等新目录，先验证，再冻结，重新执行该批；不得拼接不同版本的结果。
- 即便发生 fatal，已有可行 PT 仍可作为错误诊断信息保存，但任务不视为正常“零改善”。
- 比较期间不要并行启动训练、其他规划 benchmark 或多个本批阶段。
- 如需变更已注册方法、预算或实例，先记录新的协议版本；不要根据当前胜负直接扩展当前冻结矩阵。

## 8. 汇总与回传

~~~powershell
& $PY scripts/run_solver_paradigm_study.py summarize --out $OUT
~~~

建议回传整个输出目录。至少保留：

- protocol.json 与 tasks/*.json；
- validation/ 的测试原始日志、JUnit 和来源指纹；
- runs/ 下全部 task.json、record.json、result.json、stdout.log、stderr.log，包括失败；
- summary.json、comparison.csv、REPORT.md；
- 若尝试 C300，保留 C300_selection.json；
- 按 results_template.md 填写的分析，建议保存为本批输出目录 ANALYSIS.md。

comparison.csv 的空时间表示未达到/缺测，结合 target_reached、target_censored、censor_time_s 判读，不能把空值填成预算时间或 0。随机 seeds 只评估算法稳定性，不是独立目标轨迹。

从仓库根目录提交结果时，只加入本次输出及确有必要的代码修复，不提交整份原始 forcing：

~~~powershell
Set-Location ..
git status --short
git add asar_repro/outputs/solver_paradigm_study_20261127/local_r1
git commit -m "Record local solver paradigm study results"
git push origin solver-paradigm-study-20261127
~~~

若代码有修复，单独说明修改、重新验证和冻结的目录，不能直接把旧运行归因于新实现。

