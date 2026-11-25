# 独立受限精确修复：blocked

日期：2026-11-24。正式独立Oracle验证失败。本轮未通过验收，不得接入默认规划器或真实归档实验。
原目标、评价器、forcing、旧正式结果和baseline未修改；新增求解器及测试作为未验收研究代码保留。

## 已实现但未通过最终验收

固定前缀、自由终点的时空MILP；共享四连通路线、未来同轨迹后验分组、事件跨度计费、特殊质量保留。仅原评分器重放后严格J改善可替换incumbent。
原生HiGHS严格数值选项、threads=1、random_seed=0和透传warning有记录。开发阶段修复了零/正节点预算状态映射，并增加长时域回归；没有放宽历史或Oracle断言。

## 正式门槛结果

|阶段|状态|结果|
|---|---|---|
|新增pytest|passed|77 passed，0 failures/errors/skips|
|独立随机Oracle|blocked|计划192次；前74次通过，第75次失败|
|全量历史测试|未运行|按失败门槛停止|
|真实输入门控与三个场景诊断|未运行|不能绕过Oracle失败|

## 固化反例

seed=1059，3×3，T=7，4粒子，prefix_depth=3，corridor_radius=0，q为空间非均匀数组。允许空间为{1,2,5,7,8}，终点自由。
求解器返回completed/optimal，J=3.1495652173913045，restricted_lower_bound同值、gap=0。独立DFS已有合法路线J=3.0744347826086957，差0.0751304347826087，远超1e-10门槛。
|路线|J|Pd|
|---|---:|---:|
|MILP_returned|3.1495652173913045|0.6573913043478261|
|MILP_solver_candidate|3.1495652173913045|0.6573913043478261|
|independent_DFS_witness|3.0744347826086957|0.7325217391304348|

原生候选：[4,5,2,1,2,5,2,1]；Oracle见证：[4,5,2,1,2,5,2,5]。两者只差最后一步，去cell5可再检测一次。公开返回路径保留原incumbent，因为原生候选与它J相同。
失败后仅做只读复核：重放三条已存路线；截获冻结构建器的A/c/b（mock optimizer，求解次数0）并为已存Oracle路线构造12维变量向量。行约束、变量边界、整数残差均0；模型目标与原评分均为3.0744347826086957。
唯一可检测组β=36/115，事件t5/t7在cell5、q=.6，offset=319/115；更优赋值r5=.4、r7=.16、z7=.4，精确计入原J。该见证说明不是走廊定义不同、评分口径不同或普通舍入误差。
目前只能将问题范围缩到实际求解调用/矩阵传递/原生预处理链路。日志presolve=true且0 MIP节点即报optimal，尚不能直接断言是HiGHS自身bug。

## 后续必要工作（本轮未实施）

1. 将此反例升级为永久回归；导出实际模型及原生详细日志。
2. 在独立修复轮中只针对该模型比较presolve开关及严格选项组合，区分后端、接口和构建问题；不得升级依赖或关闭验收来掩盖。
3. 修复后重跑新增测试、全部192次独立Oracle、全量历史测试；全部通过才允许真实归档SHA验收与300秒受限诊断。
4. 受限子问题状态和dual不作为全局epsilon证书；Fundy仍须physical_direction_unverified=true。

## 命令与产物

从asar_repro目录、使用原offline_guard和PYTHONPATH环境运行；完整环境在各阶段command.json。
```powershell
& 'C:\Users\35448\.conda\envs\maritime-sar\python.exe' -m pytest -x -q -p no:cacheprovider tests/test_exact_repair.py
& 'C:\Users\35448\.conda\envs\maritime-sar\python.exe' scripts/audit_exact_repair.py --output-dir <新审计目录>
```

新增文件清单及SHA：code_files.json。失败输入、原生返回与Oracle路径：oracle/audit/input_1059.json、last_checked.json。原始stdout/stderr/XML/git diff全部保留。
完整模型向量只读检查：failure_readonly/solver_vector_check.json。路线重放：development/failure_readonly/saved_route_replay.json。
可视化：counterexample.png；CSV：counterexample.csv；机器状态：blocked.json、validation_summary.json。
最终保全：5589份既有研究文件、654份冻结baseline文件、上一轮1493份实验产物保持不变；之前已记录的两份pytest缓存例外没有新变化。
本轮的完成状态是blocked，不是正式完成。没有真实场景J/Pd提升可报告。
