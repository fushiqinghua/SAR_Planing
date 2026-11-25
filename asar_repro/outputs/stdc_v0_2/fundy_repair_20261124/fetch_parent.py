from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import urllib.request, hashlib, json, time
root=Path(__file__).resolve().parent
url='https://noaa-nos-ofs-pds.s3.amazonaws.com/gomofs/netcdf/2025/02/14/gomofs.t00z.20250214.2ds.n005.nc'
size=171414927;chunk=8*1024*1024
def fetch(start):
 end=min(size,start+chunk)-1;p=root/f'part_{start}.bin'
 if p.exists() and p.stat().st_size==end-start+1:return p
 for attempt in range(3):
  try:
   req=urllib.request.Request(url,headers={'Range':f'bytes={start}-{end}'})
   with urllib.request.urlopen(req,timeout=60) as r:
    assert r.status==206 and r.headers['Content-Range']==f'bytes {start}-{end}/{size}'
    data=r.read()
   assert len(data)==end-start+1;p.write_bytes(data);print(start,'complete',flush=True);return p
  except Exception:
   if attempt==2:raise
 with p.open('rb'):pass
with ThreadPoolExecutor(max_workers=16) as pool:parts=list(pool.map(fetch,range(0,size,chunk)))
out=root/'verified_parent_n005.nc'
with out.open('wb') as f:
 for p in parts:f.write(p.read_bytes())
sha=hashlib.sha256(out.read_bytes()).hexdigest()
assert sha=='c2879d000da71de2509e5f5194130de8c063256dc9c784a443826474894a378e'
(root/'download.json').write_text(json.dumps(dict(url=url,sha256=sha,bytes=size,status='passed',method='HTTP Range; whole-file SHA matches B1 original parent'),indent=2))
print('verified',sha,flush=True)
