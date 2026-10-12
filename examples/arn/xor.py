#!/usr/bin/env python3
"""Run the XOR environment with the ARN controller.

Build the ARN programs first with
``cargo build --release -p arn_controller -p arn_genetics``.
Then run this script from the repository root (or invoke it by path). The
experiment runs until interrupted with Ctrl-C.
"""

import argparse
import json
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import grpc

from npc_maker import diagnostics_pb2, diagnostics_pb2_grpc


BODY_TYPE = "xor"


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _connect(address, process, timeout):
    channel = grpc.insecure_channel(address)
    ready = grpc.channel_ready_future(channel)
    deadline = time.monotonic() + timeout
    while True:
        if process.poll() is not None:
            channel.close()
            raise RuntimeError(
                f"npc-server exited during startup (status {process.returncode})")
        try:
            ready.result(timeout=0.25)
            return channel
        except grpc.FutureTimeoutError:
            if time.monotonic() >= deadline:
                channel.close()
                raise RuntimeError("timed out waiting for npc-server")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--duration", type=float, default=0,
                        help="stop after this many seconds (default: run until Ctrl-C)")
    parser.add_argument("--temperature", type=float, default=1.0,
                        help="ARN controller temperature (default: %(default)s)")
    args = parser.parse_args()
    if args.duration < 0:
        parser.error("duration must not be negative")
    if args.temperature < 0:
        parser.error("temperature must not be negative")

    here = Path(__file__).resolve().parent
    repo = here.parents[1]
    controller = repo / "target" / "release" / "arn_controller"
    genetics = repo / "target" / "release" / "arn_genetics"
    missing = [str(program) for program in (controller, genetics)
               if not program.is_file()]
    if missing:
        parser.error("ARN programs are not built; run: cargo build --release "
                     "-p arn_controller -p arn_genetics")

    config = {
        "name": "XOR with the ARN controller",
        # "environment": [sys.executable, str(repo / "examples" / "xor" / "xor.py")],
        "environment": [str(repo / "target" / "release" / "xor")],
        "evolution": "npc-evo -p 10 -r oldest -s normalized=1".split(),
        "organisms": [{
            "body_type": BODY_TYPE,
            "genetics": [str(genetics), "--inputs", "2", "--outputs", "1",
                         "--duplications", "12",
                         "--temperature", str(args.temperature)],
            "controller": [str(controller), "--temperature", str(args.temperature)],
        }],
    }

    with tempfile.TemporaryDirectory(prefix="npc-arn-xor-") as directory:
        directory = Path(directory)
        config_path = directory / "experiment.json"
        config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        address = f"127.0.0.1:{_free_port()}"
        print(f"Starting npc-server on {address}", flush=True)
        server = subprocess.Popen([
            "npc-server.py", "--listen", address,
            str(config_path), str(directory / "server-data"),
        ])
        channel = None
        try:
            channel = _connect(address, server, 30)
            diagnostics = diagnostics_pb2_grpc.DiagnosticsStub(channel)
            organism = diagnostics_pb2.Organism(body_type=BODY_TYPE)
            started = time.monotonic()
            next_report = 0.0
            while args.duration == 0 or time.monotonic() - started < args.duration:
                if server.poll() is not None:
                    raise RuntimeError(
                        f"npc-server exited (status {server.returncode})")
                deaths = diagnostics.DeathCount(organism).count
                best = diagnostics.MaximumScore(organism).score
                if time.monotonic() >= next_report:
                    print(f"{deaths} evaluations, maximum score {best:.6f}", flush=True)
                    next_report = time.monotonic() + 1.0
                time.sleep(0.1)
        except KeyboardInterrupt:
            pass
        finally:
            if channel is not None:
                channel.close()
            if server.poll() is None:
                server.send_signal(signal.SIGINT)
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.terminate()
                server.wait(timeout=5)


if __name__ == "__main__":
    main()
