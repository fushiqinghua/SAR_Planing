# 阶段 0 验收记录

## 输入与变更范围

初始工作区只有以下两个文件。初始化前后 SHA-256 一致。当前工作区及其父目录中未找到 Git 仓库，无法提供 commit 或 Git 差异。所有交付文件均在新建的 `asar_repro/` 下。

| 输入 | 字节 | SHA-256 |
| --- | ---: | --- |
| baseline复现指导指南.md | 52947 | `F9587FE18FE081272DAC03A9F56DD38557E1E5C3D3D33C38B1B21825E27962A8` |
| ASARε-OptimalGraphSearchforMinimumExpected-Detection-Time.pdf | 4575824 | `8F7739C9A36E512AE57E16159517D5A74B97711DF02E0AEEA192CCD6DF55EACF` |

已通读指南（含附录 A、B）及论文 8 页。以指南正文标题识别用户指名的文件。论文版本为 arXiv:2511.10792v2。

## 代码与配置文件清单

| 文件 | 作用 |
| --- | --- |
| `src/asar_repro/__init__.py`、`src/asar_repro/cli.py` | 包入口与命令行帮助 |
| `scripts/check_env.py` | 导入依赖、记录版本和实际路径、检查 Leeway 初始结果 |
| `tests/test_smoke.py` | 同一测试核验本地源码导入、Leeway 构造和 CLI 子进程 |
| `pyproject.toml`、`.gitignore`、`configs/schema.json` | 可编辑构建、测试发现、生成文件忽略规则、阶段配置标识 |

## 环境与验收证据

PowerShell 默认 `python` 指向 `D:\Conda\python.exe`。项目安装、环境检查、pytest 和 CLI 均显式使用 `C:\Users\35448\.conda\envs\maritime-sar\python.exe`。实测 Python 3.11.18、OpenDrift 1.14.12、NumPy 2.4.6、pytest 9.2.0。

- 安装前保存 `pip list --format=freeze` 的 138 项输出，以及按指定前缀导出的 Conda 环境。使用项目内的 `PYTHONUSERBASE` 离线执行可编辑安装；安装后对比可见包清单，唯一新增项为 `asar-repro==0.0.1`。
- `& $PY -m pytest -q` 得到 `1 passed in 8.07s`。`& $PY -m asar_repro.cli --help` 打印帮助并以 0 退出。复跑命令见 README。
- 本地 `OpenDriftSimulation.__init__` 将 `self.result` 初始化为 `None`，与构造实例的观测一致。在已安装的 `opendrift/models/basemodel/__init__.py` 第 2135、2340 行，`run()` 构造并返回 Dataset。运行后的轨迹坐标与维度留待阶段 5 验证。
- 附加的配置文件格式检查中，目标环境缺少可选工具 `jsonschema`。使用已有的基础 Python 校验 Draft 2020-12 schema 和示例 `{"stage": 0}` 通过。项目运行及 pytest 均未依赖该工具。

| 已保存文件（相对 outputs/logs/） | 内容 |
| --- | --- |
| environment.json | UTC 核验时间、解释器、平台、九个包的版本和导入路径、Leeway 状态 |
| asar_environment_before.txt、conda-environment.yml | 原始依赖清单与 Conda 导出 |
| pytest.txt、cli-help.txt | 此次验收的标准输出 |

阶段 0 没有仿真或算法指标，因此图与 CSV 均为 0 个。下一轮仅待阶段 1 指令，实现四连通图、目标转移、探测更新、统一评分与手算 toy 测试。此后的独立 DFS、A^SAR、启发式与动态反例验证仍待各自阶段。

## 阶段 1 验收记录

本轮使用原 maritime-sar 解释器、NumPy 2.4.6 和 SciPy 1.17.1。项目只操作预先指定的离散转移矩阵和搜索路径。

