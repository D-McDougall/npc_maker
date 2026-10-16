import sys

import grpc
import pytest

from npc_maker.genetics import GeneticsClient, GeneticsServer
from npc_maker.individual import Individual


class ExampleGenetics(GeneticsServer):
    def __init__(self, mode="normal"):
        self.mode = mode

    def reproduce(self, parents):
        if self.mode == "invalid" and not parents:
            raise ValueError("invalid genome")
        if self.mode == "wrong-type":
            return object()
        if self.mode == "empty-name":
            child = Individual()
            child.name = ""
            return child
        if self.mode == "no-fields":
            return Individual()
        if not parents:
            child = Individual()
            child.name = "founder"
            child.genome = b"founder-genome"
            child.epigenome = b"founder-epigenome"
            child.phenome = b"founder-phenome"
            return child

        child = Individual.reproduce(parents)
        child.name = "offspring"
        child.genome = b"|".join(parent.genome or b"" for parent in parents)
        child.epigenome = b"offspring-epigenome"
        child.phenome = b"offspring-phenome"
        return child


def start_genetics(mode="normal"):
    return GeneticsClient([sys.executable, __file__, mode])


@pytest.fixture
def genetics():
    with start_genetics() as client:
        yield client


def test_reproduce_allows_founder_without_genetic_fields():
    # This checks the base server contract independently of the example
    # algorithm's optional genetic fields.
    with start_genetics("no-fields") as client:
        child = client.reproduce([])

    assert child.name
    assert child.genome is None
    assert child.epigenome is None
    assert child.phenome is None


def test_reproduce_founder_over_client_interface(genetics):
    child = genetics.reproduce([])

    assert child.name == "founder"
    assert child.genome == b"founder-genome"
    assert child.epigenome == b"founder-epigenome"
    assert child.phenome == b"founder-phenome"


def test_reproduce_wraps_parent_protobufs_and_returns_offspring(genetics):
    parent = Individual()
    parent.name = "parent"
    parent.generation = 2
    parent.genome = b"parent-genome"

    child = genetics.reproduce([parent])

    assert child.name == "offspring"
    assert child.generation == 3
    assert child.parents == ["parent"]
    assert child.genome == b"parent-genome"


def test_reproduce_combines_two_parents(genetics):
    parent_a = Individual()
    parent_a.name = "parent-a"
    parent_a.generation = 1
    parent_a.genome = b"a"
    parent_b = Individual()
    parent_b.name = "parent-b"
    parent_b.generation = 4
    parent_b.genome = b"b"

    child = genetics.reproduce([parent_a, parent_b])

    assert child.name == "offspring"
    assert child.generation == 5
    assert child.parents == ["parent-a", "parent-b"]
    assert child.genome == b"a|b"
    assert child.epigenome == b"offspring-epigenome"
    assert child.phenome == b"offspring-phenome"


def test_reproduce_maps_value_error_to_invalid_argument():
    with start_genetics("invalid") as genetics:
        with pytest.raises(grpc.RpcError) as error:
            genetics.reproduce([])

    assert error.value.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert error.value.details() == "invalid genome"


@pytest.mark.parametrize("mode", ["wrong-type", "empty-name"])
def test_reproduce_rejects_invalid_child_from_server(mode):
    with start_genetics(mode) as genetics:
        with pytest.raises(grpc.RpcError) as error:
            genetics.reproduce([])

    assert error.value.code() == grpc.StatusCode.INTERNAL


if __name__ == "__main__":
    listen_address = sys.argv[-1]
    mode = sys.argv[1]
    ExampleGenetics(mode).main(listen_address)
