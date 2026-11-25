# STDC 最后一批评估：冻结协议

本批目标是决定是否继续围绕 STDC 做性能研究，并将数学贡献与可运行优势分别判断。基于 `6167d344bd364b0a39a67d310a68e10f1e407851`，分支 `stdc-final-assessment-20261125`。机器可读参数以 `configs/stdc_final_assessment.json` 为准；正式运行前保存该文件、全部源代码、执行脚本、输入档案及环境的哈希到本批 `protocol.json`，后续运行逐项核对。

## 研究边界

固定原目标 `J = sum(M_t, t=1..T)`；t=0 不探测、四邻接、无等待、先漂移后探测，保留特殊格质量。`Pd` 必须来自同一条路线。原评分器、旧源代码和既有档案不变。本批只重放既有冻结粒子档案，不重新积分 OpenDrift；检查粒子及元数据哈希、UTC 时轴、稳定 ID、总质量及历史路线评分。原始风流场未在本机重新审计，继承来源证据不得写成新通过的全链路审计。

Lake Ontario 和 Hudsons Bay（仓库键 `arctic_ocean`）是主证据；Fundy 始终标记 `physical_direction_unverified=true`，不能单独触发投入决定。每景只有一套冻结 500 粒子输入；同一输入重复计时不是独立外推验证。本机 Linux / Python / SciPy 的计时另立表格，不与旧 Windows 计时作直接速度比。

## 有限实验清单

| 阶段 | 执行内容 | 总量与边界 | 解决的问题 |
|---|---|---|---|
| A | 三景输入复核、原路线重放、机制测试、独立小图 DFS 审计 | 冻结通过后才能计时 | 是否测的是同一个问题、下界是否正确 |
| B | 同一 `search_research`、fast guide、common PT，仅切换 zero / mass / STDC | 三景 × 1/5 秒 × 3 重复 × 3 方法；补每景每方法 5000 expansions 一次 | STDC 的增量质量、达到固定质量所需时间、下界计算成本 |
| C | MILP 冷启动、仅 warm start、仅 cutoff、两者同时 | Hudson，固定 prefix=20 / corridor=3，30 秒 × 2 重复 × 4 arm | warm 与 cutoff 是否单独有用；不扩展走廊与预算 |
| D | 最多 24 个从原起点出发的早期事件候选 | 每景 common PT 与历史最好路线各一次，最多 5 秒；一到两个硬事件 | 能否改变早期路线结构并找到真实改善 |
| E | 共享路线粒子对下界 | 每景根节点与历史路线 1/3、1/2、2/3 前缀；每节点最多 4 pair、12 秒、128 MiB managed buffers | 共同路线耦合能否收紧质量判断及其成本 |
| F | 通过筛选的方法进入独立档案验证 | 目前无新的独立真实档案；不以原数据重跑冒充 holdout | 是否值得扩大研究及结论能否外推 |

运行顺序按预先固定的种子与轮换规则交错；worker 串行、每次独立进程。保存实际 wall time、CPU time、进程峰值 RSS、计时截止超额、expanded/generated/pruned/peak OPEN、guide/bound 计时、完整 incumbent history 和最终原评分重放。进程启动与档案加载不计入算法预算，但另存整个 worker 的时间。共同初始 PT 是冻结输入，搜索函数内初始评分计时；因此时间结论是“已加载输入、给定共同 PT 后”的求解时间。

固定工作量是诊断表，不冒充公平时间对照。时间预算为合作式截止，超额不隐藏；RSS watchdog 2 GiB、超时额外宽限 20 秒。遇到非成功状态保存原因，不替换为最优或零耗时。

## 预先指定的投入门槛

这些是本项目本批的工程决策阈值，不是统计显著性声明。