| 源码 | 行为 | 对应测试 |
| --- | --- | --- |
| `grid.py` | 行优先编号、四邻边、BFS 边数、起点和预算校验 | `test_grid.py` |
| `motion.py`、`belief.py` | 恒等、重复核和时变 CSR 核；先传播后局部探测；输入验证和分支副本 | `test_belief.py`、`test_objective.py` |
| `objective.py` | 给指定路径评分，返回各步 M、g、发现概率增量和最终信念 | `test_objective.py` |

上述源码位于 `src/asar_repro/`，测试位于 `tests/`。另更新了 `pyproject.toml` 的 NumPy/SciPy 依赖声明、README 和模型假设。以 `--no-deps` 刷新了项目内的可编辑安装。

| 运行命令（在项目根目录，解释器设置见 README） | 结果 |
| --- | --- |
| `& $PY -m pytest -q tests/test_grid.py tests/test_belief.py tests/test_objective.py` | `40 passed in 0.24s` |
| `& $PY -m pytest -q` | `41 passed in 9.91s`，含阶段 0 环境 smoke test |

| 给定路径 | M₀ 至 M_T | J | Pd(T) |
| --- | --- | ---: | ---: |
| S→A→S→B，完美传感器 | 1, 0.3, 0.3, 0 | 0.6 | 1 |
| S→B→S→A，完美传感器 | 1, 0.7, 0.7, 0 | 1.4 | 1 |
| S→A→S→B，q=0 | 1, 1, 1, 1 | 3 | 0 |
| 时变两格，0→1→0 | 1, 0.5, 0.375 | 0.875 | 0.625 |

测试另覆盖了不完全探测时重复访问的几何衰减、零步预算、非法移动、无效概率和转移时间越界。对于 seed=7 的两行三列时变 toy，按来源格逐项分配目标质量并直接累计探测削减量，逐步核对统一评分器的 M、g 和 ΔPd。

**问题与范围。** 指南指出的 Eq. (2) 印刷问题按 `1−M_T` 处理。时变 toy 的 `P₁`、`P₂` 不对称且不同，可检查矩阵方向、首末时间索引和先运动后探测的顺序。本轮仅验证给定路径的数值；阶段 2 才引入独立 DFS 及与其对照的零启发搜索。动态贪心反例留待阶段 3 复验。

**产物。** `outputs/metrics/stage1_toy.json` 含四个确定性算例的输入与终值；`outputs/metrics/stage1_steps.csv` 含 15 条逐时刻记录，零步的 ΔPd 字段留空。回读两文件核对了路径、末步 g 与 Pd、各步质量及发现概率增量的总和。两次 pytest 的标准输出见 `outputs/logs/stage1_pytest.txt` 和 `stage1_regression.txt`。本轮图像数为 0，toy 路径热力图属于阶段 4。

## 阶段 2 验收记录

新增 `src/asar_repro/oracle.py`、`src/asar_repro/search.py`、`tests/test_oracle.py`、`tests/test_search.py`、`scripts/validate_stage2.py`。先独立运行 Oracle 的 4 项测试。随后在加入剪枝前，用静态与时变 3×3 各一例核对 reference，每例穷举 96 条完整路径，J 的绝对误差均为 0。

| 命令（解释器及项目目录见 README） | 最终结果 |
| --- | --- |
| `& $PY -m pytest -q tests/test_oracle.py tests/test_search.py` | 16 passed in 0.49s |
| `& $PY -m pytest -q` | 57 passed in 10.05s |
| `& $PY scripts/validate_stage2.py` | 8 例 × 3 种求解，最大 Oracle 误差 0，最大重放误差 0 |

静态与局部时变模型各覆盖 2×2、3×3、4×4。另有前缀碰撞与 q=0 全部并列两例。独立按步数累积合法游走数量，逐例核对 DFS 叶子总计 1756 条。每条返回路径均通过阶段 1 的起点、预算、逐边合法性及评分检查。两种堆搜索的扩展数在本批相同，8 例的峰值 OPEN 均因上界剪枝而减小。静态 4×4 从 320 减至 124，动态 4×4 从 273 减至 105。

