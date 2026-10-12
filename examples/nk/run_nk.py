#!/usr/bin/env python3
"""
Run an evolutionary experiment on a seeded binary NK landscape.

This starts an npc-server using the NK environment and monoploid binary
genetics, then monitors the experiment through the server's Diagnostics
service. The experiment returns the maximum score at regular intervals.
The experiment ends when it reaches either the death-limit or the time-limit.

Usage: test_nk.py [-n N] [-k K] [--seed SEED] [--death-limit COUNT] [--evolution COMMAND]
"""

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

from npc_maker.diagnostics import Diagnostics

N                  = 10
K                  = 4
SEED               = 0x5EED
BODY_TYPE          = "nk"
DEATH_LIMIT        = 10_000
EVOLUTION          = "npc-evo -p 100 -s normalized=1".split()
TIMEOUT            = 300.0  # Five minutes.
POLL_INTERVAL      = 0.1
STARTUP_TIMEOUT    = 30.0


def _make_config(n, k, seed, evolution):
    here = Path(__file__).parent
    return {
        "name": f"NK experiment (N={n}, K={k}, seed={seed}, evo={EVOLUTION})",
        "environment": [
            sys.executable,
            str(here / "nk_environment.py"),
            str(n),
            str(k),
            str(seed),
        ],
        "organisms": [
            {
                "body_type": BODY_TYPE,
                "genetics": [
                    sys.executable,
                    str(here / "nk_genetics.py"),
                    str(n),
                ],
                "evolution": evolution,
            }
        ],
    }


def _monitor(diagnostics, started, death_limit):
    """
    Poll until death or limit are reached.
    """
    last_report = 0.0
    score_report = []
    while True:
        deaths = diagnostics.death_count(BODY_TYPE)
        best = diagnostics.maximum_score(BODY_TYPE)

        score_report.append([deaths, best])

        elapsed = time.monotonic() - started
        summary = f"{deaths} dead, maximum score {best:.6f}, {elapsed:.1f}s"

        # Check success first in case both limits are crossed between polls.
        if deaths > death_limit:
            break
        if elapsed > TIMEOUT:
            break

        if time.monotonic() - last_report >= 1.0:
            print(f"  {summary}", flush=True)
            last_report = time.monotonic()
        time.sleep(POLL_INTERVAL)

    return score_report


def run_nk(n=N, k=K, seed=SEED, death_limit=DEATH_LIMIT, evolution=EVOLUTION):
    """
    Run the NK experiment and return a trace of pairs of (death-count, max-score).
    """
    with tempfile.TemporaryDirectory(prefix="npc-nk-") as directory:
        directory = Path(directory)
        config_file = directory / "experiment.json"
        config_file.write_text(
            json.dumps(_make_config(n, k, seed, evolution), indent=2),
            encoding="utf-8",
        )

        started = time.monotonic()
        with Diagnostics(config_file, directory / "server-data",
                         timeout=STARTUP_TIMEOUT) as diagnostics:
            print(f"Starting npc-server on {diagnostics.address}", flush=True)
            score_report = _monitor(diagnostics, started, death_limit)

        return score_report


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("-n", type=int, default=N,
                        help="number of genes (default: %(default)s)")
    parser.add_argument("-k", type=int, default=K,
                        help="number of interacting genes per locus "
                             "(default: %(default)s)")
    parser.add_argument("--seed", type=lambda value: int(value, 0), default=SEED,
                        help="landscape seed (default: %(default)#x)")
    parser.add_argument("--death-limit", type=int, default=DEATH_LIMIT,
                        help="fail when deaths exceed this (default: %(default)s)")
    parser.add_argument("--evolution", default=" ".join(EVOLUTION),
                        help="evolution service command (default: %(default)s)")
    args = parser.parse_args()

    if args.n <= 0:
        parser.error("N must be greater than zero")
    if not 0 <= args.k < args.n:
        parser.error("K must be in the range [0, N)")
    if args.death_limit < 0:
        parser.error("death limit must not be negative")

    run_nk(args.n, args.k, args.seed, args.death_limit, args.evolution.split())


if __name__ == "__main__":
    sys.exit(main())
