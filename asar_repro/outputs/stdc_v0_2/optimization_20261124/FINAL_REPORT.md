# STDC 优化实现与阻断记录

**状态：blocked。实现与新增单测已完成，全量回归未通过，不能宣称正式完成或指标提升。**

日期：2026-11-24（Asia/Shanghai）。分支 stdc-research-v0.2；旧 baseline、评分器与 forcing 未修改。

## 测试结果

- 新增测试：199 passed，0 failure/error/skip。
- 全量测试：预期 693 项（历史 494 + 新增199）；执行87项，86 passed、1 failed，剩余606项未执行。
- pytest 使用 -x，失败后立即停止；后续160组逐前缀Oracle、320次小图搜索、真实smoke/benchmark全部未运行。

失败：tests/test_b1_inventory.py::test_wind_acquisition_rejects_full_object_or_saves_exact_messages[True]。
异常发生于未修改的 scripts/fetch_lake_b1.py:23，os.link(tmp,target) 返回 PermissionError: [WinError 5] 拒绝访问。
这是临时文件硬链接操作被拒绝的直接证据；具体ACL/沙箱限制尚未进一步验证。不能把它记为测试通过，也不能据此推断其余历史测试均正常。
测试将网络响应mock为内存数据，没有下载真实forcing。本轮没有绕过测试、修改旧归档代码、放宽断言或替换为合成真实输入。

## 已实现的新模块

- research_particle.py：逐调用一份私有权重的paper guide；全时刻严格等价粒子分组、原ID映射、保守只读共享。
- lookahead_bound.py：mass→STDC→完整两步合法前瞻；不完整枚举回退安全基础值，辅助展开计账。
- research_search.py：集成可选级联/尾部8步前瞻、互补排序共享节点、已探索候选J/Pd非支配档案；默认仍min-J。
- tail_repair.py：固定绝对时刻前缀、自由终点、多个尾段长度共享预算，独立原评分器重放。
- 新审计与实验脚本：已冻结协议，待通过全部历史回归后才能执行。

## 模型与结论边界

四连通、固定T、t=0不检测、先移动后探测；联合未探测权重不归一化，特殊bin质量保留。J=sum(M_t,t=1..T)，Pd=1-M_T，未加Pd约束。
动态paper_greedy只排序，不用于认证。两步前瞻仅在完整枚举及原STDC下界前提成立时构成安全下界；有限测试不等同一般ε证明。
全时刻分组在实数模型中等价，浮点求和顺序可能变化；仍要求原ID全路径重放。所有新路线默认theory_certified=false。
尚未执行真实实验，因此没有本轮J/Pd、速度、峰值内存、压缩率或新路径图。不得沿用前轮结果冒充本轮提升。

## 保全与交付

- 修改前3199个既有文件逐一SHA复核，变化0个。
- 冻结baseline 654文件、研究保护文件3255个、冻结Python源码120个均通过检查。
- final_outcome.json：机器可读blocked结论；final_preservation.json：保全证据。
- test_summary.csv、changed_files.json：测试计数及新增文件清单。
- validation/new_tests 与 validation/full_tests：command.json、stdout.txt、stderr.txt、pytest.xml、stage.json、git diff与源码SHA。
- artifact_manifest.json：本轮归档SHA-256。

## 运行命令

实际解释器：C:/Users/35448/.conda/envs/maritime-sar/python.exe。
驱动按顺序执行 scripts/run_optimization_validation.py init/new_tests/full_tests --run-dir outputs/stdc_v0_2/optimization_20261124/validation，各命令完整参数和环境见对应command.json。
新增pytest目标为 tests/test_research_particle.py、tests/test_lookahead_bound.py、tests/test_tail_repair.py、tests/test_research_search.py；全量目标为 tests。均为 -x -q -p no:cacheprovider，并输出JUnit。
后续先解决执行上下文的硬链接权限，在新的结果目录复跑未修改测试；保留本次blocked目录，不覆盖、不跳过失败项。

## 新增文件清单

- docs/stdc_optimization_protocol.md
- scripts/audit_optimization.py
- scripts/run_optimization_experiments.py
- scripts/run_optimization_validation.py
- src/asar_repro/lookahead_bound.py
- src/asar_repro/research_particle.py
- src/asar_repro/research_search.py
- src/asar_repro/tail_repair.py
- tests/test_lookahead_bound.py
- tests/test_research_particle.py
- tests/test_research_search.py
- tests/test_tail_repair.py
