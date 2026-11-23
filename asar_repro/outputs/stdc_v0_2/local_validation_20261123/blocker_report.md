# STDC-A^SAR v0.2 本地接入：blocked

**状态：blocked。全量历史测试首次失败后立即停止；本轮接入未验收通过。**

研究分支为 `stdc-research-v0.2`，独立 worktree：`E:\毕业设计\终稿研发\new\baseline\SAR_Planing-stdc-v0.2`。起点为冻结分支 `baseline-v1.1` 的 `81b9be9b51625ed9012a69f9cb90e296bf2ec5c2`。原基线目录保留原分支与原数据；没有移动其引用，没有修改 B7、评价器、forcing 或原海上搜救程序。

## 本轮实际顺序与结果

| 阶段 | 本机结果 | 测试/案例数量 |
|---|---|---|
| 工作树与输入指纹预检 | passed；541 份跟踪文件一致，110 份原始数据逐文件复制后 SHA 相同 | 654 份原基线文件纳入保留核验 |
| apply_stdc_patch.py --dry-run | passed；4 组锚点各出现 1 次，零源文件变更 | 不适用 |
| 实际应用交付补丁 | passed；6 份 payload 与交付 SHA 一致，heuristic 改动与预检 diff 相同 | 不适用 |
| 新测试 | passed | 19 passed，0 failed / 0 skipped |
| 全量 pytest -x | **blocked** | **33 passed，1 failed**，随后停止 |
| 160 组随机小图、逐前缀 Oracle | **未执行** | seed 100–179 × 两类为后续原计划，不是实测 |
| 35 组小图搜索 | **未执行** | seed 15000–15034 为后续原计划 |
| Lake Ontario mass_lb / stdc_lb 两组 smoke | **未执行** | 冻结粒子 seed=41；没有生成或替换粒子 |

当前基线已有 248 项历史测试。交付新增 19 项，原 MODES 参数化测试另增加 5 项，预计完整收集应为 272 项；因全量在首次失败处终止，**本轮没有验证完整收集/执行总数**。JUnit 记录实际执行 34 项。交付包 results/ 中的镜像环境成绩没有冒充本机结果。

## 阻断原因与原始证据

失败测试：

`tests/test_b4_artifacts.py::test_legacy_source_hashes_and_completion_denominator`，第 67 行。

该测试读取冻结 `outputs/baseline_v1.1/b4/audit.json`，要求当前工作树的代码指纹等于 B4 固定指纹。交付补丁按设计修改研究工作树的 `src/asar_repro/heuristic.py`，因此出现：

- B4 预期与原 baseline 实际 SHA：`38e03ceb511c62b7d5d9494206e752647bfaff796e7dc3ba08c195f1445446fc`
- 本研究分支应用补丁后的 SHA：`43f94d7ec3ae69dc67ee4416892ea65aa445498a002905f77d4b1f533b168c0b`

B4 审计清单中的其他 8 个代码/配置指纹仍一致。这是历史源码冻结断言与研究接入方式的冲突；它既不等同于 STDC 可采纳性反例，也不能被忽略。没有改写旧 hash、删除/跳过测试、放宽断言、回滚补丁后冒充研究分支测试通过，亦未继续任何后续实验。

证据目录：`outputs/stdc_v0_2/local_validation_20261123/`：

- `blocker.json`：失败位置、两个 hash、实际计数和未执行阶段。
- `full_tests/stdout.txt`、`stderr.txt`、`pytest.xml`、`stage.json`：完整命令、输出和 pytest 原始失败。
- `new_tests/`：19 项新测试的命令、stdout/stderr、JUnit 与计数。
- `dry_run/anchors.json`、`planned_heuristic.diff`：锚点次数及先审阅后应用的差异。
- 每阶段的 `before.git.diff`、`after.git.diff`、`*.git.status`、`*.source_sha256.json`：阶段快照。
- `00_preflight.json`、`post_stop_preservation.json`：基线/输入/交付文件指纹及停止后的独立核对。
- `validation_summary.json`：总状态 blocked。
- `read_only_review.json`：只读代码审查结论；不冒充测试结果。

## 环境与执行命令

现有解释器：`C:\Users\35448\.conda\envs\maritime-sar\python.exe`。Python 包版本：NumPy 2.4.6、SciPy 1.17.1、OpenDrift 1.14.12、pytest 9.2.0、netCDF4 1.7.5。未安装或升级依赖。执行设置包括单线程 BLAS/OMP、Python 离线 socket 保护、PROJ_NETWORK=OFF、禁止写 pyc 和 pytest cache。

每条真实 subprocess 参数保存在相应 `stage.json`；本轮依次执行的核心命令为：

```powershell
& $PY '<交付目录>\patch\scripts\apply_stdc_patch.py' --repo '<研究worktree>\asar_repro' --dry-run
& $PY '<交付目录>\patch\scripts\apply_stdc_patch.py' --repo '<研究worktree>\asar_repro'
& $PY -m pytest -x -q tests/test_stdc_heuristic.py --junitxml '<run>\new_tests\pytest.xml'
& $PY -m pytest -x -q --junitxml '<run>\full_tests\pytest.xml'
```

