# Fixed-time window improvement for STDC (research, 2026-11-23)

This experiment addresses complete-route quality under a finite computation
budget. It adds independent modules; the frozen scorer, motion input, planning
objective, legacy A^SAR, baseline branch and earlier reports are unchanged.
Results belong to a new protocol, not an amendment of B7 or old STDC runs.

## Objective and exact suffix

The original objective remains `J = sum(M[t], t=1..T)` and final detection is
`Pd = 1-M[T]`. Frame zero is not observed. Minimizing J does not mathematically
imply maximizing final Pd; the two are measured separately. Acceptance requires
full-path J improvement greater than 1e-10, without adding a Pd constraint.

For a window [a,b], the prefix through a, the vertex at b, the absolute clock,
and the suffix after b remain fixed. Every candidate retains its entire belief
vector; equal (depth, vertex) or equal total mass do not identify a state.

Let D_t attenuate the searched cell/particle IDs at absolute frame t. Matrix
motion uses source-row stochastic P_t and b_t = D_t P_t^T b_(t-1). Define
nonnegative fixed-suffix vectors c_T=0, s_T=1 and work backwards:

    c_(t-1) = P_t D_t (1 + c_t)
    s_(t-1) = P_t D_t s_t

For particles the position sequence is already fixed, so P is replaced by the
identity on ID-indexed weights and D_t uses cell_ids[t]. Special bins retain
their mass and have attenuation factor 1. Then for every rewritten window:

    J_full = g_a + J_window + c_b^T b'_b
    Pd_full = 1 - s_b^T b'_b

Every accepted route and every returned incumbent is independently replayed by
the unchanged full-path scorer. Coefficient/replay disagreement above 1e-10 is
an assertion failure, never silently corrected.

## Bounds and their limited scope

Four local controls use the same feasible paths and schedule: zero, mass_lb,
stdc_lb, stdc_endpoint_lb. Terminal bounds include the exact fixed-suffix cost.
All modes exclude prefixes unable to reach the endpoint in exactly R steps.

At relative step k, ordinary STDC relaxes to all vertices exactly k moves away.
Endpoint STDC intersects that set with vertices exactly R-k moves from the
endpoint. The zero-step set contains only its source; no wait action is added.
Every legal completion is included in these sets. Simultaneously observing
each set yields a componentwise lower undetected belief. The original STDC
per-step mass recurrence lower-bounds window cost. Adding c_b dotted with the
final relaxed belief lower-bounds the fixed suffix because c_b is nonnegative.
These arguments require fixed nonnegative mass-preserving motion, fixed
nonnegative detection probabilities in [0,1], and the supplied discrete grid.
Random Oracle checks are finite numerical evidence, not a general proof.

Local search is unweighted best-first and uses a conservative numerical bound
guard at incumbent J + 1e-10. A completed window exhausts its endpoint-constrained
neighborhood up to the acceptance tolerance. Neither that completion nor an
unchanged whole sweep certifies a global optimum or global epsilon bound.
`theory_certified` is always false for this composite method. Original dynamic
paper_greedy remains uncertified, including when its search completes.

## Predeclared experimental allocation

All real methods receive the same frozen PT route as a supplied common input.
Its historical construction is not re-run or timed. Baseline paper_greedy gets
the total 5000 expansion / 20000 physical OPEN / 30 second search budget.
Each window method spends at most 1500 of those expansions on its own paper
seed, then uses the remaining shared budget for windows. Seed computation,
coefficient construction, local search, accepted-route replay and final replay
are all timed. An expansion subquota stop can continue locally; a global time
or OPEN stop cannot. This allocation is part of the proposed method, so the
baseline comparison includes an allocation difference. The four window
controls isolate the contribution of the local STDC bounds more directly.

The seed uses epsilon in {1.1,1.04,1.0}; local windows have no epsilon inflation.
Scan lengths 4 then 6, starts in increasing order; after each accepted rewrite,
subsequent windows rebuild beliefs and suffix coefficients from the new route.
Repeat sweeps until an entire sweep has no accepted improvement or a global
budget stops the process. There is no undisclosed iteration cap. Full routes
found just before a cooperative stop are retained. Overshoot is recorded.

Expanded counts sum across phases. Generated counts exclude roots and count
materialized child states; infeasible endpoints can be rejected geometrically
before materialization. Pruned counts include such geometry rejections. OPEN
is the maximum physical heap size across sequential phases, not their sum.
Window heuristic/candidate/replay counters describe only the local phase; seed
legacy counters are reported separately. Process peak memory includes input
verification and final external replay in an isolated worker.

## Sequential gates and interpretation

1. New hand-calculated, indexing, suffix, budget and Oracle unit tests.
2. Full existing regression suite, with no skips or xfails introduced.
3. 160 random matrix/particle toy cases, every legal window prefix vs independent DFS.
4. 35 unchanged historical small cases plus 5 stationary and 5 particle
   derivatives, two windows and four modes (360 searches).
5. Frozen real archive/forcing/scorer SHA verification and six smoke runs.
6. 45 paired real runs: five methods, three epsilons, three repetitions.

Any historical test, admissibility or replay failure blocks later stages.
Every stage retains command, seed, stderr, JSON, source fingerprints and diff.
Real data never use synthetic replacement. Earlier baseline and result files
are checked byte-for-byte before and after the run. Conclusions distinguish
route improvement, bound-specific improvement, budget effects and unverified
generalization beyond the single frozen scenario. Global anytime/MHA changes,
new forcing, a changed objective and a second innovation are out of scope.
