# STDC v0.2 第三轮验证：blocked

日期：2026-11-23。研究分支：stdc-research-v0.2。测试源码提交：133ea41359d0a4935ef26e3d39fcfcf3f2bccf78。

用户已明确授权追加旧基线只读权限并启动验证。管理员辅助脚本已执行：只向 JDD/35448 追加限定目标的 RX 读取/遍历权限，涉及 36 份原文件和 6 个父目录。没有改写文件内容、修改所有者或追加写权限。原 ACL 保存于 access_acl_before.json；命令和回执保存在 grant_baseline_read_access.ps1、access_repair.log、access_repair.json。权限修复后全部 654 份原基线文件 SHA-256 一致。

## 执行结果

| 阶段 | 本轮结果 |
|---|---|
| 原始文件访问恢复与指纹检查 | passed；654 份指纹一致 |
| 新测试 | 28 passed，0 failed / errors / skipped |
| 全量历史测试，pytest -x | blocked；23 passed，1 failed，实际执行 24 项 |
| 随机逐前缀 Oracle | 未执行 |
| 35 组小图搜索 | 未执行 |
| Lake Ontario 两组 smoke | 未执行 |

新测试包括交付原 19 项 STDC 测试、5 项源码审计边界负向测试、4 项路径回放与错误认证负向测试。28 项通过不等于所有数学性质或完整研究版本已验收。完整收集预计为 281 项，本轮没有验证其完整执行结果。

## 首次失败证据

失败节点：

`tests/test_b1_inventory.py::test_wind_acquisition_rejects_full_object_or_saves_exact_messages[True]`

第 135 行调用 fetch_wind；实际失败为 `scripts/fetch_lake_b1.py:23` 的 `os.link(tmp, target)` 抛出 `PermissionError: [WinError 5]`。

两个硬链接路径均位于 Codex 的 Windows 沙箱临时目录 `.../AC/#!sandbox.{...}/Temp/pytest-of-35448/...`。这是新出现的硬链接访问失败，与上轮旧 baseline 文件读取权限问题不同。测试中 urlopen 已由 monkeypatch 替换为 BytesIO 假响应，没有发起真实 forcing 下载。失败发生于文件发布操作，尚未到达该测试的内容校验断言，更没有执行到 STDC 可采纳性审计。仅凭这个失败不能推断 STDC 算法有错，也不能据此宣告所有其他历史测试正常。

失败后没有修改下载器、放宽断言、跳过用例或重跑测试；也没有进入后续实验。stderr 中另记录 pyreadline3 析构时的控制台 OSError，原样保留。

## 命令与证据

使用现有 `C:/Users/35448/.conda/envs/maritime-sar/python.exe`，不安装或升级依赖。离线保护启用；OMP/OpenBLAS/MKL/NUMEXPR 均设为单线程。

本轮按顺序执行：

```powershell
& $PY scripts/run_stdc_local_stage.py new_tests --run-dir outputs/stdc_v0_2/local_validation_20261123_r3
& $PY scripts/run_stdc_local_stage.py full_tests --run-dir outputs/stdc_v0_2/local_validation_20261123_r3
```

每个阶段的 stage.json 保存完整 pytest subprocess 参数、seed、版本、实际计数和运行时间；stdout.txt、stderr.txt、pytest.xml 及阶段前后 git diff、源码 SHA 均已保存。validation_summary.json 总状态为 blocked。前两轮的 blocked 记录保持不变。

## 停止后的保护核验

post_stop_preservation.json 再次确认原 654 份文件全部未变，研究副本的保护文件及明确授权改动均与预检指纹一致。baseline-v1.1 仍指向 81b9be9b51625ed9012a69f9cb90e296bf2ec5c2。评价器、原 B7、规划目标、forcing、粒子归档与原仿真程序均未修改。

没有运行真实或合成替代 smoke，没有运行 Leeway，没有新增 ε 最优认证，没有开展创新点二。

下一轮应先确认测试执行环境能够在独立临时目录创建硬链接，必要时使用获准的非沙箱测试进程，然后另建尝试目录从新测试、全量测试重新开始。这里不把该环境修复预判为已成功，也不恢复已中止的实验序列。
