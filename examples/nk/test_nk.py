import pytest
from run_nk import run_nk

SKIP_EXTRA_TESTS = True

SEED = 42

# With K=0, the NK environment should be very easy to solve.

def test_n10_k0():
    trace = run_nk(n=10, k=0, seed=SEED, death_limit=1000,
        evolution="npc-evo -p 20 -s normalized=1 --parents 2".split())
    assert trace[-1][1] >= 0.98

@pytest.mark.skipif(SKIP_EXTRA_TESTS, reason="long running test")
def test_n100_k0():
    trace = run_nk(n=100, k=0, seed=SEED, death_limit=1000,
        evolution="npc-evo -p 20 -s normalized=1 --parents 2".split())
    assert trace[-1][1] >= 0.98

@pytest.mark.skipif(SKIP_EXTRA_TESTS, reason="long running test")
def test_n1000_k0():
    trace = run_nk(n=1000, k=0, seed=SEED, death_limit=2000,
        evolution="npc-evo -p 20 -s normalized=1 --parents 2".split())
    assert 0.98 > trace[-1][1] >= 0.90

# With K=3, the NK environment should be much more difficult.

@pytest.mark.skipif(SKIP_EXTRA_TESTS, reason="long running test")
def test_n10_k4():
    trace = run_nk(n=10, k=3, seed=SEED, death_limit=1000,
        evolution="npc-evo -p 20 -s normalized=1 --parents 2".split())
    assert 0.90 > trace[-1][1] >= 0.70

@pytest.mark.skipif(SKIP_EXTRA_TESTS, reason="long running test")
def test_n100_k4():
    trace = run_nk(n=100, k=3, seed=SEED, death_limit=1000,
        evolution="npc-evo -p 20 -s normalized=1 --parents 2".split())
    assert 0.90 > trace[-1][1] >= 0.70

@pytest.mark.skipif(SKIP_EXTRA_TESTS, reason="long running test")
def test_n1000_k4():
    trace = run_nk(n=1000, k=3, seed=SEED, death_limit=2000,
        evolution="npc-evo -p 20 -s normalized=1 --parents 2".split())
    assert 0.75 > trace[-1][1] >= 0.60
