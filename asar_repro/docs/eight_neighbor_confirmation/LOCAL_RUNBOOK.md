# 本地执行说明：八邻接确认批

分支：`eight-neighbor-physical-study-20261127`  
参考结果提交：`b3ca640de25c1d5b9d1a7449b5ed6053d9e3f3f1`  
交付状态：**`prepared_not_run`。只有源码、配置、测试、文档与静态核查；测试、正式求解和评分回放均由你本地执行。**

先阅读 [PLAN.md](PLAN.md)、[DECISIONS.md](DECISIONS.md) 和 [REVIEW_R2.md](REVIEW_R2.md)。本批复用已上传的四份粒子档案，不重新生成 OpenDrift 数据，也不下载新 forcing。H2 的新日期工作见 [H2_PREREGISTRATION.md](H2_PREREGISTRATION.md)，不在下列执行命令中。

## 1. 更新分支

在仓库根目录执行，保留自己的未提交工作和旧结果，不重置或覆盖：

```bash
git fetch origin
git switch eight-neighbor-physical-study-20261127
git pull --ff-only origin eight-neighbor-physical-study-20261127
cd asar_repro
```

若本地尚未创建该分支，用 `git switch --track origin/eight-neighbor-physical-study-20261127` 替代 switch。使用完整 Git checkout，以便冻结参考代码和读取旧结果身份。

沿用上一批已验证的 Python 环境与机器，不为本批升级依赖。执行器记录环境并校验已有依赖；它不安装软件。若缺少依赖，先恢复本地环境，之后才进入验证与冻结。正式任务串行、新进程执行，数值线程数固定为1；运行期间避免同时启动另一个批次或使机器休眠。

## 2. 输入与共同参考

需要保留完整目录：

`outputs/eight_neighbor_followup_20261127/local_r1/`

其中包括四份 `inputs/<case>/particles.npz`、输入 manifest／元数据、旧 H30 `result.json`／`record.json` 及冻结来源。此批不要求重做漂移或重新恢复用于生成它们的原始 forcing 包；来源仍由已上传清单追踪。缺少某份粒子档案时先恢复原字节文件，不改变 seed、不生成替代档案。

旧输入和结果按原始字节SHA核对。Windows生成文件中可能保留CRLF；Git检出、编辑器或下载工具改换行后，即使JSON数值看起来相同，仍可能不再是被绑定的文件。发生这种阻断时应从固定提交恢复对应Git blob的原始字节，不手工改manifest里的哈希、不批量改旧结果换行，也不把校验关掉。新 `reference_manifest.json` 的预注册身份采用规范JSON对象哈希，避免仅因本地换行而改变语义身份；冻结后本地源码／文档仍有文件字节指纹，不允许运行中修改。上述处理不能替代旧证据原字节核验。

共同初始路线来自配置所指定的旧 H30 repetition 0 四邻接最终路线。输入身份、参考结果、路径和原评分在 `preflight` 检查并在 `freeze` 绑定。不要手工把其他运行的最佳路径替换进去。

新输出目录固定为：

`outputs/eight_neighbor_confirmation_20261127/local_r1`

旧 `eight_neighbor_followup_20261127` 目录作为输入证据，只读使用。新批结果不写回旧批目录。

## 3. 查看矩阵、预检、实际测试和冻结

以下命令均在 `asar_repro` 内逐行运行，Windows PowerShell、Linux 或 macOS 均可使用：

```bash
python scripts/run_eight_neighbor_confirmation.py plan
python scripts/run_eight_neighbor_confirmation.py preflight --out outputs/eight_neighbor_confirmation_20261127/local_r1
python scripts/run_eight_neighbor_confirmation.py validate --out outputs/eight_neighbor_confirmation_20261127/local_r1
python scripts/run_eight_neighbor_confirmation.py freeze --out outputs/eight_neighbor_confirmation_20261127/local_r1
```

`plan` 只展示固定任务、预算与状态，不求解。`preflight` 核对旧输入和参考结果、依赖、源码及环境，不生成新粒子。`validate` 实际运行配置指定的测试，保留 stdout、stderr 和 JUnit；只有测试非空、无失败／错误／跳过，且环境和源码未变化，才可冻结。

`freeze` 锁定本批源码、配置、环境、旧输入和共同路线证据及全部任务身份。此后不要改算法、参数、文档、输入或依赖版本。需要修复时保留失败目录，完成修复后使用新的输出子目录重新验证和冻结；参数或研究问题改变时还需明确注册新批次，不能只换输出目录继续调参。

上一批的253项测试和当前静态解析不替代本批本地实际测试。执行器不会把缺少验证当成可跳过的警告。

## 4. 按固定顺序执行四个阶段

