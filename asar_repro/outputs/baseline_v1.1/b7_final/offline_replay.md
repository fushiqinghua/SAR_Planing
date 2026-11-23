# Baseline v1.1 离线复跑与恢复

本地已有 maritime-sar 环境时，在 asar_repro 下执行一条命令：

    & 'C:\Users\35448\.conda\envs\maritime-sar\python.exe' scripts/replay_baseline_v1_1.py

可将命令中的解释器替换为已有兼容环境，使用 --output-dir 指定新的 outputs/baseline_v1.1 子目录。入口为 Python，不执行 PowerShell 脚本或更改系统执行策略。脚本不安装或升级依赖，禁用 Python 出站 socket 连接及 PROJ 网络；每次输出到新目录，完整执行验收、重新积分、重放、报告和新归档。正常退出为 0；任一门槛失败退出 2，汇总标记 blocked。耗时与内存是新的测量，不要求与旧值完全相同。

离线包包含代码、配置、测试、已缓存原始风流、粒子和 B0–B6 结果、B7 复验证据、Git bundle 与 payload_sha256.json。它不包含 Conda 二进制环境；须事先备妥 methods_and_environment.json 所列兼容环境，不得靠隐式升级解决复跑失败。

恢复到另一位置：先展开 ZIP 到 staging，找到其中的 baseline_history.bundle；使用 git clone --config core.autocrlf=false -b baseline-v1.1 <bundle绝对路径> <新的仓库目录>，再将 staging/asar_repro 的文件覆盖到新仓库的 asar_repro 子目录（恢复自己的新目录，不覆盖当前工程）。关闭该新仓库的自动换行转换，以保留冻结字节。Git bundle 保存 B6 起始 HEAD 及 v1.0 标签；ZIP 附带本次新增 B7 文件，其字节由 payload_sha256.json 保护。随后在新目录运行上述单条命令。若旧 v1.0 工作树不在恢复位置，Git 对象的 180 份字节校验仍会执行，报告明确区分对象恢复证据与原工作树现场证据。

ZIP 的 SHA-256 存于 archive_checksum.json，包内每个条目在创建后都重新读取计算 SHA-256。最终验证报告和 validation_summary.json 是 ZIP 校验后的交付侧文件，位于 ZIP 旁，避免自引用指纹。首次归档不包含自身，也不重复打包过往 ZIP/bundle。

仅重做有限检查时，可以分别运行（目标目录必须新建，不能指向旧输出）：

    python -m pytest -q
    python scripts/validate_forcing.py --output outputs/baseline_v1.1/NEW/forcing_audit.json
    python scripts/generate_historical_drift.py --verify-replay
    python scripts/compare_b6.py --output-dir outputs/baseline_v1.1/NEW/b6

本次协议只冻结实验，不实施创新算法。真实环境与合成环境不能混入同一算法主排名；条件性模型界与实验数值分开报告。
