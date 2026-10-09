#!/usr/bin/env python3
"""
Run an evolutionary experiment on a seeded binary NK landscape.

This starts an npc-server using the NK environment and monoploid binary
genetics, then monitors the experiment through the server's Diagnostics
service. The experiment returns the maximum score at regular intervals.
The experiment ends when it reaches either the death-limit or the time-limit.

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
DEATH_LIMIT        = 10_000
EVOLUTION          = "npc-evo -p 100 -s normalized=1".split()
TIMEOUT            = 300.0  # Five minutes.
POLL_INTERVAL      = 0.1
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


def _monitor(diagnostics, server, started, death_limit):
    """
    Poll until death or limit are reached.
    """
    organism = diagnostics_pb2.Organism(body_type=BODY_TYPE)
    last_report = 0.0
    score_report = []
    while True:
        try:
            deaths = diagnostics.DeathCount(organism).count
            best = diagnostics.MaximumScore(organism).score
        except grpc.RpcError as error:
            time.sleep(0.25)
            if server.poll() is not None:
                raise RuntimeError(
                    f"npc-server exited unexpectedly (status {server.returncode})")
            raise RuntimeError(f"diagnostics request failed: {error.code().name}")

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
        if server.poll() is not None:
            raise RuntimeError(
                f"npc-server exited unexpectedly (status {server.returncode})")
        time.sleep(POLL_INTERVAL)

    return score_report


def _shutdown(server):
    """
    Best-effort stop of npc-server using portable subprocess operations.
    """
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


def run_nk(n=N, k=K, seed=SEED, death_limit=DEATH_LIMIT, evolution=EVOLUTION):
    """
    Run the NK experiment and return a (success, message) pair.
    """
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
            success, message = _monitor(diagnostics, server, started, death_limit)
        finally:
            if channel is not None:
                channel.close()
            problems = _shutdown(server)
            if problems:
                raise RuntimeError("unclean shutdown: " + ", ".join(problems))

        if not success:
            raise ValueError(message)

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
