#!/usr/bin/env python3

import sys
import matplotlib.pyplot as plt
import numpy as np
from run_nk import run_nk

eval_limit = 500

samples = 2

seed_matrix = [87654]

test_matrix = [
    (100, 4, "-p 20 -s normalized=1 --parents 1"),
    (100, 4, "-p 20 -s normalized=1 --parents 2"),
]

colors = 'rbgypkc'

def main():
    for i, (n, k, evo_args) in enumerate(test_matrix):
        traces = []
        for seed in seed_matrix:
            for _iteration in range(samples):
                evolution = ['npc-evo'] + evo_args.split()
                trace = run_nk(n=n, k=k, seed=seed, evolution=evolution, death_limit=eval_limit)
                evals, scores = zip(*trace)
                plt.plot(evals, scores, color=colors[i % len(colors)], label=evo_args)
                scores = resample(evals, scores, grid)
                traces.append(scores)
    plt.show()


# Log-spaced to capture dynamics of early progress.
grid = np.unique(np.round(np.geomspace(100, eval_limit, 60)).astype(int))

def resample(evals, scores, grid):
    """LOCF onto `grid`. NaN where the trace has no observation yet."""
    evals, scores = np.asarray(evals), np.asarray(scores)
    idx = np.searchsorted(evals, grid, side="right") - 1   # last sample with e_i <= g
    out = np.where(idx >= 0, scores[np.clip(idx, 0, None)], np.nan)
    return out


if __name__ == "__main__":
    sys.exit(main())
