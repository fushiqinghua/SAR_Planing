"""Algorithm-2-equivalent particle guide using occupied cells and bounded geometry."""
from collections import OrderedDict
import numpy as np
from .belief import sensor_probabilities, undetected_mass
from .grid import integer
from .motion import ParticleMotion
from .research_particle import ParticleGuide

class SparseParticleGuide:
    """Only sorting: no admissibility or epsilon certificate is implied.

    Bincount visits particle weights in original order, and ties still select
    the smallest cell ID in the paper distance-radius set. Empty zero-mass
    cells remain eligible. Cached geometry is belief-independent and bounded.
    """
    def __init__(self, grid, *, budget, q, motion, max_cache_bytes=4*2**20):
        self.grid,self.motion=grid,motion
        self.budget=integer(budget,"budget")
        self.limit=integer(max_cache_bytes,"max_cache_bytes")
        self.q=sensor_probabilities(q,grid.size).copy()
        if grid.size!=motion.size:raise ValueError("grid/motion size mismatch")
        self.mode="paper_greedy"
        self.used_fallback=not isinstance(motion,ParticleMotion)
        self._fallback=ParticleGuide(grid,budget=budget,q=q,motion=motion) if self.used_fallback else None
        self.cache=OrderedDict();self.bytes=0;self.peak=0
        self.hits=self.misses=self.evictions=0;self.frames=[]
        if self.used_fallback:return
        motion.check_horizon(budget)
        allcells=np.unique(motion.cell_ids[:budget+1])
        self.occupied=allcells[allcells<grid.size]
        self.rows=(self.occupied//grid.cols).astype(np.int32)
        self.cols=(self.occupied%grid.cols).astype(np.int32)
        for cells in motion.cell_ids[:budget+1]:
            unique,inverse=np.unique(cells,return_inverse=True)
            n=int(np.searchsorted(unique,grid.size))
            mapping=np.searchsorted(self.occupied,unique[:n]).astype(np.int32)
            self.frames.append((unique,inverse,n,mapping,self.q[unique[:n]].copy()))
        for frame in self.frames:
            for x in frame:
                if isinstance(x,np.ndarray):x.setflags(write=False)
        for x in (self.q,self.occupied,self.rows,self.cols):x.setflags(write=False)
    def _distances(self,vertex):
        found=self.cache.get(vertex)
        if found is not None:
            self.hits+=1;self.cache.move_to_end(vertex);return found
        self.misses+=1
        r,c=self.grid.coordinates(vertex)
        distances=np.abs(self.rows-r)+np.abs(self.cols-c)
        distances.setflags(write=False)
        if distances.nbytes<=self.limit:
            while self.cache and self.bytes+distances.nbytes>self.limit:
                _,old=self.cache.popitem(last=False);self.bytes-=old.nbytes;self.evictions+=1
            self.cache[vertex]=distances;self.bytes+=distances.nbytes;self.peak=max(self.peak,self.bytes)
        return distances
    def __call__(self,vertex,depth,belief,*,choices=None):
        if self._fallback is not None:return self._fallback(vertex,depth,belief,choices=choices)
        r,c=self.grid.coordinates(vertex);depth=integer(depth,"depth")
        if depth>self.budget:raise ValueError("depth exceeds budget")
        if depth==self.budget:return 0.
        weights=undetected_mass(belief,self.motion.state_size).copy()
        distances=self._distances(vertex);total=0.
        for t in range(depth+1,self.budget+1):
            unique,inverse,n,mapping,qvalues=self.frames[t]
            mass=np.bincount(inverse,weights=weights,minlength=len(unique))
            k=t-depth
            gains=np.where(distances[mapping]<=k,qvalues*mass[:n],-1.)
            index=int(np.argmax(gains)) if n else None
            if n and gains[index]>0:
                best=int(unique[index])
            else:
                # Lowest row then lowest column in the paper's radius superset.
                row=max(0,r-k);col=max(0,c-(k-(r-row)))
                best=row*self.grid.cols+col
            offsets=self.motion._offsets[t]
            members=self.motion._order[t,offsets[best]:offsets[best+1]]
            weights[members]*=1.-self.q[best]
            total+=float(weights.sum())
            if choices is not None:choices.append(best)
        return total
    def cache_info(self):
        if self.used_fallback:
            return dict(fallback=True,cache_bytes=0,cache_limit_bytes=self.limit,
                memory_scope="matrix fallback uses unchanged reference guide")
        arrays=[self.q,self.occupied,self.rows,self.cols]
        arrays += [x for frame in self.frames for x in frame if isinstance(x,np.ndarray)]
        return dict(fallback=False,cache_bytes=self.bytes,cache_peak_bytes=self.peak,
            cache_limit_bytes=self.limit,cache_entries=len(self.cache),hits=self.hits,
            misses=self.misses,evictions=self.evictions,
            fixed_array_bytes=sum(a.nbytes for a in arrays),
            occupied_cells=len(self.occupied),full_grid_vertices=self.grid.size,
            memory_scope="owned fixed arrays and retained distance cache; transient bincount/weights and Python/RSS separate",
            ordering_equivalence="paper radius, no greedy-step continuity, original-ID accumulation, lowest-cell ties")

