# Rollout escape strategy review

This is a code and artifact review, not a new benchmark or a claim of improvement. Production code, objective, scorer, forcing, and prior outputs were not edited.

## What the current proposal family can change

- `short_window_rollout.py:63` permits only 4/6/8-step windows. `:182` fixes the window's end vertex to the incumbent's vertex at the same absolute time; `:284` appends the entire unchanged suffix. Each candidate is a local route substitution inside this restricted family, not an independent full-route attempt.
- `:173` ranks windows by the best *one-step* missed detection under the incumbent belief, weighted by remaining horizon. It cannot recognize the value of a temporarily unrewarding relocation which reaches a different plume several steps later. Such a useful window could have zero opportunity score and be scheduled late.
- `:228-274` preserves only 24 quality states plus at most four extra signature states. Its diversity signature (`:215-226`) uses the maximum residual spatial mass block and incoming direction, not an independently changed target cluster sequence. Wider directional variety can still follow the same overall detection strategy.
- `adaptive_search.py:129-154` grants local work at most 10% of paid global work, in bursts of at most 128 expansions and 0.1 seconds, then cools down unproductive windows. This is reasonable damage control under a short budget, but a negative outcome is not an exhaustive neighborhood result.
- A clean distinction is essential: the older `midpoint_rollout.py:1-8` already regrows a free-endpoint full suffix. It uses three incumbent detection-quantile anchors (`:154-158`) and beam selection based on the same paper ordering guide. Calling another free-endpoint suffix beam a new escape mechanism would repeat an existing experiment.

## One preferred direction: an independent exact repair oracle, then event-directed large repairs

First establish whether an improvement *exists* outside the tested short neighborhood. Build an opt-in time-expanded mixed-integer repair oracle on the same frozen ParticleMotion input. This is a diagnostic alternative to the present guide/beam, not a replacement objective and not a promise of better wall-time performance.

Fix an incumbent prefix through absolute time a, then jointly optimize the entire suffix with a free final endpoint. Use a small connected space-time corridor initially, including the incumbent and an alternative reachable residual-mass cluster. Widen the corridor or move a earlier only when the preceding model is solved. A corridor-optimal result is only corridor-optimal; it is never a global certificate.

An exact model for the current deterministic particle archive is available without approximating detection:

- Binary x[t,v] is one at the unique search cell at absolute time t. One cell per time, the fixed starting position, and x[t,v] <= sum(x[t-1,u] for u adjacent to v) enforce the unchanged four-neighbor, no-wait path rules.
- For particle i with fixed cell c[i,t], let w[i,t] be its undetected weight. Define z[i,t] = w[i,t-1] * x[t,c[i,t]], and w[i,t] = w[i,t-1] - q[c[i,t]] z[i,t]. With M = w[i,a], enforce 0 <= z <= w[i,t-1], z <= M x, and z >= w[i,t-1] - M(1-x). These linear constraints are exact when x is binary. Special/outside bins have z=0 and their entire mass remains in w and J.
- Minimize the original g[a] + sum_{t=a+1..T} sum_i w[i,t]. At a=0, the known input weights apply before any detection, preserving t=0 semantics. Pd is measured only afterward as 1-sum_i w[i,T], using the unchanged scorer.
- The exact objective can combine intervals with no possible detection; identical future cell trajectories may share coefficients with summed weights while retaining an ID mapping for original replay. This is an optional exact compression, not particle truncation.

The diagnostic question is precise: does a verified feasible route with J < incumbent_J - declared numerical tolerance exist? A found, independently replayed route disproves near-optimality at that improvement scale. A solved restricted model establishes only the tested corridor/prefix's optimum. A time limit, positive solver gap, or weak lower bound leaves the question unresolved. Do not label a solver's no-incumbent timeout as “no improvement exists.”

This is materially different from the older suffix beam: it does not irrevocably discard promising partial paths because the common guide ranks them outside width 24, and it provides a restricted-model lower bound or an explicit unfinished status. The model may be too expensive; that is a hypothesis to test rather than conceal.

Once an improving repair is found, record its first divergence, transit length before the first new detection, changed target-cluster order, and rejoin/terminal change. Use that witness to define a practical event-directed repair operator: choose a reachable future detection event in a residual cluster, release the prefix before the necessary turn, and rebuild that route plus its whole remaining suffix. Evaluate complete routes by original J only. Do not return to a fixed suffix too early or compare truncated local gains. Avoid proposing a wholly new optimization mechanism until this witness identifies which missing freedom actually matters.

## Falsification and acceptance sequence

1. Exact DFS on the current tested 4/6/8-step fixed-endpoint windows: compare the local optimum to beam output with identical prefix belief and exact unchanged suffix. If DFS improves, the beam/ordering caused loss; if not, the tested restricted neighborhood is exhausted, not the full problem.
2. On toy particle instances, compare the independent repair formulation with DFS for fixed endpoints, free endpoints, fixed suffixes, free suffixes, q=0/q=1, special bins, and dynamic absolute times. Include a crafted instance whose only better path requires a zero-detection transit followed by a different cluster, so a one-step opportunity score has no useful signal.
3. On each SHA-verified real archive, use nested neighborhoods: current fixed-endpoint short window; same start with released endpoint and jointly repaired suffix; earlier prefix with alternative cluster corridor. First seek a witness with a separately declared diagnostic budget. The expensive diagnostic is not counted as an equal-budget competitive win.
4. Only if a witness exists, implement its event-directed repair and compare with direct STDC under the same end-to-end 5-second budget and a second predeclared wall-time budget. Mixed-integer nodes and A* expansions are not comparable units; record both but use elapsed time/RSS as the primary fair budget. Include all model construction, seed search, and replay costs, use the same common initial PT, and do not give the new method a free best STDC route.
5. Keep J as the sole acceptance objective. Report Pd independently, including a J improvement/Pd decrease tradeoff; do not silently require or reward Pd in the search. Reuse Fundy's physical_direction_unverified=true label.

The decisive outcomes are: (a) a verified nonlocal improvement identifies missing search freedom; (b) a small valid gap over the full feasible domain supports near-optimality for that frozen discrete instance; (c) neither is obtained, so global proximity remains unknown. A count of 270 local completions alone supports neither (a) nor (b).
