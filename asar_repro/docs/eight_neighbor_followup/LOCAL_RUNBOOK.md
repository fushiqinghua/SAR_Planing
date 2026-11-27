# 本地执行说明：八邻接加速与同 forcing 预留实例

分支：`eight-neighbor-physical-study-20261127`  
本批基点：`97dd989a488da8604b97fd287162e1b625310501`  
交付状态：**`prepared_not_run`。本批只完成源码、配置、测试与文档准备和静态检查；没有安装依赖、运行 pytest、执行前缀审计、生成粒子或运行搜索。**

先读 [设计依据](REVIEW_R1.md)、[实验计划](PLAN.md) 和 [判断门槛](DECISIONS.md)。本说明的命令由你在本地逐条运行；没有自动串联到 H1 的一键脚本。

## 1. 更新现有分支与环境

以下在仓库根目录执行。先保存你自己的未提交工作；不要覆盖或重置已有结果。

```bash
git fetch origin
git switch eight-neighbor-physical-study-20261127
git pull --ff-only origin eight-neighbor-physical-study-20261127
cd asar_repro
```

若本地尚未建立该分支，用 `git switch --track origin/eight-neighbor-physical-study-20261127` 替代上面的 switch。需要完整 Git checkout，不能只下载 ZIP；原代码保护需要读取基点 Git blobs。

沿用上次的 `maritime-sar` 环境、Python 3.11+ 以及相同机器。所需搜索与测试依赖见 [requirements-physical-followup.txt](../../requirements-physical-followup.txt)。本批还需要能实际导入原历史漂移流程的 OpenDrift、xarray、PyYAML、netCDF4 和 Shapely 2+。保留已经验证的环境；缺包应在本地冻结之前恢复。执行器不安装或升级软件。

`preflight` 会记录软件版本、线程环境和机器信息，检查生成依赖能否导入；不会初始化漂移模型或生成粒子。已有自定义 GRIB 解码器继续使用，不要求因为本批而改换 reader。cfgrib/ecCodes 等若已安装会记录版本，不把缺少未使用的 reader 当作必须换环境的理由。

五项数值线程环境固定为 1。正式任务串行、新进程执行。运行期间避免并行负载和休眠；不要同时启动两个指向同一输出目录的执行器。

## 2. 恢复现有原始 forcing

Git 中有来源清单和旧审计记录，**没有原始 forcing 二进制包**。准备以下已经审计过的本地目录：

- `data/raw/historical/ASAR_B1_LakeOntario_20250826/`
- `data/raw/historical/ASAR_B1_HudsonsBay_20250829/`

精确文件名和 SHA 以两份已有清单为准：

- [historical_sources.json](../../data/manifests/historical_sources.json)
- [historical_sources_additional_b1.json](../../data/manifests/historical_sources_additional_b1.json)

检查实际解包层级，不要额外多套一层文件夹。目录名不是时间覆盖证明：Lake 的已有共同包络为 2025-08-26 13:00–17:00 UTC，Hudson 为 2025-08-28 21:00–2025-08-30 03:00 UTC；原生积分尾帧也必须在覆盖内。

缺包、哈希变化或包络不足会明确阻断。恢复既有输入后重做 preflight；不改源、不补零、不改变 seed、不用其他天气包替代。若无法恢复，上传阻断证据后结束本次尝试。

## 3. P0：预检、测试、开发冻结和配对审计

以下命令均在 `asar_repro` 目录执行，Windows PowerShell 与 Linux/macOS 可逐行使用。输出目录固定使用本批下的新子目录：

`outputs/eight_neighbor_followup_20261127/local_r1`

```bash
python scripts/run_eight_neighbor_followup.py plan
python scripts/run_eight_neighbor_followup.py preflight --out outputs/eight_neighbor_followup_20261127/local_r1
python scripts/run_eight_neighbor_followup.py validate --out outputs/eight_neighbor_followup_20261127/local_r1
python scripts/run_eight_neighbor_followup.py freeze-dev --out outputs/eight_neighbor_followup_20261127/local_r1
python scripts/run_eight_neighbor_followup.py audit --out outputs/eight_neighbor_followup_20261127/local_r1
```

各步含义：

