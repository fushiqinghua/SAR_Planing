import numpy as np
import pytest
from asar_repro.grid import GridGraph
from asar_repro.motion import ParticleMotion,MatrixMotion
from asar_repro.research_particle import ParticleGuide
from asar_repro.sparse_particle_guide import SparseParticleGuide

@pytest.mark.parametrize("seed",range(20))
def test_every_depth_vertex_and_choices_equal_reference(seed):
    rng=np.random.default_rng(52000+seed);grid=GridGraph(3,4);T=6;N=13
    motion=ParticleMotion(rng.integers(0,grid.size+3,size=(T+1,N)),grid.size,np.arange(N))
    q=rng.choice([0.,.3,.78,1.],size=grid.size)
    fast=ParticleGuide(grid,budget=T,q=q,motion=motion)
    sparse=SparseParticleGuide(grid,budget=T,q=q,motion=motion,max_cache_bytes=48)
    for depth in range(T+1):
        for vertex in range(grid.size):
            belief=rng.random(N)*rng.choice([0.,.1,1.],size=N)/N;original=belief.copy()
            a=[];b=[]
            x=fast(vertex,depth,belief,choices=a);y=sparse(vertex,depth,belief,choices=b)
            assert x==pytest.approx(y,abs=1e-12,rel=0)
            assert a==b
            np.testing.assert_array_equal(original,belief)
            assert sparse.cache_info()["cache_bytes"]<=48

@pytest.mark.parametrize("cache",[0,4,1024])
@pytest.mark.parametrize("q",[0.,1.])
def test_empty_cells_ties_special_bins_and_zero_weights(cache,q):
    grid=GridGraph(3,4);T=4
    cells=np.array([[12,13,14,11]]*(T+1))
    motion=ParticleMotion(cells,grid.size,[21,8,3,4])
    a=ParticleGuide(grid,budget=T,q=q,motion=motion)
    b=SparseParticleGuide(grid,budget=T,q=q,motion=motion,max_cache_bytes=cache)
    for p in (np.zeros(4),np.array([.2,.3,.5,0.]),np.array([.2,.3,.4,.1])):
        for v in range(grid.size):
            ca=[];cb=[]
            assert a(v,0,p,choices=ca)==pytest.approx(b(v,0,p,choices=cb),abs=1e-12,rel=0)
            assert ca==cb
    assert b.cache_info()["cache_bytes"]<=cache

def test_matrix_fallback_same_value_and_choices():
    grid=GridGraph(2,2);motion=MatrixMotion.identity(4);p=np.array([.1,.2,.3,.4])
    a=ParticleGuide(grid,budget=4,q=.78,motion=motion)
    b=SparseParticleGuide(grid,budget=4,q=.78,motion=motion)
    ca=[];cb=[]
    assert a(0,0,p,choices=ca)==b(0,0,p,choices=cb)
    assert ca==cb and b.cache_info()["fallback"]

def test_time_zero_is_not_observed():
    grid=GridGraph(1,3)
    motion=ParticleMotion(np.array([[0],[1],[2]]),3,[99])
    guide=SparseParticleGuide(grid,budget=2,q=1.,motion=motion)
    choices=[]
    assert guide(0,0,[1.],choices=choices)==0.
    assert choices==[1,0]  # after detection all weights zero, lowest radius ID

def test_cache_eviction_does_not_change_tie_order():
    grid=GridGraph(3,3);motion=ParticleMotion(np.tile(np.arange(9),(5,1)),9,np.arange(9))
    guide=SparseParticleGuide(grid,budget=4,q=.5,motion=motion,max_cache_bytes=36)
    reference=ParticleGuide(grid,budget=4,q=.5,motion=motion)
    for v in (0,8,4,0,8):
        x=[];y=[]
        assert guide(v,0,np.ones(9)/9,choices=x)==reference(v,0,np.ones(9)/9,choices=y)
        assert x==y
    assert guide.cache_info()["evictions"]>0

@pytest.mark.parametrize("bad",[-1,float("nan")])
def test_invalid_cache_budget_rejected(bad):
    grid=GridGraph(1,2);motion=ParticleMotion(np.zeros((2,1),dtype=int),2,[1])
    with pytest.raises((ValueError,TypeError)):
        SparseParticleGuide(grid,budget=1,q=.78,motion=motion,max_cache_bytes=bad)

