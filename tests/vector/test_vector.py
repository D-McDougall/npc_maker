#!/usr/bin/env python3
"""
Run the vector optimization experiment.

This starts an npc-server running the vector environment, and then monitors the
experiment through the server's Diagnostics service. The experiment ends when
either:

  * The maximum score rises above SCORE_THRESHOLD. This is success.
  * The number of dead individuals rises above DEATH_LIMIT. This is failure.

Failure also covers the server exiting on its own, and exceeding TIMEOUT, which
is a safety net so that a stuck experiment can not hang forever. In every case
the server and all of its subprocesses are shut down before returning.

Note that no evolution service is configured, so every individual is a fresh
random guess and this experiment is a random search. The default 2-dimensional
problem is easy enough that random search usually succeeds, but with 3 or more
dimensions it is not expected to.

Requires a POSIX system, and `npc-server.py` must be on the PATH.

Usage: test_vector.py [--dimension N] [--seed SEED]
       pytest test_vector.py
"""

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import grpc

from npc_maker import diagnostics_pb2, diagnostics_pb2_grpc

DIMENSION        = 2
SEED             = 0x5EED
BODY_TYPE        = "vector"
SCORE_THRESHOLD  = 0.99     # Success if the maximum score rises above this.
DEATH_LIMIT      = 10_000   # Failure if the number of dead rises above this.
TIMEOUT          = 300.0    # Failure if the experiment takes longer (seconds).
POLL_INTERVAL    = 0.5      # Time between diagnostic polls (seconds).
STARTUP_TIMEOUT  = 60.0     # Time allowed for the server to start (seconds).
SHUTDOWN_TIMEOUT = 15.0     # Time allowed for each shutdown step (seconds).


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _make_config(dimension, seed):
    here = Path(__file__).parent
    return {
        "name": "vector test",
        "description": f"Vector optimization experiment ({dimension}, {seed})",
        "environment": [
            sys.executable,
            str(here / "vector_environment.py"),
            str(dimension),
            str(seed),
        ],
        "organisms": [
            {
                "body_type": BODY_TYPE,
                "genetics": [
                    sys.executable,
                    str(here / "vector_genetics.py"),
                    str(dimension),
                ],
                # Evolution is intentionally omitted. The NPC server will
                # request founder individuals from the genetics service.
            }
        ],
    }


def _connect(address, server):
    """
    Connect to the Diagnostics service. Returns a (channel, stub) pair.

    Raises RuntimeError if the server exits or does not start in time.
    """
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


def _monitor(diagnostics, server, started):
    """
    Poll the diagnostics until the experiment succeeds or fails.

    Returns a (success, message) pair.
    """
    organism = diagnostics_pb2.Organism(body_type=BODY_TYPE)
    last_report = 0.0
    while True:
        try:
            deaths = diagnostics.DeathCount(organism).count
            best = diagnostics.MaximumScore(organism).score
        except grpc.RpcError as error:
            # Allow a moment for the exit status to become available.
            time.sleep(0.25)
            if server.poll() is not None:
                return False, (
                    f"npc-server exited unexpectedly (status {server.returncode})")
            return False, f"diagnostics request failed: {error.code().name}"

        elapsed = time.monotonic() - started
        # The maximum score is -inf until the first score is reported.
        summary = f"{deaths} dead, maximum score {best:.6f}, {elapsed:.1f}s"

        # Success is checked first, so if both limits are crossed within the
        # same poll then the experiment counts as a success.
        if best > SCORE_THRESHOLD:
            return True, f"maximum score exceeded {SCORE_THRESHOLD} ({summary})"
        if deaths > DEATH_LIMIT:
            return False, f"more than {DEATH_LIMIT} individuals died ({summary})"
        if elapsed > TIMEOUT:
            return False, f"timed out after {TIMEOUT:.0f}s ({summary})"

        if time.monotonic() - last_report >= 1.0:
            print(f"  {summary}", flush=True)
            last_report = time.monotonic()
        if server.poll() is not None:
            return False, (
                f"npc-server exited unexpectedly (status {server.returncode})")
        time.sleep(POLL_INTERVAL)


def _group_is_empty(group, timeout):
    """
    Wait up to timeout seconds for every process in a process group to exit.
    """
    deadline = time.monotonic() + timeout
    while True:
        try:
            os.killpg(group, 0)  # Signal 0 only checks that the group exists.
        except ProcessLookupError:
            return True
        if time.monotonic() > deadline:
            return False
        time.sleep(0.05)


def _shutdown(server):
    """
    Stop the server and everything it started. Returns a list of problems,
    which is empty if the shutdown was clean.

    The server is the leader of its own process group, which also contains the
    environment and genetics subprocesses. This allows the test to find any
    which the server fails to clean up.
    """
    problems = []
    group = server.pid  # The server is the process group leader.

    if server.poll() is None:
        # SIGINT makes the server stop its services and subprocesses and then
        # exit. SIGTERM would kill it without cleaning up its subprocesses.
        server.send_signal(signal.SIGINT)
        try:
            server.wait(timeout=SHUTDOWN_TIMEOUT)
        except subprocess.TimeoutExpired:
            problems.append("npc-server did not exit after SIGINT")
            server.terminate()
            try:
                server.wait(timeout=SHUTDOWN_TIMEOUT)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
        else:
            if server.returncode != 0:
                problems.append(f"npc-server exited with status {server.returncode}")

    # A server which was killed by a signal can not have cleaned up after
    # itself, and nothing else will either, so don't wait for it to.
    grace = 1.0 if server.returncode < 0 else SHUTDOWN_TIMEOUT
    if not _group_is_empty(group, grace):
        problems.append("subprocesses of npc-server were left running")
    # Safety net, so that nothing is ever leaked. This is a no-op if the group
    # is already empty.
    try:
        os.killpg(group, signal.SIGKILL)
    except ProcessLookupError:
        pass
    return problems


def run_vector(dimension=DIMENSION, seed=SEED):
    """
    Run the experiment. Returns a (success, message) pair.
    """
    with tempfile.TemporaryDirectory(prefix="npc-vector-") as directory:
        directory = Path(directory)
        config_file = directory / "experiment.json"
        config_file.write_text(
            json.dumps(_make_config(dimension, seed), indent=2),
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
            start_new_session=True,  # Own process group, see _shutdown()
        )

        channel = None
        try:
            started = time.monotonic()
            channel, diagnostics = _connect(address, server)
            success, message = _monitor(diagnostics, server, started)
        except RuntimeError as error:
            success, message = False, str(error)
        finally:
            # Always runs, including on KeyboardInterrupt.
            if channel is not None:
                channel.close()
            problems = _shutdown(server)

        if problems:
            # An unclean shutdown is a failure, even if the experiment itself
            # reached its goal.
            message += "; unclean shutdown: " + ", ".join(problems)
            success = False
        return success, message


def test_vector():
    success, message = run_vector()
    assert success, message


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dimension", type=int, default=DIMENSION,
                        help="number of target dimensions (default: %(default)s)")
    parser.add_argument("--seed", type=lambda s: int(s, 0), default=SEED,
                        help="seed used to generate the target (default: %(default)#x)")
    args = parser.parse_args()
    if args.dimension <= 0:
        parser.error("dimension must be greater than zero")

    success, message = run_vector(args.dimension, args.seed)
    print(f"{'SUCCESS' if success else 'FAILURE'}: {message}")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
