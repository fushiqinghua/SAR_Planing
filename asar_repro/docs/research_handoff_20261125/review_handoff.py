"""Read-only evidence checks, then build the additive publication inventory."""
from pathlib import Path
import json,re,subprocess
from run_optimization_validation import ROOT,sources,read,digest
from run_exact_repair_validation import preserved

out=Path(__file__).resolve().parent
repo=ROOT.parent
cmd=['git','-c',f'safe.directory={repo.as_posix()}']
names=subprocess.check_output(cmd+['ls-files','--others','--exclude-standard','-z'],cwd=repo).decode().split('\0')
included=[];excluded=[]
for n in filter(None,names):
    p=repo/n
    if not p.is_file() or 'research_handoff_20261125' in n:continue
    assert n.startswith('asar_repro/'),n
    e=dict(path=n,bytes=p.stat().st_size,sha256=digest(p))
    if p.suffix.lower() in ('.nc','.bin','.zip') or p.stat().st_size>95*2**20:
        e['reason']='local raw forcing/download archive; omitted, not deleted';excluded.append(e)
    else:included.append(e)
assert sources()==read(ROOT/'outputs/stdc_v0_2/exact_repair_r3_20261124/freeze.json')['source_sha256']
keep=preserved();verified=0
for folder in ('exact_repair_20261124','exact_repair_r2_20261124','exact_repair_r3_20261124'):
    base=ROOT/'outputs/stdc_v0_2'/folder
    for f in read(base/'artifact_manifest.json')['files']:
        assert digest(base/f['path'])==f['sha256'],f
        verified+=1
v=read(ROOT/'outputs/stdc_v0_2/exact_repair_r3_20261124/validation_summary.json')
assert v['stages']['full_tests']['test_counts']==dict(tests=1228,errors=0,failures=0,skipped=0)
assert v['stages']['new_tests']['test_counts']['tests']==114
for stage,count in (('oracle',192),('warm_oracle',576)):
    assert v['stages'][stage]['audit']['repair_checks']==count
    assert v['stages'][stage]['audit']['max_objective_error']==0
rows=read(ROOT/'outputs/stdc_v0_2/exact_repair_r3_20261124/diagnostic/comparison.json')['rows']
assert len(rows)==6
for x in rows:
    assert x['delta_J']==0 and x['delta_Pd']==0
    assert x['physical_direction_unverified']==(x['scene']=='bay_of_fundy')
text=(ROOT/'RESEARCH_HANDOFF_20261125.md').read_text(encoding='utf-8')
links=re.findall(r'\]\(([^)]+)\)',text)
for link in links:
    if 'research_handoff_20261125' not in link:assert (ROOT/link).is_file(),link
patterns=[r'ghp_[A-Za-z0-9]{30,}',r'github_pat_[A-Za-z0-9_]{40,}',r'AKIA[A-Z0-9]{16}',r'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----']
hits=[]
for f in included:
    p=repo/f['path']
    if p.suffix.lower() in ('.py','.json','.md','.txt','.diff','.ps1','.jsonl','.csv'):
        content=p.read_text(encoding='utf-8',errors='replace')
        if any(re.search(x,content) for x in patterns):hits.append(f['path'])
assert not hits,hits
def save(name,obj):(out/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
save('upload_inventory.json',dict(included=included,excluded=excluded,total_bytes=sum(x['bytes'] for x in included),scope='New research files; handoff metadata separately included; tracked pytest cache changes not staged'))
save('review.json',dict(status='passed',date='2026-11-25',frozen_artifacts_verified=verified,source_matches_R3=True,preservation=keep,full_tests=v['stages']['full_tests']['test_counts'],cold_oracle=192,warm_oracle=576,real_comparison_rows=6,all_delta_J_Pd_zero=True,local_links_checked=len(links),credential_pattern_hits=hits,limitations=['No scientific experiments rerun in documentation/upload turn','Selected credential patterns only, not universal secret detection','Raw forcing/download chunks excluded; portable replay needs path and protocol adaptation']))
selected=[x['path'] for x in included]+[p.relative_to(repo).as_posix() for p in out.iterdir() if p.is_file()]
(repo.parent/'stdc_handoff_stage_paths.tmp').write_bytes(b''.join(n.encode()+b'\0' for n in selected))
print(dict(included=len(selected),excluded=len(excluded),MiB=sum(x['bytes'] for x in included)/2**20,verified=verified,review='passed'))