1. **质量门槛：** 5 秒下，STDC 对最佳廉价界的中位数 J 相对改善至少 0.5%，至少出现在一个主场景，另一个主场景无超过 `1e-8` 的相对退化；通过后仍需独立档案确认。
2. **时间门槛：** 达到 `1.001 × 历史参考 J` 时，两个主场景中 STDC 的中位数时间都比 zero 和 mass 各快至少 20%，全部重复必须达到目标，最终 J 不退化。所有预设目标的未达结果按删失报告，不拿截止时间替代真实到达时间。
3. **事件机制门槛：** 原评分下任何主场景严格改善历史参考 J，才触发 event seed + mass continuation 的 5 秒、3 重复同预算验证。事件占用最多前 1 秒，全部成本计入 5 秒。仅改善 common PT 不足以触发。
   正式组合还须在一个主场景比 mass 同预算中位数改善至少 0.5%，另一主场景不退化，才建议进入独立档案验证。
4. **pair 门槛：** 根节点在主场景中关闭至少 10% 的原 `U-L` 区间，才建议后续探索搜索集成。少量 pair 的负结果只淘汰此构造与预算，不否认所有共同路线耦合方法。
5. **停止规则：** 本批不追加扫描、不延长 MILP、不增加候选数量。若质量和时间门槛均未满足，暂停以 STDC 性能调优为主线的投入，保留下界理论、正确实现和基线；事件或 pair 的独立信号按自己的证据评价。

## pair 的确定性节点与分组

节点固定为历史参考路径的 `floor(T × f)`，`f ∈ {0,1/3,1/2,2/3}`。每个节点只把未来所有绝对帧 `cell_ids` 完全相同的列进行精确聚合，对当前未探测权重求和而不归一化；保留原粒子 ID 映射。它只对这个节点的后缀等价，不许可跨历史合并。

从当前质量最高的至多 16 个组中，对每个 pair 计算 `(b_i+b_j) × 共同可搜索未来帧上的平均 Manhattan 距离`，按分数递减、组索引打破并列，贪心取最多四个互斥 pair。每个 pair 强制两粒子共用一条后缀；未选质量使用 STDC，最后 `max(full_STDC, sum(pair_bounds)+STDC(remainder))`。不能把 pair 增量直接加到全局 STDC。

## 数学与性能的声明标准

下界可采纳性、支配关系、严格例子、算法复杂度和实际运行速度分开陈述。现有 anytime search 超时时可能有未保存在 OPEN 中的在途状态，因此不把 OPEN 最小值当作全局质量证书。根节点有效界仍可给出 `L ≤ J* ≤ U` 的数值区间；普通浮点实现及小图验证不等于机器验证的区间算术证书。

下界更紧不会自动推出 wall time 更小；必须用 B 阶段的同框架对照回答。MILP dual 仅属固定 prefix/corridor 子问题；不能当作全局界。最终报告必须同时保留成功、无改善、预算中止和环境阻塞。

## 执行与恢复

在 `asar_repro` 目录，用提供 NumPy、SciPy、psutil、pytest 的 Python 环境运行。正式 worker 固定数值库线程为 1。先运行本批测试和独立理论审计，将 pytest.log、JUnit 和 theory_audit.json 保存到新输出目录的 `validation/`，再运行：

```bash
python scripts/run_stdc_final_assessment.py --stage freeze --output outputs/<new_batch>
python scripts/run_stdc_final_assessment.py --stage benchmark --output outputs/<new_batch>
python scripts/run_stdc_final_assessment.py --stage events --output outputs/<new_batch>
python scripts/run_stdc_final_assessment.py --stage event_followup --output outputs/<new_batch>
python scripts/run_stdc_final_assessment.py --stage pairs --output outputs/<new_batch>
python scripts/run_stdc_final_assessment.py --stage mip --output outputs/<new_batch>
python scripts/run_stdc_final_assessment.py --stage summarize --output outputs/<new_batch>
```

已有输出可在相同源码、环境和输入下恢复；不会重写完成记录。换机器、Python/数值库版本、CPU 或输入后须建立新的输出和冻结协议。输入文件的相对路径取自配置，所用三个 `particles.npz` 均在本仓库。判定使用截止时刻内已经完成的 incumbent；合作式超时后才得到的改进保留在 `returned_*` 字段，不能计入 1/5 秒成绩。
