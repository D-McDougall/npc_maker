import pytest
import grpc

from npc_maker import genetics_pb2
from npc_maker.genetics import Genetics
from npc_maker.individual import Individual


class AbortError(Exception):
    def __init__(self, code, details):
        super().__init__(details)
        self.code = code
        self.details = details


class Context:
    def abort(self, code, details):
        raise AbortError(code, details)


class TestGenetics(Genetics):
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.received_parents = None

    def reproduce(self, parents):
        self.received_parents = parents
        if self.error:
            raise self.error
        return self.result if self.result is not None else Individual()


def test_reproduce_allows_founder_without_genetic_fields():
    service = TestGenetics()
    response = service.Reproduce(genetics_pb2.ReproduceRequest(), Context())

    child = Individual.from_proto(response.child)
    assert child.name
    assert child.genome is None
    assert child.epigenome is None
    assert child.phenome is None
    assert service.received_parents == []


def test_reproduce_wraps_parent_protobufs():
    parent = Individual()
    parent.name = "parent"
    request = genetics_pb2.ReproduceRequest()
    request.parents.add().CopyFrom(parent.to_proto())

    service = TestGenetics()
    service.Reproduce(request, Context())

    assert len(service.received_parents) == 1
    assert isinstance(service.received_parents[0], Individual)
    assert service.received_parents[0].name == "parent"


def test_reproduce_maps_value_error_to_invalid_argument():
    service = TestGenetics(error=ValueError("invalid genome"))

    with pytest.raises(AbortError) as error:
        service.Reproduce(genetics_pb2.ReproduceRequest(), Context())

    assert error.value.code == grpc.StatusCode.INVALID_ARGUMENT
    assert error.value.details == "invalid genome"


def test_reproduce_rejects_non_individual_return():
    service = TestGenetics(result=object())

    with pytest.raises(AbortError) as error:
        service.Reproduce(genetics_pb2.ReproduceRequest(), Context())

    assert error.value.code == grpc.StatusCode.INTERNAL


def test_reproduce_rejects_empty_child_name():
    child = Individual()
    child.name = ""
    service = TestGenetics(result=child)

    with pytest.raises(AbortError) as error:
        service.Reproduce(genetics_pb2.ReproduceRequest(), Context())

    assert error.value.code == grpc.StatusCode.INTERNAL