**状态合并回归。** 在 3×3 静态例中，两条路径在第 4 步同达格 6。前缀 0→1→0→3→6 的 g=74/29，最后访问格 7 可得 J=76/29。前缀 0→3→6→7→6 的 g=72/29，余下一步最小只能达到 J=84/29。Oracle 找到唯一最优路径，两个堆版本均命中。另有一步案例验证即使新终点只改善约 4e-13，也会取代先生成的终点。

**运行问题与产物。** 直接启动指定 python.exe 时，Matplotlib 柱状图在加载 Windows 原生库时异常退出。优先设置该环境的 Library/bin 后，整条验收命令与绘图通过，无需变动依赖。逐例耗时、路径与扩展数见 `outputs/metrics/stage2_comparison.csv`；JSON 同名文件另存固定输入（含时变矩阵）；队列图见 `outputs/figures/stage2_peak_open.png`。测试原始输出位于 `outputs/logs/stage2_pytest.txt` 和 `stage2_regression.txt`。阶段 3 尚待实现 mass_lb、paper_greedy 和动态反例回归；本轮数值证据仅针对 h=0。

## 阶段 3 验收记录

新增 `src/asar_repro/heuristic.py`、`scripts/generate_stage3_fixture.py`、`scripts/validate_stage3.py`、`tests/test_heuristic.py`、`tests/test_heuristic_counterexample.py`。修改 `src/asar_repro/search.py` 以加权 f 入队并按 incumbent 剪枝；`search_zero` 仍使用原顺序。修改 `src/asar_repro/oracle.py` 支持固定前缀的独立穷举。算法与检验只调用离散目标模型。

| 运行命令 | 本轮结果 |
| --- | --- |
| `& $PY scripts/generate_stage3_fixture.py` | seed=5，首次见证是从 0 起算的第 35 轮 |
| `& $PY -m pytest -q tests/test_heuristic.py tests/test_heuristic_counterexample.py` | 27 passed in 0.45s |
| `& $PY -m pytest -q --ignore=tests/test_smoke.py` | 83 passed in 0.77s，涵盖离散模型全部回归；阶段 0 的 Leeway 检查排除在本轮范围外 |
| `& $PY scripts/validate_stage3.py` | 5 个 toy、497 个合法前缀（含终点）、45 次加权搜索 |

两个静态 toy 和三个时变 toy 均穷举所有合法前缀。zero 和 mass_lb 各自得到 0 次超界；对应的 30 次加权搜索在 ε∈{1,1.02,1.1} 均满足实例 ε 界。paper_greedy 在两个时变例中各有一个前缀高估。诊断模式同样各有一次高估。所有返回路径与统一评分器重放一致。

**附录 B。** 固定 NPZ 存有 p、四个逐行转移矩阵、q、T、起点、seed 和 trial。以中心格 4 起步，放宽贪心依次选 3→0→5→2；DFS 穷举 96 条完整路径，最优为 4→1→0→3→4。根节点 h=2.617080177089，高于真实余下代价 2.541733337875，差 0.075346839214。该例的加权搜索仍返回最优解。

**另一个本地反例。** 专门选取的 seed=213、2×2 时变 toy 使用一般稠密运动核。在 ε=1 时，paper_greedy 返回 0→1→0→1→3，J=2.197771238745；Oracle 返回 0→2→0→1→3，J=2.185746589095。该例是补充回归，未用于估算失败频率。

**输出。** `outputs/metrics/heuristic_validity_report.json` 含保证分类、逐前缀精确值与估计值、epsilon 实测、路径、抽样的入队/出队/剪枝事件及 fixture SHA-256。`outputs/metrics/stage3_search.csv` 含扩展数、生成数、剪枝数、OPEN 峰值与带跟踪的单次求解耗时。图见 `outputs/figures/stage3_counterexample.png`；测试输出见 `outputs/logs/stage3_pytest.txt` 和 `stage3_regression.txt`。阶段 4 的 Fig. 2 风格轨迹热力图和同场景基线对照尚待指令。

