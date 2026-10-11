#!/usr/bin/env python3
"""
Smoke test for the XOR environment with a known-good controller.
"""

import argparse
import json
import signal
import socket
import subprocess
import sys
import tempfile
import time
from concurrent import futures
from pathlib import Path

import grpc

from npc_maker import controller_pb2, controller_pb2_grpc
from npc_maker import diagnostics_pb2, diagnostics_pb2_grpc


class XorController(controller_pb2_grpc.ControllerServicer):
    """
    Minimal controller that returns a logical function of its two inputs.
    """
    def __init__(self, function="xor"):
        self.function = function

    def Session(self, requests, context):
        inputs = [0.0, 0.0]
        for request in requests:
            command = request.WhichOneof("command")
            if command == "reset":
                inputs = [0.0, 0.0]
            elif command == "set_inputs":
                for value in request.set_inputs.inputs:
                    if value.id < 2:
                        inputs[value.id] = value.number
            elif command == "get_outputs":
                left, right = bool(inputs[0]), bool(inputs[1])
                result = float({
                    "xor": left != right,
                    "and": left and right,
                    "or": left or right,
                    "nand": not (left and right),
                    "nor": not (left or right),
                    "eq": left == right,
                }[self.function])
                yield controller_pb2.ControllerResponse(
                    request_id=request.request_id,
                    outputs=[controller_pb2.IoValue(
                        id=output_id, number=result)
                        for output_id in request.get_outputs.ids],
                )


def _run_controller():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--controller", action="store_true")
    parser.add_argument("--listen", required=True)
    parser.add_argument("function", nargs="?", default="xor",
                        choices=("xor", "and", "or", "nand", "nor", "eq"))
    args = parser.parse_args()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    controller_pb2_grpc.add_ControllerServicer_to_server(
        XorController(args.function), server)
    server.add_insecure_port(args.listen)
    server.start()
    server.wait_for_termination()


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _run_smoke_test(environment_command, label, function):
    controller = Path(__file__).resolve()
    server_script = "npc-server.py"

    config = {
        "name": f"XOR smoke test ({label})",
        "environment": environment_command,
        "controller": [sys.executable, str(controller), "--controller", function],
        "organisms": [{"body_type": "xor"}],
    }

    with tempfile.TemporaryDirectory(prefix="npc-xor-") as directory:
        directory = Path(directory)
        config_path = directory / "experiment.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        address = f"127.0.0.1:{_free_port()}"
        server = subprocess.Popen([
            str(server_script),
            "--listen", address,
            str(config_path), str(directory / "server-data"),
        ])
        channel = grpc.insecure_channel(address)
        try:
            ready = grpc.channel_ready_future(channel)
            deadline = time.monotonic() + 30
            while True:
                if server.poll() is not None:
                    raise AssertionError(
                        f"npc-server exited during startup ({server.returncode})")
                try:
                    ready.result(timeout=0.25)
                    break
                except grpc.FutureTimeoutError:
                    if time.monotonic() >= deadline:
                        raise AssertionError("timed out waiting for npc-server")

            diagnostics = diagnostics_pb2_grpc.DiagnosticsStub(channel)
            organism = diagnostics_pb2.Organism(body_type="xor")
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if server.poll() is not None:
                    raise AssertionError(
                        f"npc-server exited during XOR run ({server.returncode})")
                if diagnostics.DeathCount(organism).count:
                    break
                time.sleep(0.05)
            else:
                raise AssertionError("XOR environment did not finish an evaluation")

            return diagnostics.MaximumScore(organism).score
        finally:
            channel.close()
            if server.poll() is None:
                server.send_signal(signal.SIGINT)
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.terminate()
                server.wait(timeout=5)


def test_smoke():
    xor_dir = Path(__file__).resolve().parent
    repo = xor_dir.parents[1]
    python_environment = [sys.executable, str(xor_dir / "xor.py")]
    rust_environment = [str(repo / "target" / "release" / "xor")]

    assert _run_smoke_test(python_environment, "python", "xor") == 16
    assert _run_smoke_test(rust_environment, "rust", "xor") == 16

    assert _run_smoke_test(python_environment, "python", "or") == 9
    assert _run_smoke_test(rust_environment, "rust", "or") == 9

    assert _run_smoke_test(python_environment, "python", "eq") == 0
    assert _run_smoke_test(rust_environment, "rust", "eq") == 0


if __name__ == "__main__":
    if "--controller" in sys.argv[1:]:
        _run_controller()
    else:
        test_smoke()
