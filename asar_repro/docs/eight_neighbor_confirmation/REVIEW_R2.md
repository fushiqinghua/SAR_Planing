# 上一批证据与本轮研究取舍

本页依据结果提交 **`b3ca640de25c1d5b9d1a7449b5ed6053d9e3f3f1`**。它是新批设计的事实依据，不包含本批任何运行成绩。

主要来源：[上一批结构化汇总](https://github.com/fushiqinghua/SAR_Planing/blob/b3ca640de25c1d5b9d1a7449b5ed6053d9e3f3f1/asar_repro/outputs/eight_neighbor_followup_20261127/local_r1/summary.json)、[原始分析](https://github.com/fushiqinghua/SAR_Planing/blob/b3ca640de25c1d5b9d1a7449b5ed6053d9e3f3f1/asar_repro/outputs/eight_neighbor_followup_20261127/local_r1/ANALYSIS.md)、[后端选择](https://github.com/fushiqinghua/SAR_Planing/blob/b3ca640de25c1d5b9d1a7449b5ed6053d9e3f3f1/asar_repro/outputs/eight_neighbor_followup_20261127/local_r1/selection.json)、[旧判定协议](../eight_neighbor_followup/DECISIONS.md)。

## 1. 已经获得了什么

上一批本地253项测试通过，8项共同前缀审计完成；D5 48项、S30 4项、H30 48项均有完整结果。缓存候选满足预声明采用条件，H1的正式结论为 `within_forcing_transfer_signal`。

四个H1主覆盖的结果如下。J和Pd来自同一条路线，三次计时重复的最终J/Pd均相同。

| 实例 | 四邻接J | 八邻接J | J改善 | Pd4→Pd8 | Pd差（百分点） |
|---|---:|---:|---:|---|---:|
| Lake early | 17.151955583 | 16.744214940 | 2.3772% | 0.909765081→0.917916211 | +0.8151 |
| Lake late | 17.276096664 | 16.871848574 | 2.3399% | 0.906255942→0.897995258 | −0.8261 |
| Hudson early | 26.344691040 | 22.790164159 | 13.4924% | 0.824859360→0.895362734 | +7.0503 |
| Hudson late | 20.337375787 | 19.815790368 | 2.5647% | 0.917093438→0.921818146 | +0.4725 |

四个主覆盖改善中位数约2.4709%；去掉Hudson early这一较大值，另三例为2.34%–2.56%。四组axis的J改善也均为正，但Lake late的axis最终Pd同样下降约0.5767个百分点。

这些结果支持继续围绕物理时间一致的多方向概率规划组织章节证据。它们不支持“所有指标同时提升”或“已经证明独立天气泛化”。四例仍使用原Lake／Hudson历史forcing，只是平移任务时窗并更换粒子seed。

## 2. 缓存收益已得到有限证据，下一步不继续堆缓存参数

D5中8个分组的J中位数均不退化。Lake heading八邻接达到固定目标的中位时间从2.5519754秒降至2.1195411秒，约减少16.95%；双方均3/3命中。Hudson heading八邻接的目标命中从0/3变为3/3。

后者没有观测到原后端的真实目标时间，不能用5秒除以cached目标时间计算速度倍数。缓存采用来自“至少一个目标组命中数增加”的预声明分支，并不是两个组都证明了至少10%的完整目标时间下降。

同批距离缓存命中率已很高，容量没有发生逐出。现有证据不足以把增大缓存上限当成下一步重点。更值得检查的是有没有及时产生完整路线，以及搜索是否把大量时间留在前缀排序上。

## 3. Hudson early需要更强四邻接对照

该例S30原 `paper_greedy` 未在初始化预算内改进PT。后续H30的四邻接两种覆盖、共六次运行仍仅保留初始路线，`terminal_candidates=0`、`replayed_candidates=1`；八邻接则找到更好路线。

因此13.4924%是有效的同预算已获路线差，不是已证明的图最优值差。现在增加同样施加给四／八邻接的固定补全候选，记录首个完整终点、深度／tick分布，再做一次对称R120，目的就是减少弱参考造成的解释歧义。

现有coarse-cell引导忽略连续航点拼接，可疑点包括排序、完整候选发现与有限资源相互作用。但原S30的paper引导已经使用图距离，它也没有找到改善；仅凭旧日志不能断言“Euclidean距离是唯一原因”。本批先采集机制证据，不预设单一结论。

代表原始记录：[Hudson early四邻接](https://github.com/fushiqinghua/SAR_Planing/blob/b3ca640de25c1d5b9d1a7449b5ed6053d9e3f3f1/asar_repro/outputs/eight_neighbor_followup_20261127/local_r1/runs/H30_e2b50a7ac703ef475325/result.json)、[八邻接](https://github.com/fushiqinghua/SAR_Planing/blob/b3ca640de25c1d5b9d1a7449b5ed6053d9e3f3f1/asar_repro/outputs/eight_neighbor_followup_20261127/local_r1/runs/H30_4682561c232631392cb5/result.json)、[共同初始化](https://github.com/fushiqinghua/SAR_Planing/blob/b3ca640de25c1d5b9d1a7449b5ed6053d9e3f3f1/asar_repro/outputs/eight_neighbor_followup_20261127/local_r1/runs/S30_a0424591fd5b4ae1b790/result.json)。

## 4. Lake late显示的是目标取舍

旧J是每个共同观测时刻后的未发现质量之和，较早取得探测收益可以降低J，即使最后一刻累计Pd稍差。Lake late主覆盖生存序列确实存在早期领先、后期落后的交叉，因此不能把这次Pd下降简单称作评分错误。

旧保存history主要是J改进链，不是完整非支配候选集。history里没有同时超过四邻接J/Pd的路线，并不证明八邻接可行域中不存在这样的路线。本批使用同一可行四邻接参考和固定Pd门槛，保留被实际访问、完整重放的非支配路线，检查是否能取得联合改善。

只有返回安全参考也能满足Pd约束，但这不是创新收益。必须同时报告相对参考的J改善，以及相对J-only候选的代价。若联合收益有限，章节可以诚实描述“更早探测与最终覆盖的可调取舍”，不必把每个指标都强行写成占优。

代表原始记录：[Lake late四邻接](https://github.com/fushiqinghua/SAR_Planing/blob/b3ca640de25c1d5b9d1a7449b5ed6053d9e3f3f1/asar_repro/outputs/eight_neighbor_followup_20261127/local_r1/runs/H30_783d14363e54c0a414a0/result.json)、[八邻接](https://github.com/fushiqinghua/SAR_Planing/blob/b3ca640de25c1d5b9d1a7449b5ed6053d9e3f3f1/asar_repro/outputs/eight_neighbor_followup_20261127/local_r1/runs/H30_9737b3621b2f8a7856a7/result.json)。

## 5. 本批不把已看数据重新包装成验证集

四个旧H1已被用于发现问题、选定补全机制、设定Pd门槛和目标J，本轮都是开发／诊断输入。三次计时重复用来观察机器和截止波动，不增加天气样本数。

H2需要新forcing日期块，在方法选择后锁定来源、日期、seed和全部输入，先完成来源／时间覆盖／物理适用性检查，随后才看规划分数。只换seed或在原包络中继续平移时段，不能替代这一步。本轮只给出 [H2预注册](H2_PREREGISTRATION.md)，没有生成或评分新日期。

## 6. 章节贡献的当前定位

可作为章节主线的候选是物理时间一致的多方向动作、共同观测时钟、动态粒子未发现概率评分及有限预算求解的组合。四／八邻接本身是既有图建模方式，当前模型也未包含实机转弯或返航；不应把增加对角边本身写成首创。

本批优先补足同预算强对照、可解释目标取舍、完整候选发现与数学边界。理论可证明的命题和仍待证据支持的论文表述见 [THEORY_AND_CLAIMS.md](THEORY_AND_CLAIMS.md)。冻结基点是研究参照，不表示已经创建Git发布tag或正式V2.0发行版。