## 阶段 4 验收记录

**按论文思想重建。** 论文未公开 Fig. 2 的原始 toy 先验。使用两套 YAML、同一初始分布、7×7 网格与 30 步预算；动态输入是本地新增算例。每个场景内三种方法共享起点、传感器和运动模型，均交给阶段 1 评分器重放。图和 CSV 的 J 单位为步。

| 场景 | 方法 | J | Pd(T) |
| --- | --- | ---: | ---: |
| 静态 | A^SAR | 11.677709 | 0.926559 |
| 静态 | 邻居贪心 | 12.835742 | 0.922128 |
| 静态 | 动态蛇形 | 17.636671 | 0.615296 |
| 动态 | A^SAR | 17.517819 | 0.669565 |
| 动态 | 邻居贪心 | 18.106678 | 0.659386 |
| 动态 | 动态蛇形 | 22.186335 | 0.412062 |

**顺序实验。** 访问次数、最终信念和最终发现概率相同。先东后北的 J 为 21.568613，先北后东为 21.764661，两者 Pd(T) 均为 0.600040。图上各时刻的 M 直接来自评分器；与第 12 步后重合的两条曲线对应的逐格信念也核验一致。

**代码与数据。** 新增 `src/asar_repro/toy.py`、`src/asar_repro/visualize.py`、`scripts/run_toy.py` 和 `tests/test_toy.py`。统一评分器 `objective.py` 增加可选的逐步信念记录。两套 YAML 位于 configs/；pyproject 新增 toy 可选依赖声明。输出 3 张 PNG、3 份 CSV 和 1 份 JSON，入口及文件说明见 README。CSV 分别含 6 条方案汇总、186 条方案时刻记录、62 条顺序实验时刻记录。JSON 保存全部初始矩阵和绘图帧。

**验收。** `& $PY -m pytest -q tests/test_toy.py` 得到 8 passed in 2.26s；`& $PY -m pytest -q --ignore=tests/test_smoke.py` 得到 91 passed in 3.08s。已检查 30 步路径的四连通性、逐帧质量与 J、动态边界守恒和第 16 步转移切换。两次独立进程在相同环境中生成的 7 个输出文件逐字节一致，并已回读 CSV 与 JSON 核对图中质量、路线和总分。日志保存在 outputs/logs/stage4_pytest.txt、stage4_regression.txt。

**适用范围。** 两个 30 步问题均超出 toy Oracle 的穷举预算，此处报告实测路径分数。paper_greedy 的理论认证标记为 false。阶段 5 的 Leeway 常量风流、轨迹预计算与网格化尚待指令。

## 阶段 5 验收记录

**本地兼容性。** 在既有 Python 3.11.18 / OpenDrift 1.14.12 上，指南的 500 粒子 PIW-1 两小时示例首先因自动陆海掩膜导致首步无活动粒子而停止。显式常量水面、关闭自动掩膜与播种移位后，原版时区写法在 xarray 最终切片触发 tz-naive / tz-aware 错误。输入先换算 UTC，仅在 Leeway 调用处去除 tzinfo，修订后得到 121 个 UTC 时刻，原生维度为 (trajectory, time)，返回值即 o.result。三次执行日志分别为 stage5_guide_smoke.txt、stage5_constant_smoke.txt、stage5_smoke_pass.txt。

**正式输入。** 读取安装包对象表，解析 PIW-2 为编号 2。预漂移自 14:45Z 至 15:45Z；137 个原生时刻覆盖到 15:53Z，重采样到 CST 起的 50 帧，末帧 15:52:33.740Z。34,000 个留出位置使用 60 s 间隔端点插值，与真实 30 s 源帧比较，RMS 0.2642 m，P95 0.3713 m，最大 0.5221 m。该检验以同一模拟轨迹为参照。

