#!/usr/bin/env python3
"""Create and plot one random founder for the ARN XOR example."""

import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import grpc

from npc_maker import genetics_pb2, genetics_pb2_grpc
from npc_maker.individual import Individual


def main():
    repo = Path(__file__).resolve().parents[2]
    genetics = repo / "target" / "release" / "arn_genetics"
    controller = repo / "target" / "release" / "arn_controller"
    if not genetics.is_file() or not controller.is_file():
        raise SystemExit("Build ARN programs first: cargo build --release -p arn_controller -p arn_genetics")

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        address = f"127.0.0.1:{sock.getsockname()[1]}"
    server = subprocess.Popen([str(genetics), "--listen", address, "--inputs", "2",
                               "--outputs", "1", *sys.argv[1:]])
    try:
        with grpc.insecure_channel(address) as channel:
            grpc.channel_ready_future(channel).result(timeout=10)
            response = genetics_pb2_grpc.GeneticsStub(channel).Reproduce(
                genetics_pb2.ReproduceRequest())
        individual = Individual.from_proto(response.child)
        individual.body_type = "xor"
        individual.controller = [str(controller)]
        with tempfile.TemporaryDirectory(prefix="npc-") as directory:
            path = individual.save(Path(directory) / "individuals")
            subprocess.run([sys.executable, str(repo / "examples" / "xor" / "plot.py"), str(path)],
                           check=True)
    finally:
        server.terminate()
        server.wait()


if __name__ == "__main__":
    main()
