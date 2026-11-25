# Trajectory iteration: frozen before experiments

Date: 2026-11-24. Branch: stdc-research-v0.2. Target incumbent J = 17.264874448.

No modification to the original objective, evaluator, baseline, archived results, or forcing.
J = sum of undetected mass after each detection at t=1..T. No sensing at t=0.
Pd = 1 - final undetected mass; a better J need not increase final Pd.
All proposed searches remain uncertified, including completed beam searches.

## Ordered gates

1. Independent time-expanded LP/MILP diagnostic: new pytest, full pytest, 12 seeded toy cases (63000..63011), MILP versus exhaustive DFS and LP against every prefix optimum. Only then SHA-gated historical Lake Ontario LP (30 seconds). A feasible LP primal objective is never a lower bound. A loose gap does not prove improvement is possible.
2. Only after gate 1: implement independent-particle dynamic programming and midpoint suffix rollout; new pytest, full pytest, random prefix and small search audits, smoke, real comparison.
3. Any historical test failure or admissibility failure blocks dependent stages. Preserve failures. No bypass or synthetic substitution.

## Planned comparisons (no post-result parameter tuning)

Methods: frozen paper_baseline; prior_stdc; compressed_stdc; dp_only; stdc_dp; mid_plain; mid_diverse; mid_dp.
All start from the same frozen PT route. No free warm start from the archived best route.
DP and compression preprocessing are charged to method wall time and peak process memory.
work protocol: 5000 total expansions, 20000 open entries, 30 seconds.
wall protocol: 5 seconds, 20000 open entries, no expansion limit.
Each method: a small smoke run, then three isolated repeats in each protocol.
Guide weight 1.04; rollout beam 24; at most three anchors just before cumulative detection reaches 25%, 50%, 75% of the seed path final Pd.
Midpoint methods use 40% of the work/time budget for seed search and share the remainder among anchors. Rebuild the whole suffix; no endpoint constraint.
mid_plain versus mid_diverse changes only candidate diversity retention; mid_dp uses max(STDC, independent-particle DP).
Beam discards are proposal losses, not admissible pruning. No state merging by depth/vertex.
Independent DP has one feasible path per particle and therefore relaxes the shared searcher route. Its max with STDC is admissible only under the unchanged fixed exogenous trajectory/detection model.

Record original archive replay J/Pd/legal paths, incumbent source, actual expansions including seed, completion versus explicit stop reason, precomputation time/operations, peak RSS, command/seed/stdout/stderr/JSON/CSV/plots/git diff. SHA-check archived forcing, particles, metadata, time grid, and evaluator before real work. Save results in this new directory only.