**审计。** 50 帧 × 500 个 ID 均参与逐步质量检查，最大绝对残差 4.44e−16。末帧固定审计路线的 M=0.9111072336064，累计移除质量 0.0888927663936。在相同 CST 粒子云上用 1 格小窗复查，格内 0.012、域外 0.988。合成全水主例的陆地质量为 0；独立构造的回归覆盖活动陆地、搁浅后空记录、其他失活、位置缺测、活动粒子域外重入，并检验等价置换运动中粒子法和阶段 1 矩阵评分逐步一致。

**交付代码。** 新增 src/asar_repro/opendrift_adapter.py、src/asar_repro/gridding.py、scripts/generate_drift.py、tests/test_opendrift_adapter.py 和 configs/lake_ontario_constant.yaml。产物与字段说明见 README。使用指定解释器运行 `-m pytest -q tests/test_opendrift_adapter.py` 得到 5 passed，`-m pytest -q` 得到 97 passed。原始输出在 outputs/logs/stage5_pytest.txt 与 stage5_regression.txt。

**复跑。** 以相同配置在另一进程的临时输出目录重跑，Python 网络连接与解析调用均被阻断。NPZ 18 个字段逐项完全一致，CSV、JSON、PNG 逐字节一致，且从归档权重与 cell_ids 成功重建全部 50 行账目。见 outputs/logs/stage5_replay.txt。阶段 6 的粒子权重搜索分支、Oracle 对照与性能评估仍待指令。

## 阶段 6 验收记录

新增 scripts/benchmark_particles.py、tests/test_particle_search.py、configs/stage6_particle_search.yaml。修改 motion.py、search.py、heuristic.py、objective.py、oracle.py、grid.py 和 pyproject.toml。矩阵与粒子共用一个搜索循环、Algorithm 2 和路径评分器。阶段 5 NPZ 以只读方式加载；搜索进程结束前检查 OpenDrift 未被导入。

**先做小 N。** 2×2、8 粒子、4 步确定性时变置换是两种运动表示等价的算例。独立 DFS 在两种表示下各穷举 16 条路径，均得到 J=1.875，代表路径为 (0,2,3,1,3)，并列集合一致。对 zero、mass_lb、paper_greedy 和两个 ε 做逐例比较；另测同格分流、特殊格重入、父分支保护和三类预算中止。阶段 6 单测 14 项通过。复跑离散与归档回归：

```powershell
& $PY -m pytest -q tests/test_particle_search.py
& $PY -m pytest -q --ignore=tests/test_smoke.py -k 'not test_guide_smoke_corrected_local_api'
```

第二条得到 109 passed，排除了阶段 0/5 的 Leeway smoke，未重新启动漂移。

**500 粒子扫描。** 8 个 ε 使用同一归档、CST 时钟和初始横扫上界。每次最多 12000 次扩展、15000 个 OPEN 节点、15 秒。前 4 个设置完成；后 4 个均因 max_open 停止，初始上界仍是已知最佳完整路径，J=45.886528，Pd=0.088893。时间超限 0 次。8 条返回路径均有 49 条四邻边，独立掩膜重放误差小于 1e-10，并用阶段 5 的 particle_step 逐步核对 M 与 Pd。各 ε 的 J、Pd、运行时间、扩展和进程峰值工作集按原始精度保存在 stage6_epsilon.csv。阶段 3 的动态可采纳性限制继续适用。

**性能。** 初步 ε=1.10 profile 定位到 Algorithm 2 的未来步循环（含可达集合构造），因此复用每个出发格不同半径的候选格数组。最后独立 profile 的搜索累计 0.172 s，其中 Heuristic.__call__ 累计 0.167 s。证据保存在 outputs/logs/stage6_profile.txt，profile 单独计量。阶段 7 的四场景复原与同数据基线对比尚待指令。

