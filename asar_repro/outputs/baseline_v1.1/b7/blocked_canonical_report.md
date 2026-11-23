# Baseline v1.1 最终验证报告

**B7 状态：blocked。**

复跑基准 Git commit：624d2176c206b8f7df852975708f0ae510626820；v1.0 标签：abd1b472798fbf3d318e83d09caf9b69cc459122。
B7 仅新增验证、归档、报告与实验协议文件；数值核心与已验收实验不修改。新增验证脚本通过源码指纹及 ZIP 成员清单记录，Git bundle 保存复跑时 HEAD。

| 强制门槛 | 状态 | 证据/失败原因 |
|---|---|---|
| frozen_integrity | passed | {'v1_commit': 'abd1b472798fbf3d318e83d09caf9b69cc459122', 'v1_files': 180, 'git_blobs_verified': True, 'original_worktree_present': True, 'original_worktree_verified': True, 'intentional_v1_1_changes': ['asar_repro/src/asar_repro/planner_adapter.py'], 'frozen_file_count': 426, 'real_files': 10} |
| full_pytest | passed | {'passed': 234, 'pytest_s': 26.99, 'command': ['C:\\Users\\35448\\.conda\\envs\\maritime-sar\\python.exe', '-m', 'pytest', '-q'], 'exit_code': 0} |
| dynamic_counterexample | passed | {'h': 2.617080177088715, 'oracle_J': 2.541733337874664, 'overestimate': 0.07534683921405083, 'paper_certified': False} |
| real_forcing | passed | {'status': 'passed', 'files': 10, 'exact_fields_samples_controls': True} |
| constant_regression | passed | {'arrays': 18, 'exact_equal': True} |
| real_particle_reintegration | passed | {'stage': 'B3', 'status': 'passed', 'mode': 'independent_replay', 'config_hash': 'b7f8f7261148f6e9cf9a4cb68a0ab3e751f729a666c9b977f9e5646ccfec7ca8', 'archive_sha256': '8b30a87e543f1b33c39e70e1d0054e1750ec046ba2e0b627dd311d9945749456', 'native': {'first_utc': '2025-08-26T14:45:00Z', 'last_utc': '2025-08-26T15:53:00Z', 'frames': 137}, 'search': {'first_utc': '2025-08-26T15:45:00Z', 'last_utc': '2025-08-26T15:52:33.74Z', 'frames': 50}, 'compared_npz_arrays': 21, 'exact_replay': True, 'forcing_terminal_events': 0, 'archive_integration_seconds': 6.837059700046666, 'runtime_seconds': 9.396643600077368} |
| all_path_replay | passed | {'old_normalized_records': 527, 'old_marine_paths': 436, 'old_marine_max_error': 8.526512829121202e-14, 'additional_record_groups': {'b5/scan_runs.json': 38, 'b5/pilot_runs.json': 6, 'lake_ontario_real/runs.json': 7, 'outputs\\baseline_v1.1\\b6_failed_attempt_01\\b6_workers\\paper_greedy_1.1.json': 1}, 'toy_rows': 72, 'max_real_replay_error': 2.7755575615628914e-17} |
| performance_evidence | passed | {'main_scan_runs': 36, 'stop_distribution': {'completed': 10, 'max_expansions': 26}, 'probe_stops': {'max_open': 2}, 'peak_process_MiB_range': [66.90625, 152.66015625], 'certified_runs': 0} |
| b6_offline_rerun | passed | {'runs': 7, 'exact_paths_scores_counters_status': True, 'timing_remeasured_separately': True} |
| old_outputs_unchanged | passed | {'files': 426, 'all_unchanged': True} |
| offline_archive | passed | {'path': 'outputs\\baseline_v1.1\\b7\\baseline_v1_1_offline.zip', 'sha256': '2257d28aa6754c19c9fbe5dbba8de4dbb5686d0d829f4253f82fd62624844507', 'bytes': 286083927, 'verified_entries': 432, 'git_bundle_sha256': '67192eb11afd8c0f74d1518007828f53df63ea461fb91fbde352ec735972d581', 'raw_forcing_included': True, 'reports': 'final report and validation_summary are sidecars generated after ZIP verification'} |
| restored_entrypoint | blocked | PowerShell script execution policy rejected the .ps1 entrypoint. Python replacement will be validated in a fresh B7 run. |

存在未通过的强制门槛。此次不定版、不开放创新阶段绿灯；请查阅同目录 validation_summary.json 与命令日志。
旧实验数值不构成本轮验收通过证据。未实施创新点。
