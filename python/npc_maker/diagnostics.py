"""
Start npc-server and check its diagnostics.
"""

import signal
import socket
import subprocess
import time
from pathlib import Path

import grpc

from . import diagnostics_pb2, diagnostics_pb2_grpc


def _free_address():
    """Return a loopback address with an available ephemeral port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return f"127.0.0.1:{sock.getsockname()[1]}"


class Diagnostics:
    """
    Manage an npc-server process and query its Diagnostics service.

    Args mirror the npc-server CLI: ``config`` and ``save_dir`` are required;
    ``verbose`` and ``listen`` are optional. If no address is supplied, a
    loopback address with an ephemeral port is selected automatically.

    The instance is a context manager so the server is always stopped and
    reaped when the context exits.
    """

    def __init__(self, config, save_dir, verbose=False, listen=None, timeout=30):
        self.config = Path(config)
        self.save_dir = Path(save_dir)
        self.verbose = bool(verbose)
        self.address = listen or _free_address()
        self.timeout = int(timeout)
        self.process = None
        self.channel = grpc.insecure_channel(self.address)

        command = ["npc-server.py"]
        if self.verbose:
            command.append("--verbose")
        command.extend(["--listen", self.address, str(self.config),
                        str(self.save_dir)])
        try:
            self.process = subprocess.Popen(command)
            ready = grpc.channel_ready_future(self.channel)
            deadline = time.monotonic() + self.timeout
            while True:
                if self.process.poll() is not None:
                    raise RuntimeError(
                        "npc-server exited during startup "
                        f"(status {self.process.returncode})")
                try:
                    ready.result(timeout=min(0.25, max(0, deadline - time.monotonic())))
                    break
                except grpc.FutureTimeoutError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("timed out waiting for npc-server")
            self.stub = diagnostics_pb2_grpc.DiagnosticsStub(self.channel)
        except BaseException:
            self.close()
            raise

    def _organism(self, body_type):
        return diagnostics_pb2.Organism(body_type=body_type)

    def living_count(self, body_type="") -> int:
        return self.stub.LivingCount(self._organism(body_type)).count

    def spawn_count(self, body_type="") -> int:
        return self.stub.SpawnCount(self._organism(body_type)).count

    def mate_count(self, body_type="") -> int:
        return self.stub.MateCount(self._organism(body_type)).count

    def score_count(self, body_type="") -> int:
        return self.stub.ScoreCount(self._organism(body_type)).count

    def telemetry_count(self, body_type="") -> int:
        return self.stub.TelemetryCount(self._organism(body_type)).count

    def death_count(self, body_type="") -> int:
        return self.stub.DeathCount(self._organism(body_type)).count

    def maximum_score(self, body_type="") -> float:
        return self.stub.MaximumScore(self._organism(body_type)).score

    def close(self):
        """Stop npc-server and release its gRPC channel."""
        if self.channel is not None:
            self.channel.close()
            self.channel = None
        if self.process is not None:
            if self.process.poll() is None:
                self.process.send_signal(signal.SIGINT)
                try:
                    self.process.wait(timeout=self.timeout)
                except subprocess.TimeoutExpired:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=self.timeout)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

