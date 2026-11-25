# Global anytime search protocol (2026-11-24)

Primary objective: improve the best already tested baseline J=17.29389415456
on the frozen Lake Ontario input without changing the min-J objective, motion,
observations, scorer, original search, or previously recorded results.

The new search uses one priority heap ordered by g + w*h_paper. This is a
search-order heuristic only: dynamic paper_greedy is not assumed admissible.
It never justifies pruning, a first-goal exit, or an epsilon certificate.
Complete candidate paths update a retained incumbent and search continues.
The three controls differ only in the bound used on popped prefixes: zero,
mass_lb, or stdc_lb. This unweighted bound independently prunes when
g+h_bound >= incumbent_J+1e-10. Nonnegative future costs also permit cheap
g-based pruning. The plus tolerance is conservative against roundoff.

No states are merged, even at equal depth/vertex/cost. Each keeps its complete
conditional belief, preserving particle IDs and absolute frames. All feasible
successors are considered unless an explicit budget stop interrupts the whole
search. OPEN cap never silently drops a branch. A candidate that may improve
the full J is replayed with the frozen evaluator before strict acceptance at
J < incumbent_J-1e-10. Initial and final incumbents are also replayed.

The bounds rely on fixed nonnegative mass-preserving motion, q in [0,1], the
supplied four-neighbor/no-wait graph, and the joint undetected-mass state. The
existing dynamic counterexample remains a mandatory test. The method is a
research anytime branch-and-bound search, not a claimed implementation of MHA.
All returned routes are labeled uncertified, including budget stops. Frontier
exhaustion is described only relative to the finite discrete model and the
numerical tolerance. Random toy checks establish local numerical facts, not a
general theorem or a new proof of the paper's dynamic epsilon guarantee.

The real experiment is predeclared: unchanged paper baseline and three anytime
controls; weights 1.04 (primary), 1.1 and 1.0; three repeated timings each, 36
runs total. Six smoke runs precede them. Every method receives the same frozen
PT path and the same 5000 expansion / 20000 physical OPEN / 30 second caps.
No method receives a free best-baseline path, and there is no separate seed
subbudget. Actual runtime differs: legacy baseline still stops at its first
goal whereas anytime may spend the remaining budget. Bound evaluations that
prune a popped node count as computation/time but not successor expansions;
guide/bound counts and time are reported separately. Cooperatively checked
deadlines retain just-generated, validated improving complete candidates.

Each worker verifies frozen real forcing/particle/metadata/scorer SHA, performs
independent replay, and records status, reason, incumbent source/history, J/Pd,
expanded/generated/pruned/OPEN, peak process memory, runtime and overshoot.
Validation sequence is new tests, all 431 prior tests plus new tests, 160-case
existing STDC per-prefix Oracle audit, and 45-case/405-search global Oracle
audit, followed by real smoke and benchmark. Failure blocks later stages.
Old baseline and window artifacts are fingerprinted before and after.

The strongest comparison is against the frozen best J across baseline
settings, not merely the weak epsilon=1 budget-stop result. Final Pd is a
separate metric; the report also compares it with the best-J baseline's Pd and
the maximum baseline Pd across settings. Any gains shared by zero/mass/STDC
belong to the anytime framework; STDC-specific gains require control-group
evidence. Three repeats on one archive measure timing, not generalization.
No post-result parameter changes, new forcing, or second innovation are part
of this protocol. Broader cases and equal actual wall-time comparisons remain
separate follow-up experiments if this gate succeeds.
