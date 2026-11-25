#!/usr/bin/env python3
"""Finite, reproducible STDC assessment on existing immutable particle archives.

Run from any directory with Python providing numpy/scipy/psutil. Each measured
task runs in a fresh, serial child. No original code or archived input is edited.
The freeze stage precedes measurements; source/input mismatches fail closed.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import random
import statistics
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT / "src"))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def clean(value):
    """Strict JSON, including numpy values and unavailable numerical quantities."""
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if hasattr(value, "tolist"):
        return clean(value.tolist())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(clean(data), ensure_ascii=False, indent=2,
                              allow_nan=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def source_inventory(config_path):
    files = sorted((ROOT / "src/asar_repro").glob("*.py"))
    files += sorted((ROOT / 'tests').glob('*.py'))
    files += [Path(__file__), Path(config_path)]
    audit = ROOT / "scripts/audit_stdc_final_theory.py"
    if audit.exists():
        files.append(audit)
    return {str(p.relative_to(ROOT)): digest(p) for p in files}


def environment():
    import numpy as np
    import scipy
    import psutil
    from scipy.optimize._highspy import _core as h
    cpu_model = platform.processor()
    if Path('/proc/cpuinfo').exists():
        cpu_model = next((line.split(':', 1)[1].strip() for line in
            Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')), cpu_model)
    return dict(python=sys.version, executable=sys.executable,
                platform=platform.platform(), machine=platform.machine(),
                cpu_count=os.cpu_count(), cpu_model=cpu_model,
                physical_memory_bytes=psutil.virtual_memory().total, numpy=np.__version__,
                scipy=scipy.__version__, psutil=psutil.__version__,
                native_highs=h._Highs().version(),
                thread_environment={k: os.getenv(k) for k in
                    ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")})


def load_scene(config, name):
    import numpy as np
    from asar_repro.grid import GridGraph
    from asar_repro.motion import ParticleMotion
    from asar_repro.objective import score_path
    s = config["scenes"][name]
    for key, expected in (("particle_path", "particle_sha256"),
                          ("metadata_path", "metadata_sha256")):
        if digest(ROOT / s[key]) != s[expected]:
            raise ValueError(f"input hash mismatch: {name} {key}")
    with np.load(ROOT / s["particle_path"], allow_pickle=False) as archive:
        cells = archive["cell_ids"].copy()
        weights = archive["initial_weights"].copy()
        ids = archive["trajectory_id"].copy()
        utc = archive["time_utc"].copy()
        config_hash = str(archive["config_hash"].item())
    mission = s["mission"]
    grid = GridGraph(*mission["grid_rows_cols"])
    budget = mission["budget"]
    if cells.shape != (budget+1, mission["particles"]):
        raise ValueError("archive dimensions disagree with frozen mission")
    if len(np.unique(ids)) != len(ids) or not np.all(np.isfinite(weights)):
        raise ValueError("invalid IDs or weights")
    if np.any(weights < 0) or abs(float(weights.sum())-1) > 1e-12:
        raise ValueError("initial probability mass invalid")
    elapsed = (utc-utc[0]) / np.timedelta64(1, "s")
    if not np.allclose(elapsed, np.arange(budget+1)*mission["step_s"], atol=1e-4, rtol=0):
        raise ValueError("search UTC time axis mismatch")
    expected_start = np.datetime64(mission["cst_utc"].removesuffix("Z"), "ns")
    if utc[0] != expected_start:
        raise ValueError("archive start UTC mismatch")
    motion = ParticleMotion(cells, grid.size, ids)
    cfg = dict(start=s["initial_path"][0], budget=budget, p=weights,
               q=mission["audit_q"], motion=motion)
    scores = {}
    for route, j, pd in (("initial_path", "PT_J", "PT_Pd"),
                         ("reference_path", "reference_J", "reference_Pd")):
        z = score_path(grid, s[route], **cfg)
        if abs(z.J-s[j]) > config["tolerance"] or abs(z.pd_final-s[pd]) > config["tolerance"]:
            raise ValueError(f"frozen route replay mismatch: {name} {route}")
        scores[route] = dict(J=z.J, Pd=z.pd_final)
    info = dict(particle_sha256=s["particle_sha256"], metadata_sha256=s["metadata_sha256"],
                config_hash=config_hash, shape=list(cells.shape),
                stable_trajectory_ids=True, initial_mass=float(weights.sum()),
                special_mass_by_step=[float(weights[c >= grid.size].sum()) for c in cells],
                utc_start=str(utc[0]), utc_end=str(utc[-1]),
                original_route_replays=scores,
                physical_direction_unverified=s["physical_direction_unverified"],
                raw_forcing_reaudited=False)
    return grid, cfg, s, info


def freeze(config, config_path, out):
    protocol_path = out / "protocol.json"
    if protocol_path.exists():
        verify(config_path, out)
        print("Existing protocol verified; no overwrite.", flush=True)
        return
    validations = {name: load_scene(config, name)[3] for name in config["scenes"]}
    # All original tracked source modules must still match the base commit.
    original_files = subprocess.check_output(
        ['git', 'ls-tree', '-r', config['base_commit'], '--', 'asar_repro/src/asar_repro'],
        cwd=REPO, text=True).splitlines()
    original_snapshot = {}
    for entry in original_files:
        metadata, relative = entry.split('\t', 1)
        _, kind, original_sha = metadata.split()
        if kind != 'blob':
            continue
        data = (REPO / relative).read_bytes()
        actual_sha = hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        if actual_sha != original_sha:
            raise ValueError(f'original source changed: {relative}')
        original_snapshot[relative] = original_sha
    validation = out / 'validation'
    required = ['pytest.log', 'junit.xml', 'theory_audit.json']
    if any(not (validation / name).is_file() for name in required):
        raise ValueError('freeze requires saved pytest/JUnit and independent theory audit evidence')
    import xml.etree.ElementTree as ET
    suites = ET.parse(validation / 'junit.xml').getroot()
    if any(int(x.attrib.get(k, 0)) for x in suites.iter('testsuite') for k in ('failures', 'errors', 'skipped')):
        raise ValueError('test evidence contains a failure, error or skipped test')
    audit = json.loads((validation / 'theory_audit.json').read_text())
    if audit.get('status') != 'passed':
        raise ValueError('independent theory audit did not pass')
    env = environment()
    expected_worker = dict(env, thread_environment={k: '1' for k in env['thread_environment']})
    protocol = dict(status="frozen_before_real_measurements", created_utc=datetime.now(timezone.utc).isoformat(),
                    config=config, source_sha256=source_inventory(config_path),
                    environment=env, expected_worker_environment=expected_worker, inputs=validations,
                    validation_sha256={name: digest(validation / name) for name in required},
                    original_source_blob_sha1=original_snapshot,
                    scope=config["scope"], raw_forcing_reaudited=False,
                    inherited_raw_provenance="original archive metadata and R3 protocol",
                    independent_holdout_available=False)
    save(protocol_path, protocol)
    print(f"Frozen {len(validations)} archives and {len(protocol['source_sha256'])} code/config files.", flush=True)


def verify(config_path, out):
    protocol = json.loads((out / "protocol.json").read_text())
    current = source_inventory(config_path)
    if current != protocol["source_sha256"]:
        changed = sorted(k for k in set(current) | set(protocol["source_sha256"])
                         if current.get(k) != protocol["source_sha256"].get(k))
        raise ValueError(f"frozen code/config mismatch: {changed}")
    if json.loads(Path(config_path).read_text()) != protocol["config"]:
        raise ValueError("frozen config mismatch")
    env = environment()
    for key, expected in protocol['expected_worker_environment'].items():
        if key != 'thread_environment' and env.get(key) != expected:
            raise ValueError(f'frozen execution environment mismatch: {key}')
    for name, expected in protocol['validation_sha256'].items():
        if digest(out / 'validation' / name) != expected:
            raise ValueError('frozen validation evidence changed')
    for scene in protocol['config']['scenes'].values():
        for path_key, hash_key in (('particle_path', 'particle_sha256'), ('metadata_path', 'metadata_sha256')):
            if digest(ROOT / scene[path_key]) != scene[hash_key]:
                raise ValueError('frozen input archive or metadata changed')
    return protocol


def exact_future_groups(grid, motion, belief, depth, budget):
    """Node-specific exact aggregation, never approximate trajectory clustering."""
    import numpy as np
    from asar_repro.motion import ParticleMotion
    trajectories = motion.cell_ids[depth+1:budget+1].T
    _, first, inverse = np.unique(trajectories, axis=0, return_index=True, return_inverse=True)
    weights = np.bincount(inverse, weights=belief, minlength=len(first))
    positive = np.flatnonzero(weights > 0)
    if not len(positive):
        # Keep one harmless zero-mass representative: ParticleMotion requires a
        # nonempty state vector, while the entire remaining cost is exactly 0.
        positive = np.array([0], dtype=int)
    first, weights = first[positive], weights[positive]
    members = [np.flatnonzero(inverse == k).tolist() for k in positive]
    # Representative IDs retain stable, unique original identities.
    grouped = ParticleMotion(motion.cell_ids[:, first], grid.size, motion.trajectory_ids[first],
                             special_bins=motion.bin_count-motion.size)
    return grouped, weights, members


def select_pairs(grid, motion, belief, depth, budget, top_groups, max_pairs):
    import numpy as np
    if max_pairs <= 0 or top_groups < 2:
        return [], []
    top = sorted(range(len(belief)), key=lambda i: (-float(belief[i]), i))[:top_groups]
    proposals = []
    for x, i in enumerate(top):
        for j in top[x+1:]:
            a, b = motion.cell_ids[depth+1:budget+1, i], motion.cell_ids[depth+1:budget+1, j]
            joint = (a < grid.size) & (b < grid.size)
            distance = (np.abs(a[joint]//grid.cols-b[joint]//grid.cols)
                        + np.abs(a[joint]%grid.cols-b[joint]%grid.cols))
            separation = float(distance.mean()) if distance.size else 0.
            proposals.append(((float(belief[i])+float(belief[j]))*separation,
                              min(i, j), max(i, j), separation))
    selected, occupied, records = [], set(), []
    for score, i, j, separation in sorted(proposals, key=lambda x: (-x[0], x[1], x[2])):
        if i in occupied or j in occupied:
            continue
        selected.append((i, j))
        occupied.update((i, j))
        records.append(dict(pair=[i, j], score=score, separation=separation,
                            mass=float(belief[i]+belief[j])))
        if len(selected) >= max_pairs:
            break
    return selected, records


def budgeted_incumbents(history, seed, seconds):
    """Exclude improvements which completed after the nominal deadline."""
    available = [seed] + [x for x in history if x['elapsed_s'] <= seconds]
    return min(available, key=lambda x: x['J']), available


def worker(config, task):
    import numpy as np
    from asar_repro.objective import score_path
    from asar_repro.research_search import search_research
    grid, cfg, scene, info = load_scene(config, task["scene"])
    actual_environment = environment()
    if any(value != '1' for value in actual_environment['thread_environment'].values()):
        raise ValueError('measured workers require one thread per numerical library')
    started, cpu = time.perf_counter(), time.process_time()
    phase = task["phase"]
    history = None
    if phase in ("wall", "work", "event_followup"):
        settings = config["search"]
        kwargs = {k: settings[k] for k in
                  ("guide_weight", "fast_guide", "portfolio", "cascade", "archive_candidates", "max_open")}
        initial_path = scene["initial_path"]
        allowance = task["seconds"]
        event_result = None
        if phase == "event_followup":
            from asar_repro.final_event_candidates import search_event_candidates
            event_offset = time.perf_counter()-started
            event_result = search_event_candidates(grid, **cfg, initial_path=initial_path,
                max_seconds=config["events"]["formal_followup_event_allowance_s"],
                max_candidates=config["events"]["max_candidates"], max_clusters=config["events"]["max_clusters"])
            initial_path = event_result.path
            allowance = max(0., task["seconds"]-(time.perf_counter()-started))
        offset = time.perf_counter()-started
        allowance = max(0., task['seconds']-offset)
        result = search_research(grid, **cfg, initial_path=initial_path,
            bound_mode=task["bound"], max_seconds=allowance,
            max_expansions=task.get("expansions"), **kwargs)
        result_data = asdict(result)
        history = result_data["incumbent_history"]
        for item in history:
            item['elapsed_s'] += offset
        if event_result is not None:
            result_data["event_stage"] = asdict(event_result)
            event_history = asdict(event_result)['incumbent_history']
            for item in event_history:
                item['elapsed_s'] += event_offset
            history = event_history + history
            result_data["incumbent_history"] = history
    elif phase == "events":
        from asar_repro.final_event_candidates import search_event_candidates
        initial = scene["initial_path"] if task["initial"] == "common_PT" else scene["reference_path"]
        offset = time.perf_counter()-started
        result = search_event_candidates(grid, **cfg, initial_path=initial,
            max_seconds=max(0., task["seconds"]-offset), max_candidates=config["events"]["max_candidates"],
            max_clusters=config["events"]["max_clusters"])
        result_data = asdict(result)
        history = result_data['incumbent_history']
        for item in history:
            item['elapsed_s'] += offset
    elif phase == "mip":
        from asar_repro.exact_repair import solve_exact_repair
        settings = config["mip"]
        result = solve_exact_repair(grid, **cfg, initial_path=scene["reference_path"],
            prefix_depth=settings["prefix_depth"], corridor_radius=settings["corridor_radius"],
            max_seconds=task["seconds"], max_memory_bytes=settings["managed_memory_bytes"],
            **settings["arms"][task["arm"]])
        result_data = asdict(result)
    elif phase == "pairs":
        from asar_repro.final_pair_bound import partition_pair_bound
        from asar_repro.stdc_heuristic import STDCHeuristic
        settings = config["pairs"]
        reference = score_path(grid, scene["reference_path"], **cfg, record_beliefs=True)
        depth = task["depth"]
        belief, vertex = reference.beliefs[depth], scene["reference_path"][depth]
        bound = STDCHeuristic(grid, budget=cfg["budget"], q=cfg["q"], motion=cfg["motion"])
        tic = time.perf_counter()
        ordinary = bound(vertex, depth, belief)
        ordinary_s = time.perf_counter()-tic
        grouped, weights, members = exact_future_groups(grid, cfg["motion"], belief, depth, cfg["budget"])
        pairs, selection = select_pairs(grid, grouped, weights, depth, cfg["budget"],
                                         settings["top_groups"], settings["max_pairs"])
        preparation_s = time.perf_counter()-started
        result = partition_pair_bound(grid, vertex=vertex, depth=depth,
            budget=cfg["budget"], q=cfg["q"], motion=grouped, belief=weights,
            pairs=pairs, max_seconds=max(0., task["seconds"]-preparation_s),
            max_memory_bytes=settings["managed_memory_bytes"])
        result_data = asdict(result)
        if result.full_stdc_bound is not None and abs(result.full_stdc_bound-ordinary) > config["tolerance"]:
            raise AssertionError("exact aggregation changed full STDC")
        future_upper = float(reference.J-reference.g[depth])
        result_data.update(original_stdc_bound=ordinary, original_stdc_wall_s=ordinary_s,
            preparation_wall_s=preparation_s, current_mass=float(belief.sum()),
            current_prefix_cost=float(reference.g[depth]), reference_suffix_J=future_upper,
            group_count=len(weights), group_members_original_columns=members,
            group_members_original_ids=[[clean(cfg["motion"].trajectory_ids[i]) for i in group] for group in members],
            group_weights=weights, pair_selection=selection,
            selected_current_mass=sum(x["mass"] for x in selection),
            interval_closure_fraction=None if result.bound is None or future_upper <= ordinary else
                max(0., result.bound-ordinary)/(future_upper-ordinary),
            bound_scope="global root" if depth == 0 else "conditional on this fixed prefix",
            global_search_certified=False)
    else:
        raise ValueError(f"unknown task phase: {phase}")
    elapsed, cpu_s = time.perf_counter()-started, time.process_time()-cpu
    result_data["measured_algorithm_wall_s"] = elapsed
    result_data["measured_cpu_s"] = cpu_s
    result_data["budget_overshoot_s"] = max(0., elapsed-task["seconds"])
    if history is not None:
        # A cooperative timer can return an improvement just after the nominal
        # deadline. Preserve it, but use only on-time incumbents for fair-budget
        # quality and time-to-target. The common archived seed exists at t=0.
        result_data['returned_path'] = result_data['path']
        result_data['returned_J'] = result_data['J']
        result_data['returned_Pd'] = result_data['Pd']
        initial_key = 'reference_path' if task.get('initial') == 'historical_reference' else 'initial_path'
        j_key = 'reference_J' if initial_key == 'reference_path' else 'PT_J'
        pd_key = 'reference_Pd' if initial_key == 'reference_path' else 'PT_Pd'
        seed = dict(path=scene[initial_key], J=scene[j_key], Pd=scene[pd_key], elapsed_s=0., source='preloaded_seed')
        chosen, on_time = budgeted_incumbents(history, seed, task['seconds'])
        result_data.update(path=chosen['path'], J=chosen['J'], Pd=chosen['Pd'],
                           strict_budget_selection=True,
                           post_deadline_incumbents=sum(x['elapsed_s'] > task['seconds'] for x in history))
    if phase != "pairs":
        replay = score_path(grid, result_data["path"], **cfg)
        if abs(replay.J-result_data["J"]) > config["tolerance"] or abs(replay.pd_final-result_data["Pd"]) > config["tolerance"]:
            raise AssertionError("independent final original replay mismatch")
        result_data["final_original_replay"] = dict(J=replay.J, Pd=replay.pd_final, passed=True)
    if history is not None:
        result_data["time_to_targets_s"] = {}
        for name, factor in config["search"]["quality_targets"].items():
            threshold = scene["reference_J"]*factor
            reached = [x["elapsed_s"] for x in on_time if x["J"] <= threshold+config["tolerance"]]
            result_data["time_to_targets_s"][name] = min(reached) if reached else None
    return dict(task=task, scene_info=info, worker_environment=actual_environment, result=clean(result_data))


def task_key(task):
    return "__".join(str(task[k]) for k in
                     ("phase", "scene", "bound", "arm", "initial", "depth", "seconds", "rep") if k in task)


def run_task(config, config_path, out, task):
    import psutil
    folder = out / "runs" / task_key(task)
    if (folder / "record.json").exists():
        record = json.loads((folder / "record.json").read_text())
        if record["task"] != task or record["protocol_sha256"] != digest(out / "protocol.json"):
            raise ValueError("resume record conflicts with frozen task/protocol")
        print("resume", task_key(task), flush=True)
        return
    folder.mkdir(parents=True, exist_ok=True)
    save(folder / "task.json", task)
    env = dict(os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    command = [sys.executable, str(Path(__file__)), "--stage", "worker",
               "--config", str(config_path), "--output", str(out), "--task", str(folder / "task.json")]
    begun, peak, reason = time.perf_counter(), 0, None
    with (folder / "stdout.log").open("w") as stdout, (folder / "stderr.log").open("w") as stderr:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr, env=env, cwd=ROOT)
        monitor = psutil.Process(process.pid)
        while process.poll() is None:
            try:
                rss = monitor.memory_info().rss + sum(p.memory_info().rss for p in monitor.children(recursive=True))
                peak = max(peak, rss)
                if rss > config["watchdog"]["rss_bytes"]:
                    reason = "process_rss_watchdog"
                if time.perf_counter()-begun > task["seconds"]+config["watchdog"]["extra_seconds"]:
                    reason = "process_wall_watchdog"
                if reason:
                    for p in monitor.children(recursive=True):
                        p.kill()
                    process.kill()
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            time.sleep(config["watchdog"]["poll_seconds"])
        process.wait()
    raw = folder / "raw_result.json"
    data = json.loads(raw.read_text()) if raw.exists() else None
    record = dict(task=task, protocol_sha256=digest(out / "protocol.json"),
                  exit_code=process.returncode, watchdog_reason=reason,
                  worker_wall_s=time.perf_counter()-begun, peak_process_rss_bytes=peak,
                  status="recorded" if process.returncode == 0 and data is not None else "blocked",
                  raw_result_sha256=digest(raw) if raw.exists() else None)
    save(folder / "record.json", record)
    result = {} if data is None else data.get("result", {})
    print(task_key(task), record["status"], result.get("status"),
          "J", result.get("J"), "wall", round(record["worker_wall_s"], 3), flush=True)


def tasks(config, stage):
    scenes = list(config["scenes"])
    if stage == "benchmark":
        settings = config["search"]
        for seconds in settings["wall_budgets_s"]:
            for rep in range(settings["repetitions"]):
                for ix, scene in enumerate(scenes):
                    arms = settings["bounds"]
                    offset = (rep+ix) % len(arms)
                    for bound in arms[offset:]+arms[:offset]:
                        yield dict(phase="wall", scene=scene, bound=bound, seconds=seconds, rep=rep)
        for scene in scenes:
            for bound in settings["bounds"]:
                yield dict(phase="work", scene=scene, bound=bound,
                    seconds=settings["fixed_work_safety_seconds"],
                    expansions=settings["fixed_work_expansions"], rep=0)
    elif stage == "events":
        for scene in scenes:
            for initial in config["events"]["initial_routes"]:
                yield dict(phase="events", scene=scene, initial=initial, seconds=config["events"]["seconds"], rep=0)
    elif stage == "pairs":
        for scene in scenes:
            T = config["scenes"][scene]["mission"]["budget"]
            for f in config["pairs"]["prefix_fractions"]:
                yield dict(phase="pairs", scene=scene, depth=int(T*f),
                           seconds=config["pairs"]["seconds_per_node"], rep=0)
    elif stage == "mip":
        setting = config["mip"]
        arms = list(setting["arms"])
        for rep in range(setting["repetitions"]):
            ordered = arms if rep % 2 == 0 else list(reversed(arms))
            for arm in ordered:
                yield dict(phase="mip", scene=setting["scene"], arm=arm,
                           seconds=setting["seconds_per_run"], rep=rep)


def records(out):
    rows = []
    protocol_hash = digest(out / 'protocol.json')
    expected_environment = json.loads((out / 'protocol.json').read_text())['expected_worker_environment']
    for path in sorted((out / "runs").glob("*/record.json")):
        record = json.loads(path.read_text())
        if record['protocol_sha256'] != protocol_hash:
            raise ValueError('saved run belongs to a different protocol')
        raw = path.parent / "raw_result.json"
        row = {"record": record, "task": record["task"], "run_directory": str(path.parent.relative_to(out))}
        if raw.exists():
            if digest(raw) != record["raw_result_sha256"]:
                raise ValueError("saved result hash mismatch")
            payload = json.loads(raw.read_text())
            if payload['task'] != record['task']:
                raise ValueError('saved run task mismatch')
            if payload['worker_environment'] != expected_environment:
                raise ValueError('saved run environment mismatch')
            row["result"] = payload.get("result", {})
        rows.append(row)
    return rows


def event_followup(config, config_path, out):
    existing = records(out)
    expected = {task_key(t) for t in tasks(config, 'events')}
    completed = {task_key(r['task']) for r in existing if r['task']['phase'] == 'events'
                 and r['record']['status'] == 'recorded' and 'J' in r.get('result', {})}
    if not expected.issubset(completed):
        save(out / 'event_followup_gate.json', dict(status='incomplete', missing=sorted(expected-completed)))
        raise ValueError('event diagnostic stage incomplete; cannot determine follow-up gate')
    promising = sorted({r["task"]["scene"] for r in existing
        if r["task"]["phase"] == "events" and r["task"]["scene"] in config["primary_scenes"]
        and r['record']['status'] == 'recorded'
        and r.get("result", {}).get("J", math.inf) < config["scenes"][r["task"]["scene"]]["reference_J"]-config["tolerance"]})
    save(out / "event_followup_gate.json", dict(promising_scenes=promising,
         status="triggered" if promising else "not_triggered", rule=config["events"]["formal_followup_trigger"]))
    if not promising:
        print("Event formal follow-up not triggered; no extra scans.", flush=True)
        return
    for scene in config["scenes"]:
        for rep in range(config["events"]["formal_followup_repetitions"]):
            run_task(config, config_path, out, dict(phase="event_followup", scene=scene,
                bound=config["events"]["formal_followup_continuation_bound"],
                seconds=config["events"]["formal_followup_seconds"], rep=rep))


def summarize(config, out):
    rows = records(out)
    grouped = {}
    for row in rows:
        t = row["task"]
        if t["phase"] not in ("wall", "work", "event_followup"):
            continue
        key = (t["phase"], t["scene"], t["bound"], t["seconds"])
        grouped.setdefault(key, []).append(row)
    comparisons = []
    for key, group in sorted(grouped.items()):
        valid = [r["result"] for r in group if r["record"]["status"] == "recorded" and "J" in r.get("result", {})]
        summary = dict(zip(("phase", "scene", "bound", "seconds"), key))
        expected_runs = (config['search']['repetitions'] if key[0] == 'wall' else
                         config['events']['formal_followup_repetitions'] if key[0] == 'event_followup' else
                         config['search']['fixed_work_repetitions'])
        summary.update(total_runs=len(group), valid_runs=len(valid), expected_runs=expected_runs,
                       missing_runs=max(0, expected_runs-len(group)), blocked_runs=len(group)-len(valid))
        for metric in ("J", "Pd", "expanded", "generated", "pruned", "peak_open", "measured_algorithm_wall_s", "measured_cpu_s", "budget_overshoot_s"):
            vals = [r[metric] for r in valid if metric in r]
            if vals:
                summary[metric] = dict(median=statistics.median(vals), min=min(vals), max=max(vals))
        summary["targets"] = {}
        for name in config["search"]["quality_targets"]:
            reached = [r["time_to_targets_s"][name] for r in valid if r.get("time_to_targets_s", {}).get(name) is not None]
            summary["targets"][name] = dict(reached=len(reached), total=expected_runs,
                censored_valid_runs=len(valid)-len(reached),
                median_reached_s=statistics.median(reached) if reached else None,
                all_reached=len(reached) == expected_runs)
        summary["peak_process_rss_bytes"] = max(r["record"]["peak_process_rss_bytes"] for r in group)
        summary["stat_medians"] = {k: statistics.median([r["stats"][k] for r in valid if k in r.get("stats", {})])
            for k in ("guide_calls", "guide_wall_s", "bound_calls", "bound_wall_s", "work_expanded", "cheap_pruned", "bound_pruned")
            if any(k in r.get("stats", {}) for r in valid)}
        comparisons.append(summary)
    decision = {"quality_screen_pass": False, "runtime_screen_pass": False,
                "independent_validation": "not_triggered", "per_scene": {},
                "scope": "same frozen archives; no cross-scene generality or optimality proof"}
    complete = True
    for name in config["primary_scenes"]:
        selected = {r["bound"]: r for r in comparisons if r["phase"] == "wall" and r["scene"] == name and r["seconds"] == 5.0}
        if set(selected) != set(config["search"]["bounds"]) or any(r.get("valid_runs") != config["search"]["repetitions"] for r in selected.values()):
            complete = False
            continue
        stdc, zero, mass = (selected[k] for k in ("stdc_lb", "zero", "mass_lb"))
        best = min(zero["J"]["median"], mass["J"]["median"])
        rel = (best-stdc["J"]["median"])/best
        target = config["decision"]["time_target"]
        times = {k: r["targets"][target] for k, r in selected.items()}
        time_ok = all(t["all_reached"] for t in times.values())
        ratios = {k: times["stdc_lb"]["median_reached_s"]/times[k]["median_reached_s"]
                  for k in ("zero", "mass_lb")} if time_ok else {}
        decision["per_scene"][name] = dict(quality_relative_gain=rel,
            no_quality_regression=rel >= -1e-8, target_time_ratios=ratios,
            runtime_pass=time_ok and all(v <= 1-config["decision"]["time_relative_reduction"] for v in ratios.values()) and rel >= -1e-8)
    if complete:
        per_scene = list(decision["per_scene"].values())
        decision["quality_screen_pass"] = all(v["no_quality_regression"] for v in per_scene) and any(v["quality_relative_gain"] >= config["decision"]["quality_relative_improvement"] for v in per_scene)
        decision["runtime_screen_pass"] = all(v["runtime_pass"] for v in per_scene)
        decision["recommendation"] = "independent_holdout_required" if decision["quality_screen_pass"] or decision["runtime_screen_pass"] else "pause_STDC_centric_performance_tuning"
        if decision["recommendation"] == "independent_holdout_required":
            decision["independent_validation"] = "blocked_missing_independent_archive"
    else:
        decision["recommendation"] = "incomplete_measurements"
    events = [r for r in rows if r["task"]["phase"] == "events"]
    pairs = [r for r in rows if r["task"]["phase"] == "pairs"]
    mip = [r for r in rows if r["task"]["phase"] == "mip"]
    decision["event_strict_reference_witnesses"] = [r["run_directory"] for r in events if r['record']['status'] == 'recorded' and r.get("result", {}).get("J", math.inf) < config["scenes"][r["task"]["scene"]]["reference_J"]-config["tolerance"]]
    decision['event_primary_witnesses'] = [r['run_directory'] for r in events
        if r['task']['scene'] in config['primary_scenes'] and r['run_directory'] in decision['event_strict_reference_witnesses']]
    decision["pair_root_screen_passes"] = [r["task"]["scene"] for r in pairs if r['record']['status'] == 'recorded' and r.get('result', {}).get('status') == 'completed' and r["task"]["depth"] == 0 and r["task"]["scene"] in config["primary_scenes"] and (r.get("result", {}).get("interval_closure_fraction") or 0) >= config["decision"]["pair_gap_closure_fraction"]]
    event_gains = []
    for name in config['primary_scenes']:
        follow = [r for r in comparisons if r['phase'] == 'event_followup' and r['scene'] == name]
        base = [r for r in comparisons if r['phase'] == 'wall' and r['scene'] == name and r['seconds'] == 5.0 and r['bound'] == 'mass_lb']
        if (len(follow) == len(base) == 1
                and follow[0]['valid_runs'] == config['events']['formal_followup_repetitions']
                and base[0]['valid_runs'] == config['search']['repetitions']):
            j = base[0]['J']['median']
            event_gains.append((j-follow[0]['J']['median'])/j)
    decision['event_formal_screen_pass'] = (len(event_gains) == len(config['primary_scenes'])
        and min(event_gains) >= -1e-8 and max(event_gains) >= config['decision']['quality_relative_improvement'])
    if decision['event_formal_screen_pass']:
        decision['independent_validation'] = 'blocked_missing_independent_archive'
    decision['pair_next_step'] = 'limited_integration_test_would_be_needed' if decision['pair_root_screen_passes'] else 'not_triggered'
    save(out / "summary.json", dict(comparisons=comparisons, decision=decision,
        events=events, pairs=pairs, mip=mip, total_runs=len(rows),
        blocked_runs=[r["run_directory"] for r in rows if r["record"]["status"] != "recorded" or r.get('result', {}).get('status') == 'blocked']))
    print(json.dumps(decision, ensure_ascii=False, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, choices=["freeze", "benchmark", "events", "pairs", "mip", "event_followup", "summarize", "worker"])
    parser.add_argument("--config", type=Path, default=ROOT / "configs/stdc_final_assessment.json")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/stdc_final_assessment_20261125")
    parser.add_argument("--task", type=Path)
    args = parser.parse_args()
    args.config, args.output = args.config.resolve(), args.output.resolve()
    config = json.loads(args.config.read_text())
    if args.stage == "freeze":
        freeze(config, args.config, args.output)
        return
    verify(args.config, args.output)
    if args.stage == "worker":
        task = json.loads(args.task.read_text())
        try:
            result = worker(config, task)
        except Exception:
            save(args.task.parent / "worker_error.json", dict(task=task, traceback=traceback.format_exc()))
            raise
        save(args.task.parent / "raw_result.json", result)
    elif args.stage == "summarize":
        summarize(config, args.output)
    elif args.stage == "event_followup":
        event_followup(config, args.config, args.output)
    else:
        for task in tasks(config, args.stage):
            run_task(config, args.config, args.output, task)


if __name__ == "__main__":
    main()
