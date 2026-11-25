# STDC optimization ablations

All routes uncertified; original min-J objective and scorer unchanged.
Same real historical Lake Ontario archive, all-water approximation, seed41. Repeats are not independent scenes.
Work protocol: 5000 total expansions INCLUDING lookahead auxiliary expansions, 20000 physical heap entries, 30s.
Wall protocol: 5s, no expansion cap, same 20000 physical heap entry cap. OPEN may stop a run before 5s.
Portfolio duplicates queue entries and charges both; compression preprocessing and candidate replay are timed.
Tail variants pay a 40% global seed quota then search suffix lengths 6/10/14 with the remainder. No free baseline warm start.
All methods start from the common frozen PT. Baseline stops at its first solution; actual effort differs.

|Protocol|Method|J median|Pd median|Seconds|Total work|Peak MiB|Stops|
|---|---|---:|---:|---:|---:|---:|---|
|work|paper_baseline|17.293894155|0.897370419|1.0730|1222|92.15|{'completed': 1}|
|work|anytime_reference|17.264874448|0.897364416|4.4388|5000|147.19|{'max_expansions': 1}|
|work|fast_zero|17.266645360|0.896678016|2.5274|5000|131.88|{'max_expansions': 1}|
|work|fast_mass|17.266645360|0.896678016|2.6192|5000|132.07|{'max_expansions': 1}|
|work|fast_stdc|17.264874448|0.897364416|4.5573|5000|148.95|{'max_expansions': 1}|
|work|cascade_stdc|17.264874448|0.897364416|3.9708|5000|148.47|{'max_expansions': 1}|
|work|lookahead_stdc|17.264874448|0.897364416|3.5686|5000|138.55|{'max_expansions': 1}|
|work|tail_zero|17.291968495|0.894972397|1.6916|5000|96.42|{'max_expansions': 1}|
|work|tail_stdc|17.291968495|0.894972397|2.1693|2292|102.96|{'global_seed_max_expansions': 1}|
|work|compressed_stdc|17.264874448|0.897364416|3.9685|5000|129.00|{'max_expansions': 1}|
|work|portfolio_stdc|17.291968495|0.894972397|11.0289|2935|118.12|{'max_open': 1}|

J and final Pd can trade off. Candidate archives describe encountered/replayed candidates only, never a global Pareto frontier.
Generic speedups, larger neighborhoods and multiple ordering queues are engineering techniques, not established STDC novelty.
No epsilon guarantee is inferred from finite Oracle checks or budget-stopped real searches.