1. `plan` 只打印固定矩阵和预算，不搜索、不生成漂移。
2. `preflight` 检查原代码、原档案、forcing 文件和生成依赖；按原流程重放现有 PT/reference 做评分桥接，不生成 H1 档案。
3. `validate` 实际运行配置列出的 **8 个测试文件**，保存 stdout/stderr、JUnit 和版本身份。需要测试数非零、无失败／错误／跳过，且运行前后源码环境不变。
4. `freeze-dev` 锁定同一源码、配置、环境、预检与测试证据，以及 P0、D5、S30、H30 全部任务身份。此时 H30 的后端位置只是 `selected`，必须待 D5 按规则决定。
5. `audit` 对两个开发档案 × 两种覆盖 × 两种邻接做 **8 项原／缓存配对前缀审计**。每项最多 128 次展开、30 秒，使用同一个确定性搜索 heap 逐前缀严格比较。审计有独立进程和资源记录，不是性能实验。

达到 128 次展开或完整耗尽 frontier 才能通过；超时和差异都不是通过。P0 未完整有效通过，D5 会被阻断。上一批的 120 项通过成绩不能替代本批验证。

冻结之后不编辑源码、配置或设计文档，不换环境。需要修复时保留旧输出目录，明确记录修改，在新目录重新验证与冻结。实验矩阵或门槛调整还需要明确注册新的批次版本；不能只改 JSON 继续原批次。

## 4. D5：有限开发对照，然后锁定后端

```bash
python scripts/run_eight_neighbor_followup.py run --stage D5 --out outputs/eight_neighbor_followup_20261127/local_r1
python scripts/run_eight_neighbor_followup.py select-backend --out outputs/eight_neighbor_followup_20261127/local_r1
```

D5 为 **48 项，每项 5 秒**：两个现有档案 × 两种覆盖 × 四／八邻接 × 原／缓存后端 × 三次计时重复。都从上一批同一条历史强路线起步；复制、重新评分、缓存构建、搜索和候选完整重放计入预算。

选择规则已写入配置：八组中位 J 都不退化，三个目标组命中数不减少，并且至少一个目标组命中次数严格增加，或者至少两个目标组双方都 3/3 命中且目标时间中位数至少缩短 10%。未命中按右删失记录，不填成恰好 5 秒来计算提速。

`selection.json` 一经生成即锁定，并绑定完整 P0/D5 证据：

- `cached`：通过本批加速采用条件。
- `original`：正确完整，但加速采用条件未达到；仍继续 H1，研究八邻接模型迁移。
- 缺失、失败、等价性不通过：不生成可用选择，停止定位原因。

**必须先选择后端，再准备新粒子。** 执行器拒绝在新输入已存在后首次生成 selection。不要根据 H1 数据、质量或航迹修改后端、seed、阈值和实例。

## 5. 显式准备四份 H1 档案

```bash
python scripts/run_eight_neighbor_followup.py prepare-inputs --out outputs/eight_neighbor_followup_20261127/local_r1
```

这是本批唯一启动四例新漂移生成的命令。四例参数已在 [配置](../../configs/eight_neighbor_followup.json) 注册：Lake 时间窗 ±1 小时、seed 1041/1042；Hudson 时间窗 ±2 小时、seed 2041/2042。事故和搜索开始时刻一起平移，保留原规划前漂移时长、空间位置、网格、500 粒子、漂移物类型、时间步、q 和预算。

每例保存 `request.json`、`input_validation.json`、`source_fingerprints.json`、`particles.npz`、`mass_audit.json`、`forcing_validation.json`、`metadata.json`、`prepare.log`、`manifest.json`。失败另留 `failure.json`，不发布成功 manifest，也不覆盖旧目录。

四例全部准备后生成 `prepared_inputs.json`。有较大 outside/unknown/inactive/land 质量，甚至没有 searchable 粒子，但结构和质量守恒有效的实例仍保留；不能因为效果差而换 seed、重新居中或移除实例。

数据层级始终是 **`same_forcing_shifted_window_new_seed`**。这些是同一 forcing 条件下的新任务／新轨迹实现，不是独立天气、日期、季节或海区验证。时段和 seed 同时变化，也不能分离两者各自效应。

漂移生成、原始 forcing 读取和哈希检查不计入后面的 1800 算法秒，可能占据明显运行时间。日志和 `generation_wall_s` 单列保存，不预先承诺总运行时长。

## 6. S30：四份共同初始路线，然后冻结 H1

```bash
python scripts/run_eight_neighbor_followup.py run --stage S30 --out outputs/eight_neighbor_followup_20261127/local_r1
python scripts/run_eight_neighbor_followup.py freeze-holdout --out outputs/eight_neighbor_followup_20261127/local_r1
```

S30 为 **4 项，每份新档案 30 秒**。先生成合法 PT，用原离散评分与 axis 物理评分核对 J/Pd；剩余时间交给原 `paper_greedy` 搜索（epsilon=1.04、max_open=100000），并保留 0.25 秒的最终核验预留。paper 候选仍需在同一总 30 秒内完成原评分与物理重放、通过 J/Pd 桥接，才能成为共同初始路线。预留不是时间保证，越界候选记录在 `late_candidates`，继续使用预算内可用的 PT。

