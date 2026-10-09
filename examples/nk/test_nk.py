#!/usr/bin/env python3

import sys
import matplotlib.pyplot as plt
from run_nk import run_nk

eval_limit = 1000

seed_matrix = [87654]

test_matrix = [
    (10, 1, "-p 20 -s normalized=1".split()),
]

def main():
    for (n, k, evo_args) in test_matrix:
        traces = []
        for seed in seed_matrix:
            evolution = ['npc-evo'] + evo_args
            score_trace = run_nk(n=n, k=k, seed=seed, evolution=evolution, death_limit=eval_limit)
            traces.append(score_trace)
            print(score_trace)


if __name__ == "__main__":
    sys.exit(main())
