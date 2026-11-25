# Oracle 门槛失败后的只读模型检查

状态：**blocked**。本检查没有修改源码、评价器、forcing、历史产物，没有调用优化器，也没有枚举/搜索新路径。

仅使用正式审计已保存的 `input_1059.json` 与 `last_checked.json`。通过内存中 mock `milp` 截获冻结构建器的 A、c、变量边界及行边界，在优化器调用前明确中断；随后对三个已保存路径构造精确残余变量向量。该截获中断是分析手段，不是新的算法失败。

源码 SHA-256 前后均为 `20fceef062b2a1817ab5fcff96b48394d1237bfbeb50b23820f899efb9533ed4`。

## 已证实

- seed=1059，3×3，T=7，prefix_depth=3，corridor_radius=0。
- 模型 12 个变量、17 条约束。Oracle 路径 `[4,5,2,1,2,5,2,5]` 在该模型中可行：行约束、变量边界和整数误差均为 0。
- 该路径的 MILP 目标值与原评分器重放完全一致：`J=3.0744347826086957`，`Pd=0.7325217391304348`。
- 已保存的求解器路径 `[4,5,2,1,2,5,2,1]` 也可行，模型值与原评分一致：`J=3.1495652173913045`。
- 原求解器声称 optimal 且返回 restricted lower bound `3.1495652173913045`，高于另一个已验证可行值 `0.07513043478260872`。因此该下界与最优性标签在此例不成立，差距远大于 `1e-10`。
- 两个原始粒子在固定前缀后拥有同一完整未来轨迹，合组质量为 `0.3130434782608696`。仅 t=5 和 t=7 可在 v=5 检测，q=.6。Oracle 两次检测使归一化残余从 1→.4→.16；求解器路径只检测一次，末残余 .4。目标差恰为组质量×(.4−.16)。
- 这排除了该例中“Oracle 路径被 corridor 排除”和“模型目标与原评分递推不一致”两个解释。

## 尚未证实

目前未做任何新的后端求解或参数消融，不能断言根因一定是 HiGHS presolve、SciPy 接口、某一严格选项或其他后端问题。当前证据是冻结构建器与原求解报告发生了可行点/下界矛盾。

必须保留 blocked，不能仅改 completed 标签、夹紧下界、放宽断言或继续真实场景。后续若获准修复，应先针对该固定模型做独立后端/预处理消融，再原样回归 Oracle；本轮没有实施这些步骤。

文件：`solver_vector_check.py`、`solver_vector_check.json`、`stdout.txt`、`stderr.txt`。JSON 包含完整系数及三个已存路径对应向量；无新的求解输出。

命令（从 asar_repro 根目录，PYTHONPATH=offline_guard;src，禁用 pyc）：

```powershell
& 'C:\Users\35448\.conda\envs\maritime-sar\python.exe' 'outputs/stdc_v0_2/exact_repair_20261124/failure_readonly/solver_vector_check.py'
```