两种覆盖和四／八邻接共享同一份初始路径，不按分支分别挑选。S30 另存两种覆盖下的重放、离散／物理桥接数值和生成成本。共同路线生成成本统一从 H30 算法计时中剥离并单列，H30 仍计入复制与重新评分成本。

`freeze-holdout` 要求四份档案与四条初始化路线全部有效，锁定 selection、输入、初始化证据与 H30 任务。不会自动启动 H30。

## 7. H30：预留实例的四／八邻接对照

```bash
python scripts/run_eight_neighbor_followup.py run --stage H30 --out outputs/eight_neighbor_followup_20261127/local_r1
python scripts/run_eight_neighbor_followup.py summarize --out outputs/eight_neighbor_followup_20261127/local_r1
```

H30 为 **48 项，各 30 秒**：四例 × 两种覆盖 × 四／八邻接 × 三次重复，只用 selection 固定的一个后端。三次重复用于观察计时波动；统计实例数是四，不是十二个独立海况。

判定使用每例三次 J 的中位数：主覆盖四例均不退化，至少两例改善 ≥0.5%；主赢家中至少一例 axis 仍有正改善，全部 axis 退化不超过 0.5%。赢家只出现在一个场景时明确标记场景限定信号。完整规则及阈值见 [DECISIONS.md](DECISIONS.md)。

## 8. 成本、结果文件和失败处理

| 阶段 | 数量 | 算法预算合计 |
|---|---:|---:|
| D5 | 48 × 5 秒 | 240 秒 |
| S30 | 4 × 30 秒 | 120 秒 |
| H30 | 48 × 30 秒 | 1440 秒 |
| 正式合计 | **100 项** | **1800 秒，30 分钟** |
| P0 配对审计 | 8 × 最多 30 秒 | 另计，最多 240 秒 |
| 测试、forcing、漂移生成、读取、进程、审计与 I/O | 单列 | 不包含在上述预算中 |

每个正式任务在新进程中串行执行；RSS 上限 2 GiB，进程 watchdog 为任务算法预算 +15 秒。watchdog 余量用于启动与外部核验，不让预算外候选成为正式成绩。搜索可能因 frontier/max_open 提前结束；不能把不同工作量的 wall 当作纯速度比。

输出入口：

- `REPORT.md`：阶段完整性和分组表。
- `summary.json`：完整性、D5 选择条件、H1 门槛与状态。
- `comparison.csv`：每一个计划任务，包括缺失或失败，不只保留成功行。
- `runs/<id>/result.json`、`record.json`、`stdout.log`、`stderr.log`：原始路径、history、预算核验、缓存和资源记录。
- `protocol.json`、`selection.json`、`prepared_inputs.json`、`holdout_protocol.json`：分阶段冻结链。

成功且哈希一致的任务可由同一命令跳过并继续；失败或不完整目录保留且拒绝覆盖。先保存日志，定位原因；不能手工删除失败后继续当作原来的完整批次。修复后使用新的输出子目录，并在分析里引用失败目录和修复提交。参数保持固定，不能因负结果追加候选、挑 seed 或扩大预算。

## 9. 回传和后续安排

复制 [RESULTS_TEMPLATE.md](RESULTS_TEMPLATE.md) 到本批输出目录，填写为 `ANALYSIS.md`，保留 J、Pd、达到目标时间、缓存统计、初始化成本、逐例正负结果与失败记录。不修改已冻结的设计文档。表格里未记录的字段填 unknown，未运行填 not_run。

在仓库根目录检查待提交范围，再提交该输出目录：

```bash
git status --short
git add asar_repro/outputs/eight_neighbor_followup_20261127/local_r1
git diff --cached --stat
git commit -m "results: eight-neighbor acceleration and within-forcing holdouts"
git push origin eight-neighbor-physical-study-20261127
```

原始 forcing 无需加入 Git；新生成的四份 NPZ、metadata、manifest 和日志属于本批证据，应随输出目录一起回传。若有失败目录，也纳入结果说明和对应提交。

后续按本批证据推进：D5 失败就结束这轮缓存开发，保留原后端；H1 若只支持 Lake 或 Hudson，先解释场景条件；两场景都有信号才另行设计使用新 forcing 的 H2。H1 未过则保留负结果、结束有限批次。**H2、300 秒、Fundy、任意角度和新 STDC 机制均未启用。**
