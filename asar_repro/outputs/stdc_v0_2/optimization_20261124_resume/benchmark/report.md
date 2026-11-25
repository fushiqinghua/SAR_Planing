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
|work|paper_baseline|17.293894155|0.897370419|1.0469|1222|92.14|{'completed': 3}|
|work|anytime_reference|17.264874448|0.897364416|4.6070|5000|147.57|{'max_expansions': 3}|
|work|fast_zero|17.266645360|0.896678016|2.4944|5000|131.74|{'max_expansions': 3}|
|work|fast_mass|17.266645360|0.896678016|2.4338|5000|131.64|{'max_expansions': 3}|
|work|fast_stdc|17.264874448|0.897364416|3.8240|5000|148.39|{'max_expansions': 3}|
|work|cascade_stdc|17.264874448|0.897364416|3.8658|5000|148.36|{'max_expansions': 3}|
|work|lookahead_stdc|17.264874448|0.897364416|3.3745|5000|138.48|{'max_expansions': 3}|
|work|tail_zero|17.291968495|0.894972397|1.3261|5000|96.49|{'max_expansions': 3}|
|work|tail_stdc|17.291968495|0.894972397|1.9047|2292|103.09|{'global_seed_max_expansions': 3}|
|work|compressed_stdc|17.264874448|0.897364416|3.6030|5000|128.53|{'max_expansions': 3}|
|work|portfolio_stdc|17.291968495|0.894972397|10.3980|2935|118.29|{'max_open': 3}|
|wall|paper_baseline|17.293894155|0.897370419|0.9755|1222|92.44|{'completed': 3}|
|wall|anytime_reference|17.264874448|0.897364416|5.0202|6170|165.44|{'max_seconds': 3}|
|wall|fast_zero|17.264874448|0.897364416|4.9785|43465|176.83|{'max_open': 2, 'max_seconds': 1}|
|wall|fast_mass|17.264874448|0.897364416|5.0239|36511|164.51|{'max_seconds': 3}|
|wall|fast_stdc|17.264874448|0.897364416|5.0154|6669|175.34|{'max_seconds': 3}|
|wall|cascade_stdc|17.264874448|0.897364416|5.0165|6715|175.52|{'max_seconds': 2, 'max_open': 1}|
|wall|lookahead_stdc|17.264874448|0.897364416|5.0185|7573|173.14|{'max_seconds': 3}|
|wall|tail_zero|17.291968495|0.894972397|2.2838|12040|167.25|{'max_open': 3}|
|wall|tail_stdc|17.291968495|0.894972397|2.1366|2689|108.97|{'global_seed_max_seconds': 3}|
|wall|compressed_stdc|17.264874448|0.897364416|4.5893|6887|150.30|{'max_open': 3}|
|wall|portfolio_stdc|17.293894155|0.897370419|5.0055|1369|93.79|{'max_seconds': 3}|

J and final Pd can trade off. Candidate archives describe encountered/replayed candidates only, never a global Pareto frontier.
Generic speedups, larger neighborhoods and multiple ordering queues are engineering techniques, not established STDC novelty.
No epsilon guarantee is inferred from finite Oracle checks or budget-stopped real searches.
