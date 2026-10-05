"""
Integration test for npc-player program.
"""

import contextlib
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

grpc = pytest.importorskip("grpc")

from npc_maker import evolution_pb2, evolution_pb2_grpc
from npc_maker.individual import Individual


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextlib.contextmanager
def player_server(directory, selection="random"):
    """
    Run npc-player with the given replay directory.

    Yields a gRPC Evolution service stub.
    """
    port = _free_port()

    command = [
        "npc-player",
        str(directory),
        selection,
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    channel = grpc.insecure_channel(f"127.0.0.1:{port}")

    try:
        try:
            grpc.channel_ready_future(channel).result(timeout=10)
        except grpc.FutureTimeoutError:
            stdout, stderr = process.communicate(timeout=1)
            pytest.fail(
                "npc-player did not start:\n"
                f"stdout:\n{stdout.decode()}\n"
                f"stderr:\n{stderr.decode()}")

        yield evolution_pb2_grpc.EvolutionStub(channel)

    finally:
        channel.close()
        process.terminate()

        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)


def test_player():
    population = tempfile.TemporaryDirectory()
    population_path = Path(population.name)

    individuals = []
    for score in range(13):
        indiv = Individual()
        indiv.score = score
        individuals.append(indiv)

    names = {individual.name for individual in individuals}

    paths = []
    for individual in individuals:
        paths.append(individual.save(population_path))

    # Pause so that an accidental rewrite would be visible even on filesystems
    # with relatively coarse timestamps.
    time.sleep(0.01)

    timestamps_before = {path: path.stat().st_mtime_ns for path in paths}

    with player_server(population_path) as player:

        for _ in range(2 * len(individuals)):
            response = player.Spawn(evolution_pb2.SpawnRequest())

            assert len(response.parents) == 1
            individual = response.parents[0]

            assert individual.metadata.name in names

            player.Death(evolution_pb2.DeathRequest(individual=individual))

    timestamps_after = {path: path.stat().st_mtime_ns for path in paths}
    assert timestamps_after == timestamps_before
