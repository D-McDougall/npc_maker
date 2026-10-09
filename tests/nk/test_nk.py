#!/usr/bin/env python3
"""Run an evolutionary experiment on a seeded binary NK landscape.

This starts an npc-server using the NK environment and monoploid binary
genetics, then monitors the experiment through the server's Diagnostics
service. The experiment succeeds when the maximum score rises above the score
limit and fails when the death limit or timeout is exceeded.

Usage: test_nk.py [--n N] [--k K] [--seed SEED]
                                [--score-limit SCORE] [--death-limit COUNT]
                                [--evoultion COMMAND]
       pytest test_nk.py
"""

import argparse
import json
import math
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import grpc

from npc_maker import diagnostics_pb2, diagnostics_pb2_grpc

N                  = 10
K                  = 4
SEED               = 0x5EED
BODY_TYPE          = "nk"
SCORE_LIMIT        = 0.9
DEATH_LIMIT        = 10_000
EVOLUTION          = "npc-evo -p 100".split()
TIMEOUT            = 300.0  # Five minutes.
POLL_INTERVAL      = 0.5
STARTUP_TIMEOUT    = 30.0
SHUTDOWN_TIMEOUT   = 3.0


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


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


def _connect(address, server):
    """Connect to Diagnostics, failing if the server exits or times out."""
    channel = grpc.insecure_channel(address)
    ready = grpc.channel_ready_future(channel)
    deadline = time.monotonic() + STARTUP_TIMEOUT
    while True:
        if server.poll() is not None:
            channel.close()
            raise RuntimeError(
                f"npc-server exited during startup (status {server.returncode})")
        try:
            ready.result(timeout=0.25)
            return channel, diagnostics_pb2_grpc.DiagnosticsStub(channel)
        except grpc.FutureTimeoutError:
            if time.monotonic() > deadline:
                channel.close()
                raise RuntimeError("timed out waiting for npc-server to start")


def _monitor(diagnostics, server, started, score_limit, death_limit):
    """Poll until the score, death, or time limit determines the outcome."""
    organism = diagnostics_pb2.Organism(body_type=BODY_TYPE)
    last_report = 0.0
    while True:
        try:
            deaths = diagnostics.DeathCount(organism).count
            best = diagnostics.MaximumScore(organism).score
        except grpc.RpcError as error:
            time.sleep(0.25)
            if server.poll() is not None:
                return False, (
                    f"npc-server exited unexpectedly (status {server.returncode})")
            return False, f"diagnostics request failed: {error.code().name}"

        elapsed = time.monotonic() - started
        summary = f"{deaths} dead, maximum score {best:.6f}, {elapsed:.1f}s"

        # Check success first in case both limits are crossed between polls.
        if best > score_limit:
            return True, f"maximum score exceeded {score_limit} ({summary})"
        if deaths > death_limit:
            return False, f"more than {death_limit} individuals died ({summary})"
        if elapsed > TIMEOUT:
            return False, f"timed out after {TIMEOUT:.0f}s ({summary})"

        if time.monotonic() - last_report >= 1.0:
            print(f"  {summary}", flush=True)
            last_report = time.monotonic()
        if server.poll() is not None:
            return False, (
                f"npc-server exited unexpectedly (status {server.returncode})")
        time.sleep(POLL_INTERVAL)


def _shutdown(server):
    """Best-effort stop of npc-server using portable subprocess operations."""
    problems = []
    if server.poll() is not None:
        if server.returncode != 0:
            problems.append(f"npc-server exited with status {server.returncode}")
        return problems

    # SIGINT gives npc-server a chance to shut down cleanly where supported.
    try:
        server.send_signal(signal.SIGINT)
    except (OSError, ValueError):
        pass
    graceful = False
    try:
        server.wait(timeout=SHUTDOWN_TIMEOUT)
        graceful = True
    except subprocess.TimeoutExpired:
        problems.append("npc-server did not exit after SIGINT")
        try:
            server.terminate()
        except OSError:
            pass
        try:
            server.wait(timeout=SHUTDOWN_TIMEOUT)
        except subprocess.TimeoutExpired:
            try:
                server.kill()
                server.wait(timeout=SHUTDOWN_TIMEOUT)
            except OSError:
                problems.append("could not force-stop npc-server")
    if graceful and server.returncode != 0:
        problems.append(f"npc-server exited with status {server.returncode}")
    return problems


def run_nk(n=N, k=K, seed=SEED, score_limit=SCORE_LIMIT,
           death_limit=DEATH_LIMIT, evolution=EVOLUTION):
    """Run the NK experiment and return a (success, message) pair."""
    with tempfile.TemporaryDirectory(prefix="npc-nk-") as directory:
        directory = Path(directory)
        config_file = directory / "experiment.json"
        config_file.write_text(
            json.dumps(_make_config(n, k, seed, evolution), indent=2),
            encoding="utf-8",
        )

        address = f"127.0.0.1:{_free_port()}"
        print(f"Starting npc-server on {address}", flush=True)
        server = subprocess.Popen(
            [
                "npc-server.py",
                "--listen", address,
                str(config_file),
                str(directory / "server-data"),
            ],
        )

        channel = None
        try:
            started = time.monotonic()
            channel, diagnostics = _connect(address, server)
            success, message = _monitor(
                diagnostics, server, started, score_limit, death_limit)
        except RuntimeError as error:
            success, message = False, str(error)
        finally:
            if channel is not None:
                channel.close()
            problems = _shutdown(server)

        if problems:
            message += "; unclean shutdown: " + ", ".join(problems)
            success = False
        return success, message


def test_monoploid():
    success, message = run_nk(n=100, k=4, seed=42,
        score_limit=0.75, death_limit=10000,
        evolution="npc-evo -p 100 -r generation -s normalized=1 --parents 1".split())
    assert success, message


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("-n", type=int, default=N,
                        help="number of genes (default: %(default)s)")
    parser.add_argument("-k", type=int, default=K,
                        help="number of interacting genes per locus "
                             "(default: %(default)s)")
    parser.add_argument("--seed", type=lambda value: int(value, 0), default=SEED,
                        help="landscape seed (default: %(default)#x)")
    parser.add_argument("--score-limit", type=float, default=SCORE_LIMIT,
                        help="succeed when maximum fitness rises above this "
                             "(default: %(default)s)")
    parser.add_argument("--death-limit", type=int, default=DEATH_LIMIT,
                        help="fail when deaths exceed this (default: %(default)s)")
    parser.add_argument("--evolution", default=" ".join(EVOLUTION),
                        help="evolution service command (default: %(default)s)")
    args = parser.parse_args()

    if args.n <= 0:
        parser.error("N must be greater than zero")
    if not 0 <= args.k < args.n:
        parser.error("K must be in the range [0, N)")
    if math.isnan(args.score_limit):
        parser.error("score limit must be a number")
    if args.death_limit < 0:
        parser.error("death limit must not be negative")

    success, message = run_nk(
        args.n, args.k, args.seed, args.score_limit, args.death_limit,
        args.evolution.split())
    print(f"{'SUCCESS' if success else 'FAILURE'}: {message}")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
