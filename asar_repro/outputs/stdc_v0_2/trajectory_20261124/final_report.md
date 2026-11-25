# STDC trajectory iteration — 2026-11-24

本轮未突破既有最好 J=17.264874448；不将速度、下界变化或 toy 改善等同于真实场景指标改善。

同扩展预算下，DP-only保持相同J/Pd，中位耗时2.3707秒，比本轮prior_stdc低38.9%，比同样压缩的compressed_stdc低35.5%。普通中段rollout可补回较弱seed与既有最好的差距，多样化版本未显示稳定收益。详细解释见 [interpretation.md](interpretation.md)，核心差值图见 [core_comparison.png](core_comparison.png)。

全量测试：独立诊断阶段 734 项，规划阶段 903 项；均无失败、错误或跳过。
诊断：12 个合成 toy 的 MILP 与独立 DFS 最优 J 一致；424 个前缀下界无越界，其中178个非终点LP全部完成并验证对偶。
规划审计：160 组随机小图、18024 个前缀；粒子 DP 检查 9012 个，0 个比 STDC 严格更紧。
35个原动态小图+5静态+5粒子派生案例，共 150 次完整搜索；最大 J 误差 0。
真实LP：状态 budget_exhausted，停止原因 wall_time_during_dual_verification；可用LP下界 0.000000000000，STDC下界 9.179977673620。未闭合区间不能证明存在更优可行路线。

|预算|方法|J 中位数|Pd 中位数|总扩展中位数|秒数中位数|峰值MiB中位数|停止原因|
|---|---|---:|---:|---:|---:|---:|---|
|work|paper_baseline|17.293894154560|0.897370418880|1222|0.9503|90.11|{'completed': 3}|
|work|prior_stdc|17.264874448000|0.897364416000|5000|3.8811|147.60|{'max_expansions': 3}|
|work|compressed_stdc|17.264874448000|0.897364416000|5000|3.6732|127.70|{'max_expansions': 3}|
|work|dp_only|17.264874448000|0.897364416000|5000|2.3707|147.33|{'max_expansions': 3}|
|work|stdc_dp|17.264874448000|0.897364416000|5000|4.0920|165.57|{'max_expansions': 3}|
|work|mid_plain|17.264874448000|0.897364416000|4142|4.6711|94.63|{'global_seed_max_expansions': 3}|
|work|mid_diverse|17.291968495053|0.894972397114|4131|4.8677|94.13|{'global_seed_max_expansions': 3}|
|work|mid_dp|17.291968495053|0.894972397114|4131|5.4252|132.07|{'global_seed_max_expansions': 3}|
|wall|paper_baseline|17.293894154560|0.897370418880|1222|0.9377|90.18|{'completed': 3}|
|wall|prior_stdc|17.264874448000|0.897364416000|6607|5.0196|173.57|{'max_seconds': 2, 'max_open': 1}|
|wall|compressed_stdc|17.264874448000|0.897364416000|6887|4.8175|149.49|{'max_open': 3}|
|wall|dp_only|17.264874448000|0.897364416000|8861|4.0790|184.62|{'max_open': 3}|
|wall|stdc_dp|17.264874448000|0.897364416000|6392|5.0171|181.96|{'max_seconds': 3}|
|wall|mid_plain|17.264874448000|0.897364416000|4293|5.0020|102.17|{'max_seconds': 3}|
|wall|mid_diverse|17.264874448000|0.897364416000|4334|5.0022|101.10|{'max_seconds': 3}|
|wall|mid_dp|17.264874448000|0.897364416000|3518|5.0025|133.41|{'max_seconds': 3}|

共 48 次正式对照；正常完成 6，预算中止 42，认证数0。
方法预算：work为5000次总扩展/30秒/20000 OPEN；wall为5秒/20000 OPEN。每种重复3次，顺序轮换。重复仅衡量同一归档的计时波动，不是独立场景。
停止原因中的global_seed_*表示seed子配额中止，即使后续rollout完成也保留该事实；它不等于整体5000扩展已用尽。各阶段状态和实际扩展在raw_result.json/phases中分别保存。
所有方法从同一冻结 PT 出发。压缩、DP预计算、seed及rollout都计入方法时间；中段方法分配40%预算给seed，剩余共享给最多3个anchor。节点扩展不包含DP网格更新，后者单独记录预处理开销。
输入：SHA核验成功的真实历史 Lake Ontario forcing 与冻结500粒子归档；精确等价压缩为342组，最终与每条接受路径按原500粒子评分。真实输入仍保留all-water场景近似标签。
目标未变：J=sum(M_t), t=1..T，t=0不探测；Pd=1-M_T。最小J与最大最终Pd不一定同向。
单粒子DP递推：V_i(T,v)=0；V_i(t,v)=min_{u邻接v} a_i(t+1,u)[1+V_i(t+1,u)]；h=sum_i b_i V_i。它允许每个粒子使用自己的可行路径，放松了共同搜索平台约束，因此在固定外生轨迹、固定探测模型下是离散剩余J的下界。max(STDC,h)保留这项模型条件。
DP下界性质不等于整个搜索获得epsilon认证。paper_greedy仅排序；beam丢弃仅属于候选保留策略；任何预算中止与本轮真实结果均未认证。
保全：修改前 3964 个文件逐一SHA相同，baseline-v1.1、原评分器、forcing、B7与此前实验均未覆盖。新增Python文件列表见final/summary.json；每阶段命令、seed、stdout/stderr、JSON、pytest XML与git diff均已保存。

图表与数据：benchmark/metrics.csv、paired_comparisons.csv、aggregate.csv、work/wall_paths.png、work/wall_quality_survival.png、work/wall_efficiency.png。
离线复跑：使用maritime-sar解释器；设置PYTHONPATH=scripts/offline_guard;src;scripts、ASAR_OFFLINE=1、PROJ_NETWORK=OFF和数值库线程数1。复制各阶段command.json中的完整参数并改为全新输出目录。初次阶段冻结使用run_trajectory_validation.py init；随后new_tests、full_tests、oracle_audit；历史硬链接测试需使用原用户环境。不得覆盖本目录复跑。
边界：仅一个冻结真实归档；没有跨场景泛化结论，没有修改forcing、评分目标或旧数据，没有开展创新点二，也未自动推送GitHub。

集成版准确复跑命令保存在 [offline_replay.ps1](offline_replay.ps1)。它以原诊断阶段734测试的冻结证据为前序，重新执行当前903测试与Oracle，再做真实对照；不要对当前集成源码重新使用默认diagnostic初始化并期待旧734测试计数。脚本为每次复跑创建全新目录。
