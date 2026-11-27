# 原始文献与本批模型的关系

本页保留此次设计所依据的原始来源。论文事实、几何推导和我们尚未验证的工程假设分开陈述，不将既有方法名称视为新颖性证明。

## 1. A^SAR 原论文：图模型与四邻接实验原因

Eric Mugford, Jonathan D. Gammell. *A^SAR: ε-Optimal Graph Search for Minimum Expected-Detection-Time Paths with Path Budget Constraints for Search and Rescue (SAR).* arXiv:2511.10792v2，2026-02-27。

- [原文 HTML](https://arxiv.org/html/2511.10792v2)
- [原文 PDF](https://arxiv.org/pdf/2511.10792v2)

III-A 的一般图定义已允许四邻接或八邻接。IV-B 的实验则排除对角线：格宽按下视相机扫幅设置，作者认为对角运动会留下格内未观测部分。四邻接并非因为无人机不能朝对角方向飞行，而与格子观测近似配套。

对本批的直接含义是：增加对角边之前需要同时定义物理耗时和观测覆盖。我们的两个正方形 footprint 是用于受控比较的假设，不能从论文的 sweep width 直接推出实体相机视场。原论文的最优性表述不替代仓库对动态启发式和当前适配器的独立审查。

## 2. Theta*：八邻接仍有方向离散限制

Kenny Daniel, Alex Nash, Sven Koenig, Ariel Felner. *Theta\*: Any-Angle Path Planning on Grids.* Journal of Artificial Intelligence Research, 39, 533–579, 2010.

- [作者机构摘要与原稿入口](https://idm-lab.org/bib/abstracts/Koen10r.html)
- [作者论文 PDF](https://arxiv.org/pdf/1401.3843)

普通八邻接仍把方向限制在45度整数倍；Theta*让路径不必沿格边，并以欧氏线段长度计算相应代价。Basic Theta*也不保证真正的连续空间最短路径。

该工作研究固定起终点之间的短无障碍路径，不优化本项目的累计未发现质量。它只作为运动表示的背景，不是本批要替换成的SAR求解器。把旧路线做几何平滑也会改变到达时刻、漂移目标位置和观测机会，必须完整重评分。

## 3. 状态格点：真实运动约束的后续背景

Mikhail Pivtoraiko, Ross Alan Knepper, Alonzo Kelly. *Differentially Constrained Mobile Robot Motion Planning in State Lattices.* Journal of Field Robotics, 26(3), 308–333, 2009.

- [CMU 官方机构页面](https://publications.ri.cmu.edu/differentially-constrained-mobile-robot-motion-planning-in-state-lattices)
- [作者原稿](https://www.cs.cmu.edu/~alonzo/pubs/papers/JFR_09Final.pdf)

该研究使用满足系统运动约束的基本运动连接离散状态；状态可包括位置、航向、曲率和速度，并通过连接连续性建立可执行路径。它是通用机器人规划方法，不能直接作为具体无人机动力学标定。

本批仍为恒定地速平面质点模型，未加入转弯半径或速度连续性。若后续要提出固定翼实际可飞性的结论，应另行引入这类状态与运动约束，并让所有对照共同满足。

## 4. 我们自己的推导与待验证假设

以下属于几何推导：正交边为d，对角边为√2d；同速耗时也相差√2。将对角边按原正交时间完成会隐含41.4%提速；从相邻对角格的两边绕行改成直连，局部转场距离减少约29.3%。这些数值不预测整体J改善。

以下属于本批待验证假设：在恒速、共同物理时钟和共同覆盖代理下，八邻接增加的空间访问方式可能改善目标探测顺序。是否产生质量收益、是否抵消额外搜索成本、是否对覆盖方向敏感，都必须由本地固定矩阵回答。

模型可行域扩展的收益与新求解器的收益是不同结论；四／八邻接本身也不是本项目新增的算法发明。独立档案、具体相机标定与实飞验证尚未开展。
