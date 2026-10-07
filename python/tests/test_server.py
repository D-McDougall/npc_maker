"""
Integration test for npc-server.

The server runs the test environment (environment.py), which exercises the
Environment service and checks the Diagnostics service against its own model.
The environment reports the outcome through a result file.

The server is told which address to listen on, so the test can also connect to
its Diagnostics service directly, and then shuts the server down with SIGINT
which must result in a successful exit status.
"""

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
from npc_maker.individual import Individual


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_npc_server_py():
    server_test_inner("npc-server.py")


def server_test_inner(server_program):
    with tempfile.TemporaryDirectory() as directory:
        directory = Path(directory)
        population = directory / "population"
        population.mkdir()

        # Create a small replay population for npc-player.
        for score in range(3):
            individual = Individual()
            individual.score = score
            individual.save(population)

        environment = Path(__file__).with_name("environment.py")
        result_file = directory / "result.json"
        config = {
            "name": "npc-server smoke test",
            "environment": [
                sys.executable,
                str(environment),
                "--result", str(result_file),
            ],
            "organisms": [
                {
                    "body_type": "test",
                    "evolution": [
                        "npc-player",
                        str(population),
                        "random",
                    ],
                },
            ],
        }

        config_file = directory / "experiment.json"
        config_file.write_text(json.dumps(config), encoding="utf-8")

        address = f"127.0.0.1:{_free_port()}"
        process = subprocess.Popen([
            server_program,
            "--verbose",
            "--listen", address,
            str(config_file), str(directory / "server-data"),
        ])

        try:
            # Wait for the environment to finish its checks.
            deadline = time.monotonic() + 120
            while not result_file.exists():
                if process.poll() is not None:
                    raise AssertionError(
                        f"npc-server exited unexpectedly with status {process.returncode}")
                if time.monotonic() > deadline:
                    raise AssertionError("timed out waiting for the environment")
                time.sleep(0.1)

            result = json.loads(result_file.read_text(encoding="utf-8"))
            assert result["ok"], result.get("error")

            # The run must have been non-trivial, or the checks prove little.
            counts = result["counts"]
            assert all(count > 0 for count in counts.values()), counts
            assert result["max_score"] is not None

            # The server should have survived the environment.
            assert process.poll() is None, (
                f"npc-server exited with status {process.returncode}")

            # The server must be serving on the address it was given, and what
            # it reports must still agree with what the environment did.
            organism = diagnostics_pb2.Organism(body_type="test")
            with grpc.insecure_channel(address) as channel:
                diagnostics = diagnostics_pb2_grpc.DiagnosticsStub(channel)
                assert diagnostics.SpawnCount(organism).count == counts["Spawn"]
                assert diagnostics.DeathCount(organism).count == counts["Death"]
                assert diagnostics.LivingCount(organism).count == result["living"]
                assert diagnostics.MaximumScore(organism).score == result["max_score"]

            # SIGINT is the clean way to stop the server.
            process.send_signal(signal.SIGINT)
            assert process.wait(timeout=30) == 0, (
                f"npc-server exited with status {process.returncode}")
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    test_server()
