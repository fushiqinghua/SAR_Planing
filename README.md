# STDC-A^SAR v0.2 研究分支

本分支基于冻结的 `baseline-v1.1`，研究 STDC 下界与搜索策略能否改善海上搜救路径。更新于 2026-11-25。

[研究交接报告与原始证据索引](asar_repro/RESEARCH_HANDOFF_20261125.md) · [供其他模型使用的分析提示词](asar_repro/docs/research_handoff_20261125/PROMPT_FOR_NEXT_MODEL.md)

## 当前结果

**直接 STDC 的 anytime 搜索在三个固定场景的工作量预算对照中都降低了 J。** Hudsons Bay 和 Bay of Fundy 的 Pd 同时提高，Lake Ontario 的 Pd 略降。Lake Ontario 的 J 从 17.29389415456 降至 17.264874448，降幅约 0.1678%。三组对照中，直接 STDC 的实际搜索时间均更长。后续调度、rollout、单粒子 DP 和受限 MILP 实验尚未把 J 降到直接 STDC 以下。

下表取自适应实验 `work` 协议的三次运行中位数。各方法从同场景的冻结平行线搜索路径（PT）出发，共用 5000 次扩展、20000 个 OPEN 条目、30 秒的上限。论文基线（`paper_greedy` A^SAR）按自身停止规则完成，直接 STDC（`prior_stdc`）达到扩展上限后返回当前最佳路径。

| 场景 | 论文基线 J↓ / Pd↑ | 直接 STDC J↓ / Pd↑ | 耗时中位数（秒，基线 → STDC） |
|---|---:|---:|---:|
| Lake Ontario | 17.293894155 / 0.897370419 | 17.264874448 / 0.897364416 | 0.925 → 3.444 |
| Hudsons Bay（`arctic_ocean`） | 20.390881327 / 0.906729745 | 20.386109349 / 0.908583112 | 1.282 → 4.741 |
| Bay of Fundy | 45.903608800 / 0.399984000 | 45.881082400 / 0.415864800 | 1.164 → 5.251 |

[工作量和 5 秒预算的完整对照](asar_repro/outputs/stdc_v0_2/adaptive_20261124/final_report.md) · [逐方法汇总 CSV](asar_repro/outputs/stdc_v0_2/adaptive_20261124/benchmark/aggregate.csv)

三个场景均使用真实历史风流数据驱动的 Leeway 模拟粒子归档（每场景 500 粒子，`q=0.78`，`seed=41`），采用 all-water 碰撞近似。Bay of Fundy 使用官方原始网格角度，保留 **物理方向未验证**（`physical_direction_unverified=true`）标签。[三场景数据与实验协议](asar_repro/outputs/stdc_v0_2/three_real_20261124/three_real_comparison.md) · [Fundy 接入记录](asar_repro/outputs/stdc_v0_2/fundy_repair_20261124/repair_report.md)

## 从早期缓存到热启动

| 研究轮次 | 设计与结果 |
|---|---|
| 缓存与固定窗口 | 复用几何和启发式计算，在固定端点窗口内按精确后缀评分搜索。早期缓存缩短了原 STDC 的耗时，窗口搜索在部分设置下改善路径。[缓存报告](asar_repro/outputs/stdc_v0_2/repair_20261123_r2/report/repair_report.md) · [窗口报告](asar_repro/outputs/stdc_v0_2/windows_20261123/FINAL_REPORT.md) |
| 全局 anytime 与计算优化 | 首条可行路径之后继续搜索，分开排序和安全剪枝。随后测试快速排序、两步前瞻、等价粒子压缩与尾段修复，部分变体降低了计算开销。[Anytime 报告](asar_repro/outputs/stdc_v0_2/anytime_20261124/FINAL_REPORT.md) · [优化报告](asar_repro/outputs/stdc_v0_2/optimization_20261124_resume/FINAL_REPORT.md) |
| 中段 rollout、自适应调度与紧凑 DP | 试验中段多样化、预算回退和单粒子下界。紧凑 DP 降低了管理数组内存。自适应轮的八种改进方案与直接 STDC 共配对 144 次，严格 J 胜出 0 次。[中段与 DP 报告](asar_repro/outputs/stdc_v0_2/trajectory_20261124/final_report.md) · [配对结果](asar_repro/outputs/stdc_v0_2/adaptive_20261124/benchmark/paired_comparisons.csv) |
| 候选诊断 | 重建的 270 个 rollout 候选均等于生成时的当前最佳路径。独立穷举最终直接 STDC 路径的 447 个短窗口，未找到更小 J。[诊断报告](asar_repro/outputs/stdc_v0_2/rollout_limit_diagnosis_20261124/diagnosis_report.md) |
| 受限 MILP | 固定前缀和走廊，释放终点。首轮 toy 反例触发停止，第二轮关闭本地 HiGHS 的 presolve 后通过回归。第三轮向求解器提交完整 STDC 可行解，并加上包含该解的目标上界。[首轮停止记录](asar_repro/outputs/stdc_v0_2/exact_repair_20261124/final_report.md) · [数值修复报告](asar_repro/outputs/stdc_v0_2/exact_repair_r2_20261124/final_report.md) |

## 最新实验：热启动与目标上界

第三轮 MILP 对照的冷、热两组都保留同一条已经求得的 STDC 路径作为可行解，每方法每场景另给 300 秒诊断预算。18 个受限子问题中，6 个完成，12 个达到时间上限。三个场景的最终 J/Pd 都等于表中的直接 STDC 值。热启动加上界组的峰值内存高于冷启动组。

| 场景 | 额外耗时（秒，冷 → 热） | 峰值内存（MiB，冷 → 热） |
|---|---:|---:|
| Lake Ontario | 300.447 → 300.039 | 428.11 → 475.54 |
| Hudsons Bay | 300.134 → 300.132 | 553.94 → 738.75 |
| Bay of Fundy | 300.122 → 300.642 | 961.30 → 989.93 |

[第三轮报告](asar_repro/outputs/stdc_v0_2/exact_repair_r3_20261124/final_report.md) · [对比 CSV](asar_repro/outputs/stdc_v0_2/exact_repair_r3_20261124/diagnostic/comparison.csv) · [耗时与内存图](asar_repro/outputs/stdc_v0_2/exact_repair_r3_20261124/diagnostic/efficiency.png)

## 验证与复跑

- 目标是最小化搜索第 1 至 T 步的未探测质量之和 J，t=0 不探测。Pd 表示截至第 T 步的累计探测概率，与 J 用同一条路径计算。
- 真实场景结果均标为未认证。动态 `paper_greedy` 在 anytime 框架中用于排序。MILP 的下界和 gap 仅适用于对应前缀与走廊，当前路径的全局最优性仍待验证。
- 最新实验归档记录了 **1228 项全量测试、192 组冷启动 Oracle、576 组热启动和上界消融 Oracle**通过，Oracle 最大 J 误差为 0。[验证汇总](asar_repro/outputs/stdc_v0_2/exact_repair_r3_20261124/validation_summary.json) · [研究交接复核](asar_repro/docs/research_handoff_20261125/review.json)

离线复跑使用已有 `maritime-sar` 环境，先按冻结协议核对输入 SHA-256，再写入新的输出目录。各轮报告附有复跑命令和环境记录。大体积原始风流文件及下载分片保存在本地。

[上传与本地保留文件清单](asar_repro/docs/research_handoff_20261125/upload_inventory.json) · [原论文阶段 0–8 复现说明](asar_repro/README.md)