`-x` 确保第一项失败后退出。新增外围 `scripts/run_stdc_local_stage.py` 按顺序记录日志，拒绝同名阶段覆盖、失败后的推进及无依据重试。后续独立审计 guard 尚未构建，因为本轮在历史测试阶段停止。

准备 worktree 时出现的目录已存在和版本目录后缀解析问题已在测试前修正并记录于 `00_preflight.json/setup_attempts`；没有任何历史测试失败后的重试。

## 文件改动范围

已按交付原样应用：

- `src/asar_repro/heuristic.py`：唯一既有源码变化，4 处模式/委托接入。
- `src/asar_repro/stdc_heuristic.py`：独立 STDC 实现。
- `tests/test_stdc_heuristic.py`：新增测试。
- `scripts/run_stdc_random_audit.py`、`run_stdc_small_search.py`、`run_stdc_smoke.py`、`run_stdc_synthetic_bench.py`：4 份运行脚本；后者未执行。

此外只增加本地阶段日志器、阻断报告和证据。安装脚本本身位于原交付目录，不在 6 份复制 payload 中。没有修改历史测试、B4 审计清单、search.py、objective.py、oracle.py、motion.py、search_reporting.py 或原仿真源码。

## 停止后的数据保留证明

- 原 baseline 分支仍为 `81b9be9b51625ed9012a69f9cb90e296bf2ec5c2`。
- 654 份原基线受检文件全部未变；研究副本唯一既有源码变化为 heuristic.py，110 份 raw 副本未变。
- 真实粒子归档 SHA：`8b30a87e543f1b33c39e70e1d0054e1750ec046ba2e0b627dd311d9945749456`。
- 冻结协议 SHA：`bc18ddcb922231168aef34d8805bd3f7388a2b3ed9c27e9522368141fa469ff7`。
- 评价器 objective.py SHA：`792077ad3e0286c03f60108f2580ea3b3557e3f5b002bc1a5e2f9f67e48fb2ad`。
- 上述 SHA 复核是文件保留检查，**不是 Lake Ontario smoke 已执行的证明**。

## 数学范围与尚未解决的问题

只读审查确认交付算法按绝对时间 d+k 传播、按相对步数 k 构造可达集；特殊粒子 bin 保留未探测质量。19 项新测试通过，但指定的大批随机前缀与搜索审计尚未运行，不能据此宣告整体数学验收或真实性能提升。

新模式的条件性离散 ε 界仍依赖至少两个顶点的矩形四邻接无等待图、外生非负质量守恒运动、固定逐格探测概率、特殊质量保留以及搜索真正完成。浮点容差不是形式化误差证明。paper_greedy 未加入 BOUND_MODES，动态 ε 界依旧不能认证；原动态反例测试尚未在本轮完整历史回归中执行到。

只读审查还发现：

1. 原 search_reporting 的通用算法命名不认识 STDC 模式；交付 smoke 自行记录 mode，不受该问题影响。本轮没有改冻结报告/评价接口。
2. 单格图的 reachable 辅助接口未完全防护；本轮模型前提和指定实验要求至少两个顶点，不扩展该范围。
3. 交付 random_audit 先累计违规、末尾才抛异常，mass dominance 仅统计；后续必须在外围补首违即停与输入数组归档。
4. 交付 small_search 未保存并独立重放路径；后续必须补完整路径合法性/J/Pd 核对及 ε=1 双向 Oracle 一致。
5. 交付 smoke 只相对当前协议验粒子 hash；后续必须先做固定协议、metadata、评价器、17×17/T49/q=.78/PT 指纹门禁，并确保中止无认证。
6. 默认 smoke 是同进程两组单次检查，不代表独立进程三次重复的性能主实验。

这些仅记录为后续接入问题；本轮未修复以跨过失败门槛。下一轮应先明确研究分支与历史源码冻结测试如何隔离，保留原历史审计的有效性，而不是改旧 hash 使其通过。没有开展创新点二、缓存优化、全消融、合成大图探针或环境 forcing 修改。

## 归档补充

停止后的归档检查发现：交付安装器在 Windows 上将 heuristic.py 写为 CRLF（73 行），git diff --check 返回 2 并将 CR 识别为行尾空白。因此原始 git diff 展示整文件行尾变化；dry_run/planned_heuristic.diff 则展示 4 处逻辑接入。详见 archive_diff_check.json 及对应 stdout/stderr。本轮保留测试时的字节，没有归一化源码或重跑测试。解释器完整版本为 Python 3.11.18（conda-forge，MSC v.1944，64 bit AMD64）。

归档提交仅保存 blocked 的研究快照，不代表接入验收、发布或数学认证。没有推送远程。
