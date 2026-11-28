# P2/H3 本地执行

从 ASAR 项目目录使用现有 maritime-sar Python。研究任务顺序以随机种子 2026112823 预先固定，先打乱日期、粒子 seed 和重复组成的区块，再在区块内打乱 C0 与 Lazy。结果写入本批次的本地结果目录。

    python scripts/h3_acquire.py lock-method
    python scripts/h3_acquire.py acquire
    python scripts/prepare_eight_neighbor_h3.py qualify

资格快照列出每组登记日期的状态、证据与下一组待核验日期。发生传输故障时可对同一日期用 `acquire --retry-transport --block ID`，排查结果保留在独立下载尝试目录。HYCOM 可使用 `--provider hycom --hycom-access dap` 下载同一官方年归档，保留原始 DAP2 数组、CF 元数据和时间轴。HYCOM OPeNDAP 时间索引来自官方原生 UTC 轴。NCSS 与 OPeNDAP 的同期交叉核验比较相同 UTC、网格和 CF 解包前后的数组。

地区候补只在不可用归档或其他已核验的资格失败后开放。读取资格快照，按登记顺序用 `acquire --block ID` 获取已开放的候补，再运行 `qualify`。六日全部合格后按以下顺序执行。

    python scripts/run_eight_neighbor_h3.py validate
    python scripts/prepare_eight_neighbor_h3.py prepare
    python scripts/prepare_eight_neighbor_h3.py verify-inputs
    python scripts/run_eight_neighbor_h3.py freeze
    python scripts/run_eight_neighbor_h3.py s30
    python scripts/run_eight_neighbor_h3.py e30
    python scripts/run_eight_neighbor_h3.py analyze

脚本在进入 S30 前重验测试、原始 forcing、十二份 OpenDrift 粒子档案及预注册方法。E30 还重验十二条共享 S30 路线和两个独立评分结果，每项任务的算法耗时上限为 30 秒。运行和重放分开计时。已完成任务可在同一批目录重新核验。失败的试验保存证据并停止。新的批次目录可显式指定为 `--out outputs/second_innovation_h3_20261128/local_r2`。

Windows 若 pytest 的硬链接检查受限制，可将 `ASAR_H3_PYTEST_PARENT` 设为验证进程可写的本地目录，再运行相同测试。验证记录包含运行命令、退出码、标准输出、标准错误和 JUnit XML。

原始下载位于 `data/raw/h3`，粒子、协议、逐项试验和报告位于 `outputs/second_innovation_h3_20261128`。UTC 日窗、来源、失败下载尝试、替代情况、资源和同一路线 J/Pd 见该目录内的 JSON 和 CSV。LOOFS 历史 nowcast 的实时可用性未验证，本协议属于历史天气重建。
