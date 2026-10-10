#!/usr/bin/env python3

import sys
import matplotlib.pyplot as plt
import numpy as np
import pytest
from run_nk import run_nk

eval_limit = 1000

samples = 5

seed_matrix = [87654]

test_matrix = [

    # Works well
    (3, "-p 20 -s normalized=1 --parents 2"),
    (3, "-p 20 -r oldest -s ranked-exponential=3 --parents 2"),

    # Proportional does not work for this score function.
    (2, "-p 20 -s proportional --parents 2"),
    # Population is too big, slows down evolution
    (2, "-p 200 -s normalized=1 --parents 2"),
    # No selection pressure, replace worst only, monoploid genetics
    (2, "-p 20 -r worst -s random --parents 1"),

    # Does not work at all
    (1, "-p 20 -s random --parents 2"),
]

colors = 'rbgcmyk'


# Log-spaced to capture dynamics of early progress.
grid = np.unique(np.round(np.geomspace(100, eval_limit, 60)).astype(int))

def resample(evals, scores, grid):
    """LOCF onto `grid`. NaN where the trace has no observation yet."""
    evals, scores = np.asarray(evals), np.asarray(scores)
    idx = np.searchsorted(evals, grid, side="right") - 1   # last sample with e_i <= g
    out = np.where(idx >= 0, scores[np.clip(idx, 0, None)], np.nan)
    return out


def main(n=100, k=4, show=True):
    for seed in seed_matrix:
        median_scores = {}
        for i, (power, evo_args) in enumerate(test_matrix):
            traces = []
            for _iteration in range(samples):
                evolution = ['npc-evo'] + evo_args.split()
                trace = run_nk(n=n, k=k, seed=seed, evolution=evolution, death_limit=eval_limit)
                evals, scores = zip(*trace)
                plt.plot(evals, scores, color=colors[i % len(colors)], label=evo_args)
                scores = resample(evals, scores, grid)
                traces.append(scores)
            # Combine the traces into their median score at each grid-point.
            median_scores[i] = np.nanmedian(traces, axis=0)

        if show:
            plt.legend()
            plt.show()

        # Compare median scores to asses power of method.
        median_scores = {i: float(trace[-1]) for (i, trace) in median_scores.items()}
        print(f"Score              \tnpc-evo arguments")
        for i, i_score in median_scores.items():
            i_method = test_matrix[i][1]
            print(f"{i_score} \t{i_method}")
        for i, i_score in median_scores.items():
            i_power = test_matrix[i][0]
            for j in range(len(test_matrix)):
                if i == j: continue
                j_score = median_scores[j]
                j_power = test_matrix[i][0]
                if i_power > j_power:
                    assert i_score > j_score, f"evo power {test_matrix[i][1]} >> {test_matrix[j][1]}"


@pytest.mark.skip(reason="long running test")
def test_evo(show=False):
    main()

if __name__ == "__main__":
    sys.exit(main(show=True))
