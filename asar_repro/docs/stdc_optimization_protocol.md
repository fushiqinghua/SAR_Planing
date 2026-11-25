# STDC 下一轮优化协议（2026-11-24）

研究分支 stdc-research-v0.2。全部实现为新增 opt-in 模块；不修改旧 baseline、B7、评分器、运动 forcing 或此前原始结果。本轮目标仍为最小化 J=sum(M_t,t=1..T)，Pd=1-M_T 单列，t=0 不检测。

## 数值不变量和依赖前提

- 四连通合法动作、完整长度 T；每次绝对时刻先移动后探测。
- 信念为未归一化联合未探测质量；非负、质量不增；陆地/域外等质量不消失。
- guide 执行内核保持论文逐步贪心、升序 tie-break、无相邻贪心选择连续性限制；仅排序，不剪枝/认证。
- 两步前瞻完整枚举所有合法前缀，max(STDC, min(C_prefix+STDC_tail))；部分枚举中断只能返回已有安全基础下界。
- 主搜索的辅助前瞻展开与普通展开共享 5000 工作量；统计单独列出。前瞻只在剩余步数≤8时调用，其他深度保留原STDC。
- 尾段保持原前缀的完整信念与累积J，使用绝对帧；所有接受路径用原评分器全路径重放，只接受J改善。
- 压缩仅合并全归档所有时刻cell_ids完全相同的粒子，含t0和特殊bin；保留原ID映射及原始p，最终以原ID重放。浮点顺序可能变化，不声称逐位搜索等价。
- 互补排序每8次pop使用一次终时刻热点截获估计。共享节点/incumbent，两份heap物理条目均计OPEN；一个路径节点只展开一次，不合并不同路径belief。
- 默认返回最小J；可记录已探索完整候选中的非支配J/Pd档案，绝不当作全局Pareto前沿，未添加Pd约束。
- 固定非负、质量守恒运动和q∈[0,1]为模型前提。所有路线theory_certified=false；无新增动态ε最优声明。

## 顺序与停止规则

1. 修改前保留所有旧文件SHA；完成源码后freeze全部src/tests/scripts指纹。
2. 新增pytest，再全部历史pytest。任何failure/error/skip标记blocked并停止。
3. 160固定随机小图、18024个前缀：独立全路线枚举Oracle检验旧全部下界及两步前瞻，验证guide选择序列；任何可采纳性断言失败即blocked。
4. 35历史动态小图+5静态派生+5合成粒子派生，320搜索与Oracle/独立重放对照。
5. B3真实历史粒子、forcing、UTC、元数据及原评分器SHA全部通过才运行11组smoke。
6. 11方法×2协议×3计时重复，共66正式运行。真实实验统一冻结Lake Ontario归档seed41；三重复不是三独立场景。
7. 文件保全、报告、CSV/JSON/图、artifact SHA清单。所有失败保留stderr与最后检查位置；不绕过门槛。

## 预先固定的实验设置

|设置|work协议|wall协议|
|---|---|---|
|总工作展开（含前瞻辅助）|5000|无限制|
|物理OPEN条目|20000|20000|
|方法时间上限|30秒|5秒|
|初始路径|共同冻结PT|共同冻结PT|
|guide权重|1.04|1.04|

停止可以早于时间上限，例如先触发OPEN；不将其包装为完整使用固定时长。时间为合作式检查，overshoot显式记录；进程峰值内存包括导入、输入核验等，不当作纯节点内存。

方法：paper_baseline、anytime_reference、fast_zero、fast_mass、fast_stdc、cascade_stdc、lookahead_stdc、tail_zero、tail_stdc、compressed_stdc、portfolio_stdc。

尾段组合先用40%总工作/时间配额运行同bound全局搜索，再用剩余预算尝试长度6、10、14；种子成本计入，无免费最好baseline暖启动。压缩构造成本计入方法时间。portfolio使用两份heap，不为第二队列赠送容量。预算中止是运行状态，合法incumbent与来源仍记录。

新优化有独立对照，未预设其一定更优：等价guide应保持work协议路径/计数；前瞻改善是否抵偿成本、尾段是否脱离局部结构、压缩率与多排序质量均由实际结果决定。

## 复跑

解释器固定为 C:/Users/35448/.conda/envs/maritime-sar/python.exe；PYTHONPATH包含scripts/offline_guard、src、scripts，数值库单线程，ASAR_OFFLINE=1、PROJ_NETWORK=OFF。每阶段command.json记录完整命令及seed。

按顺序调用 scripts/run_optimization_validation.py 的 init/new_tests/full_tests/random_audit/small_search，--run-dir 指向全新目录；随后 scripts/run_optimization_experiments.py smoke/benchmark 并提供通过的validation_summary.json；最后调用final_preservation。旧输出目录不得覆盖。

本轮不重新运行OpenDrift，不安装或升级依赖，不开展第二创新点。不把工程优化称为已证明的新颖研究贡献。
