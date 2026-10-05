"""
Check that Python and Rust read and write the same individual file format,
by using the real `npc-evo` program, which is written in Rust.

Rust loads and saves individuals from its population directory
and returns them over gRPC, which lets this test see what Rust read from disk.
These tests are skipped if the `npc-evo` program or the grpc package is not available.
"""

import contextlib
import math
import socket
import subprocess
from pathlib import Path

import pytest

grpc = pytest.importorskip("grpc")

import npc_maker
from npc_maker import evolution_pb2, evolution_pb2_grpc, individual_pb2
from npc_maker.individual import Individual


def _find_npc_evo():
    repo = Path(__file__).resolve().parents[2]
    candidates = [
        repo / "target" / "release" / "npc-evo",
        Path(npc_maker.__file__).parent / "programs" / "npc-evo",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    pytest.skip("the npc-evo program has not been built, run `make`")


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextlib.contextmanager
def evolution_server(directory, *flags):
    """
    Run npc-evo with the given save directory, which it creates if needed
    and otherwise loads the saved population from.
    Extra command line flags are passed to npc-evo.
    Yields a gRPC stub for the Evolution service.
    """
    port = _free_port()
    log_path = Path(str(directory) + ".log")
    command = [str(_find_npc_evo()), str(directory), "--port", str(port), "-r", "growth", "--parents", "1", *flags]
    with open(log_path, "ab") as log:
        process = subprocess.Popen(command, stderr=log)
        channel = grpc.insecure_channel(f"127.0.0.1:{port}")
        try:
            try:
                grpc.channel_ready_future(channel).result(timeout=10)
            except grpc.FutureTimeoutError:
                pytest.fail(f"npc-evo did not start, exit code {process.poll()}:\n{log_path.read_text()}")
            yield evolution_pb2_grpc.EvolutionStub(channel)
        finally:
            channel.close()
            process.terminate()
            process.wait(timeout=10)


def test_python_reads_what_rust_wrote(tmp_path, make_full_individual):
    sent = make_full_individual(score=5.0, ascension=None)
    with evolution_server(tmp_path / "evo") as evolution:
        evolution.Death(evolution_pb2.DeathRequest(individual=sent.to_proto()))
    # Rust assigned the ascension, and saved the individual to its population.
    expected = individual_pb2.Individual()
    expected.CopyFrom(sent.to_proto())
    expected.metadata.ascension = 0
    population = tmp_path / "evo" / "pop"
    loaded = Individual.load(population / sent.name)
    assert loaded.to_proto() == expected
    assert loaded.ascension == 0
    assert loaded.birth_date == sent.birth_date
    assert loaded.extra["nested"]["flag"] is True
    assert Individual.load_dir(population) == [expected.metadata]


def test_python_reads_empty_blobs_the_way_rust_wrote_them(tmp_path, make_full_individual):
    sent = make_full_individual(phenome=None, epigenome=None, ascension=None)
    with evolution_server(tmp_path / "evo") as evolution:
        evolution.Death(evolution_pb2.DeathRequest(individual=sent.to_proto()))
    loaded = Individual.load(tmp_path / "evo" / "pop" / sent.name)
    assert loaded.genome == b"genome data"
    assert loaded.epigenome == b""
    assert loaded.phenome == b""


def test_rust_reads_what_python_wrote(tmp_path, make_full_individual):
    evo_dir = tmp_path / "evo"
    # Let Rust create its own save directory, with one individual in the population.
    seed = make_full_individual(score=1.0, ascension=None)
    with evolution_server(evo_dir) as evolution:
        evolution.Death(evolution_pb2.DeathRequest(individual=seed.to_proto()))
    # Python adds another individual to the population directory.
    # It has the highest score, which makes it the preferred parent.
    mine = make_full_individual(score=1000.0, ascension=7)
    mine.save(evo_dir / "pop")
    # Rust loads the whole population from disk and picks parents from it.
    with evolution_server(evo_dir) as evolution:
        parents = {}
        for _ in range(20):
            for parent in evolution.Spawn(evolution_pb2.SpawnRequest()).parents:
                parents[parent.metadata.name] = parent
    assert mine.name in parents, f"Rust never returned the individual that Python saved: {sorted(parents)}"
    assert parents[mine.name] == mine.to_proto()


@pytest.mark.parametrize("score", [math.inf, -math.inf, math.nan], ids=["inf", "-inf", "nan"])
def test_rust_reads_non_finite_scores(tmp_path, make_full_individual, score):
    """
    Python writes these as the strings "Infinity", "-Infinity", and "NaN",
    as the protobuf-JSON specification says. Rust must read the correct value.

    The reverse is not tested, because Rust currently writes `null` for
    non-finite numbers and so it loses the score.
    """
    evo_dir = tmp_path / "evo"
    seed = make_full_individual(score=1.0, ascension=None)
    with evolution_server(evo_dir) as evolution:
        evolution.Death(evolution_pb2.DeathRequest(individual=seed.to_proto()))
    mine = make_full_individual(score=score, ascension=7)
    mine.save(evo_dir / "pop")
    # Select parents uniformly at random so that every score is eventually returned.
    with evolution_server(evo_dir, "-s", "random") as evolution:
        parents = {}
        for _ in range(100):
            for parent in evolution.Spawn(evolution_pb2.SpawnRequest()).parents:
                parents[parent.metadata.name] = parent
    assert mine.name in parents, f"Rust never returned the individual that Python saved: {sorted(parents)}"
    metadata = parents[mine.name].metadata
    assert metadata.HasField("score")
    if math.isnan(score):
        assert math.isnan(metadata.score)
    else:
        assert metadata.score == score