```bash
python scripts/run_eight_neighbor_confirmation.py run --stage D5 --out outputs/eight_neighbor_confirmation_20261127/local_r1
python scripts/run_eight_neighbor_confirmation.py run --stage D30 --out outputs/eight_neighbor_confirmation_20261127/local_r1
python scripts/run_eight_neighbor_confirmation.py run --stage G30 --out outputs/eight_neighbor_confirmation_20261127/local_r1
python scripts/run_eight_neighbor_confirmation.py run --stage R120 --out outputs/eight_neighbor_confirmation_20261127/local_r1
python scripts/run_eight_neighbor_confirmation.py analyze --out outputs/eight_neighbor_confirmation_20261127/local_r1
```

阶段说明：

| 阶段 | 目的 | 任务／预算 |
|---|---|---:|
| D5 | 两个问题实例的低延迟与目标命中诊断 | 24×5秒 |
| D30 | 固定补全候选与诊断缓存控制的主比较 | 72×30秒 |
| G30 | Lake late最终Pd保护与J收益的取舍 | 12×30秒 |
| R120 | Hudson early对称延长预算的质量参考 | 4×120秒 |

每阶段独立从共同参考重新起步，不继承上一阶段内存、缓存或候选路线。D5未达到目标不意味着跳过D30；候选未胜出不意味着删去G30或R120。若正确性、输入或记录失效，则先停止处理证据问题。

算法预算合计3120秒，即52分钟。测试、输入读取、哈希核查、进程启动、外部审计和I/O另计；这是预算合计，不是总墙钟时间保证。正常提前达到OPEN或archive资源限制可能缩短单次求解，但必须保存原因。

完整路线构建、诊断、缓存、候选归档和原评分重放都在每次算法预算内。进程watchdog另给60秒输入加载、独立评分核验、进程启动／清理与I/O余量，RSS上限仍2GiB；这60秒不增加求解预算，不能用于接纳预算外候选。外层记录时钟差并再次筛除越界候选。资源上限、线程和固定任务顺序以配置为准。

## 5. 失败、恢复与证据保留

已完成且文件哈希仍一致的任务可以由同一命令跳过并继续。失败、不完整或身份不一致的运行目录必须保留；不能删除失败后重新跑到满意结果再声称本次完整无失败。

如发生输入缺失或下载字节变化，恢复配置绑定的旧文件。若发生算法错误，保存失败日志和提交身份，修复后新目录重新验证。没有自动换seed、增加预算、调整补全频率或改变Pd门槛的恢复路径。

不要同时运行两个指向同一个输出目录的执行器。不要手工编辑 `protocol.json`、任务JSON、result或record来绕过冻结；这些内容是回传后核验的一部分。

## 6. 汇总时重点查看什么

自动输出为 `REPORT.md`、`summary.json`、`comparison.csv` 及逐次 `runs/`。每次阶段完成也会更新自动汇总；在四阶段尚未全部完成时，总批状态显示未完整是预期情况，须结合各阶段的missing/errors区分待执行与真实失败。用户填写的 `ANALYSIS.md` 不由自动汇总覆盖。

先看各阶段任务是否完整有效，再查看方法采用、图收益和Pd保护的不同判定。报告中应能定位下列内容：

- 每个任务的 J、Pd、路径、预算内history、迟到候选、停止原因与费用。
- D30 12组方法质量比较，四个主实例的四／八图比较，两组axis负例与正例。
- 两个D5目标的命中数和首次达到时刻；未命中按右删失保留。
- G30 是否仅返回初始参考，或满足Pd同时保留至少0.5%的J改善。
- Hudson early首个新终点与完整重放时间、深度／tick分布、R120是否因OPEN提前停止。
- 共享初始化的旧来源与成本边界；本轮所有候选开销均计时。

对比J和Pd时必须使用同一条路线。不要从一条路线取最好J、另一条路线取最好Pd后拼成一个结果。归档只包含访问过的完整候选，不代表全局最优Pareto集合。

## 7. 回传

将 [RESULTS_TEMPLATE.md](RESULTS_TEMPLATE.md) 复制到本批输出目录并填写为 `ANALYSIS.md`。未记录填unknown，未命中填not_reached；不要写猜测值。保留自动汇总和原始记录，即使候选未采用或只有安全回退。

回传新输出目录内的 protocol、验证证据、任务与运行记录、汇总、分析、日志和失败证据。旧输入已经在分支中，不重复生成。新forcing原始二进制数据不属于本批提交内容。

在检查暂存内容后仅提交本批结果：

```bash
git add outputs/eight_neighbor_confirmation_20261127/local_r1
git diff --cached --stat
git commit -m "results: eight-neighbor confirmation and probability guard"
git push origin eight-neighbor-physical-study-20261127
```

以上Git命令仍在 `asar_repro` 内执行。不要顺手提交本地依赖、其他试验目录或未审核的大型原始forcing文件。结果推送后再统一评估下一步；H2不会随本批命令自动启动。