## 阶段 7 · Table I 任务与动态基线

先复用 Lake Ontario 的归档并核对阶段 6 的 SHA-256，再依次预处理 Bay of Fundy、Salish Sea、Arctic Ocean。每组按照独立步长和绝对 UTC 对齐 500 个粒子。每个冻结输入运行 1 个动态 PT、8 个 ASAR_paper 和 100 个 ACO_inspired。共 436 条路径、22781 个含 CST 的时刻样本，直接按 ID 掩膜重放的最大绝对误差为 8.53e-14。

本阶段新增 `src/asar_repro/scenarios.py`、`src/asar_repro/scenario_baselines.py`、`scripts/run_stage7.py`、`scripts/report_stage7.py`、`configs/stage7_scenarios.yaml`、`tests/test_stage7.py` 与阶段说明。脚本继续调用阶段 5 的 Leeway 适配器和阶段 6 的搜索与评分器。

预算中止测试的首个均匀先验算例在根处已被 PT 上界剪枝，正常结束。改用非均匀质量后，测试可稳定触发零扩展预算并核对返回路径。全量测试包括 Leeway smoke，在 maritime-sar 下执行 `python -m pytest -q` 得到 121 passed。[测试记录](../outputs/logs/stage7_regression.txt)

实测 32 次 A^SAR 中 15 次正常结束，17 次达到扩展上限。可用性、来源和局限逐场景列在[偏差表](../outputs/stage7/deviations.csv)。[复跑命令与基线定义](stage7_scenarios.md)

## 阶段 8 · 最终报告与独立 adapter

核对本地论文 v2 第 7 页 Table I、II 和第 2、6 页图注。四个任务、32 个原文 C++ 时间值均与阶段 7 的表格记录一致。把 PDF 转录独立保存为 `data/fixtures/paper_tables_v2.json`，用于检测配置或原始引用计时发生变化。目录中无 Git 元数据，各阶段均无可核实的 commit。

**交付代码。** `scripts/stage8_metrics.py` 整理阶段 1–7 原始记录并核验输入指纹与路径；`scripts/build_report.py` 生成两个 Markdown、summary.csv、性能对比图和带 SHA-256 的粒子包。`src/asar_repro/planner_adapter.py` 提供数组入口和离线归档入口，`src/asar_repro/cli.py` 增加 plan 与 report 子命令。阶段 3 的 toy 加载器允许显式指定 fixture，原有默认值保留。同步更新 README、模型假设和可选依赖声明。

**复核过程。** Windows 私有临时目录生成的文件在移动后会携带私有访问权限。发布步骤改为在最终目录新建同级临时文件后替换，确认报告与 PNG 继承工作区目录权限。落盘的配置、时间、路径与评分可离线读取。重复生成文档使用历史实验计时。

**验收。** 在同一 maritime-sar 解释器下执行以下命令。专项 9 项通过，全量 130 项通过。另以不加载 OpenDrift 的进程分别重跑四个场景的 ε=1.10，原始格号路径和 M 序列逐项一致，J、Pd(T) 与历史记录一致；实际调用输出含 UTC 与经纬度。专项测试另覆盖有、无可行初始解的计算预算中止。

```powershell
& $PY -m asar_repro.cli report --results outputs/metrics
& $PY -m pytest -q tests/test_stage8.py
& $PY -m pytest -q
& $PY -m asar_repro.cli plan --scenario lake_ontario --epsilon 1.10
```

[测试输出](../outputs/logs/stage8_regression.txt) · [四场景 adapter 核验](../outputs/logs/stage8_adapter_replay.json) · [最终报告](final_reproduction_report.md) · [论文对照](paper_comparison.md)

阶段 0–8 的交付范围至此完成。历史 forcing、作者的手工 PT、原版 ACO、宿主系统内的实际航迹与返航评估仍各有独立的数据或工程前提。
