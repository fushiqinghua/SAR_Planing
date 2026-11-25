# Near-optimality evidence audit

Read-only audit of the three frozen historical inputs. No search, OpenDrift run, evaluator change, or forcing change. The `load_case` loader reverified the existing archive and forcing gates before three compact-DP constructions and root queries. `bounds.json` has full numerical values and run profiles; stdout/stderr are retained. Fundy remains physically direction unverified.

| Scene | Feasible direct STDC U | root STDC L | root particle DP | (U-L)/U |
|---|---:|---:|---:|---:|
| Lake Ontario | 17.264874448 | 9.179977674 | 5.691508495 | 46.83% |
| Hudsons Bay | 20.386109349 | 10.479531342 | 5.381820713 | 48.59% |
| Bay of Fundy | 45.881082400 | 42.448240000 | 24.871000642 | 7.48% |

The numerical bounds are conditional on the frozen discrete model and existing tested Float64 implementations; this audit is not an outward-rounded proof. A large interval is uncertainty, not proof of an improving feasible route. The Fundy interval is narrower, but cannot establish a sub-percent optimum gap. None supports calling the incumbent globally optimal.

All 18 prior-STDC runs stopped on budgets. In the 5000-expansion protocol their remaining frontier counts are 14539 / 13711 / 11759. The reported best-J plateaus are not frontier exhaustion. The saved reports lack all remaining path-dependent states and an admissible global minimum, so a tighter completed-run bound cannot be recovered from them. The weighted paper-guide priority is an ordering estimate, never a lower bound. A future diagnostic checkpoint must also include pending popped nodes, partially expanded parents/unemitted children, and held OPEN-limit children; taking only the visible heap minimum risks excluding feasible descendants.

Independent-particle DP lets each target particle choose its own ideal route. In symbols, sum_i b_i min_path C_i(path) <= min_path sum_i b_i C_i(path). This removes the crucial competition for one common searcher path. All three root DP bounds are weaker than root STDC; successful memory compression does not itself strengthen this relaxation. Bounds may still cross at deeper path-dependent states, so root comparisons do not prove general dominance.

The earlier Lake LP (`trajectory_20261124/real_diagnostic/result.json`) exhausted its wall limit during dual verification, exported only lower_bound=0, and gave no tighter verified bound. Its primal/solver status must not be used as an optimum certificate.

To separate restricted search from local optimality, freeze one existing incumbent per scene and enumerate all short fixed-endpoint bridge replacements without beam truncation. Record a local exact optimum separately from each beam result. If exact bridge enumeration improves but beam does not, the beam/ordering/budget is at fault. If the exact bridge optimum ties, release the endpoint and reoptimize the suffix, then expand the neighborhood to longer/two coordinated windows. Any independently replayed lower-J path disproves global optimality. No improvement from finitely many neighborhoods proves only neighborhood-level optimality unless a covering full-tree bound closes.

J=sum_t M_t is cumulative survival; Pd=1-M_T is terminal detection. Strictly lower J can accompany lower Pd. The frozen Lake paper baseline has J=17.29389415456, Pd=.89737041888, while direct STDC improves J to17.264874448 but Pd is .897364416. Keep J as the acceptance objective and report Pd separately; do not redefine the goal to force joint improvements.
