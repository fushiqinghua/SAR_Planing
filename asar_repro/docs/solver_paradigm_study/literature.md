# 文献依据、适配与研究边界

整理日期：2026-11-27。以下用于解释实验设计，不是新方法在本仓库已经有效的证据。方法名称本身也不是新颖性声明。表中链接指向原论文、作者页面或正式出版平台。

## 1. 与目标直接相关的搜索研究

### A^SAR：当前研究参照

Eric Mugford, Jonathan D. Gammell. *A^SAR: ε-Optimal Graph Search for Minimum Expected-Detection-Time Paths with Path Budget Constraints for Search and Rescue (SAR).* arXiv:2511.10792，v2，2026-02-27。

- 原文：[摘要与版本](https://arxiv.org/abs/2511.10792)、[v2 全文](https://arxiv.org/html/2511.10792v2)。
- 用途：最小期望探测时间、四邻路径、动态目标概率以及与 ACO 的比较，提供本项目的建模和算法参照。
- 适配边界：原文已有 ACO 对照，也讨论 CEO；不能把重新使用这些算法当成首次提出。原文的 C++ 时间、ACO 按代数比较、作者场景与本仓库运行环境不能直接合并成速度比。
- 保证边界：本项目当前动态实现和有限预算记录的认证范围必须以本仓库审计为准，不能仅凭论文标题或 ε 参数把真实场景路线标成已认证。

### ET-CEO：累计未发现质量与动作序列采样

Pablo Lanillos, Eva Besada-Portas, Jose Antonio Lopez-Orozco, Jesus Manuel De la Cruz. *Minimum Time Search in Uncertain Dynamic Domains with Complex Sensorial Platforms.* Sensors 14(8), 14131–14179, 2014。

- 原文：[全文与算法](https://www.mdpi.com/1424-8220/14/8/14131)。
- 用途：式 (3)–(6) 与 Algorithm 2 累加未归一化未发现质量；Algorithm 3 用交叉熵优化动作序列，直接支持本项目 CEM 对照的目标兼容性。
- 适配边界：论文主要实验采用 10 步控制时域串接长路线。本批每个样本必须覆盖原完整 T=49/60，不能用 10 步结果冒充完整时域优化。论文的传感器、动作集合和多搜索器设置也不照搬。
- 代码边界：本分支实现为基于机制的新适配，不声称复用了该文完整作者代码。CEM 的超参数在本地验证后、正式比较前冻结。

### 相关 ACO 对照

Sonia Pérez-Carabaza et al. *Ant colony optimization for multi-UAV minimum time search in uncertain domains.* Applied Soft Computing 62, 789–806, 2018。

- 原文：[DOI](https://doi.org/10.1016/j.asoc.2017.09.009)。
- 用途：确认最小时间搜索已有利用完整路线信息和专用启发式的随机优化方法。A^SAR 的相关对照来自此工作。
- 本轮选择：不另实现一条 ACO 主线，以免把有限预算再次分散到大量求解器。后续若需论文级比较，应根据主结果和适用范围决定是否补充。

## 2. ILS 与大邻域搜索

Helena R. Lourenço, Olivier C. Martin, Thomas Stützle. *Iterated Local Search: Framework and Applications.*

- 作者稿：[PDF](https://iridia.ulb.ac.be/~stuetzle/publications/LouMarStu10.pdf)。
- 用途：扰动、重新优化与接受规则；扰动过小易返回相同局部解，过大可能退化为低效重启。
- 本项目适配：释放早期路线，允许较大后缀重建和非局部时空决策；current 可暂时变差，best 保留原 J 最小路线。这些具体操作的 SAR 效果是本批要检验的假设。

Stefan Røpke, David Pisinger. *An Adaptive Large Neighborhood Search Heuristic for the Pickup and Delivery Problem with Time Windows.* Transportation Science 40(4), 455–472, 2006。

- 原文：[DOI](https://doi.org/10.1287/trsc.1050.0135)、[作者机构页面](https://orbit.dtu.dk/en/publications/an-adaptive-large-neighborhood-search-heuristic-for-the-pickup-an/)。
- 用途：多个删除／修复算子及基于表现的选择框架。
- 适配边界：原论文不是 SAR 模型。框架不会自动提供有效的粒子探测邻域；本轮先检验固定算子，不以“ALNS”名称掩盖实际只有旧短窗口的实现。

Niels A. Wouda, Leon Lan. *ALNS: a Python implementation of the adaptive large neighbourhood search metaheuristic.* JOSS 8(81), 5028, 2023。

- 论文：[JOSS](https://joss.theoj.org/papers/10.21105/joss.05028)；作者代码：[N-Wouda/ALNS](https://github.com/N-Wouda/ALNS)。
- 用途：可参考通用接口与接受／算子组织方式。当前首版不要求新增此依赖，也不声称该库本身能求解本项目。

## 3. 完整时域的凸整数模型

Miguel Lejeune, Johannes O. Royset, Wenbo Ma. *Multi-Agent Search for a Moving and Camouflaging Target.* arXiv:2309.02629, 2023。

- 原文：[摘要](https://arxiv.org/abs/2309.02629)、[全文](https://arxiv.org/html/2309.02629v2)。
- 用途：条件目标轨迹、指数未发现概率、凸整数模型、整数点割线、预处理与外逼近。
- 本项目适配：单搜索器、固定完整时域、四邻无等待、自由终点；保留所有时刻的累计 J。原文主要终端未发现概率不直接替换本目标。
- 计算边界：完整域数值求解可能很难；本轮首先用于小中实例标尺。求解器 dual 是声明数值容差下的完整模型下界，不能把受限前缀／走廊的 dual 升级成原问题全局证书。具体推导见 [count 模型](count_model.md)。

## 4. 保留但本轮不启用的结构化方向

Martin Jaggi. *Revisiting Frank-Wolfe: Projection-Free Sparse Convex Optimization.* ICML, PMLR 28(1), 427–435, 2013。

- 原文：[论文页面](https://proceedings.mlr.press/v28/jaggi13.html)、[PDF](https://proceedings.mlr.press/v28/jaggi13.pdf)。
- 可研究的适配：在合法完整路径凸包上优化累计未发现质量的连续松弛；每次线性子问题可生成整条时间图路径，并提供对偶间隙信息。
- 边界：连续混合不是可执行路线，松弛小 gap 不等于整数路线接近最优，也不保证比 STDC 更紧。若以后实现，应独立验证下界公式、数值和真实候选质量。本批没有启用此方法。

## 5. 本轮可能形成的贡献与仍需验证的内容

本轮首先检验“同模型换搜索组织”的可行性。只有在完整记录中观察到稳定的质量／效率收益，才值得进一步提出和验证具体算法贡献。算子名称、引用一篇新论文、在少数 toy 上获胜都不自动等于新颖性或真实任务价值。

若结果支持继续，应根据实际胜出机制进一步检索邻域设计、概率覆盖与动态目标搜索工作，完成更窄范围的相关工作比较。若没有收益，也应保留同预算负结果、候选多样性和已闭合小实例差距，为停止或转向提供依据。
