import datetime
import sys

import grpc
import pytest

from npc_maker.evolution import EvolutionClient, EvolutionServer
from npc_maker.individual import Individual


class ExampleEvolution(EvolutionServer):
    def __init__(self, mode="normal"):
        self.mode = mode
        self.deaths = []

    def spawn(self):
        if self.mode == "invalid-spawn":
            raise ValueError("invalid population")
        if self.mode == "wrong-sequence":
            return object()
        if self.mode == "wrong-parent":
            return [object()]
        if self.mode == "empty-name":
            parent = Individual()
            parent.name = ""
            return [parent]
        if self.mode == "empty":
            return []
        return self.deaths[-1:] or [self._parent("parent-a"), self._parent("parent-b")]

    def death(self, individual):
        if self.mode == "invalid-death":
            raise ValueError("invalid individual")
        if self.mode == "wrong-death-return":
            return object()
        self.deaths.append(individual)

    @staticmethod
    def _parent(name):
        parent = Individual()
        parent.name = name
        parent.genome = name.encode()
        return parent


def start_evolution(mode="normal"):
    return EvolutionClient([sys.executable, __file__, mode])


@pytest.fixture
def evolution():
    with start_evolution() as client:
        yield client


def test_spawn_returns_selected_parents(evolution):
    parents = evolution.spawn()

    assert [parent.name for parent in parents] == ["parent-a", "parent-b"]
    assert [parent.genome for parent in parents] == [b"parent-a", b"parent-b"]


def test_spawn_allows_no_parents():
    with start_evolution("empty") as evolution:
        assert evolution.spawn() == []


def test_death_sends_final_individual_record(evolution):
    individual = Individual()
    individual.name = "finished"
    individual.score = 12.5
    individual.telemetry["distance"] = "42"
    individual.epigenome = b"learned"
    individual.death_date = datetime.datetime(2026, 10, 15, tzinfo=datetime.UTC)

    evolution.death(individual)
    [received] = evolution.spawn()

    assert received.name == "finished"
    assert received.score == 12.5
    assert dict(received.telemetry) == {"distance": "42"}
    assert received.epigenome == b"learned"
    assert received.death_date == individual.death_date


@pytest.mark.parametrize(
    ("mode", "call", "details"),
    [
        ("invalid-spawn", lambda client: client.spawn(), "invalid population"),
        ("invalid-death", lambda client: client.death(Individual()), "invalid individual"),
    ],
)
def test_value_error_maps_to_invalid_argument(mode, call, details):
    with start_evolution(mode) as evolution:
        with pytest.raises(grpc.RpcError) as error:
            call(evolution)

    assert error.value.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert error.value.details() == details


@pytest.mark.parametrize("mode", ["wrong-sequence", "wrong-parent", "empty-name"])
def test_spawn_rejects_invalid_parents(mode):
    with start_evolution(mode) as evolution:
        with pytest.raises(grpc.RpcError) as error:
            evolution.spawn()

    assert error.value.code() == grpc.StatusCode.INTERNAL


def test_death_rejects_non_none_return():
    with start_evolution("wrong-death-return") as evolution:
        with pytest.raises(grpc.RpcError) as error:
            evolution.death(Individual())

    assert error.value.code() == grpc.StatusCode.INTERNAL


if __name__ == "__main__":
    listen_address = sys.argv[-1]
    mode = sys.argv[1]
    ExampleEvolution(mode).main(listen_address)
